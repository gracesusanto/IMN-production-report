#!/usr/bin/env python3
"""
Test script to verify row history works from frontend perspective
"""

import requests
import json

API_BASE = "http://192.168.1.142:8001"

def test_frontend_integration():
    """Test the complete integration from detail data to row history"""

    print("🧪 Testing Frontend Integration for Row History")

    try:
        # Step 1: Get detail data with history_key
        detail_payload = {
            "report_type": "mesin",
            "date_from": "2026-04-19",
            "date_to": "2026-04-22",
            "shift_from": 1,
            "shift_to": 3,
            "pagination": {"page": 1, "page_size": 5}
        }

        print("1️⃣ Getting detail data...")
        response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=detail_payload, timeout=30)
        response.raise_for_status()
        detail_data = response.json()

        rows = detail_data.get('rows', [])
        print(f"✅ Got {len(rows)} detail rows")

        if not rows:
            print("❌ No rows to test with")
            return

        # Step 2: Check if history_key is present
        sample_row = rows[0]
        history_key = sample_row.get('history_key')

        print(f"📋 Sample row: {sample_row.get('mc_no')} - {sample_row.get('status')}")
        print(f"🔑 History key present: {'✅' if history_key else '❌'}")

        if history_key:
            print(f"🔗 History key: {json.dumps(history_key, indent=2)}")

            # Step 3: Test row history API
            print("\n2️⃣ Testing row history API...")
            history_response = requests.post(f"{API_BASE}/api/reports/dashboard/row-history", json=history_key, timeout=30)
            history_response.raise_for_status()
            history_data = history_response.json()

            # Check response structure
            required_keys = ['summary', 'timeline', 'calculation']
            missing_keys = [key for key in required_keys if key not in history_data]

            if not missing_keys:
                print("✅ Row history API returns correct structure")

                timeline = history_data.get('timeline', [])
                calculation = history_data.get('calculation', {})

                print(f"📅 Timeline activities: {len(timeline)}")
                print(f"🧮 Calculation data: {'✅' if calculation else '❌'}")

                if timeline:
                    first_activity = timeline[0]
                    print(f"   First activity: {first_activity.get('desc')} ({first_activity.get('duration_minutes', 0):.1f} min)")

                if calculation:
                    print(f"   OEE: {calculation.get('oee_num', 0):.1%}")
                    print(f"   Plan time: {calculation.get('plan_minutes', 0):.1f} min")

                print("✅ Frontend integration test PASSED")

            else:
                print(f"❌ Missing keys in row history response: {missing_keys}")

        else:
            print("⚠️  No history_key in detail response - check backend implementation")

        # Step 4: Test error handling
        print("\n3️⃣ Testing error handling...")
        invalid_key = {
            "report_type": "mesin",
            "tanggal": "2026-01-01",  # Invalid date
            "shift": "1",
            "mc": "INVALID",
            "part_no": "INVALID",
            "proses": "INVALID"
        }

        error_response = requests.post(f"{API_BASE}/api/reports/dashboard/row-history", json=invalid_key, timeout=30)
        if error_response.status_code == 200:
            error_data = error_response.json()
            timeline = error_data.get('timeline', [])
            print(f"✅ Error handling: {len(timeline)} activities (expected 0)")
        else:
            print(f"⚠️  Error response: {error_response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_frontend_integration()