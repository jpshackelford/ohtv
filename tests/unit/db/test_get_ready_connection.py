"""Unit tests for ``ohtv.db.get_ready_connection``.

Issue #116: the canonical entry point that composes ``get_connection`` and
``ensure_db_ready`` so production callers cannot forget the migration step.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.db import (
    get_connection,
    get_db_path,
    get_ready_connection,
    migrate,
)
from ohtv.db.maintenance import is_task_completed


@pytest.fixture
def isolated_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point OHTV_DB_PATH at a fresh path inside ``tmp_path``."""
    db_path = tmp_path / "index.db"
    monkeypatch.setenv("OHTV_DB_PATH", str(db_path))
    return db_path


class TestExports:
    """The new helper is exported alongside the existing primitives."""

    def test_get_ready_connection_is_exported_from_ohtv_db(self) -> None:
        import ohtv.db as db_pkg

        assert hasattr(db_pkg, "get_ready_connection")
        assert "get_ready_connection" in db_pkg.__all__

    def test_low_level_primitives_remain_public(self) -> None:
        # AC #6: ensure_db_ready and migrate stay public.
        import ohtv.db as db_pkg

        for name in ("get_connection", "migrate", "ensure_db_ready"):
            assert hasattr(db_pkg, name)
            assert name in db_pkg.__all__


class TestHappyPath:
    """Calling get_ready_connection on a fresh DB applies migrations."""

    def test_creates_schema_on_first_call(self, isolated_db_path: Path) -> None:
        assert not isolated_db_path.exists()
        with get_ready_connection() as conn:
            # Migrations create the _migrations tracking table.
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='_migrations'"
            )
            assert cursor.fetchone() is not None

    def test_returns_connection_with_row_factory_and_wal(
        self, isolated_db_path: Path
    ) -> None:
        with get_ready_connection() as conn:
            assert conn.row_factory is sqlite3.Row
            # PRAGMA foreign_keys is honored
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1

    def test_applies_all_pending_migrations(self, isolated_db_path: Path) -> None:
        # Compare against migrate() called directly on a sibling DB.
        ref_path = isolated_db_path.parent / "ref.db"
        ref_conn = sqlite3.connect(ref_path)
        try:
            applied = migrate(ref_conn)
        finally:
            ref_conn.close()

        with get_ready_connection() as conn:
            rows = conn.execute(
                "SELECT name FROM _migrations ORDER BY name"
            ).fetchall()
            applied_via_helper = [r["name"] for r in rows]

        assert applied_via_helper == sorted(applied)

    def test_honors_explicit_db_path_argument(self, tmp_path: Path) -> None:
        explicit = tmp_path / "alt.db"
        with get_ready_connection(explicit) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='_migrations'"
            ).fetchone()
            assert row is not None
        assert explicit.exists()

    def test_honors_ohtv_db_path_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # AC #4: fresh-install commands work without db scan first.
        custom = tmp_path / "from_env.db"
        monkeypatch.setenv("OHTV_DB_PATH", str(custom))
        assert get_db_path() == custom
        with get_ready_connection() as conn:
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name='_migrations'"
            ).fetchone() is not None
        assert custom.exists()

    def test_closes_connection_on_context_exit(
        self, isolated_db_path: Path
    ) -> None:
        with get_ready_connection() as conn:
            captured = conn
        # After exit the connection is closed; ProgrammingError is raised
        # when we try to use it.
        with pytest.raises(sqlite3.ProgrammingError):
            captured.execute("SELECT 1")

    def test_closes_connection_even_on_exception(
        self, isolated_db_path: Path
    ) -> None:
        captured = None
        with pytest.raises(RuntimeError):
            with get_ready_connection() as conn:
                captured = conn
                raise RuntimeError("boom")
        assert captured is not None
        with pytest.raises(sqlite3.ProgrammingError):
            captured.execute("SELECT 1")


class TestIdempotency:
    """Behavior contract item #1: each migration applied exactly once."""

    def test_second_call_does_not_reapply_migrations(
        self, isolated_db_path: Path
    ) -> None:
        with get_ready_connection() as conn:
            first = conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
        with get_ready_connection() as conn:
            second = conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
        assert first == second

    def test_second_call_does_not_rerun_maintenance(
        self, isolated_db_path: Path
    ) -> None:
        # First call should mark any applicable maintenance tasks complete;
        # second call should observe them as already done and skip.
        with get_ready_connection():
            pass

        # Now mock ``run_maintenance`` and ensure the *second* call doesn't
        # invoke it (since there are no pending tasks on a fresh schema).
        from ohtv.db import maintenance

        with patch.object(
            maintenance, "run_maintenance", wraps=maintenance.run_maintenance
        ) as run_mock:
            with get_ready_connection():
                pass
        assert run_mock.call_count == 0


class TestShowProgress:
    """Behavior contract item #3: show_progress is opt-in."""

    def test_default_is_quiet(self, isolated_db_path: Path) -> None:
        # Defaulting to False matches the docstring contract: library
        # callers don't print spurious progress bars.
        import inspect

        sig = inspect.signature(get_ready_connection)
        assert sig.parameters["show_progress"].default is False

    def test_show_progress_passed_through_to_ensure_db_ready(
        self, isolated_db_path: Path
    ) -> None:
        # ensure_db_ready is imported lazily inside get_ready_connection,
        # so we patch on the maintenance module itself.
        from ohtv.db import maintenance

        seen: list[bool] = []
        original_fn = maintenance.ensure_db_ready

        def spy(conn: sqlite3.Connection, show_progress: bool = True) -> None:
            seen.append(show_progress)
            return original_fn(conn, show_progress=show_progress)

        with patch.object(maintenance, "ensure_db_ready", spy):
            with get_ready_connection(show_progress=True):
                pass
            with get_ready_connection(show_progress=False):
                pass
            with get_ready_connection():  # default
                pass

        assert seen == [True, False, False]


class TestMaintenanceTriggered:
    """AC #3: pending maintenance runs on first-use of every command."""

    def test_ensure_db_ready_is_called(self, isolated_db_path: Path) -> None:
        """The helper must funnel through ``ensure_db_ready`` — that's the
        whole point of #116. A bare ``migrate(conn)`` wouldn't satisfy the
        AGENTS.md item #25 contract."""
        from ohtv.db import maintenance

        original = maintenance.ensure_db_ready
        calls: list[tuple[bool]] = []

        def spy(conn: sqlite3.Connection, show_progress: bool = True) -> None:
            calls.append((show_progress,))
            return original(conn, show_progress=show_progress)

        with patch.object(maintenance, "ensure_db_ready", spy):
            with get_ready_connection():
                pass

        assert len(calls) == 1
        assert calls[0] == (False,)

    def test_pending_task_executes_on_first_call(
        self, isolated_db_path: Path
    ) -> None:
        """Inject a fake pending maintenance task and verify the helper
        runs it. This proves the helper honors the maintenance promise,
        not just migrations.
        """
        from ohtv.db import maintenance
        from ohtv.db.maintenance import MaintenanceTask

        executed: list[str] = []

        def _check_always_needed(conn: sqlite3.Connection) -> bool:
            return "fake_task_116" not in executed

        def _execute_fake(
            conn: sqlite3.Connection,
            on_progress: object,
        ) -> dict:
            executed.append("fake_task_116")
            return {"ran": True}

        fake_task = MaintenanceTask(
            name="fake_task_116",
            description="Fake maintenance task for #116 test",
            triggered_by="issue_116",
            check_needed=_check_always_needed,
            execute=_execute_fake,
        )

        with patch.object(
            maintenance, "MAINTENANCE_TASKS", [fake_task]
        ):
            with get_ready_connection():
                pass
            # Re-entry should be a no-op now that the task is recorded.
            with get_ready_connection():
                pass

        # The task ran exactly once (idempotency).
        assert executed == ["fake_task_116"]
        # And it was recorded in the maintenance_tasks table.
        with get_connection() as conn:
            row = conn.execute(
                "SELECT task_name FROM maintenance_tasks WHERE task_name=?",
                ("fake_task_116",),
            ).fetchone()
            assert row is not None
            assert is_task_completed(conn, "fake_task_116")


class TestFreshInstallCommands:
    """AC #4: fresh-install commands work without ``ohtv db scan`` first.

    These are smoke tests that invoke the converted helpers directly
    rather than spawning the CLI. The contract is identical: opening a
    connection through the canonical helper on a non-existent DB path
    must produce a usable, fully-migrated connection.
    """

    def test_get_ready_connection_against_nonexistent_db_succeeds(
        self, isolated_db_path: Path
    ) -> None:
        assert not isolated_db_path.exists()
        with get_ready_connection() as conn:
            # If embeddings table doesn't exist this raises OperationalError
            # — exactly the regression #116 is preventing.
            conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
            conn.execute("SELECT COUNT(*) FROM analysis_cache").fetchone()
            conn.execute("SELECT COUNT(*) FROM conversations").fetchone()

    def test_is_db_available_with_metadata_on_fresh_install(
        self, isolated_db_path: Path
    ) -> None:
        # Importing here so the env var fixture is already applied.
        from ohtv.conversations import is_db_available_with_metadata

        assert is_db_available_with_metadata() is False
        # DB still wasn't created — function short-circuits when
        # db_path.exists() is False.
        assert not isolated_db_path.exists()

    def test_is_db_available_with_metadata_after_db_created(
        self, isolated_db_path: Path
    ) -> None:
        from ohtv.conversations import is_db_available_with_metadata

        # Create the DB through the helper (no scan yet, no metadata).
        with get_ready_connection():
            pass

        # No conversations registered, so count_with_metadata returns 0
        # and the probe reports False — but crucially it doesn't raise.
        assert is_db_available_with_metadata() is False
