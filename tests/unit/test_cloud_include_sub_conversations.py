"""Tests for ``CloudClient`` ``include_sub_conversations`` plumbing (Issue #108).

Uses ``pytest-httpx`` to intercept HTTP calls so we can assert the
exact query-param shape the production client sends to the cloud.
"""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from ohtv.sources.cloud import CloudClient


BASE = "https://cloud.example.com"


@pytest.fixture
def client() -> CloudClient:
    return CloudClient(BASE, "test-api-key")


# ---------------------------------------------------------------------------
# search_conversations
# ---------------------------------------------------------------------------
def test_search_conversations_includes_sub_conversations_by_default(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """The default-on contract from the issue's technical approach."""
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{BASE}/api/v1/app-conversations/search"
            "?limit=100&include_sub_conversations=true"
        ),
        json={"items": [], "next_page_id": None},
    )
    items, next_id = client.search_conversations()
    assert items == []
    assert next_id is None
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].url.params.get("include_sub_conversations") == "true"


def test_search_conversations_omits_param_when_explicitly_disabled(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """The legacy default-off behavior remains reachable for symmetry.

    We send NO ``include_sub_conversations`` param at all in this
    case — matching the wire shape the API would see from a pre-#108
    client. The cloud's default on this endpoint is ``false``, so
    omission and ``false`` are equivalent.
    """
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/api/v1/app-conversations/search?limit=100",
        json={"items": [], "next_page_id": None},
    )
    client.search_conversations(include_sub_conversations=False)
    requests = httpx_mock.get_requests()
    assert "include_sub_conversations" not in requests[0].url.params


def test_search_conversations_returns_parent_conversation_id(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """Sub-conversations in the response carry the parent id verbatim."""
    payload = {
        "items": [
            {
                "id": "parent",
                "title": "Parent",
                "parent_conversation_id": None,
            },
            {
                "id": "child",
                "title": "Child",
                "parent_conversation_id": "parent",
            },
        ],
        "next_page_id": None,
    }
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{BASE}/api/v1/app-conversations/search"
            "?limit=100&include_sub_conversations=true"
        ),
        json=payload,
    )
    items, _ = client.search_conversations()
    by_id = {item["id"]: item for item in items}
    assert by_id["child"]["parent_conversation_id"] == "parent"
    assert by_id["parent"]["parent_conversation_id"] is None


# ---------------------------------------------------------------------------
# search_all_conversations
# ---------------------------------------------------------------------------
def test_search_all_conversations_forwards_kwarg_across_pages(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """Each paginated page MUST forward the kwarg so sub-convs stay
    included on later pages too (avoiding the silent-exclusion bug
    described in the issue body)."""
    page1 = {
        "items": [{"id": "a", "parent_conversation_id": None}],
        "next_page_id": "p2",
    }
    page2 = {
        "items": [{"id": "b", "parent_conversation_id": "a"}],
        "next_page_id": None,
    }
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{BASE}/api/v1/app-conversations/search"
            "?limit=100&include_sub_conversations=true"
        ),
        json=page1,
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{BASE}/api/v1/app-conversations/search"
            "?limit=100&page_id=p2&include_sub_conversations=true"
        ),
        json=page2,
    )
    items = client.search_all_conversations()
    assert {item["id"] for item in items} == {"a", "b"}
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    for r in requests:
        assert r.url.params.get("include_sub_conversations") == "true"


# ---------------------------------------------------------------------------
# count_conversations
# ---------------------------------------------------------------------------
def test_count_conversations_forwards_include_sub_conversations(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """For symmetry with the listing endpoint, ``/count`` also gets the
    kwarg forwarded. The production cloud's ``/count`` endpoint is
    inclusive regardless today (per the issue's reproduction), but we
    forward the param so any future server-side honoring is picked up
    without further client changes."""
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/api/v1/app-conversations/count?include_sub_conversations=true",
        text="3582",
    )
    count = client.count_conversations()
    assert count == 3582
    requests = httpx_mock.get_requests()
    assert requests[0].url.params.get("include_sub_conversations") == "true"


def test_count_conversations_omits_param_when_disabled(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/api/v1/app-conversations/count",
        text="3580",
    )
    count = client.count_conversations(include_sub_conversations=False)
    assert count == 3580
    requests = httpx_mock.get_requests()
    assert "include_sub_conversations" not in requests[0].url.params


# ---------------------------------------------------------------------------
# Regression: param does NOT interact with other listing kwargs
# ---------------------------------------------------------------------------
def test_search_conversations_param_coexists_with_updated_since(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """``updated_since`` + ``include_sub_conversations`` must both land
    in the same request (no silent dropping when either is set)."""
    from datetime import datetime, timezone

    since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{BASE}/api/v1/app-conversations/search?"
            "limit=100&updated_at__gte=2024-01-01T12:00:00Z"
            "&include_sub_conversations=true"
        ),
        json={"items": [], "next_page_id": None},
    )
    client.search_conversations(updated_since=since)
    requests = httpx_mock.get_requests()
    params = requests[0].url.params
    assert params.get("updated_at__gte") == "2024-01-01T12:00:00Z"
    assert params.get("include_sub_conversations") == "true"
    # ``limit`` is still on the wire so the default page size hasn't
    # been silently widened.
    assert params.get("limit") == "100"
    # No json body on GET.
    assert requests[0].read() == b""


def test_search_conversations_param_value_is_lowercase_true(
    httpx_mock: HTTPXMock, client: CloudClient
) -> None:
    """Defensive: the cloud parser is case-sensitive on some endpoints;
    ``True`` (Python repr) would silently degrade to false on the
    server. Lock the wire shape to ``"true"`` literal."""
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{BASE}/api/v1/app-conversations/search"
            "?limit=100&include_sub_conversations=true"
        ),
        json={"items": [], "next_page_id": None},
    )
    client.search_conversations()
    requests = httpx_mock.get_requests()
    # Raw URL query string, not the parsed params, so we see the
    # exact wire value.
    assert "include_sub_conversations=true" in str(requests[0].url)
    assert "include_sub_conversations=True" not in str(requests[0].url)
    # Sanity: no body on the GET.
    assert json.loads(requests[0].read() or b"null") is None
