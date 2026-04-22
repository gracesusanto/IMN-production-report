import os
import io

import fastapi
from fastapi import UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from fastapi_sqlalchemy import DBSessionMiddleware
from fastapi.responses import StreamingResponse

from sqlalchemy.orm import aliased
from sqlalchemy import case, func, desc, text

import app.service.business_logic as business_logic
import app.model.models as models
import app.schema as schema
from app.database import Sessioner
import app.cmd.generate_report as generate_report
import app.cmd.db_ingestion as db_ingestion
from app.cmd.realistic_seed_data import seed_master_data, seed_mock_activity
import app.cmd.backup_csv.backup as backup
import app.cmd.get_id as get_id
import app.cmd.mock_data as mock_data
import app.cmd.backfill_report_facts as backfill_report_facts

load_dotenv(".env")

app = fastapi.FastAPI()

app.add_middleware(DBSessionMiddleware, db_url=os.environ["DATABASE_URL"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # prod
        "http://localhost:3333",
        "http://192.168.0.103:3333",
        "http://192.168.0.218:3333",
        # dev
        "http://localhost:3334",
        "http://192.168.0.103:3334",
        "http://192.168.0.218:3334",
    ],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/operator/status/{operator_id}")
def get_operator_status(operator_id: str, session=Sessioner):
    """
    API to return the list of machines an operator is working on.
    Used by Main Screen to present current active machines operator can choose from.
    """

    # No need to show active activities that are not related to machine
    activities = business_logic.get_operator_active_machines(operator_id, business_logic.NON_MACHINE_CATEGORY, session)

    # If the operator has no active activities, set isRunning to False
    # IN which case app will only display "Mulai Aktivitas Baru"
    if not activities:
        return {
            "isRunning": False,
            "machines": []  # No active machines
        }

    # Used to determine where to go in Main Screen
    # U                                 --> RUNNING  --> Can input "output"
    # NP, BR, BT (Non Machine Category) --> STOP     --> Mulai Aktivitas Baru dan Akhiri {category} --> Pick new activity
    # Others: machine related downtime  --> DOWNTIME --> Ganti kategori downtime with the appropriate input boxes
    def get_mesin_status_from_category(category):
        if category == "U ":
            return "RUNNING"
        elif business_logic.is_non_machine_category(category):
            return "STOP"
        else:
            return "DOWNTIME"

    # Build the response with multiple machines
    # If the activity is non-machine related (BR, BT, RP), dont send duplicate
    machines = []
    seen_categories = set()  # Track categories that have already been included

    for activity in activities:
        if business_logic.is_non_machine_category(activity.category):
            if activity.category in seen_categories:
                continue  # Skip duplicate category
            seen_categories.add(activity.category)  # Mark category as processed

        machines.append({
            "mesinId": activity.mesin_id,
            "toolingId": activity.tooling_id,
            "category": activity.category,
            "mesinStatus": get_mesin_status_from_category(activity.category[:2])
        })


    return {
        "isRunning": True,
        "machines": machines  # List of active machines
    }

@app.post("/activity")
def post_activity(activity: schema.Activity, session=Sessioner):
    """
    API when Operator wants to stop an activity and/or start an activity
    1. Add event to mesin_log
    2. Stop operator's active NP activity (in activity_mesin)
    3. Stop current category activity as specified by operator (in activity_mesin)
    4. Start a new activity with next category, the newly created mesin_log entry as start id, and null stop id
    """

    def normalize_null(value):
        """Convert 'null' (string), None, or empty strings to None."""
        return None if value in ["null", None, ""] else value

    # Normalize inputs
    activity.curr_category = normalize_null(activity.curr_category)
    activity.mesin_id = normalize_null(activity.mesin_id)
    activity.tooling_id = normalize_null(activity.tooling_id)

    # Operator must always exist
    if not session.query(models.Operator).filter(models.Operator.id == activity.operator_id).first():
        raise fastapi.HTTPException(404, "Invalid operator_id")

    # Decide whether curr/next are machine-related using your helper
    curr_is_machine = (
        activity.curr_category is not None and not business_logic.is_non_machine_category(activity.curr_category)
    )
    next_is_machine = not business_logic.is_non_machine_category(activity.next_category)

    # If we're stopping a MACHINE curr_category, we must know which machine/tooling to stop
    if curr_is_machine:
        if not activity.mesin_id or not activity.tooling_id:
            raise fastapi.HTTPException(
                400,
                f"mesin_id and tooling_id are required to stop curr_category '{activity.curr_category}'"
            )

    # If we're starting a MACHINE next_category (e.g. U : Utility), we must know which machine/tooling to start on
    if next_is_machine:
        if not activity.mesin_id or not activity.tooling_id:
            raise fastapi.HTTPException(
                400,
                f"mesin_id and tooling_id are required to start next_category '{activity.next_category}'"
            )

    # Validate mesin/tooling existence if provided (or required)
    if activity.mesin_id:
        if not session.query(models.Mesin).filter(models.Mesin.id == activity.mesin_id).first():
            raise fastapi.HTTPException(404, "Invalid mesin_id")

    if activity.tooling_id:
        if not session.query(models.Tooling).filter(models.Tooling.id == activity.tooling_id).first():
            raise fastapi.HTTPException(404, "Invalid tooling_id")

    # IMPORTANT: Do NOT set activity.mesin_id/tooling_id to None here.
    # process_activity will decide what to store for the new activity row:
    # - if next is non-machine: new ActivityMesin should have NULL mesin/tooling
    # - if next is machine: must store mesin/tooling
    business_logic.process_activity(activity, session)

    return {"isSuccess": True}



@app.post("/activity/status")
def get_activity_status(request: schema.ActivityStatusRequest, session=Sessioner):
    """
    Returns the current status of a machine and the activities of the requesting operator.
    Used in ConfirmScreen to determine navigation and display warnings.
    """

    mesin_id = request.mesin_id
    operator_id = request.operator_id
    tooling_id = request.tooling_id
    curr_category = request.curr_category

    active_activities = (
        session.query(models.ActivityMesin)
        .filter(models.ActivityMesin.mesin_id == mesin_id)
        .filter(models.ActivityMesin.operator_id == operator_id)
        .filter(models.ActivityMesin.tooling_id == tooling_id)
        .filter(models.ActivityMesin.stop_time_id == None)  # Only active activities
        .all()
    )

    error = ""

    # Empty category means "Mulai Aktivitas Baru"
    # If operator is trying to work on the same mesin, disallow.
    if curr_category == "" and active_activities is not None:
        for active_activity in active_activities:
            # mesin only matters on machine-related categories
            # So it is okay to have multiple NP/BR/BT ongoing activities
            if not business_logic.is_non_machine_category(active_activity.category):
                error = f"Operator {operator_id} sedang menjalankan {active_activity.category} pada mesin {mesin_id} dan tooling {tooling_id}."
                break

    # Get all operator's current active activities
    # But no need to show non-machine categories (NP, BT, BR) in "Anda sedang menjalankan mesin lain"
    active_operator_activities = business_logic.get_operator_active_machines(operator_id, business_logic.NON_MACHINE_CATEGORY, session)

    # Get all operators currently using the requested machine
    # But no need to show Non-Machine related active activities
    active_machine_activities = business_logic.get_machine_active_operators(mesin_id, business_logic.NON_MACHINE_CATEGORY, session)

    # Returns the current machine status (the one the operator is about to end)
    # to determine which screen frontend app is to go next (which input field to show)
    # U          --> RUNNING --> output, reject, rework
    # TS, TL, TP --> SETUP   --> reject, rework
    # else       --> IDLE    --> no need to submit anything
    def get_mesin_status_from_category(full_category):
        category = full_category[:2]
        if category == "U ":
            return "RUNNING"
        elif business_logic.is_setup_category(category):
            return "SETUP"
        else:
            return "IDLE"

    # current mesin status to determine which screen to go next
    if curr_category != "":
        mesin_status = get_mesin_status_from_category(curr_category)
    else:
        mesin_status = "IDLE"

    # List all operators currently running the machine
    operators_on_machine = []
    for activity in active_machine_activities:
        # List of "Operator lain yang sedang menjalankan mesin ini"
        # Make sure we dont return our own activity
        if (not (activity.operator_id == request.operator_id and activity.category == curr_category) and activity.operator_id != request.operator_id):
            operators_on_machine.append({"operator_id": activity.operator_id, "tooling_id": activity.tooling_id or "", "category": activity.category or ""})

    # List all machines currently operated by this operator
    machines_by_operator = []
    for activity in active_operator_activities:
        # List of "Anda sedang menjalankan mesin lain"
        if not (activity.mesin_id == request.mesin_id and activity.category == curr_category):
            machines_by_operator.append({"mesin_id": activity.mesin_id or "", "tooling_id": activity.tooling_id or "", "category": activity.category or ""})

    return {
        "error": error,                 # Prevent operator from creating another entry on the same machine and tooling that he is currently active on
        "mesin_status": mesin_status,   # Used in ConfirmScreen to determine navigation
        # "operators_on_machine": operators_on_machine, # List of operators running on submitted mesin
        # "machines_by_operator": machines_by_operator, # List of mesin the submitted operator is running at
        "operators_on_machine": [],
        "machines_by_operator": [],
    }

# ----- DASHBOARD APIs ----- #
@app.post("/api/reports/dashboard/machine-summary")
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


@app.post("/api/reports/dashboard/operator-summary")
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


@app.post("/api/reports/dashboard/detail")
def get_dashboard_detail(request: schema.DashboardDetailRequest):
    """Detail/Export Dashboard - Excel-like format with exact business column order"""
    report_category = (
        generate_report.ReportCategory.MESIN
        if request.report_type == schema.ReportType.MESIN
        else generate_report.ReportCategory.OPERATOR
    )

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


@app.post("/api/reports/dashboard/row-history")
def get_dashboard_row_history(request: schema.RowHistoryRequest):
    """Get detailed history and calculation breakdown for a specific summary row"""
    return generate_report.get_row_history(
        report_type=request.report_type,
        tanggal=request.tanggal,
        shift=request.shift,
        mc=request.mc,
        part_no=request.part_no,
        proses=request.proses,
        operator=request.operator
    )


# ----- LEGACY REPORT APIs (for backward compatibility) ----- #
@app.post("/report/mesin")
def get_report(request: schema.ReportRequest):
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

@app.post("/report/operator")
def get_report(request: schema.ReportRequest):
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

# ----- ADMIN/MIGRATION APIs ----- #
@app.get("/admin/test-connection")
def test_connection():
    """Test database connection"""
    try:
        session = Sessioner()
        count = session.query(models.ReportActivityFact).count()
        session.close()
        return {"message": f"Connection OK, found {count} records"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/admin/backfill-proses")
def backfill_proses_field(session=Sessioner):
    """Manual backfill for proses field"""
    try:
        # Check what needs updating
        facts_needing_update = session.query(models.ReportActivityFact).filter(
            models.ReportActivityFact.proses.is_(None),
            models.ReportActivityFact.tooling_id.isnot(None)
        ).limit(5).all()  # Limit to first 5 for safety

        if not facts_needing_update:
            return {"message": "No records to update"}

        updated_count = 0
        for fact in facts_needing_update:
            tooling = session.query(models.Tooling).get(fact.tooling_id)
            if tooling and tooling.proses:
                fact.proses = tooling.proses
                updated_count += 1

        session.commit()
        return {"updated_count": updated_count, "message": "Success"}
    except Exception as e:
        session.rollback()
        return {"error": str(e)}

# ----- MODEL DATA CSV EXPORT API ----- #
@app.get("/export/csv")
def export_model_csv(model: str, session=Sessioner):
    """
    Export model data as CSV file.
    Query parameter 'model' should be one of: tooling, mesin, operator
    """
    # Map model names to model classes
    model_mapping = {
        "tooling": models.Tooling,
        "mesin": models.Mesin,
        "operator": models.Operator
    }

    # Validate model parameter
    if model.lower() not in model_mapping:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model '{model}'. Must be one of: {', '.join(model_mapping.keys())}"
        )

    model_class = model_mapping[model.lower()]
    return business_logic.export_model_csv(model_class, model.lower(), session)

# ---- DB INGESTION APIs ---#
@app.post("/db-ingestion")
def import_to_db():
    db_ingestion.import_to_db("data/db/data_all.csv")
    return True

@app.get("/mock-data")
async def mock_data_api(session=Sessioner):
    mock_data.mock_data(session)
    return

@app.post("/mock/seed-activities")
def seed_mock_activities(session=Sessioner):
    return mock_data.mock_activity(session)

# ----- BACKUP APIs ----- #
@app.post("/db-backup")
def backup_to_csv():
    backup.backup_to_csv()
    return True


@app.post("/db-import-backup")
def backup_from_csv():
    backup.backup_from_csv()
    return True

@app.get("/get-id")
def get_all_ids():
    get_id.get_csv(models.Tooling, "tooling")
    get_id.get_csv(models.Mesin, "mesin")
    get_id.get_csv(models.Operator, "operator")
    return True

@app.post("/report-backup")
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

@app.delete("/activity-and-log")
def delete_old_data():
    for model in [models.ActivityMesin, models.MesinLog]:
        backup.delete_old_data(model)

@app.get("/mesin-status-all/")
def get_mesin_status(session=Sessioner):
    try:
        start_log_alias = aliased(models.MesinLog, name="start_log")

        # Get active activities (stop_time_id is None)
        mesin_status = (
            session.query(
                func.to_char(
                    func.timezone("Asia/Jakarta", start_log_alias.timestamp),
                    "YYYY-MM-DD HH24:MI:SS"
                ).label("Start Time"),
                models.ActivityMesin.mesin_id.label("Mesin"),
                models.ActivityMesin.tooling_id.label("Tooling"),
                models.ActivityMesin.operator_id.label("Operator"),
                models.ActivityMesin.category.label("Status"),
            )
            .join(start_log_alias, models.ActivityMesin.start_time_id == start_log_alias.id)
            .filter(models.ActivityMesin.stop_time_id.is_(None))  # Only active activities
            .filter(models.ActivityMesin.mesin_id.isnot(None))     # Must have a machine
            .filter(models.ActivityMesin.mesin_id != "")           # Must not be empty string
            .filter(~models.ActivityMesin.category.startswith("NP"))  # Exclude "No Plan"
            .order_by(desc(start_log_alias.timestamp))  # Latest active activities first
            .all()
        )

        print(f"Mesin status query returned {len(mesin_status)} results")
        return {"details": mesin_status}

    except Exception as e:
        print(f"Error in get_mesin_status: {e}")
        import traceback
        traceback.print_exc()

        # Return empty result instead of failing
        return {"details": [], "error": str(e)}

@app.get("/debug/raw-activities/{date}/{machine}")
def debug_raw_activities(date: str, machine: str, session=Sessioner):
    """Debug endpoint to see raw activities for a specific date/machine"""
    try:
        # Get all activities for this machine on this date (any shift)
        activities = session.query(models.ActivityMesin).join(
            models.MesinLog, models.ActivityMesin.start_time_id == models.MesinLog.id
        ).filter(
            models.ActivityMesin.mesin_id == machine,
            func.date(models.MesinLog.timestamp) == date
        ).order_by(models.MesinLog.timestamp).all()

        result = []
        for activity in activities:
            start_log = session.query(models.MesinLog).get(activity.start_time_id)
            stop_log = session.query(models.MesinLog).get(activity.stop_time_id) if activity.stop_time_id else None

            result.append({
                "id": activity.id,
                "category": activity.category,
                "mesin_id": activity.mesin_id,
                "tooling_id": activity.tooling_id,
                "operator_id": activity.operator_id,
                "start_time": start_log.timestamp.isoformat() if start_log else None,
                "stop_time": stop_log.timestamp.isoformat() if stop_log else None,
                "output": activity.output,
                "reject": activity.reject,
                "rework": activity.rework
            })

        return {
            "date": date,
            "machine": machine,
            "total_activities": len(result),
            "activities": result
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/fact-activities/{date}/{machine}")
def debug_fact_activities(date: str, machine: str, session=Sessioner):
    """Debug endpoint to see ReportActivityFact data for a specific date/machine"""
    try:
        # Get all fact records for this machine on this date
        facts = session.query(models.ReportActivityFact).filter(
            models.ReportActivityFact.mc_name == machine,
            func.date(models.ReportActivityFact.tanggal_local) == date
        ).order_by(models.ReportActivityFact.start_ts_utc).all()

        result = []
        for fact in facts:
            result.append({
                "id": fact.activity_mesin_id,
                "mc_name": fact.mc_name,
                "part_no": fact.part_no,
                "part_name": fact.part_name,
                "proses": fact.proses,
                "start_ts_utc": fact.start_ts_utc.isoformat() if fact.start_ts_utc else None,
                "stop_ts_utc": fact.stop_ts_utc.isoformat() if fact.stop_ts_utc else None,
                "tanggal_local": str(fact.tanggal_local) if fact.tanggal_local else None,
                "shift": fact.shift,
                "category_full": fact.category_full,
                "qty": fact.qty,
                "reject": fact.reject,
                "rework": fact.rework,
                "keterangan_final": fact.keterangan_final
            })

        return {
            "date": date,
            "machine": machine,
            "total_facts": len(result),
            "facts": result
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/shift-assignments/{date}/{machine}")
def debug_shift_assignments(date: str, machine: str, session=Sessioner):
    """Debug what shift values are actually stored vs time windows"""
    try:
        from datetime import timezone, timedelta

        # Get fact data for this machine/date with their stored shift values
        facts = session.query(models.ReportActivityFact).filter(
            models.ReportActivityFact.mc_name == machine,
            func.date(models.ReportActivityFact.tanggal_local) == date
        ).order_by(models.ReportActivityFact.start_ts_utc).all()

        result = []
        for fact in facts:
            # Convert UTC to Jakarta time for comparison
            start_jakarta = fact.start_ts_utc.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=7)))
            stop_jakarta = fact.stop_ts_utc.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=7))) if fact.stop_ts_utc else None

            result.append({
                "stored_shift": fact.shift,
                "stored_tanggal": str(fact.tanggal_local),
                "start_utc": fact.start_ts_utc.isoformat(),
                "stop_utc": fact.stop_ts_utc.isoformat() if fact.stop_ts_utc else None,
                "start_jakarta": start_jakarta.strftime("%H:%M:%S"),
                "stop_jakarta": stop_jakarta.strftime("%H:%M:%S") if stop_jakarta else None,
                "part_no": fact.part_no,
                "proses": fact.proses,
                "category": fact.category_full,
                "qty": fact.qty
            })

        # Also show what time windows are calculated for each shift
        from datetime import datetime
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()

        shift_windows = {}
        for shift in ["1", "2", "3"]:
            from app.cmd.generate_report import _calculate_datetime_range
            time_from, time_to = _calculate_datetime_range(date_obj, shift, date_obj, shift)
            shift_windows[f"shift_{shift}"] = {
                "time_from": time_from.isoformat(),
                "time_to": time_to.isoformat()
            }

        return {
            "date": date,
            "machine": machine,
            "total_facts": len(result),
            "fact_data": result,
            "calculated_shift_windows": shift_windows
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

    except Exception as e:
        print(f"Error in get_mesin_status: {e}")
        import traceback
        traceback.print_exc()

        # Return empty result instead of failing
        return {"details": [], "error": str(e)}

@app.get("/debug/mesin-status-breakdown")
def debug_mesin_status(session=Sessioner):
    """Debug endpoint to understand why /mesin-status-all/ returns no data"""

    # Count total activities
    total_activities = session.query(models.ActivityMesin).count()

    # Count active activities (stop_time_id is None)
    active_activities = session.query(models.ActivityMesin).filter(
        models.ActivityMesin.stop_time_id.is_(None)
    ).count()

    # Count active activities with machines
    active_with_mesin = session.query(models.ActivityMesin).filter(
        models.ActivityMesin.stop_time_id.is_(None),
        models.ActivityMesin.mesin_id.isnot(None),
        models.ActivityMesin.mesin_id != ""
    ).count()

    # Count active non-NP activities with machines
    active_non_np = session.query(models.ActivityMesin).filter(
        models.ActivityMesin.stop_time_id.is_(None),
        models.ActivityMesin.mesin_id.isnot(None),
        models.ActivityMesin.mesin_id != "",
        ~models.ActivityMesin.category.startswith("NP")
    ).count()

    # Get sample data for each stage
    sample_active = session.query(models.ActivityMesin).filter(
        models.ActivityMesin.stop_time_id.is_(None)
    ).limit(3).all()

    sample_with_mesin = session.query(models.ActivityMesin).filter(
        models.ActivityMesin.stop_time_id.is_(None),
        models.ActivityMesin.mesin_id.isnot(None),
        models.ActivityMesin.mesin_id != ""
    ).limit(3).all()

    # Check for JOIN issues
    activities_without_start_log = session.query(models.ActivityMesin).filter(
        models.ActivityMesin.stop_time_id.is_(None),
        models.ActivityMesin.start_time_id.is_(None)
    ).count()

    return {
        "counts": {
            "total_activities": total_activities,
            "active_activities": active_activities,
            "active_with_mesin": active_with_mesin,
            "active_non_np": active_non_np,
            "activities_without_start_log": activities_without_start_log
        },
        "sample_active": [
            {
                "id": a.id,
                "mesin_id": a.mesin_id,
                "operator_id": a.operator_id,
                "category": a.category,
                "start_time_id": a.start_time_id,
                "stop_time_id": a.stop_time_id
            } for a in sample_active
        ],
        "sample_with_mesin": [
            {
                "id": a.id,
                "mesin_id": a.mesin_id,
                "operator_id": a.operator_id,
                "category": a.category,
                "start_time_id": a.start_time_id
            } for a in sample_with_mesin
        ]
    }

# ----- READ APIs ----- #
# ----- TIMESTAMP API for Cache Validation ----- #
@app.get("/timestamps/{model}")
def get_model_timestamps(model: str, session=Sessioner):
    """
    Get latest creation and update timestamps for any model records.
    Used by frontend cache validation system.

    Args:
        model: One of 'tooling', 'mesin', 'operator'
    """
    # Map model names to their corresponding SQLAlchemy models
    model_mapping = {
        "tooling": models.Tooling,
        "mesin": models.Mesin,
        "operator": models.Operator,
    }

    model_class = model_mapping.get(model.lower())
    if not model_class:
        raise fastapi.HTTPException(404, f"Model '{model}' not found. Available models: {list(model_mapping.keys())}")

    latest_created = session.query(func.max(model_class.time_created)).scalar()
    latest_updated = session.query(func.max(model_class.time_updated)).scalar()

    return {
        "model": model,
        "latest_created": latest_created.isoformat() if latest_created else None,
        "latest_updated": latest_updated.isoformat() if latest_updated else None
    }


@app.get("/tooling/{tooling_id}", response_model=schema.Tooling)
def get_tooling(tooling_id: str, session=Sessioner):
    tooling = (
        session.query(models.Tooling)
        .filter(models.Tooling.id == tooling_id)
        .one_or_none()
    )
    if tooling is None:
        raise fastapi.HTTPException(404, f"No Tooling with id {tooling_id} found.")
    return tooling


@app.get("/mesin/{mesin_id}", response_model=schema.Mesin)
def get_mesin(mesin_id: str, session=Sessioner):
    mesin = (
        session.query(models.Mesin).filter(models.Mesin.id == mesin_id).one_or_none()
    )
    if mesin is None:
        raise fastapi.HTTPException(404, f"No Machine with id {mesin_id} found.")
    return mesin


@app.get("/operator/{operator_id}", response_model=schema.Operator)
def get_operator(operator_id: str, session=Sessioner):
    operator = (
        session.query(models.Operator)
        .filter(models.Operator.id == operator_id)
        .one_or_none()
    )
    if operator is None:
        raise fastapi.HTTPException(404, f"No Operator with id {operator_id} found.")
    return operator


# ----- READ APIs ----- #
@app.get("/tooling/")
def get_tooling(session=Sessioner):
    toolings = session.query(models.Tooling).order_by(models.Tooling.id).all()
    return toolings


@app.get("/mesin/")
def get_mesin(session=Sessioner):
    mesin = session.query(models.Mesin).order_by(models.Mesin.id).all()
    return mesin


@app.get("/operator/")
def get_operator(session=Sessioner):
    operators = session.query(models.Operator).order_by(models.Operator.id).all()
    return operators


@app.get("/activity-mesin/")
def get_activity_mesin(session=Sessioner):
    activity_mesin = session.query(models.ActivityMesin).all()
    return activity_mesin


@app.get("/mesin-log/")
def get_mesin_log(session=Sessioner):
    mesin_log = session.query(models.MesinLog).all()
    return mesin_log

@app.get("/report-activity-fact/")
def get_report_activity_fact(session=Sessioner):
    mesin_log = session.query(models.ReportActivityFact).all()
    return mesin_log

# ----- CREATE & UPDATE APIs ----- #
@app.post("/operator/", response_model=schema.Operator)
def create_operator(operator_data: schema.OperatorCreate, session=Sessioner):
    operator = business_logic.insert_or_update_operator(
        operator_data, session
    )

    try:
        session.commit()
        return operator
    except Exception as e:
        session.rollback()
        raise fastapi.HTTPException(status_code=400, detail=str(e))


@app.post("/mesin/", response_model=schema.Mesin)
def create_mesin(mesin_data: schema.MesinCreate, session=Sessioner):
    mesin = business_logic.insert_or_update_mesin(
        mesin_data, session
    )
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise fastapi.HTTPException(status_code=400, detail=str(e))
    return mesin


@app.post("/tooling/", response_model=schema.Tooling)
def create_tooling(tooling_data: schema.ToolingCreate, session=Sessioner):
    tooling = business_logic.insert_or_update_tooling(tooling_data, session)

    try:
        session.commit()
        return tooling
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/operator/upload_csv")
async def upload_operator_csv(file: UploadFile = File(...), session=Sessioner):
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="Invalid file format")
    content = await file.read()
    try:
        business_logic.process_csv(
            content, business_logic.process_operator_row, session
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {e}")
    return {"detail": "Operators updated successfully"}


@app.post("/mesin/upload_csv")
async def upload_mesin_csv(file: UploadFile = File(...), session=Sessioner):
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="Invalid file format")
    content = await file.read()
    try:
        business_logic.process_csv(content, business_logic.process_mesin_row, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {e}")
    return {"detail": "Mesin updated successfully"}


@app.post("/tooling/upload_csv")
async def upload_tooling_csv(file: UploadFile = File(...), session=Sessioner):
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="Invalid file format")
    content = await file.read()
    try:
        business_logic.process_csv(content, business_logic.process_tooling_row, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {e}")
    return {"detail": "Tooling updated successfully"}

# ----- DELETE APIs ----- #
@app.delete("/tooling/{tooling_id}", status_code=204)
async def delete_tooling(tooling_id: str, session=Sessioner):
    business_logic.delete_item(models.Tooling, tooling_id, session)
    return fastapi.Response(status_code=204)


@app.delete("/mesin/{mesin_id}", status_code=204)
async def delete_mesin(mesin_id: str, session=Sessioner):
    business_logic.delete_item(models.Mesin, mesin_id, session)
    return fastapi.Response(status_code=204)


@app.delete("/operator/{operator_id}", status_code=204)
async def delete_operator(operator_id: str, session=Sessioner):
    business_logic.delete_item(models.Operator, operator_id, session)
    return fastapi.Response(status_code=204)


@app.get("/download-barcode/{model}/")
async def download_barcode(model: str, session=Sessioner):
    excel_file, filename = business_logic.generate_barcode(model, session)

    # Stream the Excel file directly without saving it to disk on the server
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.get("/barcode")
async def get_single_barcode(model: str, id: str, session=Sessioner):
    """
    Generate and return a single barcode image for a specific record.
    Query parameters:
    - model: one of 'tooling', 'mesin', 'operator'
    - id: the record ID to generate barcode for
    """
    barcode_image = business_logic.generate_single_barcode(model, id, session)

    return StreamingResponse(
        barcode_image,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{model}_{id}_barcode.png"'},
    )

@app.post("/report/backfill")
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


# ----- DEV-ONLY ENDPOINTS ----- #
@app.post("/dev/mock/seed-report-scenario")
def dev_seed_report_scenario(session=Sessioner):
    """
    Dev-only endpoint to seed realistic report data for testing.
    Creates comprehensive scenario with proper timing and KPI data.
    """
    # Environment guard - only allow in dev/local environments
    # if os.getenv("APP_ENV", "dev") not in {"dev", "local"}:
    #     raise HTTPException(status_code=403, detail="Dev seed endpoint disabled in production")

    try:
        # Clear existing activity data
        session.execute("DELETE FROM activity_mesin")
        session.commit()

        # Ensure master data exists
        seed_master_data(session)

        # Create realistic activity scenario
        result = seed_mock_activity(session)

        return {
            "status": "success",
            "message": "Realistic report scenario seeded successfully",
            "data": result
        }

    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to seed data: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
