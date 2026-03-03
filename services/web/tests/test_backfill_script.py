"""
Tests for backfill_activity_report.py script.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime

import app.model.models as models
from app.cmd.backfill_activity_report import (
    get_completed_activities_keyset,
    get_total_completed_activities,
    get_existing_activity_report_count,
    backfill_activity_reports
)


class TestBackfillQueries:
    """Test backfill query functions."""

    def test_get_completed_activities_keyset_basic(self, test_session, sample_activity_mesin):
        """Test basic keyset pagination query."""
        # Create additional test data
        activity2 = models.ActivityMesin(
            id=sample_activity_mesin.id + 1,
            operator_id=sample_activity_mesin.operator_id,
            category="IDLE",
            start_time_id=sample_activity_mesin.start_time_id,
            stop_time_id=sample_activity_mesin.stop_time_id
        )
        test_session.add(activity2)
        test_session.commit()

        # Test with last_id = 0 (get all)
        results = get_completed_activities_keyset(test_session, last_id=0, limit=10)

        assert len(results) == 2
        # Results should be ordered by ID
        assert results[0][0] == sample_activity_mesin.id
        assert results[1][0] == activity2.id

    def test_get_completed_activities_keyset_pagination(self, test_session, sample_activity_mesin):
        """Test keyset pagination with last_id."""
        # Create additional test data
        activity2 = models.ActivityMesin(
            id=sample_activity_mesin.id + 1,
            operator_id=sample_activity_mesin.operator_id,
            category="IDLE",
            start_time_id=sample_activity_mesin.start_time_id,
            stop_time_id=sample_activity_mesin.stop_time_id
        )
        test_session.add(activity2)
        test_session.commit()

        # Test with last_id = first activity ID
        results = get_completed_activities_keyset(
            test_session,
            last_id=sample_activity_mesin.id,
            limit=10
        )

        # Should only return the second activity
        assert len(results) == 1
        assert results[0][0] == activity2.id

    def test_get_completed_activities_keyset_limit(self, test_session):
        """Test that keyset query respects limit."""
        # Create multiple activities
        activities = []
        for i in range(5):
            activity = models.ActivityMesin(
                operator_id="OP-Test",
                category="TEST",
                start_time_id=1,
                stop_time_id=2
            )
            test_session.add(activity)
            activities.append(activity)
        test_session.commit()

        # Test with limit = 3
        results = get_completed_activities_keyset(test_session, last_id=0, limit=3)

        assert len(results) == 3

    def test_get_completed_activities_keyset_excludes_incomplete(self, test_session, sample_operator):
        """Test that query excludes incomplete activities (stop_time_id is NULL)."""
        # Create incomplete activity
        incomplete_activity = models.ActivityMesin(
            operator_id=sample_operator.id,
            category="RUNNING",
            start_time_id=1,
            stop_time_id=None  # Incomplete
        )
        test_session.add(incomplete_activity)
        test_session.commit()

        results = get_completed_activities_keyset(test_session, last_id=0, limit=10)

        # Should not include incomplete activity
        assert len(results) == 0

    def test_get_total_completed_activities(self, test_session, sample_activity_mesin):
        """Test total count query."""
        # Add another completed activity
        activity2 = models.ActivityMesin(
            operator_id=sample_activity_mesin.operator_id,
            category="IDLE",
            start_time_id=1,
            stop_time_id=2
        )
        test_session.add(activity2)
        test_session.commit()

        total = get_total_completed_activities(test_session)
        assert total == 2

    def test_get_existing_activity_report_count(self, test_session):
        """Test existing report count query."""
        # Initially no reports
        count = get_existing_activity_report_count(test_session)
        assert count == 0

        # Add a report
        report = models.ActivityReport(
            activity_id=1,
            start_time_id=1,
            stop_time_id=2,
            category="TEST",
            operator_id="OP-Test",
            operator_name="Test Op",
            operator_nik="123",
            start_ts_utc=datetime.utcnow(),
            stop_ts_utc=datetime.utcnow()
        )
        test_session.add(report)
        test_session.commit()

        count = get_existing_activity_report_count(test_session)
        assert count == 1


class TestBackfillProcess:
    """Test the main backfill process."""

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    @patch('app.cmd.backfill_activity_report.upsert_activity_report_sync')
    def test_backfill_activity_reports_success(self, mock_upsert, mock_session_class):
        """Test successful backfill process."""
        # Setup mocks
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock query results
        mock_session.query.return_value.filter.return_value.count.return_value = 5  # total activities
        mock_session.query.return_value.count.return_value = 0  # existing reports

        # Mock keyset pagination - first call returns data, second returns empty
        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = [
            [(1,), (2,), (3,)],  # First chunk
            [(4,), (5,)],        # Second chunk
            []                   # No more data
        ]

        # Run backfill
        result = backfill_activity_reports(chunk_size=3, dry_run=False)

        # Verify success
        assert result is True

        # Verify upsert was called for each activity
        expected_calls = [call(1, mock_session), call(2, mock_session), call(3, mock_session),
                         call(4, mock_session), call(5, mock_session)]
        mock_upsert.assert_has_calls(expected_calls)

        # Verify commits
        assert mock_session.commit.call_count == 2  # One per chunk

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    @patch('app.cmd.backfill_activity_report.upsert_activity_report_sync')
    def test_backfill_activity_reports_dry_run(self, mock_upsert, mock_session_class):
        """Test dry run mode."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_session.query.return_value.filter.return_value.count.return_value = 2
        mock_session.query.return_value.count.return_value = 0

        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = [
            [(1,), (2,)],
            []
        ]

        # Run dry run
        result = backfill_activity_reports(chunk_size=10, dry_run=True)

        assert result is True

        # Should not call upsert in dry run
        mock_upsert.assert_not_called()
        # Should rollback instead of commit
        mock_session.rollback.assert_called()
        mock_session.commit.assert_not_called()

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    @patch('app.cmd.backfill_activity_report.upsert_activity_report_sync')
    def test_backfill_activity_reports_partial_failure(self, mock_upsert, mock_session_class):
        """Test handling of partial failures during backfill."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_session.query.return_value.filter.return_value.count.return_value = 3
        mock_session.query.return_value.count.return_value = 0

        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = [
            [(1,), (2,), (3,)],
            []
        ]

        # Make upsert fail for one activity
        mock_upsert.side_effect = [
            None,  # Success
            Exception("Database error"),  # Failure
            None   # Success
        ]

        # Run backfill
        result = backfill_activity_reports(chunk_size=10, dry_run=False)

        # Should fail overall when there are any failures (strict success criteria)
        assert result is False

        # Should still commit the chunk
        mock_session.commit.assert_called()

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    def test_backfill_activity_reports_no_data(self, mock_session_class):
        """Test backfill with no completed activities."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_session.query.return_value.filter.return_value.count.return_value = 0

        result = backfill_activity_reports(chunk_size=10, dry_run=False)

        assert result is True

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    @patch('app.cmd.backfill_activity_report.upsert_activity_report_sync')
    def test_backfill_activity_reports_commit_failure(self, mock_upsert, mock_session_class):
        """Test handling of commit failures."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_session.query.return_value.filter.return_value.count.return_value = 2
        mock_session.query.return_value.count.return_value = 0

        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = [
            [(1,), (2,)],
            []
        ]

        # Make commit fail
        mock_session.commit.side_effect = Exception("Commit failed")

        result = backfill_activity_reports(chunk_size=10, dry_run=False)

        # Should fail when commit fails (data not persisted)
        assert result is False

        # Should call rollback on commit failure
        mock_session.rollback.assert_called()

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    def test_backfill_activity_reports_fatal_error(self, mock_session_class):
        """Test handling of fatal errors."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Make the total count query fail
        mock_session.query.return_value.filter.return_value.count.side_effect = Exception("Fatal database error")

        result = backfill_activity_reports(chunk_size=10, dry_run=False)

        # Should fail
        assert result is False

        # Should call rollback
        mock_session.rollback.assert_called()

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    @patch('app.cmd.backfill_activity_report.upsert_activity_report_sync')
    def test_backfill_activity_reports_chunking(self, mock_upsert, mock_session_class):
        """Test that backfill processes data in correct chunks."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_session.query.return_value.filter.return_value.count.return_value = 7
        mock_session.query.return_value.count.return_value = 0

        # Mock keyset pagination with chunk size 3
        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = [
            [(1,), (2,), (3,)],  # First chunk
            [(4,), (5,), (6,)],  # Second chunk
            [(7,)],              # Third chunk
            []                   # No more data
        ]

        result = backfill_activity_reports(chunk_size=3, dry_run=False)

        assert result is True

        # Should process all 7 activities
        assert mock_upsert.call_count == 7

        # Should commit 3 times (once per chunk)
        assert mock_session.commit.call_count == 3

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    @patch('app.cmd.backfill_activity_report.upsert_activity_report_sync')
    def test_backfill_activity_reports_keyset_progression(self, mock_upsert, mock_session_class):
        """Test that keyset pagination progresses correctly."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_session.query.return_value.filter.return_value.count.return_value = 4
        mock_session.query.return_value.count.return_value = 0

        # Track the filter calls to verify last_id progression
        filter_calls = []
        original_filter = mock_session.query.return_value.filter

        def track_filter(*args, **kwargs):
            # Capture the filter condition (this is a simplified mock)
            filter_calls.append(args)
            result = MagicMock()
            result.order_by.return_value.limit.return_value.all.side_effect = [
                [(10,), (20,)],  # First call: last_id=0
                [(30,), (40,)],  # Second call: last_id=20
                []               # Third call: last_id=40
            ][len(filter_calls) - 1:len(filter_calls)]
            return result

        mock_session.query.return_value.filter.return_value.filter.side_effect = track_filter

        result = backfill_activity_reports(chunk_size=2, dry_run=False)

        assert result is True

        # Should have made 3 keyset queries (2 with data, 1 empty)
        assert len(filter_calls) == 3


class TestBackfillEdgeCases:
    """Test edge cases in backfill process."""

    @patch('app.cmd.backfill_activity_report.database.SessionLocal')
    def test_backfill_with_existing_reports(self, mock_session_class):
        """Test backfill when some reports already exist (idempotency)."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # 5 total activities, 2 already have reports
        mock_session.query.return_value.filter.return_value.count.return_value = 5
        mock_session.query.return_value.count.return_value = 2

        mock_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = [
            [(1,), (2,), (3,), (4,), (5,)],
            []
        ]

        result = backfill_activity_reports(chunk_size=10, dry_run=False)

        # Should still succeed (idempotent upserts handle duplicates)
        assert result is True

    def test_backfill_empty_chunk_size(self):
        """Test backfill with invalid chunk size."""
        # Should handle gracefully or use a default
        result = backfill_activity_reports(chunk_size=0, dry_run=True)

        # Implementation should either use a default chunk size or handle gracefully
        # Exact behavior depends on implementation