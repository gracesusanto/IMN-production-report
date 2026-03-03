"""
Pre-computation functions for ActivityReport table.

This module contains functions to calculate all derived fields that will be
stored in the ActivityReport table to optimize report generation performance.
"""

from datetime import datetime
from decimal import Decimal
import pytz


# Jakarta timezone for conversions
_JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# Working shift configuration
_WORKING_SHIFT_JSON = {
    "Saturday": {"start": {"1": 7, "2": 12, "3": 17}, "duration": 5},
    "Weekday": {"start": {"1": 7, "2": 15, "3": 23}, "duration": 8},
}


def convert_utc_to_jakarta_string(utc_timestamp: datetime, fmt: str = "%m/%d/%Y %H:%M:%S") -> str:
    """
    Convert UTC timestamp to Jakarta timezone formatted string.

    Args:
        utc_timestamp: UTC datetime object
        fmt: Format string for output

    Returns:
        Formatted string in Jakarta timezone
    """
    if utc_timestamp is None:
        return None

    # Ensure timezone aware (assume UTC if naive)
    if utc_timestamp.tzinfo is None:
        utc_timestamp = utc_timestamp.replace(tzinfo=pytz.UTC)

    # Convert to Jakarta timezone
    jakarta_time = utc_timestamp.astimezone(_JAKARTA_TZ)
    return jakarta_time.strftime(fmt)


def calculate_shift_from_jakarta_datetime(jakarta_datetime_str: str) -> int:
    """
    Calculate shift number from Jakarta datetime string.

    Args:
        jakarta_datetime_str: DateTime string in Jakarta timezone (mm/dd/yyyy HH:MM:SS)

    Returns:
        Shift number (1, 2, or 3)
    """
    if not jakarta_datetime_str:
        return 1

    try:
        date_time = datetime.strptime(jakarta_datetime_str, "%m/%d/%Y %H:%M:%S")
        return _calculate_shift_from_datetime(date_time)
    except (ValueError, TypeError):
        return 1


def _calculate_shift_from_datetime(date_time: datetime) -> int:
    """Calculate shift from datetime object."""
    comp_time = date_time.time()

    if date_time.isoweekday() == 7:  # Sunday
        return 1

    day_of_week = "Saturday" if date_time.isoweekday() == 6 else "Weekday"

    # Adjusting day based on time (for early morning considerations)
    if comp_time < datetime.strptime("07:00", "%H:%M").time() and day_of_week == "Saturday":
        day_of_week = "Weekday"

    duration = _WORKING_SHIFT_JSON[day_of_week]["duration"]

    for shift, timestamp in _WORKING_SHIFT_JSON[day_of_week]["start"].items():
        start_time = datetime.strptime(f"{timestamp}:00", "%H:%M").time()
        end_time = datetime.strptime(f"{(timestamp + duration) % 24}:00", "%H:%M").time()

        if _is_time_between(start_time, end_time, comp_time):
            return int(shift)

    return 1


def _is_time_between(begin_time, end_time, check_time):
    """Check if time is between two times (handles midnight crossing)."""
    if begin_time < end_time:
        return check_time >= begin_time and check_time < end_time
    else:  # crosses midnight
        return check_time >= begin_time or check_time < end_time


def calculate_duration_seconds(start_ts_utc: datetime, stop_ts_utc: datetime) -> int:
    """
    Calculate duration in seconds between start and stop timestamps.

    Args:
        start_ts_utc: Start timestamp (UTC)
        stop_ts_utc: Stop timestamp (UTC)

    Returns:
        Duration in seconds
    """
    if not start_ts_utc or not stop_ts_utc:
        return 0

    try:
        delta = stop_ts_utc - start_ts_utc
        return max(0, int(delta.total_seconds()))
    except (TypeError, ValueError):
        return 0


def format_duration_seconds(seconds: int) -> str:
    """
    Format duration seconds into readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2h 30min 15sec")
    """
    if seconds <= 0:
        return "0sec"

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)

    if h > 0 and m > 0 and s > 0:
        return f"{h}h {m}min {s}sec"
    elif h > 0 and m > 0:
        return f"{h}h {m}min"
    elif h > 0:
        return f"{h}h"
    elif m > 0 and s > 0:
        return f"{m}min {s}sec"
    elif m > 0:
        return f"{m}min"
    else:
        return f"{s}sec"


def calculate_productivity_percent(category: str, output: int, duration_seconds: int, target_per_hour: int) -> Decimal:
    """
    Calculate productivity percentage.

    Args:
        category: Activity category
        output: Output pieces
        duration_seconds: Duration in seconds
        target_per_hour: Target pieces per hour

    Returns:
        Productivity percentage as Decimal
    """
    if category != "U : Utility" or duration_seconds <= 0 or target_per_hour <= 0:
        return Decimal('0.00')

    try:
        # Productivity (%) = (Output pcs / Waktu hr) / Target pcs/hr * 100
        hours = Decimal(duration_seconds) / Decimal(3600)

        # Handle edge cases that cause extreme values
        if hours < Decimal('0.001'):  # Less than 3.6 seconds
            # For very short durations, productivity calculation is not meaningful
            return Decimal('0.00')

        if target_per_hour < Decimal('0.1'):  # Less than 0.1 pieces per hour
            # Unreasonably low target, likely data error
            return Decimal('0.00')

        productivity = (Decimal(output) / hours) / Decimal(target_per_hour) * Decimal(100)

        # Cap productivity to database limits (NUMERIC(5,2) = -999.99 to 999.99)
        # This handles legitimate high productivity scenarios
        if productivity > Decimal('999.99'):
            return Decimal('999.99')
        elif productivity < Decimal('-999.99'):
            return Decimal('-999.99')

        return round(productivity, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return Decimal('0.00')


def calculate_ratio_percent(numerator: int, output: int, reject: int, rework: int) -> Decimal:
    """
    Calculate ratio percentage (reject or rework).

    Args:
        numerator: The value to calculate ratio for (reject or rework)
        output: Output pieces (OK pieces)
        reject: Reject pieces
        rework: Rework pieces

    Returns:
        Ratio percentage as Decimal
    """
    total = (output or 0) + (reject or 0) + (rework or 0)
    if total == 0:
        return Decimal('0.00')

    try:
        ratio = Decimal(numerator or 0) / Decimal(total) * Decimal(100)
        return round(ratio, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return Decimal('0.00')


def format_percent(percent_value: Decimal) -> str:
    """
    Format percentage value to string.

    Args:
        percent_value: Percentage as Decimal

    Returns:
        Formatted percentage string (e.g., "95.50%")
    """
    if percent_value is None:
        return "0.00%"

    return f"{percent_value:.2f}%"


def extract_plant_from_machine_name(machine_name: str) -> str:
    """
    Extract plant identifier from machine name.

    Args:
        machine_name: Machine name (e.g., "A1-MOCK")

    Returns:
        Plant identifier (last character, e.g., "1")
    """
    if not machine_name or machine_name == "-":
        return None

    return machine_name[-1] if len(machine_name) > 0 else None


def format_time_for_limax(time_str: str) -> str:
    """
    Convert time string to LIMAX format (HHMM).

    Args:
        time_str: Time string in HH:MM:SS format

    Returns:
        Time in HHMM format (with 00 hour converted to 24)
    """
    if not time_str:
        return None

    try:
        # Extract hour and minute from HH:MM:SS
        dt = datetime.strptime(time_str, "%H:%M:%S")
        hour = dt.hour
        minute = dt.minute

        # Convert 00 hour to 24 for LIMAX format
        if hour == 0:
            return f"24{minute:02d}"
        else:
            return f"{hour:02d}{minute:02d}"
    except (ValueError, TypeError):
        return None


def extract_category_code(category: str) -> str:
    """
    Extract category code (first 2 characters).

    Args:
        category: Full category description (e.g., "BT : Breaktime")

    Returns:
        Category code (e.g., "BT")
    """
    if not category:
        return None

    return category[:2].strip()


def compute_all_derived_fields(
    start_ts_utc: datetime,
    stop_ts_utc: datetime,
    category: str,
    output: int,
    reject: int,
    rework: int,
    target_per_hour: int,
    machine_name: str
) -> dict:
    """
    Compute all derived fields for ActivityReport table in one go.

    This is the main function that should be called during upsert operations
    to pre-compute all derived values.

    Args:
        start_ts_utc: Start timestamp (UTC)
        stop_ts_utc: Stop timestamp (UTC)
        category: Activity category
        output: Output pieces
        reject: Reject pieces
        rework: Rework pieces
        target_per_hour: Target pieces per hour
        machine_name: Machine name

    Returns:
        Dictionary with all computed fields
    """
    # Jakarta timezone conversions
    start_date_jakarta = convert_utc_to_jakarta_string(start_ts_utc, "%d/%m/%Y")
    stop_date_jakarta = convert_utc_to_jakarta_string(stop_ts_utc, "%d/%m/%Y")
    start_time_jakarta = convert_utc_to_jakarta_string(start_ts_utc, "%H:%M:%S")
    stop_time_jakarta = convert_utc_to_jakarta_string(stop_ts_utc, "%H:%M:%S")
    start_datetime_jakarta = convert_utc_to_jakarta_string(start_ts_utc, "%m/%d/%Y %H:%M:%S")
    stop_datetime_jakarta = convert_utc_to_jakarta_string(stop_ts_utc, "%m/%d/%Y %H:%M:%S")

    # Shift calculation
    shift = calculate_shift_from_jakarta_datetime(start_datetime_jakarta)

    # Duration calculations
    duration_seconds = calculate_duration_seconds(start_ts_utc, stop_ts_utc)

    # Productivity calculations (decimal only)
    productivity_percent = calculate_productivity_percent(category, output, duration_seconds, target_per_hour)

    # Ratio calculations (decimal only)
    reject_ratio_percent = calculate_ratio_percent(reject, output, reject, rework)
    rework_ratio_percent = calculate_ratio_percent(rework, output, reject, rework)

    # Other derived fields
    plant = extract_plant_from_machine_name(machine_name)
    awal_limax = format_time_for_limax(start_time_jakarta)
    akhir_limax = format_time_for_limax(stop_time_jakarta)
    kode_keterangan = extract_category_code(category)

    return {
        # Jakarta timezone fields
        'start_date_jakarta': start_date_jakarta,
        'stop_date_jakarta': stop_date_jakarta,
        'start_time_jakarta': start_time_jakarta,
        'stop_time_jakarta': stop_time_jakarta,
        'start_datetime_jakarta': start_datetime_jakarta,
        'stop_datetime_jakarta': stop_datetime_jakarta,
        'shift': shift,

        # Derived metrics (decimals only - formatting done at presentation time)
        'duration_seconds': duration_seconds,
        'productivity_percent': productivity_percent,
        'reject_ratio_percent': reject_ratio_percent,
        'rework_ratio_percent': rework_ratio_percent,
        'plant': plant,
        'awal_limax': awal_limax,
        'akhir_limax': akhir_limax,
        'kode_keterangan': kode_keterangan,
    }