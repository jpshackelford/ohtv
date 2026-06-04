"""Pure-Python unit tests for :mod:`ohtv.messages` (Issue #181).

Covers the message-extraction logic, on-disk event loading, truncation
and single-line collapse helpers, and the conversation-grouped
``collect_messages`` aggregator. The CLI surface is tested separately
in ``test_cli_messages.py`` via :class:`click.testing.CliRunner`.

These tests deliberately avoid mocking
:meth:`ConversationStore.list_by_event_date_range` — they seed a real
SQLite database via :func:`get_ready_connection` so we exercise the
same SQL path the CLI uses. The pattern mirrors
``tests/unit/test_cli_event_dates_filter.py`` which #180 introduced.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ohtv.messages import (
    ConversationMessages,
    TEXT_TRUNCATION_CHARS,
    UserMessage,
    collapse_to_single_line,
    collect_messages,
    extract_user_messages,
    truncate_text,
)
from ohtv.sources.base import ConversationInfo


# ---------------------------------------------------------------------------
# Test constants — 32-char dashless hex ids match the on-disk layout
# and the DB primary key (AGENTS.md item #14).
# ---------------------------------------------------------------------------
ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32

T0 = datetime(2026, 6, 1, 12, 0)  # Naive — matches fixture events.


# ---------------------------------------------------------------------------
# Helpers for writing fixture conversations.
# ---------------------------------------------------------------------------


def _write_event(conv_dir: Path, idx: int, event: dict) -> None:
    """Write a single event JSON to ``conv_dir/events/event-NNNNN-id.json``.

    Filename matches the production layout (``event-<5digits>-<id>.json``)
    so :func:`ohtv.messages._load_events`'s ``sorted(glob)`` yields a
    deterministic order.
    """
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_id = event.get("id", f"evt{idx:05d}")
    path = events_dir / f"event-{idx:05d}-{event_id}.json"
    path.write_text(json.dumps(event))


def _user_message_event(idx: int, ts: datetime, text: str | list) -> dict:
    """Construct a fixture user MessageEvent.

    ``text`` may be a string (rendered as a top-level ``content``
    fallback) or a list of ``{type, text}`` dicts (the canonical
    cloud shape).
    """
    if isinstance(text, list):
        content = text
    else:
        content = [{"type": "text", "text": text}]
    return {
        "id": f"user-{idx}",
        "timestamp": ts.isoformat(),
        "source": "user",
        "kind": "MessageEvent",
        "llm_message": {"role": "user", "content": content},
    }


def _agent_message_event(idx: int, ts: datetime, text: str) -> dict:
    """Construct a fixture agent MessageEvent (filtered out by extract)."""
    return {
        "id": f"agent-{idx}",
        "timestamp": ts.isoformat(),
        "source": "agent",
        "kind": "MessageEvent",
        "llm_message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _action_event(idx: int, ts: datetime) -> dict:
    """Construct a fixture agent ActionEvent (filtered out by extract)."""
    return {
        "id": f"act-{idx}",
        "timestamp": ts.isoformat(),
        "source": "agent",
        "kind": "ActionEvent",
        "action": {"command": "ls", "kind": "TerminalAction"},
        "tool_name": "terminal",
    }


def _conv_info(
    conv_id: str,
    *,
    title: str = "Test conv",
    source: str = "cloud",
    created_at: datetime | None = None,
    event_count: int = 5,
) -> ConversationInfo:
    """Build a ConversationInfo carrying a dashed id (matches what
    :func:`_db_conv_to_info` returns to the CLI).
    """
    return ConversationInfo(
        id=conv_id,
        title=title,
        created_at=created_at,
        updated_at=created_at,
        event_count=event_count,
        source=source,
        dir_name=conv_id.replace("-", ""),
    )


# ===========================================================================
# 1. Truncation + single-line helpers (pure functions, no I/O).
# ===========================================================================


class TestTruncateText:
    def test_short_text_returned_unchanged(self):
        assert truncate_text("hello", 500) == "hello"

    def test_text_at_boundary_unchanged(self):
        # Exactly ``max_chars`` characters → no truncation.
        text = "x" * 500
        assert truncate_text(text, 500) == text

    def test_text_over_boundary_truncated(self):
        text = "x" * 600
        result = truncate_text(text, 500)
        assert len(result) == 501  # 500 chars + 1 ellipsis char
        assert result.endswith("…")
        assert result[:-1] == "x" * 500

    def test_default_cutoff_matches_constant(self):
        text = "x" * (TEXT_TRUNCATION_CHARS + 10)
        result = truncate_text(text)
        assert len(result) == TEXT_TRUNCATION_CHARS + 1
        assert result.endswith("…")

    def test_zero_or_negative_max_chars_returns_unchanged(self):
        # Defensive — caller bug; we don't truncate to nothing.
        assert truncate_text("hello", 0) == "hello"
        assert truncate_text("hello", -1) == "hello"


class TestCollapseToSingleLine:
    def test_no_newlines_unchanged(self):
        assert collapse_to_single_line("simple text") == "simple text"

    def test_unix_newlines_become_arrow(self):
        assert collapse_to_single_line("line1\nline2") == "line1⏎line2"

    def test_windows_newlines_become_single_arrow(self):
        # ``\r\n`` must NOT produce two arrows.
        assert collapse_to_single_line("line1\r\nline2") == "line1⏎line2"

    def test_bare_cr_becomes_arrow(self):
        assert collapse_to_single_line("a\rb") == "a⏎b"

    def test_tabs_collapse_to_spaces(self):
        # Tabs in user text must not break the tab-delimited raw format.
        assert collapse_to_single_line("col1\tcol2") == "col1    col2"

    def test_mixed_whitespace(self):
        text = "line1\nline2\tindent\r\nline3"
        assert (
            collapse_to_single_line(text)
            == "line1⏎line2    indent⏎line3"
        )


# ===========================================================================
# 2. extract_user_messages — on-disk event filtering.
# ===========================================================================


class TestExtractUserMessages:
    def test_filters_by_source_and_kind(self, tmp_path):
        """Only ``source=user`` ``kind=MessageEvent`` events survive.

        Agent messages, agent actions, and any other event type are
        dropped before timestamp filtering even runs.
        """
        conv_dir = tmp_path / "conv"
        _write_event(conv_dir, 0, _user_message_event(0, T0, "first"))
        _write_event(conv_dir, 1, _agent_message_event(1, T0 + timedelta(minutes=1), "ack"))
        _write_event(conv_dir, 2, _action_event(2, T0 + timedelta(minutes=2)))
        _write_event(conv_dir, 3, _user_message_event(3, T0 + timedelta(minutes=3), "second"))

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=None, until=None)

        assert [m.text for m in msgs] == ["first", "second"]
        # Conv context is propagated onto every message.
        assert all(m.conv_id == ID_A for m in msgs)
        assert all(m.conv_title == "Test conv" for m in msgs)
        assert all(m.source == "cloud" for m in msgs)

    def test_respects_since_until_half_open(self, tmp_path):
        """``since`` is inclusive, ``until`` is exclusive (half-open)."""
        conv_dir = tmp_path / "conv"
        _write_event(conv_dir, 0, _user_message_event(0, T0, "at-since"))
        _write_event(conv_dir, 1, _user_message_event(1, T0 + timedelta(minutes=10), "in-range"))
        _write_event(conv_dir, 2, _user_message_event(2, T0 + timedelta(minutes=30), "at-until"))
        _write_event(conv_dir, 3, _user_message_event(3, T0 + timedelta(hours=1), "after-until"))

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(
            conv,
            conv_dir,
            since=T0,
            until=T0 + timedelta(minutes=30),
        )

        # ``at-since`` (==since) IN, ``at-until`` (==until) OUT.
        assert [m.text for m in msgs] == ["at-since", "in-range"]

    def test_handles_malformed_json_silently(self, tmp_path):
        """Corrupt event files are skipped (no exception bubbles up)."""
        conv_dir = tmp_path / "conv"
        _write_event(conv_dir, 0, _user_message_event(0, T0, "ok"))
        # Hand-write a corrupt JSON file.
        events_dir = conv_dir / "events"
        (events_dir / "event-00001-bad.json").write_text("{ not json")

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=None, until=None)

        assert len(msgs) == 1
        assert msgs[0].text == "ok"

    def test_extracts_multipart_content(self, tmp_path):
        """Multi-part ``llm_message.content`` arrays concatenate with newlines.

        Matches :func:`ohtv.cli._extract_message_content` verbatim.
        """
        conv_dir = tmp_path / "conv"
        _write_event(
            conv_dir,
            0,
            _user_message_event(
                0,
                T0,
                [
                    {"type": "text", "text": "part one"},
                    {"type": "text", "text": "part two"},
                ],
            ),
        )

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=None, until=None)

        assert msgs[0].text == "part one\npart two"

    def test_handles_string_content(self, tmp_path):
        """Direct ``content: "..."`` string is supported as a fallback."""
        conv_dir = tmp_path / "conv"
        event = {
            "id": "user-0",
            "timestamp": T0.isoformat(),
            "source": "user",
            "kind": "MessageEvent",
            "llm_message": {"role": "user", "content": "plain string"},
        }
        _write_event(conv_dir, 0, event)

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=None, until=None)

        assert msgs[0].text == "plain string"

    def test_sorts_by_timestamp_ascending(self, tmp_path):
        """Out-of-order filenames still produce chronological results."""
        conv_dir = tmp_path / "conv"
        # Write in reverse chronological filename order.
        _write_event(conv_dir, 0, _user_message_event(0, T0 + timedelta(minutes=20), "late"))
        _write_event(conv_dir, 1, _user_message_event(1, T0, "early"))
        _write_event(conv_dir, 2, _user_message_event(2, T0 + timedelta(minutes=10), "middle"))

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=None, until=None)

        assert [m.text for m in msgs] == ["early", "middle", "late"]

    def test_skips_events_without_timestamp(self, tmp_path):
        """An event without a parseable timestamp is dropped silently."""
        conv_dir = tmp_path / "conv"
        _write_event(conv_dir, 0, _user_message_event(0, T0, "ok"))
        no_ts = {
            "id": "user-1",
            "source": "user",
            "kind": "MessageEvent",
            "llm_message": {"role": "user", "content": "no timestamp"},
        }
        _write_event(conv_dir, 1, no_ts)

        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=None, until=None)

        assert len(msgs) == 1
        assert msgs[0].text == "ok"

    def test_missing_events_dir_returns_empty(self, tmp_path):
        """Conversation directory with no ``events/`` subdir → empty list."""
        conv_dir = tmp_path / "empty"
        conv_dir.mkdir()
        conv = _conv_info(ID_A, created_at=T0)
        assert extract_user_messages(conv, conv_dir, since=None, until=None) == []

    def test_handles_aware_since_with_naive_event_timestamps(self, tmp_path):
        """Aware ``since`` doesn't crash when events are naive.

        Cloud event timestamps are written without zone info; CLI
        ``--since`` may yield aware datetimes. We coerce both to naive
        rather than raise ``TypeError``.
        """
        conv_dir = tmp_path / "conv"
        _write_event(conv_dir, 0, _user_message_event(0, T0, "in"))
        _write_event(conv_dir, 1, _user_message_event(1, T0 - timedelta(hours=1), "out"))

        aware_since = T0.replace(tzinfo=timezone.utc) - timedelta(minutes=30)
        conv = _conv_info(ID_A, created_at=T0)
        msgs = extract_user_messages(conv, conv_dir, since=aware_since, until=None)

        assert [m.text for m in msgs] == ["in"]


# ===========================================================================
# 3. collect_messages — DB candidate + FS event load integration.
# ===========================================================================


@pytest.fixture
def seeded_collect_env(tmp_path, monkeypatch):
    """Seed a real OHTV DB + on-disk conversations for ``collect_messages``.

    Three conversations:

    * ``ID_A`` (cloud) — 2 user messages in [T0, T0+1d], 1 agent msg.
    * ``ID_B`` (cloud) — 1 user message at T0+2d.
    * ``ID_C`` (cloud) — 0 user messages, only an action event in range.

    Each has a matching ``conversation_engagement`` row so
    ``list_by_event_date_range`` includes them.
    """
    # Isolate ALL ohtv state inside ``tmp_path``: the SQLite DB
    # (OHTV_DIR), the local conv dir (OHTV_CONVERSATIONS_DIR), and the
    # synced cloud conv dir (OHTV_SYNCED_CONVERSATIONS_DIR). Otherwise
    # ``Config.from_env`` falls back to ``~/.openhands/conversations``
    # and tests pollute each other's on-disk events.
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))
    monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(tmp_path / "local"))
    monkeypatch.setenv(
        "OHTV_SYNCED_CONVERSATIONS_DIR", str(tmp_path / "cloud")
    )

    from ohtv.config import Config
    from ohtv.db import get_ready_connection
    from ohtv.db.models.conversation import Conversation
    from ohtv.db.stores import ConversationStore

    config = Config.from_env()
    cloud_dir = config.synced_conversations_dir
    cloud_dir.mkdir(parents=True, exist_ok=True)

    # ---- On-disk events ----
    conv_a = cloud_dir / ID_A
    _write_event(conv_a, 0, _user_message_event(0, T0, "first A message"))
    _write_event(conv_a, 1, _agent_message_event(1, T0 + timedelta(minutes=30), "agent"))
    _write_event(conv_a, 2, _user_message_event(2, T0 + timedelta(days=1), "second A message"))

    conv_b = cloud_dir / ID_B
    _write_event(conv_b, 0, _user_message_event(0, T0 + timedelta(days=2), "only B"))

    conv_c = cloud_dir / ID_C
    _write_event(conv_c, 0, _action_event(0, T0 + timedelta(hours=3)))

    # ---- DB rows ----
    specs = [
        (ID_A, "Conv A", T0 - timedelta(days=10), T0, T0 + timedelta(days=1)),
        (ID_B, "Conv B", T0 - timedelta(days=5), T0 + timedelta(days=2), T0 + timedelta(days=2)),
        (ID_C, "Conv C", T0 - timedelta(days=3), T0 + timedelta(hours=3), T0 + timedelta(hours=3)),
    ]

    with get_ready_connection(show_progress=False) as conn:
        store = ConversationStore(conn)
        for cid, title, created, first_ts, last_ts in specs:
            store.upsert(
                Conversation(
                    id=cid,
                    location=str(cloud_dir / cid),
                    event_count=3 if cid == ID_A else 1,
                    title=title,
                    created_at=created,
                    updated_at=last_ts,
                    source="cloud",
                )
            )
            conn.execute(
                "INSERT INTO conversation_engagement "
                "(conversation_id, threshold_seconds, first_event_ts, "
                "last_event_ts, total_duration_seconds, engaged_seconds, "
                "attention_periods, follow_up_user_message_count, "
                "attended_user_message_count, processed_at, event_count) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, ?, ?)",
                (
                    cid, 420,
                    first_ts.isoformat(),
                    last_ts.isoformat(),
                    int((last_ts - first_ts).total_seconds()) or 1,
                    600,
                    T0.isoformat(),
                    3 if cid == ID_A else 1,
                ),
            )
        conn.commit()

    yield config


class TestCollectMessages:
    def test_returns_only_conversations_with_user_messages(self, seeded_collect_env):
        """Conv C is dropped (zero user messages) but still counted."""
        config = seeded_collect_env
        groups, total_convs, total_msgs = collect_messages(
            config,
            since=T0 - timedelta(days=1),
            until=T0 + timedelta(days=5),
            source=None,
            repo=None,
            label=None,
            include_subs=False,
            limit=None,
            offset=0,
        )

        ids = {g.conv.id.replace("-", "") for g in groups}
        assert ids == {ID_A, ID_B}, "Conv C has no user messages"
        # total_conversations counts the DB candidate set (includes C).
        assert total_convs == 3
        # total_messages counts only the displayed groups.
        assert total_msgs == 3  # A has 2, B has 1

    def test_filters_by_event_timestamp_not_created_at(self, seeded_collect_env):
        """A conversation created far outside the range surfaces if its
        user messages are in range."""
        config = seeded_collect_env
        # Conv A was created 10 days before T0 but has messages in range.
        groups, _, _ = collect_messages(
            config,
            since=T0 - timedelta(hours=1),
            until=T0 + timedelta(hours=1),
            source=None,
            repo=None,
            label=None,
            include_subs=False,
            limit=None,
            offset=0,
        )

        # Only Conv A has a user message in the [T0-1h, T0+1h] window.
        ids = {g.conv.id.replace("-", "") for g in groups}
        assert ids == {ID_A}
        # And within that window, only the "first A message" qualifies.
        assert [m.text for m in groups[0].messages] == ["first A message"]

    def test_pagination_offset_and_limit_by_conversation(self, seeded_collect_env):
        """``offset`` + ``limit`` paginate at the CONVERSATION grain.

        Within a shown conversation, ALL matching user messages render
        (AC: no per-message cap).
        """
        config = seeded_collect_env

        # offset=1, limit=1 → skip the most-recent (B), keep the next (A).
        groups, total_convs, _ = collect_messages(
            config,
            since=T0 - timedelta(days=1),
            until=T0 + timedelta(days=5),
            source=None,
            repo=None,
            label=None,
            include_subs=False,
            limit=1,
            offset=1,
        )

        # Both Conv A's user messages render in the single shown conv.
        assert len(groups) == 1
        assert len(groups[0].messages) == 2  # No per-message cap.
        # The candidate denominator still reports all 3 DB convs.
        assert total_convs == 3

    def test_groups_sorted_newest_first(self, seeded_collect_env):
        """Conv B's user message (T0+2d) is more recent than Conv A's
        last (T0+1d), so B sorts before A."""
        config = seeded_collect_env
        groups, _, _ = collect_messages(
            config,
            since=T0 - timedelta(days=1),
            until=T0 + timedelta(days=5),
            source=None,
            repo=None,
            label=None,
            include_subs=False,
            limit=None,
            offset=0,
        )

        ids = [g.conv.id.replace("-", "") for g in groups]
        assert ids == [ID_B, ID_A]

    def test_no_db_returns_empty(self, tmp_path, monkeypatch):
        """No DB file → empty result (the CLI prints the hint)."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path / "nodb"))
        monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))
        from ohtv.config import Config

        groups, total_convs, total_msgs = collect_messages(
            Config.from_env(),
            since=T0,
            until=T0 + timedelta(days=1),
            source=None,
            repo=None,
            label=None,
            include_subs=False,
            limit=10,
            offset=0,
        )
        assert groups == []
        assert total_convs == 0
        assert total_msgs == 0


# ===========================================================================
# 4. Dataclass smoke — make sure UserMessage / ConversationMessages
#    are constructible with the documented shape.
# ===========================================================================


class TestDataclasses:
    def test_user_message_fields(self):
        msg = UserMessage(
            conv_id=ID_A,
            conv_title="Title",
            conv_created_at=T0,
            source="cloud",
            event_count=5,
            timestamp=T0,
            text="hello",
        )
        assert msg.conv_id == ID_A
        assert msg.text == "hello"

    def test_conversation_messages_defaults(self):
        conv = _conv_info(ID_A, created_at=T0)
        cm = ConversationMessages(conv=conv)
        assert cm.conv is conv
        assert cm.messages == []
