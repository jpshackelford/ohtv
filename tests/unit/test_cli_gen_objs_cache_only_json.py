"""Tests for ``ohtv gen objs --cache-only -F json`` cache-miss output (Issue #161).

When the cache has no analysis for a conversation and ``--cache-only`` is
set, the JSON exporter MUST emit ``goal: null`` (not the human-readable
``"(no goal identified)"`` placeholder string). This is the contract the
cookbook prompt and ``docs/guides/search-and-ask.md`` both promise, and
which the in-process ``ohtv ask --agent`` runner relies on to decide
whether to skip uncached conversations.

The table / markdown formatters still emit the placeholder — those are
human-facing surfaces.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ohtv.cli import main


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


def _build_cache_miss_analysis_result():
    """Construct a real ``AnalysisResult`` representing a cache-only cache miss.

    Mirrors what :func:`ohtv.analysis.objectives.analyze_objectives` returns
    when invoked with ``cache_only=True`` and the cache has no entry:
    ``goal=None``, empty list fields, ``from_cache=False``.
    """
    from ohtv.analysis.objectives import AnalysisResult, ObjectiveAnalysis

    analysis = ObjectiveAnalysis(
        conversation_id="test123",
        context_level="outcome",
        detail_level="brief",
        goal=None,
        primary_outcomes=[],
        secondary_outcomes=[],
        primary_objectives=[],
        summary=None,
        analyzed_at=datetime(2026, 5, 30, 15, 0, tzinfo=timezone.utc),
        model_used="",
        event_count=10,
        content_hash="",
    )
    return AnalysisResult(analysis=analysis, cost=0.0, from_cache=False)


def _build_cache_hit_analysis_result(goal: str):
    """Construct a real ``AnalysisResult`` representing a cache hit with a goal."""
    from ohtv.analysis.objectives import AnalysisResult, ObjectiveAnalysis

    analysis = ObjectiveAnalysis(
        conversation_id="test123",
        context_level="outcome",
        detail_level="brief",
        goal=goal,
        analyzed_at=datetime(2026, 5, 30, 15, 0, tzinfo=timezone.utc),
        model_used="test-model",
        event_count=10,
        content_hash="abc123",
    )
    return AnalysisResult(analysis=analysis, cost=0.0, from_cache=True)


def _patch_batch_environment(conversations: list, analysis_result):
    """Bundle the patches needed to drive ``_run_batch_objectives_analysis`` end-to-end."""
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
    raise AssertionError(f"Unbalanced brackets in:\n{text}")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestGenObjsCacheOnlyJsonGoalNull:
    """The agent contract: cache-miss in JSON output is ``goal: null``."""

    def test_cache_miss_json_emits_null_goal(self, runner, tmp_path, monkeypatch):
        """The load-bearing case: cookbook prompt + docs promise this."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_cache_miss_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "--cache-only", "-F", "json"]
            )

        assert result.exit_code == 0, result.output
        items = json.loads(_extract_json_array(result.output))
        assert len(items) == 1
        assert items[0]["goal"] is None, (
            "Cache-only cache miss must emit JSON null for goal — the agent "
            "uses this as its 'no cached analysis' signal. Got: "
            f"{items[0]['goal']!r}"
        )
        # Guard against any sibling field regressing back to a placeholder
        # string ("(no goal identified)" or similar).
        assert items[0]["goal"] != "(no goal identified)"

    def test_cache_hit_json_preserves_real_goal(self, runner, tmp_path, monkeypatch):
        """Regression guard: a real cached goal still passes through verbatim."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "b" * 32
        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_cache_hit_analysis_result(goal="Investigate the bug")

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "--cache-only", "-F", "json"]
            )

        assert result.exit_code == 0, result.output
        items = json.loads(_extract_json_array(result.output))
        assert len(items) == 1
        assert items[0]["goal"] == "Investigate the bug"

    def test_cache_miss_table_still_shows_placeholder(
        self, runner, tmp_path, monkeypatch
    ):
        """The placeholder string is the *human-facing* surface (table/markdown)."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "c" * 32
        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_cache_miss_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "--cache-only", "-F", "table"]
            )

        assert result.exit_code == 0, result.output
        # Rich may wrap long strings; check for the distinctive fragment.
        assert "(no goal identified)" in result.output

    def test_cache_miss_markdown_still_shows_placeholder(
        self, runner, tmp_path, monkeypatch
    ):
        """Markdown is human-facing too — placeholder still rendered."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "d" * 32
        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_cache_miss_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "--cache-only", "-F", "markdown"]
            )

        assert result.exit_code == 0, result.output
        assert "(no goal identified)" in result.output
