#!/usr/bin/env python3
"""
Test script to trace Report Table data flow end-to-end
"""
import sys
import os

# Add the correct path to import from services
sys.path.append('/Users/grace.susanto/src/imn/production app/IMN-production-report/services/web')

from datetime import datetime, timedelta
from app.cmd.generate_report import get_detail_export_report, ReportCategory
from app.service import report_summary as rs
import pandas as pd

def test_report_table_flow():
    """Test the complete flow for Report Table data"""
    print("=== Testing Report Table Data Flow ===")

    # Test with recent date
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    date_from = yesterday.strftime('%Y-%m-%d')
    date_to = today.strftime('%Y-%m-%d')

    print(f"Testing date range: {date_from} to {date_to}")

    try:
        # Call the actual API endpoint function
        result = get_detail_export_report(
            report_category=ReportCategory.MESIN,
            date_time_from=date_from,
            shift_from=1,
            date_time_to=date_to,
            shift_to=3,
            pagination=None,
            filters={},
            sort=None
        )

        print(f"Result type: {type(result)}")
        print(f"Result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")

        if isinstance(result, dict) and 'rows' in result:
            rows = result['rows']
            print(f"Number of rows: {len(rows)}")

            if len(rows) > 0:
                print("\n=== First Row Analysis ===")
                first_row = rows[0]

                # Check time fields
                time_fields = ['plan', 'rt', 'tp', 'ts', 'qc', 'cm', 'no', 'np', 'nm', 'mp', 'bt', 'br', 'total_dt']
                print("Time fields:")
                for field in time_fields:
                    value = first_row.get(field, 'MISSING')
                    print(f"  {field}: {value}")

                # Check KPI fields
                kpi_fields = ['target_qty', 'per', 'otr', 'qr', 'oee']
                print("\nKPI fields:")
                for field in kpi_fields:
                    value = first_row.get(field, 'MISSING')
                    print(f"  {field}: {value}")

                # Check data quality indicators
                print(f"\nData Quality Check:")
                print(f"  output: {first_row.get('output', 0)}")
                print(f"  reject: {first_row.get('reject', 0)}")
                print(f"  catatan: {first_row.get('catatan', '')[:50]}...")

                # Check if this looks like raw vs summarized data
                catatan = first_row.get('catatan', '')
                if ' -> ' in catatan or 'stop' in catatan.lower():
                    print("  WARNING: Catatan looks like raw transition text!")
                    print("  This suggests data is not properly summarized.")

                # Check if time fields are all zero
                non_zero_times = [f for f in time_fields if first_row.get(f, '00:00') != '00:00']
                if not non_zero_times:
                    print("  WARNING: All time fields are 00:00!")
                    print("  This suggests time bucket calculation failed.")
                else:
                    print(f"  Non-zero time fields: {non_zero_times}")

        else:
            print("ERROR: Result does not have expected structure")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_summarization_function():
    """Test just the summarization function with mock data"""
    print("\n=== Testing Summarization Function ===")

    # Create mock raw data that looks like what get_report_with_overlap_window returns
    mock_data = pd.DataFrame([
        {
            'Tanggal': '2024-01-15',
            'Shift': '1',
            'MC': 'M001',
            'Part No': 'P001',
            'Part Name': 'Test Part',
            'Proses': 'MACHINING',
            'Operator': 'OP001',
            'Target': 100,
            'Qty': 80,
            'Reject': 5,
            'Rework': 2,
            'Keterangan': 'Normal operation',
            '_StartTs': datetime.now() - timedelta(hours=8),
            '_StopTs': datetime.now() - timedelta(hours=7),
            '_DurationMinutes': 60,
            'Desc Code': 'U'  # Runtime
        },
        {
            'Tanggal': '2024-01-15',
            'Shift': '1',
            'MC': 'M001',
            'Part No': 'P001',
            'Part Name': 'Test Part',
            'Proses': 'MACHINING',
            'Operator': 'OP001',
            'Target': 100,
            'Qty': 0,
            'Reject': 0,
            'Rework': 0,
            'Keterangan': 'Tool change',
            '_StartTs': datetime.now() - timedelta(hours=7),
            '_StopTs': datetime.now() - timedelta(hours=6.5),
            '_DurationMinutes': 30,
            'Desc Code': 'TP'  # Tool change
        }
    ])

    print("Mock input data:")
    print(mock_data[['MC', 'Desc Code', '_DurationMinutes', 'Qty', 'Reject']].to_string())

    try:
        # Test summarization
        summarized = rs.summarize_dashboard_df(mock_data, ReportCategory.MESIN)

        print(f"\nSummarized data shape: {summarized.shape}")
        print("Summarized columns:")
        for col in sorted(summarized.columns):
            print(f"  {col}")

        if not summarized.empty:
            print("\nFirst summarized row:")
            first_row = summarized.iloc[0]

            # Check key calculated fields
            key_fields = ['Plan', 'Utility', 'U', 'TP', 'Plan Minutes', 'Utility Minutes',
                         'OTR', 'PER', 'QR', 'OEE', 'Target Qty']
            for field in key_fields:
                if field in first_row:
                    value = first_row[field]
                    print(f"  {field}: {value}")
                else:
                    print(f"  {field}: MISSING")

    except Exception as e:
        print(f"ERROR in summarization: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_report_table_flow()
    test_summarization_function()