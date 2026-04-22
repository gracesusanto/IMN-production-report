#!/usr/bin/env python3
"""
Test if the API server is running and responding
"""

import requests

API_BASE = "http://192.168.1.142:8001"

def test_server():
    """Test if server is responding"""
    try:
        # Try the detail endpoint first
        response = requests.get(f"{API_BASE}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running and responding")
        else:
            print(f"⚠️  Server responded with status {response.status_code}")

        # Test the detail endpoint
        detail_payload = {
            "report_type": "mesin",
            "date_from": "2026-04-22",
            "date_to": "2026-04-22",
            "shift_from": 3,
            "shift_to": 3,
            "pagination": {"page": 1, "page_size": 1}
        }

        response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=detail_payload, timeout=10)
        print(f"Detail endpoint status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Detail endpoint returned: {len(data.get('rows', []))} rows")

            if data.get('rows'):
                row = data['rows'][0]
                print(f"Sample row keys: {list(row.keys())}")
                print(f"History key present: {'history_key' in row}")
        else:
            print(f"Detail endpoint error: {response.text}")

    except Exception as e:
        print(f"❌ Server connection failed: {e}")

if __name__ == "__main__":
    test_server()