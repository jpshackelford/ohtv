"""Multi-turn investigation agent for RAG follow-up.

This module provides an agent that can perform multi-turn investigation
to answer questions about conversation history more thoroughly than
single-turn RAG.
"""

import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr
from rich.console import Console

# Suppress openhands-sdk banner before import
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from openhands.sdk import Agent, LocalConversation
from openhands.sdk.llm import LLM
from openhands.sdk.tool import FinishTool, ThinkTool, ToolDefinition

from ohtv.analysis.agent_tools import (
    GetRefsTool,
    SearchConversationsTool,
    ShowConversationTool,
)
from ohtv.analysis.rag import RAGAnswer

if TYPE_CHECKING:
    from ohtv.db.stores import (
        ConversationStore,
        EmbeddingStore,
        LinkStore,
        ReferenceStore,
        RepoStore,
    )

log = logging.getLogger("ohtv")

DEFAULT_MAX_ITERATIONS = 5


@dataclass
class InvestigationResult:
    """Result of a multi-turn investigation."""

    final_answer: str
    initial_answer: str
    investigation_steps: list[str]
    conversations_examined: set[str]
    total_iterations: int
    total_cost: float
    total_tokens: int
    model: str
    elapsed_seconds: float
    finished_normally: bool = True
    error: str | None = None


def get_investigation_system_prompt() -> str:
    """Get the system prompt for the investigation agent."""
    return """You are an investigation agent that helps answer questions about software development conversations and coding sessions.

You have been given an initial answer to a question, along with source citations. Your job is to:

1. **Assess the initial answer**: Is it complete? Are there gaps or areas that need more detail?
2. **Investigate if needed**: Use your tools to gather more information:
   - `show_conversation`: Load the full transcript of a specific conversation to get more detail
   - `search_conversations`: Find additional related conversations that might help
   - `get_refs`: Get git references (PRs, issues, repos) for a conversation
3. **Synthesize findings**: Produce a final comprehensive answer with citations

## Guidelines

- Start by reviewing the initial answer and identifying what additional information would be helpful
- Use the `think` tool to reason about what to investigate next
- Be efficient - don't examine conversations that won't add new information
- When you have a satisfactory answer, use the `finish` tool with your final response
- Include conversation IDs in your citations (e.g., "In conversation abc123...")
- If the initial answer is already complete and accurate, say so and finish quickly

## When to investigate more

- The initial answer mentions conversations but lacks detail
- The question asks for specifics that aren't in the initial answer
- There are multiple relevant conversations and they might have conflicting or complementary information
- The answer would benefit from examining actual code changes or PR details

## When to finish quickly

- The initial answer fully addresses the question
- No additional context would significantly improve the answer
- The question is simple and the initial answer is sufficient"""


def format_initial_context(question: str, rag_answer: RAGAnswer) -> str:
    """Format the initial RAG answer as context for the agent."""
    parts = [
        f"## Question\n{question}",
        f"\n## Initial Answer\n{rag_answer.answer}",
        f"\n## Sources ({len(rag_answer.source_conversation_ids)} conversations)",
    ]

    # Add source information
    for chunk in rag_answer.context_chunks:
        source = chunk.source
        if source:
            date_str = source.created_at.strftime("%Y-%m-%d") if source.created_at else "unknown"
            parts.append(f"\n### Conversation: {chunk.conversation_id[:8]} ({date_str})")
            parts.append(f"Title: {source.title}")
            if source.summary:
                parts.append(f"Summary: {source.summary}")
            if source.prs:
                pr_list = ", ".join(pr.fqn for pr in source.prs[:3])
                parts.append(f"PRs: {pr_list}")
            if source.repos:
                repo_list = ", ".join(r.fqn for r in source.repos[:3])
                parts.append(f"Repos: {repo_list}")
        else:
            parts.append(f"\n### Conversation: {chunk.conversation_id[:8]}")
            parts.append(f"Title: {chunk.title}")

    parts.append("\n## Your Task")
    parts.append(
        "Review the initial answer and sources above. "
        "Determine if additional investigation is needed to fully answer the question. "
        "Use the available tools to gather more information if helpful, "
        "then provide a final comprehensive answer."
    )

    return "\n".join(parts)


class InvestigationAgent:
    """Multi-turn investigation agent for RAG follow-up.

    This agent takes an initial RAG answer and can use tools to
    investigate further, examining specific conversations and
    searching for additional context.
    """

    def __init__(
        self,
        model: str,
        embed_store: "EmbeddingStore",
        conv_store: "ConversationStore",
        link_store: "LinkStore | None" = None,
        ref_store: "ReferenceStore | None" = None,
        repo_store: "RepoStore | None" = None,
        conversation_dirs: list[str] | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        console: Console | None = None,
    ):
        """Initialize the investigation agent.

        Args:
            model: LLM model for the agent
            embed_store: EmbeddingStore for searching conversations
            conv_store: ConversationStore for conversation metadata
            link_store: LinkStore for conversation-ref relationships
            ref_store: ReferenceStore for ref details
            repo_store: RepoStore for repository details
            conversation_dirs: List of directories containing conversations
            max_iterations: Maximum number of agent iterations
            console: Rich console for output (optional)
        """
        self.model = model
        self.embed_store = embed_store
        self.conv_store = conv_store
        self.link_store = link_store
        self.ref_store = ref_store
        self.repo_store = repo_store
        self.conversation_dirs = conversation_dirs or []
        self.max_iterations = max_iterations
        self.console = console or Console()

        # Verify API key is available
        api_key = os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY environment variable not set. "
                "This is required for the investigation agent."
            )

    def _create_tools(self) -> list[ToolDefinition]:
        """Create the tools available to the investigation agent."""
        tools = []

        # ShowConversation tool
        show_tools = ShowConversationTool.create(
            conv_store=self.conv_store,
            conversation_dirs=self.conversation_dirs,
        )
        tools.extend(show_tools)

        # SearchConversations tool
        search_tools = SearchConversationsTool.create(
            embed_store=self.embed_store,
            conv_store=self.conv_store,
        )
        tools.extend(search_tools)

        # GetRefs tool (only if ref stores are available)
        if self.link_store and self.ref_store and self.repo_store:
            ref_tools = GetRefsTool.create(
                link_store=self.link_store,
                ref_store=self.ref_store,
                repo_store=self.repo_store,
            )
            tools.extend(ref_tools)

        return tools

    def investigate(
        self,
        question: str,
        initial_answer: RAGAnswer,
    ) -> InvestigationResult:
        """Run multi-turn investigation starting from initial RAG answer.

        Args:
            question: The original question
            initial_answer: The initial RAG answer with context

        Returns:
            InvestigationResult with final answer and metrics
        """
        import time

        start_time = time.time()

        # Create LLM instance
        api_key = os.environ.get("LLM_API_KEY")
        llm = LLM(
            model=self.model,
            api_key=SecretStr(api_key) if api_key else None,
            base_url=os.environ.get("LLM_BASE_URL"),
        )

        # Create agent with custom tools
        custom_tools = self._create_tools()
        agent = Agent(
            llm=llm,
            tools=[],  # We'll pass tools differently
            include_default_tools=["think", "finish"],  # Include built-in tools
        )

        # Create a temporary workspace for the conversation
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create conversation with custom tools
            conversation = LocalConversation(
                agent=agent,
                workspace=temp_dir,
                max_iteration_per_run=self.max_iterations,
                visualizer=None,  # Disable visualizer for non-interactive mode
            )

            # Register custom tools with the conversation's tool registry
            for tool in custom_tools:
                # Tools need to be added to the agent's tool list
                pass  # Tools are already in the agent

            # Actually, we need to pass tools to the Agent constructor
            # Let me refactor this

        # Re-create with proper tool setup
        agent = Agent(
            llm=llm,
            tools=[],
            include_default_tools=["think", "finish"],
        )

        # Add custom tools to the agent's tools list
        # The Agent expects Tool specs, not ToolDefinition instances
        # We need to use a different approach - use the ToolDefinition directly

        # Track investigation state
        investigation_steps = []
        conversations_examined = set()
        total_tokens = 0
        total_cost = 0.0
        final_answer = ""
        finished_normally = False
        error = None

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Build the initial message
                initial_context = format_initial_context(question, initial_answer)

                # Create a simpler approach using direct LLM calls with tools
                result = self._run_investigation_loop(
                    llm=llm,
                    initial_context=initial_context,
                    custom_tools=custom_tools,
                    investigation_steps=investigation_steps,
                    conversations_examined=conversations_examined,
                )

                final_answer = result["answer"]
                total_tokens = result["total_tokens"]
                total_cost = result["total_cost"]
                finished_normally = result["finished"]

        except Exception as e:
            log.exception("Investigation failed")
            error = str(e)
            final_answer = initial_answer.answer  # Fall back to initial answer

        elapsed = time.time() - start_time

        return InvestigationResult(
            final_answer=final_answer,
            initial_answer=initial_answer.answer,
            investigation_steps=investigation_steps,
            conversations_examined=conversations_examined,
            total_iterations=len(investigation_steps),
            total_cost=total_cost,
            total_tokens=total_tokens,
            model=self.model,
            elapsed_seconds=elapsed,
            finished_normally=finished_normally,
            error=error,
        )

    def _run_investigation_loop(
        self,
        llm: LLM,
        initial_context: str,
        custom_tools: list[ToolDefinition],
        investigation_steps: list[str],
        conversations_examined: set[str],
    ) -> dict:
        """Run the investigation loop using direct LLM calls with tools.

        This is a simpler approach than using the full Agent/LocalConversation
        infrastructure, which is better suited for autonomous agent tasks.
        """
        from openhands.sdk.llm.message import Message

        # Build tool definitions for the LLM
        tool_definitions = []
        tool_map = {}

        # Add custom tools
        for tool in custom_tools:
            tool_definitions.append(tool.to_openai_tool())
            tool_map[tool.name] = tool

        # Add finish tool manually
        finish_tools = FinishTool.create()
        for ft in finish_tools:
            tool_definitions.append(ft.to_openai_tool())
            tool_map[ft.name] = ft

        # Add think tool manually
        think_tools = ThinkTool.create()
        for tt in think_tools:
            tool_definitions.append(tt.to_openai_tool())
            tool_map[tt.name] = tt

        # Initialize conversation
        messages = [
            Message(role="system", content=get_investigation_system_prompt()),
            Message(role="user", content=initial_context),
        ]

        total_tokens = 0
        total_cost = 0.0
        finished = False
        final_answer = ""
        iteration = 0

        while not finished and iteration < self.max_iterations:
            iteration += 1
            self.console.print(f"[dim]Investigation step {iteration}...[/dim]")

            try:
                # Call LLM with tools
                response = llm.completion(messages, tools=tool_definitions)

                # Track metrics
                if response.metrics:
                    if response.metrics.accumulated_token_usage:
                        usage = response.metrics.accumulated_token_usage
                        total_tokens += usage.prompt_tokens + usage.completion_tokens
                    total_cost += response.metrics.accumulated_cost or 0.0

                # Process response
                message = response.message
                tool_calls = message.tool_calls or []

                if not tool_calls:
                    # No tool calls - extract text response as final answer
                    if message.content:
                        text_parts = []
                        for part in message.content:
                            if hasattr(part, 'text') and part.text:
                                text_parts.append(part.text)
                        if text_parts:
                            final_answer = "".join(text_parts)
                            finished = True
                            investigation_steps.append(f"Finished with direct response")
                    break

                # Process tool calls
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    arguments = tool_call.function.arguments

                    # Parse arguments (might be string or dict)
                    if isinstance(arguments, str):
                        import json
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                    investigation_steps.append(f"Called {tool_name}: {arguments}")

                    # Handle finish tool
                    if tool_name == "finish":
                        final_answer = arguments.get("message", "")
                        finished = True
                        break

                    # Handle think tool
                    if tool_name == "think":
                        thought = arguments.get("thought", "")
                        investigation_steps.append(f"Thinking: {thought[:100]}...")
                        # Add tool result to messages
                        messages.append(Message(
                            role="assistant",
                            content=None,
                            tool_calls=[tool_call],
                        ))
                        messages.append(Message(
                            role="tool",
                            content=f"Thought recorded: {thought}",
                            tool_call_id=tool_call.id,
                        ))
                        continue

                    # Handle custom tools
                    tool = tool_map.get(tool_name)
                    if tool and tool.executor:
                        try:
                            # Create action from arguments
                            action = tool.action_from_arguments(arguments)
                            observation = tool(action)

                            # Track conversations examined
                            if tool_name == "show_conversation" and hasattr(observation, "conversation_id"):
                                conversations_examined.add(observation.conversation_id)

                            # Format observation for message
                            if hasattr(observation, "transcript"):
                                result_text = observation.transcript or observation.error or "No result"
                            elif hasattr(observation, "results"):
                                result_text = observation.results or observation.error or "No result"
                            elif hasattr(observation, "refs_summary"):
                                result_text = observation.refs_summary or observation.error or "No result"
                            else:
                                result_text = str(observation)

                            # Truncate if too long
                            if len(result_text) > 4000:
                                result_text = result_text[:4000] + "\n... [truncated]"

                        except Exception as e:
                            result_text = f"Error executing tool: {e}"

                        # Add tool result to messages
                        messages.append(Message(
                            role="assistant",
                            content=None,
                            tool_calls=[tool_call],
                        ))
                        messages.append(Message(
                            role="tool",
                            content=result_text,
                            tool_call_id=tool_call.id,
                        ))

                if finished:
                    break

            except Exception as e:
                log.exception("Error in investigation step")
                investigation_steps.append(f"Error: {e}")
                break

        if not final_answer and not finished:
            # If we didn't finish normally, provide a summary
            final_answer = (
                "Investigation reached iteration limit without a final answer. "
                "Please review the investigation steps for partial findings."
            )

        return {
            "answer": final_answer,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "finished": finished,
        }
