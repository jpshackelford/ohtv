"""Human input counting stage.

Counts human words and messages per conversation, distinguishing between
the initial prompt (first user message) and follow-up messages (subsequent
user messages).

Background: Both initial prompt and follow-ups are structurally identical
in the trace data (``MessageEvent`` with ``source: "user"``). Only their
position in the event sequence distinguishes them. The first user message
is the task definition; later user messages represent human steering during
agent execution.

Results are stored in the ``conversation_human_input`` table (created by
migration 016). This stage only populates the count fields; the
``initial_prompt_source`` column is left at its default ('unknown') for
later stages to classify (see issue #83).
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

STAGE_NAME = "human_input"


@dataclass
class HumanInputMetrics:
    """Word and message counts for human input in a conversation."""

    initial_prompt_words: int
    followup_word_count: int
    followup_message_count: int


def count_human_input(events: list[dict]) -> HumanInputMetrics:
    """Count human input, separating initial prompt from follow-ups.

    The first ``MessageEvent`` with ``source == "user"`` is treated as the
    initial prompt. All subsequent ones are follow-ups.

    Word counts use whitespace splitting (``str.split()``) for simple,
    reproducible counts. Non-text content items are ignored.

    Malformed events (missing/wrong-typed fields) are tolerated and
    contribute zero words.

    Args:
        events: Ordered list of conversation events.

    Returns:
        HumanInputMetrics with separate counts for initial prompt and
        follow-up messages.
    """
    initial_prompt_words = 0
    followup_word_count = 0
    followup_message_count = 0
    found_initial = False

    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("kind") != "MessageEvent":
            continue
        if event.get("source") != "user":
            continue

        words = _count_words_in_message(event)

        if not found_initial:
            initial_prompt_words = words
            found_initial = True
        else:
            followup_word_count += words
            followup_message_count += 1

    return HumanInputMetrics(
        initial_prompt_words=initial_prompt_words,
        followup_word_count=followup_word_count,
        followup_message_count=followup_message_count,
    )


def _count_words_in_message(event: dict) -> int:
    """Extract text from a MessageEvent and return word count.

    Text is read from ``llm_message.content[].text`` where ``type`` is
    ``"text"``. Multiple text items in the same message are summed.
    """
    llm_message = event.get("llm_message")
    if not isinstance(llm_message, dict):
        return 0

    content_list = llm_message.get("content")
    if not isinstance(content_list, list):
        return 0

    words = 0
    for item in content_list:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            words += len(text.split())
    return words


def process_human_input(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Count human input for a conversation and store metrics in DB.

    Reads events from ``<conversation.location>/events/event-*.json``,
    computes :class:`HumanInputMetrics`, and upserts them into
    ``conversation_human_input``. Marks the stage complete regardless of
    whether any user messages were found (e.g., orchestrator worker
    conversations have none).

    Args:
        conn: Database connection.
        conversation: The conversation to process.
    """
    conv_dir = Path(conversation.location)
    events = _load_events(conv_dir / "events")

    metrics = count_human_input(events)

    processed_at = datetime.now(timezone.utc).isoformat()
    # Upsert into conversation_human_input. We do not touch
    # initial_prompt_source on update so that later classification stages
    # can refine it without being overwritten on reprocessing.
    conn.execute(
        """
        INSERT INTO conversation_human_input (
            conversation_id,
            initial_prompt_words,
            followup_word_count,
            followup_message_count,
            processed_at,
            event_count
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET
            initial_prompt_words = excluded.initial_prompt_words,
            followup_word_count = excluded.followup_word_count,
            followup_message_count = excluded.followup_message_count,
            processed_at = excluded.processed_at,
            event_count = excluded.event_count
        """,
        (
            conversation.id,
            metrics.initial_prompt_words,
            metrics.followup_word_count,
            metrics.followup_message_count,
            processed_at,
            conversation.event_count,
        ),
    )

    stage_store = StageStore(conn)
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)

    log.debug(
        "human_input %s: initial=%d words, followups=%d msgs/%d words",
        conversation.id[:8],
        metrics.initial_prompt_words,
        metrics.followup_message_count,
        metrics.followup_word_count,
    )


def _load_events(events_dir: Path) -> list[dict]:
    """Load all events from a conversation's events directory.

    Returns an empty list if the directory does not exist or contains no
    parseable event files. Files with JSON errors are skipped.
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
