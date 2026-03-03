import time

from sqlalchemy.orm import sessionmaker

import app.database as database
import app.model.models as models
import app.service.business_logic as business_logic
import app.schema as schema

session = sessionmaker(autocommit=False, autoflush=False, bind=database.get_engine())()

# --- Mock master data definitions (module-level) ---------------------------

MOCK_MESINS = [
    {"name": "A1-MOCK", "tonase": "100"},
    {"name": "A2-MOCK", "tonase": "200"},
    {"name": "A3-MOCK", "tonase": "300"},
]

MOCK_TOOLINGS = [
    schema.ToolingCreate(
        customer="Alpha Corp.",
        part_no="123-456",
        part_name="Gear",
        child_part_name="Small Gear",
        kode_tooling="001",
        common_tooling_name="TOOLING-01",
        proses="1/1",
        std_jam="1",
    ),
    schema.ToolingCreate(
        customer="Beta Corp.",
        part_no="456-789",
        part_name="Gear",
        child_part_name="Small Gear",
        kode_tooling="002",
        common_tooling_name="TOOLING-02",
        proses="1/2",
        std_jam="2",
    ),
    schema.ToolingCreate(
        customer="Charlie Corp.",
        part_no="789-123",
        part_name="Gear",
        child_part_name="Small Gear",
        kode_tooling="003",
        common_tooling_name="TOOLING-03",
        proses="1/3",
        std_jam="3",
    ),
]

MOCK_OPERATORS = [
    {"nik": "001", "name": "Operator A"},
    {"nik": "002", "name": "Operator B"},
    {"nik": "003", "name": "Operator C"},
]
def no_0_seed_data(session):
    mesin_ids, tooling_ids, operator_ids = [], [], []

    # Mesins
    for m in MOCK_MESINS:
        mc_schema = schema.MesinCreate(name=m["name"], tonase=m["tonase"])
        new_mesin = business_logic.insert_or_update_mesin(mc_schema, session)
        mesin_ids.append(new_mesin.id)

    # Toolings
    for t in MOCK_TOOLINGS:
        new_tooling = business_logic.insert_or_update_tooling(t, session)
        tooling_ids.append(new_tooling.id)

    # Operators
    for o in MOCK_OPERATORS:
        op_schema = schema.OperatorCreate(name=o["name"], nik=o["nik"])
        new_operator = business_logic.insert_or_update_operator(op_schema, session)
        operator_ids.append(new_operator.id)

    session.commit()
    return mesin_ids, tooling_ids, operator_ids

def get_seeded_ids(session):
    """
    Re-derive the IDs from DB, based on how insert_or_update_* builds IDs.
    This makes mock_activity() callable independently.
    """
    mesin_ids = [f"MC-{m['name']}".replace(" ", "-") for m in MOCK_MESINS]

    tooling_ids = [
        f"TL-{t.common_tooling_name}-{t.kode_tooling}".replace(" ", "-").replace("/", "-OF-")
        for t in MOCK_TOOLINGS
    ]

    operator_ids = [
        f"OP-{o['name'].title()}".replace(" ", "-")
        for o in MOCK_OPERATORS
    ]

    # Validate they exist (optional, but helpful)
    missing = []
    for mid in mesin_ids:
        if not session.query(models.Mesin).filter(models.Mesin.id == mid).first():
            missing.append(mid)
    for tid in tooling_ids:
        if not session.query(models.Tooling).filter(models.Tooling.id == tid).first():
            missing.append(tid)
    for oid in operator_ids:
        if not session.query(models.Operator).filter(models.Operator.id == oid).first():
            missing.append(oid)

    if missing:
        raise ValueError(f"Seed data missing in DB: {missing}. Run no_0_seed_data() first.")

    return mesin_ids, tooling_ids, operator_ids

import random
import time

def mock_activity(session):
    mesin_ids, tooling_ids, operator_ids = get_seeded_ids(session)

    mc1, mc2, mc3 = mesin_ids[0], mesin_ids[1], mesin_ids[2]
    tl1, tl2, tl3 = tooling_ids[0], tooling_ids[1], tooling_ids[2]
    opA, opB, opC = operator_ids[0], operator_ids[1], operator_ids[2]

    def do(a: schema.Activity, sleep=True):
        # normalize like /activity
        if a.curr_category in ["null", "", None]:
            a.curr_category = None
        if a.mesin_id in ["null", "", None]:
            a.mesin_id = None
        if a.tooling_id in ["null", "", None]:
            a.tooling_id = None

        business_logic.process_activity(a, session)

        if sleep:
            time.sleep(random.randint(1, 5))

    # Operator A: 1 MC 2 TL concurrently
    do(schema.Activity(operator_id=opA, mesin_id=mc1, tooling_id=tl1, curr_category=None,
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="A start U TL1 (1 MC 2 TL)"))
    do(schema.Activity(operator_id=opA, mesin_id=mc1, tooling_id=tl2, curr_category=None,
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="A start U TL2 concurrently (1 MC 2 TL)"))
    do(schema.Activity(operator_id=opA, mesin_id=mc1, tooling_id=tl1, curr_category="U : Utility",
                      next_category="BT : Breaktime", output=55, reject=1, rework=0,
                      coil_no="A-C01", lot_no="A-L01", pack_no="A-P01",
                      keterangan="A stop TL1 only -> BT (TL2 still running)"))
    do(schema.Activity(operator_id=opA, mesin_id="", tooling_id="", curr_category="BT : Breaktime",
                      next_category="BR : Briefing", output=0, reject=0, rework=0,
                      keterangan="A BT -> BR"))
    do(schema.Activity(operator_id=opA, mesin_id="", tooling_id="", curr_category="BR : Briefing",
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="A BR -> U"))
    do(schema.Activity(operator_id=opA, mesin_id=mc1, tooling_id=tl2, curr_category="U : Utility",
                      next_category="TP : Tooling Problem", output=88, reject=2, rework=1,
                      keterangan="A stop TL2 only -> TP (setup)"))
    do(schema.Activity(operator_id=opA, mesin_id=mc1, tooling_id=tl2, curr_category="TP : Tooling Problem",
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="A TP -> U (resume TL2)"))

    # Operator B: 2 MC 1 TL concurrently (same tooling)
    do(schema.Activity(operator_id=opB, mesin_id=mc2, tooling_id=tl3, curr_category=None,
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="B start U MC2 (2 MC 1 TL)"))
    do(schema.Activity(operator_id=opB, mesin_id=mc3, tooling_id=tl3, curr_category=None,
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="B start U MC3 concurrently (2 MC 1 TL)"))
    do(schema.Activity(operator_id=opB, mesin_id=mc2, tooling_id=tl3, curr_category="U : Utility",
                      next_category="NP : No Plan", output=140, reject=0, rework=3,
                      keterangan="B stop MC2 -> NP (MC3 still running)"))
    do(schema.Activity(operator_id=opB, mesin_id="", tooling_id="", curr_category="NP : No Plan",
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="B NP -> U"))
    do(schema.Activity(operator_id=opB, mesin_id=mc3, tooling_id=tl3, curr_category="U : Utility",
                      next_category="TS : Tooling Setting", output=99, reject=1, rework=0,
                      keterangan="B stop MC3 -> TS"))
    do(schema.Activity(operator_id=opB, mesin_id=mc3, tooling_id=tl3, curr_category="TS : Tooling Setting",
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="B TS -> U"))

    # Operator C: NP/BT/BR mix
    do(schema.Activity(operator_id=opC, mesin_id=mc2, tooling_id=tl1, curr_category=None,
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="C start U"))
    do(schema.Activity(operator_id=opC, mesin_id=mc2, tooling_id=tl1, curr_category="U : Utility",
                      next_category="BR : Briefing", output=10, reject=0, rework=0,
                      keterangan="C stop U -> BR"))
    do(schema.Activity(operator_id=opC, mesin_id="", tooling_id="", curr_category="BR : Briefing",
                      next_category="BT : Breaktime", output=0, reject=0, rework=0,
                      keterangan="C BR -> BT"))
    do(schema.Activity(operator_id=opC, mesin_id="", tooling_id="", curr_category="BT : Breaktime",
                      next_category="NP : No Plan", output=0, reject=0, rework=0,
                      keterangan="C BT -> NP"))
    do(schema.Activity(operator_id=opC, mesin_id="", tooling_id="", curr_category="NP : No Plan",
                      next_category="U : Utility", output=0, reject=0, rework=0,
                      keterangan="C NP -> U"))

    return {"ok": True}
