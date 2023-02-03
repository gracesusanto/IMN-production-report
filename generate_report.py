from datetime import datetime, time

import pandas
import sqlalchemy as sa
from sqlalchemy.orm import aliased
import pytz

import database
import models


def _is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current UTC time
    check_time = check_time or datetime.utcnow().time()
    if begin_time < end_time:
        return check_time >= begin_time and check_time <= end_time
    else: # crosses midnight
        return check_time >= begin_time or check_time <= end_time

def _calculate_shift(row):
    date_time = datetime.strptime(row, '%m/%d/%Y %H:%M:%S')
    return _calculate_shift_from_datetime(date_time)

def _calculate_shift_from_datetime(date_time):
    comp_time = date_time.time()
    
    if date_time.isoweekday() == 7: # Sunday
        return 3
    elif date_time.isoweekday() == 6: # Saturday
        if _is_time_between(time(7,00), time(12,00), comp_time):
            return 1
        elif _is_time_between(time(12,1), time(17,00), comp_time):
            return 2
        elif _is_time_between(time(17,1), time(23,00), comp_time):
            return 3
    elif date_time.isoweekday() < 6: # Weekday
        if _is_time_between(time(7,00), time(15,00), comp_time):
            return 1
        elif _is_time_between(time(15,1), time(23,00), comp_time):
            return 2
        elif _is_time_between(time(23,1), time(7,00), comp_time):
            return 3

def get_curr_datetime():
    return datetime.now(pytz.timezone('Asia/Jakarta')).date()
def get_curr_shift():
    return _calculate_shift_from_datetime(datetime.now())

def _get_csv_filename(type, date_time=None, shift=None):
    if date_time == None:
        date_time = get_curr_datetime()
    if shift == None:
        shift = get_curr_shift()
    return f"result_{type}_{date_time}_shift_{shift}.csv"

def _get_csv_folder(type, date_time=None, shift=None):
    filename = _get_csv_filename(type, date_time, shift)
    return f"report/{type}/{filename}"

def _convert_seconds(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)

    if h > 0 and m > 0 and s > 0:
        return f'{h:d}h {m:d}min {s:d}sec'
    elif m > 0 and s > 0:
        return f'{m:d}min {s:d}sec'
    else:
        return f'{s:d}sec'



engine = database.get_engine()
session = sa.orm.sessionmaker(autocommit=False, autoflush=False,
                                      bind=engine)()

col_order = ['MC', 'Operator', 'Kode Tooling', 'Common Tooling Name', 'Start', 'Stop', 'Desc', 'Qty', 'Reject', 'Rework']

def query_continued_downtime():
    continued_downtime_start = aliased(models.Stop)
    continued_downtime_stop = aliased(models.Stop)

    query = session.query(models.ContinuedDowntimeMesin).\
        join(models.Mesin).\
        join(continued_downtime_start, models.ContinuedDowntimeMesin.start_time).\
        join(continued_downtime_stop, models.ContinuedDowntimeMesin.stop_time).\
        join(models.Operator, models.Operator.id == continued_downtime_start.operator_id).\
        join(models.Tooling, models.Tooling.id == continued_downtime_start.tooling_id).\
        with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            # models.Tooling.part_name.label("Part Name"),
            # models.Tooling.proses.label("Prs"),
            continued_downtime_start.timestamp.label("Start"), 
            continued_downtime_stop.timestamp.label("Stop"),
            models.ContinuedDowntimeMesin.downtime_category.label("Desc"),
            models.ContinuedDowntimeMesin.reject.label("Reject"),
            models.ContinuedDowntimeMesin.rework.label("Rework"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = 0
    return df[col_order]

def query_last_downtime():
    last_downtime_start = aliased(models.Stop)
    last_downtime_stop = aliased(models.Start)

    query = session.query(models.LastDowntimeMesin).\
        join(models.Mesin).\
        join(last_downtime_start, models.LastDowntimeMesin.start_time).\
        join(last_downtime_stop, models.LastDowntimeMesin.stop_time).\
        join(models.Operator, models.Operator.id == last_downtime_start.operator_id).\
        join(models.Tooling, models.Tooling.id == last_downtime_start.tooling_id).\
        with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            # models.Tooling.part_name.label("Part Name"),
            # models.Tooling.proses.label("Prs"),
            last_downtime_start.timestamp.label("Start"), 
            last_downtime_stop.timestamp.label("Stop"),
            models.LastDowntimeMesin.downtime_category.label("Desc"),
            models.LastDowntimeMesin.reject.label("Reject"),
            models.LastDowntimeMesin.rework.label("Rework"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = 0
    return df[col_order]

def query_utility():
    utility_start = aliased(models.Start)
    utility_stop = aliased(models.Stop)

    query = session.query(models.UtilityMesin).\
        join(models.Mesin).\
        join(utility_start, models.UtilityMesin.start_time).\
        join(utility_stop, models.UtilityMesin.stop_time).\
        join(models.Operator, models.Operator.id == utility_start.operator_id).\
        join(models.Tooling, models.Tooling.id == utility_start.tooling_id).\
        with_entities(
            models.Mesin.name.label("MC"),
            models.Operator.name.label("Operator"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            # models.Tooling.part_name.label("Part Name"),
            # models.Tooling.proses.label("Prs"),
            utility_start.timestamp.label("Start"), 
            utility_stop.timestamp.label("Stop"),
            models.UtilityMesin.output.label("Qty"),
            models.UtilityMesin.reject.label("Reject"),
            models.UtilityMesin.rework.label("Rework"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Desc'] = 'U : Utility'
    return df[col_order]

def get_mesin_report(date_time=None, shift=None):
    if date_time == None:
        date_time = get_curr_datetime()
    if shift == None:
        shift = get_curr_shift()

    df = pandas.concat([
        query_utility(), 
        query_continued_downtime(), 
        query_last_downtime()
        ], axis=0).sort_values(by=['MC', 'Start']).reset_index(drop=True)

    df['Tanggal'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y')
    df['StartTime'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%H:%M:%S')
    df['StopTime'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%H:%M:%S')

    df['Start'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
    df['Stop'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
    df['Shift'] = df['Start'].apply(lambda x: _calculate_shift(x))

    df = df.loc[df['Tanggal'] == date_time.strftime('%m/%d/%Y')]
    df = df.loc[df['Shift'] == shift]
    
    df['Duration'] = pandas.to_datetime(df.Stop) - pandas.to_datetime(df.Start)
    df['Duration'] = df['Duration'].dt.total_seconds()
    df['Duration'] = df['Duration'].apply(lambda x: _convert_seconds(x))
    df = df.fillna(0)
    df['Qty'] = df['Qty'].astype(int)
    df['Reject'] = df['Reject'].astype(int)
    df['Rework'] = df['Rework'].astype(int)
    df.drop(['Start', 'Stop'], axis=1, inplace=True)
    header = ['MC', 'Shift', 'Tanggal', 'StartTime', 'StopTime', 'Kode Tooling', 'Common Tooling Name', 'Operator', 'Qty', 'Reject', 'Rework', 'Desc', 'Duration']
    df = df[header]
    print(df)
    df.to_csv(_get_csv_folder("mesin", date_time, shift))
    return df, _get_csv_filename("mesin", date_time, shift)


def query_continued_downtime_operator():
    continued_downtime_start = aliased(models.Stop)
    continued_downtime_stop = aliased(models.Stop)

    query = session.query(models.ContinuedDowntimeOperator).\
        join(models.Operator).\
        join(continued_downtime_start, models.ContinuedDowntimeOperator.start_time).\
        join(continued_downtime_stop, models.ContinuedDowntimeOperator.stop_time).\
        join(models.Mesin, models.Mesin.id == continued_downtime_start.mesin_id).\
        join(models.Tooling, models.Tooling.id == continued_downtime_start.tooling_id).\
        with_entities(
            models.Operator.name.label("Operator"),
            models.Mesin.name.label("MC"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            continued_downtime_start.timestamp.label("Start"), 
            continued_downtime_stop.timestamp.label("Stop"),
            models.ContinuedDowntimeOperator.downtime_category.label("Desc"),
            models.ContinuedDowntimeOperator.reject.label("Reject"),
            models.ContinuedDowntimeOperator.rework.label("Rework"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = 0
    return df

def query_last_downtime_operator():
    last_downtime_start = aliased(models.Stop)
    last_downtime_stop = aliased(models.Start)

    query = session.query(models.LastDowntimeOperator).\
        join(models.Operator).\
        join(last_downtime_start, models.LastDowntimeOperator.start_time).\
        join(last_downtime_stop, models.LastDowntimeOperator.stop_time).\
        join(models.Mesin, models.Mesin.id == last_downtime_start.mesin_id).\
        join(models.Tooling, models.Tooling.id == last_downtime_start.tooling_id).\
        with_entities(
            models.Operator.name.label("Operator"),
            models.Mesin.name.label("MC"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            last_downtime_start.timestamp.label("Start"), 
            last_downtime_stop.timestamp.label("Stop"),
            models.LastDowntimeOperator.downtime_category.label("Desc"),
            models.LastDowntimeOperator.reject.label("Reject"),
            models.LastDowntimeOperator.rework.label("Rework"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = 0
    return df

def query_utility_operator():
    utility_start = aliased(models.Start)
    utility_stop = aliased(models.Stop)

    query = session.query(models.UtilityOperator).\
        join(models.Operator).\
        join(utility_start, models.UtilityOperator.start_time).\
        join(utility_stop, models.UtilityOperator.stop_time).\
        join(models.Mesin, models.Mesin.id == utility_start.mesin_id).\
        join(models.Tooling, models.Tooling.id == utility_start.tooling_id).\
        with_entities(
            models.Operator.name.label("Operator"),
            models.Mesin.name.label("MC"),
            models.Tooling.kode_tooling.label("Kode Tooling"),
            models.Tooling.common_tooling_name.label("Common Tooling Name"),
            utility_start.timestamp.label("Start"), 
            utility_stop.timestamp.label("Stop"),
            models.UtilityOperator.output.label("Qty"),
            models.UtilityOperator.reject.label("Reject"),
            models.UtilityOperator.rework.label("Rework"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Desc'] = 'U : Utility'
    return df

def get_operator_report(date_time=None, shift=None):
    if date_time == None:
        date_time = get_curr_datetime()
    if shift == None:
        shift = get_curr_shift()

    df = pandas.concat([
        query_utility_operator(), 
        query_continued_downtime_operator(), 
        query_last_downtime_operator()
        ], axis=0).sort_values(by=['Operator', 'Start']).reset_index(drop=True)

    df['Tanggal'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y')

    df['Start'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
    df['Stop'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
    df['Shift'] = df['Start'].apply(lambda x: _calculate_shift(x))
    
    df = df.loc[df['Tanggal'] == date_time.strftime('%m/%d/%Y')]
    df = df.loc[df['Shift'] == shift]

    for index, row in df.iterrows():
        if index == 0:
            continue
        if ((df.loc[index]['Operator'] == df.loc[index-1]['Operator']) and 
        (df.loc[index]['Start'] != df.loc[index-1]['Stop']) and 
        (df.loc[index]['Desc'][:2] != "NP" and df.loc[index]['Desc'][:2] != "BT")):
            insert_row = {
                'Operator': df.loc[index]['Operator'], 
                'Start': df.loc[index-1]['Stop'], 
                'Stop': df.loc[index]['Start'],
                'Desc': 'NK : Not Known'
            }
            df = pandas.concat([df, pandas.DataFrame([insert_row])])
    df.drop(df.loc[df['Desc']=="NP: No Plan"].index, inplace=True)
    df = df.sort_values(by=['Operator', 'Start']).reset_index(drop=True)
    
    df['StartTime'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%H:%M:%S')
    df['StopTime'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%H:%M:%S')

    df['Duration'] = pandas.to_datetime(df.Stop) - pandas.to_datetime(df.Start)
    df['Duration'] = df['Duration'].dt.total_seconds()
    df['Duration'] = df['Duration'].apply(lambda x: _convert_seconds(x))
    df = df.sort_values(by=['Operator', 'Start']).reset_index(drop=True)
    df = df.fillna(0)
    df['Qty'] = df['Qty'].astype(int)
    df['Reject'] = df['Reject'].astype(int)
    df['Rework'] = df['Rework'].astype(int)
    df.drop(['Start', 'Stop'], axis=1, inplace=True)
    header = ['Operator', 'Shift', 'Tanggal', 'StartTime', 'StopTime', 'MC', 'Kode Tooling', 'Common Tooling Name', 'Qty', 'Reject', 'Rework', 'Desc', 'Duration']
    df = df[header]
    print(df)
    df.to_csv(_get_csv_folder("operator", date_time, shift))
    return df, _get_csv_filename("operator", date_time, shift)

if __name__ == "__main__":
    get_mesin_report()
    get_operator_report()