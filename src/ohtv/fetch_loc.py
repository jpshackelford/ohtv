"""Backfill ``change_refs`` LOC columns from the GitHub API (Issue #80).

This module orchestrates the row-by-row LOC backfill that powers the
Conversation Metrics velocity report (#81). It is intentionally split
from :mod:`ohtv.github_api` so the CLI can swap the HTTP client in
tests via dependency injection without monkey-patching.

Design highlights
-----------------

* **Source of truth is GitHub** — never compute LOC from local
  trajectory events (see issue body for rationale).
* **Idempotent by default** — rows where ``fetched_at`` is set and
  ``lines_added`` is populated (or status is a non-pending PR status)
  are skipped. ``--force`` ignores this. PRs whose previous status was
  ``open`` are re-fetched if older than 1 hour, since they may have
  merged since.
* **Graceful per-row errors** — 404/401/5xx do NOT abort the run; the
  row is marked as "tried" via ``fetched_at = now()`` and the loop
  continues. Exit non-zero only when every request failed.
* **Non-GitHub repos are skipped** without touching the row at all
  (we don't currently support GitLab / Bitbucket LOC).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import httpx

log = logging.getLogger("ohtv")


# Re-fetch threshold for ``status='open'`` PRs — they may have merged
# since the last attempt, but we don't want to hammer the API for
# never-merged stale PRs.
OPEN_PR_REFETCH_AGE = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class GitHubClientProtocol(Protocol):
    """Subset of :class:`ohtv.github_api.GitHubClient` we depend on."""

    def get_pr(self, owner: str, repo: str, pr_number: int) -> dict | None: ...

    def get_compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> dict | None: ...


@dataclass
class FetchResult:
    """Summary of a single ``fetch_loc`` run."""

    total_candidates: int = 0  # rows considered (after filter + cache predicate)
    fetched: int = 0  # successful HTTP -> DB write (incl. open/closed PRs)
    skipped_cached: int = 0  # cached, not re-fetched
    skipped_non_github: int = 0  # repos like gitlab.com / bitbucket
    skipped_unparseable: int = 0  # missing pr_number / commit_range / bad commit_range
    failed: int = 0  # HTTP error -> we still wrote fetched_at
    still_open: int = 0  # PRs that came back as still-open
    closed_unmerged: int = 0  # PRs that closed without merging
    repo_names: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """Return a CLI exit code.

        Returns 0 unless we actually attempted HTTP and every attempt
        failed. A run with zero candidates exits 0 — that's "nothing to
        do", not "broken".
        """
        attempted = self.fetched + self.failed
        if attempted == 0:
            return 0
        if self.fetched == 0 and self.failed > 0:
            return 1
        return 0


@dataclass(frozen=True)
class _CandidateRow:
    """A single row pulled from the ``change_refs`` join."""

    id: int
    repo_id: int
    canonical_url: str
    fqn: str
    change_type: str
    pr_number: int | None
    commit_range: str | None
    status: str
    fetched_at: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_GITHUB_HOST_RE = re.compile(r"^https?://(?:www\.)?github\.com/", re.IGNORECASE)
_OWNER_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+?)(?:\.git)?(?:[/#?]|$)",
    re.IGNORECASE,
)


def is_github_url(canonical_url: str | None) -> bool:
    """Return True iff ``canonical_url`` points at github.com."""
    if not canonical_url:
        return False
    return bool(_GITHUB_HOST_RE.match(canonical_url))


def parse_github_owner_repo(canonical_url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from a GitHub canonical URL."""
    match = _OWNER_REPO_RE.match(canonical_url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    repo = repo.removesuffix(".git")
    return owner, repo


def split_commit_range(commit_range: str) -> tuple[str, str] | None:
    """Split ``"abc..def"`` (our storage format) into ``("abc", "def")``."""
    if ".." not in commit_range:
        return None
    parts = commit_range.split("..", 1)
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def _now_iso() -> str:
    """Return UTC now() in ISO-8601 (matches SQLite ``datetime('now')``)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_fetched_at(fetched_at: str | None) -> datetime | None:
    if not fetched_at:
        return None
    try:
        # SQLite ``datetime('now')`` returns ``YYYY-MM-DD HH:MM:SS`` (no tz);
        # our own writer uses ISO with offset. Handle both.
        cleaned = fetched_at.replace("Z", "+00:00")
        if " " in cleaned and "T" not in cleaned:
            cleaned = cleaned.replace(" ", "T")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _is_cached(row: _CandidateRow, now: datetime) -> bool:
    """Idempotency predicate.

    Mirrors the issue body's spec:

    .. code::

        fetched_at IS NOT NULL AND (
            (change_type = 'pr'          AND status IN ('merged','open','closed')) OR
            (change_type = 'direct_push' AND lines_added IS NOT NULL)
        )

    Plus: ``status='open'`` rows older than ``OPEN_PR_REFETCH_AGE`` are
    treated as NOT cached (they may have merged since).
    """
    if row.fetched_at is None:
        return False
    if row.change_type == "pr":
        if row.status not in {"merged", "open", "closed"}:
            return False
        if row.status == "open":
            fetched = _parse_fetched_at(row.fetched_at)
            if fetched is None or now - fetched >= OPEN_PR_REFETCH_AGE:
                return False
        return True
    # direct_push
    # We piggy-back on lines_added IS NOT NULL via the candidate query —
    # so if a direct_push row is in our list, it's not cached.
    return False


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _select_candidates(
    conn: sqlite3.Connection,
    *,
    repo_id: int | None,
    force: bool,
    limit: int | None,
) -> list[_CandidateRow]:
    """Pull candidate rows from ``change_refs`` ⨝ ``repositories``.

    The ``force=True`` mode selects all rows for the repo filter (or all
    repos). Default mode applies the cache predicate at the SQL level
    so we don't pay the round-trip for trivially-skipped rows. The
    open-PR re-fetch heuristic is applied in Python (we don't want to
    bake ``now()`` arithmetic into the SQL).
    """
    sql = [
        "SELECT cr.id, cr.repo_id, r.canonical_url, r.fqn,",
        "       cr.change_type, cr.pr_number, cr.commit_range,",
        "       cr.status, cr.fetched_at, cr.lines_added",
        "FROM change_refs cr",
        "JOIN repositories r ON r.id = cr.repo_id",
        "WHERE 1=1",
    ]
    params: list[object] = []

    if repo_id is not None:
        sql.append("AND cr.repo_id = ?")
        params.append(repo_id)

    if not force:
        # Cache predicate (SQL-side). Note we DO NOT filter out rows
        # with ``status='open'`` here, even though they have
        # ``fetched_at`` set — the "open-PR re-fetch after 1 hour"
        # heuristic is applied in Python (see :func:`_is_cached`) and
        # needs the row in hand to compare timestamps. We do include
        # them in the candidate set so the orchestrator can choose
        # to skip them or re-fetch them.
        sql.append("""
            AND NOT (
                cr.fetched_at IS NOT NULL AND (
                    (cr.change_type = 'pr' AND cr.status IN ('merged','closed'))
                    OR
                    (cr.change_type = 'direct_push' AND cr.lines_added IS NOT NULL)
                )
            )
        """)

    sql.append("ORDER BY cr.id ASC")
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(limit)

    cursor = conn.execute("\n".join(sql), params)
    return [
        _CandidateRow(
            id=row["id"],
            repo_id=row["repo_id"],
            canonical_url=row["canonical_url"],
            fqn=row["fqn"],
            change_type=row["change_type"],
            pr_number=row["pr_number"],
            commit_range=row["commit_range"],
            status=row["status"],
            fetched_at=row["fetched_at"],
        )
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Per-row processing
# ---------------------------------------------------------------------------


def _update_pr_row(
    conn: sqlite3.Connection,
    row_id: int,
    pr_data: dict,
    now: str,
) -> str:
    """Apply a PR API response to ``change_refs``.

    Returns one of ``"merged"``, ``"open"``, ``"closed"`` so the caller
    can keep running counts.
    """
    merged = bool(pr_data.get("merged"))
    state = pr_data.get("state", "open")
    if merged:
        status = "merged"
        conn.execute(
            """
            UPDATE change_refs
            SET status = ?, merged_at = ?, lines_added = ?,
                lines_removed = ?, files_changed = ?, fetched_at = ?
            WHERE id = ?
            """,
            (
                status,
                pr_data.get("merged_at"),
                pr_data.get("additions"),
                pr_data.get("deletions"),
                pr_data.get("changed_files"),
                now,
                row_id,
            ),
        )
        return status

    status = "open" if state == "open" else "closed"
    conn.execute(
        """
        UPDATE change_refs
        SET status = ?, merged_at = NULL, lines_added = NULL,
            lines_removed = NULL, files_changed = NULL, fetched_at = ?
        WHERE id = ?
        """,
        (status, now, row_id),
    )
    return status


def _update_compare_row(
    conn: sqlite3.Connection,
    row_id: int,
    compare_data: dict,
    now: str,
) -> None:
    """Apply a compare API response to a ``direct_push`` row."""
    files = compare_data.get("files") or []
    lines_added = sum(int(f.get("additions") or 0) for f in files)
    lines_removed = sum(int(f.get("deletions") or 0) for f in files)
    files_changed = len(files)

    conn.execute(
        """
        UPDATE change_refs
        SET status = 'merged', lines_added = ?, lines_removed = ?,
            files_changed = ?, fetched_at = ?
        WHERE id = ?
        """,
        (lines_added, lines_removed, files_changed, now, row_id),
    )


def _mark_tried(conn: sqlite3.Connection, row_id: int, now: str) -> None:
    """Record an HTTP failure as "tried" so we don't retry every run.

    We leave LOC columns untouched so a future ``--force`` run can
    repopulate them once the issue is resolved.
    """
    conn.execute(
        "UPDATE change_refs SET fetched_at = ? WHERE id = ?",
        (now, row_id),
    )


def _process_pr_row(
    conn: sqlite3.Connection,
    client: GitHubClientProtocol,
    row: _CandidateRow,
    owner: str,
    repo: str,
    now_iso: str,
    result: FetchResult,
) -> tuple[str | None, str | None]:
    """Process a single ``change_type='pr'`` row.

    Returns ``(msg, new_status)`` where ``msg`` is the progress label to
    display (or ``None`` if the row was skipped before any HTTP call) and
    ``new_status`` is the post-update PR status (or ``None`` on 404).

    Behavior mirrors the original inline branch in :func:`fetch_loc`:
    missing ``pr_number`` is logged + counted as ``skipped_unparseable``
    and returns ``(None, None)`` so the caller does not emit a progress
    update. May raise ``httpx.HTTPStatusError`` (handled by the caller).
    """
    if row.pr_number is None:
        log.warning(
            "fetch-loc: PR row %d missing pr_number — skipping",
            row.id,
        )
        result.skipped_unparseable += 1
        return None, None

    msg = f"{owner}/{repo}#{row.pr_number}"
    pr_data = client.get_pr(owner, repo, row.pr_number)
    if pr_data is None:
        _mark_tried(conn, row.id, now_iso)
        result.failed += 1
        log.warning("fetch-loc: %s returned 404 — marked tried", msg)
        return msg, None

    new_status = _update_pr_row(conn, row.id, pr_data, now_iso)
    result.fetched += 1
    if new_status == "open":
        result.still_open += 1
    elif new_status == "closed":
        result.closed_unmerged += 1
    return msg, new_status


def _process_push_row(
    conn: sqlite3.Connection,
    client: GitHubClientProtocol,
    row: _CandidateRow,
    owner: str,
    repo: str,
    now_iso: str,
    result: FetchResult,
) -> tuple[str | None, str | None]:
    """Process a single ``change_type='direct_push'`` row.

    Returns ``(msg, new_status)``. ``new_status`` is always ``None`` for
    direct pushes (there is no PR-style status to surface) but is
    included for symmetry with :func:`_process_pr_row`.

    Skips (missing ``commit_range`` or malformed range) return
    ``(None, None)`` so the caller does not emit a progress update,
    matching the pre-refactor ``continue`` behavior. May raise
    ``httpx.HTTPStatusError`` (handled by the caller).
    """
    if row.commit_range is None:
        log.warning(
            "fetch-loc: direct_push row %d missing commit_range",
            row.id,
        )
        result.skipped_unparseable += 1
        return None, None

    shas = split_commit_range(row.commit_range)
    if shas is None:
        log.warning(
            "fetch-loc: malformed commit_range %r — skipping",
            row.commit_range,
        )
        result.skipped_unparseable += 1
        return None, None

    base, head = shas
    msg = f"{owner}/{repo} {base[:7]}..{head[:7]}"
    cmp_data = client.get_compare(owner, repo, base, head)
    if cmp_data is None:
        _mark_tried(conn, row.id, now_iso)
        result.failed += 1
        log.warning("fetch-loc: %s returned 404 — marked tried", msg)
        return msg, None

    _update_compare_row(conn, row.id, cmp_data, now_iso)
    result.fetched += 1
    return msg, None


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


ProgressCallback = Callable[[int, int, str], None]


def fetch_loc(
    conn: sqlite3.Connection,
    *,
    client: GitHubClientProtocol,
    repo_id: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    on_progress: ProgressCallback | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> FetchResult:
    """Backfill LOC columns for ``change_refs`` rows.

    Args:
        conn: SQLite connection (with ``row_factory = sqlite3.Row``).
        client: GitHub client (implements :class:`GitHubClientProtocol`).
            In tests this is the real :class:`ohtv.github_api.GitHubClient`
            wired up against ``pytest-httpx``.
        repo_id: If provided, restrict to one repo.
        force: Ignore the cache predicate; re-fetch all matching rows.
        dry_run: Do not call HTTP and do not write to the DB; just count.
        limit: Cap the number of rows processed.
        on_progress: Optional callback ``(completed, total, message)``
            for progress-bar wiring.
        now_provider: Inject a clock for deterministic tests.

    Returns:
        :class:`FetchResult` summarising the run.
    """
    now_dt = (now_provider or (lambda: datetime.now(timezone.utc)))()
    now_iso = now_dt.replace(microsecond=0).isoformat()

    candidates = _select_candidates(
        conn, repo_id=repo_id, force=force, limit=limit
    )
    result = FetchResult()
    result.total_candidates = len(candidates)
    result.repo_names = sorted({row.fqn for row in candidates})

    if not candidates:
        if on_progress is not None:
            on_progress(0, 0, "no candidates")
        return result

    if dry_run:
        # No HTTP, no DB writes — just count and return.
        if on_progress is not None:
            on_progress(len(candidates), len(candidates), "dry-run")
        return result

    total = len(candidates)
    for index, row in enumerate(candidates, start=1):
        # Cache predicate (post-SQL): respects open-PR refetch window.
        if not force and _is_cached(row, now_dt):
            result.skipped_cached += 1
            if on_progress is not None:
                on_progress(index, total, f"cached {row.fqn}")
            continue

        # Non-GitHub repo — skip entirely (do not touch fetched_at).
        if not is_github_url(row.canonical_url):
            log.info(
                "fetch-loc: skipping non-GitHub repo %s (%s)",
                row.fqn,
                row.canonical_url,
            )
            result.skipped_non_github += 1
            if on_progress is not None:
                on_progress(index, total, f"non-github {row.fqn}")
            continue

        parsed = parse_github_owner_repo(row.canonical_url)
        if parsed is None:
            log.warning(
                "fetch-loc: cannot parse owner/repo from %s — skipping",
                row.canonical_url,
            )
            result.skipped_unparseable += 1
            if on_progress is not None:
                on_progress(index, total, f"unparseable {row.canonical_url}")
            continue
        owner, repo = parsed

        try:
            if row.change_type == "pr":
                msg, _ = _process_pr_row(
                    conn, client, row, owner, repo, now_iso, result
                )
                if msg and on_progress is not None:
                    on_progress(index, total, msg)
            elif row.change_type == "direct_push":
                msg, _ = _process_push_row(
                    conn, client, row, owner, repo, now_iso, result
                )
                if msg and on_progress is not None:
                    on_progress(index, total, msg)
            else:  # pragma: no cover — schema CHECK constraint prevents this
                log.warning(
                    "fetch-loc: unknown change_type %r — skipping",
                    row.change_type,
                )
                result.skipped_unparseable += 1
                continue

        except httpx.HTTPStatusError as exc:
            # 401/5xx: mark as tried, log, continue.
            status = exc.response.status_code if exc.response is not None else 0
            log.warning(
                "fetch-loc: HTTP %d on change_ref %d (%s) — marked tried",
                status,
                row.id,
                row.fqn,
            )
            _mark_tried(conn, row.id, now_iso)
            result.failed += 1
            if on_progress is not None:
                on_progress(index, total, f"HTTP {status}")

        # Commit after each row so a SIGINT mid-run doesn't lose work.
        conn.commit()

    return result


__all__ = [
    "FetchResult",
    "GitHubClientProtocol",
    "OPEN_PR_REFETCH_AGE",
    "fetch_loc",
    "is_github_url",
    "parse_github_owner_repo",
    "split_commit_range",
]
