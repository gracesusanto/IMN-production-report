import os
from datetime import datetime, time, timedelta
import json

import pandas
import sqlalchemy as sa
from sqlalchemy.orm import aliased
import pytz

import database
import models

"""
All timezone-aware dates and times are stored internally in UTC. 
They are converted to local time in the zone specified by 
the timezone configuration parameter before being displayed to the client.
"""
_TIMEZONE = pytz.timezone("Asia/Jakarta")

_WORKING_SHIFT_JSON = "working_shift.json"


def _is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current timezone time
    check_time = check_time or datetime.now(_TIMEZONE)
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
        return 3
    else:
        with open(_WORKING_SHIFT_JSON, "r") as openfile:
            working_shift = json.load(openfile)

            day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"
            duration = working_shift[day_of_week]["duration"]
            for shift, timestamp in working_shift[day_of_week]["start"].items():
                if _is_time_between(
                    time(timestamp, 00),
                    time((timestamp + duration) % 24, 00),
                    comp_time,
                ):
                    return shift

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


def _get_csv_folder(type, date_from, shift_from, date_to, shift_to):
    filename = _get_csv_filename(type, date_from, shift_from, date_to, shift_to)
    directory = f"data/report/{type}"
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
        with open(_WORKING_SHIFT_JSON, "r") as file:
            working_shift = json.load(file)

            day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"
            hour_from = working_shift[day_of_week]["start"][shift]

            # Get time in UTC (from GMT +7)
            time_from = datetime(year, month, day, hour_from, 0) - timedelta(hours=7)
            time_to = time_from + timedelta(
                hours=working_shift[day_of_week]["duration"]
            )

            return time_from, time_to

    return datetime(year, month, day, 0, 0), datetime(year, month, day, 0, 0)


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

    shift_from = str(shift_from)
    shift_to = str(shift_to)

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


engine = database.get_engine()
session = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)()

col_order = [
    "MC",
    "Operator",
    "Kode Tooling",
    "Common Tooling Name",
    "Start",
    "Stop",
    "Desc",
    "Qty",
    "Reject",
    "Rework",
]


def query_continued_downtime(time_from, time_to):
    continued_downtime_start = aliased(models.Stop)
    continued_downtime_stop = aliased(models.Stop)

    query = (
        session.query(models.ContinuedDowntimeMesin)
        .join(models.Mesin)
        .join(continued_downtime_start, models.ContinuedDowntimeMesin.start_time)
        .join(continued_downtime_stop, models.ContinuedDowntimeMesin.stop_time)
        .join(
            models.Operator, models.Operator.id == continued_downtime_start.operator_id
        )
        .join(models.Tooling, models.Tooling.id == continued_downtime_start.tooling_id)
        .with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            continued_downtime_start.timestamp.label("Start"),
            continued_downtime_stop.timestamp.label("Stop"),
            models.ContinuedDowntimeMesin.downtime_category.label("Desc"),
            models.ContinuedDowntimeMesin.reject.label("Reject"),
            models.ContinuedDowntimeMesin.rework.label("Rework"),
        )
        .filter(continued_downtime_start.timestamp >= time_from)
        .filter(continued_downtime_start.timestamp < time_to)
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Qty"] = 0
    return df[col_order]


def query_last_downtime(time_from, time_to):
    last_downtime_start = aliased(models.Stop)
    last_downtime_stop = aliased(models.Start)

    query = (
        session.query(models.LastDowntimeMesin)
        .join(models.Mesin)
        .join(last_downtime_start, models.LastDowntimeMesin.start_time)
        .join(last_downtime_stop, models.LastDowntimeMesin.stop_time)
        .join(models.Operator, models.Operator.id == last_downtime_start.operator_id)
        .join(models.Tooling, models.Tooling.id == last_downtime_start.tooling_id)
        .with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            last_downtime_start.timestamp.label("Start"),
            last_downtime_stop.timestamp.label("Stop"),
            models.LastDowntimeMesin.downtime_category.label("Desc"),
            models.LastDowntimeMesin.reject.label("Reject"),
            models.LastDowntimeMesin.rework.label("Rework"),
        )
        .filter(last_downtime_start.timestamp >= time_from)
        .filter(last_downtime_start.timestamp < time_to)
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Qty"] = 0
    return df[col_order]


def query_utility(time_from, time_to):
    utility_start = aliased(models.Start)
    utility_stop = aliased(models.Stop)

    query = (
        session.query(models.UtilityMesin)
        .join(models.Mesin)
        .join(utility_start, models.UtilityMesin.start_time)
        .join(utility_stop, models.UtilityMesin.stop_time)
        .join(models.Operator, models.Operator.id == utility_start.operator_id)
        .join(models.Tooling, models.Tooling.id == utility_start.tooling_id)
        .with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            utility_start.timestamp.label("Start"),
            utility_stop.timestamp.label("Stop"),
            models.UtilityMesin.output.label("Qty"),
            models.UtilityMesin.reject.label("Reject"),
            models.UtilityMesin.rework.label("Rework"),
        )
        .filter(utility_start.timestamp >= time_from)
        .filter(utility_start.timestamp < time_to)
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Desc"] = "U : Utility"
    return df[col_order]


def get_mesin_report(
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None
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

    df = (
        pandas.concat(
            [
                query_utility(time_from, time_to),
                query_continued_downtime(time_from, time_to),
                query_last_downtime(time_from, time_to),
            ],
            axis=0,
        )
        .sort_values(by=["MC", "Start"])
        .reset_index(drop=True)
    )

    df["Tanggal"] = (
        pandas.to_datetime(df.Start, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%m/%d/%Y")
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

    df["Duration"] = pandas.to_datetime(df.Stop) - pandas.to_datetime(df.Start)
    df["Duration"] = df["Duration"].dt.total_seconds()
    df["Duration"] = df["Duration"].apply(lambda x: _convert_seconds(x))

    df = df.fillna(0)
    df["Qty"] = df["Qty"].astype(int)
    df["Reject"] = df["Reject"].astype(int)
    df["Rework"] = df["Rework"].astype(int)

    df.drop(["Start", "Stop"], axis=1, inplace=True)
    header = [
        "MC",
        "Shift",
        "Tanggal",
        "StartTime",
        "StopTime",
        "Kode Tooling",
        "Common Tooling Name",
        "Operator",
        "Qty",
        "Reject",
        "Rework",
        "Desc",
        "Duration",
        "Keterangan",
    ]
    df = df[header]
    print(df)

    df.to_csv(
        _get_csv_folder(
            "mesin",
            date_from=date_from,
            shift_from=shift_from,
            date_to=date_to,
            shift_to=shift_to,
            sep=";",
        )
    )
    return df, _get_csv_filename(
        "mesin",
        date_from=date_from,
        shift_from=shift_from,
        date_to=date_to,
        shift_to=shift_to,
    )


def query_continued_downtime_operator(time_from, time_to):
    continued_downtime_start = aliased(models.Stop)
    continued_downtime_stop = aliased(models.Stop)

    query = (
        session.query(models.ContinuedDowntimeMesin)
        .join(models.Operator)
        .join(continued_downtime_start, models.ContinuedDowntimeMesin.start_time)
        .join(continued_downtime_stop, models.ContinuedDowntimeMesin.stop_time)
        .join(models.Mesin)
        .join(models.Tooling, models.Tooling.id == continued_downtime_start.tooling_id)
        .with_entities(
            models.Operator.name.label("Operator"),
            models.Mesin.name.label("MC"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            continued_downtime_start.timestamp.label("Start"),
            continued_downtime_stop.timestamp.label("Stop"),
            models.ContinuedDowntimeMesin.downtime_category.label("Desc"),
            models.ContinuedDowntimeMesin.reject.label("Reject"),
            models.ContinuedDowntimeMesin.rework.label("Rework"),
        )
        .filter(continued_downtime_start.timestamp >= time_from)
        .filter(continued_downtime_start.timestamp < time_to)
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Qty"] = 0
    df["Keterangan"] = ""
    return df


def query_last_downtime_operator(time_from, time_to):
    last_downtime_start = aliased(models.Stop)
    last_downtime_stop = aliased(models.Start)

    query = (
        session.query(models.LastDowntimeMesin)
        .join(models.Operator)
        .join(last_downtime_start, models.LastDowntimeMesin.start_time)
        .join(last_downtime_stop, models.LastDowntimeMesin.stop_time)
        .join(models.Mesin)
        .join(models.Tooling, models.Tooling.id == last_downtime_start.tooling_id)
        .with_entities(
            models.Operator.name.label("Operator"),
            models.Mesin.name.label("MC"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            last_downtime_start.timestamp.label("Start"),
            last_downtime_stop.timestamp.label("Stop"),
            models.LastDowntimeMesin.downtime_category.label("Desc"),
            models.LastDowntimeMesin.reject.label("Reject"),
            models.LastDowntimeMesin.rework.label("Rework"),
        )
        .filter(last_downtime_start.timestamp >= time_from)
        .filter(last_downtime_start.timestamp < time_to)
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Qty"] = 0
    df["Keterangan"] = ""
    return df


def query_utility_operator(time_from, time_to):
    utility_start = aliased(models.Start)
    utility_stop = aliased(models.Stop)

    query = (
        session.query(models.UtilityMesin)
        .join(models.Operator)
        .join(utility_start, models.UtilityMesin.start_time)
        .join(utility_stop, models.UtilityMesin.stop_time)
        .join(models.Mesin)
        .join(models.Tooling, models.Tooling.id == utility_start.tooling_id)
        .with_entities(
            models.Operator.name.label("Operator"),
            models.Mesin.name.label("MC"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            utility_start.timestamp.label("Start"),
            utility_stop.timestamp.label("Stop"),
            models.UtilityMesin.output.label("Qty"),
            models.UtilityMesin.reject.label("Reject"),
            models.UtilityMesin.rework.label("Rework"),
            models.UtilityMesin.coil_no.label("Coil No"),
            models.UtilityMesin.lot_no.label("Lot No"),
            models.UtilityMesin.pack_no.label("Pack No"),
        )
        .filter(utility_start.timestamp >= time_from)
        .filter(utility_start.timestamp < time_to)
        .statement
    )

    df = pandas.read_sql(sql=query, con=engine)
    df["Desc"] = "U : Utility"
    df["Coil No"] = df["Coil No"].fillna("").replace("-", "")
    df["Lot No"] = df["Lot No"].fillna("").replace("-", "")
    df["Pack No"] = df["Pack No"].fillna("").replace("-", "")
    df["Keterangan"] = df.apply(lambda row: _generate_keterangan(row), axis=1)
    df.drop(["Coil No", "Lot No", "Pack No"], axis=1)
    return df


def get_operator_report(
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None
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

    df = (
        pandas.concat(
            [
                query_utility_operator(time_from, time_to),
                query_continued_downtime_operator(time_from, time_to),
                query_last_downtime_operator(time_from, time_to),
            ],
            axis=0,
        )
        .sort_values(by=["Operator", "Start"])
        .reset_index(drop=True)
    )

    df["Tanggal"] = (
        pandas.to_datetime(df.Start, utc=True)
        .map(lambda x: x.tz_convert("Asia/Jakarta"))
        .dt.strftime("%m/%d/%Y")
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

    for index, row in df.iterrows():
        if index == 0:
            continue

        # Remove No Plan and BreakTime from Operator's Downtime
        if (
            (df.loc[index]["Operator"] == df.loc[index - 1]["Operator"])
            and (df.loc[index]["Start"] != df.loc[index - 1]["Stop"])
            and (
                df.loc[index]["Desc"][:2] != "NP" and df.loc[index]["Desc"][:2] != "BT"
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

    df = df.sort_values(by=["Operator", "Start"]).reset_index(drop=True)

    df = df.fillna(0)
    df["Qty"] = df["Qty"].astype(int)
    df["Reject"] = df["Reject"].astype(int)
    df["Rework"] = df["Rework"].astype(int)

    df.drop(["Start", "Stop"], axis=1, inplace=True)
    header = [
        "Operator",
        "Shift",
        "Tanggal",
        "StartTime",
        "StopTime",
        "MC",
        "Kode Tooling",
        "Common Tooling Name",
        "Qty",
        "Reject",
        "Rework",
        "Desc",
        "Duration",
        "Keterangan",
    ]
    df = df[header]
    print(df)

    df.to_csv(
        _get_csv_folder(
            "operator",
            date_from=date_from,
            shift_from=shift_from,
            date_to=date_to,
            shift_to=shift_to,
            sep=";",
        )
    )
    return df, _get_csv_filename(
        "operator",
        date_from=date_from,
        shift_from=shift_from,
        date_to=date_to,
        shift_to=shift_to,
    )


if __name__ == "__main__":
    get_mesin_report()
    get_operator_report()
    # print(_calculate_shift_from_datetime(datetime(2023,2,4,13,5)))
    # print(_calculate_datetime_range(
    #     date_from=datetime(2023,2,4),
    #     shift_from=1,
    #     date_to=datetime(2023,2,4),
    #     shift_to=3,
    # ))
