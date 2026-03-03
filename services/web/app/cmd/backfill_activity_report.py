#!/usr/bin/env python3
"""
Backfill script for activity_report table.

This script processes all existing completed ActivityMesin records
(where stop_time_id is NOT NULL) and creates corresponding activity_report entries
with all pre-computed fields including:

- Jakarta timezone conversions (dates, times, datetimes, shifts)
- Derived metrics (duration, productivity, reject/rework ratios)
- Display formatting (formatted percentages, duration strings)
- LIMAX format fields (plant, time codes, category codes)

The script is idempotent and can be safely re-run if it fails partway through.
Existing records will be updated with latest computed values.

Usage:
    python backfill_activity_report.py [--chunk-size 100] [--dry-run]
"""

import argparse
import sys
import traceback
from datetime import datetime

import app.database as database
import app.model.models as models
from app.service.business_logic import upsert_activity_report_sync


def get_completed_activities_keyset(session, last_id=0, limit=1000):
    """Get completed activities in chunks using keyset pagination (faster than OFFSET)."""
    return (
        session.query(models.ActivityMesin.id)
        .filter(models.ActivityMesin.stop_time_id.isnot(None))
        .filter(models.ActivityMesin.id > last_id)
        .order_by(models.ActivityMesin.id.asc())
        .limit(limit)
        .all()
    )


def get_total_completed_activities(session):
    """Get total count of completed activities."""
    return (
        session.query(models.ActivityMesin)
        .filter(models.ActivityMesin.stop_time_id.isnot(None))
        .count()
    )


def get_existing_activity_report_count(session):
    """Get count of existing activity_report records."""
    return session.query(models.ActivityReport).count()


def backfill_activity_reports(chunk_size=100, dry_run=False):
    """
    Backfill activity_report table with data from existing completed activities.

    Args:
        chunk_size (int): Number of records to process per batch
        dry_run (bool): If True, don't actually insert data
    """
    session = database.SessionLocal()

    try:
        # Get statistics
        total_activities = get_total_completed_activities(session)
        existing_reports = get_existing_activity_report_count(session)

        print(f"=== Activity Report Backfill ===")
        print(f"Total completed activities: {total_activities}")
        print(f"Existing activity reports: {existing_reports}")
        print(f"Chunk size: {chunk_size}")
        print(f"Dry run: {dry_run}")
        print()

        if total_activities == 0:
            print("No completed activities found. Nothing to backfill.")
            return True

        processed = 0
        succeeded = 0
        failed = 0
        last_id = 0

        print(f"Starting backfill at {datetime.now()}")

        while True:
            # Get next chunk of activities using keyset pagination
            activities = get_completed_activities_keyset(session, last_id, chunk_size)

            if not activities:
                break  # No more activities

            # Update last_id for next iteration
            current_batch_ids = [activity[0] for activity in activities]
            last_id = max(current_batch_ids)

            print(f"Processing chunk: IDs {min(current_batch_ids)} to {last_id} ({len(activities)} activities)")

            chunk_succeeded = 0
            chunk_failed = 0

            for activity in activities:
                activity_id = activity[0]
                processed += 1

                try:
                    if not dry_run:
                        upsert_activity_report_sync(activity_id, session)
                    chunk_succeeded += 1
                    succeeded += 1

                    if processed % 50 == 0:
                        print(f"  Processed {processed} activities...")

                except Exception as e:
                    chunk_failed += 1
                    failed += 1
                    print(f"  ERROR: Failed to process activity {activity_id}: {e}")
                    # Continue processing other activities

            if not dry_run:
                try:
                    session.commit()
                    print(f"  Chunk committed: {chunk_succeeded} succeeded, {chunk_failed} failed")
                except Exception as e:
                    session.rollback()
                    print(f"  ERROR: Failed to commit chunk: {e}")
                    failed += chunk_succeeded  # All succeeded items are now failed
                    succeeded -= chunk_succeeded
            else:
                session.rollback()  # Don't commit in dry run
                print(f"  Dry run chunk: {chunk_succeeded} would succeed, {chunk_failed} would fail")

        print()
        print(f"=== Backfill Complete ===")
        print(f"Processed: {processed} activities")
        print(f"Succeeded: {succeeded}")
        print(f"Failed: {failed}")
        print(f"Success rate: {(succeeded/processed*100):.1f}%" if processed > 0 else "N/A")

        if not dry_run:
            final_reports = get_existing_activity_report_count(session)
            print(f"Final activity report count: {final_reports}")

        return failed == 0

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        print(traceback.format_exc())
        session.rollback()
        return False
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill activity_report table")
    parser.add_argument("--chunk-size", type=int, default=100,
                        help="Number of records to process per batch (default: 100)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without actually doing it")

    args = parser.parse_args()

    success = backfill_activity_reports(
        chunk_size=args.chunk_size,
        dry_run=args.dry_run
    )

    if success:
        print("Backfill completed successfully!")
        sys.exit(0)
    else:
        print("Backfill failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()