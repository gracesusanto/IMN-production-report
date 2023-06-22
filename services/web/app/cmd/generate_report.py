import os
from datetime import datetime, time, timedelta
from enum import Enum
import csv

import pandas
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
_TIMEZONE = pytz.timezone("Asia/Jakarta")

_WORKING_SHIFT_JSON = {
    "Saturday": {"start": {"1": 7, "2": 12, "3": 17}, "duration": 5},
    "Weekday": {"start": {"1": 7, "2": 15, "3": 23}, "duration": 8},
}


def _is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current timezone time
    check_time = check_time or datetime.now(_TIMEZONE).time()
    if begin_time < end_time:
        return check_time >= begin_time and check_time < end_time
    else:  # crosses midnight
        return check_time >= begin_time or check_time < end_time


def _calculate_shift(row):
    date_time = datetime.strptime(row, "%m/%d/%Y %H:%M:%S")
    return f"'{_calculate_shift_from_datetime(date_time)}"


def _calculate_shift_from_datetime(date_time):
    comp_time = date_time.time()
    if date_time.isoweekday() == 7:  # Sunday
        return 0
    else:
        working_shift = _WORKING_SHIFT_JSON

        day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"
        duration = working_shift[day_of_week]["duration"]
        for shift, timestamp in working_shift[day_of_week]["start"].items():
            if _is_time_between(
                time(timestamp, 00), time((timestamp + duration) % 24, 00), comp_time
            ):
                return int(shift)

    return 0


def get_curr_datetime():
    return datetime.now(_TIMEZONE).date()


def get_curr_shift():
    return _calculate_shift_from_datetime(datetime.now(_TIMEZONE))


def _get_csv_filename(type, date_from, shift_from, date_to, shift_to):
    try:
        date_from = date_from.date()
        date_to = date_to.date()
    except:
        date_from = date_from
        date_to = date_to

    if date_from == date_to:
        if shift_from == shift_to:
            return f"result_{type}_{date_from}_shift_{shift_from}.csv"
        else:
            return (
                f"result_{type}_{date_from}_shift_{shift_from}_to_shift_{shift_to}.csv"
            )
    else:
        return f"result_{type}_{date_from}_shift_{shift_from}_to_{date_to}_shift_{shift_to}.csv"


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
        date_from = date_to = datetime.now(_TIMEZONE)
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


def _generate_keterangan(row):
    keterangan = (
        (f"Coil No: {row['Coil No']}, " if row["Coil No"] else "")
        + (f"Lot No: {row['Lot No']}, " if row["Lot No"] else "")
        + (f"Pack No: {row['Pack No']}" if row["Pack No"] else "")
    )

    if keterangan[-2::] == ", ":
        keterangan = keterangan[:-2]
    return keterangan


def _generate_keterangan_limax(row):
    keterangan = (f"Reject: {row['Reject']}, " if row["Reject"] else "") + (
        f"Rework: {row['Rework']}, " if row["Rework"] else ""
    )

    keterangan += _generate_keterangan(row)

    if keterangan[-2::] == ", ":
        keterangan = keterangan[:-2]
    return f"'{keterangan}"


def _format_time_for_limax(time):
    return datetime.strptime(time, "%H:%M:%S").strftime("'%H%M")


engine = database.get_engine()
session = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def query_activity_mesin(time_from, time_to):
    activity_start = aliased(models.MesinLog)
    activity_stop = aliased(models.MesinLog)

    query = (
        session.query(models.ActivityMesin)
        .join(models.Mesin)
        .join(activity_start, models.ActivityMesin.start_time)
        .join(activity_stop, models.ActivityMesin.stop_time)
        .join(models.Operator, models.Operator.id == activity_start.operator_id)
        .join(models.Tooling, models.Tooling.id == activity_start.tooling_id)
        .with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Operator.nik.label("NIK"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            activity_start.timestamp.label("Start"),
            activity_stop.timestamp.label("Stop"),
            models.ActivityMesin.downtime_category.label("Desc"),
            models.ActivityMesin.output.label("Qty"),
            models.ActivityMesin.reject.label("Reject"),
            models.ActivityMesin.rework.label("Rework"),
            models.ActivityMesin.coil_no.label("Coil No"),
            models.ActivityMesin.lot_no.label("Lot No"),
            models.ActivityMesin.pack_no.label("Pack No"),
        )
        .filter(activity_start.timestamp >= time_from)
        .filter(activity_start.timestamp < time_to)
        .order_by(models.Mesin.name.asc(), activity_start.timestamp.asc())
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Coil No"] = df["Coil No"].fillna("").replace("-", "")
    df["Lot No"] = df["Lot No"].fillna("").replace("-", "")
    df["Pack No"] = df["Pack No"].fillna("").replace("-", "")
    df["Keterangan"] = df.apply(lambda row: _generate_keterangan(row), axis=1)
    df["Keterangan Limax"] = df.apply(
        lambda row: _generate_keterangan_limax(row), axis=1
    )
    df.drop(["Coil No", "Lot No", "Pack No"], axis=1)
    return df


class ReportCategory(Enum):
    MESIN = "mesin"
    OPERATOR = "operator"


def get_report(
    report_category: ReportCategory,
    format: schema.FormatType = schema.FormatType.LIMAX,
    date_time_from=None,
    shift_from=None,
    date_time_to=None,
    shift_to=None,
):
    date_from, shift_from, date_to, shift_to = _fill_default_datetime(
        date_time_from, shift_from, date_time_to, shift_to
    )

    time_from, time_to = _calculate_datetime_range(
        date_from=date_from,
        shift_from=shift_from,
        date_to=date_to,
        shift_to=shift_to,
    )

    df = query_activity_mesin(time_from, time_to)

    df["Tanggal"] = (
        pandas.to_datetime(df.Start, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%d/%m/%Y")
    )
    df["StartTime"] = (
        pandas.to_datetime(df.Start, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%H:%M:%S")
    )
    df["StopTime"] = (
        pandas.to_datetime(df.Stop, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%H:%M:%S")
    )

    df["Start"] = (
        pandas.to_datetime(df.Start, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%m/%d/%Y %H:%M:%S")
    )
    df["Stop"] = (
        pandas.to_datetime(df.Stop, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%m/%d/%Y %H:%M:%S")
    )
    df["Shift"] = df["Start"].apply(lambda x: _calculate_shift(x))

    if report_category == ReportCategory.OPERATOR:
        for index, _ in df.iterrows():
            if index == 0:
                continue

            # Remove No Plan and BreakTime from Operator's Downtime
            if (
                (df.loc[index]["Operator"] == df.loc[index - 1]["Operator"])
                and (df.loc[index]["Start"] != df.loc[index - 1]["Stop"])
                and (
                    df.loc[index]["Desc"][:2] != "NP"
                    and df.loc[index]["Desc"][:2] != "BT"
                )
            ):
                insert_row = {
                    "Operator": df.loc[index]["Operator"],
                    "Start": df.loc[index - 1]["Stop"],
                    "Stop": df.loc[index]["Start"],
                    "Desc": "NK : Not Known",
                }
                df = pandas.concat([df, pandas.DataFrame([insert_row])])
        df.drop(df.loc[df["Desc"] == "NP : No Plan"].index, inplace=True)
        df = df.sort_values(by=["Operator", "Start"]).reset_index(drop=True)

    df["Duration"] = pandas.to_datetime(df.Stop) - pandas.to_datetime(df.Start)
    df["Duration"] = df["Duration"].dt.total_seconds()
    df["Duration"] = df["Duration"].apply(lambda x: _convert_seconds(x))

    df = df.fillna(0)
    df["Qty"] = df["Qty"].astype(int)
    df["Reject"] = df["Reject"].astype(int)
    df["Rework"] = df["Rework"].astype(int)

    df["Plant"] = df["MC"].apply(lambda MC: MC[-1])
    df["Awal"] = df["StartTime"].apply(_format_time_for_limax)
    df["Akhir"] = df["StopTime"].apply(_format_time_for_limax)
    df["Kode Keterangan"] = df["Desc"].apply(lambda Desc: Desc[0:2].strip())

    sort_by_first = "Operator" if report_category == ReportCategory.OPERATOR else "MC"
    sort_by_next = "MC" if report_category == ReportCategory.OPERATOR else "Operator"

    df = df.sort_values(by=[sort_by_first, "Start"]).reset_index(drop=True)

    df.drop(["Start", "Stop"], axis=1, inplace=True)

    # imn report
    df_imn = df.copy(deep=True)
    imn_header = [
        sort_by_first,
        "Shift",
        "Tanggal",
        "StartTime",
        "StopTime",
        sort_by_next,
        "Kode Tooling",
        "Common Tooling Name",
        "Qty",
        "Reject",
        "Rework",
        "Desc",
        "Duration",
        "Keterangan",
    ]
    df_imn = df_imn[imn_header]

    df_imn.to_csv(
        _get_csv_folder(
            format="imn",
            type=report_category.value,
            date_from=date_from,
            shift_from=shift_from,
            date_to=date_to,
            shift_to=shift_to,
        ),
        sep=";",
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
    df_limax.rename(columns=limax_header, inplace=True)
    limax_col = [
        "STR_DATE",
        "STR_PLNT",
        "TLG_CODE",
        "STR_KUAN",
        "PEG_CODE",
        "SHF_CODE",
        "MSN_CODE",
        "STR_AWAL",
        "STR_AKHR",
        "DWN_CODE",
        "STR_DESC",
    ]
    for col in df_limax.columns:
        if col not in limax_col:
            df_limax.drop(columns=col, inplace=True)

    df_limax = df_limax[limax_col].astype(str)

    df_limax.to_csv(
        _get_csv_folder(
            format="limax",
            type=report_category.value,
            date_from=date_from,
            shift_from=shift_from,
            date_to=date_to,
            shift_to=shift_to,
        ),
        sep=";",
        index=False,
    )

    filename = _get_csv_filename(
        report_category.value,
        date_from=date_from,
        shift_from=shift_from,
        date_to=date_to,
        shift_to=shift_to,
    )

    if format == schema.FormatType.LIMAX:
        return df_limax, filename
    else:
        return df_imn, filename


def get_mesin_report(
    format: schema.FormatType,
    date_time_from: datetime = None,
    shift_from: int = None,
    date_time_to: datetime = None,
    shift_to: int = None,
):
    return get_report(
        ReportCategory.MESIN, format, date_time_from, shift_from, date_time_to, shift_to
    )


def get_operator_report(
    format: schema.FormatType,
    date_time_from: datetime = None,
    shift_from: int = None,
    date_time_to: datetime = None,
    shift_to: int = None,
):
    return get_report(
        ReportCategory.OPERATOR,
        format,
        date_time_from,
        shift_from,
        date_time_to,
        shift_to,
    )


if __name__ == "__main__":
    get_mesin_report(date_time_from=datetime(2023, 6, 14, 0, 0, 0))
    get_operator_report(date_time_from=datetime(2023, 6, 14, 0, 0, 0))
