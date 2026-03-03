# Reporting Pipeline Test Suite

This directory contains comprehensive tests for the denormalized ActivityReport reporting pipeline.

## Test Structure

### Test Files

- **`conftest.py`** - Pytest fixtures and test configuration
- **`test_business_logic.py`** - Tests for business logic functions
- **`test_generate_report.py`** - Tests for report generation functions
- **`test_backfill_script.py`** - Tests for the backfill script
- **`test_integration.py`** - End-to-end integration tests
- **`run_tests.py`** - Test runner script
- **`README.md`** - This documentation

### Test Categories

#### Unit Tests
- `test_business_logic.py` - Tests `build_activity_report_row`, `upsert_activity_report`, `process_activity`
- `test_generate_report.py` - Tests timezone conversion, shift calculation, query functions, data transformation
- `test_backfill_script.py` - Tests keyset pagination, error handling, chunking behavior

#### Integration Tests
- `test_integration.py` - End-to-end workflows, multi-component interactions, error recovery

## Running Tests

### Using the Test Runner

```bash
# Run all tests
python tests/run_tests.py

# Run only unit tests
python tests/run_tests.py unit

# Run only integration tests
python tests/run_tests.py integration

# Run specific test file
python tests/run_tests.py business_logic

# Run with verbose output
python tests/run_tests.py -v
```

### Using Pytest Directly

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_business_logic.py -v

# Run specific test class
pytest tests/test_business_logic.py::TestBuildActivityReportRow -v

# Run specific test method
pytest tests/test_business_logic.py::TestBuildActivityReportRow::test_build_activity_report_row_success -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing
```

## Test Coverage

### Business Logic Functions (`test_business_logic.py`)

**`build_activity_report_row`**
- ✅ Successful row building with all fields
- ✅ NON_MACHINE_CATEGORY handling (null mesin_id/tooling_id)
- ✅ Activity not found error handling
- ✅ Incomplete activity error handling
- ✅ NULL value defaults (output=0, reject=0, rework=0)

**`upsert_activity_report`**
- ✅ Insert new ActivityReport record
- ✅ Update existing ActivityReport record (idempotency)
- ✅ Incomplete activity failure handling

**`process_activity`**
- ✅ Normal flow (start activity, stop activity, create report)
- ✅ NON_MACHINE_CATEGORY activities (NP, BT, BR)
- ✅ Stopping NP activities automatically
- ✅ Transaction rollback on error
- ✅ Deduplication of stopped activities

### Report Generation Functions (`test_generate_report.py`)

**Timezone Conversion**
- ✅ Timezone-naive timestamps (assumes UTC)
- ✅ Timezone-aware timestamps
- ✅ Custom format strings
- ✅ Edge cases (empty series, NaT values)

**Shift Calculation**
- ✅ Weekday shifts (7-15, 15-23, 23-7)
- ✅ Saturday shifts (7-12, 12-17, 17-22)
- ✅ Sunday shifts (always shift 1)
- ✅ Time range checking (_is_time_between)

**Query Functions**
- ✅ Successful query_activity_report
- ✅ Empty result handling
- ✅ Time filtering accuracy
- ✅ Column structure verification

**Data Transformation**
- ✅ _generate_keterangan with all/partial/empty fields
- ✅ df_to_report basic transformation
- ✅ Operator report NP activity filtering
- ✅ merge_consecutive_downtime functionality

**Feature Flag**
- ✅ USE_ACTIVITY_REPORT_TABLE flag behavior

### Backfill Script Functions (`test_backfill_script.py`)

**Keyset Queries**
- ✅ Basic keyset pagination
- ✅ Pagination with last_id
- ✅ Limit handling
- ✅ Incomplete activity exclusion

**Backfill Process**
- ✅ Successful backfill with chunking
- ✅ Dry run mode (no actual changes)
- ✅ Partial failure handling
- ✅ Commit failure recovery
- ✅ Fatal error handling
- ✅ Keyset progression tracking

**Edge Cases**
- ✅ Existing reports (idempotency)
- ✅ Empty chunk size handling
- ✅ No data scenarios

### Integration Tests (`test_integration.py`)

**End-to-End Workflows**
- ✅ Complete activity lifecycle (start → stop → report)
- ✅ Multiple operators working in parallel
- ✅ NON_MACHINE_CATEGORY workflow
- ✅ Feature flag integration
- ✅ Activity transition consistency

**Backfill Integration**
- ✅ Backfill and query integration
- ✅ Backfill idempotency verification

**Error Recovery**
- ✅ Partial failure recovery with rollback
- ✅ Concurrent activity handling
- ✅ Transaction consistency under failure

**Performance Scenarios**
- ✅ Large dataset handling
- ✅ Efficient query performance

## Test Database

Tests use an in-memory SQLite database for speed and isolation:
- Each test function gets a fresh database session
- All tables are created automatically via `models.Base.metadata.create_all()`
- Fixtures provide sample data (operators, machines, toolings, activities)

## Test Fixtures

**Core Fixtures** (in `conftest.py`)
- `test_session` - Database session with clean schema
- `sample_operator` - Test operator record
- `sample_mesin` - Test machine record
- `sample_tooling` - Test tooling record
- `sample_mesin_logs` - Start/stop log entries
- `sample_activity_mesin` - Completed activity record
- `sample_non_machine_activity` - NON_MACHINE_CATEGORY activity

## Mock Usage

Tests use `unittest.mock` for:
- Database session mocking (`@patch('app.cmd.backfill_activity_report.database.SessionLocal')`)
- Function mocking (`@patch('app.cmd.backfill_activity_report.upsert_activity_report')`)
- Feature flag testing (`@patch('app.cmd.generate_report.USE_ACTIVITY_REPORT_TABLE', True)`)

## Test Scenarios Covered

### Success Paths
- Normal activity processing flow
- Report generation with various data types
- Backfill processing with chunking
- Query result transformation

### Error Conditions
- Database connection failures
- Transaction rollback scenarios
- Invalid data handling
- Missing record scenarios

### Edge Cases
- Empty datasets
- NULL/None value handling
- Timezone edge cases (NaT, different formats)
- Concurrent access scenarios

### Data Integrity
- Foreign key constraint verification
- Unique constraint handling
- Default value application
- Idempotent operation verification

## Requirements

### Dependencies
```bash
pip install pytest pytest-cov pandas pytz sqlalchemy
```

### Environment
- Python 3.7+
- SQLAlchemy models and database setup
- Test data fixtures

## Continuous Integration

These tests are designed to run in CI environments:
- No external database dependencies (uses SQLite in-memory)
- Deterministic test data and timestamps
- Comprehensive error condition coverage
- Fast execution (in-memory database)