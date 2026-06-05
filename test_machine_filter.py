#!/usr/bin/env python3
"""
Test machine filtering specifically to debug the issue
"""

import requests
import json

API_BASE = "http://192.168.1.142:8001"

def test_machine_filter():
    """Test machine filtering with dropdown selection"""

    print("🔍 Testing machine filter...")

    # Test 1: Get all data first to see available machines
    all_data_payload = {
        "report_type": "mesin",
        "date_from": "2026-04-19",
        "date_to": "2026-04-22",
        "shift_from": 1,
        "shift_to": 3,
        "pagination": {"page": 1, "page_size": 20}
    }

    try:
        print("1️⃣ Getting all data to see available machines...")
        response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=all_data_payload, timeout=30)
        response.raise_for_status()
        all_data = response.json()

        all_rows = all_data.get('rows', [])
        total = all_data.get('total', 0)
        print(f"✅ All data: {len(all_rows)} rows shown, {total} total")

        if all_rows:
            machines = list(set(row.get('mc_no', '') for row in all_rows if row.get('mc_no') != '-'))
            print(f"📋 Available machines: {machines}")

            if machines:
                # Test 2: Filter by first machine using selectedMachines approach
                test_machine = machines[0]
                filtered_payload = {
                    "report_type": "mesin",
                    "date_from": "2026-04-19",
                    "date_to": "2026-04-22",
                    "shift_from": 1,
                    "shift_to": 3,
                    "filters": {
                        "mc": {
                            "type": "string",
                            "in": [test_machine]  # This should match selectedMachines filtering
                        }
                    },
                    "pagination": {"page": 1, "page_size": 20}
                }

                print(f"\n2️⃣ Testing filter by machine: {test_machine}")
                print(f"📤 Filter payload: {json.dumps(filtered_payload['filters'], indent=2)}")

                filtered_response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=filtered_payload, timeout=30)
                filtered_response.raise_for_status()
                filtered_data = filtered_response.json()

                filtered_rows = filtered_data.get('rows', [])
                filtered_total = filtered_data.get('total', 0)

                print(f"✅ Filtered data: {len(filtered_rows)} rows shown, {filtered_total} total")

                if filtered_rows:
                    # Check if all returned rows match the filter
                    matching_machines = [row.get('mc_no', '') for row in filtered_rows]
                    unique_machines = set(matching_machines)

                    print(f"📋 Machines in filtered results: {list(unique_machines)}")

                    if len(unique_machines) == 1 and test_machine in unique_machines:
                        print("✅ FILTER WORKING: All rows match the selected machine")
                    elif test_machine in unique_machines:
                        print(f"⚠️  PARTIAL MATCH: Expected only {test_machine}, got {list(unique_machines)}")
                    else:
                        print(f"❌ FILTER FAILED: Expected {test_machine}, got {list(unique_machines)}")

                    # Show comparison
                    print(f"\n📊 Results comparison:")
                    print(f"   Unfiltered: {total} total rows")
                    print(f"   Filtered: {filtered_total} total rows")

                    if filtered_total < total:
                        print("✅ Filtering reduced row count (good)")
                    else:
                        print("❌ Filtering did not reduce row count (bad)")

                else:
                    print("❌ No rows returned after filtering")

                # Test 3: Test with contains filter for comparison
                contains_payload = {
                    "report_type": "mesin",
                    "date_from": "2026-04-19",
                    "date_to": "2026-04-22",
                    "shift_from": 1,
                    "shift_to": 3,
                    "filters": {
                        "mc": {
                            "type": "string",
                            "contains": test_machine
                        }
                    },
                    "pagination": {"page": 1, "page_size": 20}
                }

                print(f"\n3️⃣ Testing contains filter for comparison...")
                contains_response = requests.post(f"{API_BASE}/api/reports/dashboard/detail", json=contains_payload, timeout=30)
                contains_response.raise_for_status()
                contains_data = contains_response.json()

                contains_total = contains_data.get('total', 0)
                print(f"✅ Contains filter: {contains_total} total rows")

                if filtered_total == contains_total:
                    print("✅ Both 'in' and 'contains' filters return same count (good)")
                else:
                    print(f"⚠️  'in' filter returned {filtered_total}, 'contains' returned {contains_total}")
            else:
                print("❌ No machines found to test with")
        else:
            print("❌ No data returned to test with")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_machine_filter()