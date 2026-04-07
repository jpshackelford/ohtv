"""Objective extraction and analysis from conversations.

Context Levels (experimentally validated):
- minimal: User messages only (lowest tokens, may lack outcome info)
- default: User messages + finish action (best balance of tokens vs accuracy)
- full: User + agent messages + action summaries (most context, highest tokens)

The 'default' level was determined through experiments comparing different
approaches across short (23 events), medium (60 events), and long (300+ events)
conversations. See experiments/objective_extraction_comparison.py for details.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

log = logging.getLogger("ohtv")

# Context level type
ContextLevel = Literal["minimal", "default", "full"]


class ObjectiveStatus(str, Enum):
    """Status of an objective in a conversation."""

    ACHIEVED = "achieved"
    PARTIALLY_ACHIEVED = "partially_achieved"
    NOT_ACHIEVED = "not_achieved"
    IN_PROGRESS = "in_progress"
    UNCLEAR = "unclear"


class Objective(BaseModel):
    """A user objective identified in a conversation."""

    description: str
    status: ObjectiveStatus
    evidence: str | None = None
    subordinates: list["Objective"] = []


class ObjectiveAnalysis(BaseModel):
    """Complete objective analysis for a conversation.

    Supports three detail levels:
    - brief: Just 'goal' field (1-2 sentences)
    - standard: goal + primary_outcomes + secondary_outcomes
    - detailed: Full hierarchical objectives with status assessment
    """

    conversation_id: str
    analyzed_at: datetime
    model_used: str
    content_hash: str
    context_level: str
    detail_level: str = "brief"

    # Brief/Standard fields
    goal: str | None = None
    primary_outcomes: list[str] = []
    secondary_outcomes: list[str] = []

    # Detailed fields (legacy/detailed mode)
    primary_objectives: list[Objective] = []
    summary: str | None = None


ANALYSIS_CACHE_FILENAME = "objective_analysis.json"

# Output detail levels
DetailLevel = Literal["brief", "standard", "detailed"]

# Prompt for brief output (just the goal, no assessment)
PROMPT_BRIEF = """Analyze this conversation between a user and an AI coding assistant.

In 1-2 sentences, answer: What outcome does the user hope to achieve?

Do not assess whether the goal was achieved. Just identify what they want.

Respond with JSON:
{"goal": "1-2 sentence description of what the user wants to accomplish"}"""

# Prompt for standard output (goal + success criteria)
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

# Prompt for detailed output (full analysis with status assessment)
PROMPT_DETAILED = """You are an expert at analyzing software development conversations to identify user objectives.

Given a conversation between a user and an AI coding assistant, identify:
1. PRIMARY OBJECTIVES: The main goals the user is trying to accomplish
2. SUBORDINATE OBJECTIVES: Supporting goals that help achieve the primary ones

For each objective, assess its status:
- achieved: The objective was fully accomplished
- partially_achieved: Some progress was made but not complete
- not_achieved: The objective was not accomplished
- in_progress: Work is ongoing with no clear conclusion
- unclear: Cannot determine the status from the conversation

Provide evidence from the conversation to support your assessment.

Respond with a JSON object in this exact format:
{
  "primary_objectives": [
    {
      "description": "Clear description of the objective",
      "status": "achieved|partially_achieved|not_achieved|in_progress|unclear",
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
# Event Loading (shared with cli.py patterns)
# =============================================================================


def load_events(conv_dir: Path) -> list[dict]:
    """Load all events from a conversation directory."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return []

    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
            events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events


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


def _compute_content_hash(items: list[dict]) -> str:
    """Compute a hash of transcript content for cache invalidation."""
    content = json.dumps(items, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def get_cached_analysis(
    conv_dir: Path,
    context: ContextLevel = "default",
    detail: DetailLevel = "brief",
) -> ObjectiveAnalysis | None:
    """Load cached analysis if it exists and is still valid.

    Cache is invalidated if:
    - Content hash has changed (conversation was modified)
    - Context level has changed
    - Detail level has changed
    """
    cache_file = conv_dir / ANALYSIS_CACHE_FILENAME
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
        analysis = ObjectiveAnalysis.model_validate(data)

        # Check if context level matches
        cached_context = getattr(analysis, "context_level", "default")
        if cached_context != context:
            log.debug("Cache invalidated: context level changed (%s -> %s)", cached_context, context)
            return None

        # Check if detail level matches
        cached_detail = getattr(analysis, "detail_level", "brief")
        if cached_detail != detail:
            log.debug("Cache invalidated: detail level changed (%s -> %s)", cached_detail, detail)
            return None

        # Check if content has changed
        events = load_events(conv_dir)
        items = build_transcript(events, context)
        current_hash = _compute_content_hash(items)
        if analysis.content_hash != current_hash:
            log.debug("Cache invalidated: content hash mismatch")
            return None

        return analysis
    except (json.JSONDecodeError, OSError, ValueError) as e:
        log.warning("Failed to load cached analysis: %s", e)
        return None


def _save_analysis(conv_dir: Path, analysis: ObjectiveAnalysis) -> None:
    """Save analysis to cache file."""
    cache_file = conv_dir / ANALYSIS_CACHE_FILENAME
    cache_file.write_text(analysis.model_dump_json(indent=2))


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
            - "detailed": Full hierarchical analysis with status
        force_refresh: If True, ignore cached analysis

    Returns:
        ObjectiveAnalysis with identified objectives

    Raises:
        ValueError: If no messages found in conversation
        RuntimeError: If LLM call fails
    """
    # Check cache first
    if not force_refresh:
        cached = get_cached_analysis(conv_dir, context, detail)
        if cached:
            log.debug("Using cached analysis from %s", cached.analyzed_at)
            return cached

    # Load events and build transcript
    events = load_events(conv_dir)
    if not events:
        raise ValueError(f"No events found in conversation: {conv_dir}")

    items = build_transcript(events, context)
    if not items:
        raise ValueError(f"No content found in conversation: {conv_dir}")

    content_hash = _compute_content_hash(items)
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

    # Select prompt based on detail level
    if detail == "brief":
        system_prompt = PROMPT_BRIEF
    elif detail == "standard":
        system_prompt = PROMPT_STANDARD
    else:  # detailed
        system_prompt = PROMPT_DETAILED

    # Log token estimate (debug level - only shows with --verbose)
    approx_tokens = int(len(transcript.split()) * 1.3)
    log.debug(
        "Analyzing conversation with %s (context=%s, detail=%s, ~%d tokens)...",
        model_used,
        context,
        detail,
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

    # Call LLM
    response = llm.completion(llm_messages)

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
            return Objective(
                description=obj_data.get("description", ""),
                status=ObjectiveStatus(obj_data.get("status", "unclear")),
                evidence=obj_data.get("evidence"),
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
            content_hash=content_hash,
            context_level=context,
            detail_level=detail,
            primary_objectives=primary_objectives,
            summary=result.get("summary"),
        )
    else:
        # Brief or standard - simpler structure
        analysis = ObjectiveAnalysis(
            conversation_id=conv_dir.name,
            analyzed_at=datetime.now(timezone.utc),
            model_used=model_used,
            content_hash=content_hash,
            context_level=context,
            detail_level=detail,
            goal=result.get("goal"),
            primary_outcomes=result.get("primary_outcomes", []),
            secondary_outcomes=result.get("secondary_outcomes", []),
        )

    # Cache the result
    _save_analysis(conv_dir, analysis)
    log.debug("Analysis complete and cached")

    return analysis
