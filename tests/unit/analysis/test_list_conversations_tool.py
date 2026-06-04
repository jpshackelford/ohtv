"""Tests for the ``list_conversations`` agent tool (Issue #160).

The executor delegates to ``cli._apply_conversation_filters`` for filtering
and to ``cli._find_conversation_dir`` + ``cache.load_all_analyses`` for
the warm-cache goal lookup. We exercise the real action/observation models
and the executor's own logic (sort, truncate, filter-echo, error handling)
against a patched filter helper so individual tests stay hermetic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ohtv.analysis.agent_tools import (
    LIST_CONVERSATIONS_MAX_LIMIT,
    ConversationSummary,
    ListConversationsAction,
    ListConversationsExecutor,
    ListConversationsObservation,
    ListConversationsTool,
)
from ohtv.cli import FilterResult
from ohtv.sources.base import ConversationInfo


# =============================================================================
# Fixtures / helpers
# =============================================================================


def _conv(
    conv_id: str,
    *,
    title: str | None = "T",
    source: str = "cloud",
    created_at: datetime | None = None,
    event_count: int | None = 10,
    selected_repository: str | None = None,
    labels: dict[str, str] | None = None,
) -> ConversationInfo:
    """Build a ConversationInfo with sensible defaults."""
    created_at = created_at or datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    return ConversationInfo(
        id=conv_id,
        title=title,
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=30),
        event_count=event_count,
        source=source,
        selected_repository=selected_repository,
        labels=labels,
        dir_name=conv_id.replace("-", ""),
    )


def _make_filter_result(convs: list[ConversationInfo]) -> FilterResult:
    return FilterResult(conversations=convs, possible_match_ids=set(), show_all=True)


@pytest.fixture
def executor(tmp_path: Path) -> ListConversationsExecutor:
    config = MagicMock()
    config.local_conversations_dir = tmp_path / "local"
    config.synced_conversations_dir = tmp_path / "cloud"
    config.extra_conversation_paths = []
    conv_store = MagicMock()
    return ListConversationsExecutor(config=config, conv_store=conv_store)


# =============================================================================
# Action / Observation / ConversationSummary
# =============================================================================


class TestListConversationsAction:
    def test_defaults(self) -> None:
        action = ListConversationsAction()
        assert action.since is None
        assert action.until is None
        assert action.day is None
        assert action.week is None
        assert action.repo is None
        assert action.pr is None
        assert action.action is None
        assert action.label is None
        assert action.limit == 20
        assert action.include_sub_conversations is False

    def test_explicit_fields(self) -> None:
        action = ListConversationsAction(
            since="7d",
            repo="owner/repo",
            label="team=AI",
            include_sub_conversations=True,
            limit=10,
        )
        assert action.since == "7d"
        assert action.repo == "owner/repo"
        assert action.label == "team=AI"
        assert action.include_sub_conversations is True
        assert action.limit == 10

    def test_visualize_renders_filters(self) -> None:
        action = ListConversationsAction(since="7d", repo="owner/repo")
        rendered = action.visualize.plain
        assert "List conversations" in rendered
        assert "since=7d" in rendered
        assert "repo=owner/repo" in rendered

    def test_visualize_with_no_filters(self) -> None:
        action = ListConversationsAction()
        rendered = action.visualize.plain
        assert "List conversations" in rendered


class TestConversationSummary:
    def test_basic(self) -> None:
        summary = ConversationSummary(
            id="abc12345" + "0" * 24,
            short_id="abc12345",
            source="cloud",
        )
        assert summary.title is None
        assert summary.goal is None
        assert summary.labels is None
        assert summary.event_count is None


class TestListConversationsObservation:
    def test_to_text_with_results(self) -> None:
        summary = ConversationSummary(
            id="abc12345" + "0" * 24,
            short_id="abc12345",
            title="Fix auth bug",
            source="cloud",
            created_at="2026-05-01T12:00:00+00:00",
            duration_seconds=300,
            event_count=42,
            goal="Restore login flow after refresh-token rotation",
            labels={"team": "auth"},
        )
        obs = ListConversationsObservation(
            total_matching=1,
            returned=[summary],
            truncated=False,
            filters_applied={"since": "2026-05-01", "limit": 20},
        )
        text = obs.to_text()
        assert "Found 1 matching" in text
        assert "abc12345" in text
        assert "Fix auth bug" in text
        assert "Restore login flow" in text
        assert "labels=team=auth" in text
        assert "42 events" in text

    def test_to_text_empty(self) -> None:
        obs = ListConversationsObservation(
            total_matching=0,
            returned=[],
            truncated=False,
            filters_applied={"repo": "owner/repo"},
        )
        assert "No conversations match" in obs.to_text()
        assert "owner/repo" in obs.to_text()

    def test_to_text_truncated_marker(self) -> None:
        summary = ConversationSummary(
            id="x" * 32, short_id="xxxxxxxx", source="cloud"
        )
        obs = ListConversationsObservation(
            total_matching=100,
            returned=[summary],
            truncated=True,
            filters_applied={"limit": 1},
        )
        assert "(truncated)" in obs.to_text()

    def test_to_text_error(self) -> None:
        obs = ListConversationsObservation(
            total_matching=0,
            returned=[],
            truncated=False,
            filters_applied={},
            error="DB unavailable",
        )
        assert obs.to_text() == "Error: DB unavailable"

    def test_to_text_marks_cache_miss(self) -> None:
        summary = ConversationSummary(
            id="x" * 32, short_id="xxxxxxxx", source="cloud", goal=None
        )
        obs = ListConversationsObservation(
            total_matching=1, returned=[summary], truncated=False, filters_applied={}
        )
        assert "(no cached analysis)" in obs.to_text()

    def test_to_text_truncates_long_goal(self) -> None:
        summary = ConversationSummary(
            id="x" * 32,
            short_id="xxxxxxxx",
            source="cloud",
            goal="A" * 500,
        )
        obs = ListConversationsObservation(
            total_matching=1, returned=[summary], truncated=False, filters_applied={}
        )
        text = obs.to_text()
        # 200 char cap with trailing "..."
        assert "A" * 197 + "..." in text
        # No 500-A run anywhere
        assert "A" * 500 not in text

    def test_visualize_renders_summaries(self) -> None:
        summaries = [
            ConversationSummary(
                id=str(i) * 32, short_id=str(i) * 8, source="cloud", title=f"t{i}"
            )
            for i in range(3)
        ]
        obs = ListConversationsObservation(
            total_matching=3,
            returned=summaries,
            truncated=False,
            filters_applied={},
        )
        rendered = obs.visualize.plain
        assert "showing 3" in rendered
        assert "t0" in rendered

    def test_visualize_error(self) -> None:
        obs = ListConversationsObservation(
            total_matching=0,
            returned=[],
            truncated=False,
            filters_applied={},
            error="boom",
        )
        assert "boom" in obs.visualize.plain


# =============================================================================
# Executor — core paths
# =============================================================================


class TestExecutorEmpty:
    def test_no_matches_returns_zero(
        self, executor: ListConversationsExecutor
    ) -> None:
        with patch(
            "ohtv.cli._apply_conversation_filters",
            return_value=_make_filter_result([]),
        ):
            obs = executor(ListConversationsAction(since="7d"))
        assert obs.total_matching == 0
        assert obs.returned == []
        assert obs.truncated is False
        assert obs.filters_applied["since"] is not None  # resolved to ISO


class TestExecutorSingleResult:
    def test_single_conv_no_cache(
        self, executor: ListConversationsExecutor
    ) -> None:
        conv = _conv("a" * 32, title="Hello")
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result([conv]),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
        ):
            obs = executor(ListConversationsAction())
        assert obs.total_matching == 1
        assert len(obs.returned) == 1
        s = obs.returned[0]
        assert s.id == "a" * 32
        assert s.short_id == "a" * 7
        assert s.title == "Hello"
        assert s.duration_seconds == 1800  # 30 minutes
        assert s.goal is None  # No cache file -> miss

    def test_single_conv_with_cached_goal(
        self, executor: ListConversationsExecutor, tmp_path: Path
    ) -> None:
        conv = _conv("b" * 32, title="Cache-warmed")
        conv_dir = tmp_path / "cache" / conv.dir_name
        # Build a real cache file the executor will read.
        from ohtv.analysis.cache import make_cache_key

        analyses = {
            make_cache_key(context="minimal", detail="brief", assess=False): {
                "goal": "Add pagination",
                "primary_outcomes": [],
                "secondary_outcomes": [],
                "primary_objectives": [],
                "summary": None,
            }
        }
        conv_dir.mkdir(parents=True)
        (conv_dir / "objective_analysis.json").write_text(
            __import__("json").dumps({"version": 1, "analyses": analyses})
        )

        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result([conv]),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=(conv_dir, True),
            ),
        ):
            obs = executor(ListConversationsAction())

        assert obs.total_matching == 1
        assert obs.returned[0].goal == "Add pagination"


class TestExecutorTruncation:
    def test_truncates_to_limit(self, executor: ListConversationsExecutor) -> None:
        convs = [
            _conv(
                hex(i)[2:].rjust(32, "0"),
                created_at=datetime(2026, 5, 1, 12, i, tzinfo=timezone.utc),
            )
            for i in range(30)
        ]
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result(convs),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
        ):
            obs = executor(ListConversationsAction(limit=10))
        assert obs.total_matching == 30
        assert len(obs.returned) == 10
        assert obs.truncated is True

    def test_limit_clamped_to_max(
        self, executor: ListConversationsExecutor
    ) -> None:
        convs = [_conv(hex(i)[2:].rjust(32, "0")) for i in range(60)]
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result(convs),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
        ):
            obs = executor(ListConversationsAction(limit=200))
        assert len(obs.returned) == LIST_CONVERSATIONS_MAX_LIMIT
        assert obs.filters_applied["limit"] == LIST_CONVERSATIONS_MAX_LIMIT

    def test_limit_floor_is_one(self, executor: ListConversationsExecutor) -> None:
        convs = [_conv("a" * 32)]
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result(convs),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
        ):
            obs = executor(ListConversationsAction(limit=0))
        assert obs.filters_applied["limit"] == 1


class TestExecutorSorting:
    def test_results_sorted_newest_first(
        self, executor: ListConversationsExecutor
    ) -> None:
        old = _conv(
            "a" * 32,
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        mid = _conv(
            "b" * 32,
            created_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        )
        new = _conv(
            "c" * 32,
            created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        )
        # Feed in arbitrary order
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result([mid, new, old]),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
        ):
            obs = executor(ListConversationsAction())
        ids = [s.id for s in obs.returned]
        assert ids == ["c" * 32, "b" * 32, "a" * 32]

    def test_handles_none_created_at(
        self, executor: ListConversationsExecutor
    ) -> None:
        no_date = ConversationInfo(
            id="a" * 32,
            title=None,
            created_at=None,
            updated_at=None,
            event_count=1,
            source="cloud",
        )
        with_date = _conv("b" * 32)
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result([no_date, with_date]),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
        ):
            obs = executor(ListConversationsAction())
        # The dated conv sorts ahead of the dateless one
        assert obs.returned[0].id == "b" * 32
        # The dateless conv has duration_seconds = None
        assert obs.returned[1].duration_seconds is None
        assert obs.returned[1].created_at is None


# =============================================================================
# Executor — filter-axis pass-through
# =============================================================================


class TestExecutorFilterAxes:
    """Every filter parameter is forwarded to ``_apply_conversation_filters``."""

    @pytest.mark.parametrize(
        "kwargs,expected_kwarg,expected_value",
        [
            ({"repo": "owner/repo"}, "repo_filter", "owner/repo"),
            ({"pr": "owner/repo#7"}, "pr_filter", "owner/repo#7"),
            ({"action": "pushed"}, "action_filter", "pushed"),
            ({"label": "team=AI"}, "label_filter", "team=AI"),
            (
                {"include_sub_conversations": True},
                "include_sub_conversations",
                True,
            ),
        ],
    )
    def test_filter_kwarg_forwarded(
        self,
        executor: ListConversationsExecutor,
        kwargs: dict,
        expected_kwarg: str,
        expected_value,
    ) -> None:
        with patch(
            "ohtv.cli._apply_conversation_filters",
            return_value=_make_filter_result([]),
        ) as patched:
            executor(ListConversationsAction(**kwargs))
        assert patched.call_args.kwargs[expected_kwarg] == expected_value

    def test_since_until_resolved_to_datetimes(
        self, executor: ListConversationsExecutor
    ) -> None:
        with patch(
            "ohtv.cli._apply_conversation_filters",
            return_value=_make_filter_result([]),
        ) as patched:
            executor(ListConversationsAction(since="7d", until="today"))
        kwargs = patched.call_args.kwargs
        assert isinstance(kwargs["since"], datetime)
        assert isinstance(kwargs["until"], datetime)

    def test_day_filter_resolved(
        self, executor: ListConversationsExecutor
    ) -> None:
        with patch(
            "ohtv.cli._apply_conversation_filters",
            return_value=_make_filter_result([]),
        ) as patched:
            executor(ListConversationsAction(day="2026-05-15"))
        kwargs = patched.call_args.kwargs
        # day populates both since AND until (day bounds)
        assert kwargs["since"] is not None
        assert kwargs["until"] is not None

    def test_week_filter_resolved(
        self, executor: ListConversationsExecutor
    ) -> None:
        with patch(
            "ohtv.cli._apply_conversation_filters",
            return_value=_make_filter_result([]),
        ) as patched:
            executor(ListConversationsAction(week="2"))
        kwargs = patched.call_args.kwargs
        assert kwargs["since"] is not None
        assert kwargs["until"] is not None

    def test_default_excludes_sub_conversations(
        self, executor: ListConversationsExecutor
    ) -> None:
        """Issue #125 default: roots only unless explicitly opted in."""
        with patch(
            "ohtv.cli._apply_conversation_filters",
            return_value=_make_filter_result([]),
        ) as patched:
            executor(ListConversationsAction())
        assert patched.call_args.kwargs["include_sub_conversations"] is False


# =============================================================================
# Executor — error paths
# =============================================================================


class TestExecutorErrors:
    def test_filter_failure_reported_as_observation_error(
        self, executor: ListConversationsExecutor
    ) -> None:
        with patch(
            "ohtv.cli._apply_conversation_filters",
            side_effect=RuntimeError("DB closed"),
        ):
            obs = executor(ListConversationsAction(repo="x/y"))
        assert obs.error is not None
        assert "DB closed" in obs.error
        assert obs.total_matching == 0
        # filters_applied still echoes the inputs so the agent can correct
        assert obs.filters_applied["repo"] == "x/y"


class TestExecutorCacheReadsOnly:
    """The executor MUST NOT trigger LLM analysis on a cache miss (AC bullet)."""

    def test_cache_miss_does_not_invoke_analyze_objectives(
        self, executor: ListConversationsExecutor
    ) -> None:
        conv = _conv("a" * 32)
        with (
            patch(
                "ohtv.cli._apply_conversation_filters",
                return_value=_make_filter_result([conv]),
            ),
            patch(
                "ohtv.analysis.agent_tools._find_conv_dir_for_executor",
                return_value=None,
            ),
            patch(
                "ohtv.analysis.objectives.analyze_objectives",
                side_effect=AssertionError("Must not be called on cache miss"),
            ),
        ):
            obs = executor(ListConversationsAction())
        assert obs.total_matching == 1
        assert obs.returned[0].goal is None


# =============================================================================
# Tool factory
# =============================================================================


class TestListConversationsToolCreate:
    def test_create_returns_one_tool(self) -> None:
        config = MagicMock()
        conv_store = MagicMock()
        tools = ListConversationsTool.create(config=config, conv_store=conv_store)
        assert len(tools) == 1
        assert tools[0].name == "list_conversations"
        assert tools[0].executor is not None
        # Tool advertised as read-only / idempotent so the host can cache.
        assert tools[0].annotations.readOnlyHint is True
        assert tools[0].annotations.destructiveHint is False

    def test_create_requires_config(self) -> None:
        with pytest.raises(ValueError, match="config is required"):
            ListConversationsTool.create(conv_store=MagicMock())

    def test_create_requires_conv_store(self) -> None:
        with pytest.raises(ValueError, match="conv_store is required"):
            ListConversationsTool.create(config=MagicMock())
