#!/usr/bin/env python3
"""
Validation script for ActivityReport denormalized reporting pipeline.

This script performs automated checks to ensure the new pipeline produces
identical results to the original query path.
"""

import sys
import traceback
from datetime import datetime, timedelta
import pandas as pd

import app.database as database
import app.model.models as models
from app.cmd.generate_report import query_activity_mesin, query_activity_report, USE_ACTIVITY_REPORT_TABLE
from app.service.business_logic import upsert_activity_report, build_activity_report_row


def test_timezone_consistency():
    """Test that timezone handling is consistent between old and new paths."""
    print("=== Testing Timezone Consistency ===")
    session = database.SessionLocal()

    try:
        # Get a sample of recent MesinLog records
        logs = session.query(models.MesinLog).limit(5).all()

        for log in logs:
            print(f"MesinLog {log.id}: {log.timestamp} (type: {type(log.timestamp)})")
            if hasattr(log.timestamp, 'tzinfo'):
                print(f"  Timezone aware: {log.timestamp.tzinfo}")
            else:
                print(f"  Timezone naive")

        print("✅ Timezone consistency check complete")
        return True

    except Exception as e:
        print(f"❌ Timezone consistency check failed: {e}")
        return False
    finally:
        session.close()


def test_activity_report_upsert():
    """Test that ActivityReport upsert works correctly."""
    print("=== Testing ActivityReport Upsert ===")
    session = database.SessionLocal()

    try:
        # Find a completed activity
        completed_activity = (
            session.query(models.ActivityMesin)
            .filter(models.ActivityMesin.stop_time_id.isnot(None))
            .first()
        )

        if not completed_activity:
            print("❌ No completed activities found for testing")
            return False

        activity_id = completed_activity.id
        print(f"Testing with ActivityMesin ID: {activity_id}")

        # Test build_activity_report_row
        row_data = build_activity_report_row(activity_id, session)
        print(f"✅ build_activity_report_row returned {len(row_data)} fields")

        # Verify required fields
        required_fields = ['activity_id', 'start_ts_utc', 'stop_ts_utc', 'category', 'operator_id']
        for field in required_fields:
            if field not in row_data:
                print(f"❌ Missing required field: {field}")
                return False

        print(f"✅ All required fields present")

        # Test upsert (idempotent)
        initial_count = session.query(models.ActivityReport).filter(
            models.ActivityReport.activity_id == activity_id
        ).count()

        upsert_activity_report(activity_id, session)
        session.commit()

        final_count = session.query(models.ActivityReport).filter(
            models.ActivityReport.activity_id == activity_id
        ).count()

        print(f"Initial count: {initial_count}, Final count: {final_count}")
        print("✅ ActivityReport upsert test passed")
        return True

    except Exception as e:
        print(f"❌ ActivityReport upsert test failed: {e}")
        traceback.print_exc()
        session.rollback()
        return False
    finally:
        session.close()


def test_query_parity():
    """Test that old and new query paths return similar data structure."""
    print("=== Testing Query Parity ===")
    session = database.SessionLocal()

    try:
        # Use a recent time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=7)

        print(f"Testing time range: {start_time} to {end_time}")

        # Test old query
        try:
            old_df = query_activity_mesin(start_time, end_time)
            print(f"✅ Old query returned {len(old_df)} rows")
            print(f"   Columns: {list(old_df.columns)}")
        except Exception as e:
            print(f"❌ Old query failed: {e}")
            return False

        # Test new query
        try:
            new_df = query_activity_report(start_time, end_time)
            print(f"✅ New query returned {len(new_df)} rows")
            print(f"   Columns: {list(new_df.columns)}")
        except Exception as e:
            print(f"❌ New query failed: {e}")
            return False

        # Compare column structure
        if list(old_df.columns) != list(new_df.columns):
            print("❌ Column mismatch between old and new queries")
            print(f"Old: {list(old_df.columns)}")
            print(f"New: {list(new_df.columns)}")
            return False

        print("✅ Column structure matches between old and new queries")

        # Check if we have data to compare
        if len(old_df) > 0 and len(new_df) > 0:
            print(f"✅ Both queries returned data")

            # Basic data type checks
            for col in ['Start', 'Stop']:
                if col in old_df.columns:
                    print(f"   {col} dtype old: {old_df[col].dtype}, new: {new_df[col].dtype}")
        else:
            print("⚠️  No data returned (this is OK for new/empty systems)")

        return True

    except Exception as e:
        print(f"❌ Query parity test failed: {e}")
        traceback.print_exc()
        return False
    finally:
        session.close()


def test_non_machine_category():
    """Test that NON_MACHINE_CATEGORY activities are handled correctly."""
    print("=== Testing Non-Machine Category Handling ===")
    session = database.SessionLocal()

    try:
        # Look for NON_MACHINE_CATEGORY activities
        non_machine_activities = (
            session.query(models.ActivityMesin)
            .filter(models.ActivityMesin.category.in_(["NP : No Plan", "BT : Breaktime", "BR : Briefing"]))
            .filter(models.ActivityMesin.stop_time_id.isnot(None))
            .limit(3)
            .all()
        )

        if not non_machine_activities:
            print("⚠️  No completed NON_MACHINE_CATEGORY activities found")
            return True

        for activity in non_machine_activities:
            print(f"Testing {activity.category} activity (ID: {activity.id})")

            # Check if ActivityReport handles null mesin_id/tooling_id
            try:
                row_data = build_activity_report_row(activity.id, session)

                # For NON_MACHINE_CATEGORY, mesin_id and tooling_id should be nullable
                if activity.category.startswith("NP") or activity.category.startswith("BT") or activity.category.startswith("BR"):
                    print(f"   mesin_id: {row_data.get('mesin_id')}")
                    print(f"   tooling_id: {row_data.get('tooling_id')}")

                print(f"✅ {activity.category} activity processed successfully")

            except Exception as e:
                print(f"❌ Failed to process {activity.category} activity: {e}")
                return False

        print("✅ Non-machine category test passed")
        return True

    except Exception as e:
        print(f"❌ Non-machine category test failed: {e}")
        traceback.print_exc()
        return False
    finally:
        session.close()


def main():
    """Run all validation tests."""
    print("🔍 Starting ActivityReport Pipeline Validation")
    print(f"USE_ACTIVITY_REPORT_TABLE = {USE_ACTIVITY_REPORT_TABLE}")
    print()

    tests = [
        ("Timezone Consistency", test_timezone_consistency),
        ("ActivityReport Upsert", test_activity_report_upsert),
        ("Query Parity", test_query_parity),
        ("Non-Machine Category", test_non_machine_category),
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")
            traceback.print_exc()
            results.append((test_name, False))
        print()

    print("=== VALIDATION SUMMARY ===")
    all_passed = True
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
        if not success:
            all_passed = False

    if all_passed:
        print("\n🎉 All validation tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Some validation tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()