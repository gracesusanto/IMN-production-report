import time

from sqlalchemy.orm import sessionmaker

import app.database as database
import app.model.models as models
import app.service.business_logic as business_logic
import app.schema as schema

session = sessionmaker(autocommit=False, autoflush=False, bind=database.get_engine())()

mesin_ids = []
tooling_ids = []
operator_ids = []

def no_0_seed_data():
    # Create dummy data
    mesins = [
        models.Mesin(name="A1-MOCK", tonase="100"),
        models.Mesin(name="A2-MOCK", tonase="200"),
        models.Mesin(name="A3-MOCK", tonase="300"),
    ]

    toolings = [
        schema.ToolingCreate(
            customer="Alpha Corp.",
            part_no="123-456",
            part_name="Gear",
            child_part_name="Small Gear",
            kode_tooling="001",
            common_tooling_name="TOOLING-01",
            proses="1/1",
            std_jam="1"
        ),
        schema.ToolingCreate(
            customer="Beta Corp.",
            part_no="456-789",
            part_name="Gear",
            child_part_name="Small Gear",
            kode_tooling="002",
            common_tooling_name="TOOLING-02",
            proses="1/2",
            std_jam="2"
        ),
        schema.ToolingCreate(
            customer="Charlie Corp.",
            part_no="789-123",
            part_name="Gear",
            child_part_name="Small Gear",
            kode_tooling="003",
            common_tooling_name="TOOLING-03",
            proses="1/3",
            std_jam="3"
        )
    ]

    operators = [
        models.Operator(nik="001", name="Operator A"),
        models.Operator(nik="002", name="Operator B"),
        models.Operator(nik="003", name="Operator C")

    ]

    for mesin in mesins:
        # MC-A1-MOCK, MC-A2-MOCK, MC-A3-MOCK
        new_mesin = business_logic.insert_or_update_mesin(mesin, session)
        mesin_ids.append(new_mesin.id)
    for tooling in toolings:
        # TL-TOOLING-01-001, TL-TOOLING-02-002, , TL-TOOLING-03-003
        new_tooling = business_logic.insert_or_update_tooling(tooling, session)
        tooling_ids.append(new_tooling.id)
    for operator in operators:
        # OP-Operator-A, OP-Operator-B, OP-Operator-C
        new_operator = business_logic.insert_or_update_operator(operator, session)
        operator_ids.append(new_operator.id)

    session.commit()

def no_1_start_activity():
    activity = schema.Activity(
        type=schema.ActivityType.START,
        tooling_id=tooling_ids[0],
        mesin_id=mesin_ids[0],
        operator_id=operator_ids[0],
        reject=0,
        rework=0,
    )
    business_logic.start_activity(activity, session)

def no_2_first_stop_activity():
    activity = schema.Activity(
        type=schema.ActivityType.FIRST_STOP,
        tooling_id=tooling_ids[0],
        mesin_id=mesin_ids[0],
        operator_id=operator_ids[0],
        output=100,
        reject=5,
        rewor=10,
        coil_no="STEEL-15",
        lot_no="A-15",
        pack_no="B-07",
        category_downtime="TS : Tooling Setup",
    )
    business_logic.first_stop_activity(activity, session)

def no_3_continue_stop_activity():
    activity = schema.Activity(
        type=schema.ActivityType.CONTINUE_STOP,
        tooling_id=tooling_ids[0],
        mesin_id=mesin_ids[0],
        operator_id=operator_ids[0],
        reject=10,
        rewor=20,
        category_downtime="BT : Breaktime",
    )
    business_logic.continue_stop_activity(activity, session)

def run_activity():
    no_0_seed_data()
    # no_1_start_activity()
    # time.sleep(2)
    # no_2_first_stop_activity()
    # time.sleep(2)
    # no_3_continue_stop_activity()
