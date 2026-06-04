"""Tests for ``ohtv gen objs --with-engagement`` (Issue #168).

Covers the display-layer surface added to ``ohtv gen objs``: the new
flag, the ID-based batch DB loader, the JSON field-merging helper, and
the integration of all three through both the multi-conversation JSON
emitter and the single-conversation JSON emitter.

All DB-touching tests use a real temporary SQLite DB (via the
``OHTV_DIR`` env var) — matching the no-mocks policy in AGENTS.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ohtv.cli import (
    _engagement_json_fields,
    _load_engagement_for_ids,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_engagement_row(
    tmp_path: Path,
    conv_id: str,
    *,
    engaged_seconds: int,
    attention_periods: int,
    threshold_seconds: int = 720,
    total_duration_seconds: int | None = 1800,
) -> None:
    """Insert a conversation + engagement row into the temp DB.

    Mirrors :func:`tests.unit.test_cli_list_engagement._seed_engagement_row`
    so the two test files exercise the same schema.
    """
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


def _mock_conversation_info(conv_id: str, *, source: str = "cloud"):
    """Build a MagicMock that quacks like a ConversationInfo for the batch path."""
    mock = MagicMock()
    mock.id = conv_id
    mock.short_id = conv_id[:7]
    mock.lookup_id = conv_id
    mock.title = f"Test {conv_id[:7]}"
    mock.source = source
    mock.created_at = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
    mock.updated_at = datetime(2026, 5, 30, 14, 30, tzinfo=timezone.utc)
    mock.event_count = 10
    mock.duration = timedelta(minutes=30)
    return mock


def _build_objective_analysis_result(goal: str = "Test goal"):
    """Construct a real ``AnalysisResult`` (no mock) for the analysis path."""
    from ohtv.analysis.objectives import AnalysisResult, ObjectiveAnalysis

    analysis = ObjectiveAnalysis(
        conversation_id="test123",
        context_level="minimal",
        detail_level="brief",
        goal=goal,
        analyzed_at=datetime(2026, 5, 30, 15, 0, tzinfo=timezone.utc),
        model_used="test-model",
        event_count=5,
        content_hash="abc123",
    )
    return AnalysisResult(analysis=analysis, cost=0.0, from_cache=True)


# ---------------------------------------------------------------------------
# _engagement_json_fields — pure helper
# ---------------------------------------------------------------------------


class TestEngagementJsonFields:
    def test_none_row_emits_five_nulls(self):
        out = _engagement_json_fields(None)
        assert out == {
            "engaged_seconds": None,
            "attention_periods": None,
            "engagement_threshold_seconds": None,
            "total_duration_seconds": None,
            "engagement_ratio": None,
        }

    def test_present_row_emits_all_five_fields(self):
        row = {
            "engaged_seconds": 2460,
            "attention_periods": 3,
            "threshold_seconds": 720,
            "total_duration_seconds": 8040,
        }
        out = _engagement_json_fields(row)
        assert out["engaged_seconds"] == 2460
        assert out["attention_periods"] == 3
        assert out["engagement_threshold_seconds"] == 720
        assert out["total_duration_seconds"] == 8040
        assert out["engagement_ratio"] == 0.306

    def test_zero_total_yields_null_ratio(self):
        row = {
            "engaged_seconds": 0,
            "attention_periods": 0,
            "threshold_seconds": 720,
            "total_duration_seconds": 0,
        }
        out = _engagement_json_fields(row)
        # Raw fields preserved; ratio is null because total is 0.
        assert out["engaged_seconds"] == 0
        assert out["total_duration_seconds"] == 0
        assert out["engagement_ratio"] is None

    def test_missing_total_yields_null_ratio(self):
        row = {
            "engaged_seconds": 100,
            "attention_periods": 1,
            "threshold_seconds": 720,
            "total_duration_seconds": None,
        }
        out = _engagement_json_fields(row)
        assert out["engagement_ratio"] is None
        # Other fields preserved as raw values.
        assert out["engaged_seconds"] == 100
        assert out["total_duration_seconds"] is None

    def test_schema_keys_are_constant(self):
        """Both None and present rows must expose the same five keys."""
        none_keys = set(_engagement_json_fields(None).keys())
        row_keys = set(_engagement_json_fields({
            "engaged_seconds": 1, "attention_periods": 1,
            "threshold_seconds": 720, "total_duration_seconds": 10,
        }).keys())
        assert none_keys == row_keys
        assert none_keys == {
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        }

    def test_engaged_zero_total_positive_yields_zero_ratio(self):
        row = {
            "engaged_seconds": 0,
            "attention_periods": 0,
            "threshold_seconds": 720,
            "total_duration_seconds": 100,
        }
        out = _engagement_json_fields(row)
        assert out["engagement_ratio"] == 0.0


# ---------------------------------------------------------------------------
# _load_engagement_for_ids — DB batch loader
# ---------------------------------------------------------------------------


class TestLoadEngagementForIds:
    def test_empty_input_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        assert _load_engagement_for_ids([]) == {}

    def test_db_missing_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        # No DB initialized — should silently return empty.
        assert _load_engagement_for_ids(["a" * 32]) == {}

    def test_present_row_is_returned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )
        result = _load_engagement_for_ids([conv_id])
        assert conv_id in result
        assert result[conv_id]["engaged_seconds"] == 2460
        assert result[conv_id]["attention_periods"] == 3
        assert result[conv_id]["total_duration_seconds"] == 8040
        assert result[conv_id]["threshold_seconds"] == 720

    def test_missing_ids_are_absent_from_result(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        seeded = "a" * 32
        missing = "b" * 32
        _seed_engagement_row(
            tmp_path, seeded, engaged_seconds=60,
            attention_periods=1, total_duration_seconds=120,
        )
        result = _load_engagement_for_ids([seeded, missing])
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
        # Caller passes dashed id; result is keyed by the caller's id form.
        result = _load_engagement_for_ids([dashed])
        assert dashed in result
        assert result[dashed]["engaged_seconds"] == 120

    def test_batch_chunking_above_900_ids(self, tmp_path, monkeypatch):
        """The loader must chunk to stay under SQLite's parameter ceiling."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        ids: list[str] = []
        for i in range(1100):
            conv_id = f"{i:032x}"
            _seed_engagement_row(
                tmp_path, conv_id, engaged_seconds=i,
                attention_periods=1, total_duration_seconds=max(i, 1),
            )
            ids.append(conv_id)
        result = _load_engagement_for_ids(ids)
        assert len(result) == 1100
        # Spot-check first/last.
        assert result[ids[0]]["engaged_seconds"] == 0
        assert result[ids[-1]]["engaged_seconds"] == 1099

    def test_chunk_query_count(self, tmp_path, monkeypatch):
        """1100 IDs ⇒ exactly two SELECTs (900 + 200).

        Wraps ``get_ready_connection`` with a proxy that intercepts
        ``execute`` calls so we can count the engagement queries. The
        real DB still backs the connection — no mocks in the data path.
        """
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        ids: list[str] = []
        for i in range(1100):
            conv_id = f"{i:032x}"
            _seed_engagement_row(
                tmp_path, conv_id, engaged_seconds=i,
                attention_periods=1, total_duration_seconds=max(i, 1),
            )
            ids.append(conv_id)

        from contextlib import contextmanager

        import ohtv.db as ohtv_db

        real_get = ohtv_db.get_ready_connection
        select_count = {"n": 0}

        class _CountingConn:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args, **kwargs):
                if (
                    "FROM conversation_engagement" in sql
                    and "WHERE conversation_id IN" in sql
                ):
                    select_count["n"] += 1
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        @contextmanager
        def wrapping(show_progress=False):
            with real_get(show_progress=show_progress) as conn:
                yield _CountingConn(conn)

        monkeypatch.setattr(ohtv_db, "get_ready_connection", wrapping)
        _load_engagement_for_ids(ids)

        # 1100 IDs at BATCH_SIZE=900 ⇒ ceil(1100/900) = 2 queries.
        assert select_count["n"] == 2


# ---------------------------------------------------------------------------
# CLI — single-conversation JSON mode (gen objs <id> --json --with-engagement)
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestSingleConvJsonWithEngagement:
    def test_flag_off_emits_only_analysis_fields(self, runner, tmp_path, monkeypatch):
        """Regression guard: no engagement keys when flag absent."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )
        analysis_result = _build_objective_analysis_result()

        with patch("ohtv.cli._find_conversation_dir", return_value=(tmp_path, None)), \
             patch("ohtv.cli._get_conversation_info", return_value=(conv_id, "Test")), \
             patch("ohtv.cli.Config"), \
             patch("ohtv.analysis.analyze_objectives", return_value=analysis_result), \
             patch("ohtv.analysis.get_cached_analysis", return_value=analysis_result.analysis), \
             patch("ohtv.analysis.load_events", return_value=[]):
            result = runner.invoke(main, ["gen", "objs", conv_id, "--json"])

        assert result.exit_code == 0, result.output
        # Find the JSON object in output (rich prints may decorate).
        payload = json.loads(_extract_json_object(result.output))
        # Analysis fields present.
        assert payload["goal"] == "Test goal"
        # No engagement keys.
        for k in (
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        ):
            assert k not in payload

    def test_flag_on_present_row_merges_five_fields(self, runner, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )
        analysis_result = _build_objective_analysis_result()

        with patch("ohtv.cli._find_conversation_dir", return_value=(tmp_path, None)), \
             patch("ohtv.cli._get_conversation_info", return_value=(conv_id, "Test")), \
             patch("ohtv.cli.Config"), \
             patch("ohtv.analysis.analyze_objectives", return_value=analysis_result), \
             patch("ohtv.analysis.get_cached_analysis", return_value=analysis_result.analysis), \
             patch("ohtv.analysis.load_events", return_value=[]):
            result = runner.invoke(
                main, ["gen", "objs", conv_id, "--json", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(_extract_json_object(result.output))
        # Analysis fields untouched.
        assert payload["goal"] == "Test goal"
        assert payload["context_level"] == "minimal"
        assert payload["detail_level"] == "brief"
        # Engagement fields present at top level.
        assert payload["engaged_seconds"] == 2460
        assert payload["attention_periods"] == 3
        assert payload["engagement_threshold_seconds"] == 720
        assert payload["total_duration_seconds"] == 8040
        assert payload["engagement_ratio"] == 0.306

    def test_flag_on_missing_row_emits_nulls(self, runner, tmp_path, monkeypatch):
        """Engagement-stage hasn't run ⇒ five nulls, analysis untouched."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        # No _seed_engagement_row call ⇒ row missing from DB.
        # Force DB to exist (empty) so the loader can do its lookup.
        from ohtv.db import get_ready_connection
        with get_ready_connection(show_progress=False):
            pass

        analysis_result = _build_objective_analysis_result()

        with patch("ohtv.cli._find_conversation_dir", return_value=(tmp_path, None)), \
             patch("ohtv.cli._get_conversation_info", return_value=(conv_id, "Test")), \
             patch("ohtv.cli.Config"), \
             patch("ohtv.analysis.analyze_objectives", return_value=analysis_result), \
             patch("ohtv.analysis.get_cached_analysis", return_value=analysis_result.analysis), \
             patch("ohtv.analysis.load_events", return_value=[]):
            result = runner.invoke(
                main, ["gen", "objs", conv_id, "--json", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(_extract_json_object(result.output))
        assert payload["goal"] == "Test goal"
        # All five engagement keys present and null.
        for k in (
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        ):
            assert k in payload
            assert payload[k] is None


# ---------------------------------------------------------------------------
# CLI — multi-conversation JSON mode (gen objs ... -F json --with-engagement)
# ---------------------------------------------------------------------------


def _patch_batch_environment(conversations: list, analysis_result):
    """Bundle the patches needed to drive ``_run_batch_objectives_analysis`` end-to-end.

    Returns a list of context managers that the caller composes with
    ``contextlib.ExitStack`` / nested ``with``.
    """
    filter_result = MagicMock()
    filter_result.conversations = conversations
    filter_result.show_all = False

    return [
        patch("ohtv.cli.Config"),
        patch("ohtv.cli._apply_conversation_filters", return_value=filter_result),
        patch("ohtv.analysis.analyze_objectives", return_value=analysis_result),
        patch("ohtv.cli._find_conversation_dir", return_value=(Path("/tmp/conv"), None)),
        patch("ohtv.cli._count_uncached_conversations_fast", return_value=0),
        patch("ohtv.cli._get_conversation_labels", return_value={}),
        patch("ohtv.cli._get_conversation_outputs", return_value=None),
    ]


class TestMultiConvJsonWithEngagement:
    def test_flag_off_omits_engagement_keys(self, runner, tmp_path, monkeypatch):
        """Regression guard: no engagement keys when flag absent."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

        import contextlib
        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(main, ["gen", "objs", "-F", "json"])

        assert result.exit_code == 0, result.output
        items = json.loads(_extract_json_array(result.output))
        assert len(items) == 1
        item = items[0]
        for k in (
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        ):
            assert k not in item

    def test_flag_on_present_row_emits_five_fields(self, runner, tmp_path, monkeypatch):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

        import contextlib
        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "-F", "json", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        items = json.loads(_extract_json_array(result.output))
        item = items[0]
        # Existing fields preserved.
        assert item["id"] == conv_id
        assert "goal" in item
        # Engagement fields appended.
        assert item["engaged_seconds"] == 2460
        assert item["attention_periods"] == 3
        assert item["engagement_threshold_seconds"] == 720
        assert item["total_duration_seconds"] == 8040
        assert item["engagement_ratio"] == 0.306

    def test_flag_on_mixed_present_and_missing_rows(
        self, runner, tmp_path, monkeypatch
    ):
        """Schema must be stable across rows — present and missing both have five fields."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        present_id = "a" * 32
        missing_id = "b" * 32
        _seed_engagement_row(
            tmp_path, present_id, engaged_seconds=100,
            attention_periods=1, total_duration_seconds=1000,
        )

        conversations = [
            _mock_conversation_info(present_id),
            _mock_conversation_info(missing_id),
        ]
        analysis_result = _build_objective_analysis_result()

        import contextlib
        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "-F", "json", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        items = json.loads(_extract_json_array(result.output))
        assert len(items) == 2
        # Both items have identical key sets.
        assert set(items[0].keys()) == set(items[1].keys())
        # Find the present and missing items by id.
        present_item = next(i for i in items if i["id"] == present_id)
        missing_item = next(i for i in items if i["id"] == missing_id)
        # Present row.
        assert present_item["engaged_seconds"] == 100
        assert present_item["engagement_ratio"] == 0.1
        # Missing row.
        for k in (
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        ):
            assert missing_item[k] is None

    def test_flag_on_table_format_is_noop(self, runner, tmp_path, monkeypatch):
        """``--with-engagement -F table`` must produce identical output to plain ``-F table``."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

        import contextlib

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            without = runner.invoke(main, ["gen", "objs", "-F", "table"])

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            with_flag = runner.invoke(
                main, ["gen", "objs", "-F", "table", "--with-engagement"]
            )

        assert without.exit_code == 0
        assert with_flag.exit_code == 0
        # Engagement keys must NOT appear in either output.
        for k in (
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        ):
            assert k not in without.output
            assert k not in with_flag.output

    def test_flag_on_markdown_format_is_noop(self, runner, tmp_path, monkeypatch):
        """``--with-engagement -F markdown`` must not inject engagement fields."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

        import contextlib
        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            with_flag = runner.invoke(
                main, ["gen", "objs", "-F", "markdown", "--with-engagement"]
            )

        assert with_flag.exit_code == 0
        # Markdown output must not carry any of the JSON-specific keys.
        for k in (
            "engaged_seconds",
            "attention_periods",
            "engagement_threshold_seconds",
            "total_duration_seconds",
            "engagement_ratio",
        ):
            assert k not in with_flag.output


# ---------------------------------------------------------------------------
# CLI help — surface check
# ---------------------------------------------------------------------------


class TestHelpSurface:
    def test_with_engagement_flag_is_documented(self, runner):
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert result.exit_code == 0
        assert "--with-engagement" in result.output


# ---------------------------------------------------------------------------
# Output-extraction utilities
# ---------------------------------------------------------------------------


def _extract_json_object(text: str) -> str:
    """Pluck the outermost ``{...}`` from rich-decorated output."""
    start = text.find("{")
    if start < 0:
        raise AssertionError(f"No JSON object in output:\n{text}")
    # Walk to the matching closing brace, honoring nested structures.
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"Unbalanced JSON object in output:\n{text}")


def _extract_json_array(text: str) -> str:
    """Pluck the outermost ``[...]`` from CLI output."""
    start = text.find("[")
    if start < 0:
        raise AssertionError(f"No JSON array in output:\n{text}")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"Unbalanced JSON array in output:\n{text}")
