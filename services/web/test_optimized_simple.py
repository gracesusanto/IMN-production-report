#!/usr/bin/env python3
"""
Simple test to verify the optimized pipeline works end-to-end.
Run this directly to test the complete flow without pytest overhead.
"""

import os
import sys
from datetime import datetime, timedelta

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app.database as database
import app.model.models as models
import app.schema as schema
from app.service.business_logic import process_activity
from app.cmd.generate_report_optimized import get_report_optimized, ReportCategory
from app.service.report_backfill import get_activity_report_coverage


def create_test_data():
    """Create test data for the pipeline."""
    session = database.SessionLocal()

    try:
        # Create operator
        operator = models.Operator(
            id="OP-TestOp",
            name="Test Operator",
            nik="TEST123"
        )
        session.add(operator)

        # Create machine
        machine = models.Mesin(
            id="MC-TestMC",
            name="A1-TEST",
            tonase=100
        )
        session.add(machine)

        # Create tooling
        tooling = models.Tooling(
            id="TL-TestTL",
            customer="Test Customer",
            part_no="PART123",
            part_name="Test Part",
            child_part_name="Child Part",
            kode_tooling="TL123",
            common_tooling_name="Test Tooling",
            proses="Stamping",
            std_jam=100
        )
        session.add(tooling)

        session.commit()
        return operator, machine, tooling, session

    except Exception as e:
        session.rollback()
        raise


def test_complete_pipeline():
    """Test the complete optimized pipeline."""
    print("=== Testing Optimized Pipeline ===")

    # Sync mode is now default, no need to set env var

    try:
        operator, machine, tooling, session = create_test_data()
        print(f"✓ Created test data: {operator.name}, {machine.name}, {tooling.common_tooling_name}")

        # Step 1: Start NP activity
        print("\n1. Starting NP activity...")
        np_activity = schema.ActivityCreate(
            operator_id=operator.id,
            curr_category=None,
            next_category="NP : No Plan"
        )
        process_activity(np_activity, session)
        print("✓ NP activity started")

        # Step 2: Start utility activity
        print("\n2. Starting utility activity...")
        utility_activity = schema.ActivityCreate(
            operator_id=operator.id,
            mesin_id=machine.id,
            tooling_id=tooling.id,
            curr_category="NP : No Plan",
            next_category="U : Utility",
            output=0, reject=0, rework=0
        )
        process_activity(utility_activity, session)
        print("✓ Utility activity started (NP stopped)")

        # Step 3: Stop utility with production data
        print("\n3. Stopping utility with production data...")
        stop_utility = schema.ActivityCreate(
            operator_id=operator.id,
            mesin_id=machine.id,
            tooling_id=tooling.id,
            curr_category="U : Utility",
            next_category="BT : Breaktime",
            output=150, reject=5, rework=2,
            coil_no="COIL123",
            lot_no="LOT456",
            pack_no="PACK789",
            keterangan="Test production"
        )
        process_activity(stop_utility, session)
        print("✓ Utility activity stopped with production data")

        # Step 4: Check ActivityReport coverage
        print("\n4. Checking ActivityReport coverage...")
        time_from = datetime.utcnow() - timedelta(hours=1)
        time_to = datetime.utcnow() + timedelta(hours=1)

        total, covered, coverage = get_activity_report_coverage(time_from, time_to)
        print(f"   Total activities: {total}")
        print(f"   Covered activities: {covered}")
        print(f"   Coverage: {coverage:.1f}%")

        # Step 5: Generate optimized report
        print("\n5. Generating optimized report...")
        df, filename = get_report_optimized(
            report_category=ReportCategory.MESIN,
            format=schema.FormatType.IMN,
            date_time_from=time_from.date(),
            date_time_to=time_to.date()
        )

        print(f"   Report generated: {filename}")
        print(f"   Rows: {len(df)}")

        if not df.empty:
            print("   Sample data:")
            for col in ["MC", "Operator", "Qty", "Duration", "Productivity"]:
                if col in df.columns:
                    print(f"     {col}: {df[col].iloc[0] if len(df) > 0 else 'N/A'}")

        # Step 6: Verify pre-computed fields exist
        print("\n6. Verifying ActivityReport entries...")
        activity_reports = session.query(models.ActivityReport).all()
        print(f"   ActivityReport entries: {len(activity_reports)}")

        if activity_reports:
            sample_report = activity_reports[0]
            print("   Sample pre-computed fields:")
            print(f"     Jakarta date: {sample_report.start_date_jakarta}")
            print(f"     Duration: {sample_report.duration_formatted}")
            print(f"     Productivity: {sample_report.productivity_formatted}")
            print(f"     Plant: {sample_report.plant}")

        print(f"\n✓ Pipeline test completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Pipeline test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Clean up
        try:
            session.rollback()
            session.close()
        except:
            pass


def main():
    """Run the pipeline test."""
    success = test_complete_pipeline()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()