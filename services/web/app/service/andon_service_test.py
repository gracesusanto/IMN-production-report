import pytest

from app.service.andon_service import _determine_line, _determine_plant


@pytest.mark.parametrize(
    ("machine_name", "expected_line"),
    [
        ("A1-P1",         "STAMPING LINE A"),
        ("A14-P2",        "STAMPING LINE A"),
        ("E11A-P1",       "STAMPING LINE E"),
        ("E11B-P1",       "STAMPING LINE E"),
        ("G1-P1",         "STAMPING LINE G"),
        ("G9-P1",         "STAMPING LINE G"),
        ("W8-P2",         "WELDING LINE"),
        ("MEJAPACK-1-P2", "PACKING LINE"),
        ("MEJAPACK-8-P2", "PACKING LINE"),
        ("TEMPERING-P2",  "TEMPERING"),
        ("CHECKLOAD-P2",  "OTHER"),
    ],
)
def test_determine_line(machine_name, expected_line):
    assert _determine_line(machine_name) == expected_line


@pytest.mark.parametrize(
    ("machine_name", "expected_plant"),
    [
        ("A10-P2",       "P2"),
        ("MEJAPACK-2-P1","P1"),
        ("CHECKLOAD",    "OTHER"),
    ],
)
def test_determine_plant(machine_name, expected_plant):
    assert _determine_plant(machine_name) == expected_plant
