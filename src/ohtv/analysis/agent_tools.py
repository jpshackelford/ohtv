"""Custom tools for the investigation agent.

Provides tools that allow the agent to:
1. Load and examine specific conversation trajectories
2. Search for related conversations
3. Get git references (PRs, issues, repos) for conversations
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Self

from pydantic import Field
from rich.text import Text

from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor


if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

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
