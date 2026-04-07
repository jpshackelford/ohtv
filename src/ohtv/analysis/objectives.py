"""Objective extraction and analysis from conversations."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger("ohtv")


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
    """Complete objective analysis for a conversation."""

    conversation_id: str
    analyzed_at: datetime
    model_used: str
    content_hash: str
    primary_objectives: list[Objective]
    summary: str | None = None


ANALYSIS_CACHE_FILENAME = "objective_analysis.json"

SYSTEM_PROMPT = """You are an expert at analyzing software development conversations to identify user objectives.

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


def _compute_content_hash(messages: list[dict]) -> str:
    """Compute a hash of conversation content for cache invalidation."""
    content = json.dumps(messages, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _load_conversation_messages(conv_dir: Path) -> list[dict]:
    """Load user and assistant messages from a conversation directory."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return []

    messages = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            event = json.loads(event_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        source = event.get("source")
        if source not in ("user", "agent"):
            continue

        # Extract message text
        text = _extract_message_text(event)
        if text:
            role = "user" if source == "user" else "assistant"
            messages.append({"role": role, "text": text})

    return messages


def _extract_message_text(event: dict) -> str | None:
    """Extract text content from an event."""
    # Try llm_message.content[].text format (cloud)
    llm_msg = event.get("llm_message", {})
    content = llm_msg.get("content", [])
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        if texts:
            return "\n".join(texts)

    # Try direct content field (local CLI format)
    if event.get("content"):
        return event["content"]

    # Try message field
    if event.get("message"):
        return event["message"]

    return None


def _format_messages_for_analysis(messages: list[dict]) -> str:
    """Format messages into a readable transcript for analysis."""
    lines = []
    for msg in messages:
        role = msg["role"].upper()
        text = msg["text"]
        # Truncate very long messages
        if len(text) > 2000:
            text = text[:2000] + "... [truncated]"
        lines.append(f"[{role}]: {text}")
    return "\n\n".join(lines)


def get_cached_analysis(conv_dir: Path) -> ObjectiveAnalysis | None:
    """Load cached analysis if it exists and is still valid."""
    cache_file = conv_dir / ANALYSIS_CACHE_FILENAME
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
        analysis = ObjectiveAnalysis.model_validate(data)

        # Check if content has changed
        messages = _load_conversation_messages(conv_dir)
        current_hash = _compute_content_hash(messages)
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
    force_refresh: bool = False,
) -> ObjectiveAnalysis:
    """Analyze a conversation to extract user objectives.

    Args:
        conv_dir: Path to the conversation directory
        model: LLM model to use (defaults to LLM_MODEL env var or claude-sonnet-4-20250514)
        force_refresh: If True, ignore cached analysis

    Returns:
        ObjectiveAnalysis with identified objectives

    Raises:
        ValueError: If no messages found in conversation
        RuntimeError: If LLM call fails
    """
    # Check cache first
    if not force_refresh:
        cached = get_cached_analysis(conv_dir)
        if cached:
            log.info("Using cached analysis from %s", cached.analyzed_at)
            return cached

    # Load messages
    messages = _load_conversation_messages(conv_dir)
    if not messages:
        raise ValueError(f"No messages found in conversation: {conv_dir}")

    content_hash = _compute_content_hash(messages)
    transcript = _format_messages_for_analysis(messages)

    # Import here to avoid loading SDK unless needed
    from openhands.sdk import LLM, Message, TextContent

    # Load LLM from environment
    llm = LLM.load_from_env()
    if model:
        llm = LLM(model=model, api_key=llm.api_key, base_url=llm.base_url)

    model_used = llm.model

    # Prepare messages for LLM
    llm_messages = [
        Message(role="system", content=[TextContent(type="text", text=SYSTEM_PROMPT)]),
        Message(
            role="user",
            content=[
                TextContent(
                    type="text",
                    text=f"Analyze this conversation and identify user objectives:\n\n{transcript}",
                )
            ],
        ),
    ]

    # Call LLM
    log.info("Analyzing conversation with %s...", model_used)
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

    # Build analysis object
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
        primary_objectives=primary_objectives,
        summary=result.get("summary"),
    )

    # Cache the result
    _save_analysis(conv_dir, analysis)
    log.info("Analysis complete and cached")

    return analysis
