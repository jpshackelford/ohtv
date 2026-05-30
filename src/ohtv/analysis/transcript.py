"""Metadata-driven transcript building for conversation analysis.

This module provides functions to build transcripts from conversation events
using ContextLevel definitions from prompt frontmatter. This replaces hardcoded
context logic with flexible, metadata-driven filtering.
"""

from ohtv.prompts.metadata import ContextLevel

# Default truncation for tool observations at the "observations" context level.
# Per Issue #149 data analysis, average terminal observations are ~2.2k chars
# and file_editor observations ~5k chars; 800 keeps the LLM signal high
# without ballooning tokens.
DEFAULT_OBSERVATION_TRUNCATE = 800


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


def extract_action_summary(event: dict, include_command: bool = False) -> str:
    """Extract a summary of an action, preferring agent-provided summary.

    Args:
        event: The action event dictionary
        include_command: If True, include full command after summary (for full context)

    Returns:
        Summary string, optionally with command details appended
    """
    tool_name = event.get("tool_name", "unknown")
    action = event.get("action") or {}
    summary = event.get("summary")  # Agent-provided summary

    # Build summary line
    if summary:
        summary_text = f"[{tool_name.title()}] {summary}"
    else:
        # Fallback to extracting from action details
        if tool_name == "terminal":
            cmd = action.get("command", "")[:100]
            summary_text = f"[Terminal] {cmd}"
        elif tool_name == "file_editor":
            path = action.get("path", "")
            cmd = action.get("command", "")
            summary_text = f"[Edit] {cmd} {path}"
        elif tool_name == "finish":
            msg = action.get("message", "")[:300]
            summary_text = f"[Finish] {msg}"
        else:
            summary_text = f"[{tool_name}]"

    # Optionally append full command for terminal actions when we have a summary
    if include_command and tool_name == "terminal" and summary:
        cmd = action.get("command", "")
        if cmd:
            summary_text += f"\n  Command: {cmd}"

    return summary_text


def extract_observation_content(
    event: dict, max_length: int = DEFAULT_OBSERVATION_TRUNCATE
) -> str:
    """Extract text content from an ObservationEvent.

    Observations carry tool outputs (terminal stdout/stderr, file contents,
    etc.). They are included only at the highest context level
    (``observations``) per Issue #149.

    Args:
        event: The observation event dictionary
        max_length: Maximum length for content (0 = no limit). Truncated content
            is suffixed with ``... [truncated]``.

    Returns:
        Observation content as a single string. Returns an empty string if
        the event has no observation payload.
    """
    obs = event.get("observation") or {}
    content = obs.get("content", "")

    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        text = "\n".join(parts)

    if not text:
        # Fall back to direct content/message fields, mirroring extract_content.
        text = event.get("content", "") or event.get("message", "")
        if not isinstance(text, str):
            text = ""

    exit_code = obs.get("exit_code")
    if max_length > 0 and len(text) > max_length:
        text = text[:max_length] + "... [truncated]"

    if exit_code is not None:
        return f"(exit={exit_code}) {text}" if text else f"(exit={exit_code})"
    return text


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
