import os
import calendar
from datetime import datetime, timedelta
from enum import Enum

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.orm import aliased, joinedload

import app.database as database
import app.model.models as models
import app.schema as schema
import app.service.utils as ru
import app.service.filter_utils as fu
import app.service.report as report
import app.cmd.backfill_report_facts as backfill_report_facts

# ---------- Feature flag ----------
# 0 = old path (ActivityMesin + MesinLog)
# 1 = new path (ReportActivityFact)
USE_REPORT_FACT_TABLE = True


# ---------- DB session ----------
engine = database.get_engine()
SessionLocal = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)


class ReportCategory(Enum):
    MESIN = "mesin"
    OPERATOR = "operator"


# ---------- Date/shift helpers ----------
def _correct_invalid_shift(shift):
    shift = max(int(shift), 1)
    shift = min(int(shift), 3)
    return str(shift)


def _fill_default_datetime(date_from=None, shift_from: str = "1", date_to=None, shift_to: str = "3"):
    if date_from is None and date_to is None:
        date_from = date_to = datetime.now(ru.JAKARTA_TZ)
    elif date_from is None:
        date_from = date_to
    elif date_to is None:
        date_to = date_from

    shift_from = "1" if shift_from is None else shift_from
    shift_to = "3" if shift_to is None else shift_to

    shift_from = _correct_invalid_shift(shift_from)
    shift_to = _correct_invalid_shift(shift_to)

    if date_to < date_from:
        date_from, date_to = date_to, date_from
    elif date_to == date_from and shift_to < shift_from:
        shift_to, shift_from = shift_from, shift_to

    return date_from, shift_from, date_to, shift_to


def _calculate_datetime_from_shift(date_time, shift):
    """
    Keep existing behavior:
    shift boundaries are interpreted in Jakarta local time,
    then converted to UTC by subtracting 7 hours.
    """
    year, month, day = date_time.year, date_time.month, date_time.day

    if date_time.isoweekday() == 7:  # Sunday
        return datetime(year, month, day, 0, 0), datetime(year, month, day, 0, 0)

    day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"
    hour_from = ru.WORKING_SHIFT_JSON[day_of_week]["start"][shift]

    time_from = datetime(year, month, day, hour_from, 0) - timedelta(hours=7)
    time_to = time_from + timedelta(hours=ru.WORKING_SHIFT_JSON[day_of_week]["duration"])
    return time_from, time_to


def _calculate_datetime_range(date_from=None, shift_from: str = "1", date_to=None, shift_to: str = "3"):
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(date_from, shift_from, date_to, shift_to)
    time_from, _ = _calculate_datetime_from_shift(date_from, shift_from)
    _, time_to = _calculate_datetime_from_shift(date_to, shift_to)
    return time_from, time_to


def _get_month_range(year=None, month=None):
    today = datetime.now()
    year = year or today.year
    month = month or today.month

    if year == 0:
        year = today.year
    if month == 0:
        month = today.month

    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)
    return first_day, last_day, year, month


def _get_csv_filename(type, date_from, shift_from, date_to, shift_to):
    try:
        date_from = date_from.date()
        date_to = date_to.date()
    except Exception:
        pass

    if date_from == date_to:
        if shift_from == shift_to:
            return f"result_{type}_{date_from}_shift_{shift_from}"
        return f"result_{type}_{date_from}_shift_{shift_from}_to_shift_{shift_to}"

    return f"result_{type}_{date_from}_shift_{shift_from}_to_{date_to}_shift_{shift_to}"


def backup_filename(report_category: ReportCategory, format: schema.FormatType, year=None, month=None):
    directory = "backup/report"
    if not os.path.exists(directory):
        os.makedirs(directory)

    if year is None or month is None:
        now = datetime.now()
        year = year or now.year
        month = month or now.month

    formatted_date = f"{year}_{month:02d}"
    return f"{directory}/backup_{report_category.value}_{format.value}_{formatted_date}.csv"

# ---------- Shared dashboard processing ----------
def apply_report_postprocessing(df, report_category, filters=None, sort=None):
    if df is None or df.empty:
        return df

    df = merge_consecutive_downtime(df, report_category)
    df = fu.apply_filters(df, filters)
    df = _apply_sort(df, report_category, sort)
    return df


def build_dashboard_preview_response(df, pagination=None):
    if df is None or df.empty:
        return {
            "rows": [],
            "total": 0,
        }

    total = len(df)
    page_df = _apply_pagination(df, pagination)

    return {
        "rows": page_df.to_dict(orient="records"),
        "total": total,
    }

# ---------- Shared filters/sort/pagination ----------
def _apply_sort(df, report_category, sort):
    if df is None or df.empty:
        return df

    primary_sort = "Operator" if report_category == ReportCategory.OPERATOR else "MC"

    if sort and sort.sort_by:
        sort_by = fu.PUBLIC_TO_INTERNAL_FILTER_COLUMNS.get(sort.sort_by, sort.sort_by)

        if sort_by in df.columns:
            ascending = (sort.direction == "ascending")
            return df.sort_values(by=[sort_by], ascending=ascending).reset_index(drop=True)

    fallback_cols = [c for c in [primary_sort, "_StartTs"] if c in df.columns]
    if fallback_cols:
        return df.sort_values(by=fallback_cols).reset_index(drop=True)

    return df.reset_index(drop=True)


def _apply_pagination(df, pagination):
    if not pagination or df is None or df.empty:
        return df

    start = (pagination.page - 1) * pagination.page_size
    end = pagination.page * pagination.page_size
    return df.iloc[start:end]


# ---------- Legacy path (ActivityMesin + MesinLog) ----------
def get_report_legacy(session, report_category, time_from, time_to, filters, sort, pagination):
    df = query_activity_mesin_legacy(session, time_from, time_to)
    df = transform_legacy_report_df(df, report_category)
    df = apply_report_postprocessing(df, report_category, filters, sort)
    return df


def query_activity_mesin_legacy(session, time_from, time_to):
    activity_start = aliased(models.MesinLog)
    activity_stop = aliased(models.MesinLog)

    query = (
        session.query(
            models.ActivityMesin.id.label("ActivityMesinId"),
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Operator.nik.label("NIK"),
            models.Tooling.id.label("Tooling"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            models.Tooling.part_no.label("Part No"),
            models.Tooling.part_name.label("Part Name"),
            models.Tooling.std_jam.label("Target"),
            activity_start.timestamp.label("_StartTs"),
            activity_stop.timestamp.label("_StopTs"),
            models.ActivityMesin.category.label("Desc"),
            models.ActivityMesin.output.label("Qty"),
            models.ActivityMesin.reject.label("Reject"),
            models.ActivityMesin.rework.label("Rework"),
            models.ActivityMesin.coil_no.label("Coil No"),
            models.ActivityMesin.lot_no.label("Lot No"),
            models.ActivityMesin.pack_no.label("Pack No"),
            models.ActivityMesin.keterangan.label("KeteranganRaw"),
        )
        .outerjoin(models.Mesin, models.ActivityMesin.mesin_id == models.Mesin.id)
        .join(activity_start, models.ActivityMesin.start_time)
        .outerjoin(activity_stop, models.ActivityMesin.stop_time)
        .join(models.Operator, models.Operator.id == activity_start.operator_id)
        .outerjoin(models.Tooling, models.Tooling.id == activity_start.tooling_id)
        .filter(activity_start.timestamp >= time_from)
        .filter(activity_start.timestamp < time_to)
        .filter(models.ActivityMesin.stop_time_id.isnot(None))
        .order_by(models.Mesin.name.asc(), activity_start.timestamp.asc())
    )

    result = session.execute(query)
    df = pd.DataFrame(result.fetchall(), columns=result.keys())

    if df.empty:
        return pd.DataFrame(
            columns=[
                "MC", "Operator", "NIK", "Tooling", "Kode Tooling", "Common Tooling Name",
                "Part No", "Part Name", "Target", "_StartTs", "_StopTs", "Desc",
                "Qty", "Reject", "Rework", "Keterangan", "Keterangan Limax",
            ]
        )

    for col in ["Coil No", "Lot No", "Pack No", "KeteranganRaw"]:
        df[col] = df[col].fillna("").replace("-", "")

    df["Keterangan"] = df.apply(
        lambda row: ru.combine_keterangan_final(
            row["KeteranganRaw"],
            row["Coil No"],
            row["Lot No"],
            row["Pack No"],
        ),
        axis=1,
    )

    df["Keterangan Limax"] = df.apply(
        lambda row: ru.build_keterangan_limax(int(row["Reject"] or 0), int(row["Rework"] or 0), row["Keterangan"]),
        axis=1,
    )

    df.drop(columns=["Coil No", "Lot No", "Pack No", "KeteranganRaw"], inplace=True)
    return df


def transform_legacy_report_df(df, report_category):
    if df is None or df.empty:
        return df

    df = df.copy()

    if report_category == ReportCategory.OPERATOR:
        df = df[df["Desc"] != "NP : No Plan"].copy()

    columns_to_replace = ["MC", "Tooling", "Kode Tooling", "Common Tooling Name", "Part No", "Part Name"]
    df.loc[:, columns_to_replace] = df.loc[:, columns_to_replace].replace([0, None, np.nan], "-")

    if report_category == ReportCategory.MESIN:
        df = df[df["MC"] != "-"].copy()

    # build derived fields from raw timestamps (not string conversions)
    df = ru.normalize_report_df(df)
    df = ru.add_numeric_metrics(df)

    return df


# ---------- New path (ReportActivityFact) ----------
def get_report_from_fact_table(session, report_category, time_from, time_to, filters, sort, pagination):
    query = (
        session.query(models.ReportActivityFact)
        .filter(models.ReportActivityFact.start_ts_utc >= time_from)
        .filter(models.ReportActivityFact.start_ts_utc < time_to)
        .order_by(models.ReportActivityFact.start_ts_utc.asc())
    )

    if report_category == ReportCategory.MESIN:
        query = query.filter(models.ReportActivityFact.mesin_id.isnot(None))

    rows = query.all()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [
            {
                "ActivityMesinId": r.activity_mesin_id,
                "MC": r.mc_name if r.mc_name else "-",
                "Operator": r.operator_name if r.operator_name else "-",
                "NIK": r.operator_nik if r.operator_nik else "-",
                "Tooling": r.tooling_id if r.tooling_id else "-",
                "Kode Tooling": r.kode_tooling if r.kode_tooling else "-",
                "Common Tooling Name": r.common_tooling_name if r.common_tooling_name else "-",
                "Part No": r.part_no if r.part_no else "-",
                "Part Name": r.part_name if r.part_name else "-",
                "Target": r.target_std_jam if r.target_std_jam else 0,
                "_StartTs": r.start_ts_utc,
                "_StopTs": r.stop_ts_utc,
                "Desc": r.category_full,
                "Qty": int(r.qty or 0),
                "Reject": int(r.reject or 0),
                "Rework": int(r.rework or 0),
                "Keterangan": r.keterangan_final or "",
                "Keterangan Limax": ru.build_keterangan_limax(int(r.reject or 0), int(r.rework or 0), r.keterangan_final or ""),
                "_ProductivityNum": float(r.productivity_pct or 0),
                "_RejectRatioNum": float(r.reject_ratio_pct or 0),
                "_ReworkRatioNum": float(r.rework_ratio_pct or 0),
            }
            for r in rows
        ]
    )

    if report_category == ReportCategory.OPERATOR:
        df = df[df["Desc"] != "NP : No Plan"].copy()

    df = ru.normalize_report_df(df)
    df = apply_report_postprocessing(df, report_category, filters, sort)
    return df

# ---------- Lazy fact backfill helpers ----------
def _get_source_activity_ids_in_range(session, time_from, time_to):
    """
    Return finished ActivityMesin ids whose START timestamp is in [time_from, time_to).
    This matches legacy report behavior.
    """
    return [
        row[0]
        for row in (
            session.query(models.ActivityMesin.id)
            .join(models.MesinLog, models.ActivityMesin.start_time_id == models.MesinLog.id)
            .filter(models.MesinLog.timestamp >= time_from)
            .filter(models.MesinLog.timestamp < time_to)
            .filter(models.ActivityMesin.stop_time_id.isnot(None))
            .order_by(models.ActivityMesin.id.asc())
            .all()
        )
    ]


def _get_fact_activity_ids_in_range(session, time_from, time_to):
    """
    Return activity_mesin_id values already present in report_activity_fact
    for rows whose start_ts_utc is in [time_from, time_to).
    """
    return {
        row[0]
        for row in (
            session.query(models.ReportActivityFact.activity_mesin_id)
            .filter(models.ReportActivityFact.start_ts_utc >= time_from)
            .filter(models.ReportActivityFact.start_ts_utc < time_to)
            .all()
        )
    }


def _ensure_fact_rows_for_range(session, time_from, time_to, max_backfill_rows=1000):
    """
    Smart lazy backfill.

    Case A: fully backfilled
    - source count == fact count
    - no backfill
    - use new path

    Case B: partially backfilled, small gap
    - source count > fact count
    - backfill missing rows up to max_backfill_rows
    - after backfill, complete
    - use new path

    Case C: partially backfilled, big gap
    - source count > fact count
    - backfill only first max_backfill_rows missing rows
    - still incomplete
    - fallback to legacy
    - avoids partial result
    """
    source_ids = _get_source_activity_ids_in_range(session, time_from, time_to)
    source_count = len(source_ids)

    if source_count == 0:
        return {
            "source_count": 0,
            "fact_count_before": 0,
            "backfilled_count": 0,
            "remaining_missing_count": 0,
        }

    fact_ids = _get_fact_activity_ids_in_range(session, time_from, time_to)
    fact_count_before = len(fact_ids)

    # Case A: fully backfilled
    if fact_count_before >= source_count:
        return {
            "source_count": source_count,
            "fact_count_before": fact_count_before,
            "backfilled_count": 0,
            "remaining_missing_count": 0,
        }

    # Case B / C: partially backfilled
    missing_ids = [activity_id for activity_id in source_ids if activity_id not in fact_ids]
    ids_to_backfill = missing_ids[:max_backfill_rows]

    if ids_to_backfill:
        activities = (
            session.query(models.ActivityMesin)
            .options(
                joinedload(models.ActivityMesin.start_time),
                joinedload(models.ActivityMesin.stop_time),
            )
            .filter(models.ActivityMesin.id.in_(ids_to_backfill))
            .order_by(models.ActivityMesin.id.asc())
            .all()
        )

        if activities:
            report.upsert_report_facts_for_stopped_activities(activities, session)
            session.commit()

    fact_ids_after = _get_fact_activity_ids_in_range(session, time_from, time_to)
    remaining_missing_count = max(source_count - len(fact_ids_after), 0)

    return {
        "source_count": source_count,
        "fact_count_before": fact_count_before,
        "backfilled_count": len(ids_to_backfill),
        "remaining_missing_count": remaining_missing_count,
    }

# ---------- Shared merge (fixed: recompute duration + metrics after merge) ----------
def merge_consecutive_downtime(df, report_category):
    if df is None or df.empty:
        return df

    group_col = "MC" if report_category == ReportCategory.MESIN else "Operator"
    df = df.sort_values(by=[group_col, "_StartTs"]).reset_index(drop=True)

    merged_rows = []
    prev = None

    def can_merge(a, b):
        return (
            a[group_col] == b[group_col]
            and a["Desc"] == b["Desc"]
            and a["Tooling"] == b["Tooling"]
            and pd.Timestamp(a["_StopTs"]) == pd.Timestamp(b["_StartTs"])
        )

    def merge_two(a, b):
        m = a.copy()
        m["_StartTs"] = min(pd.Timestamp(a["_StartTs"]), pd.Timestamp(b["_StartTs"]))
        m["_StopTs"] = max(pd.Timestamp(a["_StopTs"]), pd.Timestamp(b["_StopTs"]))

        m["Qty"] = int(a["Qty"]) + int(b["Qty"])
        m["Reject"] = int(a["Reject"]) + int(b["Reject"])
        m["Rework"] = int(a["Rework"]) + int(b["Rework"])

        if (not a["Target"]) and b["Target"]:
            m["Target"] = b["Target"]

        # keep both notes, de-dup
        parts = [a.get("Keterangan", ""), b.get("Keterangan", "")]
        parts = [x for x in parts if x]
        m["Keterangan"] = " | ".join(dict.fromkeys(parts))
        m["Keterangan Limax"] = ru.build_keterangan_limax(m["Reject"], m["Rework"], m["Keterangan"])

        # recompute all derived fields + numeric metrics from merged timestamps
        tmp = pd.DataFrame([m])
        tmp = ru.normalize_report_df(tmp)
        tmp = ru.add_numeric_metrics(tmp)
        return tmp.iloc[0]

    for _, row in df.iterrows():
        if prev is None:
            prev = row.copy()
            continue

        if can_merge(prev, row):
            prev = merge_two(prev, row)
        else:
            merged_rows.append(prev)
            prev = row.copy()

    if prev is not None:
        merged_rows.append(prev)

    return pd.DataFrame(merged_rows).reset_index(drop=True)


# ---------- Output builders ----------
def build_output_frames(df, report_category, format, date_from, shift_from, date_to, shift_to, is_backup, backup_year, backup_month):
    sort_by_first = "Operator" if report_category == ReportCategory.OPERATOR else "MC"
    sort_by_next = "MC" if report_category == ReportCategory.OPERATOR else "Operator"

    # ----- IMN output -----
    df_imn = df.copy(deep=True)

    # Fill display metric strings before selecting final columns
    df_imn = ru.finalize_metric_strings(df_imn)

    imn_header = [
        sort_by_first, "Shift", "Tanggal", "StartTime", "StopTime", sort_by_next,
        "Kode Tooling", "Common Tooling Name", "Part No", "Part Name", "Qty", "Target",
        "Reject", "Rework", "Desc", "Duration", "Productivity", "Reject Ratio", "Rework Ratio", "Keterangan",
    ]

    for col in imn_header:
        if col not in df_imn.columns:
            df_imn[col] = "" if col in [
                "Desc", "Keterangan", "Duration", "Productivity", "Reject Ratio", "Rework Ratio",
                "Tanggal", "StartTime", "StopTime", "Kode Tooling", "Common Tooling Name",
                "Part No", "Part Name"
            ] else 0
    df_imn = df_imn[imn_header]

    # ----- LIMAX output -----
    df_limax = df.copy(deep=True)
    limax_header = {
        "Tanggal": "STR_DATE",
        "Plant": "STR_PLNT",
        "Kode Tooling": "TLG_CODE",
        "Qty": "STR_KUAN",
        "NIK": "PEG_CODE",
        "Shift": "SHF_CODE",
        "MC": "MSN_CODE",
        "Awal": "STR_AWAL",
        "Akhir": "STR_AKHR",
        "Kode Keterangan": "DWN_CODE",
        "Keterangan Limax": "STR_DESC",
    }

    for original_col in limax_header.keys():
        if original_col not in df_limax.columns:
            df_limax[original_col] = "" if original_col in [
                "Tanggal", "Kode Tooling", "Keterangan Limax", "Kode Keterangan", "Awal", "Akhir"
            ] else 0

    df_limax.rename(columns=limax_header, inplace=True)
    limax_cols = [
        "STR_DATE", "STR_PLNT", "TLG_CODE", "STR_KUAN", "PEG_CODE",
        "SHF_CODE", "MSN_CODE", "STR_AWAL", "STR_AKHR", "DWN_CODE", "STR_DESC",
    ]
    for col in limax_cols:
        if col not in df_limax.columns:
            df_limax[col] = ""
    df_limax = df_limax[limax_cols].astype(str)

    # ----- Filename -----
    if is_backup is True:
        filename = backup_filename(report_category=report_category, format=format, year=backup_year, month=backup_month)
    else:
        filename = _get_csv_filename(report_category.value, date_from, shift_from, date_to, shift_to)

    return (df_limax, filename) if "limax" in format.value else (df_imn, filename)


# ---------- Main entrypoint ----------
def get_report(
    report_category: ReportCategory,
    format: schema.FormatType = schema.FormatType.LIMAX,
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None,
    pagination=None, filters=None, sort=None,
    is_backup=None, backup_year=None, backup_month=None,
):
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(date_time_from, shift_from, date_time_to, shift_to)

    if not is_backup:
        time_from, time_to = _calculate_datetime_range(date_from, shift_from, date_to, shift_to)
    else:
        time_from, time_to, backup_year, backup_month = _get_month_range(backup_year, backup_month)

    # keep behavior: limax export and backup disables pagination/filters/sort
    if ("limax" in format.value) or (is_backup is True):
        pagination = filters = sort = None

    with SessionLocal() as session:
        use_new = USE_REPORT_FACT_TABLE and (not is_backup)
        if use_new:
            df = get_report_from_fact_table(
                session=session,
                report_category=report_category,
                time_from=time_from,
                time_to=time_to,
                filters=filters,
                sort=sort,
                pagination=pagination,
            )
        else:
            df = get_report_legacy(
                session=session,
                report_category=report_category,
                time_from=time_from,
                time_to=time_to,
                filters=filters,
                sort=sort,
                pagination=pagination,
            )

        if False:
            if use_new:
                backfill_result = _ensure_fact_rows_for_range(
                    session=session,
                    time_from=time_from,
                    time_to=time_to,
                    max_backfill_rows=1000,
                )

                print(
                    f"[report] source={backfill_result['source_count']} "
                    f"fact_before={backfill_result['fact_count_before']} "
                    f"backfilled={backfill_result['backfilled_count']} "
                    f"remaining_missing={backfill_result['remaining_missing_count']}"
                )

                # Case A: fully backfilled
                # source count == fact count, no backfill,
                # use new path
                #
                # Case B: partially backfilled, small gap
                # source count > fact count, backfill missing rows up to 1000, after backfill, complete,
                # use new path
                #
                # Case C: partially backfilled, big gap
                # source count > fact count, backfill only first 1000 missing rows, still incomplete,
                # fallback to legacy, avoids partial result

                # Safety fallback:
                # if there are still missing rows after lazy backfill,
                # use legacy so we never return a partial report.
                if backfill_result["remaining_missing_count"] > 0:
                    df = get_report_legacy(
                        session=session,
                        report_category=report_category,
                        time_from=time_from,
                        time_to=time_to,
                        filters=filters,
                        sort=sort,
                        pagination=pagination,
                    )
                else:
                    df = get_report_from_fact_table(
                        session=session,
                        report_category=report_category,
                        time_from=time_from,
                        time_to=time_to,
                        filters=filters,
                        sort=sort,
                        pagination=pagination,
                    )
            else:
                df = get_report_legacy(
                    session=session,
                    report_category=report_category,
                    time_from=time_from,
                    time_to=time_to,
                    filters=filters,
                    sort=sort,
                    pagination=pagination,
                )

    return build_output_frames(df, report_category, format, date_from, shift_from, date_to, shift_to, is_backup, backup_year, backup_month)


def get_mesin_report(
    format: schema.FormatType,
    date_time_from: datetime = None, shift_from: int = None,
    date_time_to: datetime = None, shift_to: int = None,
    pagination=None, filters=None, sort=None,
    is_backup=None, backup_year=None, backup_month=None,
):
    return get_report(ReportCategory.MESIN, format, date_time_from, shift_from, date_time_to, shift_to, pagination, filters, sort, is_backup, backup_year, backup_month)


def get_operator_report(
    format: schema.FormatType,
    date_time_from: datetime = None, shift_from: int = None,
    date_time_to: datetime = None, shift_to: int = None,
    pagination=None, filters=None, sort=None,
    is_backup=None, backup_year=None, backup_month=None,
):
    return get_report(ReportCategory.OPERATOR, format, date_time_from, shift_from, date_time_to, shift_to, pagination, filters, sort, is_backup, backup_year, backup_month)
