#!/usr/bin/env python3
"""
Create test data with correct category codes for KPI calculation testing
"""
import sys
import os
from datetime import datetime

# Add the correct path to import from services
sys.path.append('/Users/grace.susanto/src/imn/production app/IMN-production-report/services/web')

from app.cmd.mock_data import mock_data, get_seeded_ids
from app.database import get_engine
from app.service import business_logic
from app import schema
from sqlalchemy.orm import sessionmaker

def create_fixed_activity_data(session):
    """Create activity data with correct category codes"""
    mesin_ids, tooling_ids, operator_ids = get_seeded_ids(session)

    mc1, mc2, mc3 = mesin_ids[0], mesin_ids[1], mesin_ids[2]
    tl1, tl2, tl3 = tooling_ids[0], tooling_ids[1], tooling_ids[2]
    opA, opB, opC = operator_ids[0], operator_ids[1], operator_ids[2]

    def do(a: schema.Activity):
        # Normalize like /activity endpoint
        if a.curr_category in ["null", "", None]:
            a.curr_category = None
        if a.mesin_id in ["null", "", None]:
            a.mesin_id = None
        if a.tooling_id in ["null", "", None]:
            a.tooling_id = None

        business_logic.process_activity(a, session)

    print("Creating fixed activity data with correct categories...")

    # Operator A: Normal production with runtime and tooling problem
    do(schema.Activity(
        operator_id=opA, mesin_id=mc1, tooling_id=tl1,
        curr_category=None,
        next_category="RT : Runtime",  # ✅ Fixed: RT instead of U
        output=0, reject=0, rework=0,
        keterangan="A start runtime TL1"
    ))

    do(schema.Activity(
        operator_id=opA, mesin_id=mc1, tooling_id=tl1,
        curr_category="RT : Runtime",
        next_category="TP : Tooling Problem",
        output=85, reject=3, rework=2,
        coil_no="A-C01", lot_no="A-L01", pack_no="A-P01",
        keterangan="A normal production -> tooling issue"
    ))

    do(schema.Activity(
        operator_id=opA, mesin_id=mc1, tooling_id=tl1,
        curr_category="TP : Tooling Problem",
        next_category="RT : Runtime",
        output=0, reject=0, rework=0,
        keterangan="A fixed tooling -> resume runtime"
    ))

    do(schema.Activity(
        operator_id=opA, mesin_id=mc1, tooling_id=tl1,
        curr_category="RT : Runtime",
        next_category="BT : Breaktime",
        output=45, reject=1, rework=0,
        keterangan="A more production -> break"
    ))

    # Operator B: Runtime with tooling setting
    do(schema.Activity(
        operator_id=opB, mesin_id=mc2, tooling_id=tl2,
        curr_category=None,
        next_category="RT : Runtime",
        output=0, reject=0, rework=0,
        keterangan="B start runtime"
    ))

    do(schema.Activity(
        operator_id=opB, mesin_id=mc2, tooling_id=tl2,
        curr_category="RT : Runtime",
        next_category="TS : Tooling Setting",
        output=120, reject=5, rework=3,
        keterangan="B production -> tooling setup"
    ))

    do(schema.Activity(
        operator_id=opB, mesin_id=mc2, tooling_id=tl2,
        curr_category="TS : Tooling Setting",
        next_category="RT : Runtime",
        output=0, reject=0, rework=0,
        keterangan="B setup complete -> resume"
    ))

    # Operator C: Runtime with multiple downtime types
    do(schema.Activity(
        operator_id=opC, mesin_id=mc3, tooling_id=tl3,
        curr_category=None,
        next_category="RT : Runtime",
        output=0, reject=0, rework=0,
        keterangan="C start runtime"
    ))

    do(schema.Activity(
        operator_id=opC, mesin_id=mc3, tooling_id=tl3,
        curr_category="RT : Runtime",
        next_category="BR : Briefing",
        output=60, reject=2, rework=1,
        keterangan="C production -> briefing"
    ))

    do(schema.Activity(
        operator_id=opC, mesin_id="", tooling_id="",
        curr_category="BR : Briefing",
        next_category="NP : No Plan",
        output=0, reject=0, rework=0,
        keterangan="C briefing -> no plan"
    ))

    do(schema.Activity(
        operator_id=opC, mesin_id="", tooling_id="",
        curr_category="NP : No Plan",
        next_category="RT : Runtime",
        output=0, reject=0, rework=0,
        keterangan="C plan available -> runtime"
    ))

    print("Fixed activity data created successfully")

def populate_and_test():
    """Populate database with corrected mock data and test the API"""
    print("=== Creating Test Data with Correct Category Codes ===")

    # Create database session
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # First ensure master data exists
        print("Ensuring master data exists...")
        try:
            mock_data(session)
        except Exception as e:
            print(f"Master data already exists or error: {e}")

        # Clear existing activity data
        print("Clearing existing activity data...")
        session.execute("DELETE FROM activity_mesin")
        session.commit()

        # Create new activity data with correct categories
        create_fixed_activity_data(session)
        session.commit()
        print("All data committed to database")

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
        raise
    finally:
        session.close()

    print("\n=== Testing Report Table API with Fixed Data ===")

    # Test the API
    today = datetime.now().strftime('%Y-%m-%d')

    import subprocess
    import json

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
            "pagination": {"page": 1, "page_size": 3}
        })
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            response = json.loads(result.stdout)
            print(f"✅ API Response: {len(response.get('rows', []))} rows, total: {response.get('total', 0)}")

            if response.get('rows'):
                first_row = response['rows'][0]

                print(f"\n=== Fixed Data Results ===")
                print(f"Machine: {first_row.get('mc_no', 'MISSING')}")
                print(f"Output/Reject: {first_row.get('output', 0)}/{first_row.get('reject', 0)}")

                # Time fields should now be non-zero
                time_fields = ['plan', 'rt', 'tp', 'ts', 'total_dt']
                print("Time fields:")
                for field in time_fields:
                    value = first_row.get(field, '00:00')
                    print(f"  {field}: {value}")

                # KPI fields should now be calculated
                kpi_fields = ['per', 'otr', 'qr', 'oee', 'target_qty']
                print("KPI fields:")
                for field in kpi_fields:
                    value = first_row.get(field, 'MISSING')
                    print(f"  {field}: {value}")

                # Check catatan
                catatan = first_row.get('catatan', '')
                print(f"Catatan: {catatan[:80]}...")

                # Final validation
                print(f"\n=== Validation Results ===")

                non_zero_times = [f for f in ['plan', 'rt'] if first_row.get(f, '00:00') != '00:00']
                if non_zero_times:
                    print(f"✅ PASS: Time fields calculated: {non_zero_times}")
                else:
                    print(f"❌ FAIL: Time fields still zero")

                non_zero_kpis = [f for f in ['per', 'otr', 'oee'] if first_row.get(f, '0%') != '0%']
                if non_zero_kpis:
                    print(f"✅ PASS: KPI fields calculated: {non_zero_kpis}")
                else:
                    print(f"❌ FAIL: KPI fields still zero")

                if ' -> ' not in catatan and 'stop' not in catatan.lower():
                    print(f"✅ PASS: Catatan properly summarized")
                else:
                    print(f"❌ FAIL: Catatan still contains transitions")

            else:
                print("❌ No data returned")
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
    else:
        print(f"❌ API call failed: {result.stderr}")

if __name__ == "__main__":
    populate_and_test()