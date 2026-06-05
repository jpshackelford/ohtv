"""CliRunner integration tests for ``ohtv messages`` (Issue #181).

Exercises the Click handler end-to-end: flag wiring, format dispatch
(``text`` / ``json`` / ``raw``), the ``-1`` shorthand, pagination
math, empty-result hints, and 500-char truncation. Seeds a real OHTV
DB + on-disk events so we hit the SAME SQL path
(:meth:`ConversationStore.list_by_event_date_range`) the CLI uses in
production — no mocks.

Pattern lifted from ``tests/unit/test_cli_event_dates_filter.py``
which #180 introduced for the same shape of test.
"""

from __future__ import annotations

import json as _json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main


# ---------------------------------------------------------------------------
# Test ids + clock. Using a fixed T0 keeps the assertions stable across
# wall-clock drift.
# ---------------------------------------------------------------------------
ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32

T0 = datetime(2026, 6, 1, 12, 0)


def _write_event(conv_dir: Path, idx: int, event: dict) -> None:
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    eid = event.get("id", f"e{idx:05d}")
    (events_dir / f"event-{idx:05d}-{eid}.json").write_text(_json.dumps(event))


def _user_evt(idx: int, ts: datetime, text: str) -> dict:
    return {
        "id": f"u-{idx}",
        "timestamp": ts.isoformat(),
        "source": "user",
        "kind": "MessageEvent",
        "llm_message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


@pytest.fixture
def seeded_cli_env(tmp_path, monkeypatch):
    """Seed three conversations with user messages and a fourth with
    only an action event (no user messages).

    * Conv A (cloud, "Auth feature"): 2 user messages at T0 and T0+10m.
    * Conv B (cloud, "Bug fix"):      1 user message at T0+1d.
    * Conv C (local, "Local task"):   1 user message at T0+2d.
    * Conv D (cloud, "No messages"):  only an agent action event.
    """
    monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
    monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(tmp_path / "local"))
    monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(tmp_path / "cloud"))
    monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

    from ohtv.config import Config
    from ohtv.db import get_ready_connection
    from ohtv.db.models.conversation import Conversation
    from ohtv.db.stores import ConversationStore

    config = Config.from_env()
    cloud_dir = config.synced_conversations_dir
    local_dir = config.local_conversations_dir
    cloud_dir.mkdir(parents=True, exist_ok=True)
    local_dir.mkdir(parents=True, exist_ok=True)

    # ---- Disk ----
    _write_event(cloud_dir / ID_A, 0, _user_evt(0, T0, "How do I add OAuth?"))
    _write_event(cloud_dir / ID_A, 1, _user_evt(1, T0 + timedelta(minutes=10), "Also email/password please."))

    _write_event(cloud_dir / ID_B, 0, _user_evt(0, T0 + timedelta(days=1), "There's a memory leak."))

    _write_event(local_dir / ID_C, 0, _user_evt(0, T0 + timedelta(days=2), "Local task message"))

    # Conv D — only an action event, no user MessageEvent.
    _write_event(
        cloud_dir / ID_D,
        0,
        {
            "id": "act-0",
            "timestamp": (T0 + timedelta(hours=2)).isoformat(),
            "source": "agent",
            "kind": "ActionEvent",
            "action": {"command": "ls", "kind": "TerminalAction"},
            "tool_name": "terminal",
        },
    )

    # ---- DB ----
    specs = [
        (ID_A, "Auth feature", "cloud", T0 - timedelta(days=30), T0, T0 + timedelta(minutes=10), 2, str(cloud_dir / ID_A)),
        (ID_B, "Bug fix",      "cloud", T0 - timedelta(days=5),  T0 + timedelta(days=1), T0 + timedelta(days=1), 1, str(cloud_dir / ID_B)),
        (ID_C, "Local task",   "local", T0 - timedelta(days=1),  T0 + timedelta(days=2), T0 + timedelta(days=2), 1, str(local_dir / ID_C)),
        (ID_D, "No messages",  "cloud", T0 - timedelta(days=2),  T0 + timedelta(hours=2), T0 + timedelta(hours=2), 1, str(cloud_dir / ID_D)),
    ]

    with get_ready_connection(show_progress=False) as conn:
        store = ConversationStore(conn)
        for cid, title, source, created, first_ts, last_ts, ev_count, loc in specs:
            store.upsert(
                Conversation(
                    id=cid,
                    location=loc,
                    event_count=ev_count,
                    title=title,
                    created_at=created,
                    updated_at=last_ts,
                    source=source,
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
                    ev_count,
                ),
            )
        conn.commit()

    yield config


def _invoke(*args) -> tuple[int, str]:
    runner = CliRunner()
    # Wide terminal so rich doesn't insert line breaks mid-token.
    result = runner.invoke(main, list(args), env={"COLUMNS": "200"})
    return result.exit_code, result.output


# ===========================================================================
# Format dispatch + -1 shorthand
# ===========================================================================


class TestFormatDispatch:
    def test_default_text_format(self, seeded_cli_env):
        exit_code, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
        )
        assert exit_code == 0, out
        # Text format prints conversation headers.
        assert "Conversation:" in out
        # Footer reports counts.
        assert "Showing" in out and "conversations" in out
        assert "messages)" in out

    def test_format_json_emits_documented_shape(self, seeded_cli_env):
        exit_code, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-F", "json",
        )
        assert exit_code == 0, out
        data = _json.loads(out)
        assert {"total_conversations", "total_messages", "offset",
                "limit", "conversations"}.issubset(data.keys())
        assert isinstance(data["conversations"], list)
        for conv in data["conversations"]:
            assert {"id", "title", "created_at", "source",
                    "event_count", "messages"}.issubset(conv.keys())
            assert isinstance(conv["messages"], list)
            for m in conv["messages"]:
                assert {"timestamp", "text"} == set(m.keys())

    def test_format_raw_one_line_per_message(self, seeded_cli_env):
        exit_code, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-F", "raw",
        )
        assert exit_code == 0, out
        # Strip trailing newline so an empty last line doesn't inflate count.
        lines = out.rstrip("\n").splitlines()
        # 4 user messages in the [05-31, 06-04) range: A×2, B×1, C×1.
        assert len(lines) == 4
        # Each line is tab-separated: short_id, ISO timestamp, text.
        for line in lines:
            parts = line.split("\t")
            assert len(parts) == 3
            assert len(parts[0]) == 8  # short id
            assert parts[1].endswith("Z")  # ISO Z timestamp
            assert "\n" not in parts[2]

    def test_dash_one_aliases_raw(self, seeded_cli_env):
        """``-1`` must produce identical output to ``-F raw``."""
        rc1, out_raw = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-F", "raw",
        )
        rc2, out_dash = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-1",
        )
        assert rc1 == rc2 == 0
        assert out_raw == out_dash


# ===========================================================================
# Pagination — by conversation, not by message
# ===========================================================================


class TestPagination:
    def test_default_limit_is_ten(self, seeded_cli_env):
        """Documented default cap is 10 conversations."""
        exit_code, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-F", "json",
        )
        data = _json.loads(out)
        assert data["limit"] == 10
        assert data["offset"] == 0

    def test_all_drops_cap(self, seeded_cli_env):
        exit_code, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "--all", "-F", "json",
        )
        data = _json.loads(out)
        assert data["limit"] is None

    def test_offset_skips_first_n_conversations(self, seeded_cli_env):
        """``--offset 1`` drops the most-recent conversation only.

        Sort order is newest-first by last in-range user message → Conv C
        (T0+2d) first, then Conv B (T0+1d), then Conv A (T0+10m).
        """
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "--offset", "1", "-F", "json",
        )
        data = _json.loads(out)
        ids = [c["id"] for c in data["conversations"]]
        # First entry (Conv C) is skipped; B and A remain.
        assert ids[0] == ID_B
        # offset is echoed in the response.
        assert data["offset"] == 1

    def test_within_conversation_all_messages_render(self, seeded_cli_env):
        """Conv A has 2 user messages; both must appear under a single
        conversation entry (no per-message cap)."""
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-F", "json",
        )
        data = _json.loads(out)
        conv_a = next(c for c in data["conversations"] if c["id"] == ID_A)
        assert len(conv_a["messages"]) == 2

    def test_text_footer_reports_next_offset_when_paginating(self, seeded_cli_env):
        """When a strict ``-n`` window leaves more conversations
        behind, the footer surfaces the next ``--offset`` hint.

        Also locks down the two-pool footer terminology (#181 review
        round 1): the denominator is "candidate conversations", not
        plain "conversations", because it counts engagement-joined
        candidates (which may include message-free convs).
        """
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-n", "1",
        )
        # Fixture has 4 candidates in range (A, B, C, D — D has only an
        # action event but its engagement row covers the window).
        assert "Showing 1 of 4 candidate conversations" in out
        assert "Next: --offset 1" in out

    def test_next_link_does_not_overshoot_when_candidates_have_no_messages(
        self, seeded_cli_env,
    ):
        """Regression for the 🟠 review-bot thread on
        ``src/ohtv/cli.py:6384`` (Issue #181 review round 1).

        Scenario: 4 candidates in range (A, B, C, D). Candidate sort is
        ``last_event_ts DESC`` → C, B, D, A. Paging with ``-k 2 -n 2``
        gives us candidates [D, A]; D has no user messages, so
        ``shown == 1``. The OLD guard ``(offset + shown) < total`` =
        ``(2 + 1) < 4`` = True would have emitted ``Next: --offset 3``
        — pointing past the end of the candidate pool. The new guard
        ``(offset + limit) < total`` = ``(2 + 2) < 4`` = False
        correctly suppresses the Next link.
        """
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-n", "2", "-k", "2",
        )
        # We showed 1 of 4 candidates on this page (only A had
        # messages; D was filtered out by Pass 2).
        assert "Showing 1 of 4 candidate conversations" in out
        # Critical regression assertion: no Next link.
        assert "Next:" not in out

    def test_text_footer_uses_candidate_terminology(self, seeded_cli_env):
        """Lockdown: the word ``candidate`` appears in the footer so
        future refactors do not silently revert to plain
        ``conversations`` (which conflates the two pools — see #181
        review round 1)."""
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
        )
        assert "candidate conversations" in out

    def test_empty_page_does_not_show_engagement_hint_when_candidates_exist(
        self, seeded_cli_env,
    ):
        """The engagement-stage hint is for the ``total_convs == 0``
        path (no candidates → user probably forgot
        ``ohtv db process engagement``). When candidates exist but the
        paginated window has zero user messages (#181 review round 1
        Repro 3), surfacing the engagement hint MISFIRES; show an
        offset hint instead.

        Scenario: ``-k 2 -n 1`` over the fixture → candidates [D] only,
        D has no user messages → empty groups, total_convs == 4.
        """
        exit_code, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "-n", "1", "-k", "2",
        )
        assert exit_code == 0
        # New "no messages on this page" wording.
        assert "No user messages on this page" in out
        assert "4 candidate conversations in range" in out
        # Offset-aware hint, NOT the engagement hint.
        assert "--offset 0" in out
        # Engagement hint must not fire here.
        assert "db process engagement" not in out


# ===========================================================================
# Date filtering wired through _parse_date_filters
# ===========================================================================


class TestDateFilters:
    def test_since_filters_by_event_timestamp(self, seeded_cli_env):
        """A conversation created 30d before T0 with a fresh message
        still surfaces — the predicate runs against event timestamp."""
        # Conv A was created 30 days before T0 but has user messages at
        # T0; ``--since T0-1d`` must include it.
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "-F", "json",
        )
        data = _json.loads(out)
        ids = {c["id"] for c in data["conversations"]}
        assert ID_A in ids

    def test_until_excludes_future_messages(self, seeded_cli_env):
        """``--until`` is exclusive; messages at-or-after are excluded."""
        # Conv B's message is at T0+1d; until=T0+1d excludes it.
        _, out = _invoke(
            "messages", "--since", "2026-05-31",
            "--until", "2026-06-02",
            "-F", "json",
        )
        data = _json.loads(out)
        ids = {c["id"] for c in data["conversations"]}
        # Conv A is at T0 (in), Conv B at T0+1d == until (excluded).
        assert ID_A in ids
        assert ID_B not in ids


# ===========================================================================
# Source / repo / label scoping
# ===========================================================================


class TestSourceFilter:
    def test_source_local_only(self, seeded_cli_env):
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "--source", "local", "-F", "json",
        )
        data = _json.loads(out)
        ids = {c["id"] for c in data["conversations"]}
        # Only Conv C is local.
        assert ids == {ID_C}

    def test_source_cloud_excludes_local(self, seeded_cli_env):
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-04",
            "--source", "cloud", "-F", "json",
        )
        data = _json.loads(out)
        ids = {c["id"] for c in data["conversations"]}
        assert ID_C not in ids
        # Conv A and Conv B remain (both cloud).
        assert {ID_A, ID_B}.issubset(ids)


# ===========================================================================
# Truncation + --full
# ===========================================================================


class TestTruncation:
    def test_text_mode_truncates_long_messages(self, tmp_path, monkeypatch):
        """A 600-char user message renders with ``…`` suffix by default."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
        monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(tmp_path / "local"))
        monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(tmp_path / "cloud"))
        monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

        from ohtv.config import Config
        from ohtv.db import get_ready_connection
        from ohtv.db.models.conversation import Conversation
        from ohtv.db.stores import ConversationStore

        config = Config.from_env()
        long_text = "x" * 600
        cloud_dir = config.synced_conversations_dir
        cloud_dir.mkdir(parents=True, exist_ok=True)
        _write_event(cloud_dir / ID_A, 0, _user_evt(0, T0, long_text))

        with get_ready_connection(show_progress=False) as conn:
            store = ConversationStore(conn)
            store.upsert(
                Conversation(
                    id=ID_A,
                    location=str(cloud_dir / ID_A),
                    event_count=1,
                    title="Long",
                    created_at=T0,
                    updated_at=T0,
                    source="cloud",
                )
            )
            conn.execute(
                "INSERT INTO conversation_engagement "
                "(conversation_id, threshold_seconds, first_event_ts, "
                "last_event_ts, total_duration_seconds, engaged_seconds, "
                "attention_periods, follow_up_user_message_count, "
                "attended_user_message_count, processed_at, event_count) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, ?, 1)",
                (
                    ID_A, 420,
                    T0.isoformat(),
                    T0.isoformat(),
                    1, 600, T0.isoformat(),
                ),
            )
            conn.commit()

        # Default (no --full) → text-mode output truncates.
        _, default_out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-02",
        )
        assert "…" in default_out
        # The truncated body holds at most 500 ``x`` characters.
        max_run = max((len(s) for s in default_out.split() if s.startswith("x")), default=0)
        assert max_run <= 500

        # ``--full`` → entire 600 chars present.
        _, full_out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-02",
            "--full",
        )
        # Allow rich to wrap; just check the full repetition appears.
        assert ("x" * 600) in full_out.replace("\n", "")

    def test_json_always_carries_full_text(self, tmp_path, monkeypatch):
        """``json`` and ``raw`` ignore the 500-char cap (AC).

        Even without ``--full``, machine-readable formats see the
        whole message body.
        """
        monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
        monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(tmp_path / "local"))
        monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(tmp_path / "cloud"))
        monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

        from ohtv.config import Config
        from ohtv.db import get_ready_connection
        from ohtv.db.models.conversation import Conversation
        from ohtv.db.stores import ConversationStore

        config = Config.from_env()
        long_text = "x" * 700
        cloud_dir = config.synced_conversations_dir
        cloud_dir.mkdir(parents=True, exist_ok=True)
        _write_event(cloud_dir / ID_A, 0, _user_evt(0, T0, long_text))

        with get_ready_connection(show_progress=False) as conn:
            store = ConversationStore(conn)
            store.upsert(
                Conversation(
                    id=ID_A, location=str(cloud_dir / ID_A),
                    event_count=1, title="L", created_at=T0, updated_at=T0,
                    source="cloud",
                )
            )
            conn.execute(
                "INSERT INTO conversation_engagement "
                "(conversation_id, threshold_seconds, first_event_ts, "
                "last_event_ts, total_duration_seconds, engaged_seconds, "
                "attention_periods, follow_up_user_message_count, "
                "attended_user_message_count, processed_at, event_count) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, ?, 1)",
                (ID_A, 420, T0.isoformat(), T0.isoformat(), 1, 600, T0.isoformat()),
            )
            conn.commit()

        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-02",
            "-F", "json",
        )
        data = _json.loads(out)
        assert data["conversations"][0]["messages"][0]["text"] == long_text


# ===========================================================================
# Empty-result path
# ===========================================================================


class TestEmptyResult:
    def test_text_empty_prints_hint(self, seeded_cli_env):
        """Range with no user messages → ``No user messages in range.``
        + engagement-stage hint, exit 0."""
        # Far-future range → nothing.
        exit_code, out = _invoke(
            "messages", "--since", "2030-01-01", "--until", "2030-01-02",
        )
        assert exit_code == 0
        assert "No user messages in range." in out
        # Hint mentions the engagement stage so users know where to look.
        assert "engagement" in out.lower() or "sync" in out.lower()

    def test_json_empty_renders_zero_totals(self, seeded_cli_env):
        exit_code, out = _invoke(
            "messages", "--since", "2030-01-01", "--until", "2030-01-02",
            "-F", "json",
        )
        assert exit_code == 0
        data = _json.loads(out)
        assert data["total_conversations"] == 0
        assert data["total_messages"] == 0
        assert data["conversations"] == []

    def test_raw_empty_prints_nothing(self, seeded_cli_env):
        """``raw`` mode on empty input prints zero output — clean for
        pipelines that don't want a hint on stdout."""
        exit_code, out = _invoke(
            "messages", "--since", "2030-01-01", "--until", "2030-01-02",
            "-1",
        )
        assert exit_code == 0
        assert out.strip() == ""


# ===========================================================================
# Sub-conversation handling (#127 plumbing)
# ===========================================================================


class TestSubConversations:
    def test_default_excludes_subs(self, tmp_path, monkeypatch):
        """Default (no ``--include-sub-conversations``): only roots
        contribute messages."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path / "ohtv"))
        monkeypatch.setenv("OHTV_CONVERSATIONS_DIR", str(tmp_path / "local"))
        monkeypatch.setenv("OHTV_SYNCED_CONVERSATIONS_DIR", str(tmp_path / "cloud"))
        monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

        from ohtv.config import Config
        from ohtv.db import get_ready_connection
        from ohtv.db.stores import ConversationStore
        from ohtv.db.models.conversation import Conversation

        config = Config.from_env()
        cloud_dir = config.synced_conversations_dir
        cloud_dir.mkdir(parents=True, exist_ok=True)

        # Root (A) and a sub of A (B). Each has a user message in range.
        _write_event(cloud_dir / ID_A, 0, _user_evt(0, T0, "root msg"))
        _write_event(cloud_dir / ID_B, 0, _user_evt(0, T0, "sub msg"))

        with get_ready_connection(show_progress=False) as conn:
            store = ConversationStore(conn)
            store.upsert(
                Conversation(
                    id=ID_A, location=str(cloud_dir / ID_A),
                    event_count=1, title="Root", created_at=T0, updated_at=T0,
                    source="cloud",
                )
            )
            store.upsert(
                Conversation(
                    id=ID_B, location=str(cloud_dir / ID_B),
                    event_count=1, title="Sub", created_at=T0, updated_at=T0,
                    source="cloud",
                    parent_conversation_id=ID_A,
                )
            )
            for cid in (ID_A, ID_B):
                conn.execute(
                    "INSERT INTO conversation_engagement "
                    "(conversation_id, threshold_seconds, first_event_ts, "
                    "last_event_ts, total_duration_seconds, engaged_seconds, "
                    "attention_periods, follow_up_user_message_count, "
                    "attended_user_message_count, processed_at, event_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, ?, 1)",
                    (cid, 420, T0.isoformat(), T0.isoformat(), 1, 600, T0.isoformat()),
                )
            conn.commit()

        # Default (roots-only) — only Conv A appears.
        _, out = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-02",
            "-F", "json",
        )
        data = _json.loads(out)
        ids = {c["id"] for c in data["conversations"]}
        assert ids == {ID_A}

        # ``--include-sub-conversations`` — both appear.
        _, out_with_subs = _invoke(
            "messages", "--since", "2026-05-31", "--until", "2026-06-02",
            "--include-sub-conversations", "-F", "json",
        )
        data_subs = _json.loads(out_with_subs)
        ids_subs = {c["id"] for c in data_subs["conversations"]}
        assert ids_subs == {ID_A, ID_B}
