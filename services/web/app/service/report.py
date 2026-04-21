from sqlalchemy.dialects.postgresql import insert as pg_insert
import app.model.models as models
import app.service.utils as utils

def upsert_report_facts_for_stopped_activities(stopped_activities: list[models.ActivityMesin], session):
    """
    Creates/updates report_activity_fact rows for each finished ActivityMesin.
    Assumes each activity in stopped_activities now has stop_time_id set.
    """
    for a in stopped_activities:
        if a.stop_time_id is None:
            continue  # not finished

        # load start/stop timestamps (UTC in DB)
        start_ts = a.start_time.timestamp
        stop_ts = a.stop_time.timestamp
        if not start_ts or not stop_ts:
            continue

        duration_sec = int((stop_ts - start_ts).total_seconds())
        if duration_sec < 0:
            # protect against bad data / clock issues
            duration_sec = 0

        # convert to jakarta for derived fields
        start_jkt = start_ts.astimezone(utils.JAKARTA_TZ)
        stop_jkt = stop_ts.astimezone(utils.JAKARTA_TZ)

        tanggal_local = start_jkt.date()
        shift = utils.calculate_shift_from_datetime_jakarta(start_jkt)

        category_full = a.category or ""
        category_code = (category_full[:2] or "").upper()

        # denormalize dimensions
        op = session.query(models.Operator).filter(models.Operator.id == a.operator_id).first()
        mc = session.query(models.Mesin).filter(models.Mesin.id == a.mesin_id).first() if a.mesin_id else None
        tl = session.query(models.Tooling).filter(models.Tooling.id == a.tooling_id).first() if a.tooling_id else None

        keterangan_final = utils.combine_keterangan_final(a.keterangan, a.coil_no, a.lot_no, a.pack_no)

        target_std_jam = tl.std_jam if tl else None

        productivity_pct = utils.calc_productivity_pct(category_full, a.output or 0, duration_sec, target_std_jam)
        reject_ratio_pct = utils.calc_ratio_pct(a.output or 0, a.reject or 0, a.rework or 0, "reject")
        rework_ratio_pct = utils.calc_ratio_pct(a.output or 0, a.reject or 0, a.rework or 0, "rework")

        mc_name = mc.name if mc else None
        plant = None
        if mc_name and len(mc_name) > 0:
            plant = mc_name[-1]  # matches your current Plant logic

        row = dict(
            activity_mesin_id=a.id,
            start_ts_utc=start_ts,
            stop_ts_utc=stop_ts,
            duration_sec=duration_sec,

            operator_id=a.operator_id,
            mesin_id=a.mesin_id,
            tooling_id=a.tooling_id,

            category_full=category_full,
            category_code=category_code,

            qty=int(a.output or 0),
            reject=int(a.reject or 0),
            rework=int(a.rework or 0),

            keterangan_final=keterangan_final,

            mc_name=mc_name,
            operator_name=(op.name if op else ""),
            operator_nik=(op.nik if op else ""),

            kode_tooling=(tl.kode_tooling if tl else None),
            common_tooling_name=(tl.common_tooling_name if tl else None),
            part_no=(tl.part_no if tl else None),
            part_name=(tl.part_name if tl else None),
            proses=(tl.proses if tl else None),
            target_std_jam=target_std_jam,

            tanggal_local=tanggal_local,
            shift=shift,

            plant=plant,
            awal_hhmm=utils.format_time_for_limax_hhmm(start_jkt),
            akhir_hhmm=utils.format_time_for_limax_hhmm(stop_jkt),

            productivity_pct=productivity_pct,
            reject_ratio_pct=reject_ratio_pct,
            rework_ratio_pct=rework_ratio_pct,
        )

        stmt = pg_insert(models.ReportActivityFact).values(**row)

        # If already exists (backfill or re-run), update mutable fields
        update_cols = row.copy()
        update_cols.pop("activity_mesin_id", None)  # keep unique key stable

        stmt = stmt.on_conflict_do_update(
            index_elements=[models.ReportActivityFact.activity_mesin_id],
            set_=update_cols,
        )

        session.execute(stmt)
