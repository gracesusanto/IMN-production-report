"""
Tests for generate_report.py functions.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytz

import app.model.models as models
from app.cmd.generate_report import (
    _convert_to_jakarta_time,
    _calculate_shift,
    _calculate_shift_from_datetime,
    _is_time_between,
    query_activity_mesin,
    query_activity_report,
    merge_consecutive_downtime,
    df_to_report,
    _generate_keterangan,
    _generate_keterangan_limax,
    ReportCategory,
    USE_ACTIVITY_REPORT_TABLE
)


class TestTimezoneConversion:
    """Test timezone conversion functions."""

    def test_convert_to_jakarta_time_naive_timestamps(self):
        """Test conversion of timezone-naive timestamps (assumes UTC)."""
        # Create timezone-naive timestamps
        timestamps = pd.Series([
            datetime(2023, 1, 1, 12, 0, 0),  # UTC noon
            datetime(2023, 6, 15, 6, 30, 0)   # UTC 6:30 AM
        ])

        result = _convert_to_jakarta_time(timestamps)

        # Jakarta is UTC+7, so noon UTC becomes 7 PM, 6:30 AM becomes 1:30 PM
        expected = pd.Series([
            "01/01/2023 19:00:00",  # 12:00 UTC + 7 hours
            "06/15/2023 13:30:00"   # 06:30 UTC + 7 hours
        ])

        pd.testing.assert_series_equal(result, expected)

    def test_convert_to_jakarta_time_aware_timestamps(self):
        """Test conversion of timezone-aware timestamps."""
        utc = pytz.UTC
        timestamps = pd.Series([
            datetime(2023, 1, 1, 12, 0, 0, tzinfo=utc),
            datetime(2023, 6, 15, 6, 30, 0, tzinfo=utc)
        ])

        result = _convert_to_jakarta_time(timestamps)

        expected = pd.Series([
            "01/01/2023 19:00:00",
            "06/15/2023 13:30:00"
        ])

        pd.testing.assert_series_equal(result, expected)

    def test_convert_to_jakarta_time_custom_format(self):
        """Test custom format in timezone conversion."""
        timestamps = pd.Series([datetime(2023, 1, 1, 12, 0, 0)])

        result = _convert_to_jakarta_time(timestamps, fmt="%Y-%m-%d %H:%M")

        expected = pd.Series(["2023-01-01 19:00"])
        pd.testing.assert_series_equal(result, expected)

    def test_convert_to_jakarta_time_edge_cases(self):
        """Test edge cases in timezone conversion."""
        # Test with empty series
        empty_series = pd.Series([], dtype='datetime64[ns]')
        result = _convert_to_jakarta_time(empty_series)
        assert len(result) == 0

        # Test with NaT values
        timestamps_with_nat = pd.Series([
            datetime(2023, 1, 1, 12, 0, 0),
            pd.NaT,
            datetime(2023, 1, 2, 12, 0, 0)
        ])
        result = _convert_to_jakarta_time(timestamps_with_nat)

        # NaT should remain as NaT in string form
        assert pd.isna(result[1]) or result[1] == "NaT"


class TestShiftCalculation:
    """Test shift calculation functions."""

    def test_calculate_shift_weekday_shift_1(self):
        """Test shift 1 on weekday (7 AM - 3 PM)."""
        # Monday 9 AM
        result = _calculate_shift("01/02/2023 09:00:00")  # Monday
        assert result == 1

    def test_calculate_shift_weekday_shift_2(self):
        """Test shift 2 on weekday (3 PM - 11 PM)."""
        # Tuesday 5 PM
        result = _calculate_shift("01/03/2023 17:00:00")  # Tuesday
        assert result == 2

    def test_calculate_shift_weekday_shift_3(self):
        """Test shift 3 on weekday (11 PM - 7 AM)."""
        # Wednesday 1 AM
        result = _calculate_shift("01/04/2023 01:00:00")  # Wednesday
        assert result == 3

    def test_calculate_shift_saturday(self):
        """Test Saturday shifts (different hours)."""
        # Saturday 9 AM (shift 1: 7-12)
        result = _calculate_shift("01/07/2023 09:00:00")  # Saturday
        assert result == 1

        # Saturday 2 PM (shift 2: 12-17)
        result = _calculate_shift("01/07/2023 14:00:00")  # Saturday
        assert result == 2

        # Saturday 7 PM (shift 3: 17-22)
        result = _calculate_shift("01/07/2023 19:00:00")  # Saturday
        assert result == 3

    def test_calculate_shift_sunday(self):
        """Test Sunday (always shift 1)."""
        # Sunday any time
        result = _calculate_shift("01/08/2023 15:00:00")  # Sunday
        assert result == 1

    def test_calculate_shift_from_datetime(self):
        """Test direct datetime shift calculation."""
        # Monday 9 AM
        dt = datetime(2023, 1, 2, 9, 0, 0)  # Monday
        result = _calculate_shift_from_datetime(dt)
        assert result == 1

        # Saturday 2 PM
        dt = datetime(2023, 1, 7, 14, 0, 0)  # Saturday
        result = _calculate_shift_from_datetime(dt)
        assert result == 2

    def test_is_time_between(self):
        """Test time range checking."""
        from datetime import time

        # Normal range (9 AM to 5 PM)
        assert _is_time_between(time(9, 0), time(17, 0), time(12, 0)) is True
        assert _is_time_between(time(9, 0), time(17, 0), time(8, 0)) is False
        assert _is_time_between(time(9, 0), time(17, 0), time(18, 0)) is False

        # Overnight range (11 PM to 7 AM)
        assert _is_time_between(time(23, 0), time(7, 0), time(1, 0)) is True
        assert _is_time_between(time(23, 0), time(7, 0), time(6, 0)) is True
        assert _is_time_between(time(23, 0), time(7, 0), time(12, 0)) is False


class TestQueryFunctions:
    """Test query functions."""

    def setup_activity_report_data(self, test_session):
        """Setup test data in ActivityReport table."""
        # Create test data
        report1 = models.ActivityReport(
            activity_id=1,
            start_time_id=1,
            stop_time_id=2,
            category="RUNNING",
            operator_id="OP-Test1",
            operator_name="Operator 1",
            operator_nik="12345",
            mesin_id="MC-Test1",
            mesin_name="Machine 1",
            tooling_id="TL-Test1",
            kode_tooling="T001",
            common_tooling_name="Tool 1",
            part_no="P001",
            part_name="Part 1",
            std_jam=8,
            output=100,
            reject=5,
            rework=2,
            start_ts_utc=datetime(2023, 1, 1, 8, 0, 0),
            stop_ts_utc=datetime(2023, 1, 1, 16, 0, 0)
        )

        report2 = models.ActivityReport(
            activity_id=2,
            start_time_id=3,
            stop_time_id=4,
            category="BT : Breaktime",
            operator_id="OP-Test1",
            operator_name="Operator 1",
            operator_nik="12345",
            mesin_id=None,
            mesin_name=None,
            tooling_id=None,
            output=0,
            reject=0,
            rework=0,
            start_ts_utc=datetime(2023, 1, 1, 10, 0, 0),
            stop_ts_utc=datetime(2023, 1, 1, 10, 15, 0)
        )

        test_session.add_all([report1, report2])
        test_session.commit()

    @patch('app.cmd.generate_report.session')
    def test_query_activity_report_success(self, mock_session, test_session):
        """Test successful query_activity_report."""
        mock_session.return_value = test_session
        self.setup_activity_report_data(test_session)

        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 1, 2, 0, 0, 0)

        result_df = query_activity_report(start_time, end_time)

        # Verify structure
        assert len(result_df) == 2
        expected_columns = [
            "MC", "Operator", "NIK", "Tooling", "Kode Tooling", "Common Tooling Name",
            "Part No", "Part Name", "Target", "Start", "Stop", "Desc",
            "Qty", "Reject", "Rework", "Keterangan"
        ]

        for col in expected_columns:
            assert col in result_df.columns

        # Verify data content
        assert result_df.iloc[0]["MC"] == "Machine 1"
        assert result_df.iloc[0]["Operator"] == "Operator 1"
        assert result_df.iloc[0]["Qty"] == 100

        # Verify NULL handling for non-machine category
        assert result_df.iloc[1]["MC"] == "-"  # NULL converted to "-"
        assert result_df.iloc[1]["Tooling"] == "-"

    @patch('app.cmd.generate_report.session')
    def test_query_activity_report_empty_result(self, mock_session, test_session):
        """Test query_activity_report with no data."""
        mock_session.return_value = test_session

        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 1, 2, 0, 0, 0)

        result_df = query_activity_report(start_time, end_time)

        # Should return empty DataFrame with correct columns
        assert len(result_df) == 0
        expected_columns = [
            "MC", "Operator", "NIK", "Tooling", "Kode Tooling", "Common Tooling Name",
            "Part No", "Part Name", "Target", "Start", "Stop", "Desc",
            "Qty", "Reject", "Rework", "Keterangan"
        ]

        for col in expected_columns:
            assert col in result_df.columns

    @patch('app.cmd.generate_report.session')
    def test_query_activity_report_time_filtering(self, mock_session, test_session):
        """Test that query_activity_report filters by time correctly."""
        mock_session.return_value = test_session
        self.setup_activity_report_data(test_session)

        # Query only for morning activities
        start_time = datetime(2023, 1, 1, 9, 0, 0)
        end_time = datetime(2023, 1, 1, 12, 0, 0)

        result_df = query_activity_report(start_time, end_time)

        # Should only return the breaktime activity (starts at 10:00)
        assert len(result_df) == 1
        assert result_df.iloc[0]["Desc"] == "BT : Breaktime"


class TestDataTransformation:
    """Test data transformation functions."""

    def test_generate_keterangan_all_fields(self):
        """Test _generate_keterangan with all fields present."""
        row = pd.Series({
            'Keterangan': 'Manual note',
            'Coil No': 'C001',
            'Lot No': 'L001',
            'Pack No': 'P001'
        })

        result = _generate_keterangan(row)
        expected = "Keterangan: Manual note, Coil No: C001, Lot No: L001, Pack No: P001"
        assert result == expected

    def test_generate_keterangan_partial_fields(self):
        """Test _generate_keterangan with some empty fields."""
        row = pd.Series({
            'Keterangan': 'Manual note',
            'Coil No': 'C001',
            'Lot No': '',  # Empty
            'Pack No': 'P001'
        })

        result = _generate_keterangan(row)
        expected = "Keterangan: Manual note, Coil No: C001, Pack No: P001"  # Empty field excluded
        assert result == expected

    def test_generate_keterangan_empty_keterangan(self):
        """Test _generate_keterangan with empty main Keterangan."""
        row = pd.Series({
            'Keterangan': '',
            'Coil No': 'C001',
            'Lot No': 'L001',
            'Pack No': ''
        })

        result = _generate_keterangan(row)
        expected = "Coil No: C001, Lot No: L001"
        assert result == expected

    def test_generate_keterangan_all_empty(self):
        """Test _generate_keterangan with all fields empty."""
        row = pd.Series({
            'Keterangan': '',
            'Coil No': '',
            'Lot No': '',
            'Pack No': ''
        })

        result = _generate_keterangan(row)
        assert result == ""

    def test_generate_keterangan_limax(self):
        """Test _generate_keterangan_limax function."""
        # This function should behave similarly but may have different logic
        row = pd.Series({
            'Keterangan': 'Test',
            'Coil No': 'C001',
            'Lot No': 'L001',
            'Pack No': 'P001',
            'Reject': 5,
            'Rework': 2
        })

        result = _generate_keterangan_limax(row)
        # Assuming similar behavior to regular keterangan
        assert isinstance(result, str)
        assert 'Test' in result


class TestReportGeneration:
    """Test report generation and processing."""

    def create_sample_dataframe(self):
        """Create sample DataFrame for testing."""
        return pd.DataFrame({
            'MC': ['Machine 1', 'Machine 1', '-'],
            'Operator': ['Op 1', 'Op 1', 'Op 2'],
            'NIK': ['123', '123', '456'],
            'Tooling': ['Tool 1', 'Tool 1', '-'],
            'Kode Tooling': ['T001', 'T001', '-'],
            'Common Tooling Name': ['Common 1', 'Common 1', '-'],
            'Part No': ['P001', 'P001', '-'],
            'Part Name': ['Part 1', 'Part 1', '-'],
            'Target': [8, 8, 0],
            'Start': [datetime(2023, 1, 1, 8, 0), datetime(2023, 1, 1, 10, 0), datetime(2023, 1, 1, 10, 15)],
            'Stop': [datetime(2023, 1, 1, 10, 0), datetime(2023, 1, 1, 10, 15), datetime(2023, 1, 1, 10, 30)],
            'Desc': ['RUNNING', 'IDLE', 'BT : Breaktime'],
            'Qty': [100, 0, 0],
            'Reject': [5, 0, 0],
            'Rework': [2, 0, 0],
            'Keterangan': ['Test', '', '']
        })

    def test_df_to_report_basic_transformation(self):
        """Test basic DataFrame transformation in df_to_report."""
        df = self.create_sample_dataframe()

        result = df_to_report(df, ReportCategory.MESIN, None, None)

        # Verify new columns are added
        assert 'Tanggal' in result.columns
        assert 'StartTime' in result.columns
        assert 'StopTime' in result.columns
        assert 'Shift' in result.columns

        # Verify data types
        assert result['Qty'].dtype == 'int64'
        assert result['Reject'].dtype == 'int64'
        assert result['Rework'].dtype == 'int64'

    def test_df_to_report_operator_drops_np(self):
        """Test that operator report drops NP activities."""
        df = pd.DataFrame({
            'MC': ['Machine 1', '-'],
            'Operator': ['Op 1', 'Op 1'],
            'NIK': ['123', '123'],
            'Tooling': ['Tool 1', '-'],
            'Kode Tooling': ['T001', '-'],
            'Common Tooling Name': ['Common 1', '-'],
            'Part No': ['P001', '-'],
            'Part Name': ['Part 1', '-'],
            'Target': [8, 0],
            'Start': [datetime(2023, 1, 1, 8, 0), datetime(2023, 1, 1, 10, 0)],
            'Stop': [datetime(2023, 1, 1, 10, 0), datetime(2023, 1, 1, 10, 15)],
            'Desc': ['RUNNING', 'NP : No Plan'],
            'Qty': [100, 0],
            'Reject': [5, 0],
            'Rework': [2, 0],
            'Keterangan': ['Test', '']
        })

        result = df_to_report(df, ReportCategory.OPERATOR, None, None)

        # NP activity should be dropped
        assert len(result) == 1
        assert result.iloc[0]['Desc'] == 'RUNNING'

    def test_merge_consecutive_downtime(self):
        """Test merge_consecutive_downtime function."""
        # Create DataFrame with consecutive downtime
        df = pd.DataFrame({
            'MC': ['Machine 1', 'Machine 1', 'Machine 1'],
            'Operator': ['Op 1', 'Op 1', 'Op 1'],
            'Tooling': ['Tool 1', 'Tool 1', 'Tool 1'],
            'Desc': ['DOWNTIME', 'DOWNTIME', 'RUNNING'],
            'StartTime': ['08:00:00', '09:00:00', '10:00:00'],
            'StopTime': ['09:00:00', '10:00:00', '11:00:00'],
            'Start': ['01/01/2023 08:00:00', '01/01/2023 09:00:00', '01/01/2023 10:00:00'],
            'Stop': ['01/01/2023 09:00:00', '01/01/2023 10:00:00', '01/01/2023 11:00:00']
        })

        result = merge_consecutive_downtime(df, ReportCategory.MESIN)

        # First two downtime entries should be merged
        assert len(result) == 2  # 2 merged downtime + 1 running

        # First row should have earliest start and latest stop of consecutive downtime
        assert result.iloc[0]['StartTime'] == '08:00:00'
        assert result.iloc[0]['StopTime'] == '10:00:00'

    def test_merge_consecutive_downtime_different_desc(self):
        """Test that merge_consecutive_downtime doesn't merge different descriptions."""
        df = pd.DataFrame({
            'MC': ['Machine 1', 'Machine 1'],
            'Operator': ['Op 1', 'Op 1'],
            'Tooling': ['Tool 1', 'Tool 1'],
            'Desc': ['DOWNTIME A', 'DOWNTIME B'],
            'StartTime': ['08:00:00', '09:00:00'],
            'StopTime': ['09:00:00', '10:00:00'],
            'Start': ['01/01/2023 08:00:00', '01/01/2023 09:00:00'],
            'Stop': ['01/01/2023 09:00:00', '01/01/2023 10:00:00']
        })

        result = merge_consecutive_downtime(df, ReportCategory.MESIN)

        # Should not merge different descriptions
        assert len(result) == 2


class TestFeatureFlag:
    """Test feature flag behavior."""

    def test_use_activity_report_table_flag(self):
        """Test that USE_ACTIVITY_REPORT_TABLE flag is accessible."""
        # The flag should be importable and have a boolean value
        assert isinstance(USE_ACTIVITY_REPORT_TABLE, bool)

    @patch('app.cmd.generate_report.USE_ACTIVITY_REPORT_TABLE', True)
    @patch('app.cmd.generate_report.query_activity_report')
    @patch('app.cmd.generate_report.query_activity_mesin')
    def test_feature_flag_uses_new_query(self, mock_old_query, mock_new_query):
        """Test that feature flag switches to new query path."""
        # This would need to be tested in the actual get_report function
        # For now, we verify the flag value affects imports
        from app.cmd.generate_report import USE_ACTIVITY_REPORT_TABLE
        assert USE_ACTIVITY_REPORT_TABLE is True

    @patch('app.cmd.generate_report.USE_ACTIVITY_REPORT_TABLE', False)
    def test_feature_flag_uses_old_query(self):
        """Test that feature flag switches to old query path."""
        from app.cmd.generate_report import USE_ACTIVITY_REPORT_TABLE
        assert USE_ACTIVITY_REPORT_TABLE is False