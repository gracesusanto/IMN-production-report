"""
Optimized report generation using pre-computed fields.

This module provides highly optimized report generation by using pre-computed
timezone conversions, ratios, and derived metrics stored in the ActivityReport table.
"""

import pandas as pd
from datetime import datetime
from enum import Enum
import numpy as np

import app.database as database
import app.model.models as models
import app.schema as schema
from app.service.report_backfill import ensure_activity_reports_exist


def _convert_seconds_to_duration(seconds):
    """Convert seconds to formatted duration string."""
    if seconds <= 0:
        return "0sec"

    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)

    if h > 0 and m > 0 and s > 0:
        return f"{h}h {m}min {s}sec"
    elif h > 0 and m > 0:
        return f"{h}h {m}min"
    elif h > 0:
        return f"{h}h"
    elif m > 0 and s > 0:
        return f"{m}min {s}sec"
    elif m > 0:
        return f"{m}min"
    else:
        return f"{s}sec"


def _format_percent(value):
    """Format decimal percentage value to string."""
    if value is None:
        return "0.00%"
    return f"{float(value):.2f}%"


class ReportCategory(Enum):
    MESIN = "mesin"
    OPERATOR = "operator"


def session():
    """Create a new database session with proper engine binding."""
    engine = database.get_engine()
    database.SessionLocal.configure(bind=engine)
    return database.SessionLocal()


def query_activity_report_optimized(time_from, time_to):
    """
    Ultra-fast query using pre-computed fields from activity_report table.

    This version uses all pre-computed timezone conversions and derived metrics
    to eliminate expensive runtime calculations.

    AUTOMATIC BACKFILL: Ensures all ActivityReport entries exist before querying.

    Returns optimized DataFrame with all required report columns.
    """
    # First, ensure all ActivityReport entries exist for the requested time range
    try:
        total_missing, backfilled = ensure_activity_reports_exist(time_from, time_to)
        if backfilled > 0:
            print(f"Automatically backfilled {backfilled} missing ActivityReport entries")
    except Exception as e:
        print(f"Warning: Backfill failed, proceeding with available data: {e}")
    query = (
        session().query(
            # Core data - same as original
            models.ActivityReport.mesin_name.label("MC"),
            models.ActivityReport.operator_name.label("Operator"),
            models.ActivityReport.operator_nik.label("NIK"),
            models.ActivityReport.tooling_id.label("Tooling"),
            models.ActivityReport.kode_tooling.label("Kode Tooling"),
            models.ActivityReport.common_tooling_name.label("Common Tooling Name"),
            models.ActivityReport.part_no.label("Part No"),
            models.ActivityReport.part_name.label("Part Name"),
            models.ActivityReport.std_jam.label("Target"),
            models.ActivityReport.category.label("Desc"),
            models.ActivityReport.output.label("Qty"),
            models.ActivityReport.reject.label("Reject"),
            models.ActivityReport.rework.label("Rework"),
            models.ActivityReport.coil_no.label("Coil No"),
            models.ActivityReport.lot_no.label("Lot No"),
            models.ActivityReport.pack_no.label("Pack No"),
            models.ActivityReport.keterangan.label("Keterangan"),

            # PRE-COMPUTED TIMEZONE FIELDS - No runtime conversion needed!
            models.ActivityReport.start_datetime_jakarta.label("Start"),
            models.ActivityReport.stop_datetime_jakarta.label("Stop"),
            models.ActivityReport.start_date_jakarta.label("Tanggal"),
            models.ActivityReport.start_time_jakarta.label("StartTime"),
            models.ActivityReport.stop_time_jakarta.label("StopTime"),
            models.ActivityReport.shift.label("Shift"),

            # PRE-COMPUTED DERIVED METRICS - Format at presentation time
            models.ActivityReport.duration_seconds.label("Duration"),
            models.ActivityReport.productivity_percent.label("Productivity"),
            models.ActivityReport.reject_ratio_percent.label("Reject Ratio"),
            models.ActivityReport.rework_ratio_percent.label("Rework Ratio"),

            # PRE-COMPUTED LIMAX FIELDS
            models.ActivityReport.plant.label("Plant"),
            models.ActivityReport.awal_limax.label("Awal"),
            models.ActivityReport.akhir_limax.label("Akhir"),
            models.ActivityReport.kode_keterangan.label("Kode Keterangan"),

            # Keep raw timestamps for any edge case compatibility
            models.ActivityReport.start_ts_utc.label("start_ts_utc"),
            models.ActivityReport.stop_ts_utc.label("stop_ts_utc"),
        )
        .filter(models.ActivityReport.start_ts_utc >= time_from)
        .filter(models.ActivityReport.start_ts_utc < time_to)
        .order_by(models.ActivityReport.mesin_name.asc().nulls_last(), models.ActivityReport.start_ts_utc.asc())
    )

    # Use query.all() for SQLAlchemy version safety
    results = query.all()
    if results:
        # Extract columns and build DataFrame
        columns = [
            "MC", "Operator", "NIK", "Tooling", "Kode Tooling", "Common Tooling Name",
            "Part No", "Part Name", "Target", "Desc", "Qty", "Reject", "Rework",
            "Coil No", "Lot No", "Pack No", "Keterangan",
            "Start", "Stop", "Tanggal", "StartTime", "StopTime", "Shift",
            "Duration", "Productivity", "Reject Ratio", "Rework Ratio",
            "Plant", "Awal", "Akhir", "Kode Keterangan",
            "start_ts_utc", "stop_ts_utc"
        ]
        data = [list(row) for row in results]
        df = pd.DataFrame(data, columns=columns)
    else:
        df = pd.DataFrame()

    if df.empty:
        # Return empty DataFrame with correct structure for compatibility
        expected_columns = [
            "MC", "Operator", "NIK", "Tooling", "Kode Tooling", "Common Tooling Name",
            "Part No", "Part Name", "Target", "Start", "Stop", "Desc",
            "Qty", "Reject", "Rework", "Coil No", "Lot No", "Pack No", "Keterangan",
            "Tanggal", "StartTime", "StopTime", "Shift",
            "Duration", "Productivity", "Reject Ratio", "Rework Ratio",
            "Plant", "Awal", "Akhir", "Kode Keterangan"
        ]
        df = pd.DataFrame(columns=expected_columns)
        return df

    # Handle NULL values for non-machine categories - replace with "-" for compatibility
    df["MC"] = df["MC"].fillna("-")
    df["Tooling"] = df["Tooling"].fillna("-")
    df["Kode Tooling"] = df["Kode Tooling"].fillna("-")
    df["Common Tooling Name"] = df["Common Tooling Name"].fillna("-")
    df["Part No"] = df["Part No"].fillna("-")
    df["Part Name"] = df["Part Name"].fillna("-")
    df["Target"] = df["Target"].fillna(0)

    # Ensure default values for missing fields
    for col in ["Coil No", "Lot No", "Pack No", "Keterangan"]:
        df[col] = df[col].fillna("").replace("-", "")

    # Apply the same transformations as the original function
    df["Keterangan"] = df.apply(_generate_keterangan_fast, axis=1)

    # Drop the separate component columns since we have combined Keterangan
    df.drop(["Coil No", "Lot No", "Pack No"], axis=1, inplace=True)

    return df


def _generate_keterangan_fast(row):
    """
    Fast keterangan generation with pre-split components.

    This is much faster than the original since we already have the components
    as separate fields instead of parsing them from a combined string.
    """
    fields = [
        f"Keterangan: {row['Keterangan']}" if row["Keterangan"] else "",
        f"Coil No: {row['Coil No']}" if row["Coil No"] else "",
        f"Lot No: {row['Lot No']}" if row["Lot No"] else "",
        f"Pack No: {row['Pack No']}" if row["Pack No"] else "",
    ]
    return ", ".join(filter(None, fields))


def df_to_report_optimized(df, report_category, filters, sort):
    """
    Ultra-fast DataFrame transformation using pre-computed values.

    This version eliminates most runtime calculations by using pre-computed
    timezone conversions and derived metrics.

    Args:
        df: DataFrame with pre-computed fields from ActivityReport table
        report_category: ReportCategory enum
        filters: Filter parameters (applied to derived metrics)
        sort: Sort parameters
    """
    if df.empty:
        return df

    # Drop NP activities for operator reports
    if report_category == ReportCategory.OPERATOR:
        df = df[df["Desc"] != "NP : No Plan"].copy()

    # Replace empty values with "-" for display columns
    columns_to_replace = [
        "MC", "Tooling", "Kode Tooling", "Common Tooling Name", "Part No", "Part Name"
    ]
    df.loc[:, columns_to_replace] = df.loc[:, columns_to_replace].replace([0, None, np.nan], "-")

    if report_category == ReportCategory.MESIN:
        df = df[df["MC"] != "-"]  # Remove empty machine entries

    # Fill missing values with 0 and convert numeric columns
    df = df.fillna(0)
    df[["Qty", "Reject", "Rework"]] = df[["Qty", "Reject", "Rework"]].astype(int)

    # Apply filters to derived metrics BEFORE formatting (works with decimal values)
    if filters:
        df = _filter_df_optimized(df, filters)

    # Format decimal values to strings at presentation time
    df["Duration"] = df["Duration"].apply(_convert_seconds_to_duration)
    df["Productivity"] = df["Productivity"].apply(_format_percent)
    df["Reject Ratio"] = df["Reject Ratio"].apply(_format_percent)
    df["Rework Ratio"] = df["Rework Ratio"].apply(_format_percent)

    # All timezone conversions and calculations are already done!
    # Just format the date for consistency
    df["Tanggal"] = df["Tanggal"].apply(lambda x: x if x and x != "0" else "")

    # Ensure all required columns exist with defaults
    if "Plant" not in df.columns:
        df["Plant"] = df["MC"].apply(lambda mc: mc[-1] if mc and mc != "-" and len(mc) > 0 else "")

    # Apply sorting
    primary_sort = "Operator" if report_category == ReportCategory.OPERATOR else "MC"
    if sort and sort.sort_by:
        df = df.sort_values(by=[sort.sort_by], ascending=(sort.direction == "ascending"))
    else:
        df = df.sort_values(by=[primary_sort, "Start"]).reset_index(drop=True)

    return df


def _filter_df_optimized(df, filters):
    """
    Apply filters to DataFrame with pre-computed decimal values.

    NOTE: This function should be called BEFORE formatting decimal values
    to percentage strings for better performance.
    """
    conditions = []

    for field, filter_condition in filters.items():
        if field not in ["Productivity", "Reject Ratio", "Rework Ratio"]:
            continue

        # Work directly with decimal values (before formatting to strings)
        if field == "Productivity":
            numeric_values = pd.to_numeric(df["Productivity"], errors='coerce').fillna(0)
        elif field == "Reject Ratio":
            numeric_values = pd.to_numeric(df["Reject Ratio"], errors='coerce').fillna(0)
        elif field == "Rework Ratio":
            numeric_values = pd.to_numeric(df["Rework Ratio"], errors='coerce').fillna(0)

        if filter_condition.lt is not None:
            conditions.append(numeric_values <= filter_condition.lt)
        if filter_condition.gt is not None:
            conditions.append(numeric_values >= filter_condition.gt)

    if conditions:
        overall_condition = pd.concat(conditions, axis=1).all(axis=1)
        df = df[overall_condition]

    return df


def merge_consecutive_downtime_optimized(df, report_category):
    """
    Optimized consecutive downtime merging using pre-computed time values.
    """
    if df.empty:
        return df

    # Determine which column to use for grouping
    group_col = "MC" if report_category == ReportCategory.MESIN else "Operator"

    # Sort by the grouping column and start time
    df = df.sort_values(by=[group_col, "StartTime"]).reset_index(drop=True)

    merged_rows = []
    prev_row = None

    for _, row in df.iterrows():
        if prev_row is not None:
            # Check if should merge (same group, category, and tooling)
            if (row[group_col] == prev_row[group_col] and
                row["Desc"] == prev_row["Desc"] and
                row["Tooling"] == prev_row["Tooling"]):
                # Update previous row's stop time to latest
                prev_row["StopTime"] = max(prev_row["StopTime"], row["StopTime"])
                continue  # Skip adding new row, just update previous

        # Add previous row if conditions not met
        if prev_row is not None:
            merged_rows.append(prev_row)

        prev_row = row.copy()

    # Add the last row
    if prev_row is not None:
        merged_rows.append(prev_row)

    return pd.DataFrame(merged_rows)


def get_report_optimized(
    report_category: ReportCategory,
    format: schema.FormatType = schema.FormatType.LIMAX,
    date_time_from=None, shift_from=None, date_time_to=None, shift_to=None,
    pagination=None, filters=None, sort=None,
    is_backup=None, backup_year=None, backup_month=None
):
    """
    Ultra-optimized report generation using pre-computed fields.

    This function provides the same output as the original get_report but with
    dramatically improved performance by using pre-computed timezone conversions
    and derived metrics.
    """
    # Import required functions from original module for date/time handling
    from app.cmd.generate_report import _fill_default_datetime, _calculate_datetime_range, _get_month_range

    date_from, shift_from, date_to, shift_to = _fill_default_datetime(
        date_time_from, shift_from, date_time_to, shift_to
    )

    if not is_backup:
        time_from, time_to = _calculate_datetime_range(
            date_from=date_from, shift_from=shift_from,
            date_to=date_to, shift_to=shift_to,
        )
    else:
        time_from, time_to, backup_year, backup_month = _get_month_range(backup_year, backup_month)

    # Ensure all completed activities have ActivityReport entries before generating report
    total_missing, backfilled = ensure_activity_reports_exist(time_from, time_to, max_backfill=5000)
    if backfilled > 0:
        print(f"Auto-backfilled {backfilled} missing ActivityReport entries (of {total_missing} total missing)")
    elif total_missing > 0:
        print(f"Found {total_missing} missing ActivityReport entries, but backfill limit was reached")

    if ("limax" in format.value) or (is_backup == True):
        pagination = filters = sort = None

    # Use the ultra-fast optimized query
    df = query_activity_report_optimized(time_from, time_to)
    df = df_to_report_optimized(df, report_category)
    df = merge_consecutive_downtime_optimized(df, report_category)

    if pagination:
        df = df.iloc[(pagination.page - 1) * pagination.page_size : pagination.page * pagination.page_size]

    # Apply sorting if needed
    primary_sort = "Operator" if report_category == ReportCategory.OPERATOR else "MC"

    if sort:
        df = df.sort_values(by=[sort.sort_by], ascending=(sort.direction == "ascending"))
    else:
        df = df.sort_values(by=[primary_sort, "Start"]).reset_index(drop=True)

    # Generate filename
    from app.cmd.generate_report import _get_csv_filename, backup_filename

    if is_backup == True:
        filename = backup_filename(
            report_category=report_category,
            format=format,
            year=backup_year,
            month=backup_month,
        )
    else:
        filename = _get_csv_filename(
            report_category.value,
            date_from=date_from, shift_from=shift_from,
            date_to=date_to, shift_to=shift_to,
        )

    # Return appropriate format
    if "limax" in format.value:
        return prepare_limax_format(df), filename
    else:
        return prepare_imn_format(df, report_category), filename


def prepare_imn_format(df, report_category):
    """Prepare DataFrame for IMN format."""
    sort_by_first = "Operator" if report_category == ReportCategory.OPERATOR else "MC"
    sort_by_next = "MC" if report_category == ReportCategory.OPERATOR else "Operator"

    imn_header = [
        sort_by_first, "Shift", "Tanggal", "StartTime", "StopTime", sort_by_next,
        "Kode Tooling", "Common Tooling Name", "Part No", "Part Name", "Qty", "Target",
        "Reject", "Rework", "Desc", "Duration", "Productivity", "Reject Ratio", "Rework Ratio", "Keterangan",
    ]

    # Ensure all required columns exist
    for col in imn_header:
        if col not in df.columns:
            df[col] = "" if col in ["Desc", "Keterangan", "Duration", "Productivity", "Reject Ratio", "Rework Ratio",
                                    "Tanggal", "StartTime", "StopTime", "Kode Tooling", "Common Tooling Name",
                                    "Part No", "Part Name"] else 0

    return df[imn_header]


def prepare_limax_format(df):
    """Prepare DataFrame for LIMAX format using pre-computed fields."""
    limax_header = {
        "Tanggal": "STR_DATE",
        "Plant": "STR_PLNT",
        "Kode Tooling": "TLG_CODE",
        "Qty": "STR_KUAN",
        "NIK": "PEG_CODE",
        "Shift": "SHF_CODE",
        "MC": "MSN_CODE",
        "Awal": "STR_AWAL",
        "Akhir": "STR_AKHR",
        "Kode Keterangan": "DWN_CODE",
        "Keterangan": "STR_DESC",  # Use original Keterangan for LIMAX
    }

    # Ensure all required columns exist for LIMAX format
    for original_col in limax_header.keys():
        if original_col not in df.columns:
            df[original_col] = "" if original_col in ["Tanggal", "Kode Tooling", "Keterangan", "Kode Keterangan", "Awal", "Akhir"] else 0

    df_limax = df.rename(columns=limax_header)
    limax_col = [
        "STR_DATE", "STR_PLNT", "TLG_CODE", "STR_KUAN", "PEG_CODE",
        "SHF_CODE", "MSN_CODE", "STR_AWAL", "STR_AKHR", "DWN_CODE", "STR_DESC",
    ]

    # Ensure all LIMAX columns exist
    for col in limax_col:
        if col not in df_limax.columns:
            df_limax[col] = ""

    return df_limax[limax_col].astype(str)