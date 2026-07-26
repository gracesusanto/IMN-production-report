#!/usr/bin/env python3
"""
Clean invalid machine records from inside the backend Docker container.

Valid machine IDs end exactly in "-P1" or "-P2" (case-insensitive).

Safety:
- Dry run by default.
- --execute deletes only machines with no related history.
- --execute --purge-history deletes each invalid machine AND its related:
    * report_activity_fact rows
    * activity_mesin rows
    * mesin_log rows
  This is destructive and cannot be undone without a backup.

Recommended location:
    /app/app/cmd/cleanup_mesin.py

Examples:
    python -m app.cmd.cleanup_mesin
    python -m app.cmd.cleanup_mesin --execute
    python -m app.cmd.cleanup_mesin --execute --purge-history
    python -m app.cmd.cleanup_mesin --execute --purge-history --yes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import app.model.models as models


VALID_SUFFIX = re.compile(r"-P(?:1|2)$", re.IGNORECASE)

EXCLUDED_MACHINE_IDS = {
    "MC-CHECKLOAD",
}

DEFAULT_MAX_LOGS = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Remove machines whose ID does not end exactly in "-P1" or "-P2". '
            "Dry run is the default."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform deletion. Without this flag, only show a preview.",
    )
    parser.add_argument(
        "--purge-history",
        action="store_true",
        help=(
            "Also delete related report_activity_fact, activity_mesin, and "
            "mesin_log history. Requires --execute."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation.",
    )
    parser.add_argument(
        "--max-logs",
        type=int,
        default=DEFAULT_MAX_LOGS,
        help=(
            "Do not delete a machine when its mesin_log count is greater "
            f"than this value. Default: {DEFAULT_MAX_LOGS}"
        ),
    )
    parser.add_argument(
        "--log-dir",
        default="/tmp",
        help="Directory for the JSON result file. Default: /tmp",
    )
    return parser.parse_args()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set inside the container.")

    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]

    return database_url


def create_session():
    engine = create_engine(get_database_url(), pool_pre_ping=True)
    factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
    )
    return engine, factory()


def text_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def is_valid_machine_id(machine_id: Any) -> bool:
    return VALID_SUFFIX.search(text_value(machine_id)) is not None


def make_log_path(log_dir: str) -> Path:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return directory / f"cleanup_mesin_results_{timestamp}.json"


def write_log(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def get_related_records(session, machine) -> dict[str, Any]:
    machine_id = text_value(machine.id)
    machine_name = text_value(getattr(machine, "name", ""))

    logs = (
        session.query(models.MesinLog)
        .filter(models.MesinLog.mesin_id == machine_id)
        .all()
    )
    log_ids = [row.id for row in logs]

    activity_conditions = [models.ActivityMesin.mesin_id == machine_id]
    if log_ids:
        activity_conditions.extend(
            [
                models.ActivityMesin.start_time_id.in_(log_ids),
                models.ActivityMesin.stop_time_id.in_(log_ids),
            ]
        )

    activities = (
        session.query(models.ActivityMesin)
        .filter(or_(*activity_conditions))
        .all()
    )
    activity_ids = [row.id for row in activities]

    facts = []
    fact_model = getattr(models, "ReportActivityFact", None)
    if fact_model is not None:
        fact_conditions = []

        if activity_ids and hasattr(fact_model, "activity_mesin_id"):
            fact_conditions.append(
                fact_model.activity_mesin_id.in_(activity_ids)
            )

        # The fact table stores the display machine name in the current
        # reporting implementation. Include it so stale report rows do not
        # remain after a destructive purge.
        if machine_name and hasattr(fact_model, "mc_name"):
            fact_conditions.append(fact_model.mc_name == machine_name)

        if fact_conditions:
            facts = (
                session.query(fact_model)
                .filter(or_(*fact_conditions))
                .all()
            )

    return {
        "logs": logs,
        "log_ids": log_ids,
        "activities": activities,
        "activity_ids": activity_ids,
        "facts": facts,
    }


def preview_item(session, machine, max_logs: int) -> dict[str, Any]:
    related = get_related_records(session, machine)
    machine_id = text_value(machine.id)
    log_count = len(related["logs"])

    skip_reasons: list[str] = []

    if machine_id.upper() in EXCLUDED_MACHINE_IDS:
        skip_reasons.append("explicitly excluded")

    if log_count > max_logs:
        skip_reasons.append(
            f"mesin_log count {log_count} exceeds limit {max_logs}"
        )

    return {
        "id": machine_id,
        "name": text_value(getattr(machine, "name", "")),
        "mesin_log_count": log_count,
        "activity_mesin_count": len(related["activities"]),
        "report_activity_fact_count": len(related["facts"]),
        "has_history": bool(
            related["logs"]
            or related["activities"]
            or related["facts"]
        ),
        "eligible": not skip_reasons,
        "skip_reasons": skip_reasons,
    }


def purge_machine(session, machine_id: str) -> dict[str, int]:
    """
    Purge one machine and its known dependent history in dependency order.

    Everything is committed as one transaction. Any failure rolls back the
    entire purge for this machine.
    """
    machine = (
        session.query(models.Mesin)
        .filter(models.Mesin.id == machine_id)
        .one_or_none()
    )
    if machine is None:
        raise RuntimeError("Machine no longer exists.")

    related = get_related_records(session, machine)

    counts = {
        "report_activity_fact": len(related["facts"]),
        "activity_mesin": len(related["activities"]),
        "mesin_log": len(related["logs"]),
        "mesin": 1,
    }

    # Delete deepest dependants first.
    for fact in related["facts"]:
        session.delete(fact)

    for activity in related["activities"]:
        session.delete(activity)

    # Flush before deleting logs so activity start/stop foreign keys are gone.
    session.flush()

    for log in related["logs"]:
        session.delete(log)

    session.flush()
    session.delete(machine)
    session.commit()

    return counts


def delete_unreferenced_machine(session, machine_id: str) -> None:
    machine = (
        session.query(models.Mesin)
        .filter(models.Mesin.id == machine_id)
        .one_or_none()
    )
    if machine is None:
        raise RuntimeError("Machine no longer exists.")

    related = get_related_records(session, machine)
    if related["logs"] or related["activities"] or related["facts"]:
        raise RuntimeError(
            "Machine has related history. Use --purge-history only if that "
            "history should also be permanently deleted."
        )

    session.delete(machine)
    session.commit()


def main() -> int:
    args = parse_args()

    if args.purge_history and not args.execute:
        print(
            "ERROR: --purge-history requires --execute.",
            file=sys.stderr,
        )
        return 2

    log_path = make_log_path(args.log_dir)

    try:
        engine, session = create_session()
    except Exception as exc:
        print(f"FATAL: could not connect to database: {exc}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dry_run": not args.execute,
        "purge_history": args.purge_history,
        "candidates": [],
        "deleted": [],
        "failed": [],
    }

    try:
        machines = session.query(models.Mesin).order_by(models.Mesin.id).all()
        invalid_machines = [
            machine
            for machine in machines
            if not is_valid_machine_id(machine.id)
        ]

        candidates = [
            preview_item(session, machine, args.max_logs)
            for machine in invalid_machines
        ]
        eligible_candidates = [
            item for item in candidates if item["eligible"]
        ]
        skipped_candidates = [
            item for item in candidates if not item["eligible"]
        ]

        result["machine_count"] = len(machines)
        result["candidate_count"] = len(candidates)
        result["eligible_count"] = len(eligible_candidates)
        result["skipped_count"] = len(skipped_candidates)
        result["max_logs"] = args.max_logs
        result["excluded_machine_ids"] = sorted(EXCLUDED_MACHINE_IDS)
        result["candidates"] = candidates
        result["eligible_candidates"] = eligible_candidates
        result["skipped_candidates"] = skipped_candidates

        print(f"Machines in database:  {len(machines)}")
        print(f"Invalid candidates:    {len(candidates)}")
        print(f"Eligible candidates:   {len(eligible_candidates)}")
        print(f"Skipped candidates:    {len(skipped_candidates)}")
        print(f"Maximum allowed logs:  {args.max_logs}")
        print("Explicit exclusions:   " + ", ".join(sorted(EXCLUDED_MACHINE_IDS)))
        print("Valid ID suffixes:     -P1, -P2")
        print()

        if eligible_candidates:
            print("ELIGIBLE:")
            for item in eligible_candidates:
                print(
                    f'  {item["id"]:<28} '
                    f'name={item["name"]!r} '
                    f'logs={item["mesin_log_count"]} '
                    f'activities={item["activity_mesin_count"]} '
                    f'facts={item["report_activity_fact_count"]}'
                )

        if skipped_candidates:
            print()
            print("SKIPPED:")
            for item in skipped_candidates:
                reasons = "; ".join(item["skip_reasons"])
                print(
                    f'  {item["id"]:<28} '
                    f'name={item["name"]!r} '
                    f'logs={item["mesin_log_count"]} '
                    f'reason={reasons}'
                )

        if not args.execute:
            write_log(log_path, result)
            print()
            print("DRY RUN ONLY: nothing was deleted.")
            print(f"Result file: {log_path}")
            return 0

        if not eligible_candidates:
            write_log(log_path, result)
            print("Nothing is eligible for deletion.")
            return 0

        if args.purge_history:
            warning = (
                f"PURGE {len(eligible_candidates)} MACHINES AND HISTORY"
            )
        else:
            deletable_count = sum(
                1
                for item in eligible_candidates
                if not item["has_history"]
            )
            warning = f"DELETE {deletable_count}"

        if not args.yes:
            print()
            print("WARNING: this operation is permanent.")
            if args.purge_history:
                print(
                    "Related machine logs, activities, and report facts "
                    "will also be deleted."
                )
            entered = input(f'Type "{warning}" to continue: ').strip()
            if entered != warning:
                result["cancelled"] = True
                write_log(log_path, result)
                print("Cancelled. Nothing was deleted.")
                return 2

        for item in eligible_candidates:
            machine_id = item["id"]

            try:
                if args.purge_history:
                    deleted_counts = purge_machine(session, machine_id)
                    result["deleted"].append(
                        {
                            **item,
                            "deleted_counts": deleted_counts,
                        }
                    )
                    print(
                        f"PURGED:  {machine_id} "
                        f"(facts={deleted_counts['report_activity_fact']}, "
                        f"activities={deleted_counts['activity_mesin']}, "
                        f"logs={deleted_counts['mesin_log']})"
                    )
                else:
                    if item["has_history"]:
                        print(
                            f"SKIPPED: {machine_id} -> has history; "
                            "use --purge-history to remove it"
                        )
                        continue

                    delete_unreferenced_machine(session, machine_id)
                    result["deleted"].append(item)
                    print(f"DELETED: {machine_id}")

            except (SQLAlchemyError, RuntimeError, Exception) as exc:
                session.rollback()
                error = str(getattr(exc, "orig", exc))
                result["failed"].append(
                    {
                        **item,
                        "error": error,
                    }
                )
                print(
                    f"FAILED:  {machine_id} -> {error}",
                    file=sys.stderr,
                )

        result["dry_run"] = False
        result["deleted_count"] = len(result["deleted"])
        result["failed_count"] = len(result["failed"])
        write_log(log_path, result)

        print()
        print(f'Deleted/purged: {result["deleted_count"]}')
        print(f'Failed:         {result["failed_count"]}')
        print(f"Result file:    {log_path}")

        return 1 if result["failed"] else 0

    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
