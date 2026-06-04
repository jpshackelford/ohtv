"""Prompt-cookbook investigation agent for ``ohtv ask --agent`` (Issue #161).

Side-by-side companion to :mod:`ohtv.analysis.investigator`. Where the
legacy investigator exposes three custom :class:`ToolDefinition`\\ s,
this one exposes a single ``run_ohtv`` tool that invokes the ``ohtv``
CLI in-process through :mod:`ohtv.analysis.ohtv_runner`. The behaviour
contract — same :class:`InvestigationResult` shape, same cost/token
tracking, same RAG-answer scaffold — is identical so downstream
telemetry (Issue #162) can stamp either path uniformly.

The cookbook prompt lives at module scope as :data:`COOKBOOK_PROMPT` so
it can be snapshot-tested; drift is caught at PR review.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from typing import Any, Self

from pydantic import Field, SecretStr
from rich.console import Console
from rich.text import Text

# Suppress openhands-sdk banner before import
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from openhands.sdk.llm import LLM
from openhands.sdk.tool import FinishTool, ThinkTool, ToolDefinition
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolExecutor

from ohtv.analysis.investigator import (
    DEFAULT_MAX_ITERATIONS,
    InvestigationResult,
    format_initial_context,
)
from ohtv.analysis.ohtv_runner import (
    ALLOWED_SUBCOMMANDS,
    CliOutput,
    extract_conversation_ids_from_argv,
    run_ohtv,
)
from ohtv.analysis.rag import RAGAnswer

log = logging.getLogger("ohtv")


# ============================================================================
# Cookbook system prompt
# ============================================================================

# Issue #161 §"System prompt cookbook". The exact wording is unit-tested
# via a string snapshot so behavioural drift is caught at PR review.
COOKBOOK_PROMPT = """You investigate questions about software-development conversations using the local `ohtv` CLI.

You have one investigation tool: `run_ohtv(argv)`. You may only invoke the subcommands listed below; anything else will be rejected with an explanation, and you should retry with an allowed command.

Cookbook — the commands you will use most often:

- Examine a conversation:
    show <id> --messages --action-summaries -n 50
    show <id> -A           # everything, for deep dives
    show <id> -F json      # if you want structured output

- Find related conversations:
    search "<query>" -n 5
    search "<query>" -F json --since 14d

- Browse by metadata (use this for "yesterday", "last week",
  "every conv that...", "how many..."):
    list -F json -S 7d
    gen objs -W 1 -F json
    gen objs --repo <name> --week -F json
    gen objs --pr <owner/repo#N> -F json

- Get PRs/issues/repos for a conversation:
    refs <id>
    refs <id> -F json

- Check for agent/LLM errors:
    errors <id>

Guidelines:
1. Start by reading the initial answer and sources you were given.
2. Use -F json whenever you want compact structured output.
3. Prefer narrow queries — short conversation IDs (8 chars) work
   everywhere in ohtv.
4. Prefer `list` / `gen objs` (browse) for temporal or
   enumerative questions; `search` for conceptual ones.
5. The `gen objs` command runs in cache-only mode automatically when
   invoked through this tool; conversations without a cached analysis
   will return `goal: null`. Treat that as "no analysis yet", not "no
   goal".
6. Stop when you can answer; call `finish` with the synthesized
   answer (cite conversation IDs).
"""


def get_investigation_cli_system_prompt() -> str:
    """Return the cookbook system prompt for the CLI-mode investigator."""
    return COOKBOOK_PROMPT


# ============================================================================
# run_ohtv tool definition (single tool — the contract)
# ============================================================================


class RunOhtvAction(Action):
    """Invoke the ``ohtv`` CLI in-process with the given argv."""

    argv: list[str] = Field(
        description=(
            "Argv list (excluding the `ohtv` program name). "
            "Example: [\"show\", \"abc123\", \"-F\", \"json\"]. "
            f"Only these subcommand prefixes are allowed: "
            f"{', '.join(' '.join(p) for p in ALLOWED_SUBCOMMANDS)}."
        )
    )

    @property
    def visualize(self) -> Text:
        content = Text()
        content.append("$ ohtv ", style="dim")
        content.append(" ".join(self.argv))
        return content


class RunOhtvObservation(Observation):
    """Captured stdout/stderr/exit code from an ``ohtv`` invocation."""

    argv: list[str] = Field(description="Effective argv (after any runner injections)")
    stdout: str = Field(default="", description="Captured stdout")
    stderr: str = Field(default="", description="Captured stderr")
    exit_code: int = Field(default=0, description="Click exit code")
    elapsed_seconds: float = Field(default=0.0, description="Wall-clock duration")
    rejected: bool = Field(default=False, description="True if the runner refused the argv")
    rejection_reason: str | None = Field(default=None, description="Short reason code for rejection")
    error: str | None = Field(default=None, description="Executor-side error")

    def to_text(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        # Defer to CliOutput.to_observation by reconstructing
        out = CliOutput(
            argv=self.argv,
            stdout=self.stdout,
            stderr=self.stderr,
            exit_code=self.exit_code,
            elapsed_seconds=self.elapsed_seconds,
            rejected=self.rejected,
            rejection_reason=self.rejection_reason,
        )
        return out.to_observation()

    @property
    def visualize(self) -> Text:
        text = Text()
        if self.rejected:
            text.append("REJECTED: ", style="red")
            text.append(" ".join(self.argv))
            return text
        text.append(f"$ ohtv {' '.join(self.argv)} → exit={self.exit_code}", style="dim")
        return text


class RunOhtvExecutor(ToolExecutor[RunOhtvAction, RunOhtvObservation]):
    """Bridge between the SDK tool framework and :func:`run_ohtv`."""

    def __init__(self, *, timeout_s: float = 30.0):
        self.timeout_s = timeout_s

    def __call__(self, action: RunOhtvAction) -> RunOhtvObservation:
        try:
            out = run_ohtv(action.argv, timeout_s=self.timeout_s)
            return RunOhtvObservation(
                argv=out.argv,
                stdout=out.stdout,
                stderr=out.stderr,
                exit_code=out.exit_code,
                elapsed_seconds=out.elapsed_seconds,
                rejected=out.rejected,
                rejection_reason=out.rejection_reason,
            )
        except Exception as e:  # noqa: BLE001 — surface to LLM
            log.exception("run_ohtv failed for argv=%s", action.argv)
            return RunOhtvObservation(
                argv=action.argv,
                error=f"{type(e).__name__}: {e}",
                exit_code=1,
            )


class RunOhtvTool(ToolDefinition[RunOhtvAction, RunOhtvObservation]):
    """``run_ohtv`` tool definition — the only investigation tool in CLI mode."""

    @classmethod
    def create(
        cls,
        conv_state: Any = None,
        timeout_s: float = 30.0,
        **params: Any,
    ) -> Sequence[Self]:
        return [
            cls(
                action_type=RunOhtvAction,
                observation_type=RunOhtvObservation,
                description=(
                    "Run the local `ohtv` CLI in-process. Accepts an argv list "
                    "(no program name, no shell). Only read-side subcommands are "
                    "allowed; the allow-list is enforced and rejections name the "
                    "blocked command so you can retry with a valid one. "
                    "`gen objs` automatically runs cache-only — cache misses "
                    "return `goal: null`, never trigger LLM analysis."
                ),
                executor=RunOhtvExecutor(timeout_s=timeout_s),
                annotations=ToolAnnotations(
                    title="run_ohtv",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]


# ============================================================================
# The investigator
# ============================================================================


class InvestigationAgentCli:
    """Prompt-cookbook investigation agent (Issue #161, ``--agent``).

    Mirrors :class:`ohtv.analysis.investigator.InvestigationAgent`'s public
    surface: same ``investigate(question, rag_answer) -> InvestigationResult``
    signature, same cost/token tracking, identical error handling. The only
    differences are:

    1. One tool (``run_ohtv``) instead of three+ custom tool definitions.
    2. ``InvestigationResult.mode`` is stamped ``"cli"``.
    3. ``conversations_examined`` is populated by parsing 8/32/36-char IDs
       out of argv (the runner doesn't know the conv-store schema; argv
       is the contract).
    """

    def __init__(
        self,
        model: str,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        console: Console | None = None,
        timeout_s: float = 30.0,
        command_count_cap: int | None = None,
    ):
        """Initialize the CLI investigation agent.

        Args:
            model: LLM model name (must match what the LLM env expects).
            max_iterations: Max investigation loop iterations. Default 5
                matches :data:`DEFAULT_MAX_ITERATIONS`.
            console: Optional Rich console for progress chatter. Defaults
                to a fresh ``Console()``.
            timeout_s: Per-``run_ohtv`` soft timeout. Logged-only in v1;
                the session-level cap below provides the hard limit.
            command_count_cap: Per-investigation cap on total run_ohtv
                invocations. Defaults to ``max_iterations * 3`` so a 5-step
                investigation can fan out to 15 commands across multi-tool
                turns. ``None`` re-applies the default.
        """
        self.model = model
        self.max_iterations = max_iterations
        self.console = console or Console()
        self.timeout_s = timeout_s
        self.command_count_cap = (
            command_count_cap if command_count_cap is not None else max_iterations * 3
        )

        # Verify API key is available
        api_key = os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY environment variable not set. "
                "This is required for the investigation agent."
            )

    def _create_tools(self) -> list[ToolDefinition]:
        """Create the tools available to the investigation agent."""
        return list(RunOhtvTool.create(timeout_s=self.timeout_s))

    def investigate(
        self,
        question: str,
        initial_answer: RAGAnswer,
    ) -> InvestigationResult:
        """Run multi-turn investigation starting from initial RAG answer.

        See :class:`InvestigationAgent.investigate` for the shape contract.
        """
        start_time = time.time()
        api_key = os.environ.get("LLM_API_KEY")
        llm = LLM(
            model=self.model,
            api_key=SecretStr(api_key) if api_key else None,
            base_url=os.environ.get("LLM_BASE_URL"),
        )

        custom_tools = self._create_tools()

        investigation_steps: list[str] = []
        conversations_examined: set[str] = set()
        total_tokens = 0
        total_cost = 0.0
        final_answer = ""
        finished_normally = False
        error: str | None = None

        try:
            initial_context = format_initial_context(question, initial_answer)
            loop_result = self._run_investigation_loop(
                llm=llm,
                initial_context=initial_context,
                custom_tools=custom_tools,
                investigation_steps=investigation_steps,
                conversations_examined=conversations_examined,
                question=question,
                initial_answer=initial_answer,
            )
            final_answer = loop_result["answer"]
            total_tokens = loop_result["total_tokens"]
            total_cost = loop_result["total_cost"]
            finished_normally = loop_result["finished"]
        except Exception as e:  # noqa: BLE001
            log.exception("CLI investigation failed")
            error = str(e)
            final_answer = initial_answer.answer

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
            mode="cli",
        )

    # ------------------------------------------------------------------
    # Loop internals
    # ------------------------------------------------------------------

    def _build_tool_map(
        self, custom_tools: list[ToolDefinition]
    ) -> tuple[list[ToolDefinition], dict[str, ToolDefinition]]:
        """Build the tool definitions list + name→tool map.

        Adds ``finish`` and ``think`` alongside the custom tools so the
        agent has a consistent termination signal across both modes.
        """
        tool_definitions: list[ToolDefinition] = []
        tool_map: dict[str, ToolDefinition] = {}

        for tool in custom_tools:
            tool_definitions.append(tool)
            tool_map[tool.name] = tool

        for ft in FinishTool.create():
            tool_definitions.append(ft)
            tool_map[ft.name] = ft

        for tt in ThinkTool.create():
            tool_definitions.append(tt)
            tool_map[tt.name] = tt

        return tool_definitions, tool_map

    def _process_tool_call(
        self,
        tool_call,
        tool_map: dict[str, ToolDefinition],
        conversations_examined: set[str],
    ) -> tuple[str | None, str | None, bool]:
        """Process a tool call.

        Returns ``(result_text, final_answer, is_finished)``.
        """
        import json

        tool_name = tool_call.name
        arguments = tool_call.arguments
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if tool_name == "finish":
            return None, arguments.get("message", ""), True

        if tool_name == "think":
            thought = arguments.get("thought", "")
            return f"Thought recorded: {thought}", None, False

        tool = tool_map.get(tool_name)
        if tool and tool.executor:
            try:
                action = tool.action_from_arguments(arguments)
                observation = tool(action)

                # Track conversation IDs the agent inspected. The runner
                # is read-only, so it's safe to assume every argv that
                # mentions a conv ID has examined it (regardless of exit
                # code — a 404 on `show abc123` still counts as an
                # examination intent).
                if isinstance(observation, RunOhtvObservation):
                    for cid in extract_conversation_ids_from_argv(observation.argv):
                        conversations_examined.add(cid)

                result_text = observation.to_text()
                if len(result_text) > 4000:
                    result_text = result_text[:4000] + "\n... [truncated]"
                return result_text, None, False
            except Exception as e:  # noqa: BLE001
                return f"Error executing tool: {e}", None, False

        return f"Unknown tool: {tool_name}", None, False

    def _add_tool_response(self, messages: list, tool_call, result_text: str) -> None:
        """Append assistant tool-call and tool-result messages."""
        from openhands.sdk.llm.message import Message

        messages.append(Message(role="assistant", content=None, tool_calls=[tool_call]))
        messages.append(
            Message(
                role="tool",
                content=result_text,
                tool_call_id=tool_call.id,
                name=tool_call.name,
            )
        )

    def _extract_final_answer_from_message(self, message) -> str | None:
        """Extract a text response from an LLM message, if present."""
        if not message.content:
            return None
        parts: list[str] = []
        for chunk in message.content:
            if hasattr(chunk, "text") and chunk.text:
                parts.append(chunk.text)
        return "".join(parts) if parts else None

    def _show_tool_progress(self, tool_name: str, arguments: str | dict) -> None:
        """Display a Rich-formatted hint about what the agent is doing."""
        import json

        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {}
        else:
            args = arguments

        if tool_name == "run_ohtv":
            argv = args.get("argv", [])
            if argv:
                preview = " ".join(str(a) for a in argv)[:80]
                self.console.print(f"[dim]$ ohtv {preview}[/dim]")
            else:
                self.console.print("[dim]$ ohtv (empty argv)[/dim]")
        elif tool_name == "think":
            pass  # handled separately
        elif tool_name == "finish":
            self.console.print("[dim]✅ Finalizing answer...[/dim]")
        else:
            self.console.print(f"[dim]🔧 {tool_name}...[/dim]")

    def _synthesize_partial_findings(
        self,
        initial_answer: RAGAnswer,
        conversations_examined: set[str],
    ) -> str:
        """Synthesize a partial answer when the loop hits its caps."""
        parts: list[str] = ["Based on the available information:\n", initial_answer.answer]
        if conversations_examined:
            parts.append(
                f"\n\n**Investigation examined {len(conversations_examined)} additional conversations** "
            )
            parts.append(
                "(IDs: " + ", ".join(sorted(c[:8] for c in conversations_examined)) + ")"
            )
        parts.append(
            "\n\n*Note: Investigation reached iteration / command-count limit. "
            "For more thorough analysis, try increasing --max-steps.*"
        )
        return "".join(parts)

    def _run_investigation_loop(
        self,
        *,
        llm: LLM,
        initial_context: str,
        custom_tools: list[ToolDefinition],
        investigation_steps: list[str],
        conversations_examined: set[str],
        question: str,
        initial_answer: RAGAnswer,
    ) -> dict:
        """Drive the LLM loop until finish, iteration cap, or command cap."""
        from openhands.sdk.llm.message import Message

        tool_definitions, tool_map = self._build_tool_map(custom_tools)

        messages = [
            Message(role="system", content=get_investigation_cli_system_prompt()),
            Message(role="user", content=initial_context),
        ]

        total_tokens = 0
        total_cost = 0.0
        finished = False
        final_answer: str | None = ""
        iteration = 0
        command_count = 0

        while not finished and iteration < self.max_iterations:
            iteration += 1
            try:
                response = llm.completion(messages, tools=tool_definitions)

                if response.metrics:
                    if response.metrics.accumulated_token_usage:
                        usage = response.metrics.accumulated_token_usage
                        total_tokens += usage.prompt_tokens + usage.completion_tokens
                    total_cost += response.metrics.accumulated_cost or 0.0

                message = response.message
                tool_calls = message.tool_calls or []

                if not tool_calls:
                    final_answer = self._extract_final_answer_from_message(message)
                    if final_answer:
                        finished = True
                        investigation_steps.append("Finished with direct response")
                    break

                pending_tool_results = []
                for tool_call in tool_calls:
                    tool_name = tool_call.name

                    # Per-investigation command-count cap (#161 AC).
                    # Counts only run_ohtv invocations — think/finish are
                    # free, since they don't pay any litellm / disk cost.
                    if tool_name == "run_ohtv":
                        if command_count >= self.command_count_cap:
                            cap_msg = (
                                f"Command-count cap reached "
                                f"({self.command_count_cap}). No more run_ohtv "
                                "invocations are permitted; call `finish` with "
                                "what you've learned so far."
                            )
                            investigation_steps.append(cap_msg)
                            pending_tool_results.append((tool_call, cap_msg))
                            continue
                        command_count += 1

                    self._show_tool_progress(tool_name, tool_call.arguments)
                    investigation_steps.append(
                        f"Called {tool_name}: {tool_call.arguments}"
                    )

                    result_text, answer, is_finished = self._process_tool_call(
                        tool_call, tool_map, conversations_examined
                    )

                    if is_finished:
                        final_answer = answer or ""
                        finished = True
                        break

                    if result_text:
                        if tool_name == "think":
                            thought = result_text.replace("Thought recorded: ", "")
                            investigation_steps.append(f"Thinking: {thought[:100]}...")
                            self.console.print(
                                f"[dim italic]💭 {thought[:200]}"
                                f"{'...' if len(thought) > 200 else ''}[/dim italic]"
                            )
                        pending_tool_results.append((tool_call, result_text))

                for tool_call, result_text in pending_tool_results:
                    self._add_tool_response(messages, tool_call, result_text)

                if finished:
                    break

            except Exception as e:  # noqa: BLE001
                log.exception("Error in CLI investigation step")
                investigation_steps.append(f"Error: {e}")
                break

        if not final_answer and not finished:
            final_answer = self._synthesize_partial_findings(
                initial_answer, conversations_examined
            )

        return {
            "answer": final_answer or "",
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "finished": finished,
        }
