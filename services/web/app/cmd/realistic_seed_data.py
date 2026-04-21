"""
Realistic seed data for Report Table testing with proper anchor-based timing.
Uses 'right now' as anchor and builds events with realistic production scenarios.
"""
from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy.orm import sessionmaker

import app.database as database
import app.model.models as models
import app.service.business_logic as business_logic
import app.service.utils as ru
import app.schema as schema


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=database.get_engine(),
)


# Master data with realistic production targets
MOCK_MESINS = [
    {"key": "MC1", "name": "A1-MOCK", "tonase": "110"},
    {"key": "MC2", "name": "A2-MOCK", "tonase": "160"},
    {"key": "MC3", "name": "A3-MOCK", "tonase": "200"},
]

MOCK_TOOLINGS = [
    {
        "key": "TL1",
        "payload": schema.ToolingCreate(
            customer="Alpha Corp.",
            part_no="123-456",
            part_name="GEAR A",
            child_part_name="SMALL GEAR A",
            kode_tooling="001",
            common_tooling_name="TOOLING-01",
            proses="1/1",
            std_jam="120",  # 120 parts/hour - realistic target
        ),
    },
    {
        "key": "TL2",
        "payload": schema.ToolingCreate(
            customer="Beta Corp.",
            part_no="456-789",
            part_name="GEAR B",
            child_part_name="SMALL GEAR B",
            kode_tooling="002",
            common_tooling_name="TOOLING-02",
            proses="1/2",
            std_jam="180",  # 180 parts/hour
        ),
    },
    {
        "key": "TL3",
        "payload": schema.ToolingCreate(
            customer="Charlie Corp.",
            part_no="789-123",
            part_name="GEAR C",
            child_part_name="SMALL GEAR C",
            kode_tooling="003",
            common_tooling_name="TOOLING-03",
            proses="1/3",
            std_jam="240",  # 240 parts/hour
        ),
    },
]

MOCK_OPERATORS = [
    {"key": "OPA", "nik": "001", "name": "Operator A"},
    {"key": "OPB", "nik": "002", "name": "Operator B"},
    {"key": "OPC", "nik": "003", "name": "Operator C"},
]


def seed_master_data(session):
    """Create master data (machines, toolings, operators)"""
    mesin_ids = {}
    tooling_ids = {}
    operator_ids = {}

    for m in MOCK_MESINS:
        mc_schema = schema.MesinCreate(name=m["name"], tonase=m["tonase"])
        new_mesin = business_logic.insert_or_update_mesin(mc_schema, session)
        mesin_ids[m["key"]] = new_mesin.id

    for t in MOCK_TOOLINGS:
        new_tooling = business_logic.insert_or_update_tooling(t["payload"], session)
        tooling_ids[t["key"]] = new_tooling.id

    for o in MOCK_OPERATORS:
        op_schema = schema.OperatorCreate(name=o["name"], nik=o["nik"])
        new_operator = business_logic.insert_or_update_operator(op_schema, session)
        operator_ids[o["key"]] = new_operator.id

    session.commit()
    return mesin_ids, tooling_ids, operator_ids


def get_seeded_ids(session):
    """Get existing seeded IDs"""
    mesin_ids = {}
    tooling_ids = {}
    operator_ids = {}

    for m in MOCK_MESINS:
        mesin_id = f"MC-{m['name']}".replace(" ", "-")
        if not session.query(models.Mesin).filter(models.Mesin.id == mesin_id).first():
            raise ValueError(f"Missing mesin seed: {mesin_id}")
        mesin_ids[m["key"]] = mesin_id

    for t in MOCK_TOOLINGS:
        payload = t["payload"]
        tooling_id = (
            f"TL-{payload.common_tooling_name}-{payload.kode_tooling}"
            .replace(" ", "-")
            .replace("/", "-OF-")
        )
        if not session.query(models.Tooling).filter(models.Tooling.id == tooling_id).first():
            raise ValueError(f"Missing tooling seed: {tooling_id}")
        tooling_ids[t["key"]] = tooling_id

    for o in MOCK_OPERATORS:
        operator_id = f"OP-{o['name'].title()}".replace(" ", "-")
        if not session.query(models.Operator).filter(models.Operator.id == operator_id).first():
            raise ValueError(f"Missing operator seed: {operator_id}")
        operator_ids[o["key"]] = operator_id

    return mesin_ids, tooling_ids, operator_ids


def build_activity_scenario(anchor: datetime) -> List[Dict]:
    """
    Build realistic production scenario with proper timing.
    Uses anchor + timedelta for deterministic timestamps.
    """
    def at(minutes: int) -> datetime:
        return anchor + timedelta(minutes=minutes)

    return [
        # ============================================================
        # Scenario 1: Multi-operator on one machine (MC1/TL1)
        # ============================================================

        # Operator A starts MC1
        {
            "at": at(0),
            "operator": "OPA",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": None,
            "next": "RT : Runtime",  # ✅ Fixed: RT instead of U
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "A start runtime on MC1/TL1",
        },
        {
            "at": at(45),  # 45 min runtime = 90 parts @ 120/hour
            "operator": "OPA",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": "RT : Runtime",
            "next": "TP : Tooling Problem",
            "output": 88,
            "reject": 2,
            "rework": 1,
            "coil_no": "A-C01",
            "lot_no": "A-L01",
            "pack_no": "A-P01",
            "keterangan": "A runtime -> tooling issue",
        },
        {
            "at": at(60),  # 15 min downtime
            "operator": "OPA",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": "TP : Tooling Problem",
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "A fixed tooling -> resume runtime",
        },
        {
            "at": at(110),  # 50 min more runtime = 100 parts @ 120/hour
            "operator": "OPA",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": "RT : Runtime",
            "next": "BR : Briefing",
            "output": 98,
            "reject": 1,
            "rework": 1,
            "coil_no": "A-C02",
            "lot_no": "A-L02",
            "pack_no": "A-P02",
            "keterangan": "A runtime -> briefing (shift handover)",
        },

        # Operator B takes over MC1 (multi-operator one machine)
        {
            "at": at(115),
            "operator": "OPB",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": None,
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "B take over MC1/TL1 from A",
        },
        {
            "at": at(170),  # 55 min runtime = 110 parts @ 120/hour
            "operator": "OPB",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": "RT : Runtime",
            "next": "MP : Machine Problem",
            "output": 108,
            "reject": 2,
            "rework": 0,
            "coil_no": "B-C01",
            "lot_no": "B-L01",
            "pack_no": "B-P01",
            "keterangan": "B runtime -> machine jam",
        },
        {
            "at": at(185),  # 15 min downtime
            "operator": "OPB",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": "MP : Machine Problem",
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "B fixed jam -> resume runtime",
        },
        {
            "at": at(225),  # 40 min runtime = 80 parts @ 120/hour
            "operator": "OPB",
            "mesin": "MC1",
            "tooling": "TL1",
            "curr": "RT : Runtime",
            "next": "BT : Breaktime",
            "output": 78,
            "reject": 2,
            "rework": 0,
            "keterangan": "B runtime -> break",
        },

        # ============================================================
        # Scenario 2: One operator multiple machines (B on MC2 & MC3)
        # ============================================================

        # Operator B also handles MC2 (multi-machine one operator)
        {
            "at": at(10),
            "operator": "OPB",
            "mesin": "MC2",
            "tooling": "TL2",
            "curr": None,
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "B start runtime on MC2/TL2 (concurrent)",
        },
        {
            "at": at(70),  # 60 min runtime = 180 parts @ 180/hour
            "operator": "OPB",
            "mesin": "MC2",
            "tooling": "TL2",
            "curr": "RT : Runtime",
            "next": "TS : Tooling Setting",
            "output": 175,
            "reject": 3,
            "rework": 2,
            "coil_no": "B2-C01",
            "lot_no": "B2-L01",
            "pack_no": "B2-P01",
            "keterangan": "B runtime MC2 -> tooling setup",
        },
        {
            "at": at(95),  # 25 min downtime
            "operator": "OPB",
            "mesin": "MC2",
            "tooling": "TL2",
            "curr": "TS : Tooling Setting",
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "B setup complete -> resume MC2",
        },
        {
            "at": at(140),  # 45 min runtime = 135 parts @ 180/hour
            "operator": "OPB",
            "mesin": "MC2",
            "tooling": "TL2",
            "curr": "RT : Runtime",
            "next": "NP : No Plan",
            "output": 132,
            "reject": 3,
            "rework": 0,
            "keterangan": "B runtime MC2 -> no plan",
        },

        # Operator B also handles MC3
        {
            "at": at(15),
            "operator": "OPB",
            "mesin": "MC3",
            "tooling": "TL3",
            "curr": None,
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "B start runtime on MC3/TL3 (concurrent)",
        },
        {
            "at": at(90),  # 75 min runtime = 300 parts @ 240/hour
            "operator": "OPB",
            "mesin": "MC3",
            "tooling": "TL3",
            "curr": "RT : Runtime",
            "next": "TS : Tooling Setting",
            "output": 295,
            "reject": 4,
            "rework": 1,
            "coil_no": "B3-C01",
            "lot_no": "B3-L01",
            "pack_no": "B3-P01",
            "keterangan": "B runtime MC3 -> tooling change",
        },
        {
            "at": at(120),  # 30 min downtime
            "operator": "OPB",
            "mesin": "MC3",
            "tooling": "TL3",
            "curr": "TS : Tooling Setting",
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "B tooling change complete -> resume MC3",
        },
        {
            "at": at(180),  # 60 min runtime = 240 parts @ 240/hour
            "operator": "OPB",
            "mesin": "MC3",
            "tooling": "TL3",
            "curr": "RT : Runtime",
            "next": "BT : Breaktime",
            "output": 235,
            "reject": 5,
            "rework": 0,
            "coil_no": "B3-C02",
            "lot_no": "B3-L02",
            "pack_no": "B3-P02",
            "keterangan": "B runtime MC3 -> break",
        },

        # ============================================================
        # Scenario 3: Non-machine activities + brief machine work
        # ============================================================

        # Operator C: mostly non-machine activities
        {
            "at": at(5),
            "operator": "OPC",
            "mesin": None,
            "tooling": None,
            "curr": None,
            "next": "BR : Briefing",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "C start briefing",
        },
        {
            "at": at(35),  # 30 min briefing
            "operator": "OPC",
            "mesin": None,
            "tooling": None,
            "curr": "BR : Briefing",
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "C briefing -> runtime",
        },
        {
            "at": at(40),  # Brief machine work
            "operator": "OPC",
            "mesin": "MC2",
            "tooling": "TL2",
            "curr": None,
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "C start runtime on MC2/TL2 (brief stint)",
        },
        {
            "at": at(80),  # 40 min runtime = 120 parts @ 180/hour
            "operator": "OPC",
            "mesin": "MC2",
            "tooling": "TL2",
            "curr": "RT : Runtime",
            "next": "BT : Breaktime",
            "output": 118,
            "reject": 2,
            "rework": 0,
            "coil_no": "C-C01",
            "lot_no": "C-L01",
            "pack_no": "C-P01",
            "keterangan": "C runtime -> break",
        },
        {
            "at": at(110),  # 30 min break
            "operator": "OPC",
            "mesin": None,
            "tooling": None,
            "curr": "BT : Breaktime",
            "next": "NP : No Plan",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "C break -> no plan",
        },
        {
            "at": at(160),  # 50 min no plan
            "operator": "OPC",
            "mesin": None,
            "tooling": None,
            "curr": "NP : No Plan",
            "next": "RT : Runtime",
            "output": 0,
            "reject": 0,
            "rework": 0,
            "keterangan": "C no plan -> runtime available",
        },
    ]


def seed_mock_activity(session, anchor: datetime = None) -> Dict:
    """Seed realistic activity data with anchor-based timing"""
    mesin_ids, tooling_ids, operator_ids = get_seeded_ids(session)

    # Use 'right now' as anchor if not provided
    anchor = anchor or datetime.now(ru.JAKARTA_TZ).replace(second=0, microsecond=0)
    scenario = build_activity_scenario(anchor)

    DEBUG_SEED = False  # Feature flag for seed debug output

    if DEBUG_SEED:
        print(f"Seeding {len(scenario)} activities with anchor: {anchor}")

    for event in scenario:
        activity = schema.Activity(
            operator_id=operator_ids[event["operator"]],
            mesin_id=mesin_ids[event["mesin"]] if event["mesin"] else "",
            tooling_id=tooling_ids[event["tooling"]] if event["tooling"] else "",
            curr_category=event["curr"],
            next_category=event["next"],
            output=event.get("output", 0),
            reject=event.get("reject", 0),
            rework=event.get("rework", 0),
            coil_no=event.get("coil_no"),
            lot_no=event.get("lot_no"),
            pack_no=event.get("pack_no"),
            keterangan=event.get("keterangan", ""),
            event_timestamp=event["at"],
        )

        # Normalize like /activity endpoint
        if activity.curr_category in ["null", "", None]:
            activity.curr_category = None
        if activity.mesin_id in ["null", "", None]:
            activity.mesin_id = None
        if activity.tooling_id in ["null", "", None]:
            activity.tooling_id = None

        business_logic.process_activity(activity, session)

    session.commit()

    return {
        "ok": True,
        "anchor": anchor.isoformat(),
        "events_seeded": len(scenario),
        "scenario_summary": {
            "multi_op_one_mc": "OPA & OPB on MC1",
            "multi_mc_one_op": "OPB on MC2 & MC3",
            "non_machine_activities": "OPC with BR/BT/NP activities",
            "realistic_targets": "120/180/240 parts/hour",
            "proper_category_codes": "RT instead of U"
        }
    }


def run_seed():
    """Standalone function to run seed data creation"""
    session = SessionLocal()
    try:
        # Clear existing activity data
        print("Clearing existing activity data...")
        session.execute("DELETE FROM activity_mesin")
        session.commit()

        # Ensure master data exists
        print("Creating master data...")
        seed_master_data(session)

        # Create activity data
        result = seed_mock_activity(session)
        print("✅ Seed data created successfully!")
        print(f"📊 Anchor: {result['anchor']}")
        print(f"📈 Events: {result['events_seeded']}")
        print(f"🏭 Scenarios: {result['scenario_summary']}")
        return result
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating seed data: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run_seed()