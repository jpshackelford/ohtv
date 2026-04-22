"""Cloud API client for OpenHands conversations."""

import logging
import random
import threading
import time
from datetime import datetime

import httpx

from ohtv.sources.base import ConversationInfo

log = logging.getLogger("ohtv")


class RateLimiter:
    """Thread-safe rate limiter with shared backoff.
    
    When any request gets rate limited, all subsequent requests will wait
    until the backoff period expires. This prevents thundering herd and
    respects the API's rate limit bucket.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._blocked_until = 0.0  # timestamp when we can make requests again
    
    def wait_if_needed(self) -> None:
        """Wait if we're currently in a backoff period."""
        with self._lock:
            now = time.time()
            if now < self._blocked_until:
                wait_time = self._blocked_until - now
                log.debug("Rate limiter: waiting %.1fs before request", wait_time)
        
        # Wait outside the lock so other threads can check too
        now = time.time()
        if now < self._blocked_until:
            time.sleep(self._blocked_until - now)
    
    def record_rate_limit(self, retry_after: float) -> None:
        """Record that we hit a rate limit - block all requests for retry_after seconds."""
        with self._lock:
            new_blocked_until = time.time() + retry_after
            # Only extend if this would block longer than current
            if new_blocked_until > self._blocked_until:
                self._blocked_until = new_blocked_until
                log.info("Rate limiter: blocking all requests for %.1fs", retry_after)


# Global rate limiter shared across all CloudClient instances
_global_rate_limiter = RateLimiter()


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
        max_retries: int = 10,
        **kwargs,
    ) -> httpx.Response:
        """Make request with shared rate limiter and exponential backoff.
        
        Uses a global rate limiter so that when ANY request hits a 429,
        ALL workers pause before retrying. This properly respects the
        API's rate limit bucket instead of having each worker retry
        independently.
        """
        base_delay = 2.0  # Start with 2 seconds
        max_delay = 60.0  # Cap at 1 minute
        
        for attempt in range(max_retries):
            # Wait if another request recently got rate limited
            _global_rate_limiter.wait_if_needed()
            
            response = self._client.request(method, path, **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            
            # Calculate delay and notify the shared rate limiter
            delay = self._get_retry_delay(response, base_delay, attempt, max_delay)
            log.warning("Rate limited (429) on %s, blocking all requests for %.1fs (attempt %d/%d)", 
                       path, delay, attempt + 1, max_retries)
            
            # Record this in the shared rate limiter so all workers wait
            _global_rate_limiter.record_rate_limit(delay)
            
            # This worker also waits
            time.sleep(delay)
        
        log.error("Rate limit retries exhausted for %s after %d attempts", path, max_retries)
        raise RateLimitExceededError(f"Rate limit retries exhausted for {path}")

    def _get_retry_delay(self, response: httpx.Response, base_delay: float, attempt: int, max_delay: float) -> float:
        """Calculate retry delay from headers or exponential backoff with jitter."""
        # Prefer server-provided Retry-After header
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), max_delay)
            except ValueError:
                pass
        
        # Exponential backoff: 2, 4, 8, 16, 32, 60, 60...
        delay = base_delay * (2 ** attempt)
        delay = min(delay, max_delay)
        
        # Small jitter (±10%) just to prevent exact synchronization
        jitter = delay * 0.1 * (2 * random.random() - 1)
        return delay + jitter


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
