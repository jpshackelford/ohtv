"""Cloud API client for OpenHands conversations."""

import logging
import time
from datetime import datetime

import httpx

from ohtv.sources.base import ConversationInfo

log = logging.getLogger("ohtv")


class CloudClient:
    """HTTP client for OpenHands Cloud API."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=180.0,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "CloudClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def search_conversations(
        self,
        updated_since: datetime | None = None,
        limit: int = 100,
        page_id: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """Search conversations, returning (items, next_page_id)."""
        params: dict = {"limit": limit}
        if updated_since:
            params["updated_at__gte"] = _format_datetime_for_api(updated_since)
        if page_id:
            params["page_id"] = page_id

        response = self._request_with_retry("GET", "/api/v1/app-conversations/search", params=params)
        data = response.json()
        return data["items"], data.get("next_page_id")


    def search_all_conversations(
        self,
        updated_since: datetime | None = None,
    ) -> list[dict]:
        """Search all conversations, handling pagination."""
        all_items: list[dict] = []
        page_id = None

        while True:
            items, next_page_id = self.search_conversations(
                updated_since=updated_since,
                page_id=page_id,
            )
            all_items.extend(items)
            if not next_page_id:
                break
            page_id = next_page_id

        return all_items

    def count_conversations(self) -> int:
        """Get total count of conversations."""
        response = self._request_with_retry("GET", "/api/v1/app-conversations/count")
        return int(response.text)

    def download_trajectory(self, conversation_id: str) -> bytes:
        """Download trajectory zip file."""
        response = self._request_with_retry(
            "GET",
            f"/api/v1/app-conversations/{conversation_id}/download",
            follow_redirects=True,
        )
        return response.content

    def _request_with_retry(
        self,
        method: str,
        path: str,
        max_retries: int = 5,
        **kwargs,
    ) -> httpx.Response:
        """Make request with exponential backoff on rate limiting."""
        base_delay = 1.0
        for attempt in range(max_retries):
            response = self._client.request(method, path, **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            delay = self._get_retry_delay(response, base_delay, attempt)
            log.warning("Rate limited (429), retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, max_retries)
            time.sleep(delay)
        log.error("Rate limit retries exhausted for %s", path)
        raise RateLimitExceededError(f"Rate limit retries exhausted for {path}")

    def _get_retry_delay(self, response: httpx.Response, base_delay: float, attempt: int) -> float:
        """Calculate retry delay from headers or exponential backoff."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            return float(retry_after)
        return base_delay * (2**attempt)


class RateLimitExceededError(Exception):
    """Raised when rate limit retries are exhausted."""


def parse_conversation_info(data: dict) -> ConversationInfo:
    """Parse API response into ConversationInfo."""
    return ConversationInfo(
        id=data["id"],
        title=data.get("title"),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
        selected_repository=data.get("selected_repository"),
    )


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string."""
    if not value:
        return None
    value = value.rstrip("Z")
    if "+" in value:
        value = value.split("+")[0]
    return datetime.fromisoformat(value)


def _format_datetime_for_api(dt: datetime) -> str:
    """Format datetime for API query parameter (ISO 8601 with Z suffix)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
