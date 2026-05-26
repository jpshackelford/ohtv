"""CLI smoke tests for ``ohtv report velocity`` (issue #81).

These exercise the full Click entry point against an isolated
``OHTV_DIR`` with a fully-migrated SQLite DB. The DB is not mocked.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main as ohtv_main
from ohtv.db.migrations import migrate

from tests.unit.reports.conftest import (
    seed_contribution,
    seed_conversation,
    seed_human_input,
    seed_pr,
    seed_repo,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force the CLI to use a temp DB at ``$OHTV_DIR/index.db``."""
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


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed_two_weeks(db_path: Path) -> None:
    """Seed two PRs in two different ISO weeks for the same repo."""
    conn = _open(db_path)
    try:
        repo_id = seed_repo(conn, canonical_url="https://github.com/jpshackelford/ohtv")
        for i, when in enumerate(
            ["2024-03-05T12:00:00Z", "2024-03-12T12:00:00Z"], start=1
        ):
            seed_conversation(conn, f"c{i}")
            seed_human_input(
                conn,
                conversation_id=f"c{i}",
                initial_prompt_words=50 * i,
                initial_prompt_source="human",
                followup_word_count=0,
                followup_message_count=0,
            )
            pr_id = seed_pr(
                conn,
                repo_id=repo_id,
                pr_number=i,
                merged_at=when,
                lines_added=100 * i,
                lines_removed=10 * i,
            )
            seed_contribution(conn, conversation_id=f"c{i}", change_ref_id=pr_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# C-1: report --help lists velocity.
# ---------------------------------------------------------------------------


def test_report_group_help_lists_velocity(runner: CliRunner) -> None:
    result = runner.invoke(ohtv_main, ["report", "--help"])
    assert result.exit_code == 0, result.output
    assert "velocity" in result.output


def test_report_velocity_help_shows_options(runner: CliRunner) -> None:
    result = runner.invoke(ohtv_main, ["report", "velocity", "--help"])
    assert result.exit_code == 0, result.output
    for option in ("--format", "--since", "--until", "--repo", "--include-empty", "--no-totals", "--verbose"):
        assert option in result.output, f"missing {option} in help"


# ---------------------------------------------------------------------------
# C-2: table output prints the seeded week labels.
# ---------------------------------------------------------------------------


def test_velocity_table_output(runner: CliRunner, isolated_db: Path) -> None:
    _seed_two_weeks(isolated_db)
    result = runner.invoke(ohtv_main, ["report", "velocity"])
    assert result.exit_code == 0, result.output
    assert "2024-W10" in result.output
    assert "2024-W11" in result.output
    # Totals row present by default.
    assert "Total" in result.output


def test_velocity_table_no_totals(runner: CliRunner, isolated_db: Path) -> None:
    """--no-totals suppresses the totals row."""
    _seed_two_weeks(isolated_db)
    result = runner.invoke(ohtv_main, ["report", "velocity", "--no-totals"])
    assert result.exit_code == 0, result.output
    assert "2024-W10" in result.output
    # The totals row should not show up; "Total" appears as a string but
    # the per-week PRs should still render.
    # We assert the totals body doesn't appear: with totals, the totals
    # PRs count is the sum (2). Without, only the per-week rows show.
    lines = [ln for ln in result.output.splitlines() if "Total" in ln]
    assert all("PRs" in ln or "Total" not in ln for ln in lines), lines


# ---------------------------------------------------------------------------
# C-3: CSV output starts with the canonical header, no totals row.
# ---------------------------------------------------------------------------


def test_velocity_csv_output(runner: CliRunner, isolated_db: Path) -> None:
    _seed_two_weeks(isolated_db)
    result = runner.invoke(ohtv_main, ["report", "velocity", "--format", "csv"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert lines[0] == (
        "week,prs_merged,lines_added,lines_removed,total_loc,"
        "human_words,human_messages,words_per_loc"
    )
    # Exactly 2 data rows, no totals row.
    data_rows = [ln for ln in lines[1:] if ln.strip()]
    assert len(data_rows) == 2
    assert all(not ln.startswith("Total") for ln in data_rows)


# ---------------------------------------------------------------------------
# C-4: empty DB hint (no change_refs).
# ---------------------------------------------------------------------------


def test_velocity_empty_db_hint(runner: CliRunner, isolated_db: Path) -> None:
    """No change_refs rows → friendly hint, exit 0."""
    result = runner.invoke(ohtv_main, ["report", "velocity"])
    assert result.exit_code == 0
    assert "No change_refs" in result.output
    assert "ohtv db process all" in result.output


def test_velocity_empty_db_hint_csv(runner: CliRunner, isolated_db: Path) -> None:
    """Empty DB in CSV mode prints just the header."""
    result = runner.invoke(ohtv_main, ["report", "velocity", "--format", "csv"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("week,prs_merged")


# ---------------------------------------------------------------------------
# C-5: --since / --until / --repo / --include-empty / --verbose
# ---------------------------------------------------------------------------


def test_velocity_since_filter(runner: CliRunner, isolated_db: Path) -> None:
    _seed_two_weeks(isolated_db)
    # Drop the first week (2024-03-05) by setting --since after it.
    result = runner.invoke(
        ohtv_main, ["report", "velocity", "--since", "2024-03-10"]
    )
    assert result.exit_code == 0, result.output
    assert "2024-W11" in result.output
    assert "2024-W10" not in result.output


def test_velocity_until_filter(runner: CliRunner, isolated_db: Path) -> None:
    _seed_two_weeks(isolated_db)
    result = runner.invoke(
        ohtv_main, ["report", "velocity", "--until", "2024-03-11"]
    )
    assert result.exit_code == 0, result.output
    assert "2024-W10" in result.output
    assert "2024-W11" not in result.output


def test_velocity_repo_filter(runner: CliRunner, isolated_db: Path) -> None:
    """--repo restricts to one repo; mismatching repo yields exit 2."""
    _seed_two_weeks(isolated_db)
    # Match.
    result = runner.invoke(
        ohtv_main, ["report", "velocity", "--repo", "jpshackelford/ohtv"]
    )
    assert result.exit_code == 0
    assert "2024-W10" in result.output

    # Mismatch → exit 2.
    result = runner.invoke(
        ohtv_main, ["report", "velocity", "--repo", "unknown/repo"]
    )
    assert result.exit_code == 2
    assert "did not match" in result.output


def test_velocity_include_empty(runner: CliRunner, isolated_db: Path) -> None:
    """--include-empty fills gap weeks between seeded weeks."""
    conn = _open(isolated_db)
    repo_id = seed_repo(conn, canonical_url="https://github.com/jpshackelford/ohtv")
    seed_conversation(conn, "c1")
    seed_conversation(conn, "c2")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=10)
    seed_human_input(conn, conversation_id="c2", initial_prompt_words=10)
    pr1 = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    pr2 = seed_pr(conn, repo_id=repo_id, pr_number=2, merged_at="2024-03-19T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr1)
    seed_contribution(conn, conversation_id="c2", change_ref_id=pr2)
    conn.close()

    result = runner.invoke(
        ohtv_main, ["report", "velocity", "--include-empty"]
    )
    assert result.exit_code == 0, result.output
    for week in ("2024-W10", "2024-W11", "2024-W12"):
        assert week in result.output


def test_velocity_verbose_shows_sql(runner: CliRunner, isolated_db: Path) -> None:
    _seed_two_weeks(isolated_db)
    result = runner.invoke(ohtv_main, ["report", "velocity", "--verbose"])
    assert result.exit_code == 0, result.output
    assert "-- SQL --" in result.output
    assert "raw rows fetched" in result.output


def test_velocity_bad_since_value(runner: CliRunner, isolated_db: Path) -> None:
    """An unparseable --since value exits 2 with a friendly message."""
    _seed_two_weeks(isolated_db)
    result = runner.invoke(
        ohtv_main, ["report", "velocity", "--since", "not-a-date"]
    )
    assert result.exit_code == 2
    assert "could not parse --since" in result.output


def test_velocity_no_merged_prs_message(runner: CliRunner, isolated_db: Path) -> None:
    """When change_refs exists but none match the filters, print the empty hint."""
    # Seed only a *pending* PR (no merged ones).
    conn = _open(isolated_db)
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at=None,
        status="pending",
    )
    conn.close()

    result = runner.invoke(ohtv_main, ["report", "velocity"])
    assert result.exit_code == 0
    assert "No merged PRs" in result.output
