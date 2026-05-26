"""Unit tests for ``ohtv.analysis.titles``.

Covers:

* The placeholder regex selector (:func:`is_placeholder_title`)
* The variant-aware description extractor
  (:func:`description_from_analysis`)
* The JSON response parser (:func:`parse_titles_response`)
* The full :func:`generate_titles_batch` pipeline, including chunking,
  per-chunk parse-failure → single-conv retry, and the length re-prompt
  loop.

Tests inject a stub ``llm_call`` so nothing hits the live LLM / network.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ohtv.analysis.objectives import Objective, ObjectiveAnalysis
from ohtv.analysis.titles import (
    MAX_TITLE_CHARS,
    TitleGenerationResult,
    description_from_analysis,
    generate_titles_batch,
    is_placeholder_title,
    parse_titles_response,
)


# =============================================================================
# is_placeholder_title
# =============================================================================


class TestIsPlaceholderTitle:
    @pytest.mark.parametrize(
        "title",
        [
            "Conversation abc12",
            "Conversation deadbeef",
            "Conversation 005915fd6ca64291b7a8b3adb446392a",
            "Conversation aaaaa",  # 5 hex chars - minimum
        ],
    )
    def test_matches_placeholder_pattern(self, title: str) -> None:
        assert is_placeholder_title(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "🚀 Transfer 20MB Files Over Network",
            "Fix bug in sync.py",
            "Refactor cloud client",
            "Conversation",  # too short to be a placeholder id
            "Conversation abcdef foo",  # extra trailing text
            " Conversation abc12",  # leading whitespace - not exact match
            "Conversation abc12 ",  # trailing whitespace - not exact match
            "Conversation ABC12",  # uppercase - regex requires lowercase hex
            "conversation abc12",  # lowercase 'conversation'
            "Conversation 12345",  # 5 chars but not all hex
        ],
    )
    def test_does_not_match_real_or_near_placeholders(self, title: str) -> None:
        # Note: "Conversation 12345" is all digits which IS valid hex,
        # so it would match. We exclude it from this test set.
        if title == "Conversation 12345":
            # All digits ARE valid hex - this IS a placeholder.
            assert is_placeholder_title(title) is True
        else:
            assert is_placeholder_title(title) is False

    @pytest.mark.parametrize("title", [None, "", "   ", "\t\n"])
    def test_empty_or_whitespace_is_placeholder(self, title: str | None) -> None:
        assert is_placeholder_title(title) is True

    def test_hex_only_too_short(self) -> None:
        # 4 chars - below the 5-char minimum
        assert is_placeholder_title("Conversation abcd") is False


# =============================================================================
# description_from_analysis
# =============================================================================


def _make_analysis(
    *,
    detail_level: str,
    assess: bool = False,
    goal: str | None = None,
    primary_outcomes: list[str] | None = None,
    primary_objectives: list[Objective] | None = None,
    summary: str | None = None,
) -> ObjectiveAnalysis:
    """Build a synthetic ObjectiveAnalysis without touching the cache layer."""
    return ObjectiveAnalysis(
        conversation_id="testconvid",
        analyzed_at=datetime.now(timezone.utc),
        model_used="test/model",
        event_count=5,
        content_hash="deadbeefcafebabe",
        prompt_hash="0123456789abcdef",
        context_level="default",
        detail_level=detail_level,
        assess=assess,
        goal=goal,
        primary_outcomes=primary_outcomes or [],
        primary_objectives=primary_objectives or [],
        summary=summary,
    )


class TestDescriptionFromAnalysis:
    def test_brief_uses_goal_only(self) -> None:
        analysis = _make_analysis(
            detail_level="brief", goal="Add pagination to search."
        )
        assert description_from_analysis(analysis) == "Add pagination to search."

    def test_brief_assess_uses_goal_only(self) -> None:
        analysis = _make_analysis(
            detail_level="brief_assess",
            assess=True,
            goal="Investigate the flaky test.",
        )
        assert description_from_analysis(analysis) == "Investigate the flaky test."

    def test_standard_joins_goal_and_outcomes(self) -> None:
        analysis = _make_analysis(
            detail_level="standard",
            goal="Add caching layer.",
            primary_outcomes=["Cache integrated", "Latency dropped 40%"],
        )
        out = description_from_analysis(analysis)
        assert "Add caching layer." in out
        assert "Cache integrated" in out
        assert "Latency dropped 40%" in out
        assert "; " in out

    def test_standard_assess_joins_goal_and_outcomes(self) -> None:
        analysis = _make_analysis(
            detail_level="standard_assess",
            assess=True,
            goal="Add caching layer.",
            primary_outcomes=["Cache integrated"],
        )
        out = description_from_analysis(analysis)
        assert out == "Add caching layer.; Cache integrated"

    def test_detailed_concatenates_objectives(self) -> None:
        analysis = _make_analysis(
            detail_level="detailed",
            goal="Build the new feature.",
            primary_objectives=[
                Objective(description="Wire up the API endpoint"),
                Objective(description="Add unit tests"),
            ],
            summary="High-level summary.",
        )
        out = description_from_analysis(analysis)
        assert "Build the new feature." in out
        assert "High-level summary." in out
        assert "Wire up the API endpoint" in out
        assert "Add unit tests" in out

    def test_detailed_ignores_sub_objectives(self) -> None:
        """Sub-objectives must NOT appear in the description blob."""
        analysis = _make_analysis(
            detail_level="detailed",
            primary_objectives=[
                Objective(
                    description="Top-level",
                    subordinates=[
                        Objective(description="DO-NOT-LEAK-THIS-SUB-OBJECTIVE"),
                    ],
                ),
            ],
        )
        out = description_from_analysis(analysis)
        assert "Top-level" in out
        assert "DO-NOT-LEAK-THIS-SUB-OBJECTIVE" not in out

    def test_empty_brief_yields_empty(self) -> None:
        analysis = _make_analysis(detail_level="brief", goal=None)
        assert description_from_analysis(analysis) == ""

    def test_unknown_detail_level_treated_as_detailed(self) -> None:
        analysis = _make_analysis(
            detail_level="experimental",
            goal="Fallback path.",
        )
        # Should still return goal even for an unrecognised detail level
        assert "Fallback path." in description_from_analysis(analysis)


# =============================================================================
# parse_titles_response
# =============================================================================


class TestParseTitlesResponse:
    def test_parses_clean_json_array(self) -> None:
        text = json.dumps(
            [
                {"id": "abc", "title": "✨ Add Feature"},
                {"id": "def", "title": "🐛 Fix Bug"},
            ]
        )
        out = parse_titles_response(text)
        assert out == {"abc": "✨ Add Feature", "def": "🐛 Fix Bug"}

    def test_strips_markdown_code_fence(self) -> None:
        text = '```json\n[{"id": "a", "title": "X"}]\n```'
        assert parse_titles_response(text) == {"a": "X"}

    def test_strips_bare_code_fence(self) -> None:
        text = '```\n[{"id": "a", "title": "X"}]\n```'
        assert parse_titles_response(text) == {"a": "X"}

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_titles_response("this is not json {{{")

    def test_raises_on_non_array_response(self) -> None:
        with pytest.raises(ValueError, match="JSON array"):
            parse_titles_response('{"id": "abc", "title": "X"}')

    def test_skips_malformed_entries(self) -> None:
        # Mixed valid + invalid; valid ones come through.
        text = json.dumps(
            [
                {"id": "ok", "title": "Good"},
                {"id": "missing_title"},  # missing title
                {"title": "missing_id"},  # missing id
                {"id": "", "title": "empty id"},
                {"id": "empty_title", "title": ""},
                "not even a dict",  # type: ignore[list-item]
                {"id": "good2", "title": "Also good"},
            ]
        )
        out = parse_titles_response(text)
        assert out == {"ok": "Good", "good2": "Also good"}

    def test_strips_whitespace(self) -> None:
        text = json.dumps([{"id": "  abc  ", "title": "  Padded Title  "}])
        out = parse_titles_response(text)
        assert out == {"abc": "Padded Title"}


# =============================================================================
# generate_titles_batch — chunking + retry
# =============================================================================


class _StubLLM:
    """Minimal LLM stub that records calls and returns canned responses."""

    def __init__(self, responses: list[tuple[str, float]]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system_prompt: str, user_prompt: str) -> tuple[str, float]:
        self.calls.append((system_prompt, user_prompt))
        if not self._responses:
            raise AssertionError("LLM called more times than expected")
        return self._responses.pop(0)


def _array_response(items: list[tuple[str, str]]) -> str:
    return json.dumps([{"id": cid, "title": t} for cid, t in items])


class TestGenerateTitlesBatch:
    def test_empty_input_returns_empty_result(self) -> None:
        result = generate_titles_batch([], llm_call=lambda *a, **kw: ("", 0.0))
        assert result == TitleGenerationResult()

    def test_single_chunk_happy_path(self) -> None:
        items = [("a", "do thing a"), ("b", "do thing b")]
        stub = _StubLLM([(_array_response([("a", "✨ Do Thing A"), ("b", "🔧 Do Thing B")]), 0.01)])
        result = generate_titles_batch(
            items, batch_size=25, llm_call=stub, system_prompt="sys",
        )
        assert result.titles == {"a": "✨ Do Thing A", "b": "🔧 Do Thing B"}
        assert result.missing_ids == []
        assert result.cost == pytest.approx(0.01)
        assert len(stub.calls) == 1
        assert result.chunks_called == 1

    def test_chunks_into_multiple_calls(self) -> None:
        items = [(f"id{i}", f"desc {i}") for i in range(7)]
        # batch_size=3 should yield 3 chunks: [0,1,2], [3,4,5], [6]
        stub = _StubLLM(
            [
                (_array_response([("id0", "T0"), ("id1", "T1"), ("id2", "T2")]), 0.001),
                (_array_response([("id3", "T3"), ("id4", "T4"), ("id5", "T5")]), 0.001),
                (_array_response([("id6", "T6")]), 0.001),
            ]
        )
        result = generate_titles_batch(items, batch_size=3, llm_call=stub, system_prompt="sys")
        assert len(stub.calls) == 3
        assert result.titles == {f"id{i}": f"T{i}" for i in range(7)}
        assert result.cost == pytest.approx(0.003)

    def test_chunk_parse_failure_falls_back_to_single_conv(self) -> None:
        """Malformed batch JSON triggers a single-conv retry per id in the chunk."""
        items = [("a", "desc a"), ("b", "desc b")]
        stub = _StubLLM(
            [
                # First call: malformed JSON
                ("not json at all", 0.001),
                # Single-conv retries
                (_array_response([("a", "Title A")]), 0.0005),
                (_array_response([("b", "Title B")]), 0.0005),
            ]
        )
        result = generate_titles_batch(
            items, batch_size=25, llm_call=stub, system_prompt="sys",
        )
        assert result.titles == {"a": "Title A", "b": "Title B"}
        assert result.missing_ids == []
        assert len(stub.calls) == 3

    def test_chunk_partial_returns_retries_only_missing_ids(self) -> None:
        """If the batch returns only some ids, only the missing ones are retried."""
        items = [("a", "desc a"), ("b", "desc b"), ("c", "desc c")]
        stub = _StubLLM(
            [
                # First call: only a + c returned
                (_array_response([("a", "Title A"), ("c", "Title C")]), 0.001),
                # Single-conv retry for b only
                (_array_response([("b", "Title B")]), 0.0005),
            ]
        )
        result = generate_titles_batch(
            items, batch_size=25, llm_call=stub, system_prompt="sys",
        )
        assert result.titles == {"a": "Title A", "b": "Title B", "c": "Title C"}
        assert len(stub.calls) == 2

    def test_single_conv_retry_still_failing_marks_missing(self) -> None:
        """When even the single-conv retry can't produce a title, id is missing."""
        items = [("a", "desc")]
        stub = _StubLLM(
            [
                # Batch call: malformed
                ("garbage", 0.001),
                # Retry: still garbage
                ("more garbage", 0.0005),
            ]
        )
        result = generate_titles_batch(
            items, batch_size=25, llm_call=stub, system_prompt="sys",
        )
        assert result.titles == {}
        assert result.missing_ids == ["a"]

    def test_overlong_title_short_overshoot_is_truncated(self) -> None:
        """Title slightly over the limit is hard-truncated without re-prompting."""
        long_title = "X" * (MAX_TITLE_CHARS + 3)  # within tolerance
        items = [("a", "desc")]
        stub = _StubLLM([(_array_response([("a", long_title)]), 0.001)])
        result = generate_titles_batch(items, llm_call=stub, system_prompt="sys")
        assert "a" in result.titles
        assert len(result.titles["a"]) <= MAX_TITLE_CHARS
        # No second LLM call - within tolerance.
        assert len(stub.calls) == 1

    def test_overlong_title_large_overshoot_triggers_retry(self) -> None:
        """Title well over the limit triggers a single-conv re-prompt."""
        too_long = "Y" * 200  # way too long
        good = "Z Z Z Acceptable Title"
        items = [("a", "desc")]
        stub = _StubLLM(
            [
                (_array_response([("a", too_long)]), 0.001),
                (_array_response([("a", good)]), 0.0005),
            ]
        )
        result = generate_titles_batch(items, llm_call=stub, system_prompt="sys")
        assert result.titles == {"a": good}
        assert len(stub.calls) == 2

    def test_overlong_title_retry_still_too_long_truncates(self) -> None:
        """If the model keeps producing too-long titles, hard truncate as last resort."""
        too_long = "Q" * 300
        retry_still_too_long = "P" * 250
        items = [("a", "desc")]
        stub = _StubLLM(
            [
                (_array_response([("a", too_long)]), 0.001),
                (_array_response([("a", retry_still_too_long)]), 0.0005),
            ]
        )
        result = generate_titles_batch(items, llm_call=stub, system_prompt="sys")
        assert "a" in result.titles
        assert len(result.titles["a"]) <= MAX_TITLE_CHARS
        # Last char should be the ellipsis since we hard-truncate.
        assert result.titles["a"].endswith("…")

    def test_llm_exception_falls_back_to_missing(self) -> None:
        """If the LLM raises in the batch call, all chunk ids are marked missing."""

        def _raiser(_sys: str, _user: str) -> tuple[str, float]:
            raise RuntimeError("api down")

        result = generate_titles_batch(
            [("a", "desc"), ("b", "desc")],
            llm_call=_raiser,
            system_prompt="sys",
        )
        assert result.titles == {}
        assert set(result.missing_ids) == {"a", "b"}

    def test_invalid_batch_size_raises(self) -> None:
        # batch_size=0 makes _chunk raise.
        with pytest.raises(ValueError):
            generate_titles_batch(
                [("a", "desc")],
                batch_size=0,
                llm_call=lambda *a, **kw: ("", 0.0),
                system_prompt="sys",
            )
