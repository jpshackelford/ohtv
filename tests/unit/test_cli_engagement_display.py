"""Tests for the engagement display path in ``ohtv show`` (Issue #163).

Covers the CLI helpers that render the engagement line and surface
engagement fields in the JSON stats payload. The ``_load_engagement_row``
fast-path is tested via a real SQLite DB to keep us off mocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ohtv.cli import _format_engaged_line, _format_show_stats


# ---------------------------------------------------------------------------
# _format_engaged_line — pure formatting helper
# ---------------------------------------------------------------------------


class TestFormatEngagedLine:
    def test_returns_none_when_engagement_missing(self):
        assert _format_engaged_line(None, timedelta(seconds=600)) is None

    def test_returns_none_when_engaged_seconds_missing(self):
        engagement = {"attention_periods": 2}
        assert _format_engaged_line(engagement, timedelta(seconds=600)) is None

    def test_returns_none_when_periods_missing(self):
        engagement = {"engaged_seconds": 60}
        assert _format_engaged_line(engagement, timedelta(seconds=600)) is None

    def test_renders_with_percentage_and_duration(self):
        engagement = {"engaged_seconds": 264, "attention_periods": 2}
        out = _format_engaged_line(engagement, timedelta(seconds=3000))
        assert out is not None
        # 264 / 3000 = 8.8%
        assert "4m 24s" in out
        assert "in 2 periods" in out
        assert "8.8%" in out
        assert "50m 00s total" in out

    def test_singular_period(self):
        engagement = {"engaged_seconds": 60, "attention_periods": 1}
        out = _format_engaged_line(engagement, timedelta(seconds=120))
        assert out is not None
        assert "in 1 period" in out  # singular, no trailing 's'
        assert "1 periods" not in out

    def test_no_percentage_when_duration_unknown(self):
        engagement = {"engaged_seconds": 60, "attention_periods": 1}
        out = _format_engaged_line(engagement, None)
        assert out == "1m 00s in 1 period"

    def test_no_percentage_when_zero_duration(self):
        engagement = {"engaged_seconds": 60, "attention_periods": 1}
        out = _format_engaged_line(engagement, timedelta(seconds=0))
        assert out == "1m 00s in 1 period"

    def test_zero_engaged_renders_as_0s(self):
        engagement = {"engaged_seconds": 0, "attention_periods": 0}
        out = _format_engaged_line(engagement, timedelta(seconds=600))
        assert out is not None
        assert "0s in 0 periods" in out
        assert "0.0%" in out


# ---------------------------------------------------------------------------
# _format_show_stats — engagement injection
# ---------------------------------------------------------------------------


def _stats_kwargs() -> dict:
    return {
        "conv_id": "abc123",
        "title": "test conversation",
        "first_ts": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "last_ts": datetime(2024, 1, 1, 12, 50, 0, tzinfo=timezone.utc),
        "event_counts": {
            "user_messages": 3,
            "agent_messages": 4,
            "actions": 5,
            "thinking": 0,
            "observations": 5,
            "finish": 1,
        },
    }


class TestFormatShowStatsWithEngagement:
    def test_text_output_includes_engaged_line_when_engagement_present(self):
        engagement = {
            "engaged_seconds": 264,
            "attention_periods": 2,
            "threshold_seconds": 480,
            "total_duration_seconds": 3000,
        }
        out = _format_show_stats(
            **_stats_kwargs(), fmt="text", engagement=engagement
        )
        assert "Engaged:" in out
        assert "4m 24s in 2 periods" in out

    def test_text_output_omits_engaged_line_when_engagement_none(self):
        out = _format_show_stats(**_stats_kwargs(), fmt="text", engagement=None)
        assert "Engaged:" not in out

    def test_markdown_output_includes_engaged_line(self):
        engagement = {"engaged_seconds": 60, "attention_periods": 1}
        out = _format_show_stats(
            **_stats_kwargs(), fmt="markdown", engagement=engagement
        )
        assert "**Engaged:**" in out

    def test_json_output_includes_engagement_keys(self):
        engagement = {
            "engaged_seconds": 264,
            "attention_periods": 2,
            "threshold_seconds": 480,
            "total_duration_seconds": 3000,
        }
        out = _format_show_stats(
            **_stats_kwargs(), fmt="json", engagement=engagement
        )
        parsed = json.loads(out)
        assert parsed["engaged_seconds"] == 264
        assert parsed["attention_periods"] == 2
        assert parsed["engagement_threshold_seconds"] == 480
        assert parsed["total_duration_seconds"] == 3000

    def test_json_output_omits_engagement_keys_when_absent(self):
        out = _format_show_stats(**_stats_kwargs(), fmt="json", engagement=None)
        parsed = json.loads(out)
        assert "engaged_seconds" not in parsed
        assert "attention_periods" not in parsed
        assert "engagement_threshold_seconds" not in parsed
        # The fields that were always there must remain.
        assert parsed["duration_seconds"] == 3000.0
        assert parsed["id"] == "abc123"


# ---------------------------------------------------------------------------
# _load_engagement_row — DB lookup helper
# ---------------------------------------------------------------------------


class TestLoadEngagementRow:
    """End-to-end exercise of the DB lookup using a real (temporary) DB."""

    def test_returns_row_when_present(self, tmp_path, monkeypatch):
        # Point OHTV_DIR at a clean tmp dir so we get a fresh DB.
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))

        from ohtv.cli import _load_engagement_row
        from ohtv.db import get_ready_connection
        from ohtv.db.models import Conversation
        from ohtv.db.stages.engagement import process_engagement
        from ohtv.db.stores import ConversationStore

        # Build a tiny conversation with two attended user messages.
        conv_dir = tmp_path / "conv"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        def _ts(s: int) -> str:
            return (base + timedelta(seconds=s)).isoformat()

        def _user_evt(s: int) -> dict:
            return {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": _ts(s),
                "llm_message": {"content": [{"type": "text", "text": "x"}]},
            }

        def _agent_evt(s: int) -> dict:
            return {
                "kind": "MessageEvent",
                "source": "agent",
                "timestamp": _ts(s),
                "llm_message": {"content": [{"type": "text", "text": "y"}]},
            }

        for i, e in enumerate([_user_evt(0), _agent_evt(30), _user_evt(60)]):
            (events_dir / f"event-{i:06d}.json").write_text(json.dumps(e))

        # Process and persist.
        with get_ready_connection(show_progress=False) as conn:
            conv = Conversation(
                id="convx", location=str(conv_dir), event_count=3
            )
            ConversationStore(conn).upsert(conv)
            process_engagement(conn, conv, threshold_seconds=300)
            conn.commit()

        row = _load_engagement_row("convx")
        assert row is not None
        assert row["engaged_seconds"] == 60
        assert row["attention_periods"] == 1
        assert row["threshold_seconds"] == 300

    def test_returns_none_when_row_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.cli import _load_engagement_row
        from ohtv.db import get_ready_connection

        # Init DB but don't create any rows.
        with get_ready_connection(show_progress=False) as _:
            pass

        assert _load_engagement_row("nonexistent") is None

    def test_normalizes_dashed_conversation_id(self, tmp_path, monkeypatch):
        """LocalSource returns dashed IDs; the DB stores dashless ones."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))

        from ohtv.cli import _load_engagement_row
        from ohtv.db import get_ready_connection
        from ohtv.db.models import Conversation
        from ohtv.db.stages.engagement import process_engagement
        from ohtv.db.stores import ConversationStore

        conv_dir = tmp_path / "conv-dashed"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i, e in enumerate([
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": (base + timedelta(seconds=i * 30)).isoformat(),
                "llm_message": {"content": [{"type": "text", "text": "x"}]},
            }
            for i in range(2)
        ]):
            (events_dir / f"event-{i:06d}.json").write_text(json.dumps(e))

        with get_ready_connection(show_progress=False) as conn:
            conv = Conversation(
                id="abcdef0123456789abcdef0123456789",
                location=str(conv_dir),
                event_count=2,
            )
            ConversationStore(conn).upsert(conv)
            process_engagement(conn, conv, threshold_seconds=300)
            conn.commit()

        # The store row is dashless; the LOOKUP key uses dashes — must
        # be normalized internally.
        dashed = "abcdef01-2345-6789-abcd-ef0123456789"
        row = _load_engagement_row(dashed)
        assert row is not None
        assert row["engaged_seconds"] == 30  # block (0, 30)


# ---------------------------------------------------------------------------
# Stage CLI wiring — engagement is in `db process all` order
# ---------------------------------------------------------------------------


def test_engagement_stage_is_in_all_choices():
    """`db process engagement` must be a valid stage choice."""
    from ohtv.db.stages import STAGES

    assert "engagement" in STAGES
    # Ordering: engagement comes after contributions so other reports
    # remain unaffected by its placement.
    keys = list(STAGES.keys())
    assert keys.index("engagement") > keys.index("contributions")


@pytest.mark.parametrize("threshold_minutes", [6, 8, 12, 14, 16, 18, 20, 22, 24, 26, 28])
def test_compute_engagement_handles_all_sweep_thresholds(threshold_minutes):
    """Smoke-test the threshold values from the tuning sweep."""
    from ohtv.db.stages.engagement import compute_engagement

    base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _ts(s: int) -> str:
        return (base + timedelta(seconds=s)).isoformat()

    events = [
        {
            "kind": "MessageEvent",
            "source": "user",
            "timestamp": _ts(0),
            "llm_message": {"content": [{"type": "text", "text": "a"}]},
        },
        {
            "kind": "MessageEvent",
            "source": "agent",
            "timestamp": _ts(60),
            "llm_message": {"content": [{"type": "text", "text": "b"}]},
        },
        {
            "kind": "MessageEvent",
            "source": "user",
            "timestamp": _ts(120),
            "llm_message": {"content": [{"type": "text", "text": "c"}]},
        },
    ]
    result = compute_engagement(events, threshold_seconds=threshold_minutes * 60)
    # All gaps are 60s; every threshold ≥ 6min = 360s ≫ 60s → attended.
    assert result.engaged_seconds == 120
    assert result.attention_periods == 1
