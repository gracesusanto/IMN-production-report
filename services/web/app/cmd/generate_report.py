import os
from datetime import datetime, time, timedelta
from enum import Enum
import calendar

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.orm import aliased
import pytz

import app.database as database
import app.model.models as models
import app.schema as schema

"""
All timezone-aware dates and times are stored internally in UTC.
They are converted to local time in the zone specified by
the timezone configuration parameter before being displayed to the client.
"""
_JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

_WORKING_SHIFT_JSON = {
    "Saturday": {"start": {"1": 7, "2": 12, "3": 17}, "duration": 5},
    "Weekday": {"start": {"1": 7, "2": 15, "3": 23}, "duration": 8},
}


def _is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current timezone time
    check_time = check_time or datetime.now(_JAKARTA_TZ).time()
    if begin_time < end_time:
        return check_time >= begin_time and check_time < end_time
    else:  # crosses midnight
        return check_time >= begin_time or check_time < end_time


def _calculate_shift(row):
    date_time = datetime.strptime(row, "%m/%d/%Y %H:%M:%S")
    return _calculate_shift_from_datetime(date_time)


def _calculate_shift_from_datetime(date_time):
    comp_time = date_time.time()
    if date_time.isoweekday() == 7:  # Sunday
        return 1
    else:
        working_shift = _WORKING_SHIFT_JSON

        day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"
        # Adjusting day based on time (for early morning considerations)
        if comp_time < time(7, 0) and day_of_week == "Saturday":  # Before 7 AM Saturday
            day_of_week = "Weekday"
        duration = working_shift[day_of_week]["duration"]
        for shift, timestamp in working_shift[day_of_week]["start"].items():
            if _is_time_between(
                time(timestamp, 00), time((timestamp + duration) % 24, 00), comp_time
            ):
                return int(shift)

    return 1


def get_curr_datetime():
    return datetime.now(_JAKARTA_TZ).date()


def get_curr_shift():
    return _calculate_shift_from_datetime(datetime.now(_JAKARTA_TZ))


def _get_csv_filename(type, date_from, shift_from, date_to, shift_to):
    try:
        date_from = date_from.date()
        date_to = date_to.date()
    except:
        date_from = date_from
        date_to = date_to

    if date_from == date_to:
        if shift_from == shift_to:
            return f"result_{type}_{date_from}_shift_{shift_from}"
        else:
            return f"result_{type}_{date_from}_shift_{shift_from}_to_shift_{shift_to}"
    else:
        return f"result_{type}_{date_from}_shift_{shift_from}_to_{date_to}_shift_{shift_to}"


def _get_csv_folder(format, type, date_from, shift_from, date_to, shift_to):
    filename = _get_csv_filename(type, date_from, shift_from, date_to, shift_to)
    directory = f"data/report/{format}/{type}"
    if not os.path.exists(directory):
        os.makedirs(directory)

    return f"{directory}/{filename}"


def _convert_seconds(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)

    if h > 0 and m > 0 and s > 0:
        return f"{h:d}h {m:d}min {s:d}sec"
    elif m > 0 and s > 0:
        return f"{m:d}min {s:d}sec"
    else:
        return f"{s:d}sec"


def _calculate_datetime_from_shift(date_time, shift):
    year = date_time.year
    month = date_time.month
    day = date_time.day

    hour_from = 0

    if date_time.isoweekday() != 7:  # Not Sunday
        working_shift = _WORKING_SHIFT_JSON

        day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"
        hour_from = working_shift[day_of_week]["start"][shift]

        # Get time in UTC (from GMT +7)
        time_from = datetime(year, month, day, hour_from, 0) - timedelta(hours=7)
        time_to = time_from + timedelta(hours=working_shift[day_of_week]["duration"])

        return time_from, time_to

    return datetime(year, month, day, 0, 0), datetime(year, month, day, 0, 0)


def _correct_invalid_shift(shift):
    shift = max(int(shift), 1)
    shift = min(int(shift), 3)
    return str(shift)


def _fill_default_datetime(
    date_from=None, shift_from: str = "1", date_to=None, shift_to: str = "3"
):
    # Fill None dates with today's date
    if date_from is None and date_to is None:
        date_from = date_to = datetime.now(_JAKARTA_TZ)
    elif date_from is None:
        date_from = date_to
    elif date_to is None:
        date_to = date_from

    if shift_from == None:
        shift_from = "1"
    if shift_to == None:
        shift_to = "3"

    shift_from = _correct_invalid_shift(shift_from)
    shift_to = _correct_invalid_shift(shift_to)

    # Make sure from < to
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    elif date_to == date_from:
        if shift_to < shift_from:
            shift_to, shift_from = shift_from, shift_to

    return date_from, shift_from, date_to, shift_to


def _calculate_datetime_range(
    date_from=None, shift_from: str = "1", date_to=None, shift_to: str = "3"
):
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(
        date_from, shift_from, date_to, shift_to
    )
    time_from, _ = _calculate_datetime_from_shift(date_from, shift_from)
    _, time_to = _calculate_datetime_from_shift(date_to, shift_to)

    return time_from, time_to


def _get_month_range(year=None, month=None):
    today = datetime.now()
    if year is None or month is None:
        year = year or today.year
        month = month or today.month

    if year == 0:
        year = today.year
    if month == 0:
        month = today.month

    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)
    return first_day, last_day, year, month

def _generate_keterangan(row):
    """
    Generates a description string based on available Keterangan, Coil No, Lot No, and Pack No.
    Ensures the result does not contain unnecessary trailing commas.
    """
    fields = [
        f"Keterangan: {row['Keterangan']}" if row["Keterangan"] else "",
        f"Coil No: {row['Coil No']}" if row["Coil No"] else "",
        f"Lot No: {row['Lot No']}" if row["Lot No"] else "",
        f"Pack No: {row['Pack No']}" if row["Pack No"] else "",
    ]

    return ", ".join(filter(None, fields))  # Filters out empty strings


def _generate_keterangan_limax(row):
    """
    Extends _generate_keterangan by adding Reject and Rework details.
    Ensures that the generated description does not contain unnecessary trailing commas.
    """
    fields = [
        f"Reject: {row['Reject']}" if row["Reject"] else "",
        f"Rework: {row['Rework']}" if row["Rework"] else "",
    ]

    return ", ".join(filter(None, fields + [_generate_keterangan(row)]))  # Concatenates and filters


def _format_time_for_limax(time):
    # Convert to limax hour format: HHMM
    dt = datetime.strptime(time, "%H:%M:%S").strftime("%H%M")
    # Convert 00 hour into 24
    if dt[:2] == "00":
        return f"24{dt[2:]}"
    else:
        return dt


engine = database.get_engine()
session = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _calculate_productivity(row):
    if row["Desc"] != "U : Utility":
        return 0

    try:
        # Productivity (%) = (Output pcs / Waktu hr) / Target pcs/hr
        productivity = ((row["Qty"] / (row["Duration"] / 3600.0)) / row["Target"]) * 100
    except:
        productivity = 0
    return productivity


def _calculate_ratio(row, type):
    # Qty is just qty of OK, not total
    total = row["Qty"] + row["Reject"] + row["Rework"]
    if total == 0:
        return 0
    return row[type] / total * 100


def _filter_df(df, filters):
    conditions = []

    for field, filter_condition in filters.items():
        if field not in ["Productivity", "Reject Ratio", "Rework Ratio"]:
            continue
        if filter_condition.lt is not None:
            conditions.append(df[field] <= filter_condition.lt)
        if filter_condition.gt is not None:
            conditions.append(df[field] >= filter_condition.gt)

    if conditions:
        overall_condition = pd.concat(conditions, axis=1).all(axis=1)
        df = df[overall_condition]

    return df


def query_activity_mesin(time_from, time_to):
    """
    Query activity records from mesin_log and activity_mesin tables.
    Fetches start/stop times, operators, tooling, and machine info.
    """
    activity_start = aliased(models.MesinLog)
    activity_stop = aliased(models.MesinLog)

    query = (
        session.query(
            models.ActivityMesin.id,
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Operator.nik.label("NIK"),
            models.Tooling.id.label("Tooling"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            models.Tooling.part_no.label("Part No"),
            models.Tooling.part_name.label("Part Name"),
            models.Tooling.std_jam.label("Target"),
            activity_start.timestamp.label("Start"),
            activity_stop.timestamp.label("Stop"),
            models.ActivityMesin.category.label("Desc"),
            models.ActivityMesin.output.label("Qty"),
            models.ActivityMesin.reject.label("Reject"),
            models.ActivityMesin.rework.label("Rework"),
            models.ActivityMesin.coil_no.label("Coil No"),
            models.ActivityMesin.lot_no.label("Lot No"),
            models.ActivityMesin.pack_no.label("Pack No"),
            models.ActivityMesin.keterangan.label("Keterangan"),
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
        expected_columns = [
            "MC", "Operator", "NIK", "Tooling", "Kode Tooling", "Common Tooling Name",
            "Part No", "Part Name", "Target", "Start", "Stop", "Desc",
            "Qty", "Reject", "Rework", "Coil No", "Lot No", "Pack No", "Keterangan"
        ]
        df = pd.DataFrame(columns=expected_columns)

    # Ensure default values for missing fields
    for col in ["Coil No", "Lot No", "Pack No", "Keterangan"]:
        df[col] = df[col].fillna("").replace("-", "")

    df["Keterangan"] = df.apply(_generate_keterangan, axis=1)
    df["Keterangan Limax"] = df.apply(_generate_keterangan_limax, axis=1)

    df.drop(["Coil No", "Lot No", "Pack No"], axis=1, inplace=True)

    return df

def _convert_to_jakarta_time(timestamp, fmt="%m/%d/%Y %H:%M:%S"):
    """Converts UTC timestamp to Jakarta time and formats it."""
    return (
        pd.to_datetime(timestamp, utc=True)
        .map(lambda x: x.tz_convert(_JAKARTA_TZ))
        .dt.strftime(fmt)
    )

def _format_percent(value):
    """Formats percentage values to two decimal places."""
    return f"{value:.2f}%"

def _insert_missing_records(df):
    """Handles missing 'Not Known' (NK) records for operator reports."""
    df = df.sort_values(by=["Operator", "Start"]).reset_index(drop=True)

    for index in range(1, len(df)):
        same_operator = df.loc[index, "Operator"] == df.loc[index - 1, "Operator"]
        start_mismatch = df.loc[index, "Start"] != df.loc[index - 1, "Stop"]

        # Insert NK when there's a gap, excluding No Plan (NP) and Break Time (BT)
        if same_operator and start_mismatch and df.loc[index, "Desc"][:2] not in ["NP", "BT"]:
            insert_row = {
                "Operator": df.loc[index]["Operator"],
                "Start": df.loc[index - 1]["Stop"],
                "Stop": df.loc[index]["Start"],
                "Desc": "NK : Not Known",
            }
            df = pd.concat([df, pd.DataFrame([insert_row])])

        # Ensure previous stop matches next start
        if same_operator and start_mismatch:
            df.loc[index - 1, "Stop"] = df.loc[index]["Start"]

    return df.sort_values(by=["Operator", "Start"]).reset_index(drop=True)

def df_to_report(df, report_category, filters, sort):
    """Transforms the raw DataFrame into a structured report format."""
    df["Tanggal"] = _convert_to_jakarta_time(df.Start, "%d/%m/%Y")
    df["StartTime"] = _convert_to_jakarta_time(df.Start, "%H:%M:%S")
    df["StopTime"] = _convert_to_jakarta_time(df.Stop, "%H:%M:%S")
    df["Start"] = _convert_to_jakarta_time(df.Start)
    df["Stop"] = _convert_to_jakarta_time(df.Stop)
    df["Shift"] = df["Start"].apply(lambda x: _calculate_shift(x))

    if report_category == ReportCategory.OPERATOR:
        df.drop(df[df["Desc"] == "NP : No Plan"].index, inplace=True)

    # Operator BT and BR are non mesin and tooling related downtime
    # So the MC and Tooling are `0`
    columns_to_replace = [
        "MC", "Tooling", "Kode Tooling", "Common Tooling Name", "Part No", "Part Name"
    ]
    df.loc[:, columns_to_replace] = df.loc[:, columns_to_replace].replace([0, None, np.nan], "-")

    if report_category == ReportCategory.MESIN:
        df = df[df["MC"] != "-"]  # Remove empty machine entries

    # Compute and format duration
    df["Duration"] = (pd.to_datetime(df.Stop) - pd.to_datetime(df.Start)).dt.total_seconds()
    df["Duration"] = df["Duration"].apply(_convert_seconds)

    # Compute key metrics
    df["Productivity"] = df.apply(_calculate_productivity, axis=1)
    df["Reject Ratio"] = df.apply(_calculate_ratio, type="Reject", axis=1)
    df["Rework Ratio"] = df.apply(_calculate_ratio, type="Rework", axis=1)

    # Convert percentages to formatted strings
    df["Productivity"] = df["Productivity"].map(_format_percent)
    df["Reject Ratio"] = df["Reject Ratio"].map(_format_percent)
    df["Rework Ratio"] = df["Rework Ratio"].map(_format_percent)

    # Fill missing values with 0 and convert numeric columns
    df = df.fillna(0)
    df[["Qty", "Reject", "Rework"]] = df[["Qty", "Reject", "Rework"]].astype(int)

    # Sorting logic
    primary_sort = "Operator" if report_category == ReportCategory.OPERATOR else "MC"

    if filters:
        df = _filter_df(df, filters)

    if sort:
        df = df.sort_values(by=[sort.sort_by], ascending=(sort.direction == "ascending"))
    else:
        df = df.sort_values(by=[primary_sort, "Start"]).reset_index(drop=True)

    # Additional columns
    df["Plant"] = df["MC"].apply(lambda mc: mc[-1])
    df["Awal"] = df["StartTime"].apply(_format_time_for_limax)
    df["Akhir"] = df["StopTime"].apply(_format_time_for_limax)

    df["Kode Keterangan"] = df["Desc"].apply(lambda desc: desc[:2].strip())

    df.drop(columns=["Start", "Stop"], inplace=True)

    return df

def merge_consecutive_downtime(df, report_category):
    """
    Merge consecutive downtime events that belong to the same machine (for mesin report)
    or the same operator (for operator report) with the same category (Desc).

    - Takes the **earliest StartTime** and **latest StopTime** for consecutive entries.
    - Works only when there is a downtime event (`Desc` is the same).
    """

    # Determine which column to use for grouping (MC for mesin, Operator for operator)
    group_col = "MC" if report_category == ReportCategory.MESIN else "Operator"

    # Sort by the grouping column and start time
    df = df.sort_values(by=[group_col, "StartTime"]).reset_index(drop=True)

    merged_rows = []
    prev_row = None

    for _, row in df.iterrows():
        if prev_row is not None:
            # Check if the downtime (Desc) and group_col (MC or Operator) are the same as previous
            if row[group_col] == prev_row[group_col] and row["Desc"] == prev_row["Desc"] and row["Tooling"] == prev_row["Tooling"]:
                # Update the previous row's StopTime to the latest one
                prev_row["StopTime"] = max(prev_row["StopTime"], row["StopTime"])
                continue  # Skip adding a new row, just update previous

        # If the condition is not met, append the previous row to the final list
        if prev_row is not None:
            merged_rows.append(prev_row)

        prev_row = row.copy()  # Move to next row

    # Append the last processed row
    if prev_row is not None:
        merged_rows.append(prev_row)

    return pd.DataFrame(merged_rows)

class ReportCategory(Enum):
    MESIN = "mesin"
    OPERATOR = "operator"


def get_report(
    report_category: ReportCategory,
    format: schema.FormatType = schema.FormatType.LIMAX,
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None,
    pagination=None, filters=None, sort=None,
    is_backup=None, backup_year=None, backup_month=None
):
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(
        date_time_from, shift_from, date_time_to, shift_to
    )


    if not is_backup:
        time_from, time_to = _calculate_datetime_range(
            date_from=date_from, shift_from=shift_from,
            date_to=date_to, shift_to=shift_to,
        )
    else:
        time_from, time_to, backup_year, backup_month = _get_month_range(backup_year, backup_month)


    if ("limax" in format.value) or (is_backup == True) :
        pagination = filters = sort = None

    df = query_activity_mesin(time_from, time_to)
    df = df_to_report(df, report_category, filters, sort)
    df = merge_consecutive_downtime(df, report_category)

    if pagination:
        df = df.iloc[(pagination.page - 1) * pagination.page_size : pagination.page * pagination.page_size]

    sort_by_first = "Operator" if report_category == ReportCategory.OPERATOR else "MC"
    sort_by_next = "MC" if report_category == ReportCategory.OPERATOR else "Operator"

    # imn report
    df_imn = df.copy(deep=True)
    imn_header = [
        sort_by_first, "Shift", "Tanggal", "StartTime", "StopTime", sort_by_next,
        "Kode Tooling", "Common Tooling Name", "Part No", "Part Name", "Qty", "Target",
        "Reject", "Rework", "Desc", "Duration", "Productivity", "Reject Ratio", "Rework Ratio", "Keterangan",
    ]

    # Ensure all required columns exist (add missing columns with default values)
    for col in imn_header:
        if col not in df_imn.columns:
            df_imn[col] = "" if col in ["Desc", "Keterangan", "Duration", "Productivity", "Reject Ratio", "Rework Ratio",
                                        "Tanggal", "StartTime", "StopTime", "Kode Tooling", "Common Tooling Name",
                                        "Part No", "Part Name"] else 0

    df_imn = df_imn[imn_header]

    df_imn.to_csv(
        _get_csv_folder(
            format="imn", type=report_category.value, date_from=date_from,
            shift_from=shift_from, date_to=date_to, shift_to=shift_to,
        ), sep=";",
    )

    # limax report
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

    # Ensure all required columns exist for LIMAX format
    for original_col in limax_header.keys():
        if original_col not in df_limax.columns:
            df_limax[original_col] = "" if original_col in ["Tanggal", "Kode Tooling", "Keterangan Limax", "Kode Keterangan", "Awal", "Akhir"] else 0

    df_limax.rename(columns=limax_header, inplace=True)
    limax_col = [
        "STR_DATE", "STR_PLNT", "TLG_CODE", "STR_KUAN", "PEG_CODE",
        "SHF_CODE", "MSN_CODE", "STR_AWAL", "STR_AKHR", "DWN_CODE", "STR_DESC",
    ]

    # Ensure all LIMAX columns exist after renaming
    for col in limax_col:
        if col not in df_limax.columns:
            df_limax[col] = ""

    # Remove columns that are not in limax_col
    for col in list(df_limax.columns):
        if col not in limax_col:
            df_limax.drop(columns=col, inplace=True)

    df_limax = df_limax[limax_col].astype(str)

    df_limax.to_csv(
        _get_csv_folder(
            format="limax", type=report_category.value, date_from=date_from,
            shift_from=shift_from, date_to=date_to, shift_to=shift_to,
        ), sep=";", index=False,
    )

    if is_backup == True:
        filename = backup_filename(
            report_category=report_category,
            format=format,
            year=backup_year,
            month=backup_month,
        )
    else:
        filename = _get_csv_filename(
            report_category.value,
            date_from=date_from, shift_from=shift_from,
            date_to=date_to, shift_to=shift_to,
        )

    if "limax" in format.value:
        return df_limax, filename
    else:
        return df_imn, filename


def get_mesin_report(
    format: schema.FormatType,
    date_time_from: datetime = None,
    shift_from: int = None,
    date_time_to: datetime = None,
    shift_to: int = None,
    pagination=None,
    filters=None,
    sort=None,
    is_backup=None, backup_year=None, backup_month=None,
):
    return get_report(
        ReportCategory.MESIN,
        format,
        date_time_from,
        shift_from,
        date_time_to,
        shift_to,
        pagination,
        filters,
        sort,
        is_backup,
        backup_year,
        backup_month,
    )


def get_operator_report(
    format: schema.FormatType,
    date_time_from: datetime = None,
    shift_from: int = None,
    date_time_to: datetime = None,
    shift_to: int = None,
    pagination=None,
    filters=None,
    sort=None,
    is_backup=None, backup_year=None, backup_month=None,
):
    return get_report(
        ReportCategory.OPERATOR,
        format,
        date_time_from,
        shift_from,
        date_time_to,
        shift_to,
        pagination,
        filters,
        sort,
        is_backup,
        backup_year,
        backup_month,
    )

def backup_filename(report_category: ReportCategory,
    format: schema.FormatType,
    year=None, month=None):

    directory = f"backup/report"
    if not os.path.exists(directory):
        os.makedirs(directory)

    if year is None or month is None:
        now = datetime.now()
        year = year or now.year
        month = month or now.month

    formatted_date = f"{year}_{month:02d}"
    filename = f"{directory}/backup_{report_category.value}_{format}_{formatted_date}.csv"
    return filename

if __name__ == "__main__":
    get_mesin_report(date_time_from=datetime(2023, 6, 14, 0, 0, 0))
    get_operator_report(date_time_from=datetime(2023, 6, 14, 0, 0, 0))
