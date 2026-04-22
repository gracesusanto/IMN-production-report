"""
Test report summary functionality - updated with timezone fixes and additional test coverage
"""
import pandas as pd
import pytest

from app.service import report_summary


def _patch_shift_config(monkeypatch):
    monkeypatch.setattr(
        report_summary.ru,
        "WORKING_SHIFT_JSON",
        {
            "Weekday": {
                "start": {"1": 7, "2": 15, "3": 23},
                "duration": 8,
            },
            "Saturday": {
                "start": {"1": 7, "2": 15, "3": 23},
                "duration": 8,
            },
        },
    )


def _utc(ts: str) -> pd.Timestamp:
    """Helper to create UTC timestamps for tests"""
    return pd.Timestamp(ts, tz="UTC")


def test_split_rows_by_shift_preserves_totals(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-A1",
                "Operator": "A",
                "Part No": "PAU-1",
                "Part Name": "Part One",
                "Proses": "6/6",
                "Desc": "U : Utility",
                "Target": 100,
                # UTC 07:30 -> 08:30 = local 14:30 -> 15:30, crosses shift 1 -> 2
                "_StartTs": _utc("2026-03-02 07:30:00"),
                "_StopTs": _utc("2026-03-02 08:30:00"),
                "Qty": 100,
                "Reject": 10,
                "Rework": 4,
                "Keterangan": "cross shift",
            }
        ]
    )

    split_df = report_summary.split_rows_by_shift(df)

    assert len(split_df) == 2
    assert split_df["Shift"].tolist() == ["1", "2"]
    assert split_df["Qty"].sum() == 100
    assert split_df["Reject"].sum() == 10
    assert split_df["Rework"].sum() == 4
    assert split_df["_DurationMinutes"].sum() == 60.0


def test_machine_summary_merges_same_machine_part_proses_in_same_shift(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-A1",
                "Operator": "A",
                "Part No": "PAU-1",
                "Part Name": "Part One",
                "Proses": "6/6",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 00:00:00"),  # local 07:00
                "_StopTs": _utc("2026-03-02 01:00:00"),   # local 08:00
                "Qty": 100,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "run 1",
            },
            {
                "MC": "P1-A1",
                "Operator": "B",
                "Part No": "PAU-1",
                "Part Name": "Part One",
                "Proses": "6/6",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 03:00:00"),  # local 10:00
                "_StopTs": _utc("2026-03-02 04:00:00"),   # local 11:00
                "Qty": 110,
                "Reject": 5,
                "Rework": 0,
                "Keterangan": "run 2",
            },
            {
                "MC": "P1-A1",
                "Operator": "B",
                "Part No": "PAU-1",
                "Part Name": "Part One",
                "Proses": "6/6",
                "Desc": "TP : Tooling Problem",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 04:00:00"),  # local 11:00
                "_StopTs": _utc("2026-03-02 04:30:00"),   # local 11:30
                "Qty": 0,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "tooling",
            },
        ]
    )

    summary = report_summary.summarize_dashboard_df(df, "mesin")

    assert len(summary) == 1
    row = summary.iloc[0]

    assert row["MC"] == "P1-A1"
    assert row["Part No"] == "PAU-1"
    assert row["Proses"] == "6/6"
    assert row["Qty"] == 210
    assert row["Reject"] == 5
    assert row["Plan"] == "02:30"
    assert row["Utility"] == "02:00"
    assert row["TP"] == "00:30"
    assert row["OTR"] == "80%"


def test_operator_summary_keeps_different_operators_separate(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-A1",
                "Operator": "A",
                "Part No": "PAU-1",
                "Part Name": "Part One",
                "Proses": "6/6",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 100,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "op A",
            },
            {
                "MC": "P1-A1",
                "Operator": "B",
                "Part No": "PAU-1",
                "Part Name": "Part One",
                "Proses": "6/6",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 01:00:00"),
                "_StopTs": _utc("2026-03-02 02:00:00"),
                "Qty": 100,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "op B",
            },
        ]
    )

    machine_summary = report_summary.summarize_dashboard_df(df, "mesin")
    operator_summary = report_summary.summarize_dashboard_df(df, "operator")

    assert len(machine_summary) == 1
    assert len(operator_summary) == 2
    assert sorted(operator_summary["Operator"].tolist()) == ["A", "B"]


def test_same_operator_same_machine_part_same_shift_merges(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-A2",
                "Operator": "A",
                "Part No": "PAU-2",
                "Part Name": "Part Two",
                "Proses": "3/4",
                "Desc": "U : Utility",
                "Target": 80,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 00:30:00"),
                "Qty": 40,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "first",
            },
            {
                "MC": "P1-A2",
                "Operator": "A",
                "Part No": "PAU-2",
                "Part Name": "Part Two",
                "Proses": "3/4",
                "Desc": "U : Utility",
                "Target": 80,
                "_StartTs": _utc("2026-03-02 02:00:00"),
                "_StopTs": _utc("2026-03-02 02:30:00"),
                "Qty": 38,
                "Reject": 2,
                "Rework": 0,
                "Keterangan": "second",
            },
        ]
    )

    summary = report_summary.summarize_dashboard_df(df, "operator")

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["Operator"] == "A"
    assert row["MC"] == "P1-A2"
    assert row["Qty"] == 78
    assert row["Reject"] == 2
    assert row["Plan"] == "01:00"
    assert row["Utility"] == "01:00"


def test_cross_shift_split_allocates_qty_reject_rework_proportionally(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-B1",
                "Operator": "C",
                "Part No": "PAU-3",
                "Part Name": "Part Three",
                "Proses": "2/3",
                "Desc": "U : Utility",
                "Target": 50,
                # UTC 07:00 -> 09:00 = local 14:00 -> 16:00, crosses shift 1 -> 2 equally
                "_StartTs": _utc("2026-03-02 07:00:00"),
                "_StopTs": _utc("2026-03-02 09:00:00"),
                "Qty": 120,
                "Reject": 6,
                "Rework": 4,
                "Keterangan": "cross shift activity",
            }
        ]
    )

    split_df = report_summary.split_rows_by_shift(df)

    assert len(split_df) == 2
    assert split_df["Qty"].sum() == 120
    assert split_df["Reject"].sum() == 6
    assert split_df["Rework"].sum() == 4

    shift_1_row = split_df[split_df["Shift"] == "1"].iloc[0]
    shift_2_row = split_df[split_df["Shift"] == "2"].iloc[0]

    assert shift_1_row["Qty"] == 60
    assert shift_2_row["Qty"] == 60
    assert shift_1_row["Reject"] == 3
    assert shift_2_row["Reject"] == 3
    assert shift_1_row["Rework"] == 2
    assert shift_2_row["Rework"] == 2


def test_proses_included_in_grouping_when_present(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-C1",
                "Operator": "D",
                "Part No": "PAU-4",
                "Part Name": "Part Four",
                "Proses": "1/2",
                "Desc": "U : Utility",
                "Target": 60,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 60,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "process 1/2",
            },
            {
                "MC": "P1-C1",
                "Operator": "D",
                "Part No": "PAU-4",
                "Part Name": "Part Four",
                "Proses": "2/2",
                "Desc": "U : Utility",
                "Target": 60,
                "_StartTs": _utc("2026-03-02 01:00:00"),
                "_StopTs": _utc("2026-03-02 02:00:00"),
                "Qty": 55,
                "Reject": 2,
                "Rework": 0,
                "Keterangan": "process 2/2",
            },
        ]
    )

    machine_summary = report_summary.summarize_dashboard_df(df, "mesin")
    assert len(machine_summary) == 2

    proses_1_row = machine_summary[machine_summary["Proses"] == "1/2"].iloc[0]
    proses_2_row = machine_summary[machine_summary["Proses"] == "2/2"].iloc[0]

    assert proses_1_row["Qty"] == 60
    assert proses_2_row["Qty"] == 55
    assert proses_1_row["Reject"] == 0
    assert proses_2_row["Reject"] == 2

    operator_summary = report_summary.summarize_dashboard_df(df, "operator")
    assert len(operator_summary) == 2


def test_multi_operator_one_machine_merges_in_machine_summary(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "MC-1",
                "Operator": "Operator A",
                "Part No": "P-100",
                "Part Name": "Part 100",
                "Proses": "1/1",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 95,
                "Reject": 3,
                "Rework": 1,
                "Keterangan": "run by A",
            },
            {
                "MC": "MC-1",
                "Operator": "Operator B",
                "Part No": "P-100",
                "Part Name": "Part 100",
                "Proses": "1/1",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 01:00:00"),
                "_StopTs": _utc("2026-03-02 02:00:00"),
                "Qty": 102,
                "Reject": 2,
                "Rework": 0,
                "Keterangan": "run by B",
            },
        ]
    )

    summary = report_summary.summarize_dashboard_df(df, "mesin")
    assert len(summary) == 1

    row = summary.iloc[0]
    assert row["MC"] == "MC-1"
    assert row["Qty"] == 197
    assert row["Reject"] == 5
    assert row["Plan"] == "02:00"
    assert row["Utility"] == "02:00"


def test_multi_machine_one_operator_stays_separate_in_operator_summary(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "MC-1",
                "Operator": "Operator A",
                "Part No": "P-200",
                "Part Name": "Part 200",
                "Proses": "1/2",
                "Desc": "U : Utility",
                "Target": 120,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 118,
                "Reject": 2,
                "Rework": 0,
                "Keterangan": "machine 1",
            },
            {
                "MC": "MC-2",
                "Operator": "Operator A",
                "Part No": "P-200",
                "Part Name": "Part 200",
                "Proses": "1/2",
                "Desc": "U : Utility",
                "Target": 120,
                "_StartTs": _utc("2026-03-02 01:00:00"),
                "_StopTs": _utc("2026-03-02 02:00:00"),
                "Qty": 121,
                "Reject": 1,
                "Rework": 0,
                "Keterangan": "machine 2",
            },
        ]
    )

    summary = report_summary.summarize_dashboard_df(df, "operator")
    assert len(summary) == 2
    assert sorted(summary["MC"].tolist()) == ["MC-1", "MC-2"]
    assert all(summary["Operator"] == "Operator A")


def test_empty_dataframe_handling(monkeypatch):
    _patch_shift_config(monkeypatch)

    empty_df = pd.DataFrame()
    result = report_summary.summarize_dashboard_df(empty_df, "mesin")
    assert result.empty

    result = report_summary.summarize_dashboard_df(None, "mesin")
    assert result.empty


def test_missing_proses_column_defaults_to_dash(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-D1",
                "Operator": "E",
                "Part No": "PAU-5",
                "Part Name": "Part Five",
                "Desc": "U : Utility",
                "Target": 75,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 75,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "no proses",
            }
        ]
    )

    summary = report_summary.summarize_dashboard_df(df, "mesin")
    assert len(summary) == 1
    assert summary.iloc[0]["Proses"] == "-"


def test_build_dashboard_response_contains_numeric_and_display_fields(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-Z1",
                "Operator": "F",
                "Part No": "PAU-9",
                "Part Name": "Part Nine",
                "Proses": "1/1",
                "Desc": "U : Utility",
                "Target": 100,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 90,
                "Reject": 10,
                "Rework": 0,
                "Keterangan": "dashboard row",
            }
        ]
    )

    response = report_summary.build_dashboard_response(df, "mesin")

    assert "meta" in response
    assert "kpis" in response
    assert "charts" in response
    assert "rows" in response
    assert "pagination" in response

    row = response["rows"][0]
    assert row["mc"] == "P1-Z1"
    assert row["plan_minutes"] == 60
    assert row["plan"] == "01:00"
    assert row["utility_minutes"] == 60
    assert row["rt"] == "01:00"
    assert row["target_qty"] == 100
    assert row["per_num"] == 100.0
    assert row["otr_num"] == 100.0
    assert row["qr_num"] == 90.0
    assert row["oee_num"] == 90.0


def test_build_detail_export_response_from_summary_has_nonzero_time_and_kpis(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "P1-X1",
                "Operator": "G",
                "Part No": "PAU-10",
                "Part Name": "Part Ten",
                "Proses": "2/2",
                "Desc": "U : Utility",
                "Target": 120,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 100,
                "Reject": 20,
                "Rework": 0,
                "Keterangan": "run",
            },
            {
                "MC": "P1-X1",
                "Operator": "G",
                "Part No": "PAU-10",
                "Part Name": "Part Ten",
                "Proses": "2/2",
                "Desc": "TP : Tooling Problem",
                "Target": 120,
                "_StartTs": _utc("2026-03-02 01:00:00"),
                "_StopTs": _utc("2026-03-02 01:30:00"),
                "Qty": 0,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "tooling",
            },
        ]
    )

    summary_df = report_summary.summarize_dashboard_df(df, "mesin")
    detail = report_summary.build_detail_export_response(summary_df, "mesin")
    row = detail["rows"][0]

    assert row["plan"] == "01:30"
    assert row["rt"] == "01:00"
    assert row["tp"] == "00:30"
    assert row["target_qty"] == 180
    assert row["per"] == "100%"
    assert row["otr"] == "67%"
    assert row["qr"] == "83%"
    assert row["oee"] == "56%"


def test_non_machine_np_row_stays_visible_and_excluded_from_plan(monkeypatch):
    _patch_shift_config(monkeypatch)

    df = pd.DataFrame(
        [
            {
                "MC": "-",
                "Operator": "Operator B",
                "Part No": "-",
                "Part Name": "-",
                "Proses": "-",
                "Desc": "NP : No Plan",
                "Target": 0,
                "_StartTs": _utc("2026-03-02 00:00:00"),
                "_StopTs": _utc("2026-03-02 01:00:00"),
                "Qty": 0,
                "Reject": 0,
                "Rework": 0,
                "Keterangan": "No Planning",
            }
        ]
    )

    summary = report_summary.summarize_dashboard_df(df, "operator")
    assert len(summary) == 1

    row = summary.iloc[0]
    assert row["Operator"] == "Operator B"
    assert row["MC"] == "-"
    assert row["Plan"] == "00:00"
    assert row["NP"] == "01:00"
    assert row["OTR"] == "0%"
    assert row["OEE"] == "0%"


def test_status_derivation_from_time_buckets():
    assert report_summary._derive_status_from_row({"MP": "00:10"}) == "MP"
    assert report_summary._derive_status_from_row({"TP": "00:05"}) == "TP"
    assert report_summary._derive_status_from_row({"TS": "00:03"}) == "TS"
    assert report_summary._derive_status_from_row({"NP": "01:00"}) == "NP"
    assert report_summary._derive_status_from_row({"BT": "01:00"}) == "BT"
    assert report_summary._derive_status_from_row({}) == "OK"


def test_category_code_extraction():
    assert report_summary._category_code("U : Utility") == "U"
    assert report_summary._category_code("TP : Tooling Problem") == "TP"
    assert report_summary._category_code("NP : No Plan") == "NP"
    assert report_summary._category_code("BT : Break Time") == "BT"
    assert report_summary._category_code("") == ""
    assert report_summary._category_code("X") == "X"
    assert report_summary._category_code("LONGCODE : Description") == "LO"


def test_minutes_to_hhmm_conversion():
    assert report_summary._minutes_to_hhmm(0) == "00:00"
    assert report_summary._minutes_to_hhmm(30) == "00:30"
    assert report_summary._minutes_to_hhmm(60) == "01:00"
    assert report_summary._minutes_to_hhmm(90) == "01:30"
    assert report_summary._minutes_to_hhmm(125) == "02:05"
    assert report_summary._minutes_to_hhmm(600) == "10:00"


def test_percentage_calculation():
    assert report_summary._pct(50, 100) == 50.0
    assert report_summary._pct(0, 100) == 0.0
    assert report_summary._pct(100, 100) == 100.0
    assert report_summary._pct(25, 0) == 0.0
    assert report_summary._pct(75, 200) == 37.5


def test_join_unique_notes():
    series = pd.Series(["note1", "note2", "note1", "", "note3", None], dtype="object")
    result = report_summary._join_unique(series)
    assert result == "note1 | note2 | note3"

    empty_series = pd.Series([], dtype="object")
    result = report_summary._join_unique(empty_series)
    assert result == ""