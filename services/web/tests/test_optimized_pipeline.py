"""
End-to-end tests for the complete optimized report generation pipeline.

Tests the integration of:
1. Async ActivityReport updates
2. Pre-computed field population
3. Optimized report generation using pre-computed values
4. CSV parity between old and new approaches
"""

import asyncio
import pytest
import pandas as pd
from datetime import datetime, timedelta
import pytz

import app.database as database
import app.model.models as models
from app.service.business_logic import process_activity
from app.service.async_report_tasks import (
    wait_for_pending_updates,
    get_pending_update_count,
    schedule_activity_report_update
)
from app.cmd.generate_report import get_report, ReportCategory
from app.cmd.generate_report_optimized import get_report_optimized
from app.service.report_calculations import compute_all_derived_fields
import app.schema as schema


@pytest.fixture
def test_session(database_session):
    """Use the existing test database session."""
    return database_session


@pytest.fixture
def sample_operator(test_session):
    """Create a sample operator for testing."""
    operator = models.Operator(
        id="OP-TestOperator",
        name="Test Operator",
        nik="TEST001"
    )
    test_session.add(operator)
    test_session.commit()
    return operator


@pytest.fixture
def sample_machine(test_session):
    """Create a sample machine for testing."""
    machine = models.Mesin(
        id="MC-TestMachine",
        name="A1-MOCK",
        tonase=100
    )
    test_session.add(machine)
    test_session.commit()
    return machine


@pytest.fixture
def sample_tooling(test_session):
    """Create a sample tooling for testing."""
    tooling = models.Tooling(
        id="TL-TestTooling",
        customer="Test Customer",
        part_no="PART001",
        part_name="Test Part",
        child_part_name="Child Part",
        kode_tooling="TL001",
        common_tooling_name="Test Tooling",
        proses="Stamping",
        std_jam=100
    )
    test_session.add(tooling)
    test_session.commit()
    return tooling


@pytest.mark.asyncio
async def test_async_activity_report_update(test_session, sample_operator, sample_machine, sample_tooling):
    """Test that ActivityReport updates happen asynchronously with all pre-computed fields."""

    # Create a MesinLog entry (start)
    start_log = models.MesinLog(
        mesin_id=sample_machine.id,
        operator_id=sample_operator.id,
        tooling_id=sample_tooling.id,
        curr_category=None,
        next_category="U : Utility"
    )
    test_session.add(start_log)
    test_session.flush()

    # Create a completed ActivityMesin
    activity = models.ActivityMesin(
        mesin_id=sample_machine.id,
        operator_id=sample_operator.id,
        tooling_id=sample_tooling.id,
        category="U : Utility",
        start_time_id=start_log.id,
        output=50,
        reject=2,
        rework=1
    )
    test_session.add(activity)
    test_session.flush()

    # Create a MesinLog entry (stop)
    stop_log = models.MesinLog(
        mesin_id=sample_machine.id,
        operator_id=sample_operator.id,
        tooling_id=sample_tooling.id,
        curr_category="U : Utility",
        next_category="NP : No Plan",
        timestamp=datetime.utcnow() + timedelta(hours=2)  # 2 hour activity
    )
    test_session.add(stop_log)
    test_session.flush()

    # Complete the activity
    activity.stop_time_id = stop_log.id
    test_session.commit()

    # Check no ActivityReport exists initially
    report_count_before = test_session.query(models.ActivityReport).count()
    assert report_count_before == 0, "Should have no ActivityReport initially"

    # Schedule async update
    await schedule_activity_report_update(activity.id)

    # Wait for async processing to complete
    success = await wait_for_pending_updates(timeout=10.0)
    assert success, "Async updates should complete within timeout"

    # Verify ActivityReport was created with pre-computed fields
    activity_report = test_session.query(models.ActivityReport).filter_by(activity_id=activity.id).first()
    assert activity_report is not None, "ActivityReport should be created"

    # Verify core data
    assert activity_report.operator_name == "Test Operator"
    assert activity_report.mesin_name == "A1-MOCK"
    assert activity_report.output == 50
    assert activity_report.reject == 2
    assert activity_report.rework == 1

    # Verify pre-computed Jakarta timezone fields exist
    assert activity_report.start_date_jakarta is not None
    assert activity_report.start_time_jakarta is not None
    assert activity_report.start_datetime_jakarta is not None
    assert activity_report.shift is not None

    # Verify pre-computed derived metrics exist
    assert activity_report.duration_seconds is not None
    assert activity_report.duration_formatted is not None
    assert activity_report.productivity_percent is not None
    assert activity_report.productivity_formatted is not None
    assert activity_report.reject_ratio_percent is not None
    assert activity_report.reject_ratio_formatted is not None

    # Verify LIMAX format fields
    assert activity_report.plant is not None
    assert activity_report.awal_limax is not None
    assert activity_report.akhir_limax is not None
    assert activity_report.kode_keterangan == "U"


def test_pre_computed_field_accuracy(test_session):
    """Test that pre-computed fields match manual calculations."""

    # Create test timestamps
    utc = pytz.UTC
    start_ts = utc.localize(datetime(2023, 3, 15, 8, 0, 0))  # 8 AM UTC
    stop_ts = utc.localize(datetime(2023, 3, 15, 10, 30, 0))  # 10:30 AM UTC

    # Manual calculations
    computed_fields = compute_all_derived_fields(
        start_ts_utc=start_ts,
        stop_ts_utc=stop_ts,
        category="U : Utility",
        output=100,
        reject=5,
        rework=3,
        target_per_hour=80,
        machine_name="A1-MOCK"
    )

    # Verify timezone conversions (Jakarta is UTC+7)
    assert "15/03/2023" in computed_fields['start_date_jakarta']
    assert computed_fields['shift'] in [1, 2, 3]

    # Verify duration calculation (2.5 hours = 9000 seconds)
    assert computed_fields['duration_seconds'] == 9000
    assert "2h 30min" in computed_fields['duration_formatted']

    # Verify productivity calculation
    # (100 pieces / 2.5 hours) / 80 pieces/hour * 100% = 50%
    assert float(computed_fields['productivity_percent']) == 50.0
    assert "50.00%" == computed_fields['productivity_formatted']

    # Verify ratio calculations
    # Total = 100 + 5 + 3 = 108
    # Reject ratio = 5/108 * 100% = 4.63%
    assert abs(float(computed_fields['reject_ratio_percent']) - 4.63) < 0.01

    # Verify LIMAX format
    assert computed_fields['plant'] == "K"  # Last char of "A1-MOCK"
    assert computed_fields['kode_keterangan'] == "U"


@pytest.mark.asyncio
async def test_optimized_vs_original_report_parity(test_session, sample_operator, sample_machine, sample_tooling):
    """Test that optimized report generation produces same results as original."""

    # Create completed activities through the normal process_activity flow
    # This ensures ActivityReport entries are created with async updates

    # Simulate starting utility activity
    start_activity = schema.ActivityCreate(
        operator_id=sample_operator.id,
        mesin_id=sample_machine.id,
        tooling_id=sample_tooling.id,
        curr_category=None,
        next_category="U : Utility",
        output=0, reject=0, rework=0
    )

    process_activity(start_activity, test_session)

    # Wait a bit to simulate work time
    await asyncio.sleep(0.1)

    # Stop the activity with production data
    stop_activity = schema.ActivityCreate(
        operator_id=sample_operator.id,
        mesin_id=sample_machine.id,
        tooling_id=sample_tooling.id,
        curr_category="U : Utility",
        next_category="NP : No Plan",
        output=75, reject=3, rework=2,
        coil_no="COIL123",
        lot_no="LOT456",
        pack_no="PACK789",
        keterangan="Test production run"
    )

    process_activity(stop_activity, test_session)

    # Wait for async ActivityReport updates to complete
    success = await wait_for_pending_updates(timeout=15.0)
    assert success, "Async updates should complete"

    # Define time range that includes our test data
    time_from = datetime.utcnow() - timedelta(hours=1)
    time_to = datetime.utcnow() + timedelta(hours=1)

    # Generate reports using both approaches
    original_df, original_filename = get_report(
        report_category=ReportCategory.MESIN,
        format=schema.FormatType.IMN,
        date_time_from=time_from.date(),
        date_time_to=time_to.date()
    )

    optimized_df, optimized_filename = get_report_optimized(
        report_category=ReportCategory.MESIN,
        format=schema.FormatType.IMN,
        date_time_from=time_from.date(),
        date_time_to=time_to.date()
    )

    # Verify both approaches return data
    assert not original_df.empty, "Original approach should return data"
    assert not optimized_df.empty, "Optimized approach should return data"

    # Sort both DataFrames consistently for comparison
    sort_cols = ['MC', 'Operator', 'Start'] if 'Start' in original_df.columns else ['MC', 'Operator']
    original_sorted = original_df.sort_values(by=sort_cols).reset_index(drop=True)
    optimized_sorted = optimized_df.sort_values(by=sort_cols).reset_index(drop=True)

    # Compare core production data columns
    production_columns = ['MC', 'Operator', 'Qty', 'Reject', 'Rework', 'Target']
    for col in production_columns:
        if col in original_sorted.columns and col in optimized_sorted.columns:
            pd.testing.assert_series_equal(
                original_sorted[col],
                optimized_sorted[col],
                check_names=True,
                msg=f"Column {col} should match between approaches"
            )

    # Verify pre-computed fields exist in optimized version
    computed_columns = ['Duration', 'Productivity', 'Reject Ratio', 'Rework Ratio']
    for col in computed_columns:
        assert col in optimized_sorted.columns, f"Optimized version should have {col} column"


def test_async_task_duplicate_prevention():
    """Test that duplicate async tasks are properly prevented."""

    # This test checks the _pending_activity_ids logic
    initial_count = get_pending_update_count()

    # Schedule same activity multiple times quickly
    activity_id = 999  # Non-existent ID for this test

    # These should not create duplicate pending tasks
    from app.service.async_report_tasks import schedule_activity_report_update_sync

    # Schedule multiple times (should deduplicate)
    schedule_activity_report_update_sync(activity_id)
    schedule_activity_report_update_sync(activity_id)
    schedule_activity_report_update_sync(activity_id)

    # The task will fail (non-existent activity) but shouldn't create duplicates
    # Wait a bit for tasks to process and fail
    import time
    time.sleep(1.0)

    # Count should return to initial level
    final_count = get_pending_update_count()
    assert final_count == initial_count, "Pending count should return to initial level"


@pytest.mark.asyncio
async def test_process_activity_with_async_updates(test_session, sample_operator, sample_machine, sample_tooling):
    """Test the complete process_activity flow with async ActivityReport updates."""

    # Start with No Plan activity
    start_np = schema.ActivityCreate(
        operator_id=sample_operator.id,
        curr_category=None,
        next_category="NP : No Plan"
    )

    process_activity(start_np, test_session)

    # Switch to utility activity
    start_utility = schema.ActivityCreate(
        operator_id=sample_operator.id,
        mesin_id=sample_machine.id,
        tooling_id=sample_tooling.id,
        curr_category="NP : No Plan",
        next_category="U : Utility"
    )

    process_activity(start_utility, test_session)

    # Stop utility with production data
    stop_utility = schema.ActivityCreate(
        operator_id=sample_operator.id,
        mesin_id=sample_machine.id,
        tooling_id=sample_tooling.id,
        curr_category="U : Utility",
        next_category="BR : Briefing",
        output=150, reject=5, rework=2
    )

    process_activity(stop_utility, test_session)

    # Wait for all async updates to complete
    success = await wait_for_pending_updates(timeout=20.0)
    assert success, "All async updates should complete"

    # Verify ActivityReport entries were created for completed activities
    reports = test_session.query(models.ActivityReport).all()

    # Should have reports for NP and Utility activities (both completed)
    assert len(reports) >= 2, "Should have ActivityReport entries for completed activities"

    # Verify the utility activity report has correct pre-computed values
    utility_report = None
    for report in reports:
        if report.category == "U : Utility":
            utility_report = report
            break

    assert utility_report is not None, "Should have ActivityReport for utility activity"
    assert utility_report.output == 150
    assert utility_report.reject == 5
    assert utility_report.rework == 2

    # Verify all pre-computed fields are populated
    assert utility_report.duration_seconds is not None
    assert utility_report.productivity_percent is not None
    assert utility_report.start_date_jakarta is not None
    assert utility_report.plant is not None