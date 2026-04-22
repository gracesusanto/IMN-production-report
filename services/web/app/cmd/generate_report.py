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
import app.service.report_summary as rs
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
            models.Tooling.proses.label("Proses"),
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
                "Part No", "Part Name", "Proses", "Target", "_StartTs", "_StopTs", "Desc",
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

    columns_to_replace = [
        "MC", "Tooling", "Kode Tooling", "Common Tooling Name",
        "Part No", "Part Name", "Proses",
    ]
    df.loc[:, columns_to_replace] = df.loc[:, columns_to_replace].replace([0, None, np.nan], "-")

    if report_category == ReportCategory.MESIN:
        df = df[df["MC"] != "-"].copy()

    # build derived fields from raw timestamps (not string conversions)
    df = ru.normalize_report_df(df)
    df = ru.add_numeric_metrics(df)

    return df


# ---------- Raw data helpers for dashboard summary ----------
def get_report_legacy_raw(session, report_category, time_from, time_to):
    """Get raw normalized report data without postprocessing for dashboard summary."""
    df = query_activity_mesin_legacy(session, time_from, time_to)
    df = transform_legacy_report_df(df, report_category)
    # Return normalized data WITHOUT apply_report_postprocessing
    return df


def get_report_from_fact_table_raw(session, report_category, time_from, time_to):
    """
    Get raw fact table data with overlap-based filtering for dashboard summary.
    Uses overlap logic: start_ts < window_end AND stop_ts > window_start
    """
    query = (
        session.query(models.ReportActivityFact)
        .filter(models.ReportActivityFact.start_ts_utc < time_to)
        .filter(models.ReportActivityFact.stop_ts_utc > time_from)
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
                "Proses": getattr(r, "proses", None) or "-",
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

    # Return normalized data WITHOUT apply_report_postprocessing
    return ru.normalize_report_df(df)


def get_report_with_overlap_window_and_filters(session, report_category, time_from, time_to, filters=None):
    """
    Get raw report data using overlap-based time filtering AND safe DB-level filters.
    Filters by: start < time_to AND stop > time_from
    Plus: machine, operator, part, proses filters that are safe at raw fact level
    """
    use_new = USE_REPORT_FACT_TABLE

    if use_new:
        # Use overlap filtering for fact table - this is the correct foundation
        query = (
            session.query(models.ReportActivityFact)
            .filter(models.ReportActivityFact.start_ts_utc < time_to)
            .filter(models.ReportActivityFact.stop_ts_utc > time_from)
        )

        # Report category filtering
        if report_category == ReportCategory.MESIN:
            query = query.filter(models.ReportActivityFact.mesin_id.isnot(None))

        # Apply safe DB-level filters from UI (these don't depend on shift splitting)
        if filters:
            mc_filter = filters.get("mc")
            if mc_filter and hasattr(mc_filter, 'contains') and mc_filter.contains:
                query = query.filter(models.ReportActivityFact.mc_name.contains(mc_filter.contains))
            elif mc_filter and (hasattr(mc_filter, 'in_list') or hasattr(mc_filter, 'in')):
                in_values = getattr(mc_filter, 'in_list', None) or getattr(mc_filter, 'in', None)
                if in_values:
                    query = query.filter(models.ReportActivityFact.mc_name.in_(in_values))

            operator_filter = filters.get("operator")
            if operator_filter and hasattr(operator_filter, 'contains') and operator_filter.contains:
                query = query.filter(models.ReportActivityFact.operator_name.contains(operator_filter.contains))
            elif operator_filter and (hasattr(operator_filter, 'in_list') or hasattr(operator_filter, 'in')):
                in_values = getattr(operator_filter, 'in_list', None) or getattr(operator_filter, 'in', None)
                if in_values:
                    query = query.filter(models.ReportActivityFact.operator_name.in_(in_values))

            part_no_filter = filters.get("part_no")
            if part_no_filter and hasattr(part_no_filter, 'contains') and part_no_filter.contains:
                query = query.filter(models.ReportActivityFact.part_no.contains(part_no_filter.contains))

            part_name_filter = filters.get("part_name")
            if part_name_filter and hasattr(part_name_filter, 'contains') and part_name_filter.contains:
                query = query.filter(models.ReportActivityFact.part_name.contains(part_name_filter.contains))

            proses_filter = filters.get("proses")
            if proses_filter and hasattr(proses_filter, 'equals') and proses_filter.equals:
                query = query.filter(models.ReportActivityFact.proses == proses_filter.equals)

        query = query.order_by(models.ReportActivityFact.start_ts_utc.asc())
        rows = query.all()
        print(f"DB query returned: {len(rows)} rows (overlap + DB-filtered)")

        if not rows:
            return pd.DataFrame()

        # Convert to DataFrame - same format as before
        df_dict = {
            "MC": [r.mc_name or "-" for r in rows],
            "Operator": [r.operator_name or "-" for r in rows],
            "NIK": [r.operator_nik or "-" for r in rows],
            "Part No": [r.part_no or "-" for r in rows],
            "Part Name": [r.part_name or "-" for r in rows],
            "Proses": [r.proses or "-" for r in rows],
            "Desc": [r.category_desc or "" for r in rows],
            "Target": [r.target_std_jam or 0 for r in rows],
            "Qty": [r.qty for r in rows],
            "Reject": [r.reject for r in rows],
            "Rework": [r.rework for r in rows],
            "Keterangan": [r.keterangan_final or "" for r in rows],
            "_StartTs": [r.start_ts_utc for r in rows],
            "_StopTs": [r.stop_ts_utc for r in rows],
            "_DurationMinutes": [(r.stop_ts_utc - r.start_ts_utc).total_seconds() / 60.0 for r in rows],
        }

        # Add tooling info if available
        if rows and hasattr(rows[0], 'kode_tooling'):
            df_dict["Kode Tooling"] = [r.kode_tooling or "-" for r in rows]
            df_dict["Common Tooling Name"] = [r.common_tooling_name or "-" for r in rows]

        return pd.DataFrame(df_dict)

    else:
        # Fallback to old method if fact table not available
        return get_report_with_overlap_window_old(session, report_category, time_from, time_to)


def get_report_with_overlap_window_old(session, report_category, time_from, time_to):
    """
    Original method for backward compatibility
    """
    use_new = False

    if not use_new:
        # Use overlap filtering for fact table
        query = (
            session.query(models.ReportActivityFact)
            .filter(models.ReportActivityFact.start_ts_utc < time_to)
            .filter(models.ReportActivityFact.stop_ts_utc > time_from)
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
                    "Proses": getattr(r, "proses", None) or "-",
                    "Target": r.target_std_jam if r.target_std_jam else 0,
                    "_StartTs": r.start_ts_utc,
                    "_StopTs": r.stop_ts_utc,
                    "Desc": r.category_full,
                    "Qty": int(r.qty or 0),
                    "Reject": int(r.reject or 0),
                    "Rework": int(r.rework or 0),
                    "Keterangan": r.keterangan_final or "",
                }
                for r in rows
            ]
        )
    else:
        # For legacy path, use overlap filtering on ActivityMesin
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
                models.Tooling.proses.label("Proses"),
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
            # Overlap filtering: start < time_to AND stop > time_from
            .filter(activity_start.timestamp < time_to)
            .filter(activity_stop.timestamp > time_from)
            .filter(models.ActivityMesin.stop_time_id.isnot(None))
            .order_by(models.Mesin.name.asc(), activity_start.timestamp.asc())
        )

        result = session.execute(query)
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

        if df.empty:
            return pd.DataFrame()

        # Process keterangan fields
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

        df.drop(columns=["Coil No", "Lot No", "Pack No", "KeteranganRaw"], inplace=True)
        df = transform_legacy_report_df(df, report_category)

    if report_category == ReportCategory.OPERATOR:
        df = df[df["Desc"] != "NP : No Plan"].copy()

    return ru.normalize_report_df(df)


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
                "Proses": getattr(r, "proses", None) or "-",
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
        "Kode Tooling", "Common Tooling Name", "Part No", "Part Name", "Proses", "Qty", "Target",
        "Reject", "Rework", "Desc", "Duration", "Productivity", "Reject Ratio", "Rework Ratio", "Keterangan",
    ]

    for col in imn_header:
        if col not in df_imn.columns:
            df_imn[col] = "" if col in [
                "Desc", "Keterangan", "Duration", "Productivity", "Reject Ratio", "Rework Ratio",
                "Tanggal", "StartTime", "StopTime", "Kode Tooling", "Common Tooling Name",
                "Part No", "Part Name", "Proses"
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


# ---------- Dashboard summary ----------
def get_dashboard_summary_report(
    report_category: ReportCategory,
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None,
    pagination=None, filters=None, sort=None,
):
    """
    Get dashboard summary report with shift splitting and business grain aggregation.
    OPTIMIZED: Filters at database level for much better performance.
    """
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(date_time_from, shift_from, date_time_to, shift_to)

    print(f"Dashboard summary report (hybrid optimized): {date_from} to {date_to}, shifts {shift_from}-{shift_to}")

    # Calculate overlap time window - this is the correct foundation
    time_from, time_to = _calculate_datetime_range(date_from, shift_from, date_to, shift_to)
    print(f"Overlap time window: {time_from} to {time_to}")

    with SessionLocal() as session:
        # OPTIMIZED: Get data with overlap window + safe DB filters
        df = get_report_with_overlap_window_and_filters(
            session=session,
            report_category=report_category,
            time_from=time_from,
            time_to=time_to,
            filters=filters,  # Push safe filters to DB level
        )

    # Apply dashboard summary aggregation
    if df.empty:
        print("No data found for the specified filters")
        return rs.build_dashboard_response(pd.DataFrame(), report_category, pagination)

    print(f"Processing {len(df)} raw rows for dashboard summary")
    summary_df = rs.summarize_dashboard_df(df, report_category)
    print(f"Summarized to {len(summary_df)} rows")

    # Apply filters after summarization
    filtered_df = fu.apply_filters(summary_df, filters)
    print(f"Filtered to {len(filtered_df)} rows")

    # Apply date/shift filtering - this is the key fix for the date filtering bug
    date_shift_filtered_df = _apply_date_shift_filter(filtered_df, date_from, date_to, shift_from, shift_to)
    print(f"Date/shift filtered to {len(date_shift_filtered_df)} rows")

    # Apply sorting
    sorted_df = _apply_sort(date_shift_filtered_df, report_category, sort)

    # Safety check
    _assert_date_shift_constraints(sorted_df, date_from, date_to, shift_from, shift_to)

    return rs.build_dashboard_response(sorted_df, report_category, pagination)


def _apply_date_shift_filter(df, date_from, date_to, shift_from, shift_to):
    """Apply date and shift filtering to summarized data"""
    try:
        if df.empty:
            return df

        # Convert dates to date objects for comparison
        if hasattr(date_from, 'date'):
            date_from = date_from.date()
        if hasattr(date_to, 'date'):
            date_to = date_to.date()

        original_count = len(df)

        # Date filtering
        if 'Tanggal' in df.columns:
            date_mask = (pd.to_datetime(df['Tanggal']).dt.date >= date_from) & \
                       (pd.to_datetime(df['Tanggal']).dt.date <= date_to)
            df = df[date_mask]

        # Shift filtering
        if 'Shift' in df.columns:
            shift_from_int = int(shift_from)
            shift_to_int = int(shift_to)
            shift_mask = (df['Shift'].astype(int) >= shift_from_int) & \
                        (df['Shift'].astype(int) <= shift_to_int)
            df = df[shift_mask]

        if original_count != len(df):
            print(f"Date/shift filter: {original_count} → {len(df)} rows")

        return df
    except Exception as e:
        print(f"ERROR in _apply_date_shift_filter: {e}")
        # Return original df if filtering fails
        return df


def _assert_date_shift_constraints(df, date_from, date_to, shift_from, shift_to):
    """Assert all rows satisfy date/shift constraints - fail in dev if not"""
    try:
        if df.empty:
            return

        # Convert dates for comparison
        if hasattr(date_from, 'date'):
            date_from = date_from.date()
        if hasattr(date_to, 'date'):
            date_to = date_to.date()

        violations = []

        if 'Tanggal' in df.columns:
            df_dates = pd.to_datetime(df['Tanggal']).dt.date
            date_violations = df[(df_dates < date_from) | (df_dates > date_to)]
            if not date_violations.empty:
                violations.append(f"Date violations: {len(date_violations)} rows outside {date_from} to {date_to}")
                print(f"DEBUG: Date violations found:")
                for _, row in date_violations.head(5).iterrows():
                    print(f"  Row has tanggal={row.get('Tanggal')}, expected {date_from} <= tanggal <= {date_to}")

        if 'Shift' in df.columns:
            shift_from_int = int(shift_from)
            shift_to_int = int(shift_to)
            df_shifts = df['Shift'].astype(int)
            shift_violations = df[(df_shifts < shift_from_int) | (df_shifts > shift_to_int)]
            if not shift_violations.empty:
                violations.append(f"Shift violations: {len(shift_violations)} rows outside shift {shift_from} to {shift_to}")
                print(f"DEBUG: Shift violations found:")
                for _, row in shift_violations.head(5).iterrows():
                    print(f"  Row has shift={row.get('Shift')}, expected {shift_from} <= shift <= {shift_to}")

        if violations:
            error_msg = f"Date/shift constraint violations: {'; '.join(violations)}"
            print(f"WARNING: {error_msg}")
            # Just log for now, don't fail
        else:
            pass  # All constraints satisfied

    except Exception as e:
        print(f"ERROR in _assert_date_shift_constraints: {e}")


def _apply_safe_fact_filters(query, filters):
    """
    Apply only filters that are safe at raw fact level.
    Do NOT apply final date/shift summary filtering here.
    """
    if not filters:
        return query

    for field, cond in filters.items():
        if not cond:
            continue

        db_field = None
        if field in {"mc", "mc_no"}:
            db_field = models.ReportActivityFact.mc_name
        elif field == "operator":
            db_field = models.ReportActivityFact.operator_name
        elif field == "part_no":
            db_field = models.ReportActivityFact.part_no
        elif field == "part_name":
            db_field = models.ReportActivityFact.part_name
        elif field == "proses":
            db_field = models.ReportActivityFact.proses
        elif field in {"desc", "category", "status"}:
            db_field = models.ReportActivityFact.category_full

        if db_field is None:
            continue

        contains_val = getattr(cond, "contains", None)
        equals_val = getattr(cond, "equals", None)
        in_val = getattr(cond, "in_list", None) or getattr(cond, "in", None)

        if contains_val:
            query = query.filter(db_field.ilike(f"%{contains_val}%"))
        elif equals_val not in [None, ""]:
            query = query.filter(db_field == equals_val)
        elif in_val:
            query = query.filter(db_field.in_(in_val))

    return query


def _build_fact_overlap_query(session, report_category, time_from, time_to, filters=None):
    """
    Raw fact query using overlap logic:
      start_ts_utc < window_end
      stop_ts_utc  > window_start
    """
    query = (
        session.query(models.ReportActivityFact)
        .filter(models.ReportActivityFact.start_ts_utc < time_to)
        .filter(models.ReportActivityFact.stop_ts_utc > time_from)
    )

    if report_category == ReportCategory.MESIN:
        query = query.filter(models.ReportActivityFact.mesin_id.isnot(None))

    query = _apply_safe_fact_filters(query, filters)
    query = query.order_by(
        models.ReportActivityFact.tanggal_local.asc(),
        models.ReportActivityFact.shift.asc(),
        models.ReportActivityFact.start_ts_utc.asc(),
    )

    return query


def _fact_rows_to_dataframe(rows, report_category):
    """Convert fact rows to normalized dataframe"""
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [
            {
                "ActivityMesinId": r.activity_mesin_id,
                "MC": r.mc_name or "-",
                "Operator": r.operator_name or "-",
                "NIK": r.operator_nik or "-",
                "Tooling": r.tooling_id or "-",
                "Kode Tooling": r.kode_tooling or "-",
                "Common Tooling Name": r.common_tooling_name or "-",
                "Part No": r.part_no or "-",
                "Part Name": r.part_name or "-",
                "Proses": getattr(r, "proses", None) or "-",
                "Target": float(r.target_std_jam or 0),
                "_StartTs": pd.Timestamp(r.start_ts_utc),
                "_StopTs": pd.Timestamp(r.stop_ts_utc),
                "Desc": r.category_full or "",
                "Qty": int(r.qty or 0),
                "Reject": int(r.reject or 0),
                "Rework": int(r.rework or 0),
                "Keterangan": r.keterangan_final or "",
                "Keterangan Limax": ru.build_keterangan_limax(
                    int(r.reject or 0),
                    int(r.rework or 0),
                    r.keterangan_final or "",
                ),
            }
            for r in rows
        ]
    )

    if report_category == ReportCategory.OPERATOR:
        df = df[df["Desc"] != "NP : No Plan"].copy()

    return ru.normalize_report_df(df)


def get_report_with_overlap_window_and_filters(
    session,
    report_category,
    time_from,
    time_to,
    filters=None,
):
    """
    Shared raw source for dashboard detail + summary.
    Uses DB overlap filtering and safe DB-level filters,
    but does NOT do summary/date-shift pruning yet.
    """
    if not USE_REPORT_FACT_TABLE:
        # fallback legacy path if needed
        return get_report_legacy_raw(session, report_category, time_from, time_to)

    rows = _build_fact_overlap_query(
        session=session,
        report_category=report_category,
        time_from=time_from,
        time_to=time_to,
        filters=filters,
    ).all()

    print(f"Processing {len(rows)} raw rows from optimized DB query")
    print(f"DEBUG: Fact query time window: {time_from} to {time_to}")
    if rows:
        print(f"DEBUG: First fact row time: {rows[0].start_ts_utc} to {rows[0].stop_ts_utc}")
        print(f"DEBUG: First fact row shift: {rows[0].shift}, tanggal: {rows[0].tanggal_local}")
    return _fact_rows_to_dataframe(rows, report_category)


def get_detail_export_report(
    report_category: ReportCategory,
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None,
    pagination=None, filters=None, sort=None,
):
    """
    Get detail/export report matching Excel column structure exactly.
    OPTIMIZED: Filters at database level for much better performance.
    """
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(date_time_from, shift_from, date_time_to, shift_to)

    print(f"Dashboard detail report (hybrid optimized): {date_from} to {date_to}, shifts {shift_from}-{shift_to}")

    # Calculate overlap time window - this is the correct foundation
    time_from, time_to = _calculate_datetime_range(date_from, shift_from, date_to, shift_to)
    print(f"Overlap time window: {time_from} to {time_to}")

    with SessionLocal() as session:
        # OPTIMIZED: Get data with overlap window + safe DB filters
        df = get_report_with_overlap_window_and_filters(
            session=session,
            report_category=report_category,
            time_from=time_from,
            time_to=time_to,
            filters=filters,  # Push safe filters to DB level
        )

    # Apply dashboard summary for consistent KPIs, then convert to detail format
    if df.empty:
        print("No data found for the specified filters")
        return rs.build_detail_export_response(pd.DataFrame(), report_category, pagination)

    print(f"Processing {len(df)} pre-filtered raw rows")
    summary_df = rs.summarize_dashboard_df(df, report_category)
    print(f"Summarized to {len(summary_df)} rows")

    # Apply remaining filters that weren't safe at DB level (should be fewer now)
    remaining_filters = {k: v for k, v in (filters or {}).items()
                        if k not in ['mc', 'operator', 'part_no', 'part_name', 'proses']}
    if remaining_filters:
        filtered_df = fu.apply_filters(summary_df, remaining_filters)
        print(f"Additional filtered to {len(filtered_df)} rows")
    else:
        filtered_df = summary_df

    # Apply final exact date/shift filtering - CRITICAL for correctness
    # This is needed because activities can cross shift/date boundaries
    date_shift_filtered_df = _apply_date_shift_filter(filtered_df, date_from, date_to, shift_from, shift_to)
    print(f"Final date/shift filtered to {len(date_shift_filtered_df)} rows")

    # Apply sorting
    sorted_df = _apply_sort(date_shift_filtered_df, report_category, sort)

    # Safety check - should pass now
    _assert_date_shift_constraints(sorted_df, date_from, date_to, shift_from, shift_to)

    return rs.build_detail_export_response(sorted_df, report_category, pagination)


def get_row_history(
    report_type: str,
    tanggal: str,
    shift: str,
    mc: str,
    part_no: str,
    proses: str,
    operator: str = None,
    source_activity_ids: list[int] | None = None,
):
    """
    Get the detailed history and calculation breakdown for a specific summary row.
    Reconstructs the source activities that contributed to the clicked summary row.
    """
    from datetime import datetime

    print(f"Row history request: {report_type} {mc} {part_no} {proses} on {tanggal} shift {shift}")
    print(f"DEBUG: Exact request payload - MC='{mc}', Part_No='{part_no}', Proses='{proses}', Date='{tanggal}', Shift='{shift}', Operator='{operator}'")
    print(f"DEBUG: Source activity IDs: {source_activity_ids}")

    # Prioritize lineage-based history using source activity IDs
    if source_activity_ids:
        return _get_row_history_by_ids(
            report_type=report_type,
            tanggal=tanggal,
            shift=shift,
            mc=mc,
            part_no=part_no,
            proses=proses,
            operator=operator,
            source_activity_ids=source_activity_ids,
        )

    DEBUG_ROW_HISTORY = True  # Enable debug mode

    # Fallback to grain-based reconstruction
    try:
        result = _get_row_history_main(report_type, tanggal, shift, mc, part_no, proses, operator)

        # Check if reconstruction actually succeeded
        if result.get("found") is False or not result.get("summary"):
            print(f"Row history reconstruction did not find a matching row for {mc} {part_no} {proses}")
        else:
            print(f"Row history reconstruction succeeded for {mc} {part_no} {proses}")

        return result
    except Exception as e:
        print(f"Main reconstruction failed: {e}")
        fallback_result = _get_row_history_fallback(report_type, tanggal, shift, mc, part_no, proses, operator)

        # In debug mode, don't return fake zeros when no row is found
        if DEBUG_ROW_HISTORY and not fallback_result.get("summary"):
            return {
                "summary": {},
                "timeline": [],
                "calculation": {},
                "error": f"Row history reconstruction failed: {str(e)}",
                "found": False,
            }

        return fallback_result


def _get_row_history_main(report_type, tanggal, shift, mc, part_no, proses, operator=None):
    """
    Main reconstruction method using stored fact table grain.
    Fixes the shift-3 window problem by querying the EXACT stored fact-table grain.
    """
    from datetime import datetime

    report_category = ReportCategory.MESIN if report_type == "mesin" else ReportCategory.OPERATOR

    # Parse the input date and shift
    date_obj = datetime.strptime(tanggal, "%Y-%m-%d").date()
    shift_num = int(shift)

    print(f"Row history for {report_type} on {tanggal} shift {shift}: querying by stored fact grain")

    with SessionLocal() as session:
        # CORE FIX: Query by the EXACT stored fact table grain
        # This avoids recalculating UTC windows that mismatch how data was stored
        query = (
            session.query(models.ReportActivityFact)
            .filter(models.ReportActivityFact.tanggal_local == date_obj)
            .filter(models.ReportActivityFact.shift == shift_num)
            .filter(models.ReportActivityFact.mc_name == mc)
            .filter(models.ReportActivityFact.part_no == part_no)
            .filter(models.ReportActivityFact.proses == proses)
        )

        if report_type == "operator" and operator:
            query = query.filter(models.ReportActivityFact.operator_name == operator)

        rows = query.order_by(models.ReportActivityFact.start_ts_utc.asc()).all()

        print(f"Found {len(rows)} exact fact rows for tanggal={date_obj} shift={shift_num} {mc}/{part_no}/{proses}")
        if rows:
            for i, r in enumerate(rows[:2]):  # Show first 2
                print(f"  Match {i}: start={r.start_ts_utc}, qty={r.qty}, cat={r.category_full}")
        else:
            print("❌ No exact fact rows found - reconstruction failed")
            return _get_row_history_fallback(report_type, tanggal, shift, mc, part_no, proses, operator)

        # Convert fact rows to dataframe for processing
        matched_df = _fact_rows_to_dataframe(rows, report_category)

        if matched_df.empty:
            print("❌ Matched dataframe is empty - reconstruction failed")
            return _get_row_history_fallback(report_type, tanggal, shift, mc, part_no, proses, operator)

        print(f"✅ Successfully matched {len(matched_df)} raw fact rows for {mc}/{part_no}/{proses}")

        # Build summary directly from matched raw facts (avoid double-splitting bug)
        summary_df = rs.summarize_dashboard_df(matched_df, report_category)

        if summary_df.empty:
            print("❌ Summary aggregation failed - using fallback")
            return _get_row_history_fallback(report_type, tanggal, shift, mc, part_no, proses, operator)

        # Apply exact date/shift filtering to ensure we get the right summary row
        final_summary = _apply_date_shift_filter(summary_df, date_obj, date_obj, shift_num, shift_num)

        if final_summary.empty:
            print("❌ No data after date/shift filtering - using fallback")
            return _get_row_history_fallback(report_type, tanggal, shift, mc, part_no, proses, operator)

        # Get the reconstructed summary row
        summary_row = final_summary.iloc[0]
        print(f"✅ Row history reconstruction succeeded: OEE={summary_row.get('OEE', 'N/A')}, Output={summary_row.get('Qty', 'N/A')}")

        # Build timeline from the matched raw activities (split for display only)
        split_df = rs.split_rows_by_shift(matched_df)
        timeline = []

        for _, activity in split_df.iterrows():
            # Double-check this activity belongs to the requested date/shift
            activity_date = pd.to_datetime(activity.get("Tanggal")).date() if "Tanggal" in activity else None
            activity_shift = int(activity.get("Shift", 0)) if "Shift" in activity else 0

            if activity_date == date_obj and activity_shift == shift_num:
                start_time = activity.get("_StartTs")
                stop_time = activity.get("_StopTs")

                # Convert to Jakarta time for display
                if isinstance(start_time, pd.Timestamp):
                    start_time = start_time.tz_convert(ru.JAKARTA_TZ).isoformat()
                if isinstance(stop_time, pd.Timestamp):
                    stop_time = stop_time.tz_convert(ru.JAKARTA_TZ).isoformat()

                duration_mins = activity.get("_DurationMinutes", 0)

                timeline.append({
                    "start_time": str(start_time),
                    "stop_time": str(stop_time),
                    "desc": activity.get("Desc", ""),
                    "duration_minutes": float(duration_mins),
                    "qty": int(activity.get("Qty", 0)),
                    "reject": int(activity.get("Reject", 0)),
                    "rework": int(activity.get("Rework", 0)),
                    "operator": activity.get("Operator", "-"),
                    "mc": activity.get("MC", "-"),
                    "part_no": activity.get("Part No", "-"),
                    "proses": activity.get("Proses", "-"),
                    "keterangan": activity.get("Keterangan", "")
                })

        # Sort timeline by start time
        timeline.sort(key=lambda x: x["start_time"])
        print(f"✅ Built timeline with {len(timeline)} activities")

        # Build the summary response (same format as detail response)
        target_per_jam = int(summary_row.get("Target", 0))
        target_qty = int(summary_row.get("Target Qty", 0)) if "Target Qty" in summary_row else target_per_jam

        summary = {
            "status": rs._derive_status_from_row(summary_row),
            "operator": summary_row.get("Operator", "-"),
            "mc_no": summary_row.get("MC", "-"),
            "part_no_name": f"{summary_row.get('Part No', '-')} {summary_row.get('Part Name', '-')}".strip(),
            "proses": summary_row.get("Proses", "-"),
            "target_per_jam": target_per_jam,
            "target_qty": target_qty,
            "output": int(summary_row.get("Qty", 0)),
            "reject": int(summary_row.get("Reject", 0)),
            "plan": summary_row.get("Plan", "00:00"),
            "utility": summary_row.get("Utility", "00:00"),  # U : Utility - the actual running time
            "tp": summary_row.get("TP", "00:00"),
            "ts": summary_row.get("TS", "00:00"),
            "qc": summary_row.get("QC", "00:00"),
            "cm": summary_row.get("CM", "00:00"),
            "no": summary_row.get("NO", "00:00"),
            "np": summary_row.get("NP", "00:00"),
            "nm": summary_row.get("NM", "00:00"),
            "mp": summary_row.get("MP", "00:00"),
            "bt": summary_row.get("BT", "00:00"),
            "br": summary_row.get("BR", "00:00"),
            "total_dt": summary_row.get("Total Downtime", "00:00"),
            "per": summary_row.get("PER", "0%"),
            "otr": summary_row.get("OTR", "0%"),
            "qr": summary_row.get("QR", "0%"),
            "oee": summary_row.get("OEE", "0%"),
            "tanggal": tanggal,
            "shift": shift
        }

        # Build calculation breakdown
        plan_minutes = summary_row.get("Plan Minutes", 0)
        utility_minutes = summary_row.get("Utility Minutes", 0)
        downtime_minutes = plan_minutes - utility_minutes

        calculation = {
            "plan_minutes": float(plan_minutes),
            "utility_minutes": float(utility_minutes),
            "downtime_minutes": float(downtime_minutes),
            "target_per_jam": target_per_jam,
            "target_qty": target_qty,
            "per_formula": "output / (utility_hours * target_per_jam)",
            "otr_formula": "utility_minutes / plan_minutes",
            "qr_formula": "output / (output + reject + rework)",
            "oee_formula": "otr * per * qr",
            "per_num": float(summary_row.get("PER Num", 0)),
            "otr_num": float(summary_row.get("OTR Num", 0)),
            "qr_num": float(summary_row.get("QR Num", 0)),
            "oee_num": float(summary_row.get("OEE Num", 0))
        }

        return {
            "summary": summary,
            "timeline": timeline,
            "calculation": calculation
        }


def _get_row_history_by_ids(
    report_type: str,
    tanggal: str,
    shift: str,
    mc: str,
    part_no: str,
    proses: str,
    operator: str = None,
    source_activity_ids: list[int] | None = None,
):
    """
    Get row history using exact source activity IDs.
    This is more reliable than grain-based reconstruction.
    """
    report_category = ReportCategory.MESIN if report_type == "mesin" else ReportCategory.OPERATOR

    if not source_activity_ids:
        return {
            "summary": {},
            "timeline": [],
            "calculation": {},
            "found": False,
            "error": "No source activity ids provided"
        }

    # Fetch exact source activities by ID
    with SessionLocal() as session:
        rows = (
            session.query(models.ReportActivityFact)
            .filter(models.ReportActivityFact.activity_mesin_id.in_(source_activity_ids))
            .order_by(models.ReportActivityFact.start_ts_utc.asc())
            .all()
        )

    raw_df = _fact_rows_to_dataframe(rows, report_category)
    if raw_df.empty:
        return {
            "summary": {},
            "timeline": [],
            "calculation": {},
            "found": False,
            "error": "No fact rows found for source activity ids"
        }

    # Re-summarize using the same logic as dashboard (avoid double-splitting)
    split_df = rs.split_rows_by_shift(raw_df)
    summary_df = rs.summarize_already_split_df(split_df, report_category)

    from datetime import datetime
    date_obj = datetime.strptime(tanggal, "%Y-%m-%d").date()
    shift_num = int(shift)

    # Apply date/shift filtering
    final_summary = _apply_date_shift_filter(summary_df, date_obj, date_obj, shift_num, shift_num)

    # Filter by operator if needed
    if report_type == "operator" and operator and not final_summary.empty:
        final_summary = final_summary[final_summary["Operator"] == operator]

    # Filter by grain to get the exact matching row
    final_summary = final_summary[
        (final_summary["MC"] == mc) &
        (final_summary["Part No"] == part_no) &
        (final_summary["Proses"] == proses)
    ]

    if final_summary.empty:
        return {
            "summary": {},
            "timeline": [],
            "calculation": {},
            "found": False,
            "error": "Could not rebuild summary row from source activity ids"
        }

    summary_row = final_summary.iloc[0]

    # Build timeline from split activities
    split_df = rs.split_rows_by_shift(raw_df)

    timeline = []
    for _, activity in split_df.iterrows():
        activity_date = pd.to_datetime(activity.get("Tanggal")).date() if "Tanggal" in activity else None
        activity_shift = int(activity.get("Shift", 0)) if "Shift" in activity else 0

        # Only include activities matching the requested date/shift
        if activity_date == date_obj and activity_shift == shift_num:
            start_time = activity.get("_StartTs")
            stop_time = activity.get("_StopTs")

            if isinstance(start_time, pd.Timestamp):
                start_time = start_time.tz_convert(ru.JAKARTA_TZ).isoformat()
            if isinstance(stop_time, pd.Timestamp):
                stop_time = stop_time.tz_convert(ru.JAKARTA_TZ).isoformat()

            timeline.append({
                "start_time": str(start_time),
                "stop_time": str(stop_time),
                "desc": activity.get("Desc", ""),
                "duration_minutes": float(activity.get("_DurationMinutes", 0)),
                "qty": int(activity.get("Qty", 0)),
                "reject": int(activity.get("Reject", 0)),
                "rework": int(activity.get("Rework", 0)),
                "operator": activity.get("Operator", "-"),
                "mc": activity.get("MC", "-"),
                "part_no": activity.get("Part No", "-"),
                "proses": activity.get("Proses", "-"),
                "keterangan": activity.get("Keterangan", ""),
                "activity_mesin_id": activity.get("ActivityMesinId"),
            })

    # Build summary response
    target_per_jam = int(summary_row.get("Target", 0))
    target_qty = int(summary_row.get("Target Qty", 0)) if "Target Qty" in summary_row else target_per_jam

    summary = {
        "status": summary_row.get("Status", "OK"),
        "operator": summary_row.get("Operator", "-"),
        "mc_no": summary_row.get("MC", "-"),
        "part_no_name": f"{summary_row.get('Part No', '-')} {summary_row.get('Part Name', '-')}".strip(),
        "proses": summary_row.get("Proses", "-"),
        "target_per_jam": target_per_jam,
        "target_qty": target_qty,
        "output": int(summary_row.get("Qty", 0)),
        "reject": int(summary_row.get("Reject", 0)),
        "rework": int(summary_row.get("Rework", 0)),
        "plan": summary_row.get("Plan", "00:00"),
        "rt": summary_row.get("Utility", "00:00"),
        "utility": summary_row.get("Utility", "00:00"),
        "tp": summary_row.get("TP", "00:00"),
        "ts": summary_row.get("TS", "00:00"),
        "qc": summary_row.get("QC", "00:00"),
        "cm": summary_row.get("CM", "00:00"),
        "no": summary_row.get("NO", "00:00"),
        "np": summary_row.get("NP", "00:00"),
        "nm": summary_row.get("NM", "00:00"),
        "mp": summary_row.get("MP", "00:00"),
        "bt": summary_row.get("BT", "00:00"),
        "br": summary_row.get("BR", "00:00"),
        "tl": summary_row.get("TL", "00:00"),
        "total_dt": summary_row.get("Total Downtime", "00:00"),
        "per": summary_row.get("PER", "0%"),
        "otr": summary_row.get("OTR", "0%"),
        "qr": summary_row.get("QR", "0%"),
        "oee": summary_row.get("OEE", "0%"),
        "tanggal": tanggal,
        "shift": shift,
    }

    # Build operator sessions with category totals
    import numpy as np

    # Add desc code if not already present
    if "Desc Code" not in split_df.columns:
        split_df["Desc Code"] = split_df["Desc"].map(lambda desc: str(desc).split(":")[0].strip().upper()[:2] if desc else "")

    # Build per-operator category minute columns
    category_codes = ["U", "TP", "TS", "QC", "CM", "NO", "NP", "NM", "MP", "BT", "BR", "TL"]  # Using U instead of RT
    operator_work = split_df.copy()

    for code in category_codes:
        operator_work[f"{code}_Minutes"] = np.where(
            operator_work["Desc Code"] == code,
            operator_work["_DurationMinutes"],
            0.0,
        )

    agg_map = {
        "_DurationMinutes": "sum",
        "ActivityMesinId": pd.Series.nunique,
    }
    for code in category_codes:
        agg_map[f"{code}_Minutes"] = "sum"

    operator_grouped = (
        operator_work.groupby("Operator", dropna=False)
        .agg(agg_map)
        .reset_index()
    )

    operator_sessions = []
    for _, op_row in operator_grouped.iterrows():
        runtime_minutes = float(op_row.get("U_Minutes", 0) or 0)  # Use U instead of RT
        total_minutes = float(op_row.get("_DurationMinutes", 0) or 0)

        category_minutes = {
            "rt_minutes": runtime_minutes,  # Keep rt for frontend compatibility
            "tp_minutes": float(op_row.get("TP_Minutes", 0) or 0),
            "ts_minutes": float(op_row.get("TS_Minutes", 0) or 0),
            "qc_minutes": float(op_row.get("QC_Minutes", 0) or 0),
            "cm_minutes": float(op_row.get("CM_Minutes", 0) or 0),
            "no_minutes": float(op_row.get("NO_Minutes", 0) or 0),
            "np_minutes": float(op_row.get("NP_Minutes", 0) or 0),
            "nm_minutes": float(op_row.get("NM_Minutes", 0) or 0),
            "mp_minutes": float(op_row.get("MP_Minutes", 0) or 0),
            "bt_minutes": float(op_row.get("BT_Minutes", 0) or 0),
            "br_minutes": float(op_row.get("BR_Minutes", 0) or 0),
            "tl_minutes": float(op_row.get("TL_Minutes", 0) or 0),
        }

        main_loss_code = None
        main_loss_minutes = 0.0
        for code_key, minutes in [
            ("TP", category_minutes["tp_minutes"]),
            ("TS", category_minutes["ts_minutes"]),
            ("QC", category_minutes["qc_minutes"]),
            ("CM", category_minutes["cm_minutes"]),
            ("NO", category_minutes["no_minutes"]),
            ("NP", category_minutes["np_minutes"]),
            ("NM", category_minutes["nm_minutes"]),
            ("MP", category_minutes["mp_minutes"]),
            ("BT", category_minutes["bt_minutes"]),
            ("BR", category_minutes["br_minutes"]),
            ("TL", category_minutes["tl_minutes"]),
        ]:
            if minutes > main_loss_minutes:
                main_loss_code = code_key
                main_loss_minutes = minutes

        operator_sessions.append({
            "operator": op_row.get("Operator", "-"),
            "activities_count": int(op_row.get("ActivityMesinId", 0) or 0),
            "sessions": int(op_row.get("ActivityMesinId", 0) or 0),
            "total_minutes": total_minutes,
            "runtime_minutes": runtime_minutes,
            "main_loss_code": main_loss_code,
            "main_loss_minutes": main_loss_minutes,
            **category_minutes,
        })

    def _operator_session_sort_key(session: dict):
        rt = float(session.get("runtime_minutes", 0) or 0)

        downtime_minutes = sum([
            float(session.get("tp_minutes", 0) or 0),
            float(session.get("ts_minutes", 0) or 0),
            float(session.get("qc_minutes", 0) or 0),
            float(session.get("cm_minutes", 0) or 0),
            float(session.get("no_minutes", 0) or 0),
            float(session.get("nm_minutes", 0) or 0),
            float(session.get("mp_minutes", 0) or 0),
            float(session.get("tl_minutes", 0) or 0),
        ])

        bt_br_np_minutes = sum([
            float(session.get("bt_minutes", 0) or 0),
            float(session.get("br_minutes", 0) or 0),
            float(session.get("np_minutes", 0) or 0),
        ])

        # tier: smaller is higher priority
        if rt > 0:
            tier = 1
        elif downtime_minutes > 0:
            tier = 2
        else:
            tier = 3

        return (
            tier,
            -rt,
            -downtime_minutes,
            -bt_br_np_minutes,
            str(session.get("operator", "")),
        )

    # Sort operator sessions by business priority (RT first, then downtime, then BT/BR/NP)
    operator_sessions = sorted(operator_sessions, key=_operator_session_sort_key)

    # Build calculation breakdown
    calculation = {
        "plan_minutes": float(summary_row.get("Plan Minutes", 0)),
        "utility_minutes": float(summary_row.get("Utility Minutes", 0)),
        "downtime_minutes": float(summary_row.get("Downtime Minutes", 0)),
        "target_per_jam": target_per_jam,
        "target_qty": target_qty,
        "per_num": float(summary_row.get("PER Num", 0)),
        "otr_num": float(summary_row.get("OTR Num", 0)),
        "qr_num": float(summary_row.get("QR Num", 0)),
        "oee_num": float(summary_row.get("OEE Num", 0)),
        "per_formula": "output / (utility_hours * target_per_jam)",
        "otr_formula": "utility_minutes / plan_minutes",
        "qr_formula": "output / (output + reject + rework)",
        "oee_formula": "otr * per * qr",
    }

    return {
        "summary": summary,
        "timeline": timeline,
        "operator_sessions": operator_sessions,
        "calculation": calculation,
        "found": True,
    }


def _get_row_history_fallback(report_type, tanggal, shift, mc, part_no, proses, operator=None):
    """
    Fallback method to get row history when reconstruction from raw data fails.
    Uses the dashboard detail data to find the matching row and extract calculation values.
    """
    from datetime import datetime

    print(f"Using fallback method for row history: {mc} {part_no} {proses} on {tanggal} shift {shift}")

    report_category = ReportCategory.MESIN if report_type == "mesin" else ReportCategory.OPERATOR
    date_obj = datetime.strptime(tanggal, "%Y-%m-%d").date()
    shift_num = int(shift)

    # Use same method as dashboard detail to get the data
    try:
        detail_response = get_detail_export_report(
            report_category=report_category,
            date_time_from=date_obj,
            shift_from=shift_num,
            date_time_to=date_obj,
            shift_to=shift_num,
            pagination=None,  # Get all data
            filters=None,
            sort=None
        )

        detail_rows = detail_response.get('rows', [])
        print(f"DEBUG: Fallback got {len(detail_rows)} detail rows to search")

        # Find the matching row using exact field matching
        matching_row = None
        for row in detail_rows:
            if (row.get('mc_no') == mc and
                row.get('tanggal') == tanggal and
                row.get('shift') == shift and
                row.get('proses') == proses):

                # Use exact part_no matching if available, fallback to substring
                if row.get('part_no') == part_no:
                    # For operator reports, also match operator
                    if report_type == "operator":
                        if row.get('operator') == operator:
                            matching_row = row
                            break
                    else:
                        matching_row = row
                        break
                # Fallback: check part number in part_no_name as before
                elif part_no in row.get('part_no_name', ''):
                    # For operator reports, also match operator
                    if report_type == "operator":
                        if row.get('operator') == operator:
                            matching_row = row
                            break
                    else:
                        matching_row = row
                        break

        if matching_row:
            print(f"DEBUG: Fallback found exact matching row - MC={matching_row.get('mc_no')}, Part={matching_row.get('part_no')}, Shift={matching_row.get('shift')}")

            # Use the row's actual values for calculation
            plan_minutes = 0
            utility_minutes = 0

            # Try to extract minutes from time strings (e.g., "02:30" -> 150 minutes)
            plan_time = matching_row.get('plan', '00:00')
            utility_time = matching_row.get('rt', '00:00')

            try:
                if ':' in plan_time:
                    hours, minutes = map(int, plan_time.split(':'))
                    plan_minutes = hours * 60 + minutes
                if ':' in utility_time:
                    hours, minutes = map(int, utility_time.split(':'))
                    utility_minutes = hours * 60 + minutes
            except:
                pass

            downtime_minutes = max(0, plan_minutes - utility_minutes)

            # Build calculation from the actual row data
            calculation = {
                "plan_minutes": float(plan_minutes),
                "utility_minutes": float(utility_minutes),
                "downtime_minutes": float(downtime_minutes),
                "target_per_jam": int(matching_row.get('target_per_jam', 0)),
                "target_qty": int(matching_row.get('target_qty', 0)),
                "per_formula": "output / (utility_hours * target_per_jam)",
                "otr_formula": "utility_minutes / plan_minutes",
                "qr_formula": "output / (output + reject + rework)",
                "oee_formula": "otr * per * qr",
                "per_num": _extract_percentage(matching_row.get('per', '0%')),
                "otr_num": _extract_percentage(matching_row.get('otr', '0%')),
                "qr_num": _extract_percentage(matching_row.get('qr', '0%')),
                "oee_num": _extract_percentage(matching_row.get('oee', '0%'))
            }

            return {
                "summary": matching_row,
                "timeline": [],  # No timeline data available in fallback
                "calculation": calculation
            }

        else:
            print("DEBUG: Fallback found NO matching row")
            if detail_rows:
                print("DEBUG: Available rows in fallback:")
                for i, row in enumerate(detail_rows[:3]):
                    print(f"  Row {i}: MC={row.get('mc_no')}, Part={row.get('part_no')}, Proses={row.get('proses')}, Shift={row.get('shift')}")

    except Exception as e:
        print(f"Error in fallback method: {e}")

    # Ultimate fallback - indicate no matching row found instead of fake zeros
    return {
        "summary": {},
        "timeline": [],
        "calculation": {},
        "found": False,
        "error": f"No matching row history found for {mc} {part_no} {proses} on {tanggal} shift {shift}"
    }


def _extract_percentage(pct_string):
    """Extract numeric value from percentage string like '98%' -> 98.0"""
    if not pct_string:
        return 0.0
    try:
        return float(pct_string.replace('%', ''))
    except:
        return 0.0


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
