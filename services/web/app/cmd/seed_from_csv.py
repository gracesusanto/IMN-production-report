"""
Seed the database from the production CSV dump in data/seed_csv/.

Master data (mesin, operator, tooling) is derived from the transaction CSVs:
  - Mesin    — unique mesin_id values from MesinLog.csv
  - Operator — unique operator_id values from MesinLog.csv (name/nik from ReportActivityFact)
  - Tooling  — unique tooling_id values from ActivityMesin.csv (details from ReportActivityFact)

Transaction data:
  - MesinLog, ActivityMesin, ReportActivityFact

All timestamps are shifted forward so the latest MesinLog timestamp lands on today (UTC).
Existing PKs are skipped — safe to call multiple times.
"""

import csv
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import app.model.models as models

CSV_DIR = os.path.join(os.path.dirname(__file__), "../../data/seed_csv")

MESIN_LOG_CSV      = os.path.join(CSV_DIR, "MesinLog.csv")
ACTIVITY_MESIN_CSV = os.path.join(CSV_DIR, "ActivityMesin.csv")
FACT_CSV           = os.path.join(CSV_DIR, "ReportActivityFact.csv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(val: str) -> str:
    """Strip Excel =\"...\" wrapper and surrounding whitespace."""
    v = val.strip()
    v = re.sub(r'^"?=""?(.*?)""?"?$', r'\1', v)
    return v.strip()


def _parse_ts(val: str):
    """Parse a timestamptz string → aware datetime (UTC). Returns None if empty/invalid."""
    v = _clean(val)
    if not v:
        return None
    v = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', v)
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(v, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _parse_date(val: str, delta: timedelta = timedelta(0)):
    v = _clean(val)
    if not v:
        return None
    try:
        d = datetime.strptime(v, "%Y-%m-%d").date()
        return d + delta
    except ValueError:
        return None


def _read_csv(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        rows = list(reader)
    return rows[0], rows[1:]


def _shift(ts, delta: timedelta):
    if ts is None:
        return None
    return ts + delta


def _int(v, default=0):
    try:
        return int(_clean(v) or default)
    except (ValueError, TypeError):
        return default


def _dec(v):
    try:
        return Decimal(_clean(v) or "0")
    except Exception:
        return Decimal("0")


def _d(row, idx, default=None):
    v = _clean(row[idx]) if len(row) > idx else ""
    return v if v else default


# ---------------------------------------------------------------------------
# Compute shift delta
# ---------------------------------------------------------------------------

def _compute_shift_delta() -> timedelta:
    """Shift so the latest MesinLog.timestamp lands on today (UTC date)."""
    _, rows = _read_csv(MESIN_LOG_CSV)
    latest = None
    for row in rows:
        if len(row) <= 6:
            continue
        ts = _parse_ts(row[6])
        if ts and (latest is None or ts > latest):
            latest = ts
    if latest is None:
        return timedelta(0)
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    latest_date = latest.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_utc - latest_date


# ---------------------------------------------------------------------------
# Seed Mesin — from unique mesin_id in MesinLog
# ---------------------------------------------------------------------------

def _seed_mesin(session):
    _, rows = _read_csv(MESIN_LOG_CSV)

    existing = {m.id for m in session.query(models.Mesin.id).all()}
    new = {}
    for row in rows:
        if len(row) < 2:
            continue
        mesin_id = _clean(row[1])
        if not mesin_id or mesin_id in existing or mesin_id in new:
            continue
        name = mesin_id[3:] if mesin_id.startswith("MC-") else mesin_id
        new[mesin_id] = models.Mesin(id=mesin_id, name=name, tonase=0)

    session.bulk_save_objects(list(new.values()))
    session.flush()
    return len(new)


# ---------------------------------------------------------------------------
# Seed Operator — from unique operator_id in MesinLog, details from Fact
# ---------------------------------------------------------------------------

def _seed_operator(session):
    # Build name/nik lookup from ReportActivityFact (more complete than deriving from ID)
    _, fact_rows = _read_csv(FACT_CSV)
    # cols: 5=operator_id, 15=operator_name, 16=operator_nik
    op_details = {}
    for row in fact_rows:
        op_id = _d(row, 5)
        if not op_id or op_id in op_details:
            continue
        name = _d(row, 15) or ""
        nik  = _d(row, 16) or ""
        op_details[op_id] = (name, nik)

    _, log_rows = _read_csv(MESIN_LOG_CSV)
    existing = {o.id for o in session.query(models.Operator.id).all()}
    new = {}
    for row in log_rows:
        if len(row) < 3:
            continue
        op_id = _clean(row[2])
        if not op_id or op_id in existing or op_id in new:
            continue
        name, nik = op_details.get(op_id, ("", ""))
        if not name:
            name = op_id[3:].replace("-", " ").title() if op_id.startswith("OP-") else op_id
        new[op_id] = models.Operator(id=op_id, name=name, nik=nik)

    session.bulk_save_objects(list(new.values()))
    session.flush()
    return len(new)


# ---------------------------------------------------------------------------
# Seed Tooling — from unique tooling_id in ActivityMesin, details from Fact
# ---------------------------------------------------------------------------

def _seed_tooling(session):
    # Build tooling detail lookup from ReportActivityFact
    # cols: 7=tooling_id, 17=kode_tooling, 18=common_tooling_name, 19=part_no,
    #       20=part_name, 21=proses, 22=target_std_jam
    _, fact_rows = _read_csv(FACT_CSV)
    tl_details = {}
    for row in fact_rows:
        tl_id = _d(row, 7)
        if not tl_id or tl_id in tl_details:
            continue
        tl_details[tl_id] = {
            "kode_tooling":       _d(row, 17) or "",
            "common_tooling_name": _d(row, 18) or "",
            "part_no":            _d(row, 19) or "",
            "part_name":          _d(row, 20) or "",
            "proses":             _d(row, 21) or "",
            "std_jam":            _int(_d(row, 22), 0),
        }

    # Collect tooling IDs from both MesinLog (col 3) and ActivityMesin (col 3)
    all_tl_ids = set()
    for path, col in ((MESIN_LOG_CSV, 3), (ACTIVITY_MESIN_CSV, 3)):
        _, rows = _read_csv(path)
        for row in rows:
            tl_id = _clean(row[col]) if len(row) > col else ""
            if tl_id:
                all_tl_ids.add(tl_id)

    existing = {t.id for t in session.query(models.Tooling.id).all()}
    new = {}
    for tl_id in all_tl_ids:
        if tl_id in existing or tl_id in new:
            continue
        d = tl_details.get(tl_id, {})
        new[tl_id] = models.Tooling(
            id=tl_id,
            customer="",
            part_no=d.get("part_no", ""),
            part_name=d.get("part_name", ""),
            child_part_name="",
            kode_tooling=d.get("kode_tooling", ""),
            common_tooling_name=d.get("common_tooling_name", ""),
            proses=d.get("proses", ""),
            std_jam=d.get("std_jam", 0),
        )

    session.bulk_save_objects(list(new.values()))
    session.flush()
    return len(new)


# ---------------------------------------------------------------------------
# Seed MesinLog
# ---------------------------------------------------------------------------

def _seed_mesin_log(session, delta: timedelta):
    _, rows = _read_csv(MESIN_LOG_CSV)
    # id;mesin_id;operator_id;tooling_id;curr_category;next_category;timestamp;time_created;time_updated

    existing = {r[0] for r in session.query(models.MesinLog.id).all()}

    batch = []
    for row in rows:
        if len(row) < 7:
            continue
        row_id = _clean(row[0])
        if not row_id or not row_id.isdigit() or int(row_id) in existing:
            continue

        op_id = _clean(row[2])
        ts    = _shift(_parse_ts(row[6]), delta)
        if not op_id or ts is None:
            continue

        tc = _shift(_parse_ts(row[7]) if len(row) > 7 else None, delta) or ts
        tu = _shift(_parse_ts(row[8]) if len(row) > 8 else None, delta)

        batch.append(models.MesinLog(
            id=int(row_id),
            mesin_id=_clean(row[1]) or None,
            operator_id=op_id,
            tooling_id=_clean(row[3]) or None,
            curr_category=_clean(row[4]) or None,
            next_category=_clean(row[5]) or None,
            timestamp=ts,
            time_created=tc,
            time_updated=tu,
        ))

    session.bulk_save_objects(batch)
    session.flush()
    return len(batch)


# ---------------------------------------------------------------------------
# Seed ActivityMesin
# ---------------------------------------------------------------------------

def _seed_activity_mesin(session, delta: timedelta):
    _, rows = _read_csv(ACTIVITY_MESIN_CSV)
    # id;mesin_id;operator_id;tooling_id;category;start_time_id;stop_time_id;
    # output;reject;rework;coil_no;lot_no;pack_no;keterangan;time_created;time_updated

    # Build set of valid MesinLog IDs to guard against FK violations from partial CSV exports
    valid_log_ids = {r[0] for r in session.query(models.MesinLog.id).all()}

    existing = {r[0] for r in session.query(models.ActivityMesin.id).all()}

    batch = []
    for row in rows:
        if len(row) < 8:
            continue
        row_id = _clean(row[0])
        if not row_id or not row_id.isdigit() or int(row_id) in existing:
            continue

        op_id         = _clean(row[2])
        start_time_id = _clean(row[5])
        if not op_id or not start_time_id or not start_time_id.isdigit():
            continue
        if int(start_time_id) not in valid_log_ids:
            continue

        stop_raw = _clean(row[6])
        stop_time_id = stop_raw if (stop_raw and stop_raw.isdigit() and int(stop_raw) in valid_log_ids) else None
        tc = _shift(_parse_ts(_d(row, 14)), delta)
        tu = _shift(_parse_ts(_d(row, 15, "")), delta)

        batch.append(models.ActivityMesin(
            id=int(row_id),
            mesin_id=_clean(row[1]) or None,
            operator_id=op_id,
            tooling_id=_clean(row[3]) or None,
            category=_clean(row[4]) or "U : Utility",
            start_time_id=int(start_time_id),
            stop_time_id=int(stop_time_id) if stop_time_id else None,
            output=_int(_d(row, 7)),
            reject=_int(_d(row, 8)),
            rework=_int(_d(row, 9)),
            coil_no=_d(row, 10),
            lot_no=_d(row, 11),
            pack_no=_d(row, 12),
            keterangan=_d(row, 13),
            time_created=tc,
            time_updated=tu,
        ))

    session.bulk_save_objects(batch)
    session.flush()
    return len(batch)


# ---------------------------------------------------------------------------
# Seed ReportActivityFact
# ---------------------------------------------------------------------------

def _seed_report_facts(session, delta: timedelta):
    _, rows = _read_csv(FACT_CSV)

    existing = {r[0] for r in session.query(models.ReportActivityFact.id).all()}

    batch = []
    for row in rows:
        if len(row) < 24:
            continue
        row_id = _clean(row[0])
        if not row_id or not row_id.isdigit() or int(row_id) in existing:
            continue

        start_ts = _shift(_parse_ts(row[2]), delta)
        stop_ts  = _shift(_parse_ts(row[3]), delta)
        if start_ts is None or stop_ts is None:
            continue

        tanggal = _parse_date(_d(row, 23, ""), delta)
        if tanggal is None:
            tanggal = (start_ts + timedelta(hours=7)).date()

        tc = _shift(_parse_ts(_d(row, 31, "")), delta)
        tu = _shift(_parse_ts(_d(row, 32, "")), delta)

        batch.append(models.ReportActivityFact(
            id=int(row_id),
            activity_mesin_id=_int(_d(row, 1)),
            start_ts_utc=start_ts,
            stop_ts_utc=stop_ts,
            duration_sec=_int(_d(row, 4)),
            operator_id=_d(row, 5, ""),
            mesin_id=_d(row, 6),
            tooling_id=_d(row, 7),
            category_full=_d(row, 8, ""),
            category_code=(_d(row, 9, "") or "")[:2],
            qty=_int(_d(row, 10)),
            reject=_int(_d(row, 11)),
            rework=_int(_d(row, 12)),
            keterangan_final=_d(row, 13, ""),
            mc_name=_d(row, 14),
            operator_name=_d(row, 15, ""),
            operator_nik=_d(row, 16, ""),
            kode_tooling=_d(row, 17),
            common_tooling_name=_d(row, 18),
            part_no=_d(row, 19),
            part_name=_d(row, 20),
            proses=_d(row, 21),
            target_std_jam=_int(_d(row, 22)) if _d(row, 22) else None,
            tanggal_local=tanggal,
            shift=_int(_d(row, 24, "1")),
            plant=_d(row, 25),
            awal_hhmm=_d(row, 26),
            akhir_hhmm=_d(row, 27),
            productivity_pct=_dec(_d(row, 28)),
            reject_ratio_pct=_dec(_d(row, 29)),
            rework_ratio_pct=_dec(_d(row, 30)),
            time_created=tc,
            time_updated=tu,
        ))

    session.bulk_save_objects(batch)
    session.flush()
    return len(batch)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def seed_from_csv(session):
    """
    Full seed: mesin → operator → tooling → mesin_log → activity_mesin → report_activity_fact.
    Timestamps shifted so latest MesinLog record lands on today.
    Safe to call multiple times — existing PKs are skipped.
    """
    for path in (MESIN_LOG_CSV, ACTIVITY_MESIN_CSV, FACT_CSV):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Seed CSV not found: {path}")

    print("Computing time shift...")
    delta = _compute_shift_delta()
    print(f"  Shifting all timestamps by {delta.days} days")

    print("Seeding Mesin...")
    n_mesin = _seed_mesin(session)
    print(f"  inserted {n_mesin}")

    print("Seeding Operator...")
    n_op = _seed_operator(session)
    print(f"  inserted {n_op}")

    print("Seeding Tooling...")
    n_tl = _seed_tooling(session)
    print(f"  inserted {n_tl}")

    print("Seeding MesinLog...")
    n_log = _seed_mesin_log(session, delta)
    print(f"  inserted {n_log}")

    print("Seeding ActivityMesin...")
    n_act = _seed_activity_mesin(session, delta)
    print(f"  inserted {n_act}")

    print("Seeding ReportActivityFact...")
    n_fact = _seed_report_facts(session, delta)
    print(f"  inserted {n_fact}")

    session.commit()
    print("Done.")

    return {
        "shift_days": delta.days,
        "inserted": {
            "mesin": n_mesin,
            "operator": n_op,
            "tooling": n_tl,
            "mesin_log": n_log,
            "activity_mesin": n_act,
            "report_activity_fact": n_fact,
        },
    }
