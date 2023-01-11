from datetime import datetime, time

import pandas
import pytz
import sqlalchemy
from sqlalchemy.orm import aliased

import database
import models


def is_time_between(begin_time, end_time, check_time=None):
    # If check time is not given, default to current UTC time
    check_time = check_time or datetime.utcnow().time()
    if begin_time < end_time:
        return check_time >= begin_time and check_time <= end_time
    else: # crosses midnight
        return check_time >= begin_time or check_time <= end_time

def calculate_shift(row):
    date_time = datetime.strptime(row, '%m/%d/%Y %H:%M:%S')
    comp_time = date_time.time()
    
    if date_time.isoweekday() == 7: # Sunday
        return 3
    elif date_time.isoweekday() == 6: # Saturday
        if is_time_between(time(7,00), time(12,00), comp_time):
            return 1
        elif is_time_between(time(12,1), time(17,00), comp_time):
            return 2
        elif is_time_between(time(17,1), time(23,00), comp_time):
            return 3
    elif date_time.isoweekday() < 6: # Weekday
        if is_time_between(time(7,00), time(15,00), comp_time):
            return 1
        elif is_time_between(time(15,1), time(23,00), comp_time):
            return 2
        elif is_time_between(time(23,1), time(7,00), comp_time):
            return 3

def convert_seconds(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)

    if h > 0 and m > 0 and s > 0:
        return f'{h:d}h {m:d}min {s:d}sec'
    elif m > 0 and s > 0:
        return f'{m:d}min {s:d}sec'
    else:
        return f'{s:d}sec'

engine = database.get_engine()
session = sqlalchemy.orm.sessionmaker(autocommit=False, autoflush=False,
                                      bind=engine)()

# col_order = ['MC', 'Operator', 'Part No', 'Part Name', 'Prs', 'Start', 'Stop', 'Desc', 'Qty']
col_order = ['MC', 'Operator', 'Part No', 'Start', 'Stop', 'Desc', 'Qty']

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
            models.Tooling.part_no.label("Part No"),
            # models.Tooling.part_name.label("Part Name"),
            # models.Tooling.proses.label("Prs"),
            continued_downtime_start.timestamp.label("Start"), 
            continued_downtime_stop.timestamp.label("Stop"),
            models.ContinuedDowntimeMesin.downtime_category.label("Desc"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = ""
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
            models.Tooling.part_no.label("Part No"),
            # models.Tooling.part_name.label("Part Name"),
            # models.Tooling.proses.label("Prs"),
            last_downtime_start.timestamp.label("Start"), 
            last_downtime_stop.timestamp.label("Stop"),
            models.LastDowntimeMesin.downtime_category.label("Desc"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = ""
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
            models.Tooling.part_no.label("Part No"),
            # models.Tooling.part_name.label("Part Name"),
            # models.Tooling.proses.label("Prs"),
            utility_start.timestamp.label("Start"), 
            utility_stop.timestamp.label("Stop"),
            models.UtilityMesin.output.label("Qty"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Desc'] = 'U : Utility'
    return df[col_order]

df = pandas.concat([
    query_utility(), 
    query_continued_downtime(), 
    query_last_downtime()
    ], axis=0).sort_values(by=['MC', 'Start']).reset_index(drop=True)

df['Start'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
df['Stop'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
df['Duration'] = pandas.to_datetime(df.Stop) - pandas.to_datetime(df.Start)
df['Duration'] = df['Duration'].dt.total_seconds()
df['Duration'] = df['Duration'].apply(lambda x: convert_seconds(x))
df['Shift'] = df['Start'].apply(lambda x: calculate_shift(x))
print(df)
df.to_csv("result_mesin.csv")


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
            models.Tooling.part_no.label("Part No"),
            continued_downtime_start.timestamp.label("Start"), 
            continued_downtime_stop.timestamp.label("Stop"),
            models.ContinuedDowntimeOperator.downtime_category.label("Desc"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = ""
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
            models.Tooling.part_no.label("Part No"),
            last_downtime_start.timestamp.label("Start"), 
            last_downtime_stop.timestamp.label("Stop"),
            models.LastDowntimeOperator.downtime_category.label("Desc"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Qty'] = ""
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
            models.Tooling.part_no.label("Part No"),
            utility_start.timestamp.label("Start"), 
            utility_stop.timestamp.label("Stop"),
            models.UtilityOperator.output.label("Qty"),
        ).\
        statement

    df = pandas.read_sql(
        sql = query,
        con = engine
    )
    df['Desc'] = 'U : Utility'
    return df

df = pandas.concat([
    query_utility_operator(), 
    query_continued_downtime_operator(), 
    query_last_downtime_operator()
    ], axis=0).sort_values(by=['Operator', 'Start']).reset_index(drop=True)

df['Start'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
df['Stop'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')

for index, row in df.iterrows():
    if index == 0:
        continue
    if ((df.loc[index]['Operator'] == df.loc[index-1]['Operator']) and (df.loc[index]['Start'] != df.loc[index-1]['Stop'])):
        insert_row = {
            'Operator': df.loc[index]['Operator'], 
            'Start': df.loc[index-1]['Stop'], 
            'Stop': df.loc[index]['Start'],
            'Desc': 'NK : Not Known'
        }
        df = pandas.concat([df, pandas.DataFrame([insert_row])])
        # df = pandas.concat([df, new_df], axis=0, ignore_index=True)
        # new_rowdf = df.append({
        #     'Operator': df.loc[index]['Operator'], 
        #     'Start': df.loc[index-1]['Stop'], 
        #     'Stop': df.loc[index]['Start'],
        #     'Desc': 'NK : Not Known'
        # }, ignore_index=True)
df['Duration'] = pandas.to_datetime(df.Stop) - pandas.to_datetime(df.Start)
df['Duration'] = df['Duration'].dt.total_seconds()
df['Duration'] = df['Duration'].apply(lambda x: convert_seconds(x))
df = df.sort_values(by=['Operator', 'Start']).reset_index(drop=True)
df['Shift'] = df['Start'].apply(lambda x: calculate_shift(x))
print(df)
df.to_csv("result_operator.csv")






# def query_continued_downtime_tooling():
#     continued_downtime_start = aliased(models.Stop)
#     continued_downtime_stop = aliased(models.Stop)

#     query = session.query(models.ContinuedDowntimeTooling).\
#         join(models.Tooling).\
#         join(continued_downtime_start, models.ContinuedDowntimeTooling.start_time).\
#         join(continued_downtime_stop, models.ContinuedDowntimeTooling.stop_time).\
#         join(models.Mesin, models.Mesin.id == continued_downtime_start.mesin_id).\
#         join(models.Operator, models.Operator.id == continued_downtime_start.operator_id).\
#         with_entities(
#             models.Tooling.part_name.label("Part Name"),
#             models.Mesin.name.label("MC"),
#             models.Operator.name.label("Operator"),
#             continued_downtime_start.timestamp.label("Start"), 
#             continued_downtime_stop.timestamp.label("Stop"),
#             models.ContinuedDowntimeTooling.downtime_category.label("Desc"),
#         ).\
#         statement

#     df = pandas.read_sql(
#         sql = query,
#         con = engine
#     )
#     df['Qty'] = ""
#     return df

# def query_last_downtime_tooling():
#     last_downtime_start = aliased(models.Stop)
#     last_downtime_stop = aliased(models.Start)

#     query = session.query(models.LastDowntimeTooling).\
#         join(models.Tooling).\
#         join(last_downtime_start, models.LastDowntimeTooling.start_time).\
#         join(last_downtime_stop, models.LastDowntimeTooling.stop_time).\
#         join(models.Mesin, models.Mesin.id == last_downtime_start.mesin_id).\
#         join(models.Operator, models.Operator.id == last_downtime_start.operator_id).\
#         with_entities(
#             models.Tooling.part_name.label("Part Name"),
#             models.Mesin.name.label("MC"),
#             models.Operator.name.label("Operator"),
#             last_downtime_start.timestamp.label("Start"), 
#             last_downtime_stop.timestamp.label("Stop"),
#             models.LastDowntimeTooling.downtime_category.label("Desc"),
#         ).\
#         statement

#     df = pandas.read_sql(
#         sql = query,
#         con = engine
#     )
#     df['Qty'] = ""
#     return df

# def query_utility_tooling():
#     utility_start = aliased(models.Start)
#     utility_stop = aliased(models.Stop)

#     query = session.query(models.UtilityTooling).\
#         join(models.Tooling).\
#         join(utility_start, models.UtilityTooling.start_time).\
#         join(utility_stop, models.UtilityTooling.stop_time).\
#         join(models.Mesin, models.Mesin.id == utility_start.mesin_id).\
#         join(models.Operator, models.Operator.id == utility_start.operator_id).\
#         with_entities(
#             models.Tooling.part_name.label("Part Name"),
#             models.Mesin.name.label("MC"),
#             models.Operator.name.label("Operator"),
#             utility_start.timestamp.label("Start"), 
#             utility_stop.timestamp.label("Stop"),
#             models.UtilityTooling.output.label("Qty"),
#         ).\
#         statement

#     df = pandas.read_sql(
#         sql = query,
#         con = engine
#     )
#     df['Desc'] = 'U'
#     return df

# df = pandas.concat([
#     query_utility_tooling(), 
#     query_continued_downtime_tooling(), 
#     query_last_downtime_tooling()
#     ], axis=0).sort_values(by=['Part Name', 'Start']).reset_index(drop=True)

# df['Start'] = pandas.to_datetime(df.Start, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
# df['Stop'] = pandas.to_datetime(df.Stop, utc=True).map(lambda x: x.tz_convert('Asia/Jakarta')).dt.strftime('%m/%d/%Y %H:%M:%S')
# print(df)
# df.to_csv("result_tooling.csv")

# print(pandas.read_sql(
#         sql = session.query(models.ContinuedDowntimeTooling).statement,
#         con = engine
#     ))
