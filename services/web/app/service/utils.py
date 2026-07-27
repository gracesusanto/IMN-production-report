import pytz
from decimal import Decimal
from datetime import datetime, timedelta, date, time as dtime
from typing import Optional

import pandas as pd

JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# ---------------------------------------------------------------------------
# Category / status configuration
# Canonical list — mirrors mobile app mKategoriList (Navigation.kt).
# Used by andon_service, report logic, and any filter that needs code→label.
#
# Flags per entry:
#   non_machine — aktivitas yang tidak melibatkan mesin (NP, BT, BR).
#                 /operator/status: tidak tampilkan pilihan STOP.
#                 /activity/status: tidak tampilkan active activity mesin/operator.
#   setup       — aktivitas setup yang menghasilkan reject dan rework (TL, TS, TP).
#                 CM juga group "setup" tapi tidak menghasilkan output, jadi tidak di-flag.
#   no_plan     — dipakai di /activity/status supaya tidak tampilkan kegiatan NP operator.
# ---------------------------------------------------------------------------
STATUS_CONFIG = {
    "U":   {"label": "RUNNING",          "group": "running",  "priority": 100},
    "MP":  {"label": "MACHINE PROBLEM",  "group": "downtime", "priority": 90},
    "TP":  {"label": "TOOLING PROBLEM",  "group": "downtime", "priority": 80,  "setup": True},
    "NM":  {"label": "NO MATERIAL",      "group": "downtime", "priority": 70},
    "QC":  {"label": "QUALITY CHECK",    "group": "downtime", "priority": 60},
    "TS":  {"label": "TOOLING SETTING",  "group": "setup",    "priority": 40,  "setup": True},
    "TL":  {"label": "TRIAL",            "group": "setup",    "priority": 40,  "setup": True},
    "CM":  {"label": "CHANGE MATERIAL",  "group": "setup",    "priority": 40},
    "NP":  {"label": "NO SCHEDULE",      "group": "no_plan",  "priority": 30,  "non_machine": True, "no_plan": True},
    "BT":  {"label": "BREAKTIME",        "group": "no_plan",  "priority": 20,  "non_machine": True},
    "BR":  {"label": "BRIEFING",         "group": "no_plan",  "priority": 20,  "non_machine": True},
    "RP":  {"label": "REPORTING",        "group": "no_plan",  "priority": 20},
    "STO": {"label": "STOCK OPNAME",     "group": "no_plan",  "priority": 20},
    "X":   {"label": "X",                "group": "no_plan",  "priority": 10},
}

# Derived sets — read from the flags above, never hardcoded separately.
NON_MACHINE_CODES: frozenset[str] = frozenset(c for c, cfg in STATUS_CONFIG.items() if cfg.get("non_machine"))
SETUP_CODES: frozenset[str]       = frozenset(c for c, cfg in STATUS_CONFIG.items() if cfg.get("setup"))
NO_PLAN_CODES: frozenset[str]     = frozenset(c for c, cfg in STATUS_CONFIG.items() if cfg.get("no_plan"))

# Full-string lists ("CODE : Label") for SQL .in_() filters in business_logic.
NON_MACHINE_CATEGORY: list[str] = [f"{c} : {cfg['label'].title()}" for c, cfg in STATUS_CONFIG.items() if cfg.get("non_machine")]
SETUP_CATEGORY: list[str]       = [f"{c} : {cfg['label'].title()}" for c, cfg in STATUS_CONFIG.items() if cfg.get("setup")]
NO_PLAN_CATEGORY: list[str]     = [f"{c} : {cfg['label'].title()}" for c, cfg in STATUS_CONFIG.items() if cfg.get("no_plan")]

WORKING_SHIFT_JSON = {
    "Weekday": {
        "start": {"1": 7, "2": 15, "3": 23},
        "duration": {"1": 8, "2": 8, "3": 8},
    },
    "Saturday": {
        "start": {"1": 7, "2": 12, "3": 17},
        "duration": {"1": 5, "2": 5, "3": 5},
    },
    "Sunday": {
        "start": {"1": 7, "2": 15, "3": 23},
        "duration": {"1": 8, "2": 8, "3": 8},
    },
}


# ---------- Time / shift helpers ----------
LOCAL_UTC_OFFSET = timedelta(hours=7)


def is_time_between(begin_time: dtime, end_time: dtime, check_time: dtime) -> bool:
    if begin_time < end_time:
        return begin_time <= check_time < end_time
    return check_time >= begin_time or check_time < end_time


def _get_day_type_for_date(d: date) -> str:
    """
    Return the configured production day type.
    """
    weekday = d.isoweekday()

    if weekday == 6:
        return "Saturday"

    if weekday == 7:
        return "Sunday"

    return "Weekday"


def _get_shift_duration_hours(day_type: str, shift: str) -> float:
    """
    Supports both old shape:
      "duration": 8

    and new flexible shape:
      "duration": {"1": 8, "2": 8, "3": 8}
    """
    duration_config = WORKING_SHIFT_JSON[day_type]["duration"]

    if isinstance(duration_config, dict):
        return float(duration_config[str(shift)])

    return float(duration_config)


def _build_official_shift_window_local(business_date: date, shift: str):
    """
    Build one official shift window in Jakarta local naive datetime.

    Example:
      Sunday shift 3 = Sunday 23:00 to Monday 07:00
    """
    shift = str(shift)
    day_type = _get_day_type_for_date(business_date)

    start_hour = WORKING_SHIFT_JSON[day_type]["start"][shift]
    duration_hours = _get_shift_duration_hours(day_type, shift)

    start_local = datetime.combine(business_date, dtime(int(start_hour), 0))
    end_local = start_local + timedelta(hours=duration_hours)

    return {
        "business_date": business_date,
        "shift": shift,
        "day_type": day_type,
        "start_local": start_local,
        "end_local": end_local,
    }


def _all_shift_windows_around(local_dt: datetime, days_before: int = 2, days_after: int = 2):
    """
    Build official shift windows around a timestamp.

    We include nearby days because:
    - shift 3 crosses midnight
    - Saturday has a gap after shift 3
    - closest-shift logic needs previous and next windows
    """
    base_date = local_dt.date()
    windows = []

    for offset in range(-days_before, days_after + 1):
        d = base_date + timedelta(days=offset)
        day_type = _get_day_type_for_date(d)

        for shift in sorted(WORKING_SHIFT_JSON[day_type]["start"].keys(), key=int):
            windows.append(_build_official_shift_window_local(d, shift))

    windows.sort(key=lambda w: w["start_local"])
    return windows


def _midpoint_datetime(a: datetime, b: datetime) -> datetime:
    return a + ((b - a) / 2)


def _build_flexible_shift_windows_around(local_dt: datetime):
    """
    Build flexible windows using closest-boundary logic.

    If two shifts are contiguous:
      previous end == next start
      boundary stays exact.

    If there is a gap:
      the gap is split at midpoint.

    Example:
      Saturday shift 3 official = Saturday 17:00–22:00
      Sunday shift 1 official   = Sunday 07:00–15:00

      Gap = Saturday 22:00–Sunday 07:00
      Midpoint = Sunday 02:30

      Therefore:
        Saturday shift 3 flexible end = Sunday 02:30
        Sunday shift 1 flexible start = Sunday 02:30
    """
    official_windows = _all_shift_windows_around(local_dt)
    flexible_windows = []

    for i, current in enumerate(official_windows):
        previous_window = official_windows[i - 1] if i > 0 else None
        next_window = official_windows[i + 1] if i < len(official_windows) - 1 else None

        flexible_start = current["start_local"]
        flexible_end = current["end_local"]

        if previous_window is not None:
            previous_end = previous_window["end_local"]

            if previous_end < current["start_local"]:
                flexible_start = _midpoint_datetime(previous_end, current["start_local"])

        if next_window is not None:
            next_start = next_window["start_local"]

            if current["end_local"] < next_start:
                flexible_end = _midpoint_datetime(current["end_local"], next_start)

        flexible_windows.append(
            {
                **current,
                "flexible_start_local": flexible_start,
                "flexible_end_local": flexible_end,
            }
        )

    return flexible_windows


def _to_jakarta_naive(dt_jakarta: datetime) -> datetime:
    """
    Convert timezone-aware Jakarta datetime into naive Jakarta datetime.

    Most report logic compares naive local datetime windows.
    """
    ts = pd.Timestamp(dt_jakarta)

    if ts.tzinfo is not None:
        ts = ts.tz_convert(JAKARTA_TZ)

    return ts.to_pydatetime().replace(tzinfo=None)


def resolve_business_shift_from_datetime_jakarta(dt_jakarta: datetime):
    """
    Resolve a Jakarta datetime to the closest business shift.

    Rules:
    1. If timestamp is inside an official shift, use that shift.
    2. If timestamp is in a gap, assign it to the closest neighboring shift.
    3. Sunday is a real configured day, not automatically shift 1.

    Returns dict with:
      - business_date
      - shift
      - day_type
      - start/end official and flexible local windows
    """
    local_dt = _to_jakarta_naive(dt_jakarta)
    flexible_windows = _build_flexible_shift_windows_around(local_dt)

    matching_windows = [
        window
        for window in flexible_windows
        if window["flexible_start_local"] <= local_dt < window["flexible_end_local"]
    ]

    if matching_windows:
        official_matches = [
            window
            for window in matching_windows
            if window["start_local"] <= local_dt < window["end_local"]
        ]

        if official_matches:
            return official_matches[0]

        return matching_windows[0]

    # Defensive fallback. Normally unreachable if nearby windows are built correctly.
    def distance_to_window(window):
        if window["start_local"] <= local_dt < window["end_local"]:
            return 0

        if local_dt < window["start_local"]:
            return abs((window["start_local"] - local_dt).total_seconds())

        return abs((local_dt - window["end_local"]).total_seconds())

    return min(flexible_windows, key=distance_to_window)


def calculate_shift_from_datetime_jakarta(dt_jakarta: datetime) -> int:
    """
    dt_jakarta must already represent Asia/Jakarta time.

    Returns only shift number for backward compatibility.
    """
    resolved = resolve_business_shift_from_datetime_jakarta(dt_jakarta)
    return int(resolved["shift"])


def calculate_business_date_from_datetime_jakarta(dt_jakarta: datetime) -> date:
    """
    Return the reporting/business date for a Jakarta timestamp.

    This matters when a timestamp is assigned to a nearby shift in a gap.
    Example:
      Saturday 22:30 may still report as Saturday shift 3.
    """
    resolved = resolve_business_shift_from_datetime_jakarta(dt_jakarta)
    return resolved["business_date"]


def calculate_business_date_and_shift_from_datetime_jakarta(dt_jakarta: datetime):
    """
    Return:
      (business_date, shift)

    business_date is a date object.
    shift is int.
    """
    resolved = resolve_business_shift_from_datetime_jakarta(dt_jakarta)
    return resolved["business_date"], int(resolved["shift"])


def build_flexible_shift_window_utc(business_date: date, shift: str):
    """
    Build selected report date + shift query window.

    Returns naive UTC datetimes because existing report query code uses naive UTC.

    Example:
      Saturday shift 3 official = Saturday 17:00–22:00 Jakarta.
      Sunday shift 1 official = Sunday 07:00–15:00 Jakarta.
      Flexible Saturday shift 3 may end at Sunday 02:30 Jakarta.
    """
    shift = str(shift)

    official = _build_official_shift_window_local(business_date, shift)
    flexible_windows = _build_flexible_shift_windows_around(official["start_local"])

    selected = None
    for window in flexible_windows:
        if window["business_date"] == business_date and window["shift"] == shift:
            selected = window
            break

    if selected is None:
        raise ValueError(f"No shift window found for date={business_date}, shift={shift}")

    time_from_utc = selected["flexible_start_local"] - LOCAL_UTC_OFFSET
    time_to_utc = selected["flexible_end_local"] - LOCAL_UTC_OFFSET

    return time_from_utc, time_to_utc


def format_time_for_limax_hhmm(dt_jakarta: datetime) -> str:
    """
    limax wants HHMM with "2400" for midnight hour (00xx -> 24xx).
    dt_jakarta must already be in Asia/Jakarta timezone.
    """
    hhmm = dt_jakarta.strftime("%H%M")
    if hhmm[:2] == "00":
        return "24" + hhmm[2:]
    return hhmm


# ---------- Keterangan helpers ----------
def combine_keterangan_final(
    keterangan: Optional[str],
    coil_no: Optional[str],
    lot_no: Optional[str],
    pack_no: Optional[str],
) -> str:
    parts = []
    if keterangan:
        parts.append(f"Keterangan: {keterangan}")
    if coil_no:
        parts.append(f"Coil No: {coil_no}")
    if lot_no:
        parts.append(f"Lot No: {lot_no}")
    if pack_no:
        parts.append(f"Pack No: {pack_no}")
    return ", ".join(parts)


def build_keterangan_limax(reject: int, rework: int, keterangan_final: str) -> str:
    return ", ".join(
        filter(
            None,
            [
                f"Reject: {reject}" if reject else "",
                f"Rework: {rework}" if rework else "",
                keterangan_final or "",
            ],
        )
    )


# ---------- Metric helpers (numeric; safe for filtering) ----------
def calc_productivity_pct(category_full: str, qty: int, duration_sec: int, target_std_jam: Optional[int]) -> Decimal:
    """
    Productivity (%) = ((qty / hours) / target) * 100
    Only for U : Utility. Returns Decimal quantized to 4 dp.
    Includes a cap to prevent absurd values (e.g. tiny duration in tests).
    """
    if category_full != "U : Utility":
        return Decimal("0")
    if duration_sec <= 0 or not target_std_jam or target_std_jam <= 0:
        return Decimal("0")

    hours = Decimal(duration_sec) / Decimal(3600)
    val = (Decimal(qty) / hours) / Decimal(target_std_jam) * Decimal(100)

    # cap (matches earlier choice)
    cap = Decimal("99999999999999.9999")
    if val > cap:
        val = cap

    return val.quantize(Decimal("0.0001"))


def calc_ratio_pct(qty: int, reject: int, rework: int, which: str) -> Decimal:
    total = qty + reject + rework
    if total <= 0:
        return Decimal("0")
    numerator = reject if which == "reject" else rework
    val = (Decimal(numerator) / Decimal(total)) * Decimal(100)
    return val.quantize(Decimal("0.0001"))


# ---------- Display helpers ----------
def convert_seconds_to_string(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)

    if h > 0 and m > 0 and s > 0:
        return f"{h:d}h {m:d}min {s:d}sec"
    elif m > 0 and s > 0:
        return f"{m:d}min {s:d}sec"
    else:
        return f"{s:d}sec"


def format_percent_2dp(value) -> str:
    return f"{float(value):.2f}%"


def utc_dt_to_jakarta(dt_utc) -> Optional[pd.Timestamp]:
    if dt_utc is None:
        return None
    ts = pd.Timestamp(dt_utc)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(JAKARTA_TZ)


# ---------- DataFrame helpers (used by generate_report) ----------
def normalize_report_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build display columns from raw timestamps:
    expects:
      - _StartTs, _StopTs (UTC)
      - MC, Desc
    produces:
      - Tanggal, StartTime, StopTime, Shift
      - _DurationSec, Duration
      - Awal, Akhir, Plant, Kode Keterangan
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    df["_StartTs"] = pd.to_datetime(df["_StartTs"], utc=True)
    df["_StopTs"] = pd.to_datetime(df["_StopTs"], utc=True)

    start_jkt = df["_StartTs"].dt.tz_convert(JAKARTA_TZ)
    stop_jkt = df["_StopTs"].dt.tz_convert(JAKARTA_TZ)

    business_date_shift = start_jkt.apply(calculate_business_date_and_shift_from_datetime_jakarta)

    df["Tanggal"] = business_date_shift.apply(lambda x: x[0].strftime("%d/%m/%Y"))
    df["StartTime"] = start_jkt.dt.strftime("%H:%M:%S")
    df["StopTime"] = stop_jkt.dt.strftime("%H:%M:%S")
    df["Shift"] = business_date_shift.apply(lambda x: x[1])

    df["_DurationSec"] = (df["_StopTs"] - df["_StartTs"]).dt.total_seconds().fillna(0).astype(int)
    df["Duration"] = df["_DurationSec"].apply(convert_seconds_to_string)

    df["Awal"] = start_jkt.apply(format_time_for_limax_hhmm)
    df["Akhir"] = stop_jkt.apply(format_time_for_limax_hhmm)

    df["Plant"] = df["MC"].apply(
        lambda mc: mc[-1] if isinstance(mc, str) and mc not in ["", "-"] and len(mc) > 0 else "-"
    )
    df["Kode Keterangan"] = df["Desc"].apply(
        lambda desc: desc[:2].strip() if isinstance(desc, str) and len(desc) >= 2 else ""
    )

    return df


def add_numeric_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds:
      - _ProductivityNum, _RejectRatioNum, _ReworkRatioNum (float)
    Requires:
      - Desc, Qty, Reject, Rework, Target, _DurationSec
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(0).astype(int)
    df["Reject"] = pd.to_numeric(df["Reject"], errors="coerce").fillna(0).astype(int)
    df["Rework"] = pd.to_numeric(df["Rework"], errors="coerce").fillna(0).astype(int)
    df["Target"] = pd.to_numeric(df["Target"], errors="coerce").fillna(0)

    df["_ProductivityNum"] = df.apply(
        lambda row: float(
            calc_productivity_pct(
                row["Desc"],
                int(row["Qty"]),
                int(row["_DurationSec"]),
                int(row["Target"]) if pd.notna(row["Target"]) and row["Target"] else None,
            )
        ),
        axis=1,
    )
    df["_RejectRatioNum"] = df.apply(
        lambda row: float(calc_ratio_pct(int(row["Qty"]), int(row["Reject"]), int(row["Rework"]), "reject")),
        axis=1,
    )
    df["_ReworkRatioNum"] = df.apply(
        lambda row: float(calc_ratio_pct(int(row["Qty"]), int(row["Reject"]), int(row["Rework"]), "rework")),
        axis=1,
    )

    return df


def finalize_metric_strings(df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates string columns expected by export/UI:
      - Productivity, Reject Ratio, Rework Ratio
    Requires:
      - _ProductivityNum, _RejectRatioNum, _ReworkRatioNum
    """
    if df is None or df.empty:
        return df

    if "_ProductivityNum" in df.columns:
        df["Productivity"] = df["_ProductivityNum"].apply(format_percent_2dp)

    if "_RejectRatioNum" in df.columns:
        df["Reject Ratio"] = df["_RejectRatioNum"].apply(format_percent_2dp)

    if "_ReworkRatioNum" in df.columns:
        df["Rework Ratio"] = df["_ReworkRatioNum"].apply(format_percent_2dp)

    return df
