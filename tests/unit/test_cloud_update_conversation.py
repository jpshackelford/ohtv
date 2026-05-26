"""Tests for ``CloudClient.update_conversation`` (Issue #89).

Uses ``pytest-httpx`` to intercept PATCH calls against the cloud API
without touching the network.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from ohtv.sources.cloud import CloudClient, RateLimitExceededError


BASE = "https://cloud.example.com"


@pytest.fixture
def client() -> CloudClient:
    return CloudClient(BASE, "test-api-key")


def test_patch_sends_title_only(httpx_mock: HTTPXMock, client: CloudClient) -> None:
    httpx_mock.add_response(
        method="PATCH",
        url=f"{BASE}/api/v1/app-conversations/abc-123",
        status_code=200,
        json={"id": "abc-123"},
    )
    client.update_conversation("abc-123", title="New Title")
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    import json as _json
    body_json = _json.loads(requests[0].read())
    assert body_json == {"title": "New Title"}
    assert requests[0].headers["authorization"] == "Bearer test-api-key"


def test_patch_sends_tags_only(httpx_mock: HTTPXMock, client: CloudClient) -> None:
    httpx_mock.add_response(
        method="PATCH",
        url=f"{BASE}/api/v1/app-conversations/abc-123",
        status_code=200,
        json={"id": "abc-123"},
    )
    client.update_conversation("abc-123", tags={"team": "AI", "env": "prod"})
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    body = requests[0].read()
    import json
    payload = json.loads(body)
    assert payload == {"tags": {"team": "AI", "env": "prod"}}
    # The title field must NOT be sent when only tags is provided.
    assert "title" not in payload


def test_patch_sends_both_when_both_provided(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    httpx_mock.add_response(
        method="PATCH",
        url=f"{BASE}/api/v1/app-conversations/abc-123",
        status_code=200,
        json={"id": "abc-123"},
    )
    client.update_conversation("abc-123", title="T", tags={"k": "v"})
    requests = httpx_mock.get_requests()
    import json
    payload = json.loads(requests[0].read())
    assert payload == {"title": "T", "tags": {"k": "v"}}


def test_patch_with_neither_is_noop(client: CloudClient, httpx_mock: HTTPXMock) -> None:
    """No keys → no network call (still a successful return)."""
    # No mock registered; if a request hits httpx_mock will raise.
    client.update_conversation("abc-123")
    assert httpx_mock.get_requests() == []


def test_patch_propagates_http_error(httpx_mock: HTTPXMock, client: CloudClient) -> None:
    """A 4xx that is not 429 should raise HTTPStatusError."""
    httpx_mock.add_response(
        method="PATCH",
        url=f"{BASE}/api/v1/app-conversations/abc",
        status_code=404,
        json={"error": "not found"},
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.update_conversation("abc", title="X")


def test_patch_honors_retry_after_header(
    httpx_mock: HTTPXMock, client: CloudClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 with ``Retry-After`` triggers the shared rate limiter."""
    httpx_mock.add_response(
        method="PATCH",
        url=f"{BASE}/api/v1/app-conversations/abc",
        status_code=429,
        headers={"Retry-After": "1"},
    )
    httpx_mock.add_response(
        method="PATCH",
        url=f"{BASE}/api/v1/app-conversations/abc",
        status_code=200,
        json={"id": "abc"},
    )

    # Patch time.sleep so we don't actually wait the Retry-After delay.
    sleeps: list[float] = []
    monkeypatch.setattr("ohtv.sources.cloud.time.sleep", lambda s: sleeps.append(s))

    client.update_conversation("abc", title="X")
    # Should retry once → exactly 2 PATCH attempts.
    assert len(httpx_mock.get_requests()) == 2
    # And we should have honoured the Retry-After value at least once.
    assert any(s >= 1.0 for s in sleeps)


def test_patch_exhausts_retries_raises(
    httpx_mock: HTTPXMock,
    client: CloudClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When 429s keep coming forever, eventually raises ``RateLimitExceededError``."""
    # Cap retries hard so the test runs fast.
    import ohtv.sources.cloud as cloud_mod

    monkeypatch.setattr("ohtv.sources.cloud.time.sleep", lambda s: None)

    # 429 on each retry attempt (max_retries=3 → 3 attempts total)
    for _ in range(3):
        httpx_mock.add_response(
            method="PATCH",
            url=f"{BASE}/api/v1/app-conversations/abc",
            status_code=429,
            headers={"Retry-After": "0"},
        )

    # Monkey-patch the request to use max_retries=3
    original = cloud_mod.CloudClient._request_with_retry

    def _bounded(self, method, path, max_retries=3, **kwargs):
        return original(self, method, path, max_retries=max_retries, **kwargs)

    monkeypatch.setattr(cloud_mod.CloudClient, "_request_with_retry", _bounded)

    with pytest.raises(RateLimitExceededError):
        client.update_conversation("abc", title="X")
