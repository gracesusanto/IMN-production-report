"""
Tests to validate CSV output parity between old and new approaches.

These tests ensure that switching the USE_ACTIVITY_REPORT_TABLE feature flag
produces identical CSV outputs for both IMN and LIMAX formats.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch

import app.cmd.generate_report as generate_report
from app.cmd.generate_report import ReportCategory, get_report
import app.schema as schema
from app.service.business_logic import upsert_activity_report_sync


class TestCSVParity:
    """Test CSV output parity between old and new query approaches."""

    def generate_reports_with_flag(self, use_new_table: bool, test_session, start_time: datetime, end_time: datetime, report_category: ReportCategory):
        """Generate reports with specified feature flag setting."""
        # Temporarily set the feature flag
        original_flag = generate_report.USE_ACTIVITY_REPORT_TABLE
        generate_report.USE_ACTIVITY_REPORT_TABLE = use_new_table

        try:
            # Mock the session for both old and new approaches
            with patch('app.cmd.generate_report.session', return_value=test_session):
                # Generate IMN format report
                imn_df, imn_filename = get_report(
                    report_category=report_category,
                    format=schema.FormatType.IMN,
                    date_time_from=start_time,
                    date_time_to=end_time
                )

                # Generate LIMAX format report
                limax_df, limax_filename = get_report(
                    report_category=report_category,
                    format=schema.FormatType.LIMAX,
                    date_time_from=start_time,
                    date_time_to=end_time
                )

                return imn_df, limax_df, imn_filename

        finally:
            # Restore original flag
            generate_report.USE_ACTIVITY_REPORT_TABLE = original_flag

    def compare_dataframes_strict(self, df1: pd.DataFrame, df2: pd.DataFrame, comparison_name: str):
        """
        Strictly compare two DataFrames for identical content.

        Args:
            df1: DataFrame from old approach
            df2: DataFrame from new approach
            comparison_name: Name for error reporting

        Raises:
            AssertionError: If DataFrames are not identical
        """
        # Check if both are empty
        if df1.empty and df2.empty:
            return  # Both empty is fine

        # Check shape
        assert df1.shape == df2.shape, f"{comparison_name}: Different shapes - Old {df1.shape} vs New {df2.shape}"

        # Check columns
        assert list(df1.columns) == list(df2.columns), f"{comparison_name}: Different columns"

        # Compare data content by sorting both DataFrames
        df1_sorted = df1.sort_values(list(df1.columns)).reset_index(drop=True)
        df2_sorted = df2.sort_values(list(df2.columns)).reset_index(drop=True)

        # Compare each column individually for better error messages
        for col in df1_sorted.columns:
            if not df1_sorted[col].equals(df2_sorted[col]):
                # Find the first difference for a helpful error message
                diff_mask = df1_sorted[col] != df2_sorted[col]
                first_diff_idx = diff_mask.idxmax() if diff_mask.any() else None
                if first_diff_idx is not None:
                    old_val = df1_sorted.iloc[first_diff_idx][col]
                    new_val = df2_sorted.iloc[first_diff_idx][col]
                    assert False, f"{comparison_name}: Column '{col}' differs at row {first_diff_idx} - Old: '{old_val}' vs New: '{new_val}'"

    def test_mesin_report_parity(self, test_session, sample_activity_mesin):
        """Test that MESIN reports are identical between old and new approaches."""
        # Ensure ActivityReport exists for the new approach to work
        upsert_activity_report_sync(sample_activity_mesin.id, test_session)
        test_session.commit()

        # Define time range that includes our test data
        start_time = datetime.utcnow() - timedelta(days=1)
        end_time = datetime.utcnow() + timedelta(days=1)

        # Generate reports with old approach (feature flag OFF)
        old_imn, old_limax, _ = self.generate_reports_with_flag(
            use_new_table=False,
            test_session=test_session,
            start_time=start_time,
            end_time=end_time,
            report_category=ReportCategory.MESIN
        )

        # Generate reports with new approach (feature flag ON)
        new_imn, new_limax, _ = self.generate_reports_with_flag(
            use_new_table=True,
            test_session=test_session,
            start_time=start_time,
            end_time=end_time,
            report_category=ReportCategory.MESIN
        )

        # Compare IMN format
        self.compare_dataframes_strict(old_imn, new_imn, "MESIN IMN Format")

        # Compare LIMAX format
        self.compare_dataframes_strict(old_limax, new_limax, "MESIN LIMAX Format")

    def test_operator_report_parity(self, test_session, sample_activity_mesin):
        """Test that OPERATOR reports are identical between old and new approaches."""
        # Ensure ActivityReport exists for the new approach to work
        upsert_activity_report_sync(sample_activity_mesin.id, test_session)
        test_session.commit()

        # Define time range that includes our test data
        start_time = datetime.utcnow() - timedelta(days=1)
        end_time = datetime.utcnow() + timedelta(days=1)

        # Generate reports with old approach (feature flag OFF)
        old_imn, old_limax, _ = self.generate_reports_with_flag(
            use_new_table=False,
            test_session=test_session,
            start_time=start_time,
            end_time=end_time,
            report_category=ReportCategory.OPERATOR
        )

        # Generate reports with new approach (feature flag ON)
        new_imn, new_limax, _ = self.generate_reports_with_flag(
            use_new_table=True,
            test_session=test_session,
            start_time=start_time,
            end_time=end_time,
            report_category=ReportCategory.OPERATOR
        )

        # Compare IMN format
        self.compare_dataframes_strict(old_imn, new_imn, "OPERATOR IMN Format")

        # Compare LIMAX format
        self.compare_dataframes_strict(old_limax, new_limax, "OPERATOR LIMAX Format")

    def test_empty_data_parity(self, test_session):
        """Test that both approaches handle empty datasets identically."""
        # Use a time range with no data
        start_time = datetime(2020, 1, 1, 0, 0, 0)
        end_time = datetime(2020, 1, 2, 0, 0, 0)

        for report_category in [ReportCategory.MESIN, ReportCategory.OPERATOR]:
            # Generate reports with old approach (feature flag OFF)
            old_imn, old_limax, _ = self.generate_reports_with_flag(
                use_new_table=False,
                test_session=test_session,
                start_time=start_time,
                end_time=end_time,
                report_category=report_category
            )

            # Generate reports with new approach (feature flag ON)
            new_imn, new_limax, _ = self.generate_reports_with_flag(
                use_new_table=True,
                test_session=test_session,
                start_time=start_time,
                end_time=end_time,
                report_category=report_category
            )

            # Both should be empty with the same structure
            self.compare_dataframes_strict(old_imn, new_imn, f"{report_category.value.upper()} IMN Empty Data")
            self.compare_dataframes_strict(old_limax, new_limax, f"{report_category.value.upper()} LIMAX Empty Data")

    def test_feature_flag_restoration(self, test_session):
        """Test that the feature flag is properly restored after test operations."""
        original_flag = generate_report.USE_ACTIVITY_REPORT_TABLE

        try:
            # Use a time range with no data to make the test fast
            start_time = datetime(2020, 1, 1, 0, 0, 0)
            end_time = datetime(2020, 1, 2, 0, 0, 0)

            # This should not affect the global flag
            _, _, _ = self.generate_reports_with_flag(
                use_new_table=not original_flag,  # Opposite of current setting
                test_session=test_session,
                start_time=start_time,
                end_time=end_time,
                report_category=ReportCategory.MESIN
            )

            # Verify the flag was restored
            assert generate_report.USE_ACTIVITY_REPORT_TABLE == original_flag

        except Exception:
            # Ensure flag is restored even if test fails
            generate_report.USE_ACTIVITY_REPORT_TABLE = original_flag
            raise