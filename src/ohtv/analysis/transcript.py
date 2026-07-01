"""Metadata-driven transcript building for conversation analysis.

This module provides functions to build transcripts from conversation events
using ContextLevel definitions from prompt frontmatter. This replaces hardcoded
context logic with flexible, metadata-driven filtering.
"""

from ohtv.prompts.metadata import ContextLevel

# Re-export extraction utilities from ohtv-utils for backward compatibility
from ohtv_utils.extraction.messages import (
    DEFAULT_OBSERVATION_TRUNCATE,
    extract_action_summary,
    extract_message_content,
    extract_observation_content,
)


def extract_content(event: dict, max_length: int = 0) -> str:
    """Extract text content from an event with optional truncation.

    Args:
        event: The event dictionary
        max_length: Maximum length for content (0 = no limit, meaning full context)

    Returns:
        The extracted content, truncated if needed
    """
    kind = event.get("kind", "")
    content = ""

    if kind == "MessageEvent":
        content = extract_message_content(event)
    elif kind == "ActionEvent":
        # Include full command when no truncation (full context level)
        content = extract_action_summary(event, include_command=(max_length == 0))
    elif kind == "ObservationEvent":
        # Observations have their own dedicated extractor so we honour the
        # per-level truncate setting (caller already truncates, but we pass 0
        # here to defer to the level's truncate value below).
        return extract_observation_content(
            event,
            max_length=max_length if max_length > 0 else DEFAULT_OBSERVATION_TRUNCATE,
        )
    else:
        content = event.get("content", "") or event.get("message", "")

    if max_length > 0 and len(content) > max_length:
        content = content[:max_length] + "... [truncated]"

    return content


def build_transcript_from_context(
    events: list[dict], context: ContextLevel
) -> list[dict]:
    """Build transcript based on context level from prompt metadata.

    Args:
        events: List of conversation events
        context: ContextLevel with include/exclude filters

    Returns:
        List of transcript items with role and text
    """
    items = []

    for event in events:
        if context.matches(event):
            content = extract_content(event, max_length=context.truncate)
            if content:
                source = event.get("source", "unknown")
                kind = event.get("kind", "unknown")

                # Map to transcript role
                if kind == "MessageEvent":
                    role = "user" if source == "user" else "assistant"
                elif kind == "ActionEvent":
                    role = "action"
                elif kind == "ObservationEvent":
                    role = "observation"
                else:
                    role = "system"

                items.append({"role": role, "text": content})

    return items


def format_transcript(items: list[dict]) -> str:
    """Format transcript items into a string for LLM analysis.

    Args:
        items: List of transcript items with role and text

    Returns:
        Formatted transcript string
    """
    lines = []
    for item in items:
        role = item["role"].upper()
        text = item["text"]
        lines.append(f"[{role}]: {text}")
    return "\n\n".join(lines)
