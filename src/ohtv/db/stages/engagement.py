"""Engagement (sustained-attention) processing stage — Issues #163, #184.

Computes a per-conversation **engaged human minutes** metric, plus the
related **attention periods** count and (normalized) total conversation
duration. The result is stored in ``conversation_engagement`` (migration
023, extended by migration 025) and the stage is registered as
``engagement`` in :mod:`ohtv.db.stages`.

Two distinct timing constants
=============================

Issue #184 surfaced a conceptual conflation in the v1 algorithm: a
single threshold ``T`` was doing two semantically different jobs. The
v2 algorithm separates them and exposes each on the stored row so they
can be re-tuned (and audited) independently.

``T`` — *silence tolerance* (``DEFAULT_THRESHOLD_SECONDS``)
    "How long can a human be silent during agent activity and still be
    considered present at that instant?" Empirically grounded in the
    distribution of inter-event gaps around follow-up user messages
    (see ``scripts/engagement_threshold_sweep.py`` / Issue #163).
    Default: 12 min.

``T_a`` — *sustained-attention window* (``DEFAULT_SUSTAINED_ATTENTION_SECONDS``)
    "How long can a human plausibly remain in one continuous block of
    monitoring before we should assume they walked away?" Caps how far
    an attended block may extend back from ``Uᵢ`` to ``Uᵢ₋₁``.

    **This default is PROVISIONAL.** ``T`` was empirically tuned at
    introduction; ``T_a`` has not yet been. The proposed corpus
    analysis (Issue #184 comment thread) is to bucket consecutive
    user-message gaps by the *length of intervening agent activity* and
    observe where the "still present" signal (gap to immediately-
    preceding event ≤ T at the follow-up) begins to fall off. The
    analysis lives in a separate workspace with a larger conversation
    corpus; until it lands, the 1-hour default is a defensible
    placeholder, not an empirically tuned value.

Algorithm (timing-only, no content inspection)
==============================================

1. Order events ascending by timestamp; find user-message indices
   ``Uᵢ``.
2. For each follow-up ``Uᵢ`` (i ≥ 1, skipping the initial prompt
   ``U₀``):

   * **Silence-tolerance gate (uses ``T``).** Walk left from ``Uᵢ`` to
     find the immediately preceding parseable event ``Pᵢ`` and check
     ``Uᵢ.ts − Pᵢ.ts ≤ T``. If false, the human was not present at
     ``Uᵢ`` — skip; no block recorded.
   * **Sustained-attention cap (uses ``T_a``).** If the silence gate
     passes, check the *user-to-user* gap ``Uᵢ.ts − Uᵢ₋₁.ts``. If it
     is ``≤ T_a``, record the attended block ``[Uᵢ₋₁, Uᵢ]`` (the v1
     behavior — "reading along" credit). If it exceeds ``T_a``, the
     user came back but cannot plausibly have been monitoring the
     whole span; record a zero-duration **touch** ``[Uᵢ, Uᵢ]``
     instead. ``attention_periods`` still increments — the user
     genuinely returned — but ``engaged_seconds`` contributes 0 for
     that span.

3. Sort the recorded blocks ascending and merge any two adjacent
   blocks whose seam gap is ``≤ T`` into a single attention period.
4. ``engaged_seconds`` = sum of merged-period spans (whole seconds);
   ``attention_periods`` = number of merged periods.

Why the v2 cap is needed
========================

The v1 algorithm gated only on the gap to the *immediately preceding*
event. For "set-and-forget overnight" conversations — initial prompt,
then the agent fires an event every few minutes for hours, then a
follow-up the next morning — the gap to the immediately preceding
event stayed under ``T`` the whole time. The block then extended
unconditionally back to ``Uᵢ₋₁`` and a 14-hour conversation was
credited as 14 hours of human engagement. Issue #184 collected 9 such
rows totalling ~50 hours of inflated engagement.

The v2 cap with ``T_a`` clips that span: the user genuinely came back
(touch is recorded, ``attention_periods`` increments), but they were
not reading along the whole night, so ``engaged_seconds`` does not
inflate.

Edge cases
==========

* Zero or one user message ⇒ ``engaged_seconds = 0``,
  ``attention_periods = 0``. The row is still written (with the metric
  set to zero, not NULL) so fire-and-forget conversations remain
  queryable.
* Tail handling. Events after the last user message do NOT extend the
  attention period (the default proposal in the original issue).
* Single-instant period (a follow-up off the initial prompt with zero
  intermediate agent events) counts as one period of 0 seconds — the
  ``attention_periods`` counter is the right signal for "user touched
  the conversation."

Both thresholds used for the stored row are recorded
(``threshold_seconds``, ``sustained_attention_seconds``,
``algorithm_version``) so re-tuning is detectable and re-runnable.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ohtv.db.models import Conversation
from ohtv.db.stores import StageStore

# Import utilities from ohtv-utils
from ohtv_utils.metrics.engagement import (
    DEFAULT_SUSTAINED_ATTENTION_SECONDS,
    DEFAULT_THRESHOLD_SECONDS,
    EngagementMetrics,
    compute_engagement,
)

log = logging.getLogger("ohtv")

STAGE_NAME = "engagement"

# Algorithm version stored alongside the metric. Bumped whenever
# ``compute_engagement`` changes in a way that produces materially
# different numbers under the same inputs. Migration 025 backfills
# pre-v2 rows by clearing the stage-tracking record so the next
# ``ohtv db process engagement`` pass recomputes them automatically.
#
#   v1 — Initial algorithm (Issue #163). Single threshold ``T``;
#        attended blocks extended unconditionally back to ``Uᵢ₋₁``.
#   v2 — Added the sustained-attention cap ``T_a`` (Issue #184).
COMPUTE_ENGAGEMENT_VERSION = 2


def process_engagement(
    conn: sqlite3.Connection,
    conversation: Conversation,
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
    sustained_attention_seconds: int = DEFAULT_SUSTAINED_ATTENTION_SECONDS,
) -> None:
    """Compute engagement for a conversation and upsert the row.

    Reads events from ``<conversation.location>/events/event-*.json``,
    computes :class:`EngagementMetrics`, and upserts them into
    ``conversation_engagement`` (migration 023 + 025). The stage is
    marked complete regardless of whether any user messages were found
    — even fire-and-forget conversations get a row (``engaged_seconds
    = 0``, ``attention_periods = 0``) so downstream queries do not
    need to LEFT JOIN.

    Args:
        conn: Database connection.
        conversation: Conversation row from ``ConversationStore``.
        threshold_seconds: ``T`` — silence-tolerance threshold. Stored
            on the row so the tuning sweep can keep per-threshold
            values distinguishable.
        sustained_attention_seconds: ``T_a`` — sustained-attention
            window cap. Stored on the row alongside ``T`` so re-tuning
            either constant is detectable. Default is the provisional
            :data:`DEFAULT_SUSTAINED_ATTENTION_SECONDS` (1 h) pending
            the empirical analysis described in Issue #184.
    """
    conv_dir = Path(conversation.location)
    events = _load_events(conv_dir / "events")

    metrics = compute_engagement(
        events,
        threshold_seconds=threshold_seconds,
        sustained_attention_seconds=sustained_attention_seconds,
    )

    processed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO conversation_engagement (
            conversation_id,
            threshold_seconds,
            sustained_attention_seconds,
            algorithm_version,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET
            threshold_seconds = excluded.threshold_seconds,
            sustained_attention_seconds = excluded.sustained_attention_seconds,
            algorithm_version = excluded.algorithm_version,
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
            int(sustained_attention_seconds),
            COMPUTE_ENGAGEMENT_VERSION,
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
        "engagement %s: engaged=%ds periods=%d T=%ds T_a=%ds v=%d follow_ups=%d attended=%d",
        conversation.id[:8],
        metrics.engaged_seconds,
        metrics.attention_periods,
        threshold_seconds,
        sustained_attention_seconds,
        COMPUTE_ENGAGEMENT_VERSION,
        metrics.follow_up_user_message_count,
        metrics.attended_user_message_count,
    )


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
