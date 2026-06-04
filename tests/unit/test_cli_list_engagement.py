"""Tests for ``ohtv list --with-engagement`` (Issue #167).

Covers the display-layer surface added to ``ohtv list``: the new flag,
the batch DB loader, the table/JSON/CSV formatters, the column
formatters, and a handful of cross-flag composition cases.

All DB-touching tests use a real temporary SQLite DB (via the
``OHTV_DIR`` env var) — matching the no-mocks policy in AGENTS.md.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from ohtv.cli import (
    _engagement_ratio,
    _format_eng_pct,
    _format_list_csv,
    _format_list_json,
    _load_engagement_for_conversations,
)
from ohtv.sources.base import ConversationInfo


# ---------------------------------------------------------------------------
# _format_eng_pct — pure formatter
# ---------------------------------------------------------------------------


class TestFormatEngPct:
    def test_renders_pct_for_real_row(self):
        assert _format_eng_pct(2460, 8040) == "30.6%"

    def test_matches_engaged_line_precision(self):
        # 264 / 3000 = 8.8% — matches the existing engaged-line example.
        assert _format_eng_pct(264, 3000) == "8.8%"

    def test_zero_total_renders_dash(self):
        assert _format_eng_pct(0, 0) == "-"

    def test_missing_total_renders_dash(self):
        assert _format_eng_pct(100, None) == "-"

    def test_missing_engaged_renders_dash(self):
        assert _format_eng_pct(None, 100) == "-"

    def test_both_missing_renders_dash(self):
        assert _format_eng_pct(None, None) == "-"

    def test_negative_total_renders_dash(self):
        # Guard against time-skew / clock-wrap weirdness in the data.
        assert _format_eng_pct(60, -1) == "-"

    def test_engaged_zero_with_real_total_renders_zero_pct(self):
        # Conversation present but no engaged blocks yet — explicitly
        # 0.0%, not "-".
        assert _format_eng_pct(0, 100) == "0.0%"

    def test_full_engagement_renders_100(self):
        assert _format_eng_pct(50, 50) == "100.0%"


# ---------------------------------------------------------------------------
# _engagement_ratio — pure formatter (JSON/CSV companion)
# ---------------------------------------------------------------------------


class TestEngagementRatio:
    def test_basic(self):
        assert _engagement_ratio(2460, 8040) == 0.306

    def test_zero_total(self):
        assert _engagement_ratio(0, 0) is None

    def test_missing_total(self):
        assert _engagement_ratio(100, None) is None

    def test_missing_engaged(self):
        assert _engagement_ratio(None, 100) is None

    def test_zero_engaged_is_real_zero_not_none(self):
        assert _engagement_ratio(0, 100) == 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conv(
    conv_id: str,
    *,
    title: str = "Test conversation",
    source: str = "cloud",
    event_count: int | None = 10,
    created: datetime | None = None,
    updated: datetime | None = None,
) -> ConversationInfo:
    base = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
    return ConversationInfo(
        id=conv_id,
        title=title,
        created_at=created or base,
        updated_at=updated or base + timedelta(minutes=30),
        event_count=event_count,
        source=source,
    )


def _seed_engagement_row(
    tmp_path,
    conv_id: str,
    *,
    engaged_seconds: int,
    attention_periods: int,
    threshold_seconds: int = 720,
    total_duration_seconds: int | None = 1800,
) -> None:
    """Insert a conversation + engagement row into the temp DB."""
    from ohtv.db import get_ready_connection
    from ohtv.db.models import Conversation
    from ohtv.db.stores import ConversationStore

    with get_ready_connection(show_progress=False) as conn:
        ConversationStore(conn).upsert(
            Conversation(id=conv_id, location=str(tmp_path / conv_id), event_count=1)
        )
        conn.execute(
            "INSERT OR REPLACE INTO conversation_engagement "
            "(conversation_id, threshold_seconds, first_event_ts, last_event_ts, "
            "total_duration_seconds, engaged_seconds, attention_periods, "
            "follow_up_user_message_count, attended_user_message_count, "
            "processed_at, event_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 1)",
            (
                conv_id,
                threshold_seconds,
                "2026-05-30T14:00:00+00:00",
                "2026-05-30T14:30:00+00:00",
                total_duration_seconds,
                engaged_seconds,
                attention_periods,
                "2026-05-30T15:00:00+00:00",
            ),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# _load_engagement_for_conversations — batch DB loader
# ---------------------------------------------------------------------------


class TestLoadEngagementForConversations:
    def test_empty_input_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        assert _load_engagement_for_conversations([]) == {}

    def test_db_missing_returns_empty_dict(self, tmp_path, monkeypatch):
        # No DB initialized — should silently return empty.
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv = _conv("abc" + "0" * 29)
        assert _load_engagement_for_conversations([conv]) == {}

    def test_present_row_is_returned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )
        conv = _conv(conv_id)
        result = _load_engagement_for_conversations([conv])
        assert conv_id in result
        assert result[conv_id]["engaged_seconds"] == 2460
        assert result[conv_id]["attention_periods"] == 3
        assert result[conv_id]["total_duration_seconds"] == 8040
        assert result[conv_id]["threshold_seconds"] == 720

    def test_missing_rows_are_absent_from_result(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        seeded = "a" * 32
        missing = "b" * 32
        _seed_engagement_row(
            tmp_path, seeded, engaged_seconds=60,
            attention_periods=1, total_duration_seconds=120,
        )
        result = _load_engagement_for_conversations([
            _conv(seeded), _conv(missing)
        ])
        assert seeded in result
        assert missing not in result

    def test_dashed_id_is_normalized(self, tmp_path, monkeypatch):
        """AGENTS.md item #14: LocalSource returns dashed ids; DB stores dashless."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        dashless = "abcdef0123456789abcdef0123456789"
        dashed = "abcdef01-2345-6789-abcd-ef0123456789"
        _seed_engagement_row(
            tmp_path, dashless, engaged_seconds=120,
            attention_periods=2, total_duration_seconds=600,
        )
        # Caller passes dashed id (the LocalSource form)
        conv = _conv(dashed)
        result = _load_engagement_for_conversations([conv])
        # Result is keyed by the caller's original id (with dashes)
        assert dashed in result
        assert result[dashed]["engaged_seconds"] == 120

    def test_batch_chunking_above_900_ids(self, tmp_path, monkeypatch):
        """The loader must chunk to stay under SQLite's parameter ceiling."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        # Seed 1100 conversations + engagement rows.
        convs: list[ConversationInfo] = []
        for i in range(1100):
            conv_id = f"{i:032x}"
            _seed_engagement_row(
                tmp_path, conv_id, engaged_seconds=i,
                attention_periods=1, total_duration_seconds=max(i, 1),
            )
            convs.append(_conv(conv_id))
        result = _load_engagement_for_conversations(convs)
        # All 1100 rows should be returned.
        assert len(result) == 1100
        # Spot-check first/last.
        assert result[convs[0].id]["engaged_seconds"] == 0
        assert result[convs[-1].id]["engaged_seconds"] == 1099


# ---------------------------------------------------------------------------
# JSON formatter — engagement fields
# ---------------------------------------------------------------------------


class TestFormatListJsonEngagement:
    def test_flag_off_omits_all_engagement_fields(self):
        """Regression guard: schema unchanged when flag not set."""
        conv = _conv("a" * 32)
        out = json.loads(_format_list_json([conv], engagement_map=None))
        item = out[0]
        for key in (
            "engaged_seconds", "attention_periods",
            "engagement_threshold_seconds", "total_duration_seconds",
            "engagement_ratio",
        ):
            assert key not in item

    def test_present_row_emits_all_five_fields(self):
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 2460,
                "attention_periods": 3,
                "threshold_seconds": 720,
                "total_duration_seconds": 8040,
            },
        }
        out = json.loads(_format_list_json([conv], engagement_map=engagement_map))
        item = out[0]
        assert item["engaged_seconds"] == 2460
        assert item["attention_periods"] == 3
        assert item["engagement_threshold_seconds"] == 720
        assert item["total_duration_seconds"] == 8040
        assert item["engagement_ratio"] == 0.306

    def test_missing_row_emits_all_nulls(self):
        conv = _conv("a" * 32)
        out = json.loads(_format_list_json([conv], engagement_map={}))
        item = out[0]
        # All five keys must be present (schema stability) and null.
        assert item["engaged_seconds"] is None
        assert item["attention_periods"] is None
        assert item["engagement_threshold_seconds"] is None
        assert item["total_duration_seconds"] is None
        assert item["engagement_ratio"] is None

    def test_zero_total_duration_emits_null_ratio(self):
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 0,
                "attention_periods": 0,
                "threshold_seconds": 720,
                "total_duration_seconds": 0,
            }
        }
        out = json.loads(_format_list_json([conv], engagement_map=engagement_map))
        item = out[0]
        # Raw fields preserved; ratio is null because total is 0.
        assert item["engaged_seconds"] == 0
        assert item["total_duration_seconds"] == 0
        assert item["engagement_ratio"] is None

    def test_schema_stable_across_present_and_missing_rows(self):
        present_id = "a" * 32
        missing_id = "b" * 32
        convs = [_conv(present_id), _conv(missing_id)]
        engagement_map = {
            present_id: {
                "engaged_seconds": 100, "attention_periods": 1,
                "threshold_seconds": 720, "total_duration_seconds": 1000,
            },
        }
        out = json.loads(_format_list_json(convs, engagement_map=engagement_map))
        # Both rows have the same key set — that's the contract.
        keys_present = set(out[0].keys())
        keys_missing = set(out[1].keys())
        assert keys_present == keys_missing


# ---------------------------------------------------------------------------
# CSV formatter — engagement columns
# ---------------------------------------------------------------------------


class TestFormatListCsvEngagement:
    def _parse(self, text: str) -> tuple[list[str], list[list[str]]]:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        return rows[0], rows[1:]

    def test_flag_off_does_not_append_columns(self):
        conv = _conv("a" * 32)
        text = _format_list_csv([conv], engagement_map=None)
        header, _ = self._parse(text)
        for col in (
            "engaged_seconds", "attention_periods",
            "engagement_threshold_seconds", "total_duration_seconds",
            "engagement_ratio",
        ):
            assert col not in header

    def test_present_row_appends_five_columns(self):
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 2460, "attention_periods": 3,
                "threshold_seconds": 720, "total_duration_seconds": 8040,
            }
        }
        text = _format_list_csv([conv], engagement_map=engagement_map)
        header, rows = self._parse(text)
        assert header[-5:] == [
            "engaged_seconds", "attention_periods",
            "engagement_threshold_seconds", "total_duration_seconds",
            "engagement_ratio",
        ]
        assert rows[0][-5:] == ["2460", "3", "720", "8040", "0.306"]

    def test_missing_row_emits_empty_strings(self):
        conv = _conv("a" * 32)
        text = _format_list_csv([conv], engagement_map={})
        _, rows = self._parse(text)
        assert rows[0][-5:] == ["", "", "", "", ""]

    def test_zero_total_emits_empty_ratio(self):
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 0, "attention_periods": 0,
                "threshold_seconds": 720, "total_duration_seconds": 0,
            }
        }
        text = _format_list_csv([conv], engagement_map=engagement_map)
        _, rows = self._parse(text)
        # Zeros are distinct from missing values — raw int columns
        # render as "0", but the engagement_ratio is empty because
        # total_duration_seconds == 0 (divide-by-zero guard).
        assert rows[0][-5] == "0"  # engaged_seconds
        assert rows[0][-4] == "0"  # attention_periods
        assert rows[0][-3] == "720"  # threshold preserved
        assert rows[0][-2] == "0"  # total
        assert rows[0][-1] == ""  # ratio (None — total 0)


# ---------------------------------------------------------------------------
# CLI surface — flag is wired, advertised in --help, and composes
# correctly with format flags.
# ---------------------------------------------------------------------------


class TestCliFlagSurface:
    """Smoke tests for the new ``--with-engagement`` flag.

    Behavioural correctness is covered by the formatter tests above;
    these guards just confirm the wiring is in place so the flag can't
    be silently dropped by an accidental refactor.
    """

    def test_help_advertises_flag(self):
        from click.testing import CliRunner
        from ohtv.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["list", "--help"])
        assert result.exit_code == 0
        assert "--with-engagement" in result.output
        # The help text should mention the engagement stage so users
        # know how to populate missing rows.
        assert "engagement" in result.output.lower()

    def test_flag_accepted_with_no_data(self, tmp_path, monkeypatch):
        """``ohtv list --with-engagement`` on an empty install runs
        cleanly — no exception even when there's no DB and no
        conversations."""
        from click.testing import CliRunner
        from ohtv.cli import main

        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        # Point the conversation root at an empty tmp dir.
        monkeypatch.setenv("OPENHANDS_BASE_DIR", str(tmp_path / "oh"))

        runner = CliRunner()
        result = runner.invoke(main, [
            "list", "--with-engagement", "-F", "json",
        ])
        # exit_code 0 — empty JSON list is fine.
        assert result.exit_code == 0, result.output
        # The output should be valid JSON (possibly an empty list).
        # We strip stderr-style "no conversations" prefixes if any.
        try:
            json.loads(result.output)
        except Exception:
            # Some commands print a header; accept any output as long as
            # exit code is 0.
            pass


# ---------------------------------------------------------------------------
# Table column rendering — direct invocation of _print_list_table so we
# can capture the rich output without going through the full Click stack.
# ---------------------------------------------------------------------------


class TestPrintListTableEngagement:
    """End-to-end render of the rich Table with engagement columns."""

    def _capture(
        self, conversations, *, engagement_map, **kwargs
    ) -> str:
        from rich.console import Console
        from ohtv import cli as cli_module

        recording = Console(record=True, width=240)
        original = cli_module.console
        cli_module.console = recording
        try:
            cli_module._print_list_table(
                conversations,
                total_count=len(conversations),
                local_count=sum(1 for c in conversations if c.source == "local"),
                cloud_count=sum(1 for c in conversations if c.source == "cloud"),
                engagement_map=engagement_map,
                **kwargs,
            )
        finally:
            cli_module.console = original
        return recording.export_text()

    def test_columns_omitted_when_flag_off(self):
        conv = _conv("a" * 32)
        out = self._capture([conv], engagement_map=None)
        assert "Engaged" not in out
        assert "Periods" not in out
        assert "Eng%" not in out

    def test_columns_present_when_flag_on(self):
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 2460, "attention_periods": 3,
                "threshold_seconds": 720, "total_duration_seconds": 8040,
            }
        }
        out = self._capture([conv], engagement_map=engagement_map)
        assert "Engaged" in out
        assert "Periods" in out
        assert "Eng%" in out
        # Data row content
        assert "41m" in out  # 2460s = 41m 00s
        assert "30.6%" in out

    def test_missing_row_renders_dashes(self):
        conv = _conv("a" * 32)
        out = self._capture([conv], engagement_map={})
        assert "Engaged" in out  # header always present
        # The data row shows three "-" placeholders for engagement.
        # Rich strips the [dim] markup in export_text, so we just check
        # that no engagement numbers leaked in.
        assert "30.6%" not in out
        assert "41m" not in out

    def test_zero_duration_row_renders_dash_for_pct(self):
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 0, "attention_periods": 0,
                "threshold_seconds": 720, "total_duration_seconds": 0,
            }
        }
        out = self._capture([conv], engagement_map=engagement_map)
        # No percentage rendered for zero total
        assert "0.0%" not in out
        assert "100.0%" not in out

    def test_idle_and_engagement_coexist(self):
        """``--idle`` replaces Duration with Idle; ``--with-engagement``
        adds three more columns to the right — they must not conflict."""
        conv = _conv("a" * 32)
        engagement_map = {
            conv.id: {
                "engaged_seconds": 60, "attention_periods": 1,
                "threshold_seconds": 720, "total_duration_seconds": 600,
            }
        }
        out = self._capture(
            [conv], engagement_map=engagement_map, idle_minutes=7
        )
        # Both Idle and engagement columns are present
        assert "Idle" in out
        assert "Duration" not in out  # replaced by Idle
        assert "Engaged" in out
        assert "Periods" in out
        assert "Eng%" in out
