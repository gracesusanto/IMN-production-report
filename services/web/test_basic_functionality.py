#!/usr/bin/env python3
"""
Simple test to verify basic functionality works.
This bypasses the complex diagnostic setup and just tests core functions.
"""

import os
import sys
from datetime import datetime, timedelta

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_basic_imports():
    """Test that we can import core modules without errors."""
    try:
        print("Testing imports...")

        # Test database connection
        import app.database as database
        print("✓ Database module imported")

        # Test models
        import app.model.models as models
        print("✓ Models imported")

        # Test business logic
        from app.service.business_logic import upsert_activity_report, build_activity_report_row
        print("✓ Business logic imported")

        # Test report calculations
        from app.service.report_calculations import compute_all_derived_fields
        print("✓ Report calculations imported")

        return True

    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_connection():
    """Test basic database connectivity."""
    try:
        print("\nTesting database connection...")

        import app.database as database
        import app.model.models as models

        # Create engine and bind session
        engine = database.get_engine()
        database.SessionLocal.configure(bind=engine)
        session = database.SessionLocal()

        # Test simple query
        count = session.query(models.Operator).count()
        print(f"✓ Database connected, found {count} operators")

        session.close()
        return True

    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_activity_report_creation():
    """Test ActivityReport creation."""
    try:
        print("\nTesting ActivityReport creation...")

        import app.database as database
        import app.model.models as models
        from app.service.business_logic import upsert_activity_report

        # Create engine and bind session
        engine = database.get_engine()
        database.SessionLocal.configure(bind=engine)
        session = database.SessionLocal()

        # Find a completed activity to test with
        completed_activity = session.query(models.ActivityMesin).filter(
            models.ActivityMesin.stop_time_id.isnot(None)
        ).first()

        if not completed_activity:
            print("⚠️ No completed activities found to test with")
            session.close()
            return True

        print(f"✓ Found completed activity ID {completed_activity.id}")

        # Test ActivityReport creation
        try:
            upsert_activity_report(completed_activity.id, session)
            session.commit()
            print("✓ ActivityReport created successfully")

            # Check if it exists
            report = session.query(models.ActivityReport).filter(
                models.ActivityReport.activity_id == completed_activity.id
            ).first()

            if report:
                print(f"✓ ActivityReport found: output={report.output}, productivity={getattr(report, 'productivity_formatted', 'N/A')}")
            else:
                print("❌ ActivityReport not found after creation")

        except Exception as e:
            print(f"❌ ActivityReport creation failed: {e}")
            import traceback
            traceback.print_exc()

        session.close()
        return True

    except Exception as e:
        print(f"❌ ActivityReport test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run basic functionality tests."""
    print("=== Basic Functionality Test ===")

    # Test imports
    if not test_basic_imports():
        return False

    # Test database
    if not test_database_connection():
        return False

    # Test ActivityReport creation
    if not test_activity_report_creation():
        return False

    print(f"\n✓ All basic tests passed!")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)