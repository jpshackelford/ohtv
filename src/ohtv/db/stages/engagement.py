"""Engagement (sustained-attention) processing stage — Issue #163.

Computes a per-conversation **engaged human minutes** metric, plus the
related **attention periods** count and (normalized) total conversation
duration. The result is stored in ``conversation_engagement`` (migration
023) and the stage is registered as ``engagement`` in
:mod:`ohtv.db.stages`.

Algorithm (timing-only, no content inspection):

1. Order the events by timestamp ascending and find the indices of all
   ``MessageEvent``s with ``source == "user"``.
2. With ``T`` = sustained-attention threshold (default 12 min), walk
   backward over follow-up user messages (skipping the initial prompt
   ``U₀``). For each ``Uᵢ`` whose gap to the immediately preceding event
   ``Pᵢ`` is ``≤ T``, record the attended block ``[Uᵢ₋₁, Uᵢ]``. The
   gap test gates *whether the human was here*; the block bounds extend
   back to the previous user message because the human was reading along
   while the agent worked between turns.
3. Sort the recorded blocks ascending and merge any two adjacent blocks
   whose seam gap is ``≤ T`` into a single **attention period**.
4. ``engaged_seconds`` = sum of merged-period spans (in whole seconds).
   ``attention_periods`` = number of merged periods.

Edge cases:

* Zero or one user message ⇒ ``engaged_seconds = 0``,
  ``attention_periods = 0``. The row is still written (with the metric
  set to zero, not NULL) so fire-and-forget conversations remain
  queryable.
* Tail handling. Events after the last user message do NOT extend the
  attention period (the default proposal in the issue's open questions).
  The pseudocode in the issue is the canonical algorithm.
* Single-instant period (a follow-up off the initial prompt with zero
  intermediate agent events) counts as one period of 0 seconds — the
  ``attention_periods`` counter is the right signal for "user touched
  the conversation."

The threshold used for the stored row is recorded in
``threshold_seconds`` so re-tuning is detectable and re-runnable.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ohtv.db.models import Conversation
from ohtv.db.stores import StageStore

log = logging.getLogger("ohtv")

STAGE_NAME = "engagement"

# Default sustained-attention threshold. The original strawman in the
# issue was 8 minutes; the user's updated guess was 12 minutes ("noticed
# the message → read response → composed reply"). 12 is shipped as the
# initial default per the issue's open-question recommendation #3; the
# tuning sweep (``scripts/engagement_threshold_sweep.py``) will pick the
# empirical value.
DEFAULT_THRESHOLD_SECONDS = 12 * 60


@dataclass(frozen=True)
class EngagementMetrics:
    """The engagement numbers for one conversation under one threshold.

    ``first_event_ts`` and ``last_event_ts`` are normalized on the
    first/last event JSON timestamps — NOT on
    ``base_state.updated_at - created_at`` — so the three numbers
    (engaged / periods / total) are self-consistent.
    """

    engaged_seconds: int
    attention_periods: int
    follow_up_user_message_count: int
    attended_user_message_count: int
    first_event_ts: datetime | None = None
    last_event_ts: datetime | None = None

    @property
    def total_duration_seconds(self) -> int | None:
        """``last_event_ts − first_event_ts`` in whole seconds, or None."""
        if self.first_event_ts is None or self.last_event_ts is None:
            return None
        return int(
            (self.last_event_ts - self.first_event_ts).total_seconds()
        )


def compute_engagement(
    events: list[dict],
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
) -> EngagementMetrics:
    """Compute engagement metrics for one conversation's events.

    Args:
        events: Ordered list of event dicts (as loaded from
            ``events/event-*.json``). Events must be in chronological
            order; the on-disk file naming guarantees this.
        threshold_seconds: ``T`` in seconds. Default
            :data:`DEFAULT_THRESHOLD_SECONDS` (12 min). Pass 0 to mark
            every gap unattended; pass a very large number to merge the
            whole conversation into a single period.

    Returns:
        :class:`EngagementMetrics` for the conversation. Malformed events
        (missing/wrong-typed timestamp or kind/source fields) are
        tolerated and silently skipped — the metric degrades gracefully
        rather than crashing the pipeline.
    """
    # Pre-extract (timestamp, is_user_message) for every parseable event.
    # We keep the same index space as `events` so the gap-test uses
    # event[u_i - 1] correctly.
    parsed: list[tuple[datetime | None, bool]] = []
    for event in events:
        if not isinstance(event, dict):
            parsed.append((None, False))
            continue
        ts = _parse_timestamp(event.get("timestamp"))
        is_user = (
            event.get("kind") == "MessageEvent"
            and event.get("source") == "user"
        )
        parsed.append((ts, is_user))

    # First and last *parseable* event timestamps anchor the conversation
    # duration. The pre-existing display code uses base_state.updated_at
    # - created_at which can drift; we deliberately re-derive here.
    parsed_ts = [ts for ts, _ in parsed if ts is not None]
    first_event_ts = parsed_ts[0] if parsed_ts else None
    last_event_ts = parsed_ts[-1] if parsed_ts else None

    user_idx = [i for i, (ts, is_user) in enumerate(parsed) if is_user and ts is not None]
    follow_up_count = max(0, len(user_idx) - 1)

    if len(user_idx) < 2:
        # Fire-and-forget (or empty): no follow-up means no engagement.
        return EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=follow_up_count,
            attended_user_message_count=0,
            first_event_ts=first_event_ts,
            last_event_ts=last_event_ts,
        )

    threshold = max(0, int(threshold_seconds))

    # Walk backward over follow-up user messages (skip U₀). For each Uᵢ
    # whose gap to the immediately preceding parseable event is ≤ T,
    # record the attended block back to Uᵢ₋₁.
    attended: list[tuple[datetime, datetime]] = []
    for k in range(len(user_idx) - 1, 0, -1):
        u_i = user_idx[k]
        u_ts = parsed[u_i][0]
        assert u_ts is not None  # user_idx filter guarantees this

        # Walk left from u_i to find the most recent parseable
        # timestamp. We tolerate gaps caused by malformed events
        # rather than letting one bad file shift the gap measurement.
        p_ts: datetime | None = None
        for j in range(u_i - 1, -1, -1):
            cand = parsed[j][0]
            if cand is not None:
                p_ts = cand
                break

        if p_ts is None:
            # Uᵢ is the first parseable event — no preceding event to
            # gate the gap. Treat as unattended (matches the pseudocode
            # which requires a preceding event Pᵢ).
            continue

        gap_seconds = (u_ts - p_ts).total_seconds()
        if gap_seconds > threshold:
            continue

        block_start_idx = user_idx[k - 1]
        block_start_ts = parsed[block_start_idx][0]
        assert block_start_ts is not None
        attended.append((block_start_ts, u_ts))

    if not attended:
        return EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=follow_up_count,
            attended_user_message_count=0,
            first_event_ts=first_event_ts,
            last_event_ts=last_event_ts,
        )

    # Merge adjacent attended blocks whose seam gap ≤ T. `attended` was
    # built walking backward; sort ascending for the merge.
    attended.sort()
    periods: list[tuple[datetime, datetime]] = [attended[0]]
    for start, end in attended[1:]:
        prev_start, prev_end = periods[-1]
        seam = (start - prev_end).total_seconds()
        if seam <= threshold:
            # Overlap or within-threshold join → extend.
            new_end = max(prev_end, end)
            periods[-1] = (prev_start, new_end)
        else:
            periods.append((start, end))

    engaged_seconds = sum(
        int((end - start).total_seconds()) for start, end in periods
    )

    return EngagementMetrics(
        engaged_seconds=engaged_seconds,
        attention_periods=len(periods),
        follow_up_user_message_count=follow_up_count,
        attended_user_message_count=len(attended),
        first_event_ts=first_event_ts,
        last_event_ts=last_event_ts,
    )


def process_engagement(
    conn: sqlite3.Connection,
    conversation: Conversation,
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
) -> None:
    """Compute engagement for a conversation and upsert the row.

    Reads events from ``<conversation.location>/events/event-*.json``,
    computes :class:`EngagementMetrics`, and upserts them into
    ``conversation_engagement`` (migration 023). The stage is marked
    complete regardless of whether any user messages were found — even
    fire-and-forget conversations get a row (``engaged_seconds = 0``,
    ``attention_periods = 0``) so downstream queries do not need to
    LEFT JOIN.

    Args:
        conn: Database connection.
        conversation: Conversation row from ``ConversationStore``.
        threshold_seconds: ``T`` to use for this row. Stored on the row
            so the tuning sweep can keep the per-threshold values
            distinguishable. The default
            (:data:`DEFAULT_THRESHOLD_SECONDS`) ships as the initial
            value per the issue's open-question recommendation; the
            real default will be picked from the empirical break in
            the gap histogram.
    """
    conv_dir = Path(conversation.location)
    events = _load_events(conv_dir / "events")

    metrics = compute_engagement(events, threshold_seconds=threshold_seconds)

    processed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO conversation_engagement (
            conversation_id,
            threshold_seconds,
            first_event_ts,
            last_event_ts,
            total_duration_seconds,
            engaged_seconds,
            attention_periods,
            follow_up_user_message_count,
            attended_user_message_count,
            processed_at,
            event_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET
            threshold_seconds = excluded.threshold_seconds,
            first_event_ts = excluded.first_event_ts,
            last_event_ts = excluded.last_event_ts,
            total_duration_seconds = excluded.total_duration_seconds,
            engaged_seconds = excluded.engaged_seconds,
            attention_periods = excluded.attention_periods,
            follow_up_user_message_count = excluded.follow_up_user_message_count,
            attended_user_message_count = excluded.attended_user_message_count,
            processed_at = excluded.processed_at,
            event_count = excluded.event_count
        """,
        (
            conversation.id,
            int(threshold_seconds),
            metrics.first_event_ts.isoformat() if metrics.first_event_ts else None,
            metrics.last_event_ts.isoformat() if metrics.last_event_ts else None,
            metrics.total_duration_seconds,
            metrics.engaged_seconds,
            metrics.attention_periods,
            metrics.follow_up_user_message_count,
            metrics.attended_user_message_count,
            processed_at,
            conversation.event_count,
        ),
    )

    stage_store = StageStore(conn)
    stage_store.mark_complete(
        conversation.id, STAGE_NAME, conversation.event_count
    )

    log.debug(
        "engagement %s: engaged=%ds periods=%d T=%ds follow_ups=%d attended=%d",
        conversation.id[:8],
        metrics.engaged_seconds,
        metrics.attention_periods,
        threshold_seconds,
        metrics.follow_up_user_message_count,
        metrics.attended_user_message_count,
    )


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp from an event JSON field.

    Returns ``None`` for missing / wrong-typed / unparseable values.
    Naive datetimes are assumed UTC (matches the rest of the codebase
    per AGENTS.md item #5 — cloud event timestamps are UTC).
    """
    if not isinstance(value, str):
        return None
    raw = value.rstrip("Z")
    if "+" in raw:
        raw = raw.split("+")[0]
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_events(events_dir: Path) -> list[dict]:
    """Load all events from a conversation's events directory.

    Returns an empty list if the directory is missing or contains no
    parseable event files. Files with JSON errors are skipped so a
    single bad event cannot stall the whole pipeline.
    """
    if not events_dir.exists():
        return []

    events: list[dict] = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            events.append(data)
    return events
