#!/usr/bin/env python3
"""
Test the POST /report/mesin endpoint to see if it returns data.
"""

import requests
import json
from datetime import datetime, timedelta

def test_report_endpoint():
    """Test the POST /report/mesin endpoint."""
    print("=== Testing POST /report/mesin endpoint ===")

    # Test data for the request
    test_request = {
        "format": "dashboard-mesin",  # Use dashboard format to get JSON response
        "date_from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
        "date_to": datetime.now().strftime("%Y-%m-%d"),
        "shift_from": 1,
        "shift_to": 3,
        "pagination": {
            "page": 1,
            "limit": 10
        },
        "filters": {},
        "sort": {}
    }

    try:
        # Make the API call
        response = requests.post(
            "http://localhost:8001/report/mesin",
            json=test_request,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, list):
                    print(f"✓ Success! Got {len(data)} records")
                    if data:
                        print("Sample record keys:", list(data[0].keys()) if data[0] else "Empty record")
                    else:
                        print("❌ No data returned - this is the blank report issue!")
                else:
                    print(f"✓ Success! Got response: {type(data)}")
            except Exception as e:
                print(f"✓ Response received but not JSON: {e}")
        else:
            print(f"❌ Error: {response.status_code}")
            try:
                print("Response:", response.text[:500])
            except:
                pass

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to API at localhost:8001")
        return False
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False

    return True

if __name__ == "__main__":
    test_report_endpoint()