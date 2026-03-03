#!/usr/bin/env python3
"""
CSV Output Parity Validation Script

This script validates that the CSV report output is identical when using the new
denormalized activity_report table vs the original join-based approach.

It temporarily switches the feature flag and compares the actual CSV output.
"""

import pandas as pd
from datetime import datetime, timedelta
import sys
import os
from pathlib import Path

# Add the current directory and parent directory to the Python path
current_dir = Path(__file__).parent.parent.parent.parent  # Go up to /app level
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(Path(__file__).parent.parent))

import app.cmd.generate_report as generate_report
from app.cmd.generate_report import ReportCategory, get_report
import app.schema as schema


def generate_test_data_csv(use_new_table: bool, start_time: datetime, end_time: datetime, report_category: ReportCategory):
    """
    Generate CSV data with the specified feature flag setting.

    Args:
        use_new_table: Whether to use the new activity_report table
        start_time: Start time for report
        end_time: End time for report
        report_category: MESIN or OPERATOR

    Returns:
        tuple: (imn_df, limax_df, filename)
    """
    # Temporarily set the feature flag
    original_flag = generate_report.USE_ACTIVITY_REPORT_TABLE
    generate_report.USE_ACTIVITY_REPORT_TABLE = use_new_table

    try:
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


def compare_dataframes(df1: pd.DataFrame, df2: pd.DataFrame, name: str):
    """
    Compare two DataFrames and report differences.

    Args:
        df1: First DataFrame (old approach)
        df2: Second DataFrame (new approach)
        name: Name of the comparison (for reporting)

    Returns:
        bool: True if identical, False if differences found
    """
    print(f"\n=== Comparing {name} ===")

    # Check if both are empty
    if df1.empty and df2.empty:
        print("✅ Both DataFrames are empty - IDENTICAL")
        return True

    # Check shape
    if df1.shape != df2.shape:
        print(f"❌ DIFFERENT SHAPES: Old {df1.shape} vs New {df2.shape}")
        return False

    print(f"📊 Shape: {df1.shape} (both)")

    # Check columns
    if list(df1.columns) != list(df2.columns):
        print(f"❌ DIFFERENT COLUMNS:")
        print(f"   Old: {list(df1.columns)}")
        print(f"   New: {list(df2.columns)}")
        return False

    print(f"📋 Columns: {len(df1.columns)} identical columns")

    # Compare data content
    try:
        # Reset index to ensure proper comparison
        df1_reset = df1.reset_index(drop=True)
        df2_reset = df2.reset_index(drop=True)

        # Sort both DataFrames by all columns to account for potential ordering differences
        df1_sorted = df1_reset.sort_values(list(df1_reset.columns)).reset_index(drop=True)
        df2_sorted = df2_reset.sort_values(list(df2_reset.columns)).reset_index(drop=True)

        # Compare sorted DataFrames
        comparison = df1_sorted.equals(df2_sorted)

        if comparison:
            print("✅ DATA IDENTICAL after sorting")
            return True
        else:
            print("❌ DATA DIFFERENCES found")

            # Find specific differences
            for col in df1_sorted.columns:
                if not df1_sorted[col].equals(df2_sorted[col]):
                    print(f"   Column '{col}' has differences")

                    # Show first few different values
                    diff_mask = df1_sorted[col] != df2_sorted[col]
                    if diff_mask.any():
                        diff_count = diff_mask.sum()
                        print(f"      {diff_count} different values out of {len(df1_sorted)}")

                        # Show first 3 differences
                        diff_indices = diff_mask[diff_mask].index[:3]
                        for idx in diff_indices:
                            old_val = df1_sorted.iloc[idx][col]
                            new_val = df2_sorted.iloc[idx][col]
                            print(f"      Row {idx}: Old='{old_val}' vs New='{new_val}'")

            return False

    except Exception as e:
        print(f"❌ ERROR during comparison: {e}")
        return False


def validate_csv_parity(days_back: int = 7):
    """
    Main validation function to compare CSV outputs.

    Args:
        days_back: Number of days back to include in the report
    """
    print("=" * 60)
    print("CSV OUTPUT PARITY VALIDATION")
    print("=" * 60)
    print(f"Comparing outputs with feature flag ON vs OFF")
    print(f"Time range: {days_back} days back from now")
    print()

    # Define time range
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days_back)

    print(f"📅 Time Range: {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}")

    success = True

    # Test both MESIN and OPERATOR reports
    for report_category in [ReportCategory.MESIN, ReportCategory.OPERATOR]:
        print(f"\n{'='*20} {report_category.value.upper()} REPORT {'='*20}")

        try:
            # Generate reports with old approach (feature flag OFF)
            print("🔄 Generating reports with OLD approach (joins)...")
            old_imn, old_limax, filename = generate_test_data_csv(
                use_new_table=False,
                start_time=start_time,
                end_time=end_time,
                report_category=report_category
            )

            # Generate reports with new approach (feature flag ON)
            print("🔄 Generating reports with NEW approach (denormalized)...")
            new_imn, new_limax, _ = generate_test_data_csv(
                use_new_table=True,
                start_time=start_time,
                end_time=end_time,
                report_category=report_category
            )

            # Compare IMN format
            imn_identical = compare_dataframes(old_imn, new_imn, f"{report_category.value.upper()} IMN Format")

            # Compare LIMAX format
            limax_identical = compare_dataframes(old_limax, new_limax, f"{report_category.value.upper()} LIMAX Format")

            if not imn_identical or not limax_identical:
                success = False

        except Exception as e:
            print(f"❌ ERROR processing {report_category.value} report: {e}")
            import traceback
            traceback.print_exc()
            success = False

    print("\n" + "=" * 60)
    if success:
        print("🎉 VALIDATION PASSED: All CSV outputs are IDENTICAL!")
        print("✅ The new denormalized approach produces exactly the same results")
    else:
        print("❌ VALIDATION FAILED: CSV outputs have differences")
        print("⚠️  The new approach needs investigation before deployment")

    print("=" * 60)
    return success


def main():
    """Main entry point for the validation script."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate CSV output parity between old and new approaches")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days back to include in report (default: 7)"
    )

    args = parser.parse_args()

    try:
        success = validate_csv_parity(days_back=args.days)
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n⚠️  Validation interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()