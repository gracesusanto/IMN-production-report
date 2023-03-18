import datetime
import app.cmd.generate_report as helper


def test_is_time_between():
    is_between = helper._is_time_between(
        datetime.time(20, 00), datetime.time(1, 00), datetime.time(23, 00)
    )
    assert is_between == True, "Tonight 11 PM is between today 8 PM and tomorrow 1 AM"


def test_calculate_shift_from_datetime_weekday():
    shift = helper._calculate_shift_from_datetime(datetime.datetime(2023, 3, 15, 14))
    assert shift == 1, "Weekday 2PM is shift 1"


def test_calculate_shift_from_datetime_saturday():
    shift = helper._calculate_shift_from_datetime(datetime.datetime(2023, 3, 11, 14))
    assert shift == 2, "Saturday 2PM is shift 2"


def test_calculate_shift_from_datetime_sunday():
    shift = helper._calculate_shift_from_datetime(datetime.datetime(2023, 3, 12, 14))
    assert shift == 0, "Sunday 2PM is invalid shift"


def test_get_csv_filename_1():
    filename = helper._get_csv_filename(
        "operator", datetime.date(2023, 3, 15), 1, datetime.date(2023, 3, 15), 1
    )
    assert filename == "result_operator_2023-03-15_shift_1.csv"


def test_get_csv_filename_2():
    filename = helper._get_csv_filename(
        "operator", datetime.date(2023, 3, 15), 1, datetime.date(2023, 3, 15), 3
    )
    assert filename == "result_operator_2023-03-15_shift_1_to_shift_3.csv"


def test_get_csv_filename_3():
    filename = helper._get_csv_filename(
        "operator", datetime.date(2023, 3, 15), 1, datetime.date(2023, 3, 16), 1
    )
    assert filename == "result_operator_2023-03-15_shift_1_to_2023-03-16_shift_1.csv"


def test_convert_seconds_to_seconds():
    sec = helper._convert_seconds(30)
    assert sec == "30sec"


def test_convert_seconds_to_minutes():
    min = helper._convert_seconds(90)
    assert min == "1min 30sec"


def test_convert_seconds_to_hours():
    hr = helper._convert_seconds(7290)
    assert hr == "2h 1min 30sec"


def test_calculate_datetime_from_shift_weekday():
    date_from, date_to = helper._calculate_datetime_from_shift(
        datetime.date(2023, 3, 15), "3"
    )
    # Returned dates are in UTC
    # To convert to GMT +7, add 7 hours
    assert date_from == datetime.datetime(
        2023, 3, 15, 16, 0
    ), "shift to date from weekday"
    assert date_to == datetime.datetime(2023, 3, 16, 0, 0), "shift to date to weekday"


def test_calculate_datetime_from_shift_saturday():
    date_from, date_to = helper._calculate_datetime_from_shift(
        datetime.date(2023, 3, 11), "3"
    )
    # Returned dates are in UTC
    # To convert to GMT +7, add 7 hours
    assert date_from == datetime.datetime(
        2023, 3, 11, 10, 0
    ), "shift to date from Saturday"
    assert date_to == datetime.datetime(2023, 3, 11, 15, 0), "shift to date to Saturday"


def test_calculate_datetime_from_shift_sunday():
    date_from, date_to = helper._calculate_datetime_from_shift(
        datetime.date(2023, 3, 12), "3"
    )
    # Returned dates are in UTC
    # To convert to GMT +7, add 7 hours
    assert (
        date_from == date_to == datetime.datetime(2023, 3, 12, 0, 0)
    ), "date to and from Sunday"


def test_fill_default_datetime_no_date_to_and_shift_to():
    date_from, shift_from, date_to, shift_to = helper._fill_default_datetime(
        date_from=datetime.datetime(2023, 3, 15), shift_from="1"
    )
    assert date_from == date_to == datetime.datetime(2023, 3, 15)
    assert shift_from == "1"
    assert shift_to == "3"


def test_fill_default_datetime_invalid_shift():
    date_from, shift_from, date_to, shift_to = helper._fill_default_datetime(
        date_from=datetime.datetime(2023, 3, 15), shift_from="-5", shift_to="-5"
    )
    assert date_from == date_to == datetime.datetime(2023, 3, 15)
    assert shift_from == "1"
    assert shift_to == "1"


def test_fill_default_datetime_invalid_shift_terbalik():
    date_from, shift_from, date_to, shift_to = helper._fill_default_datetime(
        date_from=datetime.datetime(2023, 3, 15), shift_from="5", shift_to="-5"
    )
    assert date_from == date_to == datetime.datetime(2023, 3, 15)
    assert shift_from == "1"
    assert shift_to == "3"


def test_fill_default_datetime_invalid_shift_date_terbalik():
    date_from, shift_from, date_to, shift_to = helper._fill_default_datetime(
        date_from=datetime.datetime(2023, 3, 15),
        shift_from=5,
        date_to=datetime.datetime(2023, 3, 10),
        shift_to=-5,
    )
    assert date_from == datetime.datetime(2023, 3, 10)
    assert date_to == datetime.datetime(2023, 3, 15)
    assert shift_from == "3"
    assert shift_to == "1"


def test_calculate_datetime_range_whole_day_weekday():
    time_from, time_to = helper._calculate_datetime_range(
        date_from=datetime.datetime(2023, 3, 15)
    )
    # Returned dates are in UTC
    # To convert to GMT +7, add 7 hours
    assert time_from == datetime.datetime(2023, 3, 15, 0)
    assert time_to == datetime.datetime(2023, 3, 16, 0)


def test_calculate_datetime_range_whole_day_saturday():
    time_from, time_to = helper._calculate_datetime_range(
        date_from=datetime.datetime(2023, 3, 11)
    )
    # Returned dates are in UTC
    # To convert to GMT +7, add 7 hours
    assert time_from == datetime.datetime(2023, 3, 11, 0)
    assert time_to == datetime.datetime(2023, 3, 11, 15)
