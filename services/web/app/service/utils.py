import pytz
from decimal import Decimal
from datetime import datetime, time as dtime
from typing import Optional

import pandas as pd

JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

WORKING_SHIFT_JSON = {
    "Saturday": {"start": {"1": 7, "2": 12, "3": 17}, "duration": 5},
    "Weekday": {"start": {"1": 7, "2": 15, "3": 23}, "duration": 8},
}


# ---------- Time / shift helpers ----------
def is_time_between(begin_time: dtime, end_time: dtime, check_time: dtime) -> bool:
    if begin_time < end_time:
        return begin_time <= check_time < end_time
    return check_time >= begin_time or check_time < end_time


def calculate_shift_from_datetime_jakarta(dt_jakarta: datetime) -> int:
    """
    dt_jakarta must already be in Asia/Jakarta timezone.
    """
    comp_time = dt_jakarta.time()

    if dt_jakarta.isoweekday() == 7:  # Sunday
        return 1

    day_of_week = "Saturday" if dt_jakarta.isoweekday() == 6 else "Weekday"
    if comp_time < datetime.strptime("07:00:00", "%H:%M:%S").time() and day_of_week == "Saturday":
        day_of_week = "Weekday"

    duration = WORKING_SHIFT_JSON[day_of_week]["duration"]
    for shift, start_hour in WORKING_SHIFT_JSON[day_of_week]["start"].items():
        if is_time_between(
            datetime.strptime(f"{start_hour:02d}:00:00", "%H:%M:%S").time(),
            datetime.strptime(f"{(start_hour + duration) % 24:02d}:00:00", "%H:%M:%S").time(),
            comp_time,
        ):
            return int(shift)

    return 1


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

    df["Tanggal"] = start_jkt.dt.strftime("%d/%m/%Y")
    df["StartTime"] = start_jkt.dt.strftime("%H:%M:%S")
    df["StopTime"] = stop_jkt.dt.strftime("%H:%M:%S")
    df["Shift"] = start_jkt.apply(calculate_shift_from_datetime_jakarta)

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
