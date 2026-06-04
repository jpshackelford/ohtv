"""Unit tests for the engagement filter predicates (Issue #170).

Covers :func:`ohtv.cli._validate_engagement_filter_args` and
:func:`ohtv.cli._filter_by_engagement` in isolation. The CLI-level
integration tests (``CliRunner``) live in
``test_cli_list_engagement_filter.py`` and
``test_cli_gen_objs_engagement_filter.py``.

The filter helper is intentionally pure-Python over the engagement
map returned by ``_load_engagement_for_conversations``; tests inject
a fake map via ``monkeypatch`` to avoid DB plumbing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click
import pytest

from ohtv import cli as cli_mod
from ohtv.cli import (
    _filter_by_engagement,
    _validate_engagement_filter_args,
)
from ohtv.sources.base import ConversationInfo


def _conv(conv_id: str) -> ConversationInfo:
    base = datetime(2026, 5, 30, 14, 0, tzinfo=timezone.utc)
    return ConversationInfo(
        id=conv_id,
        title=f"Conv {conv_id}",
        created_at=base,
        updated_at=base + timedelta(minutes=30),
        event_count=10,
        source="cloud",
    )


def _row(engaged: int | None, total: int | None = 1800) -> dict:
    return {
        "engaged_seconds": engaged,
        "attention_periods": 1 if engaged and engaged > 0 else 0,
        "threshold_seconds": 720,
        "total_duration_seconds": total,
    }


# ---------------------------------------------------------------------------
# _validate_engagement_filter_args
# ---------------------------------------------------------------------------


class TestValidateEngagementFilterArgs:
    def test_no_flags_is_ok(self):
        _validate_engagement_filter_args(
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )

    def test_engaged_only_is_ok(self):
        _validate_engagement_filter_args(
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )

    def test_no_engaged_only_is_ok(self):
        _validate_engagement_filter_args(
            engaged=False,
            no_engaged=True,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )

    def test_engaged_and_no_engaged_rejected(self):
        with pytest.raises(click.BadParameter, match="mutually exclusive"):
            _validate_engagement_filter_args(
                engaged=True,
                no_engaged=True,
                min_engaged_seconds=None,
                min_engagement_ratio=None,
            )

    def test_no_engaged_and_min_engaged_rejected(self):
        with pytest.raises(click.BadParameter, match="--no-engaged"):
            _validate_engagement_filter_args(
                engaged=False,
                no_engaged=True,
                min_engaged_seconds=300,
                min_engagement_ratio=None,
            )

    def test_no_engaged_and_min_engagement_ratio_rejected(self):
        with pytest.raises(click.BadParameter, match="--no-engaged"):
            _validate_engagement_filter_args(
                engaged=False,
                no_engaged=True,
                min_engaged_seconds=None,
                min_engagement_ratio=50.0,
            )

    def test_engaged_and_min_engaged_is_allowed(self):
        # AC: ``--engaged --min-engaged 5m`` is permitted — ``--engaged``
        # is silently absorbed by the threshold flag.
        _validate_engagement_filter_args(
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=300,
            min_engagement_ratio=None,
        )

    def test_engaged_and_min_engagement_ratio_is_allowed(self):
        _validate_engagement_filter_args(
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=25.0,
        )

    def test_both_thresholds_with_engaged_is_allowed(self):
        _validate_engagement_filter_args(
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=300,
            min_engagement_ratio=25.0,
        )


# ---------------------------------------------------------------------------
# _filter_by_engagement
# ---------------------------------------------------------------------------


def _patch_engagement_map(monkeypatch, mapping: dict[str, dict]) -> list[bool]:
    """Patch ``_load_engagement_for_conversations`` to return ``mapping``.

    Returns a one-element list whose only entry is ``True`` after the
    helper is called — lets tests assert "did/didn't hit the loader".
    """
    called: list[bool] = []

    def fake_loader(conversations):
        called.append(True)
        return mapping

    monkeypatch.setattr(cli_mod, "_load_engagement_for_conversations", fake_loader)
    return called


class TestFilterByEngagementNoFlags:
    def test_no_flags_returns_input_verbatim(self, monkeypatch):
        called = _patch_engagement_map(monkeypatch, {})
        convs = [_conv("a"), _conv("b")]
        result = _filter_by_engagement(
            convs,
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )
        assert result is convs
        # No DB hit when no flags set.
        assert called == []


class TestFilterByEngagementEngagedFlag:
    def test_engaged_keeps_only_positive_engagement(self, monkeypatch):
        mapping = {
            "a": _row(600),
            "b": _row(0),       # zero engagement -> drop
            "c": _row(120),
            # "d" missing -> drop
        }
        _patch_engagement_map(monkeypatch, mapping)
        convs = [_conv(x) for x in "abcd"]
        result = _filter_by_engagement(
            convs,
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )
        assert {c.id for c in result} == {"a", "c"}

    def test_engaged_with_null_engaged_seconds_drops(self, monkeypatch):
        # engaged_seconds == NULL in DB -> treated as 0 -> drop.
        mapping = {"a": _row(None)}
        _patch_engagement_map(monkeypatch, mapping)
        result = _filter_by_engagement(
            [_conv("a")],
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )
        assert result == []


class TestFilterByEngagementNoEngagedFlag:
    def test_no_engaged_keeps_missing_and_zero(self, monkeypatch):
        mapping = {
            "a": _row(600),     # engaged -> drop
            "b": _row(0),       # zero -> keep
            # "c" missing -> keep (fire-and-forget intent)
            "d": _row(None),    # NULL -> keep
        }
        _patch_engagement_map(monkeypatch, mapping)
        convs = [_conv(x) for x in "abcd"]
        result = _filter_by_engagement(
            convs,
            engaged=False,
            no_engaged=True,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )
        assert {c.id for c in result} == {"b", "c", "d"}


class TestFilterByEngagementMinEngaged:
    def test_min_engaged_threshold_keeps_at_or_above(self, monkeypatch):
        mapping = {
            "a": _row(600),   # >= 300 -> keep
            "b": _row(300),   # == 300 -> keep
            "c": _row(120),   # < 300 -> drop
            "d": _row(0),     # 0 -> drop (engaged_seconds <= 0 short-circuit)
            # "e" missing -> drop
        }
        _patch_engagement_map(monkeypatch, mapping)
        convs = [_conv(x) for x in "abcde"]
        result = _filter_by_engagement(
            convs,
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=300,
            min_engagement_ratio=None,
        )
        assert {c.id for c in result} == {"a", "b"}

    def test_min_engaged_zero_keeps_only_positive(self, monkeypatch):
        # --min-engaged 0 == --engaged (engaged_seconds > 0 short-circuits).
        mapping = {
            "a": _row(600),
            "b": _row(0),
            # "c" missing
        }
        _patch_engagement_map(monkeypatch, mapping)
        convs = [_conv(x) for x in "abc"]
        result = _filter_by_engagement(
            convs,
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=0,
            min_engagement_ratio=None,
        )
        assert {c.id for c in result} == {"a"}


class TestFilterByEngagementMinEngagementRatio:
    def test_ratio_threshold_keeps_at_or_above(self, monkeypatch):
        # PCT=25 -> ratio >= 0.25
        mapping = {
            "a": _row(600, 1000),   # 0.6 -> keep
            "b": _row(250, 1000),   # 0.25 -> keep (boundary)
            "c": _row(100, 1000),   # 0.1 -> drop
            "d": _row(600, 0),      # zero total -> drop
            "e": _row(600, None),   # NULL total -> drop
            # "f" missing -> drop
        }
        _patch_engagement_map(monkeypatch, mapping)
        convs = [_conv(x) for x in "abcdef"]
        result = _filter_by_engagement(
            convs,
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=25.0,
        )
        assert {c.id for c in result} == {"a", "b"}

    def test_ratio_zero_keeps_only_positive_engagement(self, monkeypatch):
        # AC: ``--min-engagement-ratio 0`` is a no-op equivalent to
        # ``--engaged``. Rows with 0 engaged still excluded.
        mapping = {
            "a": _row(60, 1000),
            "b": _row(0, 1000),
        }
        _patch_engagement_map(monkeypatch, mapping)
        result = _filter_by_engagement(
            [_conv("a"), _conv("b")],
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=0.0,
        )
        assert {c.id for c in result} == {"a"}


class TestFilterByEngagementCombined:
    def test_engaged_with_min_engaged_is_threshold_only(self, monkeypatch):
        """`--engaged --min-engaged 5m` ≡ `--min-engaged 5m`."""
        mapping = {
            "a": _row(600),
            "b": _row(120),
            "c": _row(0),
        }
        _patch_engagement_map(monkeypatch, mapping)
        result = _filter_by_engagement(
            [_conv(x) for x in "abc"],
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=300,
            min_engagement_ratio=None,
        )
        assert {c.id for c in result} == {"a"}

    def test_both_thresholds_must_both_pass(self, monkeypatch):
        """`--min-engaged 5m --min-engagement-ratio 50` ANDs the two."""
        mapping = {
            "a": _row(600, 1000),   # engaged>=300 AND 0.6>=0.5 -> keep
            "b": _row(600, 2000),   # engaged>=300 but 0.3 < 0.5 -> drop
            "c": _row(120, 200),    # 0.6 ratio but engaged 120 < 300 -> drop
        }
        _patch_engagement_map(monkeypatch, mapping)
        result = _filter_by_engagement(
            [_conv(x) for x in "abc"],
            engaged=False,
            no_engaged=False,
            min_engaged_seconds=300,
            min_engagement_ratio=50.0,
        )
        assert {c.id for c in result} == {"a"}


class TestFilterByEngagementEdgeCases:
    def test_empty_input_short_circuits(self, monkeypatch):
        called = _patch_engagement_map(monkeypatch, {})
        result = _filter_by_engagement(
            [],
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )
        assert result == []
        # Empty input is a no-op — no DB hit.
        assert called == []

    def test_missing_row_states_under_engaged(self, monkeypatch):
        """Tri-state collapse: every flag has a defined include/exclude
        decision for every engagement state."""
        mapping = {
            "present_pos": _row(60, 600),
            "present_zero": _row(0, 600),
            "present_null_total": _row(60, None),
            "present_zero_total": _row(60, 0),
            # "missing" not in map
        }
        _patch_engagement_map(monkeypatch, mapping)
        convs = [
            _conv("present_pos"),
            _conv("present_zero"),
            _conv("present_null_total"),
            _conv("present_zero_total"),
            _conv("missing"),
        ]

        # --engaged: positive engagement only (total irrelevant).
        result_engaged = _filter_by_engagement(
            convs, engaged=True, no_engaged=False,
            min_engaged_seconds=None, min_engagement_ratio=None,
        )
        assert {c.id for c in result_engaged} == {
            "present_pos", "present_null_total", "present_zero_total",
        }

        # Reset the patch — _patch_engagement_map clears called list each test.
        _patch_engagement_map(monkeypatch, mapping)

        # --no-engaged: missing OR zero engagement.
        result_no = _filter_by_engagement(
            convs, engaged=False, no_engaged=True,
            min_engaged_seconds=None, min_engagement_ratio=None,
        )
        assert {c.id for c in result_no} == {"present_zero", "missing"}


# ---------------------------------------------------------------------------
# ID normalization smoke (AGENTS.md item #14)
# ---------------------------------------------------------------------------


class TestFilterByEngagementIdMatching:
    def test_dashed_id_round_trip(self, monkeypatch):
        """``_load_engagement_for_conversations`` is keyed on the caller's
        *original* id, including dashes. The filter must use that key
        directly — no re-normalization in the filter layer."""
        dashed = "abcdef01-2345-6789-abcd-ef0123456789"
        mapping = {dashed: _row(600)}
        _patch_engagement_map(monkeypatch, mapping)
        result = _filter_by_engagement(
            [_conv(dashed)],
            engaged=True,
            no_engaged=False,
            min_engaged_seconds=None,
            min_engagement_ratio=None,
        )
        assert [c.id for c in result] == [dashed]
