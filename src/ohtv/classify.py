"""Conversation classification helpers.

Populates ``conversation_human_input.initial_prompt_source`` (created by
migration 016, defaulted to ``'unknown'``) with one of
``'human' | 'automation' | 'unknown'``.

This is the pure data-layer module backing ``ohtv classify``. It has no
Click / Rich dependencies so it can be unit-tested directly against an
in-memory SQLite connection with the migration chain replayed, and so
future reports (#81 velocity, #82 charting, a follow-up
``ohtv report classification``) can reuse the same helpers without
pulling in CLI plumbing.

Design notes (issue #83):

* **Bulk operations only touch ``initial_prompt_source = 'unknown'`` rows.**
  Manual single-conversation overrides are the only path that may flip an
  already-classified row. This is what makes ``--no-followups`` /
  ``--has-followups`` safe to run more than once: re-running reports
  ``0`` changed instead of clobbering prior overrides.

* **Conversation IDs are normalised (dashes stripped) before any DB
  lookup**, per AGENTS.md item #14. The DB stores IDs without dashes;
  callers may pass either form.

* **Missing ``conversation_human_input`` rows are refused, not stubbed.**
  If the ``human_input`` stage has not yet run for a given conversation,
  ``set_single`` raises :class:`MissingHumanInputRowError` with an
  actionable message. Silent inserts would mask the real issue (the
  ingestion pipeline didn't finish) and would also be a footgun for
  downstream LOC fetching (#80) and the velocity report (#81), both of
  which assume the row's word counts reflect the actual events.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

# Allowed values for ``initial_prompt_source``. Mirrors the
# ``CHECK(initial_prompt_source IN (...))`` constraint in migration 016
# so callers can ``from ohtv.classify import VALID_SOURCES`` and feed it
# straight into ``click.Choice``.
VALID_SOURCES: tuple[str, ...] = ("human", "automation", "unknown")

Source = Literal["human", "automation", "unknown"]

# Heuristic filter names. Kept as string constants (not an enum) for
# easy use as Click ``flag_value`` and clean error messages.
FILTER_NO_FOLLOWUPS = "no_followups"
FILTER_HAS_FOLLOWUPS = "has_followups"
HeuristicFilter = Literal["no_followups", "has_followups"]


class ClassifyError(Exception):
    """Base class for classification errors raised by this module."""


class MissingHumanInputRowError(ClassifyError):
    """Raised by :func:`set_single` when no human-input row exists yet."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(
            f"No conversation_human_input row for conversation {conversation_id!r}. "
            "Run 'ohtv db process human_input' first."
        )


class InvalidSourceError(ClassifyError):
    """Raised when a caller passes a ``source`` outside :data:`VALID_SOURCES`."""

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__(
            f"Invalid --source value {source!r}; must be one of {VALID_SOURCES!r}."
        )


@dataclass(frozen=True)
class UnknownRow:
    """One conversation still classified as ``'unknown'``.

    ``repo`` is the FQN (``owner/repo``) of the lexicographically first
    linked repository, or ``None`` if the conversation has no repo links.
    The lex-first choice keeps the output stable without committing to a
    particular ordering semantic; downstream consumers that need
    multi-repo handling should query the DB directly.
    """

    conversation_id: str
    short_id: str
    created_at: str | None
    repo: str | None
    followup_message_count: int
    title: str | None


@dataclass(frozen=True)
class SingleResult:
    """Outcome of :func:`set_single`."""

    conversation_id: str
    previous_source: str
    new_source: str
    changed: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_conv_id(conv_id: str) -> str:
    """Strip dashes from a conversation ID (per AGENTS.md item #14)."""
    return conv_id.replace("-", "")


def _validate_source(source: str) -> None:
    if source not in VALID_SOURCES:
        raise InvalidSourceError(source)


def _followups_predicate(filter_: HeuristicFilter) -> str:
    """Return the SQL predicate fragment for a heuristic filter.

    Raises ``ValueError`` for an unknown filter so we never silently
    construct an empty WHERE clause that would match everything.
    """
    if filter_ == FILTER_NO_FOLLOWUPS:
        return "followup_message_count = 0"
    if filter_ == FILTER_HAS_FOLLOWUPS:
        return "followup_message_count >= 1"
    raise ValueError(
        f"Unknown heuristic filter {filter_!r}; expected one of "
        f"({FILTER_NO_FOLLOWUPS!r}, {FILTER_HAS_FOLLOWUPS!r})."
    )


def _repo_ids_for_filter(
    conn: sqlite3.Connection, repo_filter: str
) -> tuple[list[int], list[str]]:
    """Resolve a ``--repo`` filter to a list of ``repositories.id`` values.

    Mirrors :func:`ohtv.filters.get_conversation_ids_for_repo` but stays
    inside the provided connection (the unit tests run against in-memory
    DBs, not the user's ``~/.ohtv/index.db``).

    The match strategy is intentionally narrow:

    * If the filter contains ``://`` we treat it as a canonical URL and
      match it exactly.
    * Otherwise we match against ``fqn`` (``owner/repo``) exactly first,
      and fall back to ``short_name`` (``repo``) — both as exact matches.
      Substring / glob matching is not supported here on purpose so
      bulk writes can never widen unexpectedly.

    Returns ``(repo_ids, matched_fqns)``. Empty lists mean "no repos
    matched"; callers should treat this as a no-op rather than as "all
    repos".
    """
    pattern = repo_filter.strip()
    if not pattern:
        return [], []

    if "://" in pattern:
        cur = conn.execute(
            "SELECT id, fqn FROM repositories WHERE canonical_url = ?",
            (pattern,),
        )
    elif "/" in pattern:
        cur = conn.execute(
            "SELECT id, fqn FROM repositories WHERE fqn = ?",
            (pattern,),
        )
    else:
        cur = conn.execute(
            "SELECT id, fqn FROM repositories WHERE short_name = ?",
            (pattern,),
        )

    rows = cur.fetchall()
    if not rows:
        return [], []

    ids: list[int] = []
    fqns: list[str] = []
    for row in rows:
        # Support both Row and tuple cursors.
        ids.append(row["id"] if isinstance(row, sqlite3.Row) else row[0])
        fqns.append(row["fqn"] if isinstance(row, sqlite3.Row) else row[1])
    return ids, fqns


def _repo_subselect_clause(repo_ids: list[int]) -> tuple[str, list[int]]:
    """Build ``AND conversation_id IN (...)`` for a non-empty repo set.

    Returns ``("", [])`` for an empty repo set; callers should then
    short-circuit to a 0-row result rather than emit the clause and
    accidentally match every row.
    """
    if not repo_ids:
        return "", []
    placeholders = ",".join("?" for _ in repo_ids)
    clause = (
        " AND chi.conversation_id IN ("
        f"SELECT conversation_id FROM conversation_repos WHERE repo_id IN ({placeholders})"
        ")"
    )
    return clause, list(repo_ids)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_matching(
    conn: sqlite3.Connection,
    *,
    filter_: HeuristicFilter,
    repo: str | None = None,
) -> int:
    """Count rows a bulk apply with ``filter_`` would touch.

    Always restricted to ``initial_prompt_source = 'unknown'`` so the
    count matches the row count that
    :func:`apply_classification` would actually change.

    ``repo`` follows the same narrow exact-match rules as
    :func:`_repo_ids_for_filter`; an unknown repo yields ``0``.
    """
    predicate = _followups_predicate(filter_)

    repo_ids: list[int] = []
    if repo is not None:
        repo_ids, matched = _repo_ids_for_filter(conn, repo)
        if not matched:
            return 0

    repo_clause, repo_params = _repo_subselect_clause(repo_ids)

    sql = (
        f"SELECT COUNT(*) FROM conversation_human_input chi "
        f"WHERE initial_prompt_source = 'unknown' AND {predicate}{repo_clause}"
    )
    cur = conn.execute(sql, repo_params)
    return int(cur.fetchone()[0])


def apply_classification(
    conn: sqlite3.Connection,
    *,
    filter_: HeuristicFilter,
    source: Source,
    repo: str | None = None,
) -> int:
    """Apply ``source`` to all rows matching ``filter_``.

    Only updates rows where ``initial_prompt_source = 'unknown'`` —
    manual overrides are preserved. Returns the number of rows actually
    changed (which is ``0`` on a second identical run, by construction).
    """
    _validate_source(source)
    predicate = _followups_predicate(filter_)

    repo_ids: list[int] = []
    if repo is not None:
        repo_ids, matched = _repo_ids_for_filter(conn, repo)
        if not matched:
            return 0

    repo_clause, repo_params = _repo_subselect_clause(repo_ids)

    sql = (
        f"UPDATE conversation_human_input AS chi "
        f"SET initial_prompt_source = ? "
        f"WHERE initial_prompt_source = 'unknown' AND {predicate}{repo_clause}"
    )
    cur = conn.execute(sql, [source, *repo_params])
    conn.commit()
    return cur.rowcount or 0


def set_single(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    source: Source,
) -> SingleResult:
    """Override a single conversation's ``initial_prompt_source``.

    Unlike :func:`apply_classification`, this CAN flip an already-classified
    row (it is the manual override path). It refuses to act if no
    ``conversation_human_input`` row exists yet — see the module
    docstring for the rationale.
    """
    _validate_source(source)

    normalized = _normalize_conv_id(conversation_id)

    cur = conn.execute(
        "SELECT initial_prompt_source FROM conversation_human_input "
        "WHERE conversation_id = ?",
        (normalized,),
    )
    row = cur.fetchone()
    if row is None:
        raise MissingHumanInputRowError(normalized)
    previous = row["initial_prompt_source"] if isinstance(row, sqlite3.Row) else row[0]

    if previous == source:
        return SingleResult(
            conversation_id=normalized,
            previous_source=previous,
            new_source=source,
            changed=False,
        )

    conn.execute(
        "UPDATE conversation_human_input SET initial_prompt_source = ? "
        "WHERE conversation_id = ?",
        (source, normalized),
    )
    conn.commit()
    return SingleResult(
        conversation_id=normalized,
        previous_source=previous,
        new_source=source,
        changed=True,
    )


def list_unknown(
    conn: sqlite3.Connection,
    *,
    repo: str | None = None,
    limit: int | None = None,
) -> list[UnknownRow]:
    """List conversations still classified as ``'unknown'``.

    Sorted by ``conversations.created_at DESC`` so the most recent
    unclassified conversations show up first. ``NULL`` ``created_at``
    sorts to the end. Optional ``limit`` caps the result count.

    Joining ``conversation_repos`` with ``MIN(fqn)`` gives a stable
    single-repo display value even when a conversation touched multiple
    repos. Multi-repo conversations are still common but the table is
    primarily a "which one do I want to override next?" surface, not an
    authoritative repo listing.
    """
    repo_ids: list[int] = []
    if repo is not None:
        repo_ids, matched = _repo_ids_for_filter(conn, repo)
        if not matched:
            return []

    repo_clause, repo_params = _repo_subselect_clause(repo_ids)

    sql = f"""
        SELECT
            chi.conversation_id AS conversation_id,
            chi.followup_message_count AS followup_message_count,
            c.created_at AS created_at,
            c.title AS title,
            (
                SELECT MIN(r.fqn)
                FROM conversation_repos cr
                JOIN repositories r ON r.id = cr.repo_id
                WHERE cr.conversation_id = chi.conversation_id
            ) AS repo_fqn
        FROM conversation_human_input chi
        LEFT JOIN conversations c ON c.id = chi.conversation_id
        WHERE chi.initial_prompt_source = 'unknown'{repo_clause}
        ORDER BY c.created_at IS NULL, c.created_at DESC, chi.conversation_id
    """
    if limit is not None:
        sql += " LIMIT ?"
        repo_params = [*repo_params, int(limit)]

    cur = conn.execute(sql, repo_params)
    out: list[UnknownRow] = []
    for row in cur.fetchall():
        conv_id = (
            row["conversation_id"]
            if isinstance(row, sqlite3.Row)
            else row[0]
        )
        out.append(
            UnknownRow(
                conversation_id=conv_id,
                short_id=conv_id[:8],
                followup_message_count=(
                    row["followup_message_count"]
                    if isinstance(row, sqlite3.Row)
                    else row[1]
                ),
                created_at=(
                    row["created_at"] if isinstance(row, sqlite3.Row) else row[2]
                ),
                title=row["title"] if isinstance(row, sqlite3.Row) else row[3],
                repo=row["repo_fqn"] if isinstance(row, sqlite3.Row) else row[4],
            )
        )
    return out


__all__ = [
    "ClassifyError",
    "FILTER_HAS_FOLLOWUPS",
    "FILTER_NO_FOLLOWUPS",
    "HeuristicFilter",
    "InvalidSourceError",
    "MissingHumanInputRowError",
    "SingleResult",
    "Source",
    "UnknownRow",
    "VALID_SOURCES",
    "apply_classification",
    "count_matching",
    "list_unknown",
    "set_single",
]
