"""GitHub REST API client for fetching PR / compare stats (Issue #80).

This module is the HTTP boundary for ``ohtv fetch-loc``. It deliberately
sticks to a thin wrapper around ``httpx.Client`` so ``pytest-httpx`` can
mock all requests in unit tests without any code path being replaced.

Endpoints used:

* ``GET /repos/{owner}/{repo}/pulls/{pr_number}`` — PR LOC + merge state.
* ``GET /repos/{owner}/{repo}/compare/{base}...{head}`` — direct-push
  LOC (sum of ``files[].additions`` / ``files[].deletions``).

Rate-limit strategy mirrors :class:`ohtv.sources.cloud.CloudClient`:

1. On 429 (or 403 with rate-limit signal) honor ``Retry-After``, falling
   back to ``X-RateLimit-Reset`` (unix epoch − now()), then exponential
   backoff with jitter capped at 60 s.
2. After every successful response, peek ``X-RateLimit-Remaining``; if
   below 100, emit a ``WARNING``-level log line.
3. On exhausted retries raise :class:`RateLimitExceededError` — the
   orchestrator catches it and exits with the usual error path.

Auth tokens are never logged. The token is supplied at construction
time and only ever flows out via the ``Authorization`` header.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Mapping

import httpx

log = logging.getLogger("ohtv")

GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "ohtv/0.1"
RATE_LIMIT_WARN_THRESHOLD = 100


class RateLimitExceededError(Exception):
    """Raised when GitHub rate-limit retries are exhausted."""


class GitHubClient:
    """Thin synchronous client over the GitHub REST API.

    Only the two endpoints needed for ``ohtv fetch-loc`` are exposed.
    Everything else (auth headers, rate-limit handling, retry backoff)
    is shared via :meth:`_request_with_retry`.

    Args:
        token: Personal access token / fine-grained token. Required; if
            the caller has none, the CLI should error before reaching
            this class so we never log a token-less request.
        base_url: Override the GitHub API root (only used in tests so
            ``pytest-httpx`` can pin URLs).
        timeout: Per-request timeout in seconds. Default 30 s — GitHub
            responses are usually < 1 s; we mostly need this in case of
            transient network hangs.
        max_retries: Maximum 429/rate-limit retries per request.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = GITHUB_API_BASE,
        timeout: float = 30.0,
        max_retries: int = 6,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Context manager / lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    def get_pr(self, owner: str, repo: str, pr_number: int) -> dict[str, Any] | None:
        """Fetch a PR's metadata + LOC stats.

        Returns ``None`` if the PR is 404 (deleted or private) so the
        caller can record a "tried" attempt without aborting the run.
        All other non-2xx responses raise :class:`httpx.HTTPStatusError`
        via :meth:`_request_with_retry`.
        """
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}"
        response = self._request_with_retry("GET", path)
        if response is None:
            return None
        return response.json()

    def get_compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> dict[str, Any] | None:
        """Fetch ``compare`` data between two SHAs (used for direct pushes).

        Note GitHub's compare URL uses **three** dots between SHAs even
        though our internal ``commit_range`` stores them with two.
        Returns ``None`` on 404.
        """
        path = f"/repos/{owner}/{repo}/compare/{base}...{head}"
        response = self._request_with_retry("GET", path)
        if response is None:
            return None
        return response.json()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request_with_retry(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response | None:
        """Issue a request, retrying on 429 / rate-limited 403.

        Returns the successful response, or ``None`` if the server
        returned 404. All other non-2xx responses raise via
        ``response.raise_for_status()``.
        """
        base_delay = 2.0
        max_delay = 60.0

        for attempt in range(self._max_retries):
            response = self._client.request(method, path, **kwargs)

            # 404 is a recoverable signal — the orchestrator marks
            # the row as "tried" and moves on.
            if response.status_code == 404:
                log.warning("GitHub 404 for %s — treating as missing", path)
                return None

            if _is_rate_limited(response):
                delay = self._get_retry_delay(response, base_delay, attempt, max_delay)
                log.warning(
                    "GitHub rate-limited on %s (status=%d), sleeping %.1fs "
                    "(attempt %d/%d)",
                    path,
                    response.status_code,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                time.sleep(delay)
                continue

            # Any other non-2xx — surface to caller, do not retry.
            response.raise_for_status()
            _maybe_warn_low_rate_limit(response.headers)
            return response

        log.error(
            "GitHub rate-limit retries exhausted for %s after %d attempts",
            path,
            self._max_retries,
        )
        raise RateLimitExceededError(
            f"Rate-limit retries exhausted for {path} after {self._max_retries} attempts"
        )

    @staticmethod
    def _get_retry_delay(
        response: httpx.Response,
        base_delay: float,
        attempt: int,
        max_delay: float,
    ) -> float:
        """Pick a sleep duration honoring server hints first."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), max_delay)
            except ValueError:
                pass

        # X-RateLimit-Reset is a unix epoch; compute time-to-reset.
        reset = response.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                delta = float(reset) - time.time()
                if 0 < delta <= max_delay:
                    return delta
            except ValueError:
                pass

        # Exponential backoff + ±10% jitter.
        delay = min(base_delay * (2 ** attempt), max_delay)
        jitter = delay * 0.1 * (2 * random.random() - 1)
        return max(0.0, delay + jitter)


def _is_rate_limited(response: httpx.Response) -> bool:
    """Detect 429 and 403-with-rate-limit-signal responses.

    GitHub uses 403 for secondary rate limits with a message body
    containing "rate limit"; the auth-failure path also returns 403,
    so we additionally guard on ``X-RateLimit-Remaining == 0`` /
    presence of ``Retry-After`` to avoid retrying real 403s forever.
    """
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if response.headers.get("Retry-After"):
        return True
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            if int(remaining) <= 0:
                return True
        except ValueError:
            pass
    return False


def _maybe_warn_low_rate_limit(headers: Mapping[str, str]) -> None:
    """Emit a WARNING if the user is close to their hourly quota."""
    remaining = headers.get("X-RateLimit-Remaining")
    if remaining is None:
        return
    try:
        remaining_int = int(remaining)
    except ValueError:
        return
    if remaining_int < RATE_LIMIT_WARN_THRESHOLD:
        log.warning(
            "GitHub rate-limit low: %d requests remaining (threshold=%d). "
            "Reset header: %s",
            remaining_int,
            RATE_LIMIT_WARN_THRESHOLD,
            headers.get("X-RateLimit-Reset", "unknown"),
        )


__all__ = [
    "GitHubClient",
    "RateLimitExceededError",
    "GITHUB_API_BASE",
    "RATE_LIMIT_WARN_THRESHOLD",
]
