"""Tests for the 5-level context ladder and auto-promotion (Issue #149).

Covers:

- ``CONTEXT_LEVEL_ORDER`` definition and ordering invariants
- ``promote_context_level`` helper (step-one-level-at-a-time)
- ``_string_build_transcript`` adjacency: each level adds exactly one
  category of events compared to the level below
- Observation-event extraction at the highest level
- Full promotion sweep against the integration-level ``_prepare_data``
  helper to assert the loop terminates at the first level with content

These tests do NOT touch the LLM. The integration of auto-promotion with
``analyze_objectives`` is covered separately in
``tests/integration/test_gen_objs_batch.py``.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.analysis.objectives import (
    CONTEXT_LEVEL_ORDER,
    _level_at_least,
    _prepare_data,
    build_transcript,
    promote_context_level,
)
from ohtv.analysis.transcript import (
    DEFAULT_OBSERVATION_TRUNCATE,
    extract_content,
    extract_observation_content,
)


# -----------------------------------------------------------------------------
# CONTEXT_LEVEL_ORDER + promote_context_level helpers
# -----------------------------------------------------------------------------


class TestContextLevelOrder:
    def test_exactly_five_levels(self):
        assert len(CONTEXT_LEVEL_ORDER) == 5

    def test_order_is_canonical(self):
        assert CONTEXT_LEVEL_ORDER == (
            "minimal", "outcome", "dialogue", "actions", "observations"
        )


class TestPromoteContextLevel:
    @pytest.mark.parametrize(
        "current,expected",
        [
            ("minimal", "outcome"),
            ("outcome", "dialogue"),
            ("dialogue", "actions"),
            ("actions", "observations"),
        ],
    )
    def test_promotes_each_adjacent_pair(self, current, expected):
        """Every adjacent pair triggers exactly one promote step."""
        assert promote_context_level(current) == expected

    def test_returns_none_at_top(self):
        assert promote_context_level("observations") is None

    def test_unknown_level_starts_at_minimal(self):
        """Unknown levels are treated as ``minimal`` (idx 0) for safety."""
        assert promote_context_level("nonsense") == "outcome"

    def test_step_one_level_only(self):
        """Promotion must NEVER skip levels (regression guard for the
        2-step ``minimal -> default -> full`` jump from before #149)."""
        seen = []
        cur = "minimal"
        while cur is not None:
            seen.append(cur)
            cur = promote_context_level(cur)
        assert seen == list(CONTEXT_LEVEL_ORDER)


# -----------------------------------------------------------------------------
# _level_at_least
# -----------------------------------------------------------------------------


class TestLevelAtLeast:
    def test_same_level(self):
        assert _level_at_least("dialogue", "dialogue") is True

    def test_higher_includes_lower(self):
        assert _level_at_least("observations", "minimal") is True

    def test_lower_does_not_include_higher(self):
        assert _level_at_least("minimal", "observations") is False

    def test_unknown_treated_as_minimal(self):
        assert _level_at_least("bogus", "minimal") is True
        assert _level_at_least("bogus", "outcome") is False


# -----------------------------------------------------------------------------
# String slicer adjacency: each level adds exactly one event category
# -----------------------------------------------------------------------------


def _events_with_one_of_each():
    """Synthesize one event per level so we can read off level inclusion."""
    return [
        {  # belongs to: minimal+
            "source": "user",
            "kind": "MessageEvent",
            "llm_message": {"content": [{"type": "text", "text": "Hi"}]},
        },
        {  # belongs to: outcome+
            "source": "agent",
            "kind": "ActionEvent",
            "tool_name": "finish",
            "action": {"message": "Done"},
        },
        {  # belongs to: dialogue+
            "source": "agent",
            "kind": "MessageEvent",
            "llm_message": {"content": [{"type": "text", "text": "Reasoning..."}]},
        },
        {  # belongs to: actions+
            "source": "agent",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "git status"},
        },
        {  # belongs to: observations only
            "kind": "ObservationEvent",
            "observation": {
                "content": [{"type": "text", "text": "On branch main"}],
                "exit_code": 0,
            },
        },
    ]


class TestStringSlicerAdjacency:
    @pytest.mark.parametrize(
        "level,expected_count",
        [
            ("minimal", 1),       # user msg
            ("outcome", 2),       # + finish action
            ("dialogue", 3),      # + agent msg
            ("actions", 4),       # + non-finish action
            ("observations", 5),  # + observation event
        ],
    )
    def test_level_count_is_additive(self, level, expected_count):
        events = _events_with_one_of_each()
        result = build_transcript(events, context=level)
        assert len(result) == expected_count

    def test_promotion_adjacency_against_slicer(self):
        """Walking the ladder one step at a time must add at most one item
        per step (it can add zero on a level that has no matching event)."""
        events = _events_with_one_of_each()
        prev_count = 0
        for level in CONTEXT_LEVEL_ORDER:
            count = len(build_transcript(events, context=level))
            assert count >= prev_count, f"{level} dropped items vs prev"
            assert count - prev_count <= 1, (
                f"{level} added more than one category of event (got {count} "
                f"items, previous level had {prev_count})"
            )
            prev_count = count


# -----------------------------------------------------------------------------
# ObservationEvent extraction
# -----------------------------------------------------------------------------


class TestExtractObservationContent:
    def test_string_content(self):
        event = {"observation": {"content": "stdout text"}}
        assert extract_observation_content(event) == "stdout text"

    def test_list_content(self):
        event = {
            "observation": {
                "content": [
                    {"type": "text", "text": "line 1"},
                    {"type": "text", "text": "line 2"},
                ]
            }
        }
        assert extract_observation_content(event) == "line 1\nline 2"

    def test_truncation(self):
        event = {"observation": {"content": "x" * 5000}}
        result = extract_observation_content(event, max_length=100)
        assert result.endswith("... [truncated]")
        assert len(result) == 100 + len("... [truncated]")

    def test_exit_code_annotation(self):
        event = {"observation": {"content": "fail", "exit_code": 1}}
        assert extract_observation_content(event) == "(exit=1) fail"

    def test_exit_code_zero_is_included(self):
        event = {"observation": {"content": "ok", "exit_code": 0}}
        assert extract_observation_content(event) == "(exit=0) ok"

    def test_no_observation_payload(self):
        assert extract_observation_content({}) == ""

    def test_default_truncate_constant(self):
        assert DEFAULT_OBSERVATION_TRUNCATE > 0

    def test_extract_content_routes_observations(self):
        """``extract_content`` must hand ObservationEvents to the dedicated
        extractor so the per-level truncate is honoured."""
        event = {
            "kind": "ObservationEvent",
            "observation": {"content": "y" * 2000, "exit_code": 0},
        }
        result = extract_content(event, max_length=50)
        assert result.startswith("(exit=0) ")
        assert "... [truncated]" in result

    def test_observation_role_in_string_transcript(self):
        events = [
            {
                "kind": "ObservationEvent",
                "observation": {"content": "hello", "exit_code": 0},
            }
        ]
        result = build_transcript(events, context="observations")
        assert len(result) == 1
        assert result[0]["role"] == "observation"


# -----------------------------------------------------------------------------
# Full promotion sweep using _prepare_data (no LLM)
# -----------------------------------------------------------------------------


class TestPromotionSweep:
    """Simulate the auto-promotion loop in ``analyze_objectives`` without
    invoking the LLM. Verifies the loop terminates at the lowest level
    that surfaces content for the events under test.
    """

    def _walk(self, events) -> list[str]:
        """Mimic the loop body in ``analyze_objectives`` and return the
        sequence of levels visited."""
        # Patch ``load_events`` so ``_prepare_data`` sees our in-memory events
        # regardless of the conv_dir argument.
        with patch(
            "ohtv.analysis.objectives.load_events", return_value=events
        ):
            visited = []
            current = "minimal"
            while True:
                visited.append(current)
                data = _prepare_data(Path("/fake"), current)
                if data.items:
                    return visited
                nxt = promote_context_level(current)
                if nxt is None:
                    return visited
                current = nxt

    def test_minimal_with_content_does_not_promote(self):
        events = [
            {
                "source": "user",
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "hi"}]},
            },
        ]
        assert self._walk(events) == ["minimal"]

    def test_worker_with_finish_stops_at_outcome(self):
        events = [
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "finish",
                "action": {"message": "done"},
            }
        ]
        assert self._walk(events) == ["minimal", "outcome"]

    def test_worker_with_only_dialogue_msgs_stops_at_dialogue(self):
        events = [
            {
                "source": "agent",
                "kind": "MessageEvent",
                "llm_message": {"content": [{"type": "text", "text": "thinking"}]},
            }
        ]
        assert self._walk(events) == ["minimal", "outcome", "dialogue"]

    def test_worker_without_finish_stops_at_actions(self):
        events = [
            {
                "source": "agent",
                "kind": "ActionEvent",
                "tool_name": "terminal",
                "action": {"command": "git push"},
            }
        ]
        assert self._walk(events) == [
            "minimal",
            "outcome",
            "dialogue",
            "actions",
        ]

    def test_observations_only_walks_all_the_way(self):
        events = [
            {
                "kind": "ObservationEvent",
                "observation": {"content": "out", "exit_code": 0},
            }
        ]
        assert self._walk(events) == list(CONTEXT_LEVEL_ORDER)

    def test_empty_events_walks_to_top_without_content(self):
        """No event categories at all - loop runs the full ladder and gives
        up. ``analyze_objectives`` separately guards against this with the
        ``_has_action_events`` precondition."""
        assert self._walk([]) == list(CONTEXT_LEVEL_ORDER)
