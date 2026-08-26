from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.model import models
from app.service import business_logic
from app.service.utils import NON_MACHINE_CATEGORY, STATUS_CONFIG


def test_np_canonical_label_is_no_plan():
    assert STATUS_CONFIG["NP"]["label"] == "NO PLAN"
    assert "NP : No Plan" in NON_MACHINE_CATEGORY


def test_non_machine_detection_uses_code_not_display_label():
    assert business_logic.is_non_machine_category("NP : No Plan")
    assert business_logic.is_non_machine_category("NP : Historical Label")
    assert business_logic.is_non_machine_category("NP")
    assert not business_logic.is_non_machine_category("U : Utility")


def test_operator_machine_query_excludes_np_regardless_of_label():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    try:
        session.add_all(
            [
                models.ActivityMesin(
                    operator_id="OP-1",
                    category="NP : No Plan",
                    start_time_id=1,
                ),
                models.ActivityMesin(
                    operator_id="OP-1",
                    category="NP : No Schedule",
                    start_time_id=2,
                ),
                models.ActivityMesin(
                    operator_id="OP-1",
                    mesin_id="MC-1",
                    tooling_id="TL-1",
                    category="U : Utility",
                    start_time_id=3,
                ),
                models.ActivityMesin(
                    operator_id="OP-1",
                    mesin_id=None,
                    tooling_id=None,
                    category="U : Utility",
                    start_time_id=4,
                ),
                models.ActivityMesin(
                    operator_id="OP-1",
                    mesin_id="",
                    tooling_id="",
                    category="U : Utility",
                    start_time_id=5,
                ),
            ]
        )
        session.commit()

        activities = business_logic.get_operator_active_machines(
            "OP-1", NON_MACHINE_CATEGORY, session
        )

        assert [activity.category for activity in activities] == ["U : Utility"]
    finally:
        session.close()


def test_optional_identifier_normalizes_android_sentinels():
    for value in (None, "", " ", "null", "NULL", "NONE", " none "):
        assert business_logic.normalize_optional_identifier(value) is None
    assert business_logic.normalize_optional_identifier(" MC-1 ") == "MC-1"
