"""Dashboard reporting APIs: machine/operator summary, detail/export, and row history.

Moved verbatim out of app/main.py (no behavior change) as part of the router-split
structural refactor. See docs/REFACTOR_VERIFICATION.md for the mapping.
"""

import io
import csv

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

import app.schema as schema
import app.cmd.generate_report as generate_report

router = APIRouter()


@router.post("/api/reports/dashboard/machine-summary")
def get_machine_dashboard_summary(request: schema.DashboardReportRequest):
    """Machine Summary Dashboard - aggregated by tanggal + shift + mc + part + proses"""
    return generate_report.get_dashboard_summary_report(
        report_category=generate_report.ReportCategory.MESIN,
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
        pagination=request.pagination,
        filters=request.filters,
        sort=request.sort,
    )


@router.post("/api/reports/dashboard/operator-summary")
def get_operator_dashboard_summary(request: schema.DashboardReportRequest):
    """Operator Summary Dashboard - aggregated by tanggal + shift + operator + mc + part + proses"""
    return generate_report.get_dashboard_summary_report(
        report_category=generate_report.ReportCategory.OPERATOR,
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
        pagination=request.pagination,
        filters=request.filters,
        sort=request.sort,
    )


def _convert_dashboard_detail_to_csv(response_data: dict, report_type: str) -> StreamingResponse:
    """
    Convert dashboard detail response to CSV format.
    Uses comma delimiter as requested by user.
    """
    if not response_data or not response_data.get("rows"):
        # Empty CSV with headers only
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=",")

        # Write basic headers for empty response
        headers = ["STATUS", "MC NO.", "PART NO", "PART NAME", "PROSES", "TANGGAL", "SHIFT",
                  "TARGET/JAM", "OUTPUT", "REJECT", "PLAN", "UTILITY", "RT", "TP", "TS", "QC",
                  "CM", "NO", "NP", "NM", "MP", "BT", "BR", "RP", "STO", "X", "TOTAL DT",
                  "PER", "OTR", "QR", "OEE", "CATATAN"]

        if report_type == "operator":
            headers.insert(1, "OPERATOR")  # Insert OPERATOR after STATUS

        writer.writerow(headers)
        stream.seek(0)
        response_content = stream.getvalue()
    else:
        # Generate CSV from rows data
        rows = response_data["rows"]
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=",")

        # Define column headers and their corresponding keys in the response data
        # This matches the Excel column order as seen in the response structure
        column_mapping = [
            ("STATUS", "status"),
            ("MC NO.", "mc_no"),
            ("PART NO", "part_no"),
            ("PART NAME", "part_name"),
            ("PROSES", "proses"),
            ("TANGGAL", "tanggal"),
            ("SHIFT", "shift"),
            ("TARGET/JAM", "target_per_jam"),
            ("TARGET QTY", "target_qty"),
            ("OUTPUT", "output"),
            ("REJECT", "reject"),
            ("PLAN", "plan"),
            ("UTILITY", "utility"),
            ("RT", "rt"),
            ("TP", "tp"),
            ("TS", "ts"),
            ("QC", "qc"),
            ("CM", "cm"),
            ("NO", "no"),
            ("NP", "np"),
            ("NM", "nm"),
            ("MP", "mp"),
            ("BT", "bt"),
            ("BR", "br"),
            ("RP", "rp"),
            ("STO", "sto"),
            ("X", "x"),
            ("TOTAL DT", "total_dt"),
            ("PER", "per"),
            ("OTR", "otr"),
            ("QR", "qr"),
            ("OEE", "oee"),
            ("CATATAN", "catatan"),
        ]

        # For operator reports, insert OPERATOR column after STATUS
        if report_type == "operator":
            column_mapping.insert(1, ("OPERATOR", "operator"))

        # Write headers
        headers = [col[0] for col in column_mapping]
        writer.writerow(headers)

        # Write data rows
        for row in rows:
            csv_row = []
            for _, key in column_mapping:
                value = row.get(key, "")
                # Convert any non-string values to strings and handle None values
                if value is None:
                    value = ""
                elif not isinstance(value, str):
                    value = str(value)
                csv_row.append(value)
            writer.writerow(csv_row)

        stream.seek(0)
        response_content = stream.getvalue()

    # Generate filename with current date range
    date_from = response_data.get("date_from", "")
    date_to = response_data.get("date_to", "")
    if date_from and date_to:
        filename = f"{report_type}_dashboard_{date_from}_to_{date_to}.csv"
    else:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_type}_dashboard_{timestamp}.csv"

    return StreamingResponse(
        iter([response_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/api/reports/dashboard/detail")
def get_dashboard_detail(request: schema.DashboardDetailRequest, fastapi_request: Request):
    """Detail/Export Dashboard - Excel-like format with exact business column order"""
    report_category = (
        generate_report.ReportCategory.MESIN
        if request.report_type == schema.ReportType.MESIN
        else generate_report.ReportCategory.OPERATOR
    )

    # Check if CSV export is requested
    accept_header = fastapi_request.headers.get("accept", "")
    is_csv_request = "text/csv" in accept_header or "blob" in fastapi_request.headers.get("responseType", "")

    if is_csv_request:
        # For CSV export, remove pagination to get full dataset
        csv_request_data = request.copy()
        csv_request_data.pagination = None

        response_data = generate_report.get_detail_export_report(
            report_category=report_category,
            date_time_from=csv_request_data.date_from,
            shift_from=csv_request_data.shift_from,
            date_time_to=csv_request_data.date_to,
            shift_to=csv_request_data.shift_to,
            pagination=None,  # No pagination for CSV export
            filters=csv_request_data.filters,
            sort=csv_request_data.sort,
        )

        # Convert to CSV format
        return _convert_dashboard_detail_to_csv(response_data, request.report_type)
    else:
        # Standard JSON response
        return generate_report.get_detail_export_report(
            report_category=report_category,
            date_time_from=request.date_from,
            shift_from=request.shift_from,
            date_time_to=request.date_to,
            shift_to=request.shift_to,
            pagination=request.pagination,
            filters=request.filters,
            sort=request.sort,
        )


@router.post("/api/reports/dashboard/row-history")
def get_dashboard_row_history(request: schema.RowHistoryRequest):
    """Get detailed history and calculation breakdown for a specific summary row"""
    return generate_report.get_row_history(
        report_type=request.report_type,
        tanggal=request.tanggal,
        shift=request.shift,
        mc=request.mc,
        part_no=request.part_no,
        proses=request.proses,
        operator=request.operator,
        source_activity_ids=request.source_activity_ids
    )
