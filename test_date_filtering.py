#!/usr/bin/env python3
"""
Test script to verify date filtering works correctly in dashboard detail API
"""

import requests
import json
from datetime import date

API_BASE = "http://192.168.1.142:8001"
ENDPOINT = "/api/reports/dashboard/detail"

def test_date_filtering():
    """Test that date filtering actually works"""

    # Test date range: 2026-04-21 to 2026-04-21 (single day)
    test_payload = {
        "report_type": "mesin",
        "date_from": "2026-04-21",
        "date_to": "2026-04-21",
        "shift_from": 1,
        "shift_to": 1,
        "pagination": {
            "page": 1,
            "page_size": 100
        }
    }

    print("🧪 Testing Dashboard Detail Date Filtering")
    print(f"📅 Request: {test_payload['date_from']} to {test_payload['date_to']}")
    print(f"🕒 Shifts: {test_payload['shift_from']} to {test_payload['shift_to']}")
    print()

    try:
        response = requests.post(f"{API_BASE}{ENDPOINT}", json=test_payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        rows = data.get('rows', [])

        print(f"✅ API call successful: {len(rows)} rows returned")

        if not rows:
            print("⚠️  No data returned - this might be expected if no data exists for the date range")
            return

        # Check date constraints
        date_violations = []
        shift_violations = []

        for i, row in enumerate(rows):
            tanggal = row.get('tanggal')
            shift = row.get('shift')

            # Check date range
            if tanggal:
                if tanggal < test_payload['date_from'] or tanggal > test_payload['date_to']:
                    date_violations.append((i, tanggal))

            # Check shift range
            if shift:
                shift_int = int(shift) if str(shift).isdigit() else 0
                if shift_int < test_payload['shift_from'] or shift_int > test_payload['shift_to']:
                    shift_violations.append((i, shift))

        # Report results
        if date_violations:
            print(f"❌ DATE FILTERING FAILED: {len(date_violations)} rows outside date range:")
            for i, bad_date in date_violations[:5]:  # Show first 5
                print(f"   Row {i}: tanggal={bad_date} (expected: {test_payload['date_from']} to {test_payload['date_to']})")
        else:
            print("✅ Date filtering PASSED: All rows within requested date range")

        if shift_violations:
            print(f"❌ SHIFT FILTERING FAILED: {len(shift_violations)} rows outside shift range:")
            for i, bad_shift in shift_violations[:5]:  # Show first 5
                print(f"   Row {i}: shift={bad_shift} (expected: {test_payload['shift_from']} to {test_payload['shift_to']})")
        else:
            print("✅ Shift filtering PASSED: All rows within requested shift range")

        # Show sample of dates
        sample_dates = [row.get('tanggal') for row in rows[:10]]
        sample_shifts = [row.get('shift') for row in rows[:10]]
        print(f"\n📊 Sample dates: {sample_dates}")
        print(f"📊 Sample shifts: {sample_shifts}")

        # Overall result
        if not date_violations and not shift_violations:
            print("\n🎉 TEST PASSED: Date and shift filtering working correctly!")
        else:
            print(f"\n💥 TEST FAILED: Found {len(date_violations)} date violations and {len(shift_violations)} shift violations")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_date_filtering()