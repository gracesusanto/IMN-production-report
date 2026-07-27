from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc, func
from sqlalchemy.orm import aliased

import app.model.models as models
import app.schema as schema
from app.service.utils import STATUS_CONFIG


def build_part_display(part_name: str | None, proses: str | None) -> str | None:
    normalized_part = (part_name or "").strip()
    if not normalized_part:
        return None
    normalized_process = (proses or "").strip()
    if not normalized_process:
        return normalized_part
    normalized_process = re.sub(
        r"^(proses|process|prs?\.?)\s*",
        "",
        normalized_process,
        flags=re.IGNORECASE,
    ).strip()
    if not normalized_process:
        return normalized_part
    return f"{normalized_part} Prs. {normalized_process}"


def _category_code(category: str) -> str:
    if not category:
        return ""
    return category.split(":", 1)[0].strip().upper()


# ---------------------------------------------------------------------------
# Deterministic layout parser — groups by process type, not plant.
#
# PROCESS_GROUP_CONFIG: maps each line name to its display group and sort order.
#   process_group  — top-level grouping shown on the andon board
#   group_order    — sort order of the process group
# ---------------------------------------------------------------------------

# Line → process group mapping.
# Machining = all G-prefix machines (G1-P1 … G8-P1).
# Stamping  = A–F, H prefixes.
# Others    = Tempering, Shearing, and anything unrecognised.
PROCESS_GROUP_CONFIG = {
    "STAMPING LINE A": {"process_group": "Stamping",            "group_order": 10},
    "STAMPING LINE B": {"process_group": "Stamping",            "group_order": 10},
    "STAMPING LINE C": {"process_group": "Stamping",            "group_order": 10},
    "STAMPING LINE D": {"process_group": "Stamping",            "group_order": 10},
    "STAMPING LINE E": {"process_group": "Stamping",            "group_order": 10},
    "STAMPING LINE F": {"process_group": "Stamping",            "group_order": 10},
    "STAMPING LINE H": {"process_group": "Stamping",            "group_order": 10},
    "MACHINING LINE":  {"process_group": "Machining",           "group_order": 20},
    "WELDING LINE":    {"process_group": "Welding",             "group_order": 30},
    "PACKING LINE":    {"process_group": "Packing & Check Load","group_order": 40},
    "TEMPERING":       {"process_group": "Others",              "group_order": 50},
    "SHEARING":        {"process_group": "Others",              "group_order": 50},
    "OTHER":           {"process_group": "Others",              "group_order": 50},
}

# Line prefixes: A–F, H = Stamping; G = Machining (all G-lines are machining).
STAMPING_PREFIXES = {"A", "B", "C", "D", "E", "F", "H"}
MACHINING_PREFIXES = {"G"}

_STAMPING = re.compile(r"^(?P<line>[A-Z])(?P<number>\d+)(?P<variant>[A-Z]*)(?:-|[\s_])P[12]$", re.IGNORECASE)
_WELDING  = re.compile(r"^W\d+(?:-|[\s_])P[12]$", re.IGNORECASE)
_NUMBER   = re.compile(r"(\d+)")


def _normalize(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).upper()


def _determine_line(name: str | None) -> str:
    n = _normalize(name)
    if n.startswith("MEJAPACK") or n.startswith("CHECKLOAD"):
        return "PACKING LINE"
    if n.startswith("TEMPERING"):
        return "TEMPERING"
    if "SHERING" in n or "SHEARING" in n:
        return "SHEARING"
    if _WELDING.match(n):
        return "WELDING LINE"
    m = _STAMPING.match(n)
    if m:
        prefix = m.group("line").upper()
        if prefix in MACHINING_PREFIXES:
            return "MACHINING LINE"
        if prefix in STAMPING_PREFIXES:
            return f"STAMPING LINE {prefix}"
    return "OTHER"


_MACHINE_KEY = re.compile(r"^(?P<prefix>[A-Z]+)(?P<number>\d+)", re.IGNORECASE)

def _machine_sort_key(name: str | None) -> tuple:
    """Sort key: (letter_prefix, number) so A1 < A2 < B1 < W1 etc."""
    n = _normalize(name)
    m = _MACHINE_KEY.match(n)
    if m:
        return (m.group("prefix").upper(), int(m.group("number")))
    # Fallback: treat as very high value
    digits = _NUMBER.search(n)
    return ("~", int(digits.group(1)) if digits else 9999)


_PLANT_SUFFIX = re.compile(r"(?:-|[\s_])P(?P<plant>[12])$", re.IGNORECASE)

PLANT_ORDER = {"P1": 10, "P2": 20, "OTHER": 999}


def _determine_plant(name: str | None) -> str:
    m = _PLANT_SUFFIX.search(_normalize(name))
    return f"P{m.group('plant')}" if m else "OTHER"


@dataclass(frozen=True)
class _Layout:
    plant: str
    line_name: str
    process_group: str
    group_order: int
    machine_sort_key: tuple


def _layout(name: str | None) -> _Layout:
    plant = _determine_plant(name)
    line = _determine_line(name)
    cfg = PROCESS_GROUP_CONFIG.get(line, PROCESS_GROUP_CONFIG["OTHER"])
    return _Layout(
        plant=plant,
        line_name=line,
        process_group=cfg["process_group"],
        group_order=cfg["group_order"],
        machine_sort_key=_machine_sort_key(name),
    )


# ---------------------------------------------------------------------------
# Database query
# ---------------------------------------------------------------------------

def query_latest_open_machine_activities(session):
    start_log_alias = aliased(models.MesinLog, name="andon_start_log")

    ranked_subquery = (
        session.query(
            models.ActivityMesin.id.label("activity_id"),
            models.ActivityMesin.mesin_id.label("mesin_id"),
            models.ActivityMesin.tooling_id.label("tooling_id"),
            models.ActivityMesin.operator_id.label("operator_id"),
            models.ActivityMesin.category.label("category"),
            models.ActivityMesin.start_time_id.label("start_log_id"),
            start_log_alias.timestamp.label("start_ts"),
            func.row_number()
            .over(
                partition_by=[
                    models.ActivityMesin.mesin_id,
                    models.ActivityMesin.operator_id,
                ],
                order_by=[
                    desc(start_log_alias.timestamp),
                    desc(models.ActivityMesin.id),
                ],
            )
            .label("rn"),
        )
        .join(start_log_alias, models.ActivityMesin.start_time_id == start_log_alias.id)
        .filter(models.ActivityMesin.stop_time_id.is_(None))
        .filter(models.ActivityMesin.mesin_id.isnot(None))
        .filter(models.ActivityMesin.mesin_id != "")
        .subquery()
    )

    return (
        session.query(
            ranked_subquery.c.activity_id,
            ranked_subquery.c.mesin_id,
            ranked_subquery.c.tooling_id,
            ranked_subquery.c.operator_id,
            ranked_subquery.c.category,
            ranked_subquery.c.start_log_id,
            ranked_subquery.c.start_ts,
            models.Mesin.name.label("mesin_name"),
            models.Mesin.tonase.label("tonase"),
            models.Tooling.part_name.label("part_name"),
            models.Tooling.part_no.label("part_no"),
            models.Tooling.kode_tooling.label("kode_tooling"),
            models.Tooling.proses.label("proses"),
            models.Operator.name.label("operator_name"),
        )
        .outerjoin(models.Mesin,     models.Mesin.id     == ranked_subquery.c.mesin_id)
        .outerjoin(models.Tooling,   models.Tooling.id   == ranked_subquery.c.tooling_id)
        .outerjoin(models.Operator,  models.Operator.id  == ranked_subquery.c.operator_id)
        .filter(ranked_subquery.c.rn == 1)
        .all()
    )


# ---------------------------------------------------------------------------
# Sort helpers — latest timestamp wins; priority breaks ties
# ---------------------------------------------------------------------------

def _as_utc(value) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_sort_key(row) -> tuple:
    code = _category_code(row["category"])
    priority = STATUS_CONFIG.get(code, {"priority": 0})["priority"]
    return (_as_utc(row["start_ts"]), priority, row["activity_id"] or 0)


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _build_active_card(machine, rows, layout: _Layout, now: datetime) -> schema.AndonMachineCard:
    mappings = [row._mapping if hasattr(row, "_mapping") else row for row in rows]

    codes = {_category_code(row["category"]) for row in mappings}

    # Newest activity wins; priority only breaks ties at the same timestamp.
    selected_row = max(mappings, key=_row_sort_key)
    selected_code = _category_code(selected_row["category"])
    selected_status = STATUS_CONFIG.get(
        selected_code,
        {"label": f"DOWNTIME {selected_code}", "group": "other", "priority": 0},
    )
    if selected_status["group"] == "other":
        selected_status = {**selected_status, "label": f"DOWNTIME {selected_code}"}

    # Find the latest conflicting (different-code) activity timestamp.
    latest_conflicting_start = max(
        (_as_utc(row["start_ts"]) for row in mappings if _category_code(row["category"]) != selected_code),
        default=None,
    )

    # Current rows: same code AND started after (or with) the last conflicting event.
    current_rows = [
        row for row in mappings
        if _category_code(row["category"]) == selected_code
        and (latest_conflicting_start is None or _as_utc(row["start_ts"]) >= latest_conflicting_start)
    ] or [selected_row]

    status_started_at = min(_as_utc(row["start_ts"]) for row in current_rows)
    last_start_at = max(_as_utc(row["start_ts"]) for row in mappings)

    show_timer = selected_code != "NP"
    duration_seconds = max(0, int((now - status_started_at).total_seconds())) if show_timer else None

    # Operators — from current_rows only (card reflects current state)
    operators_map: dict = {}
    for row in current_rows:
        op_id = row["operator_id"]
        if not op_id:
            continue
        if op_id not in operators_map:
            operators_map[op_id] = {
                "operator_id": op_id,
                "operator_name": row["operator_name"] or op_id,
                "status_codes": set(),
                "activity_ids": [],
            }
        operators_map[op_id]["status_codes"].add(_category_code(row["category"]))
        operators_map[op_id]["activity_ids"].append(row["activity_id"])

    operators = [
        schema.AndonOperator(
            operator_id=op["operator_id"],
            operator_name=op["operator_name"],
            status_codes=sorted(op["status_codes"]),
            activity_ids=sorted(op["activity_ids"]),
        )
        for op in operators_map.values()
    ]

    # Toolings — from current_rows only
    toolings_map: dict = {}
    for row in current_rows:
        tid = row["tooling_id"]
        if not tid or tid in toolings_map:
            continue
        toolings_map[tid] = schema.AndonTooling(
            tooling_id=tid,
            part_name=row["part_name"],
            part_no=row["part_no"],
            tooling_code=row["kode_tooling"],
            process=row["proses"],
        )

    # Open activities for detail drawer
    open_activities = []
    for row in mappings:
        code = _category_code(row["category"])
        cfg = STATUS_CONFIG.get(
            code,
            {"label": f"DOWNTIME {code}", "group": "other", "priority": 0},
        )
        label = f"DOWNTIME {code}" if cfg["group"] == "other" else cfg["label"]
        started_at = row["start_ts"]
        if started_at and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        is_stale = (
            started_at is not None
            and (now - started_at).total_seconds() > 24 * 60 * 60
        )
        open_activities.append(
            schema.AndonOpenActivity(
                activity_id=row["activity_id"],
                operator_id=row["operator_id"],
                tooling_id=row["tooling_id"],
                operator_name=row["operator_name"] or row["operator_id"] or "Unknown operator",
                category_code=code,
                category_label=label,
                category_raw=row["category"],
                part_name=row["part_name"],
                part_no=row["part_no"],
                tooling_code=row["kode_tooling"],
                process=row["proses"],
                started_at=started_at,
                is_stale=is_stale,
            )
        )

    part_names = sorted({row["part_name"] for row in current_rows if row["part_name"]})
    part_name = (
        part_names[0] if len(part_names) == 1
        else "MULTIPLE PARTS" if len(part_names) > 1
        else None
    )

    # For part_display pick the process from the selected row's tooling.
    selected_process = selected_row.get("proses")
    part_display = (
        build_part_display(part_name, selected_process)
        if len(part_names) == 1
        else part_name
    )

    warnings = []
    if len(codes) > 1:
        warnings.append("MIXED_STATUS")
    if len(part_names) > 1:
        warnings.append("MULTIPLE_PARTS")

    source_activity_ids = sorted({row["activity_id"] for row in mappings})
    primary_activity_id = selected_row["activity_id"]

    return schema.AndonMachineCard(
        machine_id=machine.id,
        machine_name=machine.name,
        tonnage=machine.tonase,
        plant=layout.plant,
        process_group=layout.process_group,
        line=layout.line_name,
        display_order=0,

        status_code=selected_code,
        status_label=selected_status["label"],
        status_group=selected_status["group"],
        status_source="open_activity",

        show_timer=show_timer,
        show_started_at=show_timer,

        started_at=status_started_at if show_timer else None,
        duration_seconds=duration_seconds,
        last_start_at=last_start_at if show_timer else None,

        part_name=part_name,
        part_display=part_display,
        part_display_mode="active",
        operator_display_mode="active",

        operators=operators,
        operator_count=len(operators),

        toolings=list(toolings_map.values()),
        open_activities=open_activities,

        primary_activity_id=primary_activity_id,
        source_activity_ids=source_activity_ids,
        source_start_log_ids=sorted({row["start_log_id"] for row in mappings}),

        has_mixed_status=len(codes) > 1,
        has_multiple_parts=len(part_names) > 1,
        warnings=warnings,
        version_token=str(primary_activity_id) if primary_activity_id else None,
    )


def _build_no_schedule_card(machine, layout: _Layout) -> schema.AndonMachineCard:
    return schema.AndonMachineCard(
        machine_id=machine.id,
        machine_name=machine.name,
        tonnage=machine.tonase,
        plant=layout.plant,
        process_group=layout.process_group,
        line=layout.line_name,
        display_order=0,

        status_code="NP",
        status_label="NO SCHEDULE",
        status_group="no_plan",
        status_source="computed_no_open_activity",

        show_timer=False,
        show_started_at=False,

        started_at=None,
        duration_seconds=None,
        last_start_at=None,

        part_name=None,
        part_display_mode="active",
        operator_display_mode="active",

        operators=[],
        operator_count=0,

        toolings=[],
        open_activities=[],

        primary_activity_id=None,
        source_activity_ids=[],
        source_start_log_ids=[],

        has_mixed_status=False,
        has_multiple_parts=False,
        warnings=[],
        version_token=None,
    )


# ---------------------------------------------------------------------------
# Board assembly
# ---------------------------------------------------------------------------

def get_andon_board(session) -> schema.AndonBoardResponse:
    now = datetime.now(timezone.utc)

    machines = session.query(models.Mesin).order_by(models.Mesin.id).all()

    open_rows = query_latest_open_machine_activities(session)

    rows_by_machine: dict = defaultdict(list)
    for row in open_rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        rows_by_machine[mapping["mesin_id"]].append(row)

    cards = []
    for machine in machines:
        lo = _layout(machine.name)
        machine_rows = rows_by_machine.get(machine.id, [])
        if machine_rows:
            card = _build_active_card(machine=machine, rows=machine_rows, layout=lo, now=now)
        else:
            card = _build_no_schedule_card(machine=machine, layout=lo)
        cards.append(card)

    # Group: plant → process_group → machines (no line sub-grouping)
    group_order_of = {cfg["process_group"]: cfg["group_order"] for cfg in PROCESS_GROUP_CONFIG.values()}

    plant_group_map: dict = defaultdict(lambda: defaultdict(list))
    for card in cards:
        plant_group_map[card.plant][card.process_group].append(card)

    plants = []
    for plant_name, groups_dict in sorted(plant_group_map.items(), key=lambda item: PLANT_ORDER.get(item[0], 999)):
        process_groups = []
        for group_name, group_cards in sorted(groups_dict.items(), key=lambda item: group_order_of.get(item[0], 999)):
            group_cards.sort(key=lambda c: _machine_sort_key(c.machine_name))
            process_groups.append(schema.AndonProcessGroup(name=group_name, machines=group_cards))
        plants.append(schema.AndonPlantGroup(
            name=plant_name,
            display_name={"P1": "PLANT 1", "P2": "PLANT 2"}.get(plant_name, plant_name),
            process_groups=process_groups,
        ))

    summary = schema.AndonSummary(
        total=len(cards),
        running=sum(1 for c in cards if c.status_group == "running"),
        downtime=sum(1 for c in cards if c.status_group == "downtime"),
        setup=sum(1 for c in cards if c.status_group == "setup"),
        no_plan=sum(1 for c in cards if c.status_group == "no_plan"),
        other=sum(1 for c in cards if c.status_group == "other"),
    )

    return schema.AndonBoardResponse(
        generated_at=now,
        refresh_after_seconds=10,
        summary=summary,
        plants=plants,
    )

