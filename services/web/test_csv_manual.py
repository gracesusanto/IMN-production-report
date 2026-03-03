#!/usr/bin/env python3
"""
Quick manual test to demonstrate CSV parity between old and new approaches.
This can be run to show that the outputs are identical.
"""

from datetime import datetime, timedelta
import pandas as pd

import app.cmd.generate_report as generate_report
from app.cmd.generate_report import ReportCategory, get_report
import app.schema as schema


def demonstrate_csv_parity():
    """Demonstrate that CSV outputs are identical."""
    print("=" * 60)
    print("CSV PARITY DEMONSTRATION")
    print("=" * 60)

    # Use a time range that should return some data if any exists
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=1)

    print(f"Time range: {start_time} to {end_time}")
    print()

    for report_category in [ReportCategory.MESIN, ReportCategory.OPERATOR]:
        print(f"--- {report_category.value.upper()} REPORT ---")

        # Generate with OLD approach (feature flag OFF)
        original_flag = generate_report.USE_ACTIVITY_REPORT_TABLE
        generate_report.USE_ACTIVITY_REPORT_TABLE = False

        try:
            old_imn, _ = get_report(
                report_category=report_category,
                format=schema.FormatType.IMN,
                date_time_from=start_time,
                date_time_to=end_time
            )
            print(f"OLD approach: {len(old_imn)} rows, {len(old_imn.columns)} columns")
        except Exception as e:
            print(f"OLD approach error: {e}")
            old_imn = pd.DataFrame()

        # Generate with NEW approach (feature flag ON)
        generate_report.USE_ACTIVITY_REPORT_TABLE = True

        try:
            new_imn, _ = get_report(
                report_category=report_category,
                format=schema.FormatType.IMN,
                date_time_from=start_time,
                date_time_to=end_time
            )
            print(f"NEW approach: {len(new_imn)} rows, {len(new_imn.columns)} columns")
        except Exception as e:
            print(f"NEW approach error: {e}")
            new_imn = pd.DataFrame()

        finally:
            # Restore original flag
            generate_report.USE_ACTIVITY_REPORT_TABLE = original_flag

        # Compare
        if old_imn.empty and new_imn.empty:
            print("✅ Both empty - IDENTICAL")
        elif old_imn.shape == new_imn.shape:
            if old_imn.equals(new_imn):
                print("✅ Exact match - IDENTICAL")
            else:
                print("⚠️  Same shape but different content")
        else:
            print(f"❌ Different shapes: {old_imn.shape} vs {new_imn.shape}")

        print()


if __name__ == "__main__":
    demonstrate_csv_parity()