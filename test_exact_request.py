#!/usr/bin/env python3
"""
Test the exact row history request that the user provided
"""

import requests
import json

API_BASE = "http://192.168.1.142:8001"

def test_exact_request():
    """Test the exact request the user provided"""

    # This is the exact request the user sent
    request_payload = {
        "report_type": "mesin",
        "tanggal": "2026-04-22",
        "shift": "3",
        "mc": "A1-MOCK",
        "part_no": "123-456",
        "proses": "1/1"
    }

    print("🧪 Testing Exact User Request")
    print(f"📤 Request: {json.dumps(request_payload, indent=2)}")

    try:
        response = requests.post(
            f"{API_BASE}/api/reports/dashboard/row-history",
            json=request_payload,
            timeout=30
        )

        print(f"📥 Response Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"📊 Response: {json.dumps(data, indent=2)}")

            calculation = data.get('calculation', {})
            timeline = data.get('timeline', [])

            print(f"\n🔍 Analysis:")
            print(f"   Timeline activities: {len(timeline)}")
            print(f"   Plan minutes: {calculation.get('plan_minutes', 0)}")
            print(f"   Utility minutes: {calculation.get('utility_minutes', 0)}")
            print(f"   PER num: {calculation.get('per_num', 0)}")
            print(f"   OTR num: {calculation.get('otr_num', 0)}")

        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"Response text: {response.text}")

    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_exact_request()