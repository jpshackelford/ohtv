"""Error analysis for OpenHands conversations.

Detects and classifies agent/LLM errors that impact agent behavior:
- ConversationErrorEvent: Terminal errors that stop the conversation (LLM errors, budget exceeded)
- AgentErrorEvent: Agent-level errors (sandbox restarts, tool validation failures)

Note: This module does NOT track routine terminal command failures (non-zero exit codes)
which are normal during development workflows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterator


class ErrorSeverity(Enum):
    """Error severity classification."""
    
    TERMINAL = "terminal"  # Conversation stopped
    RECOVERED = "recovered"  # Error occurred but conversation continued


class ErrorType(Enum):
    """Types of agent/LLM errors detected in conversations."""
    
    CONVERSATION_ERROR = "ConversationError"  # ConversationErrorEvent (LLM errors, budget)
    AGENT_ERROR = "AgentError"  # AgentErrorEvent (sandbox restart, validation)


@dataclass
class ErrorInfo:
    """Information about a single error occurrence."""
    
    event_index: int  # Event sequence number (e.g., 45 from event-00045-*.json)
    event_id: str
    timestamp: datetime | None
    error_type: ErrorType
    severity: ErrorSeverity
    code: str | None = None  # Error code (e.g., LLMBadRequestError)
    message: str | None = None  # Error message/detail
    tool_name: str | None = None  # Tool that produced the error (for AgentErrorEvent)


@dataclass
class ErrorSummary:
    """Summary of agent/LLM errors in a conversation."""
    
    conversation_id: str
    execution_status: str | None = None  # From base_state.json
    total_errors: int = 0
    terminal_count: int = 0
    recovered_count: int = 0
    errors: list[ErrorInfo] = field(default_factory=list)
    error_counts: dict[str, int] = field(default_factory=dict)  # ErrorType name -> count
    
    @property
    def has_terminal_error(self) -> bool:
        """Check if conversation has a terminal error."""
        return self.terminal_count > 0 or self.execution_status == "error"
    
    @property
    def has_errors(self) -> bool:
        """Check if conversation has any errors."""
        return self.total_errors > 0 or self.execution_status == "error"
    
    def add_error(self, error: ErrorInfo) -> None:
        """Add an error to the summary."""
        self.errors.append(error)
        self.total_errors += 1
        if error.severity == ErrorSeverity.TERMINAL:
            self.terminal_count += 1
        else:
            self.recovered_count += 1
        type_name = error.error_type.value
        self.error_counts[type_name] = self.error_counts.get(type_name, 0) + 1


def extract_event_index(filename: str) -> int:
    """Extract event sequence number from filename.
    
    Args:
        filename: Event filename like "event-00045-abc123.json"
        
    Returns:
        Event index (e.g., 45)
    """
    match = re.match(r'event[_-](\d+)', filename)
    if match:
        return int(match.group(1))
    return -1


def parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string."""
    if not value:
        return None
    value = value.rstrip("Z").split("+")[0]
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def analyze_event(event: dict, event_index: int, is_last_event: bool = False) -> ErrorInfo | None:
    """Analyze a single event for agent/LLM errors.
    
    Args:
        event: Event data dictionary
        event_index: Event sequence number
        is_last_event: Whether this is the last event in the conversation
        
    Returns:
        ErrorInfo if an agent/LLM error was detected, None otherwise
    """
    kind = event.get("kind", "")
    event_id = event.get("id", "")
    timestamp = parse_datetime(event.get("timestamp"))
    
    # ConversationErrorEvent - always terminal (LLM errors, budget exceeded, etc.)
    if kind == "ConversationErrorEvent":
        return ErrorInfo(
            event_index=event_index,
            event_id=event_id,
            timestamp=timestamp,
            error_type=ErrorType.CONVERSATION_ERROR,
            severity=ErrorSeverity.TERMINAL,
            code=event.get("code"),
            message=event.get("detail"),
        )
    
    # AgentErrorEvent - terminal if last event, otherwise recovered
    # These are agent-level errors like sandbox restarts, tool validation failures
    if kind == "AgentErrorEvent":
        severity = ErrorSeverity.TERMINAL if is_last_event else ErrorSeverity.RECOVERED
        return ErrorInfo(
            event_index=event_index,
            event_id=event_id,
            timestamp=timestamp,
            error_type=ErrorType.AGENT_ERROR,
            severity=severity,
            message=event.get("error"),
            tool_name=event.get("tool_name"),
        )
    
    return None


def load_events(conv_dir: Path) -> Iterator[tuple[int, dict]]:
    """Load events from a conversation directory.
    
    Yields:
        Tuples of (event_index, event_data)
    """
    import json
    
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return
    
    for event_file in sorted(events_dir.glob("event-*.json")):
        event_index = extract_event_index(event_file.name)
        try:
            data = json.loads(event_file.read_text())
            yield event_index, data
        except (json.JSONDecodeError, OSError):
            continue


def load_base_state(conv_dir: Path) -> dict:
    """Load base_state.json from a conversation directory."""
    import json
    
    base_state_path = conv_dir / "base_state.json"
    if not base_state_path.exists():
        return {}
    
    try:
        return json.loads(base_state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def analyze_conversation(conv_dir: Path, conv_id: str | None = None) -> ErrorSummary:
    """Analyze a conversation for errors.
    
    Args:
        conv_dir: Path to conversation directory
        conv_id: Optional conversation ID (uses directory name if not provided)
        
    Returns:
        ErrorSummary with all detected errors
    """
    if conv_id is None:
        conv_id = conv_dir.name
    
    # Load base_state for execution_status
    base_state = load_base_state(conv_dir)
    execution_status = base_state.get("execution_status")
    
    summary = ErrorSummary(
        conversation_id=conv_id,
        execution_status=execution_status,
    )
    
    # Load all events to determine which is last
    events = list(load_events(conv_dir))
    if not events:
        return summary
    
    last_index = events[-1][0]
    
    # Analyze each event
    for event_index, event in events:
        is_last = event_index == last_index
        error = analyze_event(event, event_index, is_last_event=is_last)
        if error:
            summary.add_error(error)
    
    return summary


def analyze_conversation_lazy(conv_dir: Path, conv_id: str | None = None) -> ErrorSummary | None:
    """Lazily analyze a conversation for errors (quick check).
    
    This is a faster version that stops early once it detects any error.
    Used for filtering in list commands.
    
    Args:
        conv_dir: Path to conversation directory
        conv_id: Optional conversation ID
        
    Returns:
        ErrorSummary if errors found, None if no errors
    """
    if conv_id is None:
        conv_id = conv_dir.name
    
    # Quick check: execution_status == "error" is always an error
    base_state = load_base_state(conv_dir)
    execution_status = base_state.get("execution_status")
    
    if execution_status == "error":
        return ErrorSummary(
            conversation_id=conv_id,
            execution_status=execution_status,
            total_errors=1,
            terminal_count=1,
        )
    
    # Check events for errors
    events = list(load_events(conv_dir))
    if not events:
        return None
    
    last_index = events[-1][0]
    found_error = False
    summary = ErrorSummary(
        conversation_id=conv_id,
        execution_status=execution_status,
    )
    
    for event_index, event in events:
        is_last = event_index == last_index
        error = analyze_event(event, event_index, is_last_event=is_last)
        if error:
            summary.add_error(error)
            found_error = True
    
    return summary if found_error else None


def format_error_type_counts(error_counts: dict[str, int]) -> str:
    """Format error type counts for display.
    
    Args:
        error_counts: Dict mapping error type name to count
        
    Returns:
        Formatted string like "ExitCode x3, AgentError"
    """
    parts = []
    for type_name, count in sorted(error_counts.items(), key=lambda x: -x[1]):
        if count > 1:
            parts.append(f"{type_name} x{count}")
        else:
            parts.append(type_name)
    return ", ".join(parts) if parts else ""
