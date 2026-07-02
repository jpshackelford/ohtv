"""Message, action, and observation content extraction from OpenHands events.

These functions extract text content from different event types in OpenHands
conversation traces. They handle both string and structured content formats,
and provide sensible defaults for missing or malformed data.
"""

# Default truncation for tool observations. Per ohtv Issue #149 data analysis,
# average terminal observations are ~2.2k chars and file_editor observations
# ~5k chars; 800 keeps signal high without ballooning tokens.
DEFAULT_OBSERVATION_TRUNCATE = 800


def extract_message_content(event: dict, include_critic: bool = False) -> str:
    """Extract text content from a MessageEvent.

    Handles both string content and structured content arrays with text items.
    Falls back to top-level content/message fields if llm_message structure
    is not present.

    Args:
        event: The event dictionary (from event-*.json files)
        include_critic: If False (default), exclude critic_result metadata.
            Critic results are internal evaluation data that shouldn't
            influence objective analysis.

    Returns:
        The extracted message content as a string. Returns empty string if
        no content is found.

    Example:
        >>> event = {"kind": "MessageEvent", "llm_message": {"content": [
        ...     {"type": "text", "text": "Hello"}
        ... ]}}
        >>> extract_message_content(event)
        'Hello'
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

    Extracts summaries from ActionEvents (tool calls). Prefers the agent's
    own summary field, falls back to extracting details from the action payload.

    Args:
        event: The action event dictionary
        include_command: If True, include full command after summary for
            terminal actions (useful for full context analysis)

    Returns:
        Summary string, optionally with command details appended. For terminal
        actions, the summary is formatted as "[Terminal] command". For file
        edits: "[Edit] command path". For finish: "[Finish] message".

    Example:
        >>> event = {"tool_name": "terminal", "action": {"command": "ls -la"},
        ...          "summary": "List files"}
        >>> extract_action_summary(event)
        '[Terminal] List files'
        >>> extract_action_summary(event, include_command=True)
        '[Terminal] List files\\n  Command: ls -la'
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
    etc.). Content can be a string or a structured array of content items.

    Args:
        event: The observation event dictionary
        max_length: Maximum length for content (0 = no limit). Truncated
            content is suffixed with "... [truncated]".

    Returns:
        Observation content as a single string, optionally prefixed with
        exit code. Returns empty string if the event has no observation
        payload.

    Example:
        >>> event = {"observation": {"content": "Command output here",
        ...                          "exit_code": 0}}
        >>> extract_observation_content(event)
        '(exit=0) Command output here'
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
        # Fall back to direct content/message fields
        text = event.get("content", "") or event.get("message", "")
        if not isinstance(text, str):
            text = ""

    exit_code = obs.get("exit_code")
    if max_length > 0 and len(text) > max_length:
        text = text[:max_length] + "... [truncated]"

    if exit_code is not None:
        return f"(exit={exit_code}) {text}" if text else f"(exit={exit_code})"
    return text
