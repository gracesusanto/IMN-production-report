#!/usr/bin/env python3
"""
Test script to verify row history API works correctly
"""

import requests
import json

API_BASE = "http://192.168.1.142:8001"

def test_row_history():
    """Test the row history API endpoint"""

    # First get some detail data to extract a history_key - use same range as performance test
    detail_payload = {
        "report_type": "mesin",
        "date_from": "2026-04-19",
        "date_to": "2026-04-22",
        "shift_from": 1,
        "shift_to": 3,
        "pagination": {"page": 1, "page_size": 10}
    }

    print("🔍 Getting detail data to find a row to test...")
    try:
        detail_response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=detail_payload, timeout=30)
        detail_response.raise_for_status()
        detail_data = detail_response.json()

        rows = detail_data.get('rows', [])
        if not rows:
            print("❌ No detail rows found to test with")
            return

        # Get the first row's history_key
        test_row = rows[0]
        history_key = test_row.get('history_key', {})

        print(f"✅ Found test row: {test_row['mc_no']} / {test_row['part_no_name']}")
        print(f"📋 History key: {history_key}")

        if not history_key:
            print("❌ No history_key found in row")
            return

        # Test the row history endpoint
        print("\n🔍 Testing row history API...")
        history_response = requests.post(f"{API_BASE}/api/reports/dashboard/row-history", json=history_key, timeout=30)
        history_response.raise_for_status()
        history_data = history_response.json()

        # Verify response structure
        if all(key in history_data for key in ['summary', 'timeline', 'calculation']):
            print("✅ Row history response has correct structure")

            summary = history_data['summary']
            timeline = history_data['timeline']
            calculation = history_data['calculation']

            print(f"📊 Summary: {summary.get('mc_no', 'N/A')} - {summary.get('status', 'N/A')}")
            print(f"📅 Timeline: {len(timeline)} activities")

            if timeline:
                first_activity = timeline[0]
                print(f"   First: {first_activity.get('start_time', 'N/A')} - {first_activity.get('desc', 'N/A')}")

            print(f"🧮 Calculation: OEE={calculation.get('oee_num', 0)}% (OTR={calculation.get('otr_num', 0)}% × PER={calculation.get('per_num', 0)}% × QR={calculation.get('qr_num', 0)}%)")

            # Verify the summary matches the original row
            if (summary.get('mc_no') == test_row.get('mc_no') and
                summary.get('tanggal') == test_row.get('tanggal') and
                summary.get('shift') == test_row.get('shift')):
                print("✅ Row history summary matches original row")
            else:
                print("⚠️  Row history summary doesn't match original row")

        else:
            print("❌ Row history response missing required keys")
            print(f"Got keys: {list(history_data.keys())}")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_row_history()