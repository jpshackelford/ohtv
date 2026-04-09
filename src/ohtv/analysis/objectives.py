"""Objective extraction and analysis from conversations.

Context Levels (experimentally validated):
- minimal: User messages only (lowest tokens, may lack outcome info)
- default: User messages + finish action (best balance of tokens vs accuracy)
- full: User + agent messages + action summaries (most context, highest tokens)

The 'default' level was determined through experiments comparing different
approaches across short (23 events), medium (60 events), and long (300+ events)
conversations. See experiments/objective_extraction_comparison.py for details.
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ohtv.analysis.cache import (
    AnalysisCacheManager,
    CachedAnalysis,
    compute_content_hash,
    load_events,
)

log = logging.getLogger("ohtv")

# Context level type
ContextLevel = Literal["minimal", "default", "full"]


class ObjectiveStatus(str, Enum):
    """Status of an objective in a conversation.

    We use a decisive, optimistic assessment approach:
    - Assume success unless there's clear evidence of failure
    - Look for negative signals: user frustration, repeated retries,
      explicit errors, user giving up
    - No "partially achieved" - decide achieved or not
    """

    ACHIEVED = "achieved"
    NOT_ACHIEVED = "not_achieved"
    IN_PROGRESS = "in_progress"  # Only for ongoing work with no conclusion


class Objective(BaseModel):
    """A user objective identified in a conversation."""

    description: str
    status: ObjectiveStatus | None = None  # Only present when assess=True
    evidence: str | None = None  # Only present when assess=True
    subordinates: list["Objective"] = []


class ObjectiveAnalysis(CachedAnalysis):
    """Complete objective analysis for a conversation.

    Supports three detail levels:
    - brief: Just 'goal' field (1-2 sentences)
    - standard: goal + primary_outcomes + secondary_outcomes
    - detailed: Full hierarchical objectives with subordinates

    All levels support optional assessment (assess=True) which adds
    status (achieved/not_achieved/in_progress) and evidence.
    """

    context_level: str
    detail_level: str = "brief"
    assess: bool = False

    # Brief/Standard fields
    goal: str | None = None
    status: str | None = None  # For assessed mode
    primary_outcomes: list[str] = []
    secondary_outcomes: list[str] = []

    # Detailed fields (detailed mode)
    primary_objectives: list[Objective] = []
    summary: str | None = None


ANALYSIS_CACHE_FILENAME = "objective_analysis.json"

# Cache manager for objective analysis
_cache_manager = AnalysisCacheManager(ANALYSIS_CACHE_FILENAME, ObjectiveAnalysis)

# Output detail levels
DetailLevel = Literal["brief", "standard", "detailed"]

# Status values for assessment
STATUS_VALUES = "achieved|not_achieved|in_progress"

# =============================================================================
# Prompts without assessment (default)
# =============================================================================

PROMPT_BRIEF = """Analyze this conversation between a user and an AI coding assistant.

In 1-2 sentences, describe the user's goal using imperative mood (e.g., "Add pagination to search results" not "The user wants to add pagination").

Do not assess whether the goal was achieved. Just identify what they want.

Respond with JSON:
{"goal": "1-2 sentence description in imperative mood"}"""

PROMPT_STANDARD = """Analyze this conversation between a user and an AI coding assistant.

Identify:
1. The user's primary goal (1-2 sentences)
2. Primary outcomes or success criteria (3-6 bullets max)
3. Secondary outcomes if any (3-6 bullets max)

Do not assess whether goals were achieved. Just identify what the user wants.

Respond with JSON:
{
  "goal": "1-2 sentence description of the primary goal",
  "primary_outcomes": ["outcome 1", "outcome 2"],
  "secondary_outcomes": ["outcome 1", "outcome 2"]
}"""

# =============================================================================
# Prompts WITH assessment (--assess flag)
#
# Assessment philosophy: Be optimistic and decisive.
# - Assume success unless there's clear evidence of failure
# - Failure signals: user frustration, repeated retry requests, explicit errors,
#   user giving up, negative feedback
# - No "partially achieved" - make a decision
# =============================================================================

PROMPT_BRIEF_ASSESS = """Analyze this conversation between a user and an AI coding assistant.

1. In 1-2 sentences, describe: What outcome does the user hope to achieve?
2. Assess whether the goal was achieved.

ASSESSMENT APPROACH: Be optimistic and decisive.
- Assume SUCCESS unless there is clear evidence of failure
- Failure signals: user frustration, requests to retry followed by giving up,
  explicit errors that weren't resolved, negative feedback
- Do NOT use "partially achieved" - decide achieved or not achieved

Status values:
- achieved: Goal was accomplished (default assumption unless failure signals present)
- not_achieved: Clear evidence of failure (errors, user frustration, giving up)
- in_progress: Conversation ended mid-work with no conclusion

Respond with JSON:
{
  "goal": "1-2 sentence description of what the user wants to accomplish",
  "status": "achieved|not_achieved|in_progress"
}"""

PROMPT_STANDARD_ASSESS = """Analyze this conversation between a user and an AI coding assistant.

Identify:
1. The user's primary goal (1-2 sentences)
2. Primary outcomes or success criteria (3-6 bullets max)
3. Secondary outcomes if any (3-6 bullets max)
4. Overall status of goal achievement

ASSESSMENT APPROACH: Be optimistic and decisive.
- Assume SUCCESS unless there is clear evidence of failure
- Failure signals: user frustration, requests to retry followed by giving up,
  explicit errors that weren't resolved, negative feedback
- Do NOT use "partially achieved" - decide achieved or not achieved

Status values:
- achieved: Goal was accomplished (default assumption unless failure signals present)
- not_achieved: Clear evidence of failure (errors, user frustration, giving up)
- in_progress: Conversation ended mid-work with no conclusion

Respond with JSON:
{
  "goal": "1-2 sentence description of the primary goal",
  "status": "achieved|not_achieved|in_progress",
  "primary_outcomes": ["outcome 1", "outcome 2"],
  "secondary_outcomes": ["outcome 1", "outcome 2"]
}"""

PROMPT_DETAILED = """You are an expert at analyzing software development conversations to identify user objectives.

Given a conversation between a user and an AI coding assistant, identify:
1. PRIMARY OBJECTIVES: The main goals the user is trying to accomplish
2. SUBORDINATE OBJECTIVES: Supporting goals that help achieve the primary ones

Do not assess whether objectives were achieved. Just identify what the user wants to accomplish
and structure them hierarchically.

Respond with a JSON object in this exact format:
{
  "primary_objectives": [
    {
      "description": "Clear description of the objective",
      "subordinates": [
        {
          "description": "Description of subordinate objective",
          "subordinates": []
        }
      ]
    }
  ],
  "summary": "Brief overall summary of what the user was trying to accomplish"
}"""

PROMPT_DETAILED_ASSESS = """You are an expert at analyzing software development conversations to identify user objectives.

Given a conversation between a user and an AI coding assistant, identify:
1. PRIMARY OBJECTIVES: The main goals the user is trying to accomplish
2. SUBORDINATE OBJECTIVES: Supporting goals that help achieve the primary ones

ASSESSMENT APPROACH: Be optimistic and decisive.
- Assume SUCCESS unless there is clear evidence of failure
- Failure signals: user frustration, requests to retry followed by giving up,
  explicit errors that weren't resolved, negative feedback
- Do NOT use "partially achieved" - decide achieved or not achieved

For each objective, assess its status:
- achieved: Objective was accomplished (default assumption unless failure signals present)
- not_achieved: Clear evidence of failure (errors, user frustration, giving up)
- in_progress: Work is ongoing with no conclusion yet

Provide brief evidence from the conversation to support your assessment.

Respond with a JSON object in this exact format:
{
  "primary_objectives": [
    {
      "description": "Clear description of the objective",
      "status": "achieved|not_achieved|in_progress",
      "evidence": "Brief quote or reference from conversation",
      "subordinates": [
        {
          "description": "Description of subordinate objective",
          "status": "status",
          "evidence": "evidence",
          "subordinates": []
        }
      ]
    }
  ],
  "summary": "Brief overall summary of what the user was trying to accomplish"
}"""


# =============================================================================
# Event Content Extraction
# =============================================================================


def extract_message_content(event: dict, include_critic: bool = False) -> str:
    """Extract text content from a message event.

    Args:
        event: The event dictionary
        include_critic: If False (default), exclude critic_result metadata from
            the extracted content. Critic results are internal evaluation data
            that shouldn't influence objective analysis.
    """
    # Note: critic_result is a top-level field in MessageEvents, not part of
    # the message content itself. It contains evaluation scores/metadata.
    # We don't need to explicitly filter it since we only extract from
    # llm_message.content or direct content fields.

    llm_msg = event.get("llm_message", {})
    content = llm_msg.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    if isinstance(content, str):
        return content

    return event.get("content", "") or event.get("message", "")


def extract_action_summary(event: dict) -> str:
    """Extract a brief summary of an action."""
    tool_name = event.get("tool_name", "unknown")
    action = event.get("action", {})

    if tool_name == "terminal":
        cmd = action.get("command", "")[:100]
        return f"[Terminal] {cmd}"
    elif tool_name == "file_editor":
        path = action.get("path", "")
        cmd = action.get("command", "")
        return f"[Edit] {cmd} {path}"
    elif tool_name == "finish":
        msg = action.get("message", "")[:300]
        return f"[Finish] {msg}"
    else:
        return f"[{tool_name}]"


# =============================================================================
# Transcript Building
# =============================================================================


def build_transcript(events: list[dict], context: ContextLevel = "default") -> list[dict]:
    """Build a transcript based on the context level.

    Context levels:
    - minimal: User messages only
    - default: User messages + finish action
    - full: User + agent messages + action summaries
    """
    items = []

    for event in events:
        source = event.get("source", "")
        kind = event.get("kind", "")

        # User messages - always included
        if source == "user" and kind == "MessageEvent":
            content = extract_message_content(event)
            if content:
                items.append({"role": "user", "text": content})

        # Agent messages - only in full context
        elif source == "agent" and kind == "MessageEvent" and context == "full":
            content = extract_message_content(event)
            if content:
                # Truncate long agent messages
                if len(content) > 1000:
                    content = content[:1000] + "... [truncated]"
                items.append({"role": "assistant", "text": content})

        # Action events
        elif source == "agent" and kind == "ActionEvent":
            tool_name = event.get("tool_name", "")

            # Finish action - included in default and full
            if tool_name == "finish" and context in ("default", "full"):
                summary = extract_action_summary(event)
                items.append({"role": "action", "text": summary})

            # Other actions - only in full context
            elif context == "full" and tool_name != "finish":
                summary = extract_action_summary(event)
                items.append({"role": "action", "text": summary})

    return items


def format_transcript(items: list[dict]) -> str:
    """Format transcript items into a string for LLM analysis."""
    lines = []
    for item in items:
        role = item["role"].upper()
        text = item["text"]
        # Truncate very long items
        if len(text) > 2000:
            text = text[:2000] + "... [truncated]"
        lines.append(f"[{role}]: {text}")
    return "\n\n".join(lines)


def get_cached_analysis(
    conv_dir: Path,
    context: ContextLevel = "default",
    detail: DetailLevel = "brief",
    assess: bool = False,
) -> ObjectiveAnalysis | None:
    """Load cached analysis if it exists and is still valid.

    Cache is invalidated if:
    - Event count has changed (quick check for trajectory growth)
    - Content hash has changed (conversation was modified)
    - Context level has changed
    - Detail level has changed
    - Assess flag has changed
    """
    events = load_events(conv_dir)
    items = build_transcript(events, context)
    content_hash = compute_content_hash(items)

    return _cache_manager.load_cached(
        conv_dir,
        events,
        content_hash,
        context_level=context,
        detail_level=detail,
        assess=assess,
    )


def _parse_llm_response(response_text: str) -> dict:
    """Parse the LLM response, handling potential markdown wrapping."""
    text = response_text.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's just ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return json.loads(text)


def analyze_objectives(
    conv_dir: Path,
    model: str | None = None,
    context: ContextLevel = "default",
    detail: DetailLevel = "brief",
    assess: bool = False,
    force_refresh: bool = False,
) -> ObjectiveAnalysis:
    """Analyze a conversation to extract user objectives.

    Args:
        conv_dir: Path to the conversation directory
        model: LLM model to use (defaults to LLM_MODEL env var)
        context: Context level for transcript building:
            - "minimal": User messages only (lowest tokens)
            - "default": User messages + finish action (recommended)
            - "full": User + agent messages + action summaries (most tokens)
        detail: Detail level for output:
            - "brief": Just the goal (1-2 sentences)
            - "standard": Goal + primary/secondary outcomes
            - "detailed": Full hierarchical objectives with subordinates
        assess: If True, include status assessment (achieved/not_achieved/in_progress)
            for each objective. Requires at least "default" context (finish action).
        force_refresh: If True, ignore cached analysis

    Returns:
        ObjectiveAnalysis with identified objectives

    Raises:
        ValueError: If no messages found in conversation
        RuntimeError: If LLM call fails
    """
    # For assessment, we need at least the finish action
    # Upgrade context if needed
    effective_context = context
    if assess and context == "minimal":
        effective_context = "default"
        log.debug("Upgrading context to 'default' for assessment (need finish action)")

    # Check cache first
    if not force_refresh:
        cached = get_cached_analysis(conv_dir, effective_context, detail, assess)
        if cached:
            log.debug("Using cached analysis from %s", cached.analyzed_at)
            return cached

    # Load events and build transcript
    events = load_events(conv_dir)
    if not events:
        raise ValueError(f"No events found in conversation: {conv_dir}")

    items = build_transcript(events, effective_context)
    if not items:
        raise ValueError(f"No content found in conversation: {conv_dir}")

    event_count = len(events)
    content_hash = compute_content_hash(items)
    transcript = format_transcript(items)

    # Suppress SDK banner before import
    import os
    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

    # Import here to avoid loading SDK unless needed
    from openhands.sdk import LLM, Message, TextContent

    # Load LLM from environment
    llm = LLM.load_from_env()
    if model:
        llm = LLM(model=model, api_key=llm.api_key, base_url=llm.base_url)

    model_used = llm.model

    # Select prompt based on detail level and assess flag
    if detail == "detailed":
        system_prompt = PROMPT_DETAILED_ASSESS if assess else PROMPT_DETAILED
    elif assess:
        # Assessment variants for brief/standard
        system_prompt = PROMPT_BRIEF_ASSESS if detail == "brief" else PROMPT_STANDARD_ASSESS
    else:
        # No assessment
        system_prompt = PROMPT_BRIEF if detail == "brief" else PROMPT_STANDARD

    # Estimate tokens and log analysis parameters
    approx_tokens = int(len(transcript.split()) * 1.3)
    log.debug(
        "Analyzing conversation with %s (context=%s, detail=%s, assess=%s, ~%d tokens)...",
        model_used,
        effective_context,
        detail,
        assess,
        approx_tokens,
    )

    # Prepare messages for LLM
    llm_messages = [
        Message(role="system", content=[TextContent(type="text", text=system_prompt)]),
        Message(
            role="user",
            content=[
                TextContent(
                    type="text",
                    text=f"Analyze this conversation:\n\n{transcript}",
                )
            ],
        ),
    ]

    # Import timeout error type for specific handling
    from openhands.sdk.llm.exceptions import LLMTimeoutError

    # Call LLM with timeout awareness
    try:
        response = llm.completion(llm_messages)
    except LLMTimeoutError as e:
        timeout_val = llm.timeout or 300
        raise RuntimeError(
            f"LLM request timed out after {timeout_val}s. "
            f"For long conversations, try setting LLM_TIMEOUT to a higher value "
            f"(e.g., export LLM_TIMEOUT=600 for 10 minutes)."
        ) from e

    # Extract text from response
    response_text = ""
    for content_item in response.message.content:
        if hasattr(content_item, "text"):
            response_text += content_item.text

    # Parse response
    try:
        result = _parse_llm_response(response_text)
    except json.JSONDecodeError as e:
        log.error("Failed to parse LLM response: %s", response_text[:500])
        raise RuntimeError(f"Failed to parse LLM response as JSON: {e}") from e

    # Build analysis object based on detail level
    if detail == "detailed":
        # Full hierarchical analysis
        def parse_objective(obj_data: dict) -> Objective:
            # Only parse status/evidence when assess=True
            status = None
            evidence = None
            if assess:
                status_str = obj_data.get("status")
                if status_str:
                    status = ObjectiveStatus(status_str)
                evidence = obj_data.get("evidence")

            return Objective(
                description=obj_data.get("description", ""),
                status=status,
                evidence=evidence,
                subordinates=[
                    parse_objective(sub) for sub in obj_data.get("subordinates", [])
                ],
            )

        primary_objectives = [
            parse_objective(obj) for obj in result.get("primary_objectives", [])
        ]

        analysis = ObjectiveAnalysis(
            conversation_id=conv_dir.name,
            analyzed_at=datetime.now(timezone.utc),
            model_used=model_used,
            event_count=event_count,
            content_hash=content_hash,
            context_level=effective_context,
            detail_level=detail,
            assess=assess,
            primary_objectives=primary_objectives,
            summary=result.get("summary"),
        )
    else:
        # Brief or standard - simpler structure
        analysis = ObjectiveAnalysis(
            conversation_id=conv_dir.name,
            analyzed_at=datetime.now(timezone.utc),
            model_used=model_used,
            event_count=event_count,
            content_hash=content_hash,
            context_level=effective_context,
            detail_level=detail,
            assess=assess,
            goal=result.get("goal"),
            status=result.get("status") if assess else None,
            primary_outcomes=result.get("primary_outcomes", []),
            secondary_outcomes=result.get("secondary_outcomes", []),
        )

    # Cache the result
    _cache_manager.save(conv_dir, analysis)
    log.debug("Analysis complete and cached")

    return analysis
