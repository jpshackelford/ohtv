"""CLI smoke tests for ``ohtv report weekly-counts`` (issue #92).

Exercise the full Click entry point against an isolated ``OHTV_DIR``
with a fully-migrated SQLite DB. No DB mocks.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main as ohtv_main
from ohtv.db.migrations import migrate


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force the CLI to use a temp DB at ``$OHTV_DIR/index.db``.

    Mirrors the pattern in :mod:`tests.unit.reports.test_cli_report`.
    """
    ohtv_dir = tmp_path / "ohtv"
    ohtv_dir.mkdir()
    db_path = ohtv_dir / "index.db"
    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    monkeypatch.setenv("OHTV_DB_PATH", str(db_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    conn.close()
    return db_path


def _seed_two_weeks(db_path: Path) -> None:
    """Seed two cloud conversations in adjacent ISO weeks.

    Each row sets ``root_conversation_id = id`` so it survives the
    root-grain filter added in issue #123. ``ConversationStore``
    does this automatically in production; raw-SQL test seeds
    have to do it explicitly.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, created_at, source, root_conversation_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("c1", "/tmp/c1", "2024-03-05T12:00:00Z", "cloud", "c1"),  # W10
    )
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, created_at, source, root_conversation_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("c2", "/tmp/c2", "2024-03-12T12:00:00Z", "local", "c2"),  # W11
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# C-1: default stdout CSV
# ---------------------------------------------------------------------------


def test_default_stdout_csv(runner: CliRunner, isolated_db: Path) -> None:
    """Default invocation prints a parseable CSV with the canonical header."""
    _seed_two_weeks(isolated_db)
    result = runner.invoke(ohtv_main, ["report", "weekly-counts"])
    assert result.exit_code == 0, result.output

    # First line is the header.
    lines = result.output.splitlines()
    assert lines[0] == "week,cloud,cli,total", lines[0]

    # Parses cleanly with DictReader.
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert reader.fieldnames == ["week", "cloud", "cli", "total"]
    assert len(rows) == 2
    by_week = {r["week"]: r for r in rows}
    assert by_week["2024-W10"]["cloud"] == "1"
    assert by_week["2024-W10"]["cli"] == "0"
    assert by_week["2024-W10"]["total"] == "1"
    assert by_week["2024-W11"]["cloud"] == "0"
    assert by_week["2024-W11"]["cli"] == "1"
    assert by_week["2024-W11"]["total"] == "1"


# ---------------------------------------------------------------------------
# C-2: --out writes to file
# ---------------------------------------------------------------------------


def test_out_flag_writes_file(
    runner: CliRunner, isolated_db: Path, tmp_path: Path
) -> None:
    """``--out PATH`` writes the CSV to the file and prints nothing on stdout."""
    _seed_two_weeks(isolated_db)
    out_file = tmp_path / "counts.csv"
    result = runner.invoke(
        ohtv_main, ["report", "weekly-counts", "--out", str(out_file)]
    )
    assert result.exit_code == 0, result.output
    assert result.output == "", f"expected empty stdout, got {result.output!r}"
    assert out_file.exists()

    contents = out_file.read_text()
    lines = contents.splitlines()
    assert lines[0] == "week,cloud,cli,total"

    reader = csv.DictReader(io.StringIO(contents))
    rows = list(reader)
    assert len(rows) == 2
    assert {r["week"] for r in rows} == {"2024-W10", "2024-W11"}


# ---------------------------------------------------------------------------
# C-3: empty DB → header-only
# ---------------------------------------------------------------------------


def test_empty_db_emits_header_only(
    runner: CliRunner, isolated_db: Path
) -> None:
    """No conversations → exactly the header row, exit 0."""
    result = runner.invoke(ohtv_main, ["report", "weekly-counts"])
    assert result.exit_code == 0, result.output
    non_empty_lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert non_empty_lines == ["week,cloud,cli,total"]
