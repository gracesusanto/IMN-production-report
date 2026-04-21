#!/usr/bin/env python3
"""
Populate database with test data and test the Report Table API
"""
import sys
import os
from datetime import datetime

# Add the correct path to import from services
sys.path.append('/Users/grace.susanto/src/imn/production app/IMN-production-report/services/web')

from app.cmd.mock_data import mock_data, mock_activity
from app.database import get_engine
from sqlalchemy.orm import sessionmaker

def populate_and_test():
    """Populate database with mock data and test the API"""
    print("=== Populating Test Data ===")

    # Create database session
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # First create master data (machines, toolings, operators)
        print("Creating master data...")
        mesin_ids, tooling_ids, operator_ids = mock_data(session)
        print(f"Created {len(mesin_ids)} machines, {len(tooling_ids)} toolings, {len(operator_ids)} operators")

        # Then create activity data
        print("Creating activity data...")
        mock_activity(session)
        print("Activity data created successfully")

        # Commit all changes
        session.commit()
        print("All data committed to database")

    except Exception as e:
        print(f"Error populating data: {e}")
        session.rollback()
        raise
    finally:
        session.close()

    print("\n=== Testing Report Table API ===")

    # Test the API with today's date (since mock data uses current time)
    today = datetime.now().strftime('%Y-%m-%d')

    import subprocess
    import json

    # Test mesin report
    print(f"Testing machine report for {today}...")
    cmd = [
        'curl', '-s', '-X', 'POST', 'http://192.168.1.142:8001/api/reports/dashboard/detail',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({
            "report_type": "mesin",
            "date_from": today,
            "date_to": today,
            "shift_from": 1,
            "shift_to": 3,
            "filters": {},
            "pagination": {"page": 1, "page_size": 5}
        })
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            response = json.loads(result.stdout)
            print(f"Machine report response: {len(response.get('rows', []))} rows, total: {response.get('total', 0)}")

            if response.get('rows'):
                print("\n=== First Machine Row Analysis ===")
                first_row = response['rows'][0]

                # Check time fields
                time_fields = ['plan', 'rt', 'tp', 'ts', 'total_dt']
                print("Time fields:")
                for field in time_fields:
                    value = first_row.get(field, 'MISSING')
                    print(f"  {field}: {value}")

                # Check KPI fields
                kpi_fields = ['per', 'otr', 'qr', 'oee']
                print("\nKPI fields:")
                for field in kpi_fields:
                    value = first_row.get(field, 'MISSING')
                    print(f"  {field}: {value}")

                # Check other key fields
                print(f"\nOther fields:")
                print(f"  mc_no: {first_row.get('mc_no', 'MISSING')}")
                print(f"  output: {first_row.get('output', 'MISSING')}")
                print(f"  reject: {first_row.get('reject', 'MISSING')}")
                print(f"  target_qty: {first_row.get('target_qty', 'MISSING')}")
                print(f"  catatan: {first_row.get('catatan', '')[:100]}...")

                # Validation checks
                print(f"\n=== Validation Results ===")

                # Check if time fields are not all zero
                non_zero_times = [f for f in time_fields if first_row.get(f, '00:00') != '00:00']
                if non_zero_times:
                    print(f"✅ PASS: Non-zero time fields: {non_zero_times}")
                else:
                    print(f"❌ FAIL: All time fields are 00:00")

                # Check if KPIs are not all 0%
                non_zero_kpis = [f for f in kpi_fields if first_row.get(f, '0%') != '0%']
                if non_zero_kpis:
                    print(f"✅ PASS: Non-zero KPI fields: {non_zero_kpis}")
                else:
                    print(f"❌ FAIL: All KPI fields are 0%")

                # Check if catatan is summarized
                catatan = first_row.get('catatan', '')
                if ' -> ' not in catatan and 'stop' not in catatan.lower():
                    print(f"✅ PASS: Catatan appears to be summarized business context")
                else:
                    print(f"❌ FAIL: Catatan contains raw transition text: {catatan[:50]}...")

            else:
                print("No machine rows returned")

        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response: {e}")
            print(f"Raw response: {result.stdout}")
    else:
        print(f"API call failed: {result.stderr}")

    # Test operator report
    print(f"\nTesting operator report for {today}...")
    cmd[9] = json.dumps({
        "report_type": "operator",
        "date_from": today,
        "date_to": today,
        "shift_from": 1,
        "shift_to": 3,
        "filters": {},
        "pagination": {"page": 1, "page_size": 5}
    })

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            response = json.loads(result.stdout)
            print(f"Operator report response: {len(response.get('rows', []))} rows, total: {response.get('total', 0)}")
        except json.JSONDecodeError:
            print(f"Failed to parse operator response")

    print("\n=== Test Complete ===")

if __name__ == "__main__":
    populate_and_test()