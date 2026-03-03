"""
Pytest configuration and fixtures for reporting pipeline tests.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.model.models as models
import app.database as database


@pytest.fixture(scope="function")
def test_session():
    """Create a test database session with in-memory SQLite."""
    # Use in-memory SQLite for fast tests
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    models.Base.metadata.create_all(bind=engine)

    # Create session
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    yield session

    session.close()


@pytest.fixture
def sample_operator(test_session):
    """Create a sample operator."""
    operator = models.Operator(
        id="OP-TestOperator",
        nik="12345",
        name="Test Operator"
    )
    test_session.add(operator)
    test_session.commit()
    return operator


@pytest.fixture
def sample_mesin(test_session):
    """Create a sample machine."""
    mesin = models.Mesin(
        id="MC-TestMachine",
        name="Test Machine",
        tonase=100
    )
    test_session.add(mesin)
    test_session.commit()
    return mesin


@pytest.fixture
def sample_tooling(test_session):
    """Create a sample tooling."""
    tooling = models.Tooling(
        id="TL-TestTooling",
        customer="Test Customer",
        part_no="P001",
        part_name="Test Part",
        child_part_name="Child Part",
        kode_tooling="T001",
        common_tooling_name="Common Tool",
        proses="Test Process",
        std_jam=8
    )
    test_session.add(tooling)
    test_session.commit()
    return tooling


@pytest.fixture
def sample_mesin_logs(test_session, sample_operator, sample_mesin, sample_tooling):
    """Create sample MesinLog entries."""
    start_time = datetime.utcnow() - timedelta(hours=2)
    stop_time = datetime.utcnow() - timedelta(hours=1)

    start_log = models.MesinLog(
        mesin_id=sample_mesin.id,
        operator_id=sample_operator.id,
        tooling_id=sample_tooling.id,
        curr_category=None,
        next_category="RUNNING",
        timestamp=start_time
    )
    test_session.add(start_log)
    test_session.flush()

    stop_log = models.MesinLog(
        mesin_id=sample_mesin.id,
        operator_id=sample_operator.id,
        tooling_id=sample_tooling.id,
        curr_category="RUNNING",
        next_category="IDLE",
        timestamp=stop_time
    )
    test_session.add(stop_log)
    test_session.flush()

    return start_log, stop_log


@pytest.fixture
def sample_activity_mesin(test_session, sample_operator, sample_mesin, sample_tooling, sample_mesin_logs):
    """Create a completed ActivityMesin."""
    start_log, stop_log = sample_mesin_logs

    activity = models.ActivityMesin(
        mesin_id=sample_mesin.id,
        operator_id=sample_operator.id,
        tooling_id=sample_tooling.id,
        category="RUNNING",
        start_time_id=start_log.id,
        stop_time_id=stop_log.id,
        output=100,
        reject=5,
        rework=2,
        coil_no="C001",
        lot_no="L001",
        pack_no="P001",
        keterangan="Test activity"
    )
    test_session.add(activity)
    test_session.commit()
    return activity


@pytest.fixture
def sample_non_machine_activity(test_session, sample_operator):
    """Create a NON_MACHINE_CATEGORY activity (NP/BT/BR)."""
    start_time = datetime.utcnow() - timedelta(minutes=30)
    stop_time = datetime.utcnow() - timedelta(minutes=15)

    start_log = models.MesinLog(
        mesin_id=None,
        operator_id=sample_operator.id,
        tooling_id=None,
        curr_category=None,
        next_category="BT : Breaktime",
        timestamp=start_time
    )
    test_session.add(start_log)
    test_session.flush()

    stop_log = models.MesinLog(
        mesin_id=None,
        operator_id=sample_operator.id,
        tooling_id=None,
        curr_category="BT : Breaktime",
        next_category="RUNNING",
        timestamp=stop_time
    )
    test_session.add(stop_log)
    test_session.flush()

    activity = models.ActivityMesin(
        mesin_id=None,
        operator_id=sample_operator.id,
        tooling_id=None,
        category="BT : Breaktime",
        start_time_id=start_log.id,
        stop_time_id=stop_log.id,
        output=0,
        reject=0,
        rework=0
    )
    test_session.add(activity)
    test_session.commit()
    return activity