"""Metadata-driven transcript building for conversation analysis.

This module provides functions to build transcripts from conversation events
using ContextLevel definitions from prompt frontmatter. This replaces hardcoded
context logic with flexible, metadata-driven filtering.
"""

from ohtv.prompts.metadata import ContextLevel


def extract_message_content(event: dict, include_critic: bool = False) -> str:
    """Extract text content from a message event.

    Args:
        event: The event dictionary
        include_critic: If False (default), exclude critic_result metadata from
            the extracted content. Critic results are internal evaluation data
            that shouldn't influence objective analysis.

    Returns:
        The extracted message content as a string
    """
    llm_msg = event.get("llm_message", {})
    content = llm_msg.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        result = "\n".join(texts)
        if result:
            return result

    if isinstance(content, str):
        if content:
            return content

    return event.get("content", "") or event.get("message", "")


def extract_action_summary(event: dict) -> str:
    """Extract a brief summary of an action.

    Args:
        event: The action event dictionary

    Returns:
        A brief summary string describing the action
    """
    tool_name = event.get("tool_name", "unknown")
    action = event.get("action") or {}

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


def extract_content(event: dict, max_length: int = 0) -> str:
    """Extract text content from an event with optional truncation.

    Args:
        event: The event dictionary
        max_length: Maximum length for content (0 = no limit)

    Returns:
        The extracted content, truncated if needed
    """
    kind = event.get("kind", "")
    content = ""

    if kind == "MessageEvent":
        content = extract_message_content(event)
    elif kind == "ActionEvent":
        content = extract_action_summary(event)
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
