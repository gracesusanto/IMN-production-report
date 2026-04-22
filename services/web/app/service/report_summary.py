from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

import app.service.utils as ru

CATEGORY_CODES = ("U", "TL", "TS", "TP", "QC", "CM", "NO", "NP", "NM", "MP", "BR", "BT")


# TODO: Re-implement contextual Keterangan helper after debugging
# def _format_keterangan_with_context(row: pd.Series, category_value: str) -> str:
#     """Format notes with operator/machine context for grouped rows"""
#     note = str(row.get("Keterangan", "") or "").strip()
#     if not note:
#         return ""

#     if category_value == "mesin":
#         operator = str(row.get("Operator", "") or "").strip()
#         if operator and operator != "-":
#             return f"[OP: {operator}] {note}"
#         return note

#     # For operator category, prefix with machine
#     mc = str(row.get("MC", "") or "").strip()
#     if mc and mc != "-":
#         return f"[MC: {mc}] {note}"
#     return note

# Assumption for v1 summary logic:
# - NP, BT, NO are outside counted plan
# - change these constants if business finalizes a different rule later
PLAN_INCLUDED_CODES = frozenset({"U", "TL", "TS", "TP", "QC", "CM", "NM", "MP", "BR"})


def _report_category_value(report_category: Any) -> str:
    if hasattr(report_category, "value"):
        return str(report_category.value)
    return str(report_category).lower()


def _category_code(desc: str) -> str:
    if not desc:
        return ""
    return str(desc).split(":")[0].strip().upper()[:2]


def _minutes_to_hhmm(minutes: float) -> str:
    total_minutes = max(int(round(float(minutes))), 0)
    hours, mins = divmod(total_minutes, 60)
    return f"{hours:02d}:{mins:02d}"


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (float(numerator) / float(denominator)) * 100.0


def _join_unique(values: pd.Series) -> str:
    seen: list[str] = []
    for value in values.fillna("").astype(str):
        value = value.strip()
        if value and value not in seen:
            seen.append(value)
    return " | ".join(seen)


def _to_utc_timestamp(value):
    """Convert timestamp to UTC, handling both naive and aware timestamps"""
    if pd.isna(value):
        return pd.NaT
    ts = pd.Timestamp(value)
    if ts.tz is None:
        # Assume naive timestamps are UTC
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _calculate_shift_window_utc(local_date: datetime, shift: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    year, month, day = local_date.year, local_date.month, local_date.day

    # Keep existing generate_report behavior:
    # Sunday returns no active shift window.
    if local_date.isoweekday() == 7:
        zero = pd.Timestamp(datetime(year, month, day, 0, 0), tz='UTC')
        return zero, zero

    day_of_week = "Saturday" if local_date.isoweekday() == 6 else "Weekday"
    hour_from = ru.WORKING_SHIFT_JSON[day_of_week]["start"][shift]

    start_local = pd.Timestamp(datetime(year, month, day, hour_from, 0), tz='Asia/Jakarta')
    start_utc = start_local.tz_convert('UTC')
    end_utc = start_utc + pd.Timedelta(hours=ru.WORKING_SHIFT_JSON[day_of_week]["duration"])
    return start_utc, end_utc


def _iter_shift_windows_utc(start_ts: pd.Timestamp, stop_ts: pd.Timestamp):
    local_start_day = (pd.Timestamp(start_ts) + pd.Timedelta(hours=7)).normalize() - pd.Timedelta(days=1)
    local_stop_day = (pd.Timestamp(stop_ts) + pd.Timedelta(hours=7)).normalize() + pd.Timedelta(days=1)

    cursor = local_start_day
    while cursor <= local_stop_day:
        local_date = cursor.to_pydatetime()
        for shift in ("1", "2", "3"):
            win_start, win_end = _calculate_shift_window_utc(local_date, shift)
            if win_start == win_end:
                continue
            # Ensure timestamps are timezone-aware for comparison
            stop_ts_utc = pd.Timestamp(stop_ts).tz_convert('UTC') if pd.Timestamp(stop_ts).tz is not None else pd.Timestamp(stop_ts, tz='UTC')
            start_ts_utc = pd.Timestamp(start_ts).tz_convert('UTC') if pd.Timestamp(start_ts).tz is not None else pd.Timestamp(start_ts, tz='UTC')

            if stop_ts_utc <= win_start or start_ts_utc >= win_end:
                continue
            yield shift, win_start, win_end
        cursor += pd.Timedelta(days=1)


def _allocate_integer_metric(rows: list[dict], source_total: int, field_name: str) -> None:
    if not rows:
        return

    total_minutes = sum(float(r["_DurationMinutes"]) for r in rows)
    if total_minutes <= 0:
        for row in rows:
            row[field_name] = 0
        return

    raw_shares = []
    for row in rows:
        share = (float(source_total) * float(row["_DurationMinutes"])) / total_minutes
        raw_shares.append(share)

    floors = [int(np.floor(x)) for x in raw_shares]
    remainder = int(source_total) - sum(floors)

    ranked = sorted(
        range(len(raw_shares)),
        key=lambda idx: (raw_shares[idx] - floors[idx], idx),
        reverse=True,
    )

    for i, row in enumerate(rows):
        row[field_name] = floors[i]

    for idx in ranked[: max(remainder, 0)]:
        rows[idx][field_name] += 1


def split_rows_by_shift(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    working = df.copy()
    # Normalize timestamps to UTC before any comparisons
    working["_StartTs"] = working["_StartTs"].apply(_to_utc_timestamp)
    working["_StopTs"] = working["_StopTs"].apply(_to_utc_timestamp)

    if "Proses" not in working.columns:
        working["Proses"] = "-"

    split_rows: list[dict] = []

    for _, row in working.iterrows():
        start_ts = row["_StartTs"]
        stop_ts = row["_StopTs"]
        if pd.isna(start_ts) or pd.isna(stop_ts) or stop_ts <= start_ts:
            continue

        slices: list[dict] = []
        for shift, win_start, win_end in _iter_shift_windows_utc(start_ts, stop_ts):
            seg_start = max(start_ts, win_start)
            seg_end = min(stop_ts, win_end)
            duration_minutes = (seg_end - seg_start).total_seconds() / 60.0
            if duration_minutes <= 0:
                continue

            row_dict = row.to_dict()
            row_dict["_StartTs"] = seg_start
            row_dict["_StopTs"] = seg_end
            row_dict["_DurationMinutes"] = duration_minutes
            row_dict["Shift"] = str(shift)
            row_dict["Tanggal"] = (seg_start + pd.Timedelta(hours=7)).date()
            slices.append(row_dict)

        if not slices:
            continue

        _allocate_integer_metric(slices, int(row.get("Qty", 0) or 0), "Qty")
        _allocate_integer_metric(slices, int(row.get("Reject", 0) or 0), "Reject")
        _allocate_integer_metric(slices, int(row.get("Rework", 0) or 0), "Rework")

        split_rows.extend(slices)

    result = pd.DataFrame(split_rows)
    if result.empty:
        return result

    result["Desc Code"] = result["Desc"].map(_category_code)
    result["Target"] = pd.to_numeric(result.get("Target", 0), errors="coerce").fillna(0)
    result["Qty"] = pd.to_numeric(result.get("Qty", 0), errors="coerce").fillna(0).astype(int)
    result["Reject"] = pd.to_numeric(result.get("Reject", 0), errors="coerce").fillna(0).astype(int)
    result["Rework"] = pd.to_numeric(result.get("Rework", 0), errors="coerce").fillna(0).astype(int)
    result["Keterangan"] = result.get("Keterangan", "").fillna("")
    result["Proses"] = result.get("Proses", "-").fillna("-").replace("", "-")

    return result


def build_dashboard_response(df: pd.DataFrame, report_category: Any, pagination=None) -> dict:
    """
    Build complete dashboard response with meta, kpis, rows, and charts.
    Returns both numeric and display fields for chart compatibility.
    """
    summary_df = summarize_dashboard_df(df, report_category)

    if summary_df.empty:
        return {
            "meta": {
                "view": f"{_report_category_value(report_category)}_summary",
                "generated_at": datetime.now().isoformat(),
                "grain": "tanggal_shift_mc_part_proses" if _report_category_value(report_category) == "mesin" else "tanggal_shift_operator_mc_part_proses",
                "timezone": "Asia/Jakarta"
            },
            "kpis": {},
            "charts": {},
            "rows": [],
            "pagination": {"page": 1, "page_size": 50, "total_rows": 0}
        }

    # Calculate aggregated KPIs
    kpis = _calculate_aggregated_kpis(summary_df)

    # Build chart data
    charts = _build_chart_data(summary_df, report_category)

    # Convert rows to API format with both numeric and display fields
    rows = _convert_rows_to_api_format(summary_df, report_category)

    # Apply pagination to rows
    total_rows = len(rows)
    if pagination:
        start_idx = (pagination.page - 1) * pagination.page_size
        end_idx = start_idx + pagination.page_size
        rows = rows[start_idx:end_idx]

        pagination_info = {
            "page": pagination.page,
            "page_size": pagination.page_size,
            "total_rows": total_rows
        }
    else:
        pagination_info = {
            "page": 1,
            "page_size": total_rows,
            "total_rows": total_rows
        }

    return {
        "meta": {
            "view": f"{_report_category_value(report_category)}_summary",
            "generated_at": datetime.now().isoformat(),
            "grain": "tanggal_shift_mc_part_proses" if _report_category_value(report_category) == "mesin" else "tanggal_shift_operator_mc_part_proses",
            "timezone": "Asia/Jakarta"
        },
        "kpis": kpis,
        "charts": charts,
        "rows": rows,
        "pagination": pagination_info
    }


def _calculate_aggregated_kpis(df: pd.DataFrame) -> dict:
    """Calculate aggregated KPIs from summary dataframe"""
    if df.empty:
        return {}

    total_plan_minutes = df["Plan Minutes"].sum()
    total_utility_minutes = df["Utility Minutes"].sum()
    total_downtime_minutes = df["Downtime Minutes"].sum()
    total_output = df["Qty"].sum()
    total_reject = df["Reject"].sum()
    total_rework = df["Rework"].sum()
    total_target_qty = df["Target Qty"].sum()

    # Calculate aggregate percentages
    expected_output_during_utility = ((df["Utility Minutes"] / 60.0) * df["Target"]).sum()

    otr_num = _pct(total_utility_minutes, total_plan_minutes) if total_plan_minutes > 0 else 0
    per_num = _pct(total_output, expected_output_during_utility) if expected_output_during_utility > 0 else 0
    qr_num = _pct(total_output, total_output + total_reject + total_rework) if (total_output + total_reject + total_rework) > 0 else 0
    oee_num = (otr_num * per_num * qr_num) / 10000.0

    return {
        "plan_minutes": int(total_plan_minutes),
        "plan": _minutes_to_hhmm(total_plan_minutes),
        "utility_minutes": int(total_utility_minutes),
        "utility": _minutes_to_hhmm(total_utility_minutes),
        "downtime_minutes": int(total_downtime_minutes),
        "downtime": _minutes_to_hhmm(total_downtime_minutes),
        "output": int(total_output),
        "reject": int(total_reject),
        "rework": int(total_rework),
        "target_qty": int(total_target_qty),
        "otr_num": round(otr_num, 2),
        "otr": f"{int(round(otr_num))}%",
        "per_num": round(per_num, 2),
        "per": f"{int(round(per_num))}%",
        "qr_num": round(qr_num, 2),
        "qr": f"{int(round(qr_num))}%",
        "oee_num": round(oee_num, 2),
        "oee": f"{int(round(oee_num))}%"
    }


def _build_chart_data(df: pd.DataFrame, report_category: Any) -> dict:
    """Build chart-ready data aggregates"""
    if df.empty:
        return {}

    charts = {}

    # OEE by machine
    if "MC" in df.columns:
        oee_by_machine = df.groupby("MC")["OEE Num"].mean().round(2).to_dict()
        charts["oee_by_machine"] = [{"mc": mc, "oee_num": oee} for mc, oee in oee_by_machine.items()]

    # Downtime by category
    downtime_categories = []
    for code in CATEGORY_CODES:
        if f"{code}_Minutes" in df.columns:
            total_minutes = df[f"{code}_Minutes"].sum()
            if total_minutes > 0:
                downtime_categories.append({"category": code, "minutes": int(total_minutes)})
    charts["downtime_by_category"] = downtime_categories

    # OEE trend by date
    if "Tanggal" in df.columns:
        oee_trend = df.groupby("Tanggal")["OEE Num"].mean().round(2).to_dict()
        charts["oee_trend"] = [{"tanggal": str(date), "oee_num": oee} for date, oee in oee_trend.items()]

    return charts


def _derive_status_from_row(row: dict) -> str:
    """
    Derive status from row data based on downtime categories.
    Priority: MP > TP > TS > QC > CM > NO > NP > NM > BT > BR > OK
    """
    # Check time-based columns (HH:MM format)
    if row.get("MP", "00:00") != "00:00":
        return "MP"
    if row.get("TP", "00:00") != "00:00":
        return "TP"
    if row.get("TS", "00:00") != "00:00":
        return "TS"
    if row.get("QC", "00:00") != "00:00":
        return "QC"
    if row.get("CM", "00:00") != "00:00":
        return "CM"
    if row.get("NO", "00:00") != "00:00":
        return "NO"
    if row.get("NP", "00:00") != "00:00":
        return "NP"
    if row.get("NM", "00:00") != "00:00":
        return "NM"
    if row.get("BT", "00:00") != "00:00":
        return "BT"
    if row.get("BR", "00:00") != "00:00":
        return "BR"

    # Check minute-based columns as backup
    mp_minutes = row.get("MP_Minutes", 0) or 0
    tp_minutes = row.get("TP_Minutes", 0) or 0
    ts_minutes = row.get("TS_Minutes", 0) or 0
    qc_minutes = row.get("QC_Minutes", 0) or 0
    cm_minutes = row.get("CM_Minutes", 0) or 0
    no_minutes = row.get("NO_Minutes", 0) or 0
    np_minutes = row.get("NP_Minutes", 0) or 0
    nm_minutes = row.get("NM_Minutes", 0) or 0
    bt_minutes = row.get("BT_Minutes", 0) or 0
    br_minutes = row.get("BR_Minutes", 0) or 0

    if mp_minutes > 0:
        return "MP"
    elif tp_minutes > 0:
        return "TP"
    elif ts_minutes > 0:
        return "TS"
    elif qc_minutes > 0:
        return "QC"
    elif cm_minutes > 0:
        return "CM"
    elif no_minutes > 0:
        return "NO"
    elif np_minutes > 0:
        return "NP"
    elif nm_minutes > 0:
        return "NM"
    elif bt_minutes > 0:
        return "BT"
    elif br_minutes > 0:
        return "BR"

    return "OK"


def _convert_rows_to_api_format(df: pd.DataFrame, report_category: Any) -> list:
    """Convert dataframe rows to API format with both numeric and display fields"""
    rows = []
    category_value = _report_category_value(report_category)

    for _, row in df.iterrows():
        api_row = {
            "tanggal": str(row.get("Tanggal", "")),
            "shift": str(row.get("Shift", "")),
            "status": _derive_status_from_row(row),
            "mc": row.get("MC", "-"),
            "part_no": row.get("Part No", "-"),
            "part_name": row.get("Part Name", "-"),
            "part_no_name": f"{row.get('Part No', '-')} {row.get('Part Name', '-')}".strip(),
            "proses": row.get("Proses", "-"),
            "target_per_jam": int(row.get("Target", 0)),
            "target_qty": int(row.get("Target Qty", 0)),
            "output": int(row.get("Qty", 0)),
            "reject": int(row.get("Reject", 0)),
            "rework": int(row.get("Rework", 0)),

            # Time fields - both numeric and display
            "plan_minutes": int(row.get("Plan Minutes", 0)),
            "plan": row.get("Plan", "00:00"),
            "utility_minutes": int(row.get("Utility Minutes", 0)),
            "utility": row.get("Utility", "00:00"),  # U : Utility - the actual running time
            "downtime_minutes": int(row.get("Downtime Minutes", 0)),
            "downtime": row.get("Total Downtime", "00:00"),

            # Category duration fields
            "tp_minutes": int(row.get("TP_Minutes", 0)),
            "tp": row.get("TP", "00:00"),
            "ts_minutes": int(row.get("TS_Minutes", 0)),
            "ts": row.get("TS", "00:00"),
            "qc_minutes": int(row.get("QC_Minutes", 0)),
            "qc": row.get("QC", "00:00"),
            "cm_minutes": int(row.get("CM_Minutes", 0)),
            "cm": row.get("CM", "00:00"),
            "no_minutes": int(row.get("NO_Minutes", 0)),
            "no": row.get("NO", "00:00"),
            "np_minutes": int(row.get("NP_Minutes", 0)),
            "np": row.get("NP", "00:00"),
            "nm_minutes": int(row.get("NM_Minutes", 0)),
            "nm": row.get("NM", "00:00"),
            "mp_minutes": int(row.get("MP_Minutes", 0)),
            "mp": row.get("MP", "00:00"),
            "tl_minutes": int(row.get("TL_Minutes", 0)),
            "tl": row.get("TL", "00:00"),
            "br_minutes": int(row.get("BR_Minutes", 0)),
            "br": row.get("BR", "00:00"),
            "bt_minutes": int(row.get("BT_Minutes", 0)),
            "bt": row.get("BT", "00:00"),

            "catatan": row.get("Keterangan", ""),

            # KPI fields - both numeric and display
            "per_num": round(row.get("PER Num", 0), 2),
            "per": row.get("PER", "0%"),
            "otr_num": round(row.get("OTR Num", 0), 2),
            "otr": row.get("OTR", "0%"),
            "qr_num": round(row.get("QR Num", 0), 2),
            "qr": row.get("QR", "0%"),
            "oee_num": round(row.get("OEE Num", 0), 2),
            "oee": row.get("OEE", "0%"),
        }

        # Add operator fields for operator summary
        if category_value == "operator":
            api_row["operator"] = row.get("Operator", "-")
            api_row["nik"] = row.get("NIK", "-")

        # Add additional fields that might be present
        if "Kode Tooling" in row:
            api_row["kode_tooling"] = row.get("Kode Tooling", "-")
        if "Common Tooling Name" in row:
            api_row["common_tooling_name"] = row.get("Common Tooling Name", "-")

        # Add history_key for row lineage (similar to detail response)
        history_key = {
            "report_type": category_value,
            "tanggal": str(row.get("Tanggal", "")),
            "shift": str(row.get("Shift", "")),
            "mc": row.get("MC", "-"),
            "part_no": row.get("Part No", "-"),
            "proses": row.get("Proses", "-"),
        }
        if category_value == "operator":
            history_key["operator"] = row.get("Operator", "-")

        api_row["history_key"] = history_key

        rows.append(api_row)

    return rows


def build_detail_export_response(df: pd.DataFrame, report_category: Any, pagination=None) -> dict:
    """
    Build detail/export response matching Excel column order exactly.
    This preserves the business-recognizable format.
    """
    if df.empty:
        return {"rows": [], "total": 0}

    # Convert to detail format with exact Excel column order
    detail_rows = []

    for _, row in df.iterrows():
        # Get properly calculated values from summarized data
        target_per_jam = int(row.get("Target", 0))
        target_qty = int(row.get("Target Qty", 0)) if "Target Qty" in row and row.get("Target Qty") else target_per_jam

        # Build history_key for row lineage
        history_key = {
            "report_type": str(report_category).split(".")[-1].lower(),  # Extract "mesin" or "operator" from ReportCategory
            "tanggal": str(row.get("Tanggal", "")),
            "shift": str(row.get("Shift", "")),
            "mc": row.get("MC", "-"),
            "part_no": row.get("Part No", "-"),
            "proses": row.get("Proses", "-")
        }

        # Add operator for operator reports
        if str(report_category).split(".")[-1].lower() == "operator":
            history_key["operator"] = row.get("Operator", "-")

        detail_row = {
            # Excel column order exactly
            "status": _derive_status_from_row(row),
            "operator": row.get("Operator", "-"),
            "mc_no": row.get("MC", "-"),
            "part_no": row.get("Part No", "-"),
            "part_name": row.get("Part Name", "-"),
            "part_no_name": f"{row.get('Part No', '-')} {row.get('Part Name', '-')}".strip(),
            "proses": row.get("Proses", "-"),
            "target_per_jam": target_per_jam,
            "target_qty": target_qty,
            "output": int(row.get("Qty", 0)),
            "reject": int(row.get("Reject", 0)),

            # Time fields - use summarized columns with proper fallbacks
            "plan": row.get("Plan", "00:00"),
            "utility": row.get("Utility", "00:00"),  # U : Utility - the actual running time
            "tp": row.get("TP", "00:00"),
            "ts": row.get("TS", "00:00"),
            "qc": row.get("QC", "00:00"),
            "cm": row.get("CM", "00:00"),
            "no": row.get("NO", "00:00"),
            "np": row.get("NP", "00:00"),
            "nm": row.get("NM", "00:00"),
            "mp": row.get("MP", "00:00"),
            "bt": row.get("BT", "00:00"),
            "br": row.get("BR", "00:00"),
            "total_dt": row.get("Total Downtime", "00:00"),

            # Use summarized Keterangan, not raw transition text
            "catatan": row.get("Keterangan", ""),

            # KPI fields - both percentage strings and numeric values
            "per": row.get("PER", "0%"),
            "per_num": float(row.get("PER Num", 0)),
            "otr": row.get("OTR", "0%"),
            "otr_num": float(row.get("OTR Num", 0)),
            "qr": row.get("QR", "0%"),
            "qr_num": float(row.get("QR Num", 0)),
            "oee": row.get("OEE", "0%"),
            "oee_num": float(row.get("OEE Num", 0)),

            "tanggal": str(row.get("Tanggal", "")),
            "shift": str(row.get("Shift", "")),

            # Row history lineage key
            "history_key": history_key
        }
        detail_rows.append(detail_row)

    # Debug logging - log first row to understand data structure
    DEBUG_BUILD_RESPONSE = False  # Feature flag for debug output

    if DEBUG_BUILD_RESPONSE and len(detail_rows) > 0:
        print(f"\n=== DEBUG: build_detail_export_response ===")
        print(f"Total rows in df: {len(df)}")
        print(f"DataFrame columns: {list(df.columns)}")
        if not df.empty:
            first_row = df.iloc[0]
            print(f"Sample raw row data:")
            print(f"  Plan Minutes: {first_row.get('Plan Minutes', 'MISSING')}")
            print(f"  Plan: {first_row.get('Plan', 'MISSING')}")
            print(f"  Utility Minutes: {first_row.get('Utility Minutes', 'MISSING')}")
            print(f"  Utility: {first_row.get('Utility', 'MISSING')}")
            print(f"  Target: {first_row.get('Target', 'MISSING')}")
            print(f"  Target Qty: {first_row.get('Target Qty', 'MISSING')}")
            print(f"  OTR Num: {first_row.get('OTR Num', 'MISSING')}")
            print(f"  OTR: {first_row.get('OTR', 'MISSING')}")
            print(f"  TP_Minutes: {first_row.get('TP_Minutes', 'MISSING')}")
            print(f"  TP: {first_row.get('TP', 'MISSING')}")
        print(f"Sample formatted response row:")
        sample_response = detail_rows[0]
        print(f"  plan: {sample_response['plan']}")
        print(f"  rt: {sample_response['rt']}")
        print(f"  target_qty: {sample_response['target_qty']}")
        print(f"  per: {sample_response['per']}")
        print(f"  otr: {sample_response['otr']}")
        print(f"=== END DEBUG ===\n")

    # Apply pagination
    total_rows = len(detail_rows)
    if pagination:
        start_idx = (pagination.page - 1) * pagination.page_size
        end_idx = start_idx + pagination.page_size
        detail_rows = detail_rows[start_idx:end_idx]

    return {"rows": detail_rows, "total": total_rows}


def summarize_dashboard_df(df: pd.DataFrame, report_category: Any) -> pd.DataFrame:
    split_df = split_rows_by_shift(df)
    if split_df.empty:
        return split_df

    category_value = _report_category_value(report_category)

    for code in CATEGORY_CODES:
        split_df[f"{code}_Minutes"] = np.where(
            split_df["Desc Code"] == code,
            split_df["_DurationMinutes"],
            0.0,
        )

    # TODO: Add contextual Keterangan column before grouping (temporarily disabled)
    # split_df["Keterangan Context"] = split_df.apply(
    #     lambda row: _format_keterangan_with_context(row, category_value),
    #     axis=1,
    # )

    base_keys = ["Tanggal", "Shift"]
    if category_value == "operator":
        base_keys += ["Operator", "MC", "Part No", "Part Name", "Proses"]
    else:
        base_keys += ["MC", "Part No", "Part Name", "Proses"]

    agg_map: dict[str, Any] = {
        "Qty": "sum",
        "Reject": "sum",
        "Rework": "sum",
        "Target": "max",
        "Keterangan": _join_unique,
        "_StartTs": "min",
        "_StopTs": "max",
    }

    if "Kode Tooling" in split_df.columns:
        agg_map["Kode Tooling"] = _join_unique
    if "Common Tooling Name" in split_df.columns:
        agg_map["Common Tooling Name"] = _join_unique
    if category_value == "mesin" and "Operator" in split_df.columns:
        agg_map["Operator"] = _join_unique
    if category_value == "operator" and "NIK" in split_df.columns:
        agg_map["NIK"] = "first"

    for code in CATEGORY_CODES:
        agg_map[f"{code}_Minutes"] = "sum"

    grouped = (
        split_df.groupby(base_keys, dropna=False)
        .agg(agg_map)
        .reset_index()
    )

    # TODO: Choose contextual vs plain Keterangan (temporarily disabled)
    # if category_value == "mesin":
    #     if "_OperatorCount" in grouped.columns:
    #         grouped["Keterangan"] = np.where(
    #             grouped["_OperatorCount"] > 1,
    #             grouped["Keterangan Context"],
    #             grouped["Keterangan"],
    #         )
    #         grouped.drop(columns=["_OperatorCount"], inplace=True)

    grouped["Total Output"] = grouped["Qty"] + grouped["Reject"] + grouped["Rework"]
    grouped["Utility Minutes"] = grouped.get("U_Minutes", 0.0)
    grouped["Plan Minutes"] = 0.0
    for code in PLAN_INCLUDED_CODES:
        grouped["Plan Minutes"] += grouped.get(f"{code}_Minutes", 0.0)

    grouped["Downtime Minutes"] = (grouped["Plan Minutes"] - grouped["Utility Minutes"]).clip(lower=0)
    grouped["Target Qty"] = grouped["Target"] * (grouped["Plan Minutes"] / 60.0)

    grouped["OTR Num"] = grouped.apply(
        lambda row: _pct(row["Utility Minutes"], row["Plan Minutes"]),
        axis=1,
    )
    grouped["PER Num"] = grouped.apply(
        lambda row: _pct(
            row["Qty"],
            (row["Utility Minutes"] / 60.0) * row["Target"],
        ),
        axis=1,
    )
    grouped["QR Num"] = grouped.apply(
        lambda row: _pct(row["Qty"], row["Total Output"]),
        axis=1,
    )
    grouped["OEE Num"] = (
        grouped["OTR Num"] * grouped["PER Num"] * grouped["QR Num"] / 10000.0
    )

    grouped["Plan"] = grouped["Plan Minutes"].map(_minutes_to_hhmm)
    grouped["Utility"] = grouped["Utility Minutes"].map(_minutes_to_hhmm)
    grouped["Total Downtime"] = grouped["Downtime Minutes"].map(_minutes_to_hhmm)

    for code in CATEGORY_CODES:
        grouped[code] = grouped[f"{code}_Minutes"].map(_minutes_to_hhmm)

    for label, num_col in (
        ("OTR", "OTR Num"),
        ("PER", "PER Num"),
        ("QR", "QR Num"),
        ("OEE", "OEE Num"),
    ):
        grouped[label] = grouped[num_col].round().astype(int).astype(str) + "%"

    sort_cols = [c for c in ["Tanggal", "Shift", "Operator", "MC", "Part No", "Proses"] if c in grouped.columns]
    grouped = grouped.sort_values(sort_cols).reset_index(drop=True)

    return grouped
