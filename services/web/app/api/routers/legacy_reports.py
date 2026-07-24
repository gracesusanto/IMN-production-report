"""Legacy report APIs, preserved for backward compatibility.

Moved verbatim out of app/main.py (no behavior change) as part of the router-split
structural refactor. See docs/REFACTOR_VERIFICATION.md for the mapping.

Note: the two original handlers in main.py were both named `get_report`
(the second definition shadowed the first in the main.py module namespace).
This had no observable effect because FastAPI registers each route at
decoration time, before the name is rebound. They are given distinct names
here (`get_mesin_report_legacy` / `get_operator_report_legacy`) for clarity;
routes, methods, request/response shapes, and behavior are unchanged.
"""

from fastapi import APIRouter, HTTPException

import app.service.business_logic as business_logic
import app.schema as schema
import app.cmd.generate_report as generate_report
import app.cmd.backfill_report_facts as backfill_report_facts
from app.database import Sessioner

router = APIRouter()


@router.post("/report/mesin")
def get_mesin_report_legacy(request: schema.ReportRequest):
    """Legacy mesin report endpoint - unchanged behavior for backward compatibility"""
    df, filename = generate_report.get_mesin_report(
        format=request.format,
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
        pagination=request.pagination,
        filters=request.filters,
        sort=request.sort,
    )

    return business_logic.generate_report_response(df, filename, request.format)


@router.post("/report/operator")
def get_operator_report_legacy(request: schema.ReportRequest):
    """Legacy operator report endpoint - unchanged behavior for backward compatibility"""
    df, filename = generate_report.get_operator_report(
        format=request.format,
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
        pagination=request.pagination,
        filters=request.filters,
        sort=request.sort,
    )

    return business_logic.generate_report_response(df, filename, request.format)


@router.post("/report-backup")
def backup_report(request: schema.ReportBackupRequest):

    for fmt in [schema.FormatType.LIMAX, schema.FormatType.IMN]:
        df, filename = generate_report.get_operator_report(
            format=fmt,
            is_backup=True,
            backup_year=request.year, backup_month=request.month
        )
        df.to_csv(filename)

        df, filename = generate_report.get_mesin_report(
            format=fmt,
            is_backup=True,
            backup_year=request.year, backup_month=request.month
        )
        df.to_csv(filename)
    return


@router.post("/report/backfill")
def report_backfill(request: schema.ReportBackfillRequest, session=Sessioner):
    time_from = request.date_from
    time_to = request.date_to

    if time_to <= time_from:
        raise HTTPException(status_code=400, detail="date_to must be after date_from")

    total = backfill_report_facts.backfill_range(
        session=session,
        time_from_utc=time_from,
        time_to_utc=time_to,
        batch_size=request.batch_size,
    )

    return {
        "ok": True,
        "date_from": time_from,
        "date_to": time_to,
        "batch_size": request.batch_size,
        "total_backfilled": total,
    }
