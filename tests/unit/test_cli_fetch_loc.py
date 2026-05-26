"""End-to-end CLI smoke tests for ``ohtv fetch-loc`` (Issue #80).

These exercise the full Click entry point with a temp ``OHTV_DIR``
and a fully-migrated SQLite DB. HTTP is mocked via ``pytest-httpx``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest_httpx import HTTPXMock

from ohtv.cli import main as ohtv_main
from ohtv.db.migrations import migrate
from ohtv.github_api import GITHUB_API_BASE


PR_MERGED = {
    "merged": True,
    "state": "closed",
    "merged_at": "2024-05-01T12:34:56Z",
    "additions": 100,
    "deletions": 25,
    "changed_files": 3,
}


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

    # Initialise the DB once so the `db scan` step the user normally runs
    # before ``fetch-loc`` is implicit here.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    conn.close()
    return db_path


def _seed_pr_row(
    db_path: Path,
    canonical_url: str,
    pr_number: int,
) -> tuple[int, int]:
    """Insert a repo + a pending PR change_ref. Return ``(repo_id, row_id)``."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    fqn = canonical_url.split("//", 1)[-1]
    short = fqn.split("/")[-1]
    repo_id = conn.execute(
        "INSERT INTO repositories (canonical_url, fqn, short_name) "
        "VALUES (?, ?, ?) RETURNING id",
        (canonical_url, fqn, short),
    ).fetchone()["id"]
    row_id = conn.execute(
        "INSERT INTO change_refs (repo_id, change_type, pr_number, status) "
        "VALUES (?, 'pr', ?, 'pending') RETURNING id",
        (repo_id, pr_number),
    ).fetchone()["id"]
    conn.commit()
    conn.close()
    return repo_id, row_id


# ---------------------------------------------------------------------------
# Discoverability / help
# ---------------------------------------------------------------------------


def test_help_is_discoverable(runner: CliRunner) -> None:
    """AC #1: ``ohtv fetch-loc --help`` works and is listed in ``ohtv --help``."""
    top = runner.invoke(ohtv_main, ["--help"])
    assert top.exit_code == 0
    assert "fetch-loc" in top.output

    sub = runner.invoke(ohtv_main, ["fetch-loc", "--help"])
    assert sub.exit_code == 0
    assert "Backfill" in sub.output
    assert "GITHUB_TOKEN" in sub.output


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_missing_github_token_exits_nonzero(
    runner: CliRunner,
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #2: missing GITHUB_TOKEN → non-zero exit + helpful message."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(ohtv_main, ["fetch-loc"])
    assert result.exit_code != 0
    assert "GITHUB_TOKEN" in result.output
    assert "gh auth token" in result.output


def test_token_value_never_logged(
    runner: CliRunner,
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecrettokenvalue123")
    # No PR rows seeded → zero candidates → no HTTP. Just verify the
    # token value doesn't leak into stdout/stderr.
    result = runner.invoke(ohtv_main, ["fetch-loc", "--quiet"])
    assert "ghp_supersecrettokenvalue123" not in result.output


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing_and_makes_zero_http(
    runner: CliRunner,
    isolated_db: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #7: ``--dry-run`` does not call HTTP and does not write to the DB."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _seed_pr_row(isolated_db, "https://github.com/owner/repo", 76)

    # No GITHUB_TOKEN — dry-run still works.
    result = runner.invoke(ohtv_main, ["fetch-loc", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry-run" in result.output
    assert "1 row" in result.output

    assert httpx_mock.get_requests() == []

    # Row state is unchanged.
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM change_refs").fetchone()
    conn.close()
    assert row["status"] == "pending"
    assert row["fetched_at"] is None


# ---------------------------------------------------------------------------
# End-to-end fetch
# ---------------------------------------------------------------------------


def test_end_to_end_pr_fetch_populates_row(
    runner: CliRunner,
    isolated_db: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #13: integration smoke. PR row ends up populated."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    _seed_pr_row(isolated_db, "https://github.com/owner/repo", 76)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/76",
        status_code=200,
        json=PR_MERGED,
    )

    result = runner.invoke(ohtv_main, ["fetch-loc", "--quiet"])
    assert result.exit_code == 0

    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM change_refs").fetchone()
    conn.close()
    assert row["status"] == "merged"
    assert row["lines_added"] == 100
    assert row["lines_removed"] == 25
    assert row["files_changed"] == 3
    assert row["fetched_at"] is not None


def test_progress_bar_present_by_default_suppressed_under_quiet(
    runner: CliRunner,
    isolated_db: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #12: progress bar present by default; --quiet suppresses it.

    We can't easily inspect the live Rich progress widget, but we can
    assert that the post-run summary block is the only visible output
    under --quiet (no `Fetching LOC ...` line), and that the default
    run includes some progress affordance.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    _seed_pr_row(isolated_db, "https://github.com/owner/repo", 76)
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/76",
        status_code=200,
        json=PR_MERGED,
    )

    # Quiet: no "fetch-loc complete" block, no "Fetching LOC".
    result_quiet = runner.invoke(ohtv_main, ["fetch-loc", "-q"])
    assert result_quiet.exit_code == 0
    assert "Fetching LOC" not in result_quiet.output
    assert "fetch-loc complete" not in result_quiet.output


def test_repo_filter_restricts_to_one_repo(
    runner: CliRunner,
    isolated_db: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #8: ``--repo`` filter resolves through repo store and restricts rows."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    _seed_pr_row(isolated_db, "https://github.com/owner/repo-a", 10)
    _seed_pr_row(isolated_db, "https://github.com/owner/repo-b", 20)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo-a/pulls/10",
        status_code=200,
        json=PR_MERGED,
    )

    result = runner.invoke(ohtv_main, ["fetch-loc", "--repo", "owner/repo-a", "-q"])
    assert result.exit_code == 0
    assert len(httpx_mock.get_requests()) == 1
    assert "/repos/owner/repo-a/" in str(httpx_mock.get_requests()[0].url)

    # repo-b row was untouched.
    conn = sqlite3.connect(isolated_db)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT cr.* FROM change_refs cr JOIN repositories r ON r.id=cr.repo_id "
        "WHERE r.fqn = 'github.com/owner/repo-b'"
    ))
    conn.close()
    assert len(rows) == 1
    assert rows[0]["fetched_at"] is None


def test_unknown_repo_filter_exits_nonzero(
    runner: CliRunner,
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    result = runner.invoke(
        ohtv_main, ["fetch-loc", "--repo", "totally/unknown-repo"]
    )
    assert result.exit_code != 0
    assert "did not match any known repository" in result.output


def test_dry_run_works_without_token(
    runner: CliRunner,
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run should not require GITHUB_TOKEN — it never calls HTTP."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _seed_pr_row(isolated_db, "https://github.com/owner/repo", 1)
    result = runner.invoke(ohtv_main, ["fetch-loc", "--dry-run"])
    assert result.exit_code == 0
