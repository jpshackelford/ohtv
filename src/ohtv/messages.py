"""User-message browse surface for ``ohtv messages`` (Issue #181).

This module provides the pure-Python core of the ``ohtv messages``
command: list every user message within a date range, grouped by
conversation, newest conversation first.

It is the sibling of :mod:`ohtv.errors` / :mod:`ohtv.actions` /
:mod:`ohtv.fetch_loc` — kept out of :mod:`ohtv.cli` so the message-
extraction logic stays unit-testable without Click.

Two pass strategy (see Issue #181 technical comment for the full
write-up):

1. **Pass 1 — DB candidates** via
   :meth:`ohtv.db.stores.ConversationStore.list_by_event_date_range`
   (the SINGLE owner of the engagement-overlap WHERE clause, AGENTS.md
   item #35). Returns conversations whose
   ``[first_event_ts, last_event_ts]`` engagement span overlaps
   ``[since, until]`` — a strict superset of "conversations with ≥1
   user message in range". We then pass that list through the existing
   ``--repo`` / ``--label`` filters and through the pagination
   (offset + limit).

2. **Pass 2 — events from disk** for *displayed* conversations only.
   We load each surviving conversation's ``events/*.json`` file once,
   keep only ``source == "user"`` ``MessageEvent`` rows whose
   timestamp lies in ``[since, until]``, truncate the conversation
   from the output if zero such messages survive, and yield the rest.

The cost ceiling is ``offset + limit`` JSON-loaded conversations per
invocation. With the default ``-n 10``, a 7-day query loads ~10
conversations × ~50 events ≈ ~500 JSON parses — far below the cost of
a synchronous LLM call.

Output rendering (text / json / raw) lives in :mod:`ohtv.cli` so it can
reuse the existing ``console`` Rich glue; this module only produces
the structured :class:`ConversationMessages` records that the CLI
formats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ohtv.config import Config
    from ohtv.sources.base import ConversationInfo


# Default truncation cutoff for text-mode rendering. Matches the AC in
# Issue #181. ``json`` and ``raw`` always carry the full text.
TEXT_TRUNCATION_CHARS = 500


@dataclass
class UserMessage:
    """A single user message extracted from a conversation's event log.

    Fields are denormalized (conversation context is carried alongside
    the message) so the JSON / raw renderers don't need to look back at
    the parent conversation. The text-mode renderer groups by
    ``conv_id`` and prints the conversation header once per group via
    :class:`ConversationMessages`.
    """

    conv_id: str
    """Conversation id (normalized — dashless, 32-char hex).

    Stored dashless so it matches the directory name on disk and the
    DB primary key. The CLI renders ``conv_id[:8]`` (or similar
    short form) for human-readable headers.
    """

    conv_title: str | None
    """Conversation title, or ``None`` if the conversation has no
    title yet (fresh sync, no first-user-message fallback applied)."""

    conv_created_at: datetime | None
    """The conversation's ``created_at``. Distinct from the per-
    message ``timestamp`` — Issue #181 explicitly filters by event
    timestamp, not ``created_at``, but we still render ``created_at``
    in the conversation header for context."""

    source: str
    """``"local"`` or ``"cloud"``, propagated from the parent
    conversation row."""

    event_count: int
    """Number of events in the parent conversation, displayed in the
    text-mode header for context."""

    timestamp: datetime
    """The user message's own ``timestamp`` field. The date predicate
    in :func:`extract_user_messages` runs against this value."""

    text: str
    """Full message text. Multi-part ``llm_message.content`` arrays
    are joined with ``\\n`` (matching
    :func:`ohtv.cli._extract_message_content`). Truncation is the
    renderer's responsibility — this dataclass always carries the
    untruncated text."""


@dataclass
class ConversationMessages:
    """All in-range user messages for a single conversation.

    Returned by :func:`collect_messages` as a list, one entry per
    conversation that has at least one matching message. Conversations
    with zero matching messages are dropped before this list is
    handed back (they're still counted toward
    ``total_conversations`` though — pagination is by conversation,
    not by message).
    """

    conv: "ConversationInfo"
    """The parent conversation row (carries id, title,
    created_at, event_count, source — all the fields the text-mode
    header needs)."""

    messages: list[UserMessage] = field(default_factory=list)
    """In-range user messages, ordered by timestamp ascending. The
    text renderer prints them in this order under the conversation
    header."""


# ---------------------------------------------------------------------------
# Event extraction — Pass 2 of the two-pass design.
# ---------------------------------------------------------------------------


def _extract_message_content(event: dict) -> str:
    """Return the text payload of a user MessageEvent.

    Mirrors :func:`ohtv.cli._extract_message_content` verbatim — the
    same shape handling for ``llm_message.content`` (list of typed
    parts, plain string, or top-level ``content`` fallback). Kept as a
    private helper here so :mod:`ohtv.messages` does not depend on the
    Click monolith.
    """
    llm_msg = event.get("llm_message", {})
    content = llm_msg.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    if isinstance(content, str):
        return content

    # Fallback for direct content field on the event.
    return event.get("content", "")


def _parse_event_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string. Returns ``None`` on failure.

    Events are written with microseconds-and-no-zone (cloud) or with a
    trailing ``Z`` (some local CLI versions). We strip both before
    calling :meth:`datetime.fromisoformat` for compatibility with
    Python 3.10's stricter parser.
    """
    if not value:
        return None
    cleaned = value.rstrip("Z").split("+")[0]
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _load_events(conv_dir: Path) -> list[dict]:
    """Load all event JSON files from ``conv_dir/events`` in name order.

    Mirrors :func:`ohtv.cli._load_events`: ``sorted(glob)`` for
    deterministic order, malformed or unreadable files are silently
    skipped (the CLI absorbs the same exceptions on the same code
    path). Returns an empty list if the events directory is missing.
    """
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return []

    events: list[dict] = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            events.append(json.loads(event_file.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return events


def _is_aware(dt: datetime) -> bool:
    """Return ``True`` if ``dt`` carries a tzinfo."""
    return dt.tzinfo is not None


def _coerce_naive(dt: datetime) -> datetime:
    """Drop tzinfo on aware datetimes so comparisons stay total.

    Event timestamps in fixture data are naive (cloud writes them
    without a trailing ``Z`` zone). The CLI passes ``since`` / ``until``
    through :func:`ohtv.cli._parse_date_option` which can yield either
    aware or naive datetimes depending on input format. We coerce both
    sides to naive before comparison rather than risk a
    ``TypeError: can't compare offset-naive and offset-aware``.
    """
    return dt.replace(tzinfo=None) if _is_aware(dt) else dt


def extract_user_messages(
    conv: "ConversationInfo",
    conv_dir: Path,
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[UserMessage]:
    """Extract in-range user messages from a single conversation directory.

    Filters at the event level:

    * ``source == "user"`` (drops agent / environment events).
    * ``kind == "MessageEvent"`` (drops user-mode tool results, etc.
      — there shouldn't be any, but we're defensive).
    * Optional ``timestamp >= since`` and ``timestamp < until``
      (matching the existing CLI ``--since`` / ``--until`` half-open
      convention).

    Multi-part ``llm_message.content`` arrays are concatenated with
    ``\\n``. Events with malformed JSON or missing timestamps are
    skipped silently (the parent ``_load_events`` swallows the
    decode error; an event lacking a timestamp cannot be range-
    filtered and is dropped rather than guessed).

    Returns the surviving messages sorted by timestamp ascending — the
    same order :func:`collect_messages` and the text renderer expect.
    """
    norm_since = _coerce_naive(since) if since else None
    norm_until = _coerce_naive(until) if until else None

    out: list[UserMessage] = []
    for event in _load_events(conv_dir):
        if event.get("source") != "user":
            continue
        if event.get("kind") != "MessageEvent":
            continue

        ts = _parse_event_timestamp(event.get("timestamp"))
        if ts is None:
            continue

        norm_ts = _coerce_naive(ts)
        if norm_since is not None and norm_ts < norm_since:
            continue
        if norm_until is not None and norm_ts >= norm_until:
            continue

        text = _extract_message_content(event)
        # An empty user message is a Click "send" with no payload —
        # we still surface it; the renderer will show "(empty)" if
        # the consumer cares (out of scope for v1; we emit "").
        out.append(
            UserMessage(
                conv_id=conv.id.replace("-", ""),
                conv_title=conv.title,
                conv_created_at=conv.created_at,
                source=conv.source,
                event_count=conv.event_count or 0,
                timestamp=norm_ts,
                text=text,
            )
        )

    out.sort(key=lambda m: m.timestamp)
    return out


# ---------------------------------------------------------------------------
# Conversation aggregation — the public entry point for the CLI handler.
# ---------------------------------------------------------------------------


def _resolve_conversation_dir(
    config: "Config", conv: "ConversationInfo"
) -> Path | None:
    """Resolve a ConversationInfo to its on-disk directory.

    The DB stores ``conversations.location`` as the absolute (or
    config-relative) directory — but the value can become stale if the
    user moves the ohtv data dir. We prefer the canonical
    ``<source>_conversations_dir / <dir_name>`` layout (using
    ``conv.dir_name`` which is the dashless 32-char id, per AGENTS.md
    item #14), falling back to ``conv.location`` when that path
    doesn't exist.
    """
    dir_name = conv.dir_name or conv.id.replace("-", "")

    candidates: list[Path] = []
    if conv.source == "local":
        candidates.append(config.local_conversations_dir / dir_name)
    elif conv.source == "cloud":
        candidates.append(config.synced_conversations_dir / dir_name)
    else:  # Extra paths or unknown source — try both standard dirs.
        candidates.append(config.synced_conversations_dir / dir_name)
        candidates.append(config.local_conversations_dir / dir_name)

    # Extra conversation paths (rare, but supported).
    for extra in config.extra_conversation_paths:
        candidates.append(extra / dir_name)

    for cand in candidates:
        if cand.exists():
            return cand

    return None


def collect_messages(
    config: "Config",
    *,
    since: datetime | None,
    until: datetime | None,
    source: str | None,
    repo: str | None,
    label: str | None,
    include_subs: bool,
    limit: int | None,
    offset: int,
) -> tuple[list[ConversationMessages], int, int]:
    """Two-pass collection of in-range user messages.

    Pass 1 (DB):

    * Open a ``get_connection()`` and call
      :meth:`ConversationStore.list_by_event_date_range` — the single
      SQL owner introduced in #180. This returns conversations whose
      engagement span overlaps ``[since, until]``, with the same
      ``source`` / ``include_subs`` filters the rest of the CLI uses.

    * Apply ``--repo`` / ``--label`` in Python via
      :func:`ohtv.cli._filter_by_repo` / :func:`ohtv.cli._filter_by_label`
      so we don't duplicate the join logic.

    * Apply ``--offset`` then ``--max`` (or ``--all``) at the
      conversation grain (AC #4: pagination is BY CONVERSATION).

    Pass 2 (FS): for each surviving conversation, load events from
    disk and keep the in-range user messages. Conversations that end
    up with zero such messages are dropped from the output but still
    counted toward ``total_conversations`` — that's what the user is
    paging through and what the footer hint reports.

    Returns:
        ``(displayed_groups, total_conversations, total_messages)``.

        * ``displayed_groups`` is the list of conversations that
          survive both the pagination window AND have ≥1 user message
          in range, sorted by most-recent in-range user message
          descending (newest first).
        * ``total_conversations`` is the count BEFORE applying
          ``offset`` / ``limit`` — the denominator in the
          "Showing K of N" footer. We use the DB candidate count for
          this rather than walking every conversation's events
          (which would defeat the cost ceiling).
        * ``total_messages`` is the count across the *displayed*
          groups only. The full-history count would require Pass 2
          over every candidate; we deliberately do not pay that cost.
    """
    from ohtv.conversations import _db_conv_to_info
    from ohtv.db import get_connection, get_db_path
    from ohtv.db.stores import ConversationStore

    # ---- Pass 1: DB candidates ---------------------------------------
    db_path = get_db_path()
    if not db_path.exists():
        # Without a DB we have no engagement table and therefore no
        # cheap candidate set. The CLI's empty-result path will render
        # the appropriate hint.
        return [], 0, 0

    with get_connection() as conn:
        store = ConversationStore(conn)
        db_convs = store.list_by_event_date_range(
            since=since,
            until=until,
            source=source,
            include_subs=include_subs,
        )

    # Convert to ConversationInfo so the existing repo/label filters
    # accept them. ``_db_conv_to_info`` carries dashed ids forward to
    # match what the filter helpers expect.
    candidates: list[ConversationInfo] = [
        _db_conv_to_info(c) for c in db_convs
    ]

    # Apply non-date filters via the existing helpers. We deliberately
    # call them as siblings rather than going through
    # ``_apply_conversation_filters`` because that helper also
    # re-runs the DB date predicate (which we already pushed through
    # ``list_by_event_date_range``).
    from ohtv.cli import _filter_by_label, _filter_by_repo

    if repo is not None:
        candidates = _filter_by_repo(
            candidates, repo, include_subs=include_subs
        )
    if label is not None:
        candidates = _filter_by_label(
            config, candidates, label, include_subs=include_subs
        )

    total_conversations = len(candidates)

    # ---- Pagination at the conversation grain (AC) -------------------
    if offset:
        candidates = candidates[offset:]
    if limit is not None:
        candidates = candidates[:limit]

    # ---- Pass 2: load events from disk for the displayed window ------
    groups: list[ConversationMessages] = []
    total_messages = 0

    for conv in candidates:
        conv_dir = _resolve_conversation_dir(config, conv)
        if conv_dir is None:
            # Conversation row exists in the DB but the directory is
            # missing on disk — skip silently (matches ``ohtv show``
            # which renders an "events_dir does not exist" hint and
            # carries on).
            continue

        messages = extract_user_messages(
            conv, conv_dir, since=since, until=until,
        )
        if not messages:
            # Pass 1 returned this conversation because *some* event
            # was in range, but no user message was. Drop it from the
            # output — the count still surfaces via Pass 1's
            # ``total_conversations``.
            continue

        groups.append(ConversationMessages(conv=conv, messages=messages))
        total_messages += len(messages)

    # Sort by most-recent in-range user message timestamp descending,
    # so "what did I most recently say" surfaces first. The
    # ``list_by_event_date_range`` query already sorts by
    # ``last_event_ts DESC``, but that includes non-user events; we
    # re-sort here by the strictly-user-message timestamp to match the
    # documented contract. Secondary stable sort by conv.id for
    # determinism in tests.
    groups.sort(
        key=lambda g: (
            -g.messages[-1].timestamp.timestamp(),
            g.conv.id,
        )
    )

    return groups, total_conversations, total_messages


# ---------------------------------------------------------------------------
# Truncation / single-line helpers used by the CLI renderers.
# ---------------------------------------------------------------------------


def truncate_text(
    text: str, max_chars: int = TEXT_TRUNCATION_CHARS
) -> str:
    """Truncate ``text`` to ``max_chars`` chars with a single-character
    ellipsis suffix.

    Used by the ``text`` renderer when ``--full`` is not set. Matches
    the AC "truncate to 500 chars + …". The suffix is the Unicode
    ellipsis (U+2026), which is one code point but one display column.
    Empty / short strings are returned unchanged.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def collapse_to_single_line(text: str) -> str:
    """Collapse newlines and tabs so a message fits a single tab-delimited line.

    Used exclusively by the ``raw`` (``-1``) renderer where each
    message must be a single line of the form::

        <conv_id_short>\\t<ISO_timestamp>\\t<text>

    ``\\n`` and ``\\r`` collapse to a visible ``⏎``; literal tabs in
    the message collapse to four spaces so they don't pollute the
    column layout downstream consumers ``cut``/``awk`` on.
    """
    # ``\r\n`` first so we don't double-substitute it.
    out = text.replace("\r\n", "⏎").replace("\n", "⏎").replace("\r", "⏎")
    out = out.replace("\t", "    ")
    return out
