#!/usr/bin/env python3
"""
Test script to verify pagination works correctly in dashboard detail API
"""

import requests
import json

API_BASE = "http://192.168.1.142:8001"
ENDPOINT = "/api/reports/dashboard/detail"

def test_pagination():
    """Test that pagination actually works"""

    # Test with small page size to force multiple pages
    base_payload = {
        "report_type": "mesin",
        "date_from": "2026-04-19",
        "date_to": "2026-04-22",
        "shift_from": 1,
        "shift_to": 3,
    }

    print("🧪 Testing Dashboard Pagination")
    print(f"📅 Date range: {base_payload['date_from']} to {base_payload['date_to']}")
    print()

    # Test page 1
    page1_payload = {
        **base_payload,
        "pagination": {"page": 1, "page_size": 3}
    }

    try:
        print("📄 Testing Page 1 (page_size=3)")
        response1 = requests.post(f"{API_BASE}{ENDPOINT}", json=page1_payload, timeout=30)
        response1.raise_for_status()
        data1 = response1.json()

        rows1 = data1.get('rows', [])
        total1 = data1.get('total', 0)

        print(f"✅ Page 1: {len(rows1)} rows returned, total={total1}")

        if total1 > 3:  # Only test page 2 if there's more data
            # Test page 2
            page2_payload = {
                **base_payload,
                "pagination": {"page": 2, "page_size": 3}
            }

            print("📄 Testing Page 2 (page_size=3)")
            response2 = requests.post(f"{API_BASE}{ENDPOINT}", json=page2_payload, timeout=30)
            response2.raise_for_status()
            data2 = response2.json()

            rows2 = data2.get('rows', [])
            total2 = data2.get('total', 0)

            print(f"✅ Page 2: {len(rows2)} rows returned, total={total2}")

            # Check if pagination is working correctly
            if total1 != total2:
                print(f"⚠️  Total count inconsistent: page1={total1}, page2={total2}")

            # Check if we got different data
            page1_ids = [f"{row.get('mc_no', '')}-{row.get('tanggal', '')}-{row.get('shift', '')}" for row in rows1]
            page2_ids = [f"{row.get('mc_no', '')}-{row.get('tanggal', '')}-{row.get('shift', '')}" for row in rows2]

            if set(page1_ids) & set(page2_ids):  # If there's intersection
                print(f"❌ PAGINATION FAILED: Some rows appear on both pages")
                print(f"   Page 1 IDs: {page1_ids}")
                print(f"   Page 2 IDs: {page2_ids}")
            else:
                print("✅ Pagination PASSED: Different rows on each page")

            # Test expected counts
            expected_page1_count = min(3, total1)
            expected_page2_count = min(3, max(0, total1 - 3))

            if len(rows1) == expected_page1_count and len(rows2) == expected_page2_count:
                print("✅ Row counts PASSED: Correct number of rows per page")
            else:
                print(f"❌ Row counts FAILED: Expected {expected_page1_count},{expected_page2_count}, got {len(rows1)},{len(rows2)}")

        else:
            print("⚠️  Only one page of data available, can't test multi-page pagination")

        # Test edge case: request page beyond available data
        if total1 > 0:
            big_page_payload = {
                **base_payload,
                "pagination": {"page": 999, "page_size": 10}
            }

            print("📄 Testing Page 999 (beyond available data)")
            response999 = requests.post(f"{API_BASE}{ENDPOINT}", json=big_page_payload, timeout=30)
            response999.raise_for_status()
            data999 = response999.json()

            rows999 = data999.get('rows', [])
            total999 = data999.get('total', 0)

            print(f"✅ Page 999: {len(rows999)} rows returned, total={total999}")

            if len(rows999) == 0 and total999 == total1:
                print("✅ Edge case PASSED: No rows for page beyond data, but total count correct")
            else:
                print(f"⚠️  Edge case unexpected: got {len(rows999)} rows, total={total999}")

        print("\n🎉 Pagination test completed!")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_pagination()