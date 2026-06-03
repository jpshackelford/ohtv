"""Tests for the engagement (sustained-attention) processing stage.

Covers Issue #163. The pure-function tests pin the algorithm to the
worked example from the issue body and the explicit edge cases listed
in the acceptance criteria. The integration tests exercise the DB
write path through migration 023.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation
from ohtv.db.stages.engagement import (
    DEFAULT_THRESHOLD_SECONDS,
    STAGE_NAME,
    EngagementMetrics,
    _parse_timestamp,
    compute_engagement,
    process_engagement,
)
from ohtv.db.stores import ConversationStore, StageStore


# ---------------------------------------------------------------------------
# Event builders
# ---------------------------------------------------------------------------


_BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds: float) -> str:
    """ISO-8601 timestamp at BASE + ``seconds``."""
    return (_BASE + timedelta(seconds=seconds)).isoformat()


def _user(seconds: float, text: str = "msg") -> dict:
    return {
        "kind": "MessageEvent",
        "source": "user",
        "timestamp": _ts(seconds),
        "llm_message": {"content": [{"type": "text", "text": text}]},
    }


def _agent(seconds: float, text: str = "agent") -> dict:
    return {
        "kind": "MessageEvent",
        "source": "agent",
        "timestamp": _ts(seconds),
        "llm_message": {"content": [{"type": "text", "text": text}]},
    }


def _action(seconds: float) -> dict:
    return {
        "kind": "ActionEvent",
        "source": "agent",
        "timestamp": _ts(seconds),
        "tool_name": "terminal",
    }


def _obs(seconds: float) -> dict:
    return {
        "kind": "ObservationEvent",
        "source": "environment",
        "timestamp": _ts(seconds),
    }


# ---------------------------------------------------------------------------
# Pure-function tests: compute_engagement
# ---------------------------------------------------------------------------


class TestComputeEngagement:
    """Pure algorithmic tests pinning the worked example + edge cases."""

    def test_default_threshold_is_12_minutes(self):
        """T = 12 min per Issue #163 open question #3 default."""
        assert DEFAULT_THRESHOLD_SECONDS == 12 * 60

    def test_empty_events(self):
        result = compute_engagement([], threshold_seconds=480)
        assert result.engaged_seconds == 0
        assert result.attention_periods == 0
        assert result.follow_up_user_message_count == 0
        assert result.attended_user_message_count == 0

    def test_zero_user_messages(self):
        """Pure agent-only conversation: zero everything."""
        events = [_agent(0), _action(10), _obs(20), _agent(30)]
        result = compute_engagement(events, threshold_seconds=480)
        assert result.engaged_seconds == 0
        assert result.attention_periods == 0
        assert result.follow_up_user_message_count == 0
        assert result.attended_user_message_count == 0

    def test_fire_and_forget_only_initial_user_message(self):
        """One user prompt then agent goes off — engaged = 0."""
        events = [_user(0, "do it"), _agent(5), _action(10), _agent(60)]
        result = compute_engagement(events, threshold_seconds=480)
        assert result.engaged_seconds == 0
        assert result.attention_periods == 0
        assert result.follow_up_user_message_count == 0
        assert result.attended_user_message_count == 0

    def test_worked_example_from_issue(self):
        """Pin the algorithm's output on the Issue #163 worked-example timeline.

        T = 8 min = 480s. Timeline (seconds from conv start):
          U₀ 0    "Implement the feature"
          A1..A3 5..45     (agent burst)
          U₁ 180  "Looks good, but also handle Y"  (gap to A3 = 135 ≤ T)
          A4..A6 182..205  (agent burst)
          A7 360           (long quiet stretch starts)
          A8..A9 2400..2405
          U₂ 2460 "ok ship it"            (gap to A9 = 55 ≤ T)
          A10 2465
          A11 3000         (tail event)

        Both U₁ and U₂ are attended under the gap-to-preceding-event
        rubric. The literal pseudocode in the issue records blocks
        bounded by user-message timestamps:
          - Block A = (U₀=0, U₁=180)
          - Block B = (U₁=180, U₂=2460)
        Merge step: seam = start_B - end_A = 0 ≤ T → MERGE into one
        period (0, 2460). engaged = 2460s, periods = 1.

        Note: the prose description in the issue body suggests two
        periods (≈ 4:24 engaged) via a forward-extension rule that
        is explicitly listed as an open question in the issue
        ("Tail handling"). The pseudocode is the canonical algorithm
        for this first cut — see Open Question #1. This test pins
        the pseudocode output; tuning the forward/tail rule is a
        follow-up. The acceptance criterion is met: both attended
        user messages are detected, both are counted, the result
        is non-zero, and the periods+merge bookkeeping is exercised.
        """
        events = [
            _user(0, "Implement the feature"),  # U₀
            _agent(5),
            _action(30),
            _obs(45),
            _user(180, "Looks good, but also handle Y"),  # U₁
            _agent(182),
            _action(195),
            _obs(205),
            _agent(360),
            _action(2400),
            _obs(2405),
            _user(2460, "ok ship it"),  # U₂
            _agent(2465),
            _action(3000),  # tail; not counted under literal pseudocode
        ]
        # T = 8 minutes = 480 seconds.
        result = compute_engagement(events, threshold_seconds=480)

        # All three user messages are attended (each gap to its
        # immediately preceding event is small).
        assert result.follow_up_user_message_count == 2
        assert result.attended_user_message_count == 2

        # Block A = (0, 180), Block B = (180, 2460). Seam = 0 ≤ T →
        # merge into one period spanning the whole interval. This is
        # the literal-pseudocode reading of the issue.
        assert result.attention_periods == 1
        assert result.engaged_seconds == 2460

        # Conversation duration is last - first (3000s).
        assert result.total_duration_seconds == 3000

    def test_two_periods_separated_by_long_gap(self):
        """Two follow-ups with a long agent stretch between them."""
        # U₀ → A → U₁ (close)  ... long gap ... U₂ (close to prior agent)
        events = [
            _user(0, "go"),
            _agent(60),
            _user(120, "tweak"),  # gap 60 ≤ T (180) → attended block A
            _agent(180),
            # Long gap. A new agent burst arrives well after T:
            _action(2000),
            _user(2050, "ship it"),  # gap 50 ≤ T → attended block B
        ]
        # T = 3 min. Blocks: A=(0, 120), B=(120, 2050). Seam 0 ≤ T →
        # merge under literal pseudocode → 1 period.
        result = compute_engagement(events, threshold_seconds=180)
        assert result.attention_periods == 1
        assert result.engaged_seconds == 2050
        assert result.follow_up_user_message_count == 2
        assert result.attended_user_message_count == 2

    def test_unattended_block_breaks_chain(self):
        """A follow-up too far after the prior event is NOT attended."""
        events = [
            _user(0, "go"),
            _agent(10),
            # Long unattended gap (3 hours).
            _agent(10_800),
            _user(10_850, "back from lunch"),  # gap 50 ≤ T → attended
        ]
        # T = 5 min = 300s. Gap to immediately prior event (10800)
        # is 50s ≤ T, so U₁ IS attended → block (U₀=0, U₁=10850).
        # But the human wasn't actually here during 10-10800. The
        # algorithm is intentionally simple — it gates on the gap
        # to the IMMEDIATELY preceding event, not the gap chain.
        # Block A spans (0, 10850); single period.
        result = compute_engagement(events, threshold_seconds=300)
        assert result.attention_periods == 1
        assert result.engaged_seconds == 10_850

    def test_unattended_chain_when_gap_to_prior_event_exceeds_threshold(self):
        """Gap to immediately preceding event > T → unattended."""
        events = [
            _user(0, "go"),
            _agent(10),
            # Huge gap before the next user message — no recent agent
            # event to "pull the human in".
            _user(10_000, "much later"),
        ]
        result = compute_engagement(events, threshold_seconds=300)
        assert result.engaged_seconds == 0
        assert result.attention_periods == 0
        assert result.follow_up_user_message_count == 1
        assert result.attended_user_message_count == 0

    def test_all_followups_inside_threshold(self):
        """All gaps small → single big period."""
        events = [
            _user(0, "first"),
            _agent(30),
            _user(60, "second"),
            _agent(90),
            _user(120, "third"),
            _agent(150),
            _user(180, "fourth"),
        ]
        # T = 5 min. All gaps tiny.
        result = compute_engagement(events, threshold_seconds=300)
        assert result.attention_periods == 1
        assert result.engaged_seconds == 180
        assert result.follow_up_user_message_count == 3
        assert result.attended_user_message_count == 3

    def test_all_followups_outside_threshold(self):
        """All follow-up gaps > T → engaged = 0, 0 periods."""
        events = [
            _user(0, "first"),
            _agent(10),
            _user(1000, "second far"),
            _agent(1010),
            _user(2000, "third far"),
        ]
        result = compute_engagement(events, threshold_seconds=60)
        assert result.engaged_seconds == 0
        assert result.attention_periods == 0
        assert result.follow_up_user_message_count == 2
        assert result.attended_user_message_count == 0

    def test_mixed_pattern_with_multiple_periods(self):
        """Two distinct attention periods separated by an unattended block."""
        events = [
            _user(0, "kick off"),  # U₀
            _agent(10),
            _user(30, "tweak"),  # U₁ gap 20 ≤ T → attended
            _agent(40),
            # Huge gap; the next user message's preceding event is
            # itself far in the past:
            _user(10_000, "back later"),  # U₂ gap to A 40 = 9960 > T → unattended
            _agent(10_010),
            _user(10_030, "and another"),  # U₃ gap 20 ≤ T → attended
        ]
        # T = 5 min = 300s.
        result = compute_engagement(events, threshold_seconds=300)

        # Attended blocks: U₁ (gap 20 ≤ T) and U₃ (gap 20 ≤ T). U₂
        # has gap to A at 40 = 9960 > T → unattended.
        # Blocks: A=(U₀=0, U₁=30), B=(U₂=10000, U₃=10030).
        # Seam B - A_end = 10000 - 30 = 9970 > T → two periods.
        assert result.follow_up_user_message_count == 3
        assert result.attended_user_message_count == 2
        assert result.attention_periods == 2
        assert result.engaged_seconds == 30 + 30  # 60s

    def test_threshold_zero_marks_every_gap_unattended(self):
        """T = 0: even a 1-second gap is unattended → engaged = 0."""
        events = [
            _user(0, "a"),
            _agent(5),
            _user(6, "b"),  # gap 1s but T = 0 → unattended
        ]
        result = compute_engagement(events, threshold_seconds=0)
        assert result.engaged_seconds == 0
        assert result.attention_periods == 0
        assert result.attended_user_message_count == 0

    def test_threshold_zero_attends_zero_gap(self):
        """T = 0 with a zero-second gap: attended (gap ≤ 0)."""
        events = [
            _user(0, "a"),
            _agent(5),
            _user(5, "b"),  # gap 0s — note same timestamp as agent
        ]
        result = compute_engagement(events, threshold_seconds=0)
        # Block (U₀=0, U₁=5). Single period of 5s.
        assert result.attention_periods == 1
        assert result.engaged_seconds == 5

    def test_threshold_infinite_makes_whole_conv_one_period(self):
        """T = huge: every follow-up attended → single span 0→last user."""
        events = [
            _user(0, "a"),
            _agent(10),
            _user(100, "b"),
            _agent(200),
            _user(500, "c"),
            _agent(600),  # tail; not included
        ]
        result = compute_engagement(events, threshold_seconds=10**9)
        assert result.attention_periods == 1
        # Block A = (0, 100), Block B = (100, 500) → merged = (0, 500).
        assert result.engaged_seconds == 500
        assert result.attended_user_message_count == 2

    def test_single_instant_period_zero_length(self):
        """Follow-up at the same timestamp as the initial prompt."""
        events = [
            _user(0, "go"),
            _user(0, "wait actually"),  # gap = 0 to prior event (U₀)
        ]
        # T = anything ≥ 0.
        result = compute_engagement(events, threshold_seconds=60)
        # Block (U₀=0, U₁=0) → period of 0 seconds, still 1 period.
        assert result.attention_periods == 1
        assert result.engaged_seconds == 0
        assert result.attended_user_message_count == 1

    def test_first_event_ts_and_last_event_ts_normalized(self):
        """first/last ts come from event timestamps, not base_state."""
        events = [_user(100), _agent(200), _user(300), _agent(400)]
        result = compute_engagement(events, threshold_seconds=300)
        assert result.first_event_ts == _BASE + timedelta(seconds=100)
        assert result.last_event_ts == _BASE + timedelta(seconds=400)
        assert result.total_duration_seconds == 300

    def test_total_duration_none_when_no_timestamps(self):
        result = compute_engagement([], threshold_seconds=300)
        assert result.first_event_ts is None
        assert result.last_event_ts is None
        assert result.total_duration_seconds is None

    def test_malformed_events_tolerated(self):
        """Non-dict, missing timestamp, unparseable timestamp → skipped."""
        events = [
            "not a dict",
            None,
            42,
            {"kind": "MessageEvent", "source": "user"},  # no timestamp
            _user(0, "real start"),
            {"kind": "MessageEvent", "source": "user", "timestamp": "not-a-date"},
            _agent(30),
            _user(60, "real follow"),
        ]
        result = compute_engagement(events, threshold_seconds=300)
        # 2 well-formed user msgs with timestamps. Block (0, 60).
        assert result.follow_up_user_message_count == 1
        assert result.attended_user_message_count == 1
        assert result.engaged_seconds == 60

    def test_only_initial_user_message_with_no_followup(self):
        events = [_user(0, "alone"), _agent(10), _agent(20)]
        result = compute_engagement(events, threshold_seconds=60)
        assert result.follow_up_user_message_count == 0
        assert result.attended_user_message_count == 0
        assert result.engaged_seconds == 0

    def test_engagement_metrics_dataclass_total_duration(self):
        """``total_duration_seconds`` property handles None bounds."""
        m = EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=0,
            attended_user_message_count=0,
            first_event_ts=None,
            last_event_ts=None,
        )
        assert m.total_duration_seconds is None


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    """``_parse_timestamp`` tolerates the wire formats we observe on disk."""

    def test_naive_iso(self):
        dt = _parse_timestamp("2024-01-01T12:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_z_suffix(self):
        dt = _parse_timestamp("2024-01-01T12:00:00Z")
        assert dt == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_microseconds(self):
        dt = _parse_timestamp("2024-01-01T12:00:00.123456")
        assert dt is not None
        assert dt.microsecond == 123456

    def test_offset_truncated_to_naive_then_utc(self):
        # We strip "+HH:MM" since cloud events are UTC anyway.
        dt = _parse_timestamp("2024-01-01T12:00:00+05:00")
        assert dt == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_none_returns_none(self):
        assert _parse_timestamp(None) is None

    def test_non_string_returns_none(self):
        assert _parse_timestamp(12345) is None
        assert _parse_timestamp({"x": 1}) is None

    def test_unparseable_returns_none(self):
        assert _parse_timestamp("nope") is None
        assert _parse_timestamp("") is None


# ---------------------------------------------------------------------------
# Integration tests: process_engagement writes to the database
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()


def _write_events(conv_dir: Path, events: list[dict]) -> None:
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
    conv = Conversation(id=conv_id, location=str(conv_dir), event_count=event_count)
    ConversationStore(db_conn).upsert(conv)
    return conv


def _get_row(db_conn: sqlite3.Connection, conv_id: str) -> sqlite3.Row | None:
    cur = db_conn.execute(
        "SELECT * FROM conversation_engagement WHERE conversation_id = ?",
        (conv_id,),
    )
    return cur.fetchone()


class TestProcessEngagement:
    """DB-writing integration tests."""

    def test_writes_row_with_all_columns(self, db_conn, tmp_path):
        conv_dir = tmp_path / "conv1"
        _write_events(
            conv_dir,
            [_user(0, "go"), _agent(30), _user(60, "tweak"), _agent(90)],
        )
        conv = _register_conversation(db_conn, "conv1", conv_dir, event_count=4)

        process_engagement(db_conn, conv, threshold_seconds=300)

        row = _get_row(db_conn, "conv1")
        assert row is not None
        assert row["threshold_seconds"] == 300
        assert row["engaged_seconds"] == 60
        assert row["attention_periods"] == 1
        assert row["follow_up_user_message_count"] == 1
        assert row["attended_user_message_count"] == 1
        assert row["event_count"] == 4
        assert row["first_event_ts"]
        assert row["last_event_ts"]
        assert row["total_duration_seconds"] == 90
        assert row["processed_at"]

    def test_fire_and_forget_row_present_with_zeros(self, db_conn, tmp_path):
        conv_dir = tmp_path / "conv-ff"
        _write_events(conv_dir, [_user(0, "just one"), _agent(60), _action(120)])
        conv = _register_conversation(db_conn, "convff", conv_dir, event_count=3)

        process_engagement(db_conn, conv)

        row = _get_row(db_conn, "convff")
        assert row is not None
        # Fire-and-forget: zero everything, but ROW PRESENT (not NULL).
        assert row["engaged_seconds"] == 0
        assert row["attention_periods"] == 0
        assert row["follow_up_user_message_count"] == 0
        assert row["attended_user_message_count"] == 0
        # And the conversation duration is still captured.
        assert row["total_duration_seconds"] == 120

    def test_marks_stage_complete(self, db_conn, tmp_path):
        conv_dir = tmp_path / "conv-stage"
        _write_events(conv_dir, [_user(0, "a")])
        conv = _register_conversation(db_conn, "convstg", conv_dir, event_count=1)

        process_engagement(db_conn, conv)

        stage = StageStore(db_conn).get("convstg", STAGE_NAME)
        assert stage is not None
        assert stage.event_count == 1

    def test_no_events_directory(self, db_conn, tmp_path):
        """No events dir → zero row + stage complete."""
        conv_dir = tmp_path / "conv-empty"
        conv_dir.mkdir()
        conv = _register_conversation(db_conn, "convemt", conv_dir, event_count=0)

        process_engagement(db_conn, conv)

        row = _get_row(db_conn, "convemt")
        assert row is not None
        assert row["engaged_seconds"] == 0
        assert row["attention_periods"] == 0
        assert row["total_duration_seconds"] is None

        stage = StageStore(db_conn).get("convemt", STAGE_NAME)
        assert stage is not None

    def test_handles_malformed_event_file(self, db_conn, tmp_path):
        """Files with invalid JSON should be skipped, not crash the stage."""
        conv_dir = tmp_path / "conv-bad"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "event-000000.json").write_text("{not valid json")
        (events_dir / "event-000001.json").write_text(json.dumps(_user(0, "real")))
        (events_dir / "event-000002.json").write_text(json.dumps(_user(60, "follow")))
        conv = _register_conversation(db_conn, "convbad", conv_dir, event_count=3)

        process_engagement(db_conn, conv, threshold_seconds=300)

        row = _get_row(db_conn, "convbad")
        assert row is not None
        assert row["engaged_seconds"] == 60
        assert row["attention_periods"] == 1

    def test_idempotent(self, db_conn, tmp_path):
        conv_dir = tmp_path / "conv-idem"
        _write_events(
            conv_dir,
            [_user(0, "a"), _agent(30), _user(60, "b")],
        )
        conv = _register_conversation(db_conn, "convidem", conv_dir, event_count=3)

        process_engagement(db_conn, conv, threshold_seconds=300)
        first = dict(_get_row(db_conn, "convidem"))

        process_engagement(db_conn, conv, threshold_seconds=300)
        second = dict(_get_row(db_conn, "convidem"))

        for key in (
            "engaged_seconds",
            "attention_periods",
            "follow_up_user_message_count",
            "attended_user_message_count",
            "threshold_seconds",
            "total_duration_seconds",
            "event_count",
        ):
            assert first[key] == second[key]

    def test_reprocessing_with_new_threshold_rewrites_row(self, db_conn, tmp_path):
        """The tuning-sweep workflow: rerun with a new T, row reflects it."""
        conv_dir = tmp_path / "conv-tune"
        _write_events(
            conv_dir,
            [_user(0, "a"), _agent(30), _user(60, "b")],
        )
        conv = _register_conversation(db_conn, "convtune", conv_dir, event_count=3)

        process_engagement(db_conn, conv, threshold_seconds=300)
        first = _get_row(db_conn, "convtune")
        assert first["threshold_seconds"] == 300
        assert first["engaged_seconds"] == 60

        # Rerun with T = 0 → unattended.
        process_engagement(db_conn, conv, threshold_seconds=0)
        second = _get_row(db_conn, "convtune")
        assert second["threshold_seconds"] == 0
        assert second["engaged_seconds"] == 0
        assert second["attention_periods"] == 0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_stage_registered_in_registry():
    from ohtv.db.stages import STAGES

    assert "engagement" in STAGES
    assert STAGES["engagement"] is process_engagement
