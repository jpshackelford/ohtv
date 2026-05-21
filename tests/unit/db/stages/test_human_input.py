"""Tests for the human_input counting stage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation
from ohtv.db.stages.human_input import (
    STAGE_NAME,
    HumanInputMetrics,
    count_human_input,
    process_human_input,
)
from ohtv.db.stores import ConversationStore, StageStore


# ---------------------------------------------------------------------------
# Pure-function tests: count_human_input
# ---------------------------------------------------------------------------


def _user_msg(text: str) -> dict:
    """Build a user MessageEvent with a single text content item."""
    return {
        "kind": "MessageEvent",
        "source": "user",
        "llm_message": {
            "content": [{"type": "text", "text": text}],
        },
    }


def _agent_msg(text: str) -> dict:
    """Build an agent MessageEvent."""
    return {
        "kind": "MessageEvent",
        "source": "agent",
        "llm_message": {
            "content": [{"type": "text", "text": text}],
        },
    }


class TestCountHumanInput:
    """Unit tests for the pure counting function."""

    def test_empty_events(self):
        result = count_human_input([])
        assert result == HumanInputMetrics(0, 0, 0)

    def test_only_initial_prompt(self):
        events = [_user_msg("Fix the broken tests please")]
        result = count_human_input(events)
        assert result.initial_prompt_words == 5
        assert result.followup_word_count == 0
        assert result.followup_message_count == 0

    def test_initial_and_followups(self):
        events = [
            _user_msg("one two three"),  # 3 words - initial
            _agent_msg("agent talks here"),
            _user_msg("four five"),  # 2 words - followup 1
            _user_msg("six seven eight nine"),  # 4 words - followup 2
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 3
        assert result.followup_word_count == 6
        assert result.followup_message_count == 2

    def test_no_user_messages(self):
        """Orchestrator/worker conversations may have no user messages."""
        events = [
            _agent_msg("agent thinking"),
            {"kind": "ActionEvent", "source": "agent", "tool_name": "terminal"},
        ]
        result = count_human_input(events)
        assert result == HumanInputMetrics(0, 0, 0)

    def test_ignores_non_message_events(self):
        events = [
            {
                "kind": "ActionEvent",
                "source": "user",
                "llm_message": {"content": [{"type": "text", "text": "ignored"}]},
            },
            _user_msg("real prompt"),
        ]
        result = count_human_input(events)
        # Only the MessageEvent counts as the initial prompt.
        assert result.initial_prompt_words == 2
        assert result.followup_message_count == 0

    def test_ignores_agent_messages(self):
        events = [
            _agent_msg("ignored agent words"),
            _user_msg("actual initial"),
            _agent_msg("more agent"),
            _user_msg("follow up"),
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 2
        assert result.followup_word_count == 2
        assert result.followup_message_count == 1

    def test_multiple_text_items_in_content(self):
        """Multiple text items in one message are summed."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [
                        {"type": "text", "text": "one two"},
                        {"type": "text", "text": "three four five"},
                    ],
                },
            },
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 5

    def test_ignores_non_text_content_items(self):
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://x"}},
                        {"type": "text", "text": "the words"},
                    ],
                },
            },
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 2

    def test_whitespace_splitting(self):
        """Word count uses str.split() — collapses runs of whitespace."""
        events = [_user_msg("  hello   world\n\nfoo\tbar  ")]
        result = count_human_input(events)
        assert result.initial_prompt_words == 4

    def test_empty_text_content(self):
        events = [_user_msg("")]
        result = count_human_input(events)
        assert result.initial_prompt_words == 0

    def test_malformed_missing_llm_message(self):
        events = [
            {"kind": "MessageEvent", "source": "user"},  # no llm_message
            _user_msg("real followup here"),
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 0
        # The malformed event is still counted as the initial prompt slot
        # (it is a user MessageEvent), so the next one is a follow-up.
        assert result.followup_message_count == 1
        assert result.followup_word_count == 3

    def test_malformed_llm_message_not_dict(self):
        events = [
            {"kind": "MessageEvent", "source": "user", "llm_message": "not a dict"},
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 0

    def test_malformed_content_not_list(self):
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {"content": "oops not a list"},
            },
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 0

    def test_malformed_content_item_not_dict(self):
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": ["string-item", {"type": "text", "text": "ok"}]
                },
            },
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 1

    def test_malformed_text_field_not_string(self):
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {"content": [{"type": "text", "text": 12345}]},
            },
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 0

    def test_non_dict_event_skipped(self):
        events = ["a string", 42, None, _user_msg("two words")]
        result = count_human_input(events)
        assert result.initial_prompt_words == 2

    def test_user_messages_without_source_skipped(self):
        events = [
            {
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "no source"}]},
            },
            _user_msg("real one"),
        ]
        result = count_human_input(events)
        assert result.initial_prompt_words == 2
        assert result.followup_message_count == 0


# ---------------------------------------------------------------------------
# Integration tests: process_human_input writes to the database
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn():
    """Create an in-memory database with migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()


def _write_events(conv_dir: Path, events: list[dict]) -> None:
    """Write events as event-NNNNNN.json files in <conv_dir>/events/."""
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    for i, event in enumerate(events):
        (events_dir / f"event-{i:06d}.json").write_text(json.dumps(event))


def _register_conversation(
    db_conn: sqlite3.Connection,
    conv_id: str,
    conv_dir: Path,
    event_count: int,
) -> Conversation:
    """Insert a conversation row and return the model."""
    conv = Conversation(
        id=conv_id,
        location=str(conv_dir),
        event_count=event_count,
    )
    ConversationStore(db_conn).upsert(conv)
    return conv


def _get_human_input_row(
    db_conn: sqlite3.Connection, conv_id: str
) -> sqlite3.Row | None:
    cur = db_conn.execute(
        "SELECT * FROM conversation_human_input WHERE conversation_id = ?",
        (conv_id,),
    )
    return cur.fetchone()


class TestProcessHumanInput:
    """Integration tests for the DB-writing stage."""

    def test_populates_database(self, db_conn, tmp_path):
        conv_dir = tmp_path / "conv1"
        _write_events(
            conv_dir,
            [
                _user_msg("hello world"),  # initial: 2 words
                _agent_msg("agent reply"),
                _user_msg("please fix"),  # followup: 2 words
                _user_msg("and add tests"),  # followup: 3 words
            ],
        )
        conv = _register_conversation(db_conn, "conv1", conv_dir, event_count=4)

        process_human_input(db_conn, conv)

        row = _get_human_input_row(db_conn, "conv1")
        assert row is not None
        assert row["initial_prompt_words"] == 2
        assert row["followup_word_count"] == 5
        assert row["followup_message_count"] == 2
        assert row["event_count"] == 4
        assert row["initial_prompt_source"] == "unknown"  # default
        assert row["processed_at"]

    def test_marks_stage_complete(self, db_conn, tmp_path):
        conv_dir = tmp_path / "conv2"
        _write_events(conv_dir, [_user_msg("a prompt")])
        conv = _register_conversation(db_conn, "conv2", conv_dir, event_count=1)

        process_human_input(db_conn, conv)

        stage = StageStore(db_conn).get("conv2", STAGE_NAME)
        assert stage is not None
        assert stage.event_count == 1

    def test_no_events_directory(self, db_conn, tmp_path):
        """If events dir is missing, we still write a zero-row and mark complete."""
        conv_dir = tmp_path / "conv-no-events"
        conv_dir.mkdir()
        conv = _register_conversation(db_conn, "convne", conv_dir, event_count=0)

        process_human_input(db_conn, conv)

        row = _get_human_input_row(db_conn, "convne")
        assert row is not None
        assert row["initial_prompt_words"] == 0
        assert row["followup_word_count"] == 0
        assert row["followup_message_count"] == 0

        stage = StageStore(db_conn).get("convne", STAGE_NAME)
        assert stage is not None

    def test_handles_malformed_event_file(self, db_conn, tmp_path):
        """Files with invalid JSON should be skipped, not crash the stage."""
        conv_dir = tmp_path / "conv-bad"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "event-000000.json").write_text("{not valid json")
        (events_dir / "event-000001.json").write_text(
            json.dumps(_user_msg("real prompt"))
        )
        conv = _register_conversation(db_conn, "convbad", conv_dir, event_count=2)

        process_human_input(db_conn, conv)

        row = _get_human_input_row(db_conn, "convbad")
        assert row["initial_prompt_words"] == 2

    def test_idempotent_same_results(self, db_conn, tmp_path):
        """Running the stage twice on the same data should not change counts."""
        conv_dir = tmp_path / "conv-idem"
        _write_events(
            conv_dir,
            [
                _user_msg("first one"),
                _user_msg("second one here"),
            ],
        )
        conv = _register_conversation(db_conn, "convidem", conv_dir, event_count=2)

        process_human_input(db_conn, conv)
        first = dict(_get_human_input_row(db_conn, "convidem"))

        process_human_input(db_conn, conv)
        second = dict(_get_human_input_row(db_conn, "convidem"))

        # The counts and event_count must remain identical; processed_at may
        # update but the underlying metrics should not change.
        assert first["initial_prompt_words"] == second["initial_prompt_words"]
        assert first["followup_word_count"] == second["followup_word_count"]
        assert first["followup_message_count"] == second["followup_message_count"]
        assert first["event_count"] == second["event_count"]

    def test_reprocessing_updates_counts(self, db_conn, tmp_path):
        """If events change between runs, counts should be updated."""
        conv_dir = tmp_path / "conv-grow"
        _write_events(conv_dir, [_user_msg("hello")])
        conv = _register_conversation(db_conn, "convgrow", conv_dir, event_count=1)
        process_human_input(db_conn, conv)

        # Now grow the conversation: add a follow-up message.
        _write_events(
            conv_dir,
            [_user_msg("hello"), _user_msg("now bigger followup")],
        )
        conv2 = Conversation(id="convgrow", location=str(conv_dir), event_count=2)
        ConversationStore(db_conn).upsert(conv2)
        process_human_input(db_conn, conv2)

        row = _get_human_input_row(db_conn, "convgrow")
        assert row["initial_prompt_words"] == 1
        assert row["followup_message_count"] == 1
        assert row["followup_word_count"] == 3
        assert row["event_count"] == 2

    def test_no_user_messages_orchestrator_worker(self, db_conn, tmp_path):
        """A conversation with only agent messages stores zeros."""
        conv_dir = tmp_path / "conv-orch"
        _write_events(
            conv_dir,
            [
                _agent_msg("first agent message"),
                _agent_msg("second agent message"),
            ],
        )
        conv = _register_conversation(db_conn, "convorch", conv_dir, event_count=2)

        process_human_input(db_conn, conv)

        row = _get_human_input_row(db_conn, "convorch")
        assert row["initial_prompt_words"] == 0
        assert row["followup_word_count"] == 0
        assert row["followup_message_count"] == 0

    def test_preserves_initial_prompt_source_on_reprocessing(
        self, db_conn, tmp_path
    ):
        """``initial_prompt_source`` must NOT revert on reprocessing.

        The upsert in ``process_human_input`` deliberately omits
        ``initial_prompt_source`` from its ``ON CONFLICT ... DO UPDATE SET``
        clause so that a downstream classification stage (see issue #83) can
        set it to e.g. ``'human'`` once and have that value survive any
        subsequent reprocessing triggered by event growth. This test pins
        that contract.
        """
        conv_dir = tmp_path / "conv-preserve"
        _write_events(conv_dir, [_user_msg("hello")])
        conv = _register_conversation(db_conn, "convpres", conv_dir, event_count=1)

        # First processing run: source defaults to 'unknown'.
        process_human_input(db_conn, conv)
        initial_row = _get_human_input_row(db_conn, "convpres")
        assert initial_row["initial_prompt_source"] == "unknown"

        # Simulate a future classification stage marking this prompt as human.
        db_conn.execute(
            "UPDATE conversation_human_input "
            "SET initial_prompt_source = 'human' WHERE conversation_id = ?",
            ("convpres",),
        )
        db_conn.commit()

        # Conversation grows, triggering a reprocess.
        _write_events(
            conv_dir,
            [_user_msg("hello"), _user_msg("now a followup of four words")],
        )
        conv2 = Conversation(
            id="convpres", location=str(conv_dir), event_count=2
        )
        ConversationStore(db_conn).upsert(conv2)
        process_human_input(db_conn, conv2)

        row = _get_human_input_row(db_conn, "convpres")
        # Contract: classification result is preserved across reprocessing.
        assert row["initial_prompt_source"] == "human"
        # Sanity check: the count columns WERE refreshed by the reprocess.
        assert row["event_count"] == 2
        assert row["followup_message_count"] == 1
        assert row["followup_word_count"] == 6

    def test_needs_processing_after_first_run(self, db_conn, tmp_path):
        """StageStore.needs_processing reflects completion state correctly."""
        conv_dir = tmp_path / "conv-skip"
        _write_events(conv_dir, [_user_msg("hi")])
        conv = _register_conversation(db_conn, "convskip", conv_dir, event_count=1)

        stage_store = StageStore(db_conn)
        assert stage_store.needs_processing("convskip", STAGE_NAME, 1) is True

        process_human_input(db_conn, conv)

        # Same event_count: no further work needed.
        assert stage_store.needs_processing("convskip", STAGE_NAME, 1) is False
        # Conversation grew: needs reprocessing.
        assert stage_store.needs_processing("convskip", STAGE_NAME, 5) is True


# ---------------------------------------------------------------------------
# Registry test
# ---------------------------------------------------------------------------


def test_stage_registered_in_registry():
    """The stage must be exposed in the STAGES registry."""
    from ohtv.db.stages import STAGES

    assert "human_input" in STAGES
    assert STAGES["human_input"] is process_human_input
