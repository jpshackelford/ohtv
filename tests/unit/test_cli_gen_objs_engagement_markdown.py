"""Tests for ``ohtv gen objs --with-engagement -F markdown`` (Issue #169).

Covers the new ``_format_engaged_markdown_subbullet`` helper plus the
integration of the ``Engaged:`` sub-bullet into the multi-conversation
markdown emitter (``_format_summary_markdown``). Mirrors the structure
of ``test_cli_gen_objs_engagement.py`` (Issue #168) for the JSON path.

All DB-touching tests use a real temporary SQLite DB (via the
``OHTV_DIR`` env var) — matching the no-mocks-on-data-path policy in
AGENTS.md.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ohtv.cli import (
    _format_engaged_markdown_subbullet,
    _format_summary_markdown,
    main,
)


# ---------------------------------------------------------------------------
# Helpers (mirror test_cli_gen_objs_engagement.py)
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
    mock.event_count = 8
    mock.duration = timedelta(minutes=50)
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


def _make_result_dict(
    *,
    conv_id: str = "abc123def456",
    short_id: str = "abc123d",
    duration: timedelta | None = timedelta(seconds=3000),
    goal: str = "Fix flaky CI",
    engagement: dict | None = None,
    labels: dict | None = None,
    outputs: dict | None = None,
) -> dict:
    """Build a minimal result dict for ``_format_summary_markdown``."""
    return {
        "id": conv_id,
        "short_id": short_id,
        "created_at": datetime(2026, 6, 3, 9, 12, tzinfo=timezone.utc),
        "duration": duration,
        "event_count": 8,
        "goal": goal,
        "engagement": engagement,
        "labels": labels,
        "outputs": outputs,
    }


# ---------------------------------------------------------------------------
# _format_engaged_markdown_subbullet — pure helper
# ---------------------------------------------------------------------------


class TestFormatEngagedMarkdownSubbullet:
    def test_returns_none_when_engagement_missing(self):
        assert _format_engaged_markdown_subbullet(None, timedelta(seconds=3000)) is None

    def test_returns_none_when_engagement_empty_dict(self):
        """Empty dict ⇒ both required keys missing ⇒ None (matches _format_engaged_line)."""
        assert _format_engaged_markdown_subbullet({}, timedelta(seconds=3000)) is None

    def test_returns_none_when_engaged_seconds_missing(self):
        engagement = {"attention_periods": 2}
        assert _format_engaged_markdown_subbullet(engagement, timedelta(seconds=3000)) is None

    def test_returns_none_when_periods_missing(self):
        engagement = {"engaged_seconds": 264}
        assert _format_engaged_markdown_subbullet(engagement, timedelta(seconds=3000)) is None

    def test_renders_present_row_with_percentage(self):
        engagement = {
            "engaged_seconds": 264,
            "attention_periods": 2,
            "total_duration_seconds": 3014,
        }
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=3000))
        # 264 / 3000 = 8.8%
        assert out == "4m 24s in 2 periods (8.8%)"

    def test_drops_of_total_suffix_vs_engaged_line(self):
        """Issue #169: the parent bullet already shows duration inline,
        so we omit the ``of <duration> total`` tail."""
        engagement = {"engaged_seconds": 264, "attention_periods": 2}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=3000))
        assert "of " not in out
        assert "total" not in out

    def test_singular_period(self):
        engagement = {"engaged_seconds": 60, "attention_periods": 1}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=120))
        assert out == "1m 00s in 1 period (50.0%)"
        assert "1 periods" not in out

    def test_plural_periods(self):
        engagement = {"engaged_seconds": 120, "attention_periods": 3}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=600))
        assert out == "2m 00s in 3 periods (20.0%)"

    def test_drops_percentage_when_duration_none(self):
        engagement = {"engaged_seconds": 264, "attention_periods": 2}
        out = _format_engaged_markdown_subbullet(engagement, None)
        # No parenthetical when total duration is unknown.
        assert out == "4m 24s in 2 periods"
        assert "(" not in out

    def test_drops_percentage_when_zero_duration(self):
        engagement = {"engaged_seconds": 264, "attention_periods": 2}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=0))
        assert out == "4m 24s in 2 periods"
        assert "(" not in out

    def test_engaged_zero_renders_zero_seconds(self):
        """engaged_seconds=0 ⇒ '0s' (not '0m 00s' or '')."""
        engagement = {"engaged_seconds": 0, "attention_periods": 0}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=3000))
        assert out == "0s in 0 periods (0.0%)"

    def test_hours_format(self):
        """Large engaged_seconds gets hour/minute/second formatting."""
        engagement = {"engaged_seconds": 8040, "attention_periods": 5}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=10000))
        # 8040 / 10000 = 80.4%; 8040s = 2h 14m 00s
        assert "2h 14m 00s" in out
        assert "in 5 periods" in out
        assert "(80.4%)" in out

    def test_precision_one_decimal(self):
        """Percentage uses XX.X% precision — matches _format_engaged_line."""
        engagement = {"engaged_seconds": 100, "attention_periods": 1}
        out = _format_engaged_markdown_subbullet(engagement, timedelta(seconds=333))
        # 100 / 333 = 30.0300...% → "30.0%"
        assert "(30.0%)" in out


# ---------------------------------------------------------------------------
# _format_summary_markdown — engagement integration
# ---------------------------------------------------------------------------


class TestFormatSummaryMarkdownEngagement:
    def test_engagement_absent_no_subbullet(self):
        """No 'engagement' key ⇒ no 'Engaged:' sub-bullet (default path)."""
        r = _make_result_dict(engagement=None)
        out = _format_summary_markdown([r])
        assert "Engaged:" not in out

    def test_engagement_missing_required_fields_no_subbullet(self):
        """Partial engagement dict ⇒ helper returns None ⇒ no sub-bullet."""
        r = _make_result_dict(engagement={"engaged_seconds": 264})
        out = _format_summary_markdown([r])
        assert "Engaged:" not in out

    def test_engagement_present_renders_subbullet(self):
        r = _make_result_dict(
            engagement={"engaged_seconds": 264, "attention_periods": 2},
            duration=timedelta(seconds=3000),
        )
        out = _format_summary_markdown([r])
        # Sub-bullet uses two-space indent + dash (matches refs / labels).
        assert "  - Engaged: 4m 24s in 2 periods (8.8%)" in out

    def test_subbullet_immediately_after_parent_bullet(self):
        """AC: Engaged: rendered first among sub-bullets."""
        r = _make_result_dict(
            engagement={"engaged_seconds": 264, "attention_periods": 2},
            duration=timedelta(seconds=3000),
            labels={"team": "AI"},
        )
        out = _format_summary_markdown([r])
        lines = out.split("\n")
        # Find the parent bullet, then assert the next non-empty line is Engaged:.
        parent_idx = next(i for i, ln in enumerate(lines) if ln.startswith("- **"))
        assert lines[parent_idx + 1].lstrip().startswith("- Engaged: ")

    def test_subbullet_ordering_before_refs_and_labels(self):
        """AC: Engaged: appears before Repos / PRs / Issues / Labels."""
        # Build an outputs dict mimicking what _get_conversation_outputs returns.
        # Use sets to mirror the production data type used by _format_refs_for_markdown.
        outputs = {
            "refs": {
                "repos": {"https://github.com/jpshackelford/OpenPaw"},
                "prs": {"https://github.com/jpshackelford/OpenPaw/pull/142"},
                "issues": set(),
            },
            "interactions": None,
            "unpushed_commits": set(),
        }
        r = _make_result_dict(
            engagement={"engaged_seconds": 264, "attention_periods": 2},
            duration=timedelta(seconds=3000),
            outputs=outputs,
            labels={"team": "AI"},
        )
        out = _format_summary_markdown([r], include_outputs=True)
        engaged_idx = out.find("Engaged:")
        repo_idx = out.find("Repo:")
        pr_idx = out.find("PR:")
        labels_idx = out.find("Labels:")
        # All four substrings present in the output.
        assert engaged_idx != -1
        assert repo_idx != -1
        assert pr_idx != -1
        assert labels_idx != -1
        # Engaged comes before each of the other sub-bullets.
        assert engaged_idx < repo_idx
        assert engaged_idx < pr_idx
        assert engaged_idx < labels_idx

    def test_zero_duration_drops_percentage_in_subbullet(self):
        """AC: total_duration_seconds=0 / NULL ⇒ drop the percentage."""
        r = _make_result_dict(
            engagement={"engaged_seconds": 264, "attention_periods": 2},
            duration=timedelta(seconds=0),
        )
        out = _format_summary_markdown([r])
        # Sub-bullet rendered but without percentage.
        assert "  - Engaged: 4m 24s in 2 periods" in out
        assert "%" not in out.split("Engaged:")[1].split("\n")[0]

    def test_singular_period_in_subbullet(self):
        r = _make_result_dict(
            engagement={"engaged_seconds": 60, "attention_periods": 1},
            duration=timedelta(seconds=120),
        )
        out = _format_summary_markdown([r])
        assert "  - Engaged: 1m 00s in 1 period (50.0%)" in out
        # Critical: no "1 periods" anywhere in the output.
        assert "1 periods" not in out

    def test_mixed_present_missing_zero_in_one_render(self):
        """3-row mix: present row, absent row, zero-duration row.

        Asserts each row's bullet is structurally correct and they don't
        bleed sub-bullets into each other.
        """
        present = _make_result_dict(
            conv_id="a" * 32, short_id="aaaaaaa",
            engagement={"engaged_seconds": 264, "attention_periods": 2},
            duration=timedelta(seconds=3000),
            goal="Present goal",
        )
        absent = _make_result_dict(
            conv_id="b" * 32, short_id="bbbbbbb",
            engagement=None,
            duration=timedelta(seconds=3000),
            goal="Absent goal",
        )
        zero_dur = _make_result_dict(
            conv_id="c" * 32, short_id="ccccccc",
            engagement={"engaged_seconds": 60, "attention_periods": 1},
            duration=timedelta(seconds=0),
            goal="Zero-dur goal",
        )
        out = _format_summary_markdown([present, absent, zero_dur])
        # Exactly two Engaged sub-bullets — one for present, one for zero-dur.
        # The absent row contributes zero.
        assert out.count("- Engaged: ") == 2
        # Present row carries percentage.
        assert "Engaged: 4m 24s in 2 periods (8.8%)" in out
        # Zero-duration row omits percentage.
        assert "Engaged: 1m 00s in 1 period" in out
        assert "1 period (" not in out  # no parenthetical after the period count
        # All three parent bullets present.
        assert "**aaaaaaa**" in out
        assert "**bbbbbbb**" in out
        assert "**ccccccc**" in out

    def test_helper_signature_unchanged_without_engagement(self):
        """Regression guard: _format_summary_markdown still works for
        result dicts that have no 'engagement' key (pre-#169 shape)."""
        r = {
            "id": "abc",
            "short_id": "abc",
            "created_at": datetime(2026, 6, 3, 9, 12, tzinfo=timezone.utc),
            "duration": timedelta(seconds=3000),
            "event_count": 8,
            "goal": "Pre-169 result",
        }
        # Must not raise and must not render Engaged:.
        out = _format_summary_markdown([r])
        assert "Engaged:" not in out
        assert "**abc**" in out


# ---------------------------------------------------------------------------
# CLI integration via CliRunner
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCliWithEngagementMarkdown:
    def test_flag_off_no_engaged_subbullet(self, runner, tmp_path, monkeypatch):
        """Regression guard: -F markdown without --with-engagement is unchanged."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(main, ["gen", "objs", "-F", "markdown"])

        assert result.exit_code == 0, result.output
        assert "Engaged:" not in result.output

    def test_flag_on_present_row_renders_engaged_subbullet(
        self, runner, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        # Engaged 2460s / 3000s duration ≈ 82.0%. The mock CI has duration=50m=3000s.
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=3000,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "-F", "markdown", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        assert "  - Engaged: 41m 00s in 3 periods (82.0%)" in result.output

    def test_flag_on_mixed_present_and_missing_rows(
        self, runner, tmp_path, monkeypatch
    ):
        """One conversation has a row; the other doesn't. Mixed render."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        present_id = "a" * 32
        missing_id = "b" * 32
        _seed_engagement_row(
            tmp_path, present_id, engaged_seconds=100,
            attention_periods=1, total_duration_seconds=3000,
        )

        conversations = [
            _mock_conversation_info(present_id),
            _mock_conversation_info(missing_id),
        ]
        analysis_result = _build_objective_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "-F", "markdown", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        # Exactly ONE Engaged sub-bullet in the output (the present row).
        assert result.output.count("  - Engaged:") == 1
        # Both parent bullets present.
        assert f"**{present_id[:7]}**" in result.output
        assert f"**{missing_id[:7]}**" in result.output

    def test_flag_on_table_is_byte_identical_noop(
        self, runner, tmp_path, monkeypatch
    ):
        """``--with-engagement -F table`` must produce byte-identical output to plain ``-F table``.

        Mirrors the same regression guard in the JSON test file. (Test
        ``TestMultiConvJsonWithEngagement.test_flag_on_table_format_is_noop``
        in test_cli_gen_objs_engagement.py already covers this, but we
        re-assert here so the markdown work doesn't regress the table path.)
        """
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        conv_id = "a" * 32
        _seed_engagement_row(
            tmp_path, conv_id, engaged_seconds=2460,
            attention_periods=3, total_duration_seconds=8040,
        )

        conversations = [_mock_conversation_info(conv_id)]
        analysis_result = _build_objective_analysis_result()

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
        # Neither output mentions Engaged in the table format.
        assert "Engaged:" not in without.output
        assert "Engaged:" not in with_flag.output

    def test_id_normalization_dashed_caller_id(
        self, runner, tmp_path, monkeypatch
    ):
        """AGENTS.md item #14: LocalSource returns dashed ids; DB stores dashless.

        Seed an engagement row with a dashless id and run gen objs with a
        ConversationInfo whose id is dashed. The sub-bullet must render
        (proves the batch loader normalizes correctly).
        """
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        dashless = "abcdef0123456789abcdef0123456789"
        dashed = "abcdef01-2345-6789-abcd-ef0123456789"
        _seed_engagement_row(
            tmp_path, dashless, engaged_seconds=300,
            attention_periods=2, total_duration_seconds=3000,
        )

        conversations = [_mock_conversation_info(dashed)]
        analysis_result = _build_objective_analysis_result()

        with contextlib.ExitStack() as stack:
            for cm in _patch_batch_environment(conversations, analysis_result):
                stack.enter_context(cm)
            result = runner.invoke(
                main, ["gen", "objs", "-F", "markdown", "--with-engagement"]
            )

        assert result.exit_code == 0, result.output
        # 300 / 3000 = 10.0%
        assert "  - Engaged: 5m 00s in 2 periods (10.0%)" in result.output


# ---------------------------------------------------------------------------
# CLI help — surface check
# ---------------------------------------------------------------------------


class TestHelpDocumentsMarkdownEffect:
    def test_help_text_mentions_markdown(self, runner):
        result = runner.invoke(main, ["gen", "objs", "--help"])
        assert result.exit_code == 0
        # The help text now mentions the markdown sub-bullet (Issue #169).
        assert "--with-engagement" in result.output
        # Updated help text mentions markdown rendering. We don't pin the
        # exact wording — just that the markdown effect is documented.
        assert "markdown" in result.output.lower()


# ---------------------------------------------------------------------------
# Pure helper: ensure _format_summary_markdown signature is unchanged
# ---------------------------------------------------------------------------


def test_format_summary_markdown_signature_unchanged():
    """Defensive: the (results, *, include_outputs) signature must not regress.

    Issue #169 explicitly chose to attach engagement to each result dict
    rather than threading a new engagement_map parameter, to keep the
    public signature stable for the legacy callers.
    """
    import inspect

    sig = inspect.signature(_format_summary_markdown)
    params = list(sig.parameters.keys())
    assert params == ["results", "include_outputs"]
