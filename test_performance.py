#!/usr/bin/env python3
"""
Test script to measure performance improvement of database-level filtering
"""

import requests
import json
import time

API_BASE = "http://192.168.1.142:8001"
ENDPOINT = "/api/reports/dashboard/detail"

def test_performance():
    """Test performance of the optimized database filtering"""

    # Test with a date range that should have some data
    test_payload = {
        "report_type": "mesin",
        "date_from": "2026-04-19",
        "date_to": "2026-04-22",
        "shift_from": 1,
        "shift_to": 3,
        "pagination": {
            "page": 1,
            "page_size": 50
        },
        "filters": {
            # Test with some machine filtering to see DB-level filter performance
        }
    }

    print("⚡ Testing Performance of Optimized Database Filtering")
    print(f"📅 Date range: {test_payload['date_from']} to {test_payload['date_to']}")
    print(f"📄 Page size: {test_payload['pagination']['page_size']}")
    print()

    # Test 1: No additional filters (baseline)
    print("🔍 Test 1: No additional filters")
    start_time = time.time()

    try:
        response = requests.post(f"{API_BASE}{ENDPOINT}", json=test_payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        end_time = time.time()
        duration = end_time - start_time

        rows = data.get('rows', [])
        total = data.get('total', 0)

        print(f"✅ Baseline test: {duration:.2f}s")
        print(f"📊 Results: {len(rows)} rows returned, {total} total available")

        baseline_time = duration

        # Test 2: With machine filter (should still be fast due to DB filtering)
        if total > 0 and rows:
            # Get a machine name from the results to filter by
            sample_machine = rows[0].get('mc_no', '')
            if sample_machine and sample_machine != '-':
                print(f"\n🔍 Test 2: With machine filter (MC = '{sample_machine}')")

                test_payload_filtered = {
                    **test_payload,
                    "filters": {
                        "mc": {
                            "type": "string",
                            "contains": sample_machine
                        }
                    }
                }

                start_time = time.time()
                response_filtered = requests.post(f"{API_BASE}{ENDPOINT}", json=test_payload_filtered, timeout=30)
                response_filtered.raise_for_status()
                data_filtered = response_filtered.json()
                end_time = time.time()

                filtered_duration = end_time - start_time
                filtered_rows = data_filtered.get('rows', [])
                filtered_total = data_filtered.get('total', 0)

                print(f"✅ Filtered test: {filtered_duration:.2f}s")
                print(f"📊 Results: {len(filtered_rows)} rows returned, {filtered_total} total available")

                # Performance analysis
                if filtered_duration < baseline_time * 1.5:  # Allow some variance
                    print(f"🚀 PERFORMANCE GOOD: Filtering overhead minimal ({filtered_duration/baseline_time:.1f}x baseline)")
                else:
                    print(f"⚠️  PERFORMANCE CONCERN: Filtering took {filtered_duration/baseline_time:.1f}x baseline time")

                # Verify filtering worked
                machine_match_count = sum(1 for row in filtered_rows if sample_machine in row.get('mc_no', ''))
                if machine_match_count == len(filtered_rows) and len(filtered_rows) > 0:
                    print("✅ FILTERING ACCURACY: All returned rows match filter")
                elif len(filtered_rows) == 0:
                    print("⚠️  FILTERING RESULT: No rows match filter (may be expected)")
                else:
                    print(f"❌ FILTERING ERROR: {machine_match_count}/{len(filtered_rows)} rows match filter")

        # Test 3: Multiple pages to test pagination performance
        if total > test_payload['pagination']['page_size']:
            print(f"\n🔍 Test 3: Pagination performance (Page 2)")

            test_payload_page2 = {
                **test_payload,
                "pagination": {
                    "page": 2,
                    "page_size": test_payload['pagination']['page_size']
                }
            }

            start_time = time.time()
            response_page2 = requests.post(f"{API_BASE}{ENDPOINT}", json=test_payload_page2, timeout=30)
            response_page2.raise_for_status()
            data_page2 = response_page2.json()
            end_time = time.time()

            page2_duration = end_time - start_time
            page2_rows = data_page2.get('rows', [])

            print(f"✅ Page 2 test: {page2_duration:.2f}s")
            print(f"📊 Results: {len(page2_rows)} rows returned")

            if page2_duration < baseline_time * 1.5:
                print(f"🚀 PAGINATION PERFORMANCE GOOD: {page2_duration/baseline_time:.1f}x baseline")
            else:
                print(f"⚠️  PAGINATION PERFORMANCE: {page2_duration/baseline_time:.1f}x baseline time")

        print(f"\n🎯 Summary:")
        print(f"   • Baseline query: {baseline_time:.2f}s for {total} total records")
        print(f"   • Database-level filtering should be much faster than previous in-memory approach")
        print(f"   • Page size {test_payload['pagination']['page_size']} loads efficiently")

    except requests.exceptions.RequestException as e:
        print(f"❌ API request failed: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode failed: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_performance()