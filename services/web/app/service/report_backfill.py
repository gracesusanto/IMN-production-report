"""
Automatic backfill functionality for ActivityReport table during report generation.

This module ensures that every completed activity (stop_time_id IS NOT NULL)
has a corresponding entry in the ActivityReport table before generating reports.
"""

import logging
from typing import List, Tuple
from sqlalchemy import text

import app.database as database
import app.model.models as models
from app.service.business_logic import upsert_activity_report_sync


logger = logging.getLogger(__name__)


def get_missing_activity_reports(session, time_from, time_to) -> List[int]:
    """
    Get list of activity IDs that are missing from ActivityReport table.

    Args:
        session: SQLAlchemy session
        time_from: Start timestamp for filtering
        time_to: End timestamp for filtering

    Returns:
        List of ActivityMesin.id values that need ActivityReport entries
    """
    # Query for completed activities in time range that don't have ActivityReport entries
    query = text("""
        SELECT am.id
        FROM activity_mesin am
        JOIN mesin_log ml_start ON am.start_time_id = ml_start.id
        WHERE am.stop_time_id IS NOT NULL
        AND ml_start.timestamp >= :time_from
        AND ml_start.timestamp < :time_to
        AND NOT EXISTS (
            SELECT 1 FROM activity_report ar
            WHERE ar.activity_id = am.id
        )
        ORDER BY am.id
    """)

    result = session.execute(query, {
        'time_from': time_from,
        'time_to': time_to
    })

    return [row[0] for row in result.fetchall()]


def ensure_activity_reports_exist(time_from, time_to, max_backfill=1000) -> Tuple[int, int]:
    """
    Ensure that all completed activities in the given time range have ActivityReport entries.

    This function is called automatically before generating reports to guarantee
    that the ActivityReport table is complete for the requested time range.

    Args:
        time_from: Start timestamp for filtering
        time_to: End timestamp for filtering
        max_backfill: Maximum number of activities to backfill in one call

    Returns:
        Tuple of (total_missing, backfilled) counts
    """
    # Properly configure session with engine binding
    engine = database.get_engine()
    database.SessionLocal.configure(bind=engine)
    session = database.SessionLocal()

    try:
        # Find missing ActivityReport entries
        missing_ids = get_missing_activity_reports(session, time_from, time_to)

        if not missing_ids:
            logger.debug("No missing ActivityReport entries found")
            return (0, 0)

        total_missing = len(missing_ids)

        if total_missing > max_backfill:
            logger.warning(f"Found {total_missing} missing ActivityReport entries, "
                          f"but limiting backfill to {max_backfill} for performance")
            missing_ids = missing_ids[:max_backfill]

        logger.info(f"Backfilling {len(missing_ids)} missing ActivityReport entries")

        backfilled = 0
        failed = 0

        for activity_id in missing_ids:
            try:
                upsert_activity_report_sync(activity_id, session)
                backfilled += 1

                # Commit in small batches for better memory usage
                if backfilled % 50 == 0:
                    session.commit()
                    logger.debug(f"Backfilled {backfilled} ActivityReport entries...")

            except Exception as e:
                failed += 1
                logger.error(f"Failed to backfill activity_id={activity_id}: {e}")
                # Continue with other activities

        # Final commit
        session.commit()

        logger.info(f"Backfill complete: {backfilled} succeeded, {failed} failed")
        return (total_missing, backfilled)

    except Exception as e:
        logger.error(f"Error during ActivityReport backfill: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def get_activity_report_coverage(time_from, time_to) -> Tuple[int, int, float]:
    """
    Get ActivityReport coverage statistics for a time range.

    Args:
        time_from: Start timestamp for filtering
        time_to: End timestamp for filtering

    Returns:
        Tuple of (total_activities, covered_activities, coverage_percentage)
    """
    session = database.SessionLocal()

    try:
        # Count total completed activities in time range
        total_query = text("""
            SELECT COUNT(*)
            FROM activity_mesin am
            JOIN mesin_log ml_start ON am.start_time_id = ml_start.id
            WHERE am.stop_time_id IS NOT NULL
            AND ml_start.timestamp >= :time_from
            AND ml_start.timestamp < :time_to
        """)

        total_result = session.execute(total_query, {
            'time_from': time_from,
            'time_to': time_to
        })
        total_activities = total_result.scalar() or 0

        # Count activities with ActivityReport entries
        covered_query = text("""
            SELECT COUNT(*)
            FROM activity_mesin am
            JOIN mesin_log ml_start ON am.start_time_id = ml_start.id
            JOIN activity_report ar ON ar.activity_id = am.id
            WHERE am.stop_time_id IS NOT NULL
            AND ml_start.timestamp >= :time_from
            AND ml_start.timestamp < :time_to
        """)

        covered_result = session.execute(covered_query, {
            'time_from': time_from,
            'time_to': time_to
        })
        covered_activities = covered_result.scalar() or 0

        # Calculate coverage percentage
        coverage_percentage = (covered_activities / total_activities * 100.0) if total_activities > 0 else 100.0

        return (total_activities, covered_activities, coverage_percentage)

    finally:
        session.close()


def validate_activity_report_integrity(time_from, time_to) -> List[str]:
    """
    Validate ActivityReport table integrity for a time range.

    Checks for:
    1. Missing ActivityReport entries for completed activities
    2. Orphaned ActivityReport entries (activity doesn't exist)
    3. Data consistency issues

    Args:
        time_from: Start timestamp for filtering
        time_to: End timestamp for filtering

    Returns:
        List of integrity issues found (empty if all good)
    """
    session = database.SessionLocal()
    issues = []

    try:
        # Check for missing ActivityReport entries
        missing_ids = get_missing_activity_reports(session, time_from, time_to)
        if missing_ids:
            issues.append(f"Missing ActivityReport entries for {len(missing_ids)} completed activities")

        # Check for orphaned ActivityReport entries
        orphan_query = text("""
            SELECT COUNT(*)
            FROM activity_report ar
            LEFT JOIN activity_mesin am ON ar.activity_id = am.id
            WHERE ar.start_ts_utc >= :time_from
            AND ar.start_ts_utc < :time_to
            AND am.id IS NULL
        """)

        orphan_result = session.execute(orphan_query, {
            'time_from': time_from,
            'time_to': time_to
        })
        orphan_count = orphan_result.scalar() or 0

        if orphan_count > 0:
            issues.append(f"Found {orphan_count} orphaned ActivityReport entries")

        # Check for incomplete activities with ActivityReport entries
        incomplete_query = text("""
            SELECT COUNT(*)
            FROM activity_report ar
            JOIN activity_mesin am ON ar.activity_id = am.id
            WHERE ar.start_ts_utc >= :time_from
            AND ar.start_ts_utc < :time_to
            AND am.stop_time_id IS NULL
        """)

        incomplete_result = session.execute(incomplete_query, {
            'time_from': time_from,
            'time_to': time_to
        })
        incomplete_count = incomplete_result.scalar() or 0

        if incomplete_count > 0:
            issues.append(f"Found {incomplete_count} ActivityReport entries for incomplete activities")

        return issues

    finally:
        session.close()