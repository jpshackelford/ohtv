"""Conversation classification helpers.

Populates ``conversation_human_input.initial_prompt_source`` (created by
migration 016, widened by migration 022 — see issue #126) with one of
``'human' | 'automation' | 'unknown' | 'sub_agent'``.

Of those four values, the first three (``'human'`` / ``'automation'`` /
``'unknown'``) are the operator-facing *trigger* answers exposed via the
CLI ``--source`` flag. The fourth, ``'sub_agent'``, is a
**system-managed** label that ``classify`` writes automatically for every
sub-conversation — see :func:`apply_sub_classification`. It is not a
valid value for ``--source`` because a sub-conversation has no trigger of
its own (it is an extension of its parent, not an independently
triggered run). The parent's actual trigger type is always recoverable
by walking up ``conversations.parent_conversation_id`` to the root.

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

# Operator-facing values for ``--source``. Intentionally **excludes**
# ``'sub_agent'``: that label is system-managed (see
# :func:`apply_sub_classification`) and is not selectable by the
# operator. Callers can ``from ohtv.classify import VALID_SOURCES`` and
# feed it straight into ``click.Choice``.
VALID_SOURCES: tuple[str, ...] = ("human", "automation", "unknown")

Source = Literal["human", "automation", "unknown"]

# System-managed value for sub-conversations (issue #126). Authorized
# by the widened CHECK constraint in migration 022. Lives outside
# :data:`VALID_SOURCES` on purpose: ``set_single`` and the heuristic
# bulk path must never accept ``'sub_agent'`` as a user choice.
SUB_AGENT_SOURCE = "sub_agent"

# Heuristic filter names. Kept as string constants (not an enum) for
# easy use as Click ``flag_value`` and clean error messages.
FILTER_NO_FOLLOWUPS = "no_followups"
FILTER_HAS_FOLLOWUPS = "has_followups"
HeuristicFilter = Literal["no_followups", "has_followups"]


class ClassifyError(Exception):
    """Base class for classification errors raised by this module."""


class MissingHumanInputRowError(ClassifyError):
    """Raised by :func:`set_single` when no human-input row exists yet.

    Distinct from :class:`NoSuchConversationError`: the conversation row
    exists in ``conversations``, but the ``human_input`` processing stage
    has not produced a ``conversation_human_input`` row for it yet.
    """

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(
            f"No conversation_human_input row for conversation {conversation_id!r}. "
            "Run 'ohtv db process human_input' first."
        )


class NoSuchConversationError(ClassifyError):
    """Raised when a conversation ID (or short prefix) matches no row.

    Distinct from :class:`MissingHumanInputRowError`: the conversation
    itself isn't indexed in ``conversations``, so the caller most likely
    has a typo or hasn't run ``ohtv db scan`` yet.
    """

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(
            f"No such conversation {conversation_id!r}. "
            "Check the ID or run 'ohtv db scan' to index new conversations."
        )


class AmbiguousConversationIdError(ClassifyError):
    """Raised when a short-ID prefix matches more than one conversation.

    Mirrors the convention used by ``_find_conversation_dir`` (AGENTS.md
    item #14): callers may pass a unique prefix, but ambiguous prefixes
    must be rejected loudly so they don't silently target the wrong row.
    """

    def __init__(self, conversation_id: str, matches: list[str]) -> None:
        self.conversation_id = conversation_id
        self.matches = matches
        sample = ", ".join(m[:12] for m in matches[:5])
        more = f" (+{len(matches) - 5} more)" if len(matches) > 5 else ""
        super().__init__(
            f"Ambiguous conversation ID {conversation_id!r}: "
            f"{len(matches)} matches ({sample}{more}). "
            "Provide more characters."
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


def _resolve_conversation_id(
    conn: sqlite3.Connection, conv_id: str
) -> str:
    """Resolve a possibly-short conversation ID to its full DB form.

    Accepts either a full 32-char ID (with or without dashes) or a unique
    short prefix, mirroring ``_find_conversation_dir`` (AGENTS.md item
    #14). Returns the full normalised ID on success.

    Raises:
        NoSuchConversationError: no row in ``conversations`` matches the
            input (typo, fabricated ID, or ``db scan`` hasn't run yet).
        AmbiguousConversationIdError: the input is a prefix that matches
            more than one conversation; caller should pass more chars.
    """
    normalized = _normalize_conv_id(conv_id)

    # Fast path: exact match. Cheap and unambiguous for full IDs.
    cur = conn.execute(
        "SELECT id FROM conversations WHERE id = ?",
        (normalized,),
    )
    row = cur.fetchone()
    if row is not None:
        return row["id"] if isinstance(row, sqlite3.Row) else row[0]

    # Prefix path: LIKE 'prefix%' for short-ID lookup. SQLite escapes the
    # ``%`` only inside the literal, so a literal ``%`` in the prefix
    # would be unusual but technically broaden the match — guard against
    # it by escaping. Hex-only IDs in practice means this is paranoia.
    safe_prefix = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    cur = conn.execute(
        "SELECT id FROM conversations WHERE id LIKE ? ESCAPE '\\' LIMIT 11",
        (safe_prefix + "%",),
    )
    matches = [r["id"] if isinstance(r, sqlite3.Row) else r[0] for r in cur.fetchall()]

    if not matches:
        raise NoSuchConversationError(conv_id)
    if len(matches) > 1:
        raise AmbiguousConversationIdError(conv_id, matches)
    return matches[0]


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


def _assert_parent_column_present(conn: sqlite3.Connection) -> None:
    """Guardrail: verify migration 019 (``parent_conversation_id``) has run.

    Mirrors the #123 / #124 / #125 pattern. Raised at runtime (not
    import time) so the CLI can format a friendly error and exit before
    any classification work happens.

    The issue body (#126) refers to this as "migration 018" because the
    parent column was committed to ``018_parent_conversation_id.py``
    pre-merge; it was renumbered to ``019_parent_conversation_id.py``
    when the set-diff-sync schema landed first. The check is on the
    column name, not the migration filename, so the error message
    points users at the actual repair path (``ohtv db scan`` reapplies
    pending migrations regardless of number).
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}
    if "parent_conversation_id" not in cols:
        raise RuntimeError(
            "classify requires migration 019 (parent_conversation_id); "
            "run 'ohtv db scan' to apply pending migrations"
        )


def apply_sub_classification(conn: sqlite3.Connection) -> int:
    """Set ``initial_prompt_source='sub_agent'`` on every sub-conversation.

    A "sub-conversation" is one whose ``conversations.parent_conversation_id``
    is non-NULL (populated by migration 019, originally proposed as 018
    in #108).

    Why a dedicated ``'sub_agent'`` value rather than reusing
    ``'automation'``: a sub-conversation has no trigger of its own — it
    is a delegated continuation of its parent. ``'automation'`` already
    means something specific (an automation run dispatched the
    conversation, cron / webhook), and conflating those two would
    silently slurp every sub-agent delegation into the automation-run
    bucket of ``report velocity`` / ``report weekly-counts``. The
    parent's actual trigger type is always recoverable by walking up
    ``parent_conversation_id``, so nothing is lost by giving subs their
    own label. (The widened CHECK constraint lives in migration 022;
    see issue #126 PR discussion for the design rationale.)

    Unlike :func:`apply_classification` (#83), this CAN overwrite rows
    whose current value is ``'human'``, ``'automation'``, or
    ``'unknown'`` — those values are wrong for subs and the helper is
    idempotent in either direction. Returns the number of rows actually
    changed (``0`` on a second identical run by construction).

    Self-healing: every ``ohtv classify`` invocation runs this before
    its mode-specific work, so any residual mis-classification (e.g.
    from a pre-fix ``--has-followups --source human`` bulk run that
    flipped subs to ``'human'`` because subs frequently have follow-ups
    from the orchestrating agent) is corrected automatically. No new
    flag is added.

    The ``UPDATE ... WHERE EXISTS (...)`` form silently skips subs that
    have no ``conversation_human_input`` row yet (the ``human_input``
    stage hasn't processed them) — there's nothing to update. No
    exception, no special-case branch.
    """
    cur = conn.execute(
        """
        UPDATE conversation_human_input AS chi
        SET initial_prompt_source = 'sub_agent'
        WHERE chi.initial_prompt_source <> 'sub_agent'
          AND EXISTS (
              SELECT 1 FROM conversations c
              WHERE c.id = chi.conversation_id
                AND c.parent_conversation_id IS NOT NULL
          )
        """
    )
    conn.commit()
    return cur.rowcount or 0


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

    Accepts a full 32-char conversation ID (with or without dashes) or a
    unique short prefix (mirrors ``_find_conversation_dir``; AGENTS.md
    item #14). Raises :class:`NoSuchConversationError` if the input
    matches no conversation, or :class:`AmbiguousConversationIdError` if
    it matches more than one — these are distinct from
    :class:`MissingHumanInputRowError`, which means the conversation
    exists but the ``human_input`` stage hasn't run for it.
    """
    _validate_source(source)

    # Resolve first so "no such conversation" is a distinct error from
    # "human_input stage hasn't run". This is what makes the README's
    # ``classify --list-unknown -1 | head -5 | xargs ohtv classify {}``
    # pipeline work: ``-1`` emits 8-char short IDs.
    normalized = _resolve_conversation_id(conn, conversation_id)

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
    "SUB_AGENT_SOURCE",
    "Source",
    "UnknownRow",
    "VALID_SOURCES",
    "_assert_parent_column_present",
    "apply_classification",
    "apply_sub_classification",
    "count_matching",
    "list_unknown",
    "set_single",
]
