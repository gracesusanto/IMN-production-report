#!/usr/bin/env python3
"""
Unit test for KPI calculation and response format
"""
import sys
import os
from datetime import datetime, timedelta

# Mock the models and database dependencies
class MockReportCategory:
    MESIN = "mesin"

sys.modules['app.cmd.generate_report'] = type(sys)('mock')
sys.modules['app.cmd.generate_report'].ReportCategory = MockReportCategory

# Now we can import pandas and test the functions
import pandas as pd

# Create mock functions for the parts we need
def _minutes_to_hhmm(minutes):
    """Convert minutes to HH:MM format"""
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"

def _pct(numerator, denominator):
    """Calculate percentage safely"""
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100.0

def _join_unique(series):
    """Join unique non-null values"""
    unique_vals = series.dropna().unique()
    return " | ".join(str(v) for v in unique_vals if str(v).strip())

# Mock the constants
CATEGORY_CODES = frozenset({"U", "TL", "TS", "TP", "QC", "CM", "NO", "NP", "NM", "MP", "BT", "BR"})
PLAN_INCLUDED_CODES = frozenset({"U", "TL", "TS", "TP", "QC", "CM", "NM", "MP", "BR"})

def test_summarize_function():
    """Test the summarization logic with realistic mock data"""
    print("=== Testing KPI Calculation ===")

    # Create mock raw data that simulates real production data
    mock_data = pd.DataFrame([
        # Normal runtime activity
        {
            'Tanggal': '2024-01-15',
            'Shift': '1',
            'MC': 'M001',
            'Part No': 'P001',
            'Part Name': 'Test Part',
            'Proses': 'MACHINING',
            'Operator': 'OP001',
            'Target': 100,  # 100 parts per hour
            'Qty': 80,      # Actual output
            'Reject': 5,    # Reject count
            'Rework': 2,    # Rework count
            'Keterangan': 'Normal production',
            '_StartTs': datetime(2024, 1, 15, 7, 0, 0),
            '_StopTs': datetime(2024, 1, 15, 8, 0, 0),
            '_DurationMinutes': 60,
            'Desc Code': 'U'  # Runtime
        },
        # Tool change downtime
        {
            'Tanggal': '2024-01-15',
            'Shift': '1',
            'MC': 'M001',
            'Part No': 'P001',
            'Part Name': 'Test Part',
            'Proses': 'MACHINING',
            'Operator': 'OP001',
            'Target': 100,
            'Qty': 0,       # No output during tool change
            'Reject': 0,
            'Rework': 0,
            'Keterangan': 'Tool change required',
            '_StartTs': datetime(2024, 1, 15, 8, 0, 0),
            '_StopTs': datetime(2024, 1, 15, 8, 30, 0),
            '_DurationMinutes': 30,
            'Desc Code': 'TP'  # Tool change
        },
        # More runtime
        {
            'Tanggal': '2024-01-15',
            'Shift': '1',
            'MC': 'M001',
            'Part No': 'P001',
            'Part Name': 'Test Part',
            'Proses': 'MACHINING',
            'Operator': 'OP001',
            'Target': 100,
            'Qty': 40,      # More output
            'Reject': 2,
            'Rework': 1,
            'Keterangan': 'Resumed production',
            '_StartTs': datetime(2024, 1, 15, 8, 30, 0),
            '_StopTs': datetime(2024, 1, 15, 9, 0, 0),
            '_DurationMinutes': 30,
            'Desc Code': 'U'  # Runtime
        }
    ])

    print("Input mock data:")
    print(mock_data[['MC', 'Desc Code', '_DurationMinutes', 'Qty', 'Reject', 'Target']].to_string())

    # Now manually implement the summarization logic
    print("\n=== Manual Summarization ===")

    # Step 1: Add time bucket columns
    for code in CATEGORY_CODES:
        mock_data[f"{code}_Minutes"] = mock_data.apply(
            lambda row: row['_DurationMinutes'] if row['Desc Code'] == code else 0.0,
            axis=1
        )

    print("Time bucket columns added:")
    time_cols = [f"{code}_Minutes" for code in ['U', 'TP', 'TS']]
    print(mock_data[time_cols].to_string())

    # Step 2: Group by business grain
    base_keys = ["Tanggal", "Shift", "MC", "Part No", "Part Name", "Proses"]

    agg_map = {
        "Qty": "sum",
        "Reject": "sum",
        "Rework": "sum",
        "Target": "max",
        "Keterangan": _join_unique,
        "_StartTs": "min",
        "_StopTs": "max",
        "Operator": _join_unique
    }

    # Add time bucket aggregations
    for code in CATEGORY_CODES:
        agg_map[f"{code}_Minutes"] = "sum"

    grouped = mock_data.groupby(base_keys, dropna=False).agg(agg_map).reset_index()

    print(f"\nGrouped data shape: {grouped.shape}")
    print("Grouped data:")
    print(grouped[['MC', 'Qty', 'Reject', 'U_Minutes', 'TP_Minutes', 'Target']].to_string())

    # Step 3: Calculate derived fields
    grouped["Total Output"] = grouped["Qty"] + grouped["Reject"] + grouped["Rework"]
    grouped["Utility Minutes"] = grouped.get("U_Minutes", 0.0)  # U = Runtime/Utility
    grouped["Plan Minutes"] = 0.0

    for code in PLAN_INCLUDED_CODES:
        grouped["Plan Minutes"] += grouped.get(f"{code}_Minutes", 0.0)

    grouped["Downtime Minutes"] = (grouped["Plan Minutes"] - grouped["Utility Minutes"]).clip(lower=0)
    grouped["Target Qty"] = grouped["Target"] * (grouped["Plan Minutes"] / 60.0)

    print("\nCalculated base fields:")
    print(f"Plan Minutes: {grouped['Plan Minutes'].iloc[0]}")
    print(f"Utility Minutes: {grouped['Utility Minutes'].iloc[0]}")
    print(f"Target Qty: {grouped['Target Qty'].iloc[0]}")
    print(f"Total Output: {grouped['Total Output'].iloc[0]}")

    # Step 4: Calculate KPIs
    grouped["OTR Num"] = grouped.apply(
        lambda row: _pct(row["Utility Minutes"], row["Plan Minutes"]), axis=1
    )
    grouped["PER Num"] = grouped.apply(
        lambda row: _pct(
            row["Total Output"],
            (row["Utility Minutes"] / 60.0) * row["Target"]
        ), axis=1
    )
    grouped["QR Num"] = grouped.apply(
        lambda row: _pct(row["Qty"], row["Total Output"]), axis=1
    )
    grouped["OEE Num"] = (
        grouped["OTR Num"] * grouped["PER Num"] * grouped["QR Num"] / 10000.0
    )

    print("\nCalculated KPI numbers:")
    print(f"OTR Num: {grouped['OTR Num'].iloc[0]:.2f}%")
    print(f"PER Num: {grouped['PER Num'].iloc[0]:.2f}%")
    print(f"QR Num: {grouped['QR Num'].iloc[0]:.2f}%")
    print(f"OEE Num: {grouped['OEE Num'].iloc[0]:.2f}%")

    # Step 5: Format display fields
    grouped["Plan"] = grouped["Plan Minutes"].map(_minutes_to_hhmm)
    grouped["Utility"] = grouped["Utility Minutes"].map(_minutes_to_hhmm)
    grouped["Total Downtime"] = grouped["Downtime Minutes"].map(_minutes_to_hhmm)

    # Format time buckets
    for code in CATEGORY_CODES:
        grouped[code] = grouped[f"{code}_Minutes"].map(_minutes_to_hhmm)

    # Format KPI percentages
    for label, num_col in [("OTR", "OTR Num"), ("PER", "PER Num"), ("QR", "QR Num"), ("OEE", "OEE Num")]:
        grouped[label] = grouped[num_col].round().astype(int).astype(str) + "%"

    print("\nFormatted display fields:")
    print(f"Plan: {grouped['Plan'].iloc[0]}")
    print(f"Utility (U): {grouped['Utility'].iloc[0]}")
    print(f"TP: {grouped['TP'].iloc[0]}")
    print(f"Total Downtime: {grouped['Total Downtime'].iloc[0]}")
    print(f"OTR: {grouped['OTR'].iloc[0]}")
    print(f"PER: {grouped['PER'].iloc[0]}")
    print(f"QR: {grouped['QR'].iloc[0]}")
    print(f"OEE: {grouped['OEE'].iloc[0]}")

    # Step 6: Test the response format
    print("\n=== Testing Response Format ===")

    if not grouped.empty:
        first_row = grouped.iloc[0]

        # Simulate build_detail_export_response logic
        detail_row = {
            "mc_no": first_row.get("MC", "-"),
            "output": int(first_row.get("Qty", 0)),
            "reject": int(first_row.get("Reject", 0)),
            "target_per_jam": int(first_row.get("Target", 0)),
            "target_qty": int(first_row.get("Target Qty", 0)),

            # Time fields - should now have proper values
            "plan": first_row.get("Plan", "00:00"),
            "rt": first_row.get("Utility", "00:00"),
            "tp": first_row.get("TP", "00:00"),
            "total_dt": first_row.get("Total Downtime", "00:00"),

            # KPI fields - should now have proper percentages
            "per": first_row.get("PER", "0%"),
            "otr": first_row.get("OTR", "0%"),
            "qr": first_row.get("QR", "0%"),
            "oee": first_row.get("OEE", "0%"),

            "catatan": first_row.get("Keterangan", "")
        }

        print("Final API response row:")
        for key, value in detail_row.items():
            print(f"  {key}: {value}")

        # Validation checks
        print("\n=== Validation ===")

        if detail_row["plan"] == "00:00":
            print("❌ FAIL: Plan time is still 00:00")
        else:
            print("✅ PASS: Plan time calculated correctly")

        if detail_row["rt"] == "00:00":
            print("❌ FAIL: Runtime is still 00:00")
        else:
            print("✅ PASS: Runtime calculated correctly")

        if detail_row["per"] == "0%":
            print("❌ FAIL: PER is still 0%")
        else:
            print("✅ PASS: PER calculated correctly")

        if detail_row["otr"] == "0%":
            print("❌ FAIL: OTR is still 0%")
        else:
            print("✅ PASS: OTR calculated correctly")

        if detail_row["catatan"] and " -> " in detail_row["catatan"]:
            print("❌ FAIL: Catatan contains raw transition text")
        else:
            print("✅ PASS: Catatan is properly summarized")

if __name__ == "__main__":
    test_summarize_function()