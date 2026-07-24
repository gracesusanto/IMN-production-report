"""Admin, maintenance, seeding, and backup APIs.

Moved verbatim out of app/main.py (no behavior change) as part of the router-split
structural refactor. See docs/REFACTOR_VERIFICATION.md for the mapping.
"""

from fastapi import APIRouter, HTTPException

import app.model.models as models
import app.cmd.db_ingestion as db_ingestion
from app.cmd.realistic_seed_data import seed_master_data, seed_mock_activity
import app.cmd.backup_csv.backup as backup
import app.cmd.get_id as get_id
import app.cmd.mock_data as mock_data
from app.database import Sessioner

router = APIRouter()


# ----- ADMIN/MIGRATION APIs ----- #
@router.get("/admin/test-connection")
def test_connection():
    """Test database connection"""
    try:
        session = Sessioner()
        count = session.query(models.ReportActivityFact).count()
        session.close()
        return {"message": f"Connection OK, found {count} records"}
    except Exception as e:
        return {"error": str(e)}

@router.post("/admin/backfill-proses")
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


# ---- DB INGESTION APIs ---#
@router.post("/db-ingestion")
def import_to_db():
    db_ingestion.import_to_db("data/db/data_all.csv")
    return True

@router.get("/mock-data")
async def mock_data_api(session=Sessioner):
    mock_data.mock_data(session)
    return

@router.post("/mock/seed-activities")
def seed_mock_activities(session=Sessioner):
    return mock_data.mock_activity(session)


# ----- BACKUP APIs ----- #
@router.post("/db-backup")
def backup_to_csv():
    backup.backup_to_csv()
    return True


@router.post("/db-import-backup")
def backup_from_csv():
    backup.backup_from_csv()
    return True

@router.get("/get-id")
def get_all_ids():
    get_id.get_csv(models.Tooling, "tooling")
    get_id.get_csv(models.Mesin, "mesin")
    get_id.get_csv(models.Operator, "operator")
    return True

@router.delete("/activity-and-log")
def delete_old_data():
    for model in [models.ActivityMesin, models.MesinLog]:
        backup.delete_old_data(model)


# ----- DEV-ONLY ENDPOINTS ----- #
@router.post("/dev/mock/seed-report-scenario")
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
