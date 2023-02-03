import logging
from datetime import timedelta

from fastapi import HTTPException

import models


def check_operator(tooling_id, mesin_id, operator_id, session):
    operator_status = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )

    if operator_status is None :
        operator_status = models.OperatorStatus(
            id=operator_id, 
            status=models.OperatorStatusEnum.RUNNING,
            last_tooling_id = tooling_id,
            last_mesin_id = mesin_id
        )
        session.add(operator_status)
        session.commit()
        return True, ""
    
    if operator_status.status == models.OperatorStatusEnum.IDLE:
        return True, ""
    else:
        if (operator_status.last_tooling_id == tooling_id 
        and operator_status.last_mesin_id == mesin_id):
                return True, ""
    
    error_message = f"ERROR \nOperator {operator_id} sedang running di \n" +\
        f"Mesin:\t {operator_status.last_mesin_id} \n" +\
        f"Tooling:\t {operator_status.last_tooling_id}\n\n" + \
        f"Silahkan stop operasi di Mesin {operator_status.last_mesin_id} dan Tooling {operator_status.last_tooling_id} dengan kategori NP : No Planning, \n" + \
        "atau ganti operator di mesin tersebut."
    
    return False, error_message

def start_activity(tooling_id, mesin_id, operator_id, reject, rework, session):
    # Insert to Start Table
    start_entity = models.Start(
        tooling_id = tooling_id,
        mesin_id = mesin_id,
        operator_id = operator_id
    )
    session.add(start_entity)
    session.commit()

    # Get current mesin status
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is None:
        # Create mesin status, insert last stop 5 seconds before starting
        first_stop_mesin = models.Stop(
            mesin_id = mesin_id,
            timestamp = start_entity.timestamp - timedelta(seconds=5),
            downtime_category = "Object Creation"
        )
        session.add(first_stop_mesin)
        session.commit()

        mesin_status = models.MesinStatus(
            id=mesin_id, 
            status=models.Status.IDLE,
            last_stop = first_stop_mesin,
            last_start = start_entity,
            last_tooling_id = tooling_id,
            last_operator_id = operator_id
        )
        session.add(mesin_status)

    if mesin_status.status == models.Status.RUNNING:
        raise HTTPException(
            status_code=403, detail="Machine is already running"
        )

    prev_downtime_category = mesin_status.last_stop.downtime_category

    # Insert mesin's last downtime
    last_downtime = models.LastDowntimeMesin(
        mesin_id = mesin_id,
        start_time = mesin_status.last_stop,
        stop_time = start_entity,
        reject = reject,
        rework = rework,
        downtime_category = prev_downtime_category
    )
    session.add(last_downtime)
    session.commit()

    # Update downtime for prev operator
    # if (get_downtime_category(prev_downtime_category) != "NP"):
    last_downtime_operator = models.LastDowntimeOperator(
        operator_id = mesin_status.last_operator_id,
        start_time = mesin_status.last_stop,
        stop_time = start_entity,
        reject = reject,
        rework = rework,
        downtime_category = prev_downtime_category
    )
    session.add(last_downtime_operator)
    session.commit()

    if (mesin_status.last_operator_id != operator_id):
        operator_status = (
            session.query(models.OperatorStatus)
            .filter(models.OperatorStatus.id == mesin_status.last_operator_id)
            .one_or_none()
        )
        operator_status.status = models.OperatorStatusEnum.IDLE

    # Update mesin's status and last start
    mesin_status.status = models.Status.RUNNING
    mesin_status.last_start = start_entity
    mesin_status.last_tooling_id = tooling_id
    mesin_status.last_operator_id = operator_id
    mesin_status.category_downtime = "U : Utility"
    mesin_status.displayedStatus = models.DisplayedStatus.RUNNING
    session.commit()


def first_stop_activity(tooling_id, mesin_id, operator_id, output, downtime_category, reject, rework, session):
    logging.info("First stop activity")
    # Insert to Stop Table
    stop_entity = models.Stop(
        tooling_id = tooling_id,
        mesin_id = mesin_id,
        operator_id = operator_id,
        output = output,
        downtime_category = downtime_category
    )
    session.add(stop_entity)
    session.commit()

    # Get current mesin status
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is None:
        logging.info(f"Creating mesin status {mesin_id}")
        # Create mesin status, insert last start 5 seconds before stopping
        first_start_mesin = models.Start(
            mesin_id = mesin_id,
            timestamp = stop_entity.timestamp - timedelta(seconds=5)
        )
        session.add(first_start_mesin)
        session.commit()

        mesin_status = models.MesinStatus(
            id=mesin_id, 
            status=models.Status.RUNNING,
            last_stop = stop_entity,
            last_start = first_start_mesin,
            last_tooling_id = tooling_id,
            last_operator_id = operator_id
        )
        session.add(mesin_status)

    if mesin_status.status != models.Status.RUNNING:
        raise HTTPException(
            status_code=403, detail="Machine is already idle"
        )

    # Insert mesin's utility table
    utility = models.UtilityMesin(
        mesin_id = mesin_id,
        start_time = mesin_status.last_start,
        stop_time = stop_entity,
        output = output,
        reject = reject,
        rework = rework,
    )
    session.add(utility)
    session.commit()

    # Update downtime for prev operator
    utility_operator = models.UtilityOperator(
        operator_id = mesin_status.last_operator_id,
        start_time = mesin_status.last_start,
        stop_time = stop_entity,
        output = output,
        reject = reject,
        rework = rework,
    )
    session.add(utility_operator)
    session.commit()

    displayed_status =  get_displayed_status(downtime_category)

    if (mesin_status.last_operator_id != operator_id) or \
    (displayed_status == models.DisplayedStatus.IDLE):
        operator_status = (
            session.query(models.OperatorStatus)
            .filter(models.OperatorStatus.id == mesin_status.last_operator_id)
            .one_or_none()
        )
        operator_status.status = models.OperatorStatusEnum.IDLE

    # Update mesin's status and last stop
    mesin_status.status = update_downtime_mesin_status(downtime_category)
    mesin_status.last_stop = stop_entity
    mesin_status.last_tooling_id = tooling_id
    mesin_status.last_operator_id = operator_id
    mesin_status.category_downtime = downtime_category

    mesin_status.displayedStatus = displayed_status

    if displayed_status == models.DisplayedStatus.IDLE:
        mesin_status.last_operator_id = None


    session.commit()

def continue_stop_activity(tooling_id, mesin_id, operator_id, downtime_category, reject, rework, session):
    # Insert to Stop Table
    stop_entity = models.Stop(
        tooling_id = tooling_id,
        mesin_id = mesin_id,
        operator_id = operator_id,
        downtime_category = downtime_category
    )
    session.add(stop_entity)
    session.commit()

    # Get current mesin status
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is None:
        # Create mesin status, insert last start 5 seconds before stopping
        first_start_mesin = models.Start(
            mesin_id = mesin_id,
            timestamp = stop_entity.timestamp - timedelta(seconds=5)
        )
        session.add(first_start_mesin)
        session.commit()

        mesin_status = models.MesinStatus(
            id=mesin_id, 
            status=models.Status.IDLE,
            last_stop = stop_entity,
            last_start = first_start_mesin,
            last_tooling_id = tooling_id,
            last_operator_id = operator_id
        )
        session.add(mesin_status)

    if mesin_status.status == models.Status.RUNNING:
        raise HTTPException(
            status_code=403, detail="Machine is not running"
        )

    prev_downtime_category = mesin_status.last_stop.downtime_category
    
    # Insert mesin's continued downtime table
    continued_downtime = models.ContinuedDowntimeMesin(
        mesin_id = mesin_id,
        start_time = mesin_status.last_stop,
        stop_time = stop_entity,
        reject = reject,
        rework = rework,
        downtime_category = prev_downtime_category
    )
    session.add(continued_downtime)
    session.commit()

    # if (get_downtime_category(prev_downtime_category) != "NP"):
    continued_downtime_operator = models.ContinuedDowntimeOperator(
        operator_id = mesin_status.last_operator_id,
        start_time = mesin_status.last_stop,
        stop_time = stop_entity,
        reject = reject,
        rework = rework,
        downtime_category = prev_downtime_category
    )
    session.add(continued_downtime_operator)
    session.commit()

    displayed_status =  get_displayed_status(downtime_category)

    if (mesin_status.last_operator_id != operator_id) or \
    (displayed_status == models.DisplayedStatus.IDLE):
        operator_status = (
            session.query(models.OperatorStatus)
            .filter(models.OperatorStatus.id == mesin_status.last_operator_id)
            .one_or_none()
        )
        operator_status.status = models.OperatorStatusEnum.IDLE

    # Update mesin's status and last stop
    mesin_status.status = update_downtime_mesin_status(downtime_category)
    mesin_status.last_stop = stop_entity
    mesin_status.last_tooling_id = tooling_id
    mesin_status.last_operator_id = operator_id
    mesin_status.category_downtime = downtime_category

    mesin_status.displayedStatus = displayed_status

    if displayed_status == models.DisplayedStatus.IDLE:
        mesin_status.last_operator_id = None

    session.commit()

def get_downtime_category(downtime_category):
    return downtime_category[:2].upper()

def update_downtime_mesin_status(downtime_category):
    return models.Status.SETUP if get_downtime_category(downtime_category) in ["TP", "TS", "TL"] else models.Status.IDLE

def get_displayed_status(downtime_category):
    downtime_category_initial = get_downtime_category(downtime_category)
    return models.DisplayedStatus.IDLE if downtime_category_initial in ["NP", "BT", "BR"] else models.DisplayedStatus.DOWNTIME