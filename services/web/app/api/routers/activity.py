"""Operator/activity APIs: current status, start/stop transitions, and status checks.

Moved verbatim out of app/main.py (no behavior change) as part of the router-split
structural refactor. See docs/REFACTOR_VERIFICATION.md for the mapping.
"""

import fastapi
from fastapi import APIRouter

import app.service.business_logic as business_logic
import app.model.models as models
import app.schema as schema
from app.database import Sessioner

router = APIRouter()


@router.get("/operator/status/{operator_id}")
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
        code = business_logic._category_code(category)
        if code == "U":
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
            "mesinStatus": get_mesin_status_from_category(activity.category)
        })


    return {
        "isRunning": True,
        "machines": machines  # List of active machines
    }

@router.post("/activity")
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


@router.post("/activity/status")
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
        code = business_logic._category_code(full_category)

        if code == "U":
            return "RUNNING"
        elif business_logic.is_setup_category(full_category):
            return "SETUP"
        elif business_logic.is_non_machine_category(full_category):
            return "STOP"
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
