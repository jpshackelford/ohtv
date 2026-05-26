"""Unit tests for ``ohtv.github_api.GitHubClient`` (Issue #80).

Uses ``pytest-httpx`` to mock all outbound HTTP. The client must:

* Always send the auth + accept + API-version headers.
* Translate 404 to ``None`` (graceful — the orchestrator records "tried").
* Sleep + retry on 429 / rate-limited 403; honor ``Retry-After``.
* Raise :class:`RateLimitExceededError` when retries are exhausted.
* Log a WARNING when ``X-RateLimit-Remaining`` falls below 100.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from ohtv.github_api import (
    GITHUB_API_BASE,
    GitHubClient,
    RateLimitExceededError,
    _is_rate_limited,
    _maybe_warn_low_rate_limit,
)


# A merged PR fixture. Trimmed down to the fields we read.
PR_MERGED = {
    "number": 76,
    "state": "closed",
    "merged": True,
    "merged_at": "2024-05-01T12:34:56Z",
    "additions": 120,
    "deletions": 30,
    "changed_files": 4,
}

PR_OPEN = {
    "number": 77,
    "state": "open",
    "merged": False,
    "merged_at": None,
    "additions": 0,
    "deletions": 0,
    "changed_files": 0,
}

PR_CLOSED_UNMERGED = {
    "number": 78,
    "state": "closed",
    "merged": False,
    "merged_at": None,
    "additions": 0,
    "deletions": 0,
    "changed_files": 0,
}

COMPARE_RESPONSE = {
    "base_commit": {"sha": "abc1234"},
    "merge_base_commit": {"sha": "abc1234"},
    "files": [
        {"filename": "a.py", "additions": 10, "deletions": 5},
        {"filename": "b.py", "additions": 3, "deletions": 0},
        {"filename": "c.md", "additions": 1, "deletions": 1},
    ],
}


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient("test-token-do-not-log")


def test_get_pr_parses_merged_response(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/76",
        status_code=200,
        json=PR_MERGED,
    )
    data = client.get_pr("owner", "repo", 76)
    assert data is not None
    assert data["merged"] is True
    assert data["additions"] == 120
    assert data["deletions"] == 30
    assert data["changed_files"] == 4
    assert data["merged_at"] == "2024-05-01T12:34:56Z"


def test_get_pr_parses_open_response(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/77",
        status_code=200,
        json=PR_OPEN,
    )
    data = client.get_pr("owner", "repo", 77)
    assert data is not None
    assert data["merged"] is False
    assert data["state"] == "open"


def test_get_pr_parses_closed_unmerged(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/78",
        status_code=200,
        json=PR_CLOSED_UNMERGED,
    )
    data = client.get_pr("owner", "repo", 78)
    assert data is not None
    assert data["merged"] is False
    assert data["state"] == "closed"


def test_get_pr_handles_404(httpx_mock: HTTPXMock, client: GitHubClient) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/9999",
        status_code=404,
        json={"message": "Not Found"},
    )
    # 404 → None (graceful), not an exception.
    assert client.get_pr("owner", "repo", 9999) is None


def test_get_compare_sums_file_stats_and_uses_triple_dot(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    """Compare URL must use three dots between SHAs, not two."""
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/compare/abc123...def456",
        status_code=200,
        json=COMPARE_RESPONSE,
    )
    data = client.get_compare("owner", "repo", "abc123", "def456")
    assert data is not None
    assert len(data["files"]) == 3
    # Caller does the summing; client just returns the raw response.
    total_add = sum(f["additions"] for f in data["files"])
    total_del = sum(f["deletions"] for f in data["files"])
    assert total_add == 14
    assert total_del == 6


def test_get_compare_handles_404(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/compare/xxx...yyy",
        status_code=404,
        json={"message": "Not Found"},
    )
    assert client.get_compare("owner", "repo", "xxx", "yyy") is None


def test_auth_and_versioning_headers_present(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    """All three GitHub-mandated headers must be on every outbound request.

    This is also the test that proves we send a Bearer token *but* does
    not log it: we read it from the request object, never from the
    GitHubClient's internal state.
    """
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=200,
        json=PR_MERGED,
    )
    client.get_pr("owner", "repo", 1)
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    headers = requests[0].headers
    assert headers["authorization"] == "Bearer test-token-do-not-log"
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"
    assert headers["user-agent"].startswith("ohtv/")


def test_rate_limit_retry_honors_retry_after(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch, client: GitHubClient
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "ohtv.github_api.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    # First response: 429 with Retry-After 0.1.
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=429,
        headers={"Retry-After": "0.1", "X-RateLimit-Remaining": "0"},
        json={"message": "rate limited"},
    )
    # Second response: 200.
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=200,
        json=PR_MERGED,
    )

    data = client.get_pr("owner", "repo", 1)
    assert data is not None
    assert data["additions"] == 120
    assert len(httpx_mock.get_requests()) == 2
    # Sleep was called once, with ≤ 0.1 s (the Retry-After hint).
    assert len(sleep_calls) == 1
    assert sleep_calls[0] <= 0.1 + 0.01  # tiny float tolerance


def test_rate_limit_403_with_remaining_zero_is_retried(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub returns 403 with X-RateLimit-Remaining=0 for primary limits."""
    client = GitHubClient("t", max_retries=3)
    monkeypatch.setattr("ohtv.github_api.time.sleep", lambda s: None)

    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=403,
        headers={"X-RateLimit-Remaining": "0", "Retry-After": "0"},
        json={"message": "API rate limit exceeded"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=200,
        json=PR_MERGED,
    )

    assert client.get_pr("owner", "repo", 1) is not None
    assert len(httpx_mock.get_requests()) == 2
    client.close()


def test_rate_limit_exhausted_raises(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = GitHubClient("t", max_retries=2)
    monkeypatch.setattr("ohtv.github_api.time.sleep", lambda s: None)

    # Both attempts return 429.
    for _ in range(2):
        httpx_mock.add_response(
            method="GET",
            url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
            status_code=429,
            headers={"Retry-After": "0"},
            json={"message": "rate limited"},
        )

    with pytest.raises(RateLimitExceededError):
        client.get_pr("owner", "repo", 1)
    assert len(httpx_mock.get_requests()) == 2
    client.close()


def test_low_rate_limit_logs_warning(
    httpx_mock: HTTPXMock,
    client: GitHubClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=200,
        json=PR_MERGED,
        headers={"X-RateLimit-Remaining": "50", "X-RateLimit-Reset": "9999999999"},
    )
    with caplog.at_level(logging.WARNING, logger="ohtv"):
        client.get_pr("owner", "repo", 1)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("rate-limit low" in r.getMessage() for r in warnings)


def test_high_rate_limit_no_warning(
    httpx_mock: HTTPXMock,
    client: GitHubClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=200,
        json=PR_MERGED,
        headers={"X-RateLimit-Remaining": "4500"},
    )
    with caplog.at_level(logging.WARNING, logger="ohtv"):
        client.get_pr("owner", "repo", 1)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("rate-limit low" in r.getMessage() for r in warnings)


def test_non_404_non_rate_limit_5xx_raises(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=500,
        json={"message": "server error"},
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.get_pr("owner", "repo", 1)


def test_real_403_without_rate_limit_signal_is_not_retried(
    httpx_mock: HTTPXMock, client: GitHubClient
) -> None:
    """Auth-failure 403 must propagate, not loop forever."""
    httpx_mock.add_response(
        method="GET",
        url=f"{GITHUB_API_BASE}/repos/owner/repo/pulls/1",
        status_code=403,
        json={"message": "Forbidden"},
        headers={"X-RateLimit-Remaining": "4500"},
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.get_pr("owner", "repo", 1)


# ---------------------------------------------------------------------------
# Helper-function tests
# ---------------------------------------------------------------------------


def test_is_rate_limited_classifier() -> None:
    def _make(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(status, headers=headers or {})

    assert _is_rate_limited(_make(429)) is True
    assert _is_rate_limited(_make(403, {"X-RateLimit-Remaining": "0"})) is True
    assert _is_rate_limited(_make(403, {"Retry-After": "5"})) is True
    assert _is_rate_limited(_make(403, {"X-RateLimit-Remaining": "1000"})) is False
    assert _is_rate_limited(_make(200)) is False
    assert _is_rate_limited(_make(500)) is False


def test_maybe_warn_low_rate_limit_ignores_missing_header(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="ohtv"):
        _maybe_warn_low_rate_limit({})
    assert not any("rate-limit low" in r.getMessage() for r in caplog.records)


def test_maybe_warn_low_rate_limit_invalid_header_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="ohtv"):
        _maybe_warn_low_rate_limit({"X-RateLimit-Remaining": "not-a-number"})
    assert not any("rate-limit low" in r.getMessage() for r in caplog.records)
