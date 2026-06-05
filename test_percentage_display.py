#!/usr/bin/env python3
"""
Test script to verify percentage calculations display correctly
"""

import requests
import json

API_BASE = "http://192.168.1.142:8001"

def test_percentage_display():
    """Test percentage calculations display correctly in row history"""

    print("📊 Testing Percentage Display in Row History")

    try:
        # Get data with broader range to find rows with actual percentages
        detail_payload = {
            "report_type": "mesin",
            "date_from": "2026-04-19",
            "date_to": "2026-04-22",
            "shift_from": 1,
            "shift_to": 3,
            "pagination": {"page": 1, "page_size": 10}
        }

        response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=detail_payload, timeout=30)
        response.raise_for_status()
        detail_data = response.json()

        rows = detail_data.get('rows', [])
        print(f"✅ Got {len(rows)} detail rows")

        # Look for a row with non-zero percentages
        test_row = None
        for row in rows:
            if (row.get('per_num', 0) > 0 or
                row.get('otr_num', 0) > 0 or
                row.get('qr_num', 0) > 0):
                test_row = row
                break

        if not test_row:
            print("⚠️  No rows with non-zero percentages found, using first row")
            test_row = rows[0] if rows else None

        if not test_row:
            print("❌ No test data available")
            return

        print(f"📋 Testing row: {test_row.get('mc_no')} - {test_row.get('status')}")
        print(f"🎯 Row percentages in detail response:")
        print(f"   PER: {test_row.get('per')} (num: {test_row.get('per_num', 0)})")
        print(f"   OTR: {test_row.get('otr')} (num: {test_row.get('otr_num', 0)})")
        print(f"   QR: {test_row.get('qr')} (num: {test_row.get('qr_num', 0)})")
        print(f"   OEE: {test_row.get('oee')} (num: {test_row.get('oee_num', 0)})")

        # Test row history
        history_key = test_row.get('history_key')
        if history_key:
            print(f"\n🔍 Testing row history calculations...")

            history_response = requests.post(f"{API_BASE}/api/reports/dashboard/row-history", json=history_key, timeout=30)
            history_response.raise_for_status()
            history_data = history_response.json()

            calc = history_data.get('calculation', {})
            if calc:
                print(f"🧮 Calculation response:")
                print(f"   Plan minutes: {calc.get('plan_minutes', 0):.1f}")
                print(f"   Utility minutes: {calc.get('utility_minutes', 0):.1f}")
                print(f"   PER num: {calc.get('per_num', 0):.2f}")
                print(f"   OTR num: {calc.get('otr_num', 0):.2f}")
                print(f"   QR num: {calc.get('qr_num', 0):.2f}")
                print(f"   OEE num: {calc.get('oee_num', 0):.2f}")

                # Check if values make sense
                otr_calc = calc.get('utility_minutes', 0) / calc.get('plan_minutes', 1) * 100 if calc.get('plan_minutes', 0) > 0 else 0
                print(f"\n✅ Validation:")
                print(f"   Expected OTR: {otr_calc:.2f}% vs API: {calc.get('otr_num', 0):.2f}%")

                if abs(otr_calc - calc.get('otr_num', 0)) < 0.1:
                    print("✅ OTR calculation looks correct")
                elif calc.get('plan_minutes', 0) == 0:
                    print("ℹ️  No plan time to validate OTR calculation")
                else:
                    print(f"⚠️  OTR calculation mismatch")

            else:
                print("❌ No calculation data in response")

        else:
            print("❌ No history_key to test with")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_percentage_display()