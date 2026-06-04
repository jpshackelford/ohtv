"""Custom tools for the investigation agent.

Provides tools that allow the agent to:
1. Load and examine specific conversation trajectories
2. Search for related conversations
3. Get git references (PRs, issues, repos) for conversations
4. Enumerate conversations by metadata filters (date / repo / PR / action / label)
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, Field
from rich.text import Text

from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor


if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ohtv.config import Config
    from ohtv.db.stores import (
        ConversationStore,
        EmbeddingStore,
        LinkStore,
        ReferenceStore,
        RepoStore,
    )


# ============================================================================
# ShowConversation Tool
# ============================================================================


class ShowConversationAction(Action):
    """Action to load and examine a specific conversation transcript."""

    conversation_id: str = Field(
        description="The conversation ID to examine (first 8 characters are sufficient)"
    )
    show_details: bool = Field(
        default=False,
        description="Whether to include detailed tool call information",
    )
    max_messages: int = Field(
        default=50,
        description="Maximum number of messages to return (default: 50)",
    )

    @property
    def visualize(self) -> Text:
        content = Text()
        content.append("Show conversation: ", style="bold blue")
        content.append(self.conversation_id)
        return content


class ShowConversationObservation(Observation):
    """Observation containing the conversation transcript."""

    conversation_id: str = Field(description="The full conversation ID")
    title: str | None = Field(default=None, description="Conversation title")
    message_count: int = Field(description="Number of messages retrieved")
    transcript: str = Field(description="The conversation transcript")
    error: str | None = Field(default=None, description="Error message if any")

    def to_text(self) -> str:
        """Return the observation content as plain text for LLM context."""
        return self.transcript or self.error or "No result"

    @property
    def visualize(self) -> Text:
        content = Text()
        if self.error:
            content.append(f"Error: {self.error}", style="red")
        else:
            content.append(f"Transcript ({self.message_count} messages):\n", style="dim")
            # Show truncated preview
            preview = self.transcript[:500] + "..." if len(self.transcript) > 500 else self.transcript
            content.append(preview)
        return content


class ShowConversationExecutor(ToolExecutor[ShowConversationAction, ShowConversationObservation]):
    """Executor that loads conversation transcripts from the database."""

    def __init__(
        self,
        conv_store: "ConversationStore",
        conversation_dirs: list[str] | None = None,
    ):
        self.conv_store = conv_store
        self.conversation_dirs = conversation_dirs or []

    def _find_conversation_dir(self, conv_id: str):
        """Find conversation directory by prefix match."""
        from pathlib import Path

        normalized_id = conv_id.replace("-", "")

        for base_dir_str in self.conversation_dirs:
            base_dir = Path(base_dir_str)
            if not base_dir.exists():
                continue

            # Try exact match first
            exact = base_dir / normalized_id
            if exact.exists():
                return exact

            # Prefix match
            for d in base_dir.iterdir():
                if d.is_dir() and d.name.startswith(normalized_id):
                    return d

        return None

    def _load_events(self, conv_dir) -> list[dict]:
        """Load events from conversation directory."""
        import json
        from pathlib import Path

        events = []
        events_dir = conv_dir / "events"

        if not events_dir.exists():
            # Try loading from single file
            events_file = conv_dir / "events.json"
            if events_file.exists():
                with open(events_file) as f:
                    events = json.load(f)
            return events

        # Load individual event files
        for event_file in sorted(events_dir.glob("*.json")):
            try:
                with open(event_file) as f:
                    events.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue

        return events

    def _build_simple_transcript(self, events: list[dict], max_messages: int, show_details: bool) -> str:
        """Build a simple transcript from events."""
        from ohtv.analysis.transcript import extract_message_content, extract_action_summary

        lines = []
        count = 0

        for event in events:
            if count >= max_messages:
                lines.append(f"\n... (truncated, {len(events) - count} more events)")
                break

            kind = event.get("kind", "")
            source = event.get("source", "")

            if kind == "MessageEvent":
                content = extract_message_content(event)
                if content:
                    role = "USER" if source == "user" else "ASSISTANT"
                    # Truncate long messages
                    if len(content) > 1000 and not show_details:
                        content = content[:1000] + "..."
                    lines.append(f"[{role}]: {content}")
                    count += 1

            elif kind == "ActionEvent" and show_details:
                summary = extract_action_summary(event)
                lines.append(f"[ACTION]: {summary}")
                count += 1

        return "\n\n".join(lines)

    def __call__(
        self,
        action: ShowConversationAction,
        conversation: "LocalConversation | None" = None,
    ) -> ShowConversationObservation:
        try:
            conv_id = action.conversation_id.replace("-", "")

            # Find conversation directory
            conv_dir = self._find_conversation_dir(conv_id)
            if conv_dir is None:
                return ShowConversationObservation(
                    conversation_id=conv_id,
                    title=None,
                    message_count=0,
                    transcript="",
                    error=f"Conversation not found: {action.conversation_id}",
                )

            # Get title from database
            full_id = conv_dir.name.replace("-", "")
            conv = self.conv_store.get(full_id)
            title = conv.title if conv else None

            # Load and build transcript
            events = self._load_events(conv_dir)
            transcript = self._build_simple_transcript(events, action.max_messages, action.show_details)

            return ShowConversationObservation(
                conversation_id=full_id,
                title=title,
                message_count=len([e for e in events if e.get("kind") == "MessageEvent"]),
                transcript=transcript,
            )

        except Exception as e:
            return ShowConversationObservation(
                conversation_id=action.conversation_id,
                title=None,
                message_count=0,
                transcript="",
                error=str(e),
            )


class ShowConversationTool(ToolDefinition[ShowConversationAction, ShowConversationObservation]):
    """Tool for loading and examining a specific conversation trajectory."""

    @classmethod
    def create(
        cls,
        conv_state: Any = None,
        conv_store: "ConversationStore | None" = None,
        conversation_dirs: list[str] | None = None,
        **params,
    ) -> Sequence[Self]:
        if conv_store is None:
            raise ValueError("conv_store is required for ShowConversationTool")

        return [
            cls(
                action_type=ShowConversationAction,
                observation_type=ShowConversationObservation,
                description=(
                    "Load and examine a specific conversation trajectory. "
                    "Use this to get detailed information about a conversation mentioned in the initial answer. "
                    "Provide the conversation ID (first 8 characters are sufficient)."
                ),
                executor=ShowConversationExecutor(conv_store, conversation_dirs),
                annotations=ToolAnnotations(
                    title="show_conversation",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]


# ============================================================================
# SearchConversations Tool
# ============================================================================


class SearchConversationsAction(Action):
    """Action to search for related conversations."""

    query: str = Field(
        description="Search query to find related conversations"
    )
    max_results: int = Field(
        default=5,
        description="Maximum number of results to return (default: 5)",
    )

    @property
    def visualize(self) -> Text:
        content = Text()
        content.append("Search: ", style="bold blue")
        content.append(self.query)
        return content


class SearchConversationsObservation(Observation):
    """Observation containing search results."""

    query: str = Field(description="The search query used")
    result_count: int = Field(description="Number of results found")
    results: str = Field(description="Formatted search results")
    error: str | None = Field(default=None, description="Error message if any")

    def to_text(self) -> str:
        """Return the observation content as plain text for LLM context."""
        return self.results or self.error or "No result"

    @property
    def visualize(self) -> Text:
        content = Text()
        if self.error:
            content.append(f"Error: {self.error}", style="red")
        else:
            content.append(f"Found {self.result_count} results:\n", style="dim")
            content.append(self.results)
        return content


class SearchConversationsExecutor(ToolExecutor[SearchConversationsAction, SearchConversationsObservation]):
    """Executor that searches conversations using embeddings."""

    def __init__(
        self,
        embed_store: "EmbeddingStore",
        conv_store: "ConversationStore",
    ):
        self.embed_store = embed_store
        self.conv_store = conv_store

    def __call__(
        self,
        action: SearchConversationsAction,
        conversation: "LocalConversation | None" = None,
    ) -> SearchConversationsObservation:
        try:
            # Search using embeddings
            results = self.embed_store.search_conversations(
                query=action.query,
                limit=action.max_results,
            )

            if not results:
                return SearchConversationsObservation(
                    query=action.query,
                    result_count=0,
                    results="No matching conversations found.",
                )

            # Format results
            formatted = []
            for r in results:
                conv = self.conv_store.get(r.conversation_id)
                title = conv.title if conv else f"Conversation {r.conversation_id[:8]}"
                date_str = conv.created_at.strftime("%Y-%m-%d") if conv and conv.created_at else "unknown"
                summary = conv.summary if conv and conv.summary else "No summary available"
                
                formatted.append(
                    f"- [{r.conversation_id[:8]}] {title} ({date_str})\n"
                    f"  Score: {r.score:.3f}\n"
                    f"  Summary: {summary[:150]}{'...' if len(summary) > 150 else ''}"
                )

            return SearchConversationsObservation(
                query=action.query,
                result_count=len(results),
                results="\n\n".join(formatted),
            )

        except Exception as e:
            return SearchConversationsObservation(
                query=action.query,
                result_count=0,
                results="",
                error=str(e),
            )


class SearchConversationsTool(ToolDefinition[SearchConversationsAction, SearchConversationsObservation]):
    """Tool for searching related conversations using semantic search."""

    @classmethod
    def create(
        cls,
        conv_state: Any = None,
        embed_store: "EmbeddingStore | None" = None,
        conv_store: "ConversationStore | None" = None,
        **params,
    ) -> Sequence[Self]:
        if embed_store is None:
            raise ValueError("embed_store is required for SearchConversationsTool")
        if conv_store is None:
            raise ValueError("conv_store is required for SearchConversationsTool")

        return [
            cls(
                action_type=SearchConversationsAction,
                observation_type=SearchConversationsObservation,
                description=(
                    "Search for related conversations using semantic search. "
                    "Use this to find additional conversations that might be relevant to the question. "
                    "The query can be natural language describing what you're looking for."
                ),
                executor=SearchConversationsExecutor(embed_store, conv_store),
                annotations=ToolAnnotations(
                    title="search_conversations",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]


# ============================================================================
# GetRefs Tool
# ============================================================================


class GetRefsAction(Action):
    """Action to get git references for a conversation."""

    conversation_id: str = Field(
        description="The conversation ID to get refs for (first 8 characters are sufficient)"
    )

    @property
    def visualize(self) -> Text:
        content = Text()
        content.append("Get refs for: ", style="bold blue")
        content.append(self.conversation_id)
        return content


class GetRefsObservation(Observation):
    """Observation containing git references."""

    conversation_id: str = Field(description="The conversation ID")
    refs_summary: str = Field(description="Summary of git references (PRs, issues, repos)")
    error: str | None = Field(default=None, description="Error message if any")

    def to_text(self) -> str:
        """Return the observation content as plain text for LLM context."""
        return self.refs_summary or self.error or "No result"

    @property
    def visualize(self) -> Text:
        content = Text()
        if self.error:
            content.append(f"Error: {self.error}", style="red")
        else:
            content.append("Git References:\n", style="dim")
            content.append(self.refs_summary)
        return content


class GetRefsExecutor(ToolExecutor[GetRefsAction, GetRefsObservation]):
    """Executor that retrieves git references for a conversation."""

    def __init__(
        self,
        link_store: "LinkStore",
        ref_store: "ReferenceStore",
        repo_store: "RepoStore",
    ):
        self.link_store = link_store
        self.ref_store = ref_store
        self.repo_store = repo_store

    def __call__(
        self,
        action: GetRefsAction,
        conversation: "LocalConversation | None" = None,
    ) -> GetRefsObservation:
        try:
            conv_id = action.conversation_id.replace("-", "")

            # Get repositories
            repos = []
            for repo_id, link_type in self.link_store.get_repos_for_conversation(conv_id):
                repo = self.repo_store.get_by_id(repo_id)
                if repo:
                    repos.append(f"  - {repo.fqn} ({link_type.value})")

            # Get refs (PRs and issues)
            prs = []
            issues = []
            for ref_id, link_type in self.link_store.get_refs_for_conversation(conv_id):
                ref = self.ref_store.get_by_id(ref_id)
                if ref:
                    entry = f"  - {ref.fqn} ({link_type.value}): {ref.url}"
                    if ref.ref_type.value == "pr":
                        prs.append(entry)
                    elif ref.ref_type.value == "issue":
                        issues.append(entry)

            # Format output
            parts = []
            if repos:
                parts.append("Repositories:\n" + "\n".join(repos))
            if prs:
                parts.append("Pull Requests:\n" + "\n".join(prs))
            if issues:
                parts.append("Issues:\n" + "\n".join(issues))

            if not parts:
                summary = "No git references found for this conversation."
            else:
                summary = "\n\n".join(parts)

            return GetRefsObservation(
                conversation_id=conv_id,
                refs_summary=summary,
            )

        except Exception as e:
            return GetRefsObservation(
                conversation_id=action.conversation_id,
                refs_summary="",
                error=str(e),
            )


class GetRefsTool(ToolDefinition[GetRefsAction, GetRefsObservation]):
    """Tool for getting git references (PRs, issues, repos) for a conversation."""

    @classmethod
    def create(
        cls,
        conv_state: Any = None,
        link_store: "LinkStore | None" = None,
        ref_store: "ReferenceStore | None" = None,
        repo_store: "RepoStore | None" = None,
        **params,
    ) -> Sequence[Self]:
        if link_store is None:
            raise ValueError("link_store is required for GetRefsTool")
        if ref_store is None:
            raise ValueError("ref_store is required for GetRefsTool")
        if repo_store is None:
            raise ValueError("repo_store is required for GetRefsTool")

        return [
            cls(
                action_type=GetRefsAction,
                observation_type=GetRefsObservation,
                description=(
                    "Get git references (PRs, issues, repositories) for a conversation. "
                    "Use this to find related code changes and issues. "
                    "Provide the conversation ID (first 8 characters are sufficient)."
                ),
                executor=GetRefsExecutor(link_store, ref_store, repo_store),
                annotations=ToolAnnotations(
                    title="get_refs",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]


# ============================================================================
# ListConversations Tool (Issue #160)
# ============================================================================


class ConversationSummary(BaseModel):
    """Compact summary of a conversation, used by ListConversationsObservation.

    Mirrors the minimal shape that ``ohtv gen objs -F json`` emits so the agent
    sees the same "shape" of a conversation that the user would see at the CLI.
    Refs are intentionally NOT included here; the agent can call ``get_refs``
    on any id it wants to investigate further. This keeps each summary at
    ~200 bytes so a 20-row response stays well within the prompt budget.
    """

    id: str = Field(description="Conversation ID")
    short_id: str = Field(description="First 8 characters of the ID")
    title: str | None = Field(default=None, description="Conversation title")
    source: str = Field(description="'local' or 'cloud'")
    created_at: str | None = Field(
        default=None, description="ISO 8601 timestamp when the conversation was created"
    )
    duration_seconds: int | None = Field(
        default=None, description="Duration between created_at and updated_at, in seconds"
    )
    event_count: int | None = Field(default=None, description="Total events in the conversation")
    selected_repository: str | None = Field(
        default=None, description="Repository the conversation was scoped to, if any"
    )
    goal: str | None = Field(
        default=None,
        description=(
            "Cached 'gen objs' brief-variant goal. None when no cached analysis "
            "exists for this conversation (cache miss). The agent may call "
            "show_conversation to inspect details on cache miss."
        ),
    )
    labels: dict[str, str] | None = Field(default=None, description="Cloud-side labels (key=value)")


class ListConversationsAction(Action):
    """Action to enumerate conversations by metadata filters.

    Mirrors the filter surface of ``ohtv gen objs`` multi-conversation mode
    (since/until/day/week/repo/pr/action/label/include-sub-conversations).
    """

    since: str | None = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) or relative ('7d', '2w', '1m', 'today', 'yesterday')",
    )
    until: str | None = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) or relative",
    )
    day: str | None = Field(
        default=None,
        description=(
            "A specific day: 'YYYY-MM-DD' or 'today'. May also be a small integer "
            "for an N-day lookback (e.g. '3' = today + 2 days back)."
        ),
    )
    week: str | None = Field(
        default=None,
        description=(
            "A specific week reference: 'today' (this week) or a small integer for "
            "an N-week lookback (e.g. '2' = this week + last week)."
        ),
    )
    repo: str | None = Field(
        default=None,
        description="Repo filter: full URL, owner/repo, or short name",
    )
    pr: str | None = Field(
        default=None,
        description="PR filter: URL, owner/repo#N, or repo#N",
    )
    action: str | None = Field(
        default=None,
        description="Action filter, e.g. 'pushed', 'open-pr', 'merged'",
    )
    label: str | None = Field(
        default=None,
        description="Label filter in 'key=value' form",
    )
    limit: int = Field(
        default=20,
        description="Maximum number of conversations to return (capped at 50)",
    )
    include_sub_conversations: bool = Field(
        default=False,
        description=(
            "Include agent-delegated sub-conversations. Default False matches the "
            "CLI's post-#125 roots-only behavior."
        ),
    )

    @property
    def visualize(self) -> Text:
        content = Text()
        content.append("List conversations", style="bold blue")
        parts: list[str] = []
        for name in ("since", "until", "day", "week", "repo", "pr", "action", "label"):
            value = getattr(self, name)
            if value:
                parts.append(f"{name}={value}")
        if self.include_sub_conversations:
            parts.append("include_sub_conversations=True")
        if parts:
            content.append(" (", style="dim")
            content.append(", ".join(parts), style="dim")
            content.append(")", style="dim")
        return content


class ListConversationsObservation(Observation):
    """Observation returned by the ``list_conversations`` tool."""

    total_matching: int = Field(
        description="Ground-truth count of conversations matching the filters"
    )
    returned: list[ConversationSummary] = Field(
        default_factory=list,
        description="List of conversation summaries, capped at the requested limit",
    )
    truncated: bool = Field(
        default=False, description="True when total_matching > len(returned)"
    )
    filters_applied: dict[str, Any] = Field(
        default_factory=dict,
        description="Echo of the resolved filter parameters",
    )
    error: str | None = Field(default=None, description="Error message if any")

    def to_text(self) -> str:
        """Return a compact text representation for LLM context."""
        if self.error:
            return f"Error: {self.error}"
        if self.total_matching == 0:
            return (
                f"No conversations match the filters. "
                f"filters_applied={self.filters_applied}"
            )

        lines = [
            f"Found {self.total_matching} matching conversation(s); "
            f"returning {len(self.returned)}"
            f"{' (truncated)' if self.truncated else ''}.",
        ]
        for summary in self.returned:
            parts = [
                f"- [{summary.short_id}] ({summary.source})",
            ]
            if summary.created_at:
                parts.append(summary.created_at)
            if summary.duration_seconds is not None:
                parts.append(f"{summary.duration_seconds}s")
            if summary.event_count is not None:
                parts.append(f"{summary.event_count} events")
            if summary.selected_repository:
                parts.append(summary.selected_repository)
            if summary.labels:
                labels_str = ",".join(f"{k}={v}" for k, v in sorted(summary.labels.items()))
                parts.append(f"labels={labels_str}")
            lines.append(" | ".join(parts))
            if summary.title:
                lines.append(f"    title: {summary.title}")
            if summary.goal:
                # Single-line, truncated goal preview
                goal = summary.goal.replace("\n", " ").strip()
                if len(goal) > 200:
                    goal = goal[:197] + "..."
                lines.append(f"    goal:  {goal}")
            else:
                lines.append("    goal:  (no cached analysis)")
        return "\n".join(lines)

    @property
    def visualize(self) -> Text:
        content = Text()
        if self.error:
            content.append(f"Error: {self.error}", style="red")
            return content
        content.append(
            f"{self.total_matching} matching, showing {len(self.returned)}"
            f"{' (truncated)' if self.truncated else ''}\n",
            style="dim",
        )
        for summary in self.returned[:10]:
            line = f"  [{summary.short_id}] {summary.title or '(no title)'}"
            content.append(line + "\n")
        if len(self.returned) > 10:
            content.append(f"  ... and {len(self.returned) - 10} more\n", style="dim")
        return content


# Hard cap on the limit value the agent can request. Keeps the observation
# under a few kilobytes even when the agent asks for "all" of something.
LIST_CONVERSATIONS_MAX_LIMIT = 50

# Cache lookup defaults — must match ``gen objs`` multi-conv mode.
LIST_CONVERSATIONS_CACHE_CONTEXT = "minimal"
LIST_CONVERSATIONS_CACHE_DETAIL = "brief"
LIST_CONVERSATIONS_CACHE_ASSESS = False


# Sentinel used for sorting conversations with no created_at field.
# Tz-aware so it can be compared against tz-aware created_at values.
_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def _normalize_for_sort(dt: datetime | None) -> datetime:
    """Coerce a datetime to a tz-aware value usable as a sort key.

    Naive datetimes (e.g. from local-CLI conversations) are interpreted
    as UTC; this matches the convention the rest of the codebase uses
    when bucketing across sources (see AGENTS.md item 29's UTC-bin
    caveat).
    """
    if dt is None:
        return _MIN_DATETIME
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _find_conv_dir_for_executor(config: "Config", conv_id: str):
    """Lazy wrapper around ``cli._find_conversation_dir``.

    Kept as a module-level helper so tests can patch it independently of the
    full cli import.
    """
    from ohtv.cli import _find_conversation_dir

    return _find_conversation_dir(config, conv_id)


class ListConversationsExecutor(
    ToolExecutor[ListConversationsAction, ListConversationsObservation]
):
    """Executor that delegates to ``cli._apply_conversation_filters`` and
    pulls cached brief ``gen objs`` analyses from the analysis cache.

    Reads only — never triggers LLM analysis on cache miss. On a cache miss
    the conversation is still returned, but with ``goal=None`` so the agent
    knows to use ``show_conversation`` if it wants the trajectory.
    """

    def __init__(self, config: "Config", conv_store: "ConversationStore"):
        self.config = config
        self.conv_store = conv_store

    def _resolve_dates(
        self, action: ListConversationsAction
    ) -> tuple[datetime | None, datetime | None]:
        """Resolve since/until/day/week to (since, until) datetimes.

        ``since`` / ``until`` accept the full ``parse_date_filter`` surface
        (ISO date, '7d'/'2w'/'1m', 'today'/'yesterday') so the agent can
        say "since 7d" without needing to compute the absolute date itself.
        ``day`` / ``week`` are handled by the cli helper, which understands
        numeric lookbacks (e.g. ``week='2'`` = last 2 weeks).
        """
        from ohtv.cli import _parse_date_filters
        from ohtv.filters import parse_date_filter

        since: datetime | None = None
        until: datetime | None = None
        if action.since:
            since = parse_date_filter(action.since)
            if since is None:
                raise ValueError(f"Could not parse 'since' value: {action.since!r}")
        if action.until:
            until = parse_date_filter(action.until)
            if until is None:
                raise ValueError(f"Could not parse 'until' value: {action.until!r}")

        # Delegate day/week handling to the cli helper. since/until are
        # already resolved above; pass None so the helper only fills in
        # what's still missing (it preserves an existing value with
        # ``since = since or day_start``).
        if action.day is not None or action.week is not None:
            day_since, day_until = _parse_date_filters(
                None, None, action.day, action.week
            )
            if since is None:
                since = day_since
            if until is None:
                until = day_until

        return since, until

    def _lookup_cached_goal(self, conv_id: str) -> str | None:
        """Look up the brief ``gen objs`` goal in the analysis cache.

        Returns None on any cache miss; never raises.
        """
        from ohtv.analysis.cache import load_all_analyses, make_cache_key

        try:
            result = _find_conv_dir_for_executor(self.config, conv_id)
            if result is None:
                return None
            conv_dir, _ = result
            analyses = load_all_analyses(conv_dir)
            if not analyses:
                return None
            cache_key = make_cache_key(
                context=LIST_CONVERSATIONS_CACHE_CONTEXT,
                detail=LIST_CONVERSATIONS_CACHE_DETAIL,
                assess=LIST_CONVERSATIONS_CACHE_ASSESS,
            )
            entry = analyses.get(cache_key)
            if entry is None:
                # Fall back: return any cached goal so the agent still gets
                # *something* useful when only e.g. the `standard` variant
                # has been warmed. The brief variant is preferred when
                # available because that's what the multi-conv CLI shows.
                entry = next(iter(analyses.values()), None)
            if not entry:
                return None
            goal = entry.get("goal")
            if goal:
                return goal
            # 'detailed' variant uses summary / primary_objectives instead
            summary = entry.get("summary")
            if summary:
                return summary
            primary = entry.get("primary_objectives") or []
            if primary and isinstance(primary, list):
                first = primary[0]
                if isinstance(first, dict):
                    return first.get("description")
            return None
        except Exception:  # noqa: BLE001 - cache lookup is best-effort
            return None

    def _build_summary(self, conv: Any) -> ConversationSummary:
        """Convert a ``ConversationInfo`` into a ``ConversationSummary``."""
        duration_seconds: int | None = None
        if conv.duration is not None:
            duration_seconds = int(conv.duration.total_seconds())
        created_at_str: str | None = None
        if conv.created_at is not None:
            created_at_str = conv.created_at.isoformat()
        return ConversationSummary(
            id=conv.id,
            short_id=conv.short_id,
            title=conv.title,
            source=conv.source,
            created_at=created_at_str,
            duration_seconds=duration_seconds,
            event_count=conv.event_count,
            selected_repository=conv.selected_repository,
            goal=self._lookup_cached_goal(conv.id),
            labels=conv.labels,
        )

    def __call__(
        self,
        action: ListConversationsAction,
        conversation: "LocalConversation | None" = None,
    ) -> ListConversationsObservation:
        # Reject obviously-bad limits up front so we never echo nonsense
        # back to the agent.
        requested_limit = max(1, min(action.limit, LIST_CONVERSATIONS_MAX_LIMIT))

        try:
            since, until = self._resolve_dates(action)
        except Exception as e:  # noqa: BLE001
            return ListConversationsObservation(
                total_matching=0,
                returned=[],
                truncated=False,
                filters_applied={},
                error=f"Failed to parse date filters: {e}",
            )

        filters_applied: dict[str, Any] = {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "repo": action.repo,
            "pr": action.pr,
            "action": action.action,
            "label": action.label,
            "limit": requested_limit,
            "include_sub_conversations": action.include_sub_conversations,
        }

        try:
            from ohtv.cli import _apply_conversation_filters

            filter_result = _apply_conversation_filters(
                self.config,
                since=since,
                until=until,
                pr_filter=action.pr,
                repo_filter=action.repo,
                action_filter=action.action,
                label_filter=action.label,
                include_sub_conversations=action.include_sub_conversations,
            )
        except Exception as e:  # noqa: BLE001
            return ListConversationsObservation(
                total_matching=0,
                returned=[],
                truncated=False,
                filters_applied=filters_applied,
                error=f"Filter resolution failed: {e}",
            )

        conversations = filter_result.conversations
        # Sort by created_at descending (newest first) for stable, useful order.
        # ``_normalize_for_sort`` makes naive and tz-aware created_at values
        # comparable without raising on mixed sources (local CLI vs cloud).
        conversations = sorted(
            conversations,
            key=lambda c: _normalize_for_sort(c.created_at),
            reverse=True,
        )
        total_matching = len(conversations)
        returned_convs = conversations[:requested_limit]

        summaries = [self._build_summary(c) for c in returned_convs]

        return ListConversationsObservation(
            total_matching=total_matching,
            returned=summaries,
            truncated=total_matching > len(summaries),
            filters_applied=filters_applied,
        )


class ListConversationsTool(
    ToolDefinition[ListConversationsAction, ListConversationsObservation]
):
    """Tool for enumerating conversations by metadata filters.

    Use this when the user's question is anchored to time
    ("yesterday", "last week"), is enumerative ("every conv that touched X"),
    or needs an aggregate ("how many PRs did we land in May?"). Pair with
    ``show_conversation``, ``get_refs``, or ``search_conversations`` for
    deeper investigation of individual results.
    """

    @classmethod
    def create(
        cls,
        conv_state: Any = None,
        config: "Config | None" = None,
        conv_store: "ConversationStore | None" = None,
        **params,
    ) -> Sequence[Self]:
        if config is None:
            raise ValueError("config is required for ListConversationsTool")
        if conv_store is None:
            raise ValueError("conv_store is required for ListConversationsTool")

        return [
            cls(
                action_type=ListConversationsAction,
                observation_type=ListConversationsObservation,
                description=(
                    "Enumerate conversations matching metadata filters "
                    "(date range, repo, PR, action, label). Prefer this over "
                    "search_conversations for temporal ('yesterday', 'last week') "
                    "or enumerative ('every conv that touched repo X') questions, "
                    "and for verifying negatives ('did we work on Y at all?'). "
                    "Returns at most 50 conversations; narrow filters if "
                    "total_matching is much larger than what was returned."
                ),
                executor=ListConversationsExecutor(config, conv_store),
                annotations=ToolAnnotations(
                    title="list_conversations",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]

