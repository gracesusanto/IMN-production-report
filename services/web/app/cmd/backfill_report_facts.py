import argparse
from datetime import datetime
import pytz
import sqlalchemy as sa
from sqlalchemy.orm import joinedload

import app.database as database
import app.model.models as models
import app.service.report as report

UTC = pytz.UTC


def get_finished_activities_in_range_query(session, time_from_utc: datetime, time_to_utc: datetime):
    """
    Base query for finished ActivityMesin rows whose START timestamp is in [time_from_utc, time_to_utc).
    This matches the report query behavior.
    """
    return (
        session.query(models.ActivityMesin)
        .options(
            joinedload(models.ActivityMesin.start_time),
            joinedload(models.ActivityMesin.stop_time),
        )
        .join(models.MesinLog, models.ActivityMesin.start_time_id == models.MesinLog.id)
        .filter(models.MesinLog.timestamp >= time_from_utc)
        .filter(models.MesinLog.timestamp < time_to_utc)
        .filter(models.ActivityMesin.stop_time_id.isnot(None))
        .order_by(models.ActivityMesin.id.asc())
    )


def backfill_range(session, time_from_utc: datetime, time_to_utc: datetime, batch_size: int = 2000):
    """
    Backfill report_activity_fact using the SAME upsert used by process_activity.

    Idempotent:
    - upsert_report_facts_for_stopped_activities uses ON CONFLICT(activity_mesin_id) DO UPDATE
    - safe to rerun for the same range
    """
    q = get_finished_activities_in_range_query(session, time_from_utc, time_to_utc)

    last_id = 0
    total = 0

    while True:
        batch = (
            q.filter(models.ActivityMesin.id > last_id)
            .limit(batch_size)
            .all()
        )
        if not batch:
            break

        last_id = batch[-1].id

        try:
            report.upsert_report_facts_for_stopped_activities(batch, session)
            session.commit()
            total += len(batch)
            print(f"Backfilled up to ActivityMesin.id={last_id} (batch size {len(batch)}, total {total})")
        except Exception:
            session.rollback()
            raise

    return total


def backfill_range_limited(session, time_from_utc: datetime, time_to_utc: datetime, limit: int = 1000):
    """
    Backfill at most `limit` finished rows in range.
    Useful for on-demand lazy backfill from generate_report.
    """
    batch = (
        get_finished_activities_in_range_query(session, time_from_utc, time_to_utc)
        .limit(limit)
        .all()
    )

    if not batch:
        return 0

    try:
        report.upsert_report_facts_for_stopped_activities(batch, session)
        session.commit()
        return len(batch)
    except Exception:
        session.rollback()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="dt_from", required=True, help="UTC start, e.g. 2026-01-01 or 2026-01-01T00:00:00+00:00")
    parser.add_argument("--to", dest="dt_to", required=True, help="UTC end, e.g. 2026-02-01 or 2026-02-01T00:00:00+00:00")
    parser.add_argument("--batch", dest="batch", type=int, default=2000)
    args = parser.parse_args()

    time_from = datetime.fromisoformat(args.dt_from)
    time_to = datetime.fromisoformat(args.dt_to)

    if time_from.tzinfo is None:
        time_from = UTC.localize(time_from)
    if time_to.tzinfo is None:
        time_to = UTC.localize(time_to)

    engine = database.get_engine()
    Session = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with Session() as session:
        total = backfill_range(session, time_from, time_to, batch_size=args.batch)
        print(f"Done. Total backfilled: {total}")

# python -m app.cmd.backfill_report_facts --from 2026-01-01 --to 2026-02-01
# python -m app.cmd.backfill_report_facts --from 2026-01-01 --to 2026-02-01 --batch 500
# docker compose exec app python -m app.cmd.backfill_report_facts --from 2026-01-01 --to 2026-02-01
if __name__ == "__main__":
    main()
