"""Fresh-install behavioral tests for the converted entry points.

Issue #116 AC #4: ``ohtv ask``, ``ohtv search``, ``ohtv refs <id>``, and
``ohtv sync`` (et al) must succeed against a non-existent ``index.db``
without raising ``sqlite3.OperationalError: no such table: <X>``.

These tests invoke each converted helper directly via Click's
:class:`CliRunner` so they cover the integration of
``get_ready_connection`` into real command code paths — not just the
helper in isolation.

We deliberately stop short of asserting on command-specific exit codes
beyond "did not raise an unexpected OperationalError". The commands have
their own contracts (e.g. ``ohtv search`` exits 1 when no embeddings
exist) that are tested elsewhere; the contract that *this* file
guarantees is simply: "fresh DB → schema is current → no missing-table
errors anywhere in the command's first DB touch."
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main as cli


@pytest.fixture
def fresh_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point both OHTV_DIR and OHTV_DB_PATH at a fresh tmp_path.

    Returns the directory that will hold the DB once it's created.
    """
    ohtv_dir = tmp_path / "ohtv"
    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    db_path = ohtv_dir / "index.db"
    monkeypatch.setenv("OHTV_DB_PATH", str(db_path))
    # Also isolate ~/.openhands so we don't pick up real conversations.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert not db_path.exists()
    return ohtv_dir


def _no_operational_error(result) -> None:
    """Assert no ``OperationalError: no such table`` in the output.

    This is the specific regression #116 is preventing — see the issue's
    "most recent first-install regression" example.
    """
    output = (result.output or "") + str(result.exception or "")
    assert "no such table" not in output, (
        f"OperationalError 'no such table' surfaced from CLI:\n"
        f"---\n{output}\n---\n"
        f"This is the fresh-install regression #116 is preventing."
    )


class TestFreshInstallSearch:
    def test_search_does_not_raise_no_such_table(self, fresh_install: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["search", "some query"], catch_exceptions=True)
        _no_operational_error(result)


class TestFreshInstallAsk:
    def test_ask_does_not_raise_no_such_table(self, fresh_install: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["ask", "what did we work on?"], catch_exceptions=True
        )
        _no_operational_error(result)


class TestFreshInstallDbScan:
    def test_db_scan_creates_schema_and_does_not_raise(
        self, fresh_install: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "scan"], catch_exceptions=True)
        _no_operational_error(result)
        # The DB should now exist with a current schema.
        db_path = Path(fresh_install) / "index.db"
        assert db_path.exists()
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        # Schema is current — these are stable tables across migrations.
        assert "conversations" in tables
        assert "_migrations" in tables


class TestFreshInstallDbProcess:
    def test_db_process_all_does_not_raise(self, fresh_install: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "process", "all"], catch_exceptions=True)
        _no_operational_error(result)


class TestFreshInstallDbIndexCache:
    def test_db_index_cache_does_not_raise(self, fresh_install: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "index-cache"], catch_exceptions=True)
        _no_operational_error(result)


class TestFreshInstallList:
    def test_list_does_not_raise_no_such_table(self, fresh_install: Path) -> None:
        # ``ohtv list`` hits is_db_available_with_metadata() and (when label
        # filters are used) _filter_by_label — both were on the conversion
        # list. We exercise the no-filter happy path here; the label filter
        # path is exercised by its own unit tests.
        runner = CliRunner()
        result = runner.invoke(cli, ["list"], catch_exceptions=True)
        _no_operational_error(result)
