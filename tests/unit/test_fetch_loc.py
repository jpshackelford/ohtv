"""Unit tests for ``ohtv.fetch_loc.fetch_loc`` (Issue #80).

These tests use a real in-memory SQLite connection (migration 016 runs
against it) plus a real :class:`ohtv.github_api.GitHubClient` wired up
against ``pytest-httpx``. No mocks except at the HTTP boundary, per
project policy.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pytest_httpx import HTTPXMock

from ohtv.db.migrations import migrate
from ohtv.fetch_loc import (
    fetch_loc,
    is_github_url,
    parse_github_owner_repo,
    split_commit_range,
)
from ohtv.github_api import GITHUB_API_BASE, GitHubClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn() -> sqlite3.Connection:
    """A fresh in-memory DB with all migrations applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient("test-token", max_retries=3)


def _add_repo(
    conn: sqlite3.Connection,
    canonical_url: str,
    fqn: str | None = None,
    short_name: str | None = None,
) -> int:
    """Insert a row in ``repositories`` and return its id."""
    if fqn is None:
        # Derive a reasonable FQN from the URL.
        fqn = canonical_url.split("//", 1)[-1]
    if short_name is None:
        short_name = fqn.split("/")[-1]
    cursor = conn.execute(
        "INSERT INTO repositories (canonical_url, fqn, short_name) "
        "VALUES (?, ?, ?) RETURNING id",
        (canonical_url, fqn, short_name),
    )
    return cursor.fetchone()[0]


def _add_pr_row(
    conn: sqlite3.Connection,
    repo_id: int,
    pr_number: int,
    *,
    status: str = "pending",
    fetched_at: str | None = None,
    lines_added: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO change_refs (repo_id, change_type, pr_number, status,
                                 fetched_at, lines_added)
        VALUES (?, 'pr', ?, ?, ?, ?) RETURNING id
        """,
        (repo_id, pr_number, status, fetched_at, lines_added),
    )
    return cursor.fetchone()[0]


def _add_push_row(
    conn: sqlite3.Connection,
    repo_id: int,
    commit_range: str,
    *,
    status: str = "pending",
    fetched_at: str | None = None,
    lines_added: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO change_refs (repo_id, change_type, commit_range, status,
                                 fetched_at, lines_added)
        VALUES (?, 'direct_push', ?, ?, ?, ?) RETURNING id
        """,
        (repo_id, commit_range, status, fetched_at, lines_added),
    )
    return cursor.fetchone()[0]


def _read_row(conn: sqlite3.Connection, row_id: int) -> dict:
    cur = conn.execute("SELECT * FROM change_refs WHERE id = ?", (row_id,))
    return dict(cur.fetchone())


# Canned API responses ------------------------------------------------------

PR_MERGED = {
    "merged": True,
    "state": "closed",
    "merged_at": "2024-05-01T12:34:56Z",
    "additions": 120,
    "deletions": 30,
    "changed_files": 4,
}

PR_OPEN = {
    "merged": False,
    "state": "open",
    "merged_at": None,
    "additions": 0,
    "deletions": 0,
    "changed_files": 0,
}

PR_CLOSED_UNMERGED = {
    "merged": False,
    "state": "closed",
    "merged_at": None,
    "additions": 0,
    "deletions": 0,
    "changed_files": 0,
}

COMPARE_RESPONSE = {
    "files": [
        {"filename": "a.py", "additions": 10, "deletions": 5},
        {"filename": "b.py", "additions": 3, "deletions": 0},
        {"filename": "c.md", "additions": 1, "deletions": 1},
    ],
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_is_github_url_classifier() -> None:
    assert is_github_url("https://github.com/owner/repo") is True
    assert is_github_url("https://github.com/owner/repo.git") is True
    assert is_github_url("https://www.github.com/owner/repo") is True
    assert is_github_url("http://github.com/owner/repo") is True
    assert is_github_url("https://gitlab.com/owner/repo") is False
    assert is_github_url("https://bitbucket.org/owner/repo") is False
    assert is_github_url("") is False
    assert is_github_url(None) is False


def test_parse_github_owner_repo() -> None:
    assert parse_github_owner_repo("https://github.com/foo/bar") == ("foo", "bar")
    assert parse_github_owner_repo("https://github.com/foo/bar.git") == ("foo", "bar")
    assert parse_github_owner_repo("https://github.com/foo/bar/") == ("foo", "bar")
    assert parse_github_owner_repo("https://github.com/foo/bar/issues/1") == (
        "foo",
        "bar",
    )
    assert parse_github_owner_repo("https://github.com/") is None


def test_split_commit_range() -> None:
    assert split_commit_range("abc..def") == ("abc", "def")
    assert split_commit_range("abc123..def456") == ("abc123", "def456")
    assert split_commit_range("abc") is None
    assert split_commit_range("..def") is None
    assert split_commit_range("abc..") is None


# ---------------------------------------------------------------------------
# Orchestrator: PR path
# ---------------------------------------------------------------------------


def test_pr_merged_path_updates_loc_and_status(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_pr_row(conn, repo_id, 76)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/76",
        status_code=200,
        json=PR_MERGED,
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    assert result.failed == 0
    assert result.total_candidates == 1

    row = _read_row(conn, row_id)
    assert row["status"] == "merged"
    assert row["lines_added"] == 120
    assert row["lines_removed"] == 30
    assert row["files_changed"] == 4
    assert row["merged_at"] == "2024-05-01T12:34:56Z"
    assert row["fetched_at"] is not None


def test_pr_open_path_updates_status_only(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_pr_row(conn, repo_id, 77)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/77",
        status_code=200,
        json=PR_OPEN,
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    assert result.still_open == 1

    row = _read_row(conn, row_id)
    assert row["status"] == "open"
    assert row["lines_added"] is None
    assert row["lines_removed"] is None
    assert row["files_changed"] is None
    assert row["merged_at"] is None
    assert row["fetched_at"] is not None


def test_pr_closed_unmerged_updates_status_only(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_pr_row(conn, repo_id, 78)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/78",
        status_code=200,
        json=PR_CLOSED_UNMERGED,
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    assert result.closed_unmerged == 1

    row = _read_row(conn, row_id)
    assert row["status"] == "closed"
    assert row["lines_added"] is None


# ---------------------------------------------------------------------------
# Orchestrator: direct_push path
# ---------------------------------------------------------------------------


def test_direct_push_path_sums_file_stats(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_push_row(conn, repo_id, "abc..def")

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/compare/abc...def",
        status_code=200,
        json=COMPARE_RESPONSE,
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1

    row = _read_row(conn, row_id)
    assert row["status"] == "merged"
    assert row["lines_added"] == 14  # 10 + 3 + 1
    assert row["lines_removed"] == 6  # 5 + 0 + 1
    assert row["files_changed"] == 3
    assert row["fetched_at"] is not None


def test_direct_push_empty_files_is_zero_loc(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_push_row(conn, repo_id, "abc..def")
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/compare/abc...def",
        status_code=200,
        json={"files": []},
    )
    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    row = _read_row(conn, row_id)
    assert row["lines_added"] == 0
    assert row["files_changed"] == 0


def test_direct_push_malformed_commit_range_skipped(
    conn: sqlite3.Connection, client: GitHubClient, httpx_mock: HTTPXMock
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    _add_push_row(conn, repo_id, "no-dots-here")

    result = fetch_loc(conn, client=client)
    assert result.skipped_unparseable == 1
    assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------
# Idempotency + force + dry-run
# ---------------------------------------------------------------------------


def test_idempotent_second_run_makes_zero_requests(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    _add_pr_row(conn, repo_id, 76)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/76",
        status_code=200,
        json=PR_MERGED,
    )

    # First run populates the row.
    fetch_loc(conn, client=client)
    assert len(httpx_mock.get_requests()) == 1

    # Second run must make ZERO additional requests. The merged row is
    # filtered out at the SQL level, so it never even reaches the
    # Python orchestrator — ``total_candidates`` is 0 and HTTP is silent.
    result2 = fetch_loc(conn, client=client)
    assert len(httpx_mock.get_requests()) == 1  # still the original
    assert result2.total_candidates == 0
    assert result2.fetched == 0


def test_force_refetches_populated_rows(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    # Pre-populated row — should be skipped without --force.
    row_id = _add_pr_row(
        conn, repo_id, 76, status="merged",
        fetched_at="2024-01-01T00:00:00+00:00",
        lines_added=10,
    )

    # Sanity: default run sees zero candidates.
    result_default = fetch_loc(conn, client=client)
    assert result_default.total_candidates == 0
    assert httpx_mock.get_requests() == []

    # --force gets one HTTP call.
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/76",
        status_code=200,
        json=PR_MERGED,
    )
    result_force = fetch_loc(conn, client=client, force=True)
    assert result_force.fetched == 1
    row = _read_row(conn, row_id)
    assert row["lines_added"] == 120  # updated to new value


def test_dry_run_makes_no_http_calls_and_no_db_writes(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_pr_row(conn, repo_id, 76)
    before = _read_row(conn, row_id)

    result = fetch_loc(conn, client=client, dry_run=True)
    assert result.total_candidates == 1
    assert result.fetched == 0
    assert httpx_mock.get_requests() == []

    after = _read_row(conn, row_id)
    assert after == before


# ---------------------------------------------------------------------------
# Repo filter
# ---------------------------------------------------------------------------


def test_repo_filter_restricts_rows(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_a = _add_repo(conn, "https://github.com/owner/repo-a")
    repo_b = _add_repo(conn, "https://github.com/owner/repo-b")
    _add_pr_row(conn, repo_a, 10)
    _add_pr_row(conn, repo_b, 20)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo-a/pulls/10",
        status_code=200,
        json=PR_MERGED,
    )

    result = fetch_loc(conn, client=client, repo_id=repo_a)
    assert result.total_candidates == 1
    assert result.fetched == 1
    assert len(httpx_mock.get_requests()) == 1
    assert "/repos/owner/repo-a/" in str(httpx_mock.get_requests()[0].url)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_404_marks_fetched_and_continues(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_a = _add_pr_row(conn, repo_id, 1)
    row_b = _add_pr_row(conn, repo_id, 2)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=404,
        json={"message": "Not Found"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/2",
        status_code=200,
        json=PR_MERGED,
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    assert result.failed == 1
    assert result.exit_code == 0  # mixed success/failure -> exit 0

    # Row a was marked tried; row b was populated.
    row_a_after = _read_row(conn, row_a)
    assert row_a_after["fetched_at"] is not None
    assert row_a_after["lines_added"] is None  # 404 leaves LOC NULL

    row_b_after = _read_row(conn, row_b)
    assert row_b_after["lines_added"] == 120


def test_500_marks_tried_and_continues(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_a = _add_pr_row(conn, repo_id, 1)
    _add_pr_row(conn, repo_id, 2)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=500,
        json={"message": "boom"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/2",
        status_code=200,
        json=PR_MERGED,
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    assert result.failed == 1
    assert result.exit_code == 0

    row_a_after = _read_row(conn, row_a)
    assert row_a_after["fetched_at"] is not None  # marked tried
    assert row_a_after["lines_added"] is None


def test_all_requests_fail_exits_nonzero(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    _add_pr_row(conn, repo_id, 1)
    _add_pr_row(conn, repo_id, 2)

    for n in (1, 2):
        httpx_mock.add_response(
            method="GET",
            url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{n}",
            status_code=404,
            json={"message": "Not Found"},
        )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 0
    assert result.failed == 2
    assert result.exit_code == 1


def test_zero_candidates_exits_zero(
    conn: sqlite3.Connection, client: GitHubClient
) -> None:
    result = fetch_loc(conn, client=client)
    assert result.total_candidates == 0
    assert result.exit_code == 0


def test_401_marks_tried_and_continues(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    row_id = _add_pr_row(conn, repo_id, 1)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=401,
        json={"message": "Bad credentials"},
    )
    result = fetch_loc(conn, client=client)
    assert result.failed == 1
    assert _read_row(conn, row_id)["fetched_at"] is not None


# ---------------------------------------------------------------------------
# Non-GitHub + edge cases
# ---------------------------------------------------------------------------


def test_non_github_repo_skipped_without_touching_row(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://gitlab.com/group/proj")
    row_id = _add_pr_row(conn, repo_id, 1)
    before = _read_row(conn, row_id)

    result = fetch_loc(conn, client=client)
    assert result.skipped_non_github == 1
    assert result.fetched == 0
    assert httpx_mock.get_requests() == []

    after = _read_row(conn, row_id)
    assert after == before  # no fetched_at, no status change


def test_open_pr_re_fetches_after_one_hour(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    """An open PR fetched >1 h ago is re-fetched even without --force."""
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    two_hours_ago = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).replace(microsecond=0).isoformat()
    row_id = _add_pr_row(
        conn, repo_id, 1, status="open", fetched_at=two_hours_ago
    )

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=200,
        json=PR_MERGED,  # has merged since
    )

    result = fetch_loc(conn, client=client)
    assert result.fetched == 1
    assert _read_row(conn, row_id)["status"] == "merged"


def test_recent_open_pr_not_re_fetched(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    five_min_ago = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).replace(microsecond=0).isoformat()
    _add_pr_row(conn, repo_id, 1, status="open", fetched_at=five_min_ago)

    result = fetch_loc(conn, client=client)
    assert result.skipped_cached == 1
    assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


def test_progress_callback_fires_for_each_row(
    httpx_mock: HTTPXMock, conn: sqlite3.Connection, client: GitHubClient
) -> None:
    repo_id = _add_repo(conn, "https://github.com/owner/repo")
    for n in (1, 2):
        _add_pr_row(conn, repo_id, n)
        httpx_mock.add_response(
            method="GET",
            url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{n}",
            status_code=200,
            json=PR_MERGED,
        )

    events: list[tuple[int, int, str]] = []
    fetch_loc(conn, client=client, on_progress=lambda i, t, m: events.append((i, t, m)))

    assert len(events) == 2
    assert events[0][:2] == (1, 2)
    assert events[1][:2] == (2, 2)
    assert "owner/repo#1" in events[0][2]
    assert "owner/repo#2" in events[1][2]
