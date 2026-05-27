"""CLI smoke tests for ``ohtv report velocity --chart`` (issue #82).

Mirrors the structure of ``test_cli_report.py``: an isolated
``OHTV_DIR`` with a fully-migrated SQLite DB, seeded via the
fixtures in ``conftest.py``. Each test runs the Click entry point
end-to-end.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

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


def _seed_one_repo(db_path: Path, repo_url: str = "https://github.com/jpshackelford/ohtv") -> int:
    """Seed two merged PRs in two consecutive ISO weeks."""
    conn = _open(db_path)
    try:
        repo_id = seed_repo(conn, canonical_url=repo_url)
        for i, when in enumerate(
            ["2024-03-05T12:00:00Z", "2024-03-12T12:00:00Z"], start=1
        ):
            seed_conversation(conn, f"c{repo_url}-{i}")
            seed_human_input(
                conn,
                conversation_id=f"c{repo_url}-{i}",
                initial_prompt_words=50 * i,
                initial_prompt_source="human",
            )
            pr_id = seed_pr(
                conn,
                repo_id=repo_id,
                pr_number=i,
                merged_at=when,
                lines_added=100 * i,
                lines_removed=10 * i,
            )
            seed_contribution(
                conn, conversation_id=f"c{repo_url}-{i}", change_ref_id=pr_id
            )
        return repo_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# C-1: --chart writes a non-empty image file.
# ---------------------------------------------------------------------------


def test_cli_chart_creates_file(runner: CliRunner, isolated_db: Path, tmp_path: Path) -> None:
    _seed_one_repo(isolated_db)
    out = tmp_path / "v.png"
    result = runner.invoke(ohtv_main, ["report", "velocity", "--chart", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.stat().st_size > 0
    with open(out, "rb") as f:
        assert f.read(4) == b"\x89PNG"


# ---------------------------------------------------------------------------
# C-2: empty DB → exit 0, hint printed, NO file written.
# ---------------------------------------------------------------------------


def test_cli_chart_empty_db_no_file(
    runner: CliRunner, isolated_db: Path, tmp_path: Path
) -> None:
    out = tmp_path / "v.png"
    # No data seeded — change_refs table is empty.
    result = runner.invoke(ohtv_main, ["report", "velocity", "--chart", str(out)])
    assert result.exit_code == 0, result.output
    assert not out.exists()
    # Mirrors the existing #81 empty-state hint.
    assert "No change_refs rows found" in result.output


def test_cli_chart_no_merged_prs_in_range_no_file(
    runner: CliRunner, isolated_db: Path, tmp_path: Path
) -> None:
    """Seeded data outside the --since window → empty productive set."""
    _seed_one_repo(isolated_db)
    out = tmp_path / "v.png"
    result = runner.invoke(
        ohtv_main,
        ["report", "velocity", "--chart", str(out), "--since", "2099-01-01"],
    )
    assert result.exit_code == 0, result.output
    assert not out.exists()
    assert "No merged PRs in range" in result.output


# ---------------------------------------------------------------------------
# C-3: matplotlib missing → friendly UsageError.
# ---------------------------------------------------------------------------


def test_cli_chart_missing_matplotlib(
    runner: CliRunner, isolated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When matplotlib is not importable, CLI exits 2 with a friendly hint.

    We simulate the missing-extra state by patching ``sys.modules`` so
    that importing ``matplotlib`` raises ``ImportError`` even though
    the package is physically present.
    """
    _seed_one_repo(isolated_db)
    out = tmp_path / "v.png"

    # Evict any cached matplotlib modules and our charts module.
    for k in list(sys.modules):
        if k == "matplotlib" or k.startswith("matplotlib."):
            monkeypatch.delitem(sys.modules, k, raising=False)
    monkeypatch.delitem(sys.modules, "ohtv.reports.charts", raising=False)

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("No module named 'matplotlib'")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=fake_import):
        result = runner.invoke(ohtv_main, ["report", "velocity", "--chart", str(out)])

    assert result.exit_code != 0
    assert "pip install ohtv[charts]" in result.output


# ---------------------------------------------------------------------------
# C-4: --chart respects --repo filter (data routed through aggregate_velocity).
# ---------------------------------------------------------------------------


def test_cli_chart_respects_repo_filter(
    runner: CliRunner, isolated_db: Path, tmp_path: Path
) -> None:
    """Seed two repos; --repo X should produce a chart with only X's bars."""
    _seed_one_repo(isolated_db, "https://github.com/jpshackelford/ohtv")

    # Second repo with a different week and bigger numbers.
    conn = _open(isolated_db)
    try:
        repo_id = seed_repo(conn, canonical_url="https://github.com/other/other")
        seed_conversation(conn, "co-2")
        seed_human_input(
            conn, conversation_id="co-2", initial_prompt_words=999, initial_prompt_source="human"
        )
        pr_id = seed_pr(
            conn,
            repo_id=repo_id,
            pr_number=1,
            merged_at="2024-04-02T12:00:00Z",
            lines_added=9999,
            lines_removed=0,
        )
        seed_contribution(conn, conversation_id="co-2", change_ref_id=pr_id)
    finally:
        conn.close()

    out = tmp_path / "v.png"

    from matplotlib.axes import Axes

    with patch.object(Axes, "bar", autospec=True) as bar:
        result = runner.invoke(
            ohtv_main,
            ["report", "velocity", "--chart", str(out), "--repo", "jpshackelford/ohtv"],
        )
    assert result.exit_code == 0, result.output
    assert out.exists()

    # First bar call is the PR-counts panel for the filtered set.
    # We expect 2 bars (the seeded W10 + W11). The "other" repo would
    # add a third week (W14) if --repo didn't filter it out.
    first = bar.call_args_list[0]
    assert len(list(first.args[2])) == 2


# ---------------------------------------------------------------------------
# Mark-date round-trip through the CLI.
# ---------------------------------------------------------------------------


def test_cli_chart_mark_date_drawn(
    runner: CliRunner, isolated_db: Path, tmp_path: Path
) -> None:
    _seed_one_repo(isolated_db)
    out = tmp_path / "v.svg"

    from matplotlib.axes import Axes

    with patch.object(Axes, "axvline", autospec=True) as axvline:
        result = runner.invoke(
            ohtv_main,
            [
                "report",
                "velocity",
                "--chart",
                str(out),
                "--mark-date",
                "2024-03-11",
                "--title",
                "Smoke",
            ],
        )
    assert result.exit_code == 0, result.output
    panel_calls = [c for c in axvline.call_args_list if c.kwargs.get("linestyle") == "--"]
    assert len(panel_calls) == 3
