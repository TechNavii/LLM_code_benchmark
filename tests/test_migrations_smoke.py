"""Migration/schema consistency checks for server databases.

Since this project uses SQLAlchemy's create_all() approach (no Alembic migrations),
these tests validate:
1. Fresh temp SQLite DB schema creation works
2. Schema matches current ORM model definitions
3. All expected tables/columns exist
4. Foreign key constraints are correctly configured

Tests are hermetic (use temp directories) and fast.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker


class TestMainDatabaseSchema:
    """Test main database (runs) schema consistency."""

    @pytest.fixture
    def temp_db_url(self, tmp_path: Path) -> str:
        """Create a temp database URL for testing."""
        return f"sqlite:///{tmp_path / 'test_history.db'}"

    @pytest.fixture
    def temp_engine(self, temp_db_url: str):
        """Create a temp engine for testing."""
        return create_engine(temp_db_url)

    def test_schema_creation_succeeds(self, temp_engine, tmp_path: Path) -> None:
        """Base.metadata.create_all should complete without errors."""
        from server.database import Base

        # Create schema in temp DB
        Base.metadata.create_all(bind=temp_engine)

        # Verify tables were created
        inspector = inspect(temp_engine)
        tables = inspector.get_table_names()
        assert "runs" in tables
        assert "attempts" in tables

    def test_runs_table_has_expected_columns(self, temp_engine) -> None:
        """Runs table should have all expected columns with correct types."""
        from server.database import Base

        Base.metadata.create_all(bind=temp_engine)

        inspector = inspect(temp_engine)
        columns = {col["name"]: col for col in inspector.get_columns("runs")}

        # Check required columns exist
        expected_columns = [
            "id",
            "timestamp_utc",
            "model_id",
            "tasks",
            "samples",
            "accuracy",
            "total_cost",
            "total_duration",
            "summary_path",
            "summary_json",
        ]
        for col_name in expected_columns:
            assert col_name in columns, f"Missing column: {col_name}"

        # Check key column properties
        assert columns["id"]["primary_key"] == 1
        assert columns["timestamp_utc"]["nullable"] is False
        assert columns["model_id"]["nullable"] is False
        assert columns["tasks"]["nullable"] is False
        assert columns["samples"]["nullable"] is False

        # Nullable columns should be nullable
        assert columns["accuracy"]["nullable"] is True
        assert columns["total_cost"]["nullable"] is True
        assert columns["total_duration"]["nullable"] is True

    def test_attempts_table_has_expected_columns(self, temp_engine) -> None:
        """Attempts table should have all expected columns."""
        from server.database import Base

        Base.metadata.create_all(bind=temp_engine)

        inspector = inspect(temp_engine)
        columns = {col["name"]: col for col in inspector.get_columns("attempts")}

        expected_columns = [
            "id",
            "run_id",
            "task_id",
            "status",
            "duration",
            "prompt_tokens",
            "completion_tokens",
            "cost",
            "error",
        ]
        for col_name in expected_columns:
            assert col_name in columns, f"Missing column: {col_name}"

        # Check key column properties
        assert columns["id"]["primary_key"] == 1
        assert columns["run_id"]["nullable"] is False
        assert columns["task_id"]["nullable"] is False
        assert columns["status"]["nullable"] is False

        # Nullable columns should be nullable
        assert columns["duration"]["nullable"] is True
        assert columns["prompt_tokens"]["nullable"] is True
        assert columns["completion_tokens"]["nullable"] is True
        assert columns["cost"]["nullable"] is True
        assert columns["error"]["nullable"] is True

    def test_foreign_key_constraint_exists(self, temp_engine) -> None:
        """Attempts should have FK to runs table."""
        from server.database import Base

        Base.metadata.create_all(bind=temp_engine)

        inspector = inspect(temp_engine)
        fks = inspector.get_foreign_keys("attempts")

        # Should have exactly one FK
        assert len(fks) >= 1

        # FK should reference runs table
        runs_fks = [fk for fk in fks if fk["referred_table"] == "runs"]
        assert len(runs_fks) == 1

        fk = runs_fks[0]
        assert fk["constrained_columns"] == ["run_id"]
        assert fk["referred_columns"] == ["id"]

    def test_schema_is_idempotent(self, temp_engine) -> None:
        """Calling create_all multiple times should not fail."""
        from server.database import Base

        # Call create_all multiple times
        for _ in range(3):
            Base.metadata.create_all(bind=temp_engine)

        # Should still have correct schema
        inspector = inspect(temp_engine)
        tables = inspector.get_table_names()
        assert "runs" in tables
        assert "attempts" in tables


class TestQADatabaseSchema:
    """Test QA database (qa_runs) schema consistency."""

    @pytest.fixture
    def temp_db_url(self, tmp_path: Path) -> str:
        """Create a temp database URL for testing."""
        return f"sqlite:///{tmp_path / 'test_qa_history.db'}"

    @pytest.fixture
    def temp_engine(self, temp_db_url: str):
        """Create a temp engine for testing."""
        return create_engine(temp_db_url)

    def test_schema_creation_succeeds(self, temp_engine) -> None:
        """Base.metadata.create_all should complete without errors."""
        from server.qa_database import Base

        # Create schema in temp DB
        Base.metadata.create_all(bind=temp_engine)

        # Verify tables were created
        inspector = inspect(temp_engine)
        tables = inspector.get_table_names()
        assert "qa_runs" in tables
        assert "qa_attempts" in tables

    def test_qa_runs_table_has_expected_columns(self, temp_engine) -> None:
        """QA runs table should have all expected columns."""
        from server.qa_database import Base

        Base.metadata.create_all(bind=temp_engine)

        inspector = inspect(temp_engine)
        columns = {col["name"]: col for col in inspector.get_columns("qa_runs")}

        expected_columns = [
            "id",
            "timestamp_utc",
            "model_id",
            "questions",
            "samples",
            "accuracy",
            "total_cost",
            "total_duration",
            "summary_path",
            "summary_json",
        ]
        for col_name in expected_columns:
            assert col_name in columns, f"Missing column: {col_name}"

        # Check key column properties
        assert columns["id"]["primary_key"] == 1
        assert columns["timestamp_utc"]["nullable"] is False
        assert columns["model_id"]["nullable"] is False

    def test_qa_attempts_table_has_expected_columns(self, temp_engine) -> None:
        """QA attempts table should have all expected columns."""
        from server.qa_database import Base

        Base.metadata.create_all(bind=temp_engine)

        inspector = inspect(temp_engine)
        columns = {col["name"]: col for col in inspector.get_columns("qa_attempts")}

        expected_columns = [
            "id",
            "run_id",
            "model",
            "sample_index",
            "question_number",
            "status",
            "duration",
            "prompt_tokens",
            "completion_tokens",
            "cost",
            "model_answer",
            "expected_answer",
            "normalized_answer",
            "normalized_expected",
            "error",
        ]
        for col_name in expected_columns:
            assert col_name in columns, f"Missing column: {col_name}"

        # Check key column properties
        assert columns["id"]["primary_key"] == 1
        assert columns["run_id"]["nullable"] is False
        assert columns["model"]["nullable"] is False
        assert columns["status"]["nullable"] is False

    def test_qa_foreign_key_constraint_exists(self, temp_engine) -> None:
        """QA attempts should have FK to qa_runs table."""
        from server.qa_database import Base

        Base.metadata.create_all(bind=temp_engine)

        inspector = inspect(temp_engine)
        fks = inspector.get_foreign_keys("qa_attempts")

        # FK should reference qa_runs table
        qa_runs_fks = [fk for fk in fks if fk["referred_table"] == "qa_runs"]
        assert len(qa_runs_fks) == 1

        fk = qa_runs_fks[0]
        assert fk["constrained_columns"] == ["run_id"]
        assert fk["referred_columns"] == ["id"]


class TestModelSchemaConsistency:
    """Verify ORM models match the created schema."""

    @pytest.fixture
    def temp_db_url(self, tmp_path: Path) -> str:
        """Create a temp database URL for testing."""
        return f"sqlite:///{tmp_path / 'test_consistency.db'}"

    def test_run_record_fields_match_columns(self) -> None:
        """RunRecord model fields should match expected column set."""
        from server.database import RunRecord

        # Get all mapped columns from the model
        mapper = RunRecord.__mapper__
        column_names = {col.name for col in mapper.columns}

        expected = {
            "id",
            "timestamp_utc",
            "model_id",
            "tasks",
            "samples",
            "accuracy",
            "total_cost",
            "total_duration",
            "summary_path",
            "summary_json",
        }
        assert column_names == expected

    def test_attempt_record_fields_match_columns(self) -> None:
        """AttemptRecord model fields should match expected column set."""
        from server.database import AttemptRecord

        mapper = AttemptRecord.__mapper__
        column_names = {col.name for col in mapper.columns}

        expected = {
            "id",
            "run_id",
            "task_id",
            "status",
            "duration",
            "prompt_tokens",
            "completion_tokens",
            "cost",
            "error",
        }
        assert column_names == expected

    def test_qa_run_record_fields_match_columns(self) -> None:
        """QARunRecord model fields should match expected column set."""
        from server.qa_database import QARunRecord

        mapper = QARunRecord.__mapper__
        column_names = {col.name for col in mapper.columns}

        expected = {
            "id",
            "timestamp_utc",
            "model_id",
            "questions",
            "samples",
            "accuracy",
            "total_cost",
            "total_duration",
            "summary_path",
            "summary_json",
        }
        assert column_names == expected

    def test_qa_attempt_record_fields_match_columns(self) -> None:
        """QAAttemptRecord model fields should match expected column set."""
        from server.qa_database import QAAttemptRecord

        mapper = QAAttemptRecord.__mapper__
        column_names = {col.name for col in mapper.columns}

        expected = {
            "id",
            "run_id",
            "model",
            "sample_index",
            "question_number",
            "status",
            "duration",
            "prompt_tokens",
            "completion_tokens",
            "cost",
            "model_answer",
            "expected_answer",
            "normalized_answer",
            "normalized_expected",
            "error",
        }
        assert column_names == expected


class TestDatabaseCRUDOperations:
    """Smoke test basic CRUD operations against temp databases."""

    @pytest.fixture
    def temp_main_session(self, tmp_path: Path):
        """Create a session for temp main database."""
        from server.database import Base

        db_url = f"sqlite:///{tmp_path / 'test_main.db'}"
        engine = create_engine(db_url)
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        with SessionLocal() as session:
            yield session

    @pytest.fixture
    def temp_qa_session(self, tmp_path: Path):
        """Create a session for temp QA database."""
        from server.qa_database import Base

        db_url = f"sqlite:///{tmp_path / 'test_qa.db'}"
        engine = create_engine(db_url)
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        with SessionLocal() as session:
            yield session

    def test_can_insert_and_query_run_record(self, temp_main_session: Session) -> None:
        """Should be able to insert and query RunRecord."""
        import datetime as dt

        from server.database import RunRecord

        record = RunRecord(
            id="test_run_001",
            timestamp_utc=dt.datetime(2024, 1, 1, 12, 0, 0),
            model_id="test-model",
            tasks='["task1", "task2"]',
            samples=2,
            accuracy=0.85,
            total_cost=0.05,
            total_duration=10.5,
            summary_path="/tmp/test/summary.json",
            summary_json='{"test": true}',
        )
        temp_main_session.add(record)
        temp_main_session.commit()

        # Query back
        retrieved = temp_main_session.get(RunRecord, "test_run_001")
        assert retrieved is not None
        assert retrieved.model_id == "test-model"
        assert retrieved.samples == 2
        assert retrieved.accuracy == 0.85

    def test_can_insert_run_with_attempts(self, temp_main_session: Session) -> None:
        """Should be able to insert RunRecord with AttemptRecords."""
        import datetime as dt

        from server.database import AttemptRecord, RunRecord

        run = RunRecord(
            id="test_run_002",
            timestamp_utc=dt.datetime(2024, 1, 1, 12, 0, 0),
            model_id="test-model",
            tasks='["task1"]',
            samples=1,
            summary_path="/tmp/test/summary.json",
            summary_json="{}",
        )
        run.attempts = [
            AttemptRecord(
                task_id="task1",
                status="pass",
                duration=5.0,
                prompt_tokens=100,
                completion_tokens=50,
            ),
            AttemptRecord(
                task_id="task1",
                status="fail",
                error="Test error",
            ),
        ]
        temp_main_session.add(run)
        temp_main_session.commit()

        # Verify attempts were created
        retrieved = temp_main_session.get(RunRecord, "test_run_002")
        assert retrieved is not None
        assert len(retrieved.attempts) == 2
        assert retrieved.attempts[0].status == "pass"
        assert retrieved.attempts[1].error == "Test error"

    def test_cascade_delete_removes_attempts(self, temp_main_session: Session) -> None:
        """Deleting a run should cascade delete attempts."""
        import datetime as dt

        from server.database import AttemptRecord, RunRecord

        run = RunRecord(
            id="test_run_003",
            timestamp_utc=dt.datetime(2024, 1, 1, 12, 0, 0),
            model_id="test-model",
            tasks="[]",
            samples=1,
            summary_path="/tmp/summary.json",
            summary_json="{}",
        )
        run.attempts = [
            AttemptRecord(task_id="task1", status="pass"),
        ]
        temp_main_session.add(run)
        temp_main_session.commit()

        # Delete run
        temp_main_session.delete(run)
        temp_main_session.commit()

        # Verify attempts were also deleted
        from sqlalchemy import select

        attempts = (
            temp_main_session.execute(select(AttemptRecord).where(AttemptRecord.run_id == "test_run_003"))
            .scalars()
            .all()
        )
        assert len(attempts) == 0

    def test_can_insert_and_query_qa_run_record(self, temp_qa_session: Session) -> None:
        """Should be able to insert and query QARunRecord."""
        import datetime as dt

        from server.qa_database import QARunRecord

        record = QARunRecord(
            id="qa_test_001",
            timestamp_utc=dt.datetime(2024, 1, 1, 12, 0, 0),
            model_id="test-model",
            questions='["q1", "q2"]',
            samples=2,
            accuracy=0.90,
            summary_path="/tmp/qa/summary.json",
            summary_json='{"qa": true}',
        )
        temp_qa_session.add(record)
        temp_qa_session.commit()

        retrieved = temp_qa_session.get(QARunRecord, "qa_test_001")
        assert retrieved is not None
        assert retrieved.accuracy == 0.90


class TestMigrationDirectoryExists:
    """Verify migration infrastructure exists (even if unused)."""

    def test_migrations_directory_exists(self) -> None:
        """Migrations directory should exist for potential future use."""
        migrations_dir = Path(__file__).parent.parent / "migrations"
        assert migrations_dir.exists(), "migrations/ directory should exist"

    def test_alembic_env_exists(self) -> None:
        """Alembic env.py should exist."""
        env_file = Path(__file__).parent.parent / "migrations" / "env.py"
        assert env_file.exists(), "migrations/env.py should exist"

    def test_migrations_readme_exists(self) -> None:
        """Migrations README should exist with instructions."""
        readme = Path(__file__).parent.parent / "migrations" / "README.md"
        assert readme.exists(), "migrations/README.md should exist"
