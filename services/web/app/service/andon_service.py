"""Build the live Andon board from open machine activities.

Core design decisions
---------------------
1. One card per machine
   Every machine from the master table is returned. A machine with no open
   activity is represented as ``NO SCHEDULE`` rather than being omitted.

2. Multiple operators are allowed on one machine
   The database query keeps the latest open activity for each
   ``(machine_id, operator_id)`` pair. This lets several operators appear on
   the same machine while suppressing duplicate/orphaned open rows for the
   same operator.

3. A machine can still have conflicting open statuses
   When different operators have different open status codes, the newest
   status transition wins. Priority is used only when two activities have the
   exact same start timestamp. Rows belonging to the previous status are kept
   in ``open_activities`` for diagnostics, but are excluded from the card's
   active operator/tooling summary.

4. Timer semantics
   The timer starts at the earliest row in the current-status cluster. This
   represents when the machine entered the current state, not when the last
   operator joined it.

5. Layout is deterministic
   Machine names determine plant, line, process group, and sort order. The
   same machine name therefore appears in the same place on every refresh.

Important limitation
--------------------
The latest-row query assumes that one operator should have at most one current
activity on one machine. If the business intentionally allows the same operator
to run multiple toolings concurrently on the same machine, add ``tooling_id``
to the SQL window partition. Doing so will show more rows, but can also expose
old orphaned activities that are currently being suppressed.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable, Mapping

from sqlalchemy import desc, func
from sqlalchemy.orm import aliased

import app.model.models as models
import app.schema as schema
from app.service.utils import STATUS_CONFIG


# Operational constants live here so behavior is not hidden in calculations.
REFRESH_AFTER_SECONDS = 10
STALE_ACTIVITY_SECONDS = 24 * 60 * 60

# The code currently treats timezone-naive database timestamps as UTC.
# If the database actually stores naive Asia/Jakarta time, this must be changed
# centrally; otherwise timers can be off by seven hours.
NAIVE_TIMESTAMP_TIMEZONE = timezone.utc
MIN_UTC_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Display and status helpers
# ---------------------------------------------------------------------------

_PROCESS_PREFIX_RE = re.compile(
    r"^(proses|process|prs?\.?)\s*",
    flags=re.IGNORECASE,
)


def build_part_display(part_name: str | None, proses: str | None) -> str | None:
    """Return a compact part label such as ``Case Magnet B8A Prs. 3/4``.

    ``Tooling.proses`` sometimes already contains text such as ``Proses`` or
    ``Prs.``. Removing that prefix avoids duplicated output like
    ``Prs. Prs. 3/4``.
    """

    normalized_part = (part_name or "").strip()
    if not normalized_part:
        return None

    normalized_process = (proses or "").strip()
    if not normalized_process:
        return normalized_part

    normalized_process = _PROCESS_PREFIX_RE.sub("", normalized_process).strip()
    if not normalized_process:
        return normalized_part

    return f"{normalized_part} Prs. {normalized_process}"


def _category_code(category: str | None) -> str:
    """Extract the short status code from values such as ``MP : Machine``."""

    if not category:
        return ""
    return category.split(":", 1)[0].strip().upper()


@lru_cache(maxsize=128)
def _status_for_code(code: str) -> dict[str, Any]:
    """Resolve a status without overwriting configured labels.

    A previous implementation replaced every configured status in the
    ``other`` group with ``DOWNTIME <code>``. That accidentally hid useful
    labels such as ``REPORTING``. Only genuinely unknown codes now receive the
    generic fallback label.
    """

    configured = STATUS_CONFIG.get(code)
    if configured is not None:
        return {
            "label": configured.get("label") or code or "UNKNOWN",
            "group": configured.get("group") or "other",
            "priority": configured.get("priority") or 0,
        }

    safe_code = code or "UNKNOWN"
    return {
        "label": f"DOWNTIME {safe_code}",
        "group": "other",
        "priority": 0,
    }


# ---------------------------------------------------------------------------
# Deterministic layout parser
# ---------------------------------------------------------------------------
#
# The response is grouped as:
#     plant -> process_group -> machine cards
#
# ``line_name`` is still stored on every card so the frontend can display or
# filter specific lines. The backend intentionally does not create another
# nested line level in the response. If the frontend must render separate
# headers for STAMPING LINE A and STAMPING LINE B, it can subgroup the cards by
# ``card.line``, or the API schema can be expanded later.
# ---------------------------------------------------------------------------

PROCESS_GROUP_CONFIG = {
    "STAMPING LINE A": {"process_group": "Stamping", "group_order": 10},
    "STAMPING LINE B": {"process_group": "Stamping", "group_order": 10},
    "STAMPING LINE C": {"process_group": "Stamping", "group_order": 10},
    "STAMPING LINE D": {"process_group": "Stamping", "group_order": 10},
    "STAMPING LINE E": {"process_group": "Stamping", "group_order": 10},
    "STAMPING LINE F": {"process_group": "Stamping", "group_order": 10},
    "STAMPING LINE H": {"process_group": "Stamping", "group_order": 10},
    "MACHINING LINE": {"process_group": "Machining", "group_order": 20},
    "WELDING LINE": {"process_group": "Welding", "group_order": 30},
    "PACKING LINE": {
        "process_group": "Packing & Check Load",
        "group_order": 40,
    },
    "TEMPERING": {"process_group": "Others", "group_order": 50},
    "SHEARING": {"process_group": "Others", "group_order": 50},
    "OTHER": {"process_group": "Others", "group_order": 50},
}

# Derived once at import time instead of rebuilding the same dictionary on
# every 10-second board refresh.
PROCESS_GROUP_ORDER = {
    config["process_group"]: config["group_order"]
    for config in PROCESS_GROUP_CONFIG.values()
}

STAMPING_PREFIXES = frozenset({"A", "B", "C", "D", "E", "F", "H"})
MACHINING_PREFIXES = frozenset({"G"})

_MACHINE_WITH_PLANT_RE = re.compile(
    r"^(?P<line>[A-Z])(?P<number>\d+)(?P<variant>[A-Z]*)(?:-|[\s_])P[12]$",
    re.IGNORECASE,
)
_WELDING_RE = re.compile(r"^W\d+(?:-|[\s_])P[12]$", re.IGNORECASE)
_MACHINE_KEY_RE = re.compile(
    r"^(?P<prefix>[A-Z]+)(?P<number>\d+)",
    re.IGNORECASE,
)
_PLANT_SUFFIX_RE = re.compile(
    r"(?:-|[\s_])P(?P<plant>[12])$",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(\d+)")

PLANT_ORDER = {"P1": 10, "P2": 20, "OTHER": 999}
PLANT_DISPLAY_NAME = {"P1": "PLANT 1", "P2": "PLANT 2"}


def _normalize(name: str | None) -> str:
    """Normalize spacing and case before applying machine-name rules."""

    return re.sub(r"\s+", " ", (name or "").strip()).upper()


def _determine_line_from_normalized(name: str) -> str:
    """Map a normalized machine name to its operational line."""

    if name.startswith(("MEJAPACK", "CHECKLOAD")):
        return "PACKING LINE"
    if name.startswith("TEMPERING"):
        return "TEMPERING"
    if "SHERING" in name or "SHEARING" in name:
        return "SHEARING"
    if _WELDING_RE.match(name):
        return "WELDING LINE"

    match = _MACHINE_WITH_PLANT_RE.match(name)
    if match:
        prefix = match.group("line").upper()
        if prefix in MACHINING_PREFIXES:
            return "MACHINING LINE"
        if prefix in STAMPING_PREFIXES:
            return f"STAMPING LINE {prefix}"

    return "OTHER"


def _determine_plant_from_normalized(name: str) -> str:
    """Read the ``-P1``/`` P2`` suffix; unmatched names go to OTHER."""

    match = _PLANT_SUFFIX_RE.search(name)
    return f"P{match.group('plant')}" if match else "OTHER"


def _machine_sort_key_from_normalized(name: str) -> tuple[str, int, str]:
    """Create a natural and deterministic machine ordering.

    Examples: A1 < A2 < A10 < B1. The complete normalized name is included as
    a final tie-breaker so names such as A1 and A1B never depend on database
    return order.
    """

    match = _MACHINE_KEY_RE.match(name)
    if match:
        return (
            match.group("prefix").upper(),
            int(match.group("number")),
            name,
        )

    # Unrecognised names are placed after normal prefixed machines. If a number
    # exists, it still gives the fallback entries a stable natural order.
    digits = _NUMBER_RE.search(name)
    return ("~", int(digits.group(1)) if digits else 9999, name)


@dataclass(frozen=True)
class _Layout:
    """Precomputed placement metadata for one machine."""

    plant: str
    line_name: str
    process_group: str
    machine_sort_key: tuple[str, int, str]


@lru_cache(maxsize=512)
def _layout(name: str | None) -> _Layout:
    """Parse a machine name once and cache the deterministic result.

    The board refreshes frequently, while machine names rarely change. Caching
    avoids repeating several regular-expression matches on every request.
    """

    normalized_name = _normalize(name)
    plant = _determine_plant_from_normalized(normalized_name)
    line = _determine_line_from_normalized(normalized_name)
    config = PROCESS_GROUP_CONFIG.get(line, PROCESS_GROUP_CONFIG["OTHER"])

    return _Layout(
        plant=plant,
        line_name=line,
        process_group=config["process_group"],
        machine_sort_key=_machine_sort_key_from_normalized(normalized_name),
    )


# ---------------------------------------------------------------------------
# Database query
# ---------------------------------------------------------------------------


def query_latest_open_machine_activities(session):
    """Fetch one latest open activity per machine/operator pair.

    Why a SQL window function is used
    ---------------------------------
    A machine can have multiple operators. Partitioning by both machine and
    operator preserves one row for each operator. Within each partition, the
    newest open activity receives ``rn = 1`` and older duplicates are ignored.

    Conflict handled by this query
    ------------------------------
    Operators sometimes leave old activities open. Without ranking, the board
    could show the same operator several times and incorrectly combine old
    tooling/status data with the current state.

    Trade-off
    ---------
    If one operator is intentionally allowed to have several concurrent
    toolings on the same machine, this partition is too aggressive. In that
    case, include ``tooling_id`` in ``partition_by`` after confirming that it
    will not reintroduce orphaned history.

    Performance note
    ----------------
    Machine name and tonnage are not selected here because ``get_andon_board``
    already loads the machine master table. Removing that duplicate join and
    duplicate columns reduces query work and transferred data.
    """

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
                    # Activity IDs are only a deterministic tie-breaker. Do not
                    # assume a string ID is chronologically sortable.
                    desc(models.ActivityMesin.id),
                ],
            )
            .label("rn"),
        )
        .join(
            start_log_alias,
            models.ActivityMesin.start_time_id == start_log_alias.id,
        )
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
            models.Tooling.part_name.label("part_name"),
            models.Tooling.part_no.label("part_no"),
            models.Tooling.kode_tooling.label("kode_tooling"),
            models.Tooling.proses.label("proses"),
            models.Operator.name.label("operator_name"),
        )
        .outerjoin(
            models.Tooling,
            models.Tooling.id == ranked_subquery.c.tooling_id,
        )
        .outerjoin(
            models.Operator,
            models.Operator.id == ranked_subquery.c.operator_id,
        )
        .filter(ranked_subquery.c.rn == 1)
        .all()
    )


# ---------------------------------------------------------------------------
# Row preparation and deterministic conflict resolution
# ---------------------------------------------------------------------------


def _optional_as_utc(value: datetime | None) -> datetime | None:
    """Convert a timestamp to aware UTC while preserving ``None``."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=NAIVE_TIMESTAMP_TIMEZONE)
    return value.astimezone(timezone.utc)


def _prepare_activity_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Normalize frequently reused fields once per database row.

    ``category`` parsing and timezone conversion were previously repeated in
    several loops. Preparing them once makes the later conflict-resolution code
    easier to read and avoids redundant work.
    """

    prepared_rows: list[dict[str, Any]] = []
    for row in rows:
        mapping: Mapping[str, Any] = (
            row._mapping if hasattr(row, "_mapping") else row
        )
        prepared = dict(mapping)
        prepared["_category_code"] = _category_code(prepared.get("category"))
        prepared["_start_ts_utc"] = _optional_as_utc(prepared.get("start_ts"))
        prepared_rows.append(prepared)
    return prepared_rows


def _row_sort_key(row: Mapping[str, Any]) -> tuple[datetime, int, str]:
    """Newest timestamp wins; priority and ID resolve exact-time ties."""

    code = row["_category_code"]
    priority = _status_for_code(code)["priority"]

    # Convert to string so a defensive ``None`` value can never be compared to
    # a string ID and raise TypeError during a tie.
    activity_id = str(row.get("activity_id") or "")
    return (
        row.get("_start_ts_utc")
        or MIN_UTC_DATETIME,
        priority,
        activity_id,
    )


def _sorted_unique(values: Iterable[Any]) -> list[Any]:
    """Return non-null unique identifiers in deterministic order."""

    return sorted({value for value in values if value is not None}, key=str)


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------


def _build_active_card(
    machine,
    rows,
    layout: _Layout,
    now: datetime,
) -> schema.AndonMachineCard:
    """Collapse several operator rows into one current machine card.

    Conflict-resolution algorithm
    -----------------------------
    1. Select the newest activity across all operators.
    2. When timestamps tie exactly, use ``STATUS_CONFIG.priority``.
    3. Find the latest row whose status differs from the selected status.
    4. Keep selected-status rows that started at or after that conflicting row.

    Step 4 is important. It prevents an old, still-open operator row from a
    previous machine state from remaining visible after another operator has
    moved the machine to a new status.

    Example
    -------
    - Operator A: RUNNING at 08:00, never closed
    - Operator B: MACHINE PROBLEM at 10:00

    The card shows MACHINE PROBLEM and only rows belonging to that current
    status cluster. Operator A's stale RUNNING row remains in the detail drawer
    so an administrator can diagnose and close it.
    """

    mappings = _prepare_activity_rows(rows)
    codes = {row["_category_code"] for row in mappings}

    # The SQL query does not guarantee result order, so all decisions use an
    # explicit deterministic key.
    selected_row = max(mappings, key=_row_sort_key)
    selected_code = selected_row["_category_code"]
    selected_status = _status_for_code(selected_code)

    # A row with a different code marks a potential status boundary. Only the
    # latest such boundary matters when identifying the current status cluster.
    latest_conflicting_start = max(
        (
            row["_start_ts_utc"]
            for row in mappings
            if row["_category_code"] != selected_code
            and row["_start_ts_utc"] is not None
        ),
        default=None,
    )

    current_rows = [
        row
        for row in mappings
        if row["_category_code"] == selected_code
        and (
            latest_conflicting_start is None
            or (
                row["_start_ts_utc"] is not None
                and row["_start_ts_utc"] >= latest_conflicting_start
            )
        )
    ] or [selected_row]

    valid_current_starts = [
        row["_start_ts_utc"]
        for row in current_rows
        if row["_start_ts_utc"] is not None
    ]
    valid_all_starts = [
        row["_start_ts_utc"]
        for row in mappings
        if row["_start_ts_utc"] is not None
    ]

    # Earliest current-row start represents the machine entering this state;
    # using the latest would incorrectly restart the timer whenever another
    # operator joins the same state.
    status_started_at = min(valid_current_starts) if valid_current_starts else now
    last_start_at = max(valid_all_starts) if valid_all_starts else now

    show_timer = selected_code != "NP"
    duration_seconds = (
        max(0, int((now - status_started_at).total_seconds()))
        if show_timer
        else None
    )

    # Operators are intentionally derived from ``current_rows`` only. Using all
    # mappings would make operators from a previous conflicting state appear on
    # the main card.
    operators_map: dict[Any, dict[str, Any]] = {}
    for row in current_rows:
        operator_id = row.get("operator_id")
        if not operator_id:
            continue

        operator = operators_map.setdefault(
            operator_id,
            {
                "operator_id": operator_id,
                "operator_name": row.get("operator_name") or operator_id,
                "status_codes": set(),
                "activity_ids": [],
            },
        )
        operator["status_codes"].add(row["_category_code"])
        if row.get("activity_id") is not None:
            operator["activity_ids"].append(row["activity_id"])

    # Sort output so card text and API snapshots do not change when the database
    # returns the same rows in a different order.
    operators = [
        schema.AndonOperator(
            operator_id=operator["operator_id"],
            operator_name=operator["operator_name"],
            status_codes=sorted(operator["status_codes"]),
            activity_ids=_sorted_unique(operator["activity_ids"]),
        )
        for operator in sorted(
            operators_map.values(),
            key=lambda item: (
                str(item["operator_name"]).upper(),
                str(item["operator_id"]),
            ),
        )
    ]

    # Toolings follow the same current-state rule as operators. One tooling is
    # emitted once even when multiple operators reference it.
    toolings_map: dict[Any, schema.AndonTooling] = {}
    for row in current_rows:
        tooling_id = row.get("tooling_id")
        if not tooling_id or tooling_id in toolings_map:
            continue

        toolings_map[tooling_id] = schema.AndonTooling(
            tooling_id=tooling_id,
            part_name=row.get("part_name"),
            part_no=row.get("part_no"),
            tooling_code=row.get("kode_tooling"),
            process=row.get("proses"),
        )

    toolings = [
        toolings_map[tooling_id]
        for tooling_id in sorted(toolings_map, key=str)
    ]

    # The detail drawer intentionally includes every row returned by the query,
    # including conflicting rows. This is diagnostic data; hiding it would make
    # mixed/open activity problems harder to repair.
    open_activities = []
    for row in sorted(mappings, key=_row_sort_key, reverse=True):
        code = row["_category_code"]
        status = _status_for_code(code)
        started_at = row["_start_ts_utc"]
        is_stale = (
            started_at is not None
            and (now - started_at).total_seconds() > STALE_ACTIVITY_SECONDS
        )

        open_activities.append(
            schema.AndonOpenActivity(
                activity_id=row.get("activity_id"),
                operator_id=row.get("operator_id"),
                tooling_id=row.get("tooling_id"),
                operator_name=(
                    row.get("operator_name")
                    or row.get("operator_id")
                    or "Unknown operator"
                ),
                category_code=code,
                category_label=status["label"],
                category_raw=row.get("category"),
                part_name=row.get("part_name"),
                part_no=row.get("part_no"),
                tooling_code=row.get("kode_tooling"),
                process=row.get("proses"),
                started_at=started_at,
                is_stale=is_stale,
            )
        )

    part_names = sorted(
        {
            row["part_name"]
            for row in current_rows
            if row.get("part_name")
        }
    )
    part_name = (
        part_names[0]
        if len(part_names) == 1
        else "MULTIPLE PARTS"
        if len(part_names) > 1
        else None
    )

    # The selected row is guaranteed to belong to the selected status cluster,
    # so its process is the most defensible process to pair with the single part.
    # When multiple parts exist, a single process would be misleading.
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
    if not valid_current_starts:
        warnings.append("MISSING_START_TIME")

    primary_activity_id = selected_row.get("activity_id")

    return schema.AndonMachineCard(
        machine_id=machine.id,
        machine_name=machine.name,
        tonnage=machine.tonase,
        plant=layout.plant,
        process_group=layout.process_group,
        line=layout.line_name,
        # The current schema requires this field, but ordering is performed with
        # ``layout.machine_sort_key`` during board assembly. A future cleanup can
        # remove this field or populate it after grouping.
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
        toolings=toolings,
        open_activities=open_activities,
        primary_activity_id=primary_activity_id,
        source_activity_ids=_sorted_unique(
            row.get("activity_id") for row in mappings
        ),
        source_start_log_ids=_sorted_unique(
            row.get("start_log_id") for row in mappings
        ),
        has_mixed_status=len(codes) > 1,
        has_multiple_parts=len(part_names) > 1,
        warnings=warnings,
        version_token=(
            str(primary_activity_id) if primary_activity_id is not None else None
        ),
    )


def _build_no_schedule_card(
    machine,
    layout: _Layout,
) -> schema.AndonMachineCard:
    """Create a stable placeholder for a machine with no open activity.

    ``NO SCHEDULE`` is computed, not read from old report rows. This guarantees
    that every master machine appears exactly once on the live board.
    """

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
    """Build the complete plant/process-group Andon response.

    The function performs two database queries regardless of machine count:
    one for machine master data and one for ranked open activities. Remaining
    grouping, conflict resolution, and sorting happen in memory.
    """

    now = datetime.now(timezone.utc)

    # No ORDER BY is needed here because final display order is determined by
    # parsed machine names, not database IDs.
    machines = session.query(models.Mesin).all()
    open_rows = query_latest_open_machine_activities(session)

    rows_by_machine: dict[Any, list[Any]] = defaultdict(list)
    for row in open_rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        rows_by_machine[mapping["mesin_id"]].append(row)

    cards: list[schema.AndonMachineCard] = []
    layouts_by_machine_id: dict[Any, _Layout] = {}

    for machine in machines:
        layout = _layout(machine.name)
        layouts_by_machine_id[machine.id] = layout

        machine_rows = rows_by_machine.get(machine.id, [])
        card = (
            _build_active_card(
                machine=machine,
                rows=machine_rows,
                layout=layout,
                now=now,
            )
            if machine_rows
            else _build_no_schedule_card(machine=machine, layout=layout)
        )
        cards.append(card)

    # Nested defaultdict keeps the grouping pass O(number of machines).
    plant_group_map: dict[
        str,
        dict[str, list[schema.AndonMachineCard]],
    ] = defaultdict(lambda: defaultdict(list))

    for card in cards:
        plant_group_map[card.plant][card.process_group].append(card)

    plants = []
    for plant_name, groups_dict in sorted(
        plant_group_map.items(),
        key=lambda item: PLANT_ORDER.get(item[0], 999),
    ):
        process_groups = []

        for group_name, group_cards in sorted(
            groups_dict.items(),
            key=lambda item: PROCESS_GROUP_ORDER.get(item[0], 999),
        ):
            # Reuse the layout key computed earlier instead of reparsing every
            # machine name during each sort.
            group_cards.sort(
                key=lambda card: layouts_by_machine_id[
                    card.machine_id
                ].machine_sort_key
            )
            process_groups.append(
                schema.AndonProcessGroup(
                    name=group_name,
                    machines=group_cards,
                )
            )

        plants.append(
            schema.AndonPlantGroup(
                name=plant_name,
                display_name=PLANT_DISPLAY_NAME.get(plant_name, plant_name),
                process_groups=process_groups,
            )
        )

    # Count once instead of scanning the full card list separately for every
    # summary field. Any status group not represented by a dedicated summary
    # field (for example blocked, quality, or no_data) is folded into ``other``
    # so TOTAL always reconciles with the visible summary.
    counts = Counter(card.status_group for card in cards)
    explicitly_counted = (
        counts["running"]
        + counts["downtime"]
        + counts["setup"]
        + counts["no_plan"]
    )

    summary = schema.AndonSummary(
        total=len(cards),
        running=counts["running"],
        downtime=counts["downtime"],
        setup=counts["setup"],
        no_plan=counts["no_plan"],
        other=len(cards) - explicitly_counted,
    )

    return schema.AndonBoardResponse(
        generated_at=now,
        refresh_after_seconds=REFRESH_AFTER_SECONDS,
        summary=summary,
        plants=plants,
    )
