"""Tests for error analysis module."""

import pytest
from datetime import datetime

from ohtv.errors import (
    ErrorInfo,
    ErrorSeverity,
    ErrorSummary,
    ErrorType,
    analyze_event,
    extract_event_index,
    format_error_type_counts,
    parse_datetime,
)


class TestExtractEventIndex:
    """Tests for extract_event_index function."""

    def test_local_format(self):
        assert extract_event_index("event-00045-abc123.json") == 45

    def test_cloud_format(self):
        assert extract_event_index("event_000045_abc123.json") == 45

    def test_zero_index(self):
        assert extract_event_index("event-00000-abc123.json") == 0

    def test_large_index(self):
        assert extract_event_index("event-99999-abc123.json") == 99999

    def test_invalid_format(self):
        assert extract_event_index("not_an_event.json") == -1


class TestParseDatetime:
    """Tests for parse_datetime function."""

    def test_basic_iso(self):
        dt = parse_datetime("2026-04-14T13:37:49")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.day == 14

    def test_with_microseconds(self):
        dt = parse_datetime("2026-04-14T13:37:49.261427")
        assert dt is not None
        assert dt.microsecond == 261427

    def test_with_z_suffix(self):
        dt = parse_datetime("2026-04-14T13:37:49.261427Z")
        assert dt is not None

    def test_with_timezone(self):
        dt = parse_datetime("2026-04-14T13:37:49+00:00")
        assert dt is not None

    def test_none_input(self):
        assert parse_datetime(None) is None

    def test_empty_string(self):
        assert parse_datetime("") is None


class TestAnalyzeEvent:
    """Tests for analyze_event function."""

    def test_conversation_error_event(self):
        event = {
            "id": "abc123",
            "timestamp": "2026-04-14T13:37:49",
            "source": "environment",
            "kind": "ConversationErrorEvent",
            "code": "LLMBadRequestError",
            "detail": "Some error message",
        }
        
        error = analyze_event(event, event_index=9, is_last_event=True)
        
        assert error is not None
        assert error.event_index == 9
        assert error.event_id == "abc123"
        assert error.error_type == ErrorType.CONVERSATION_ERROR
        assert error.severity == ErrorSeverity.TERMINAL
        assert error.code == "LLMBadRequestError"
        assert error.message == "Some error message"

    def test_agent_error_event_terminal(self):
        event = {
            "id": "def456",
            "timestamp": "2026-04-14T13:37:49",
            "source": "agent",
            "kind": "AgentErrorEvent",
            "error": "A restart occurred",
            "tool_name": "terminal",
        }
        
        # Terminal when last event
        error = analyze_event(event, event_index=100, is_last_event=True)
        
        assert error is not None
        assert error.error_type == ErrorType.AGENT_ERROR
        assert error.severity == ErrorSeverity.TERMINAL
        assert error.message == "A restart occurred"
        assert error.tool_name == "terminal"

    def test_agent_error_event_recovered(self):
        event = {
            "id": "def456",
            "timestamp": "2026-04-14T13:37:49",
            "source": "agent",
            "kind": "AgentErrorEvent",
            "error": "A restart occurred",
            "tool_name": "terminal",
        }
        
        # Recovered when not last event
        error = analyze_event(event, event_index=50, is_last_event=False)
        
        assert error is not None
        assert error.error_type == ErrorType.AGENT_ERROR
        assert error.severity == ErrorSeverity.RECOVERED

    def test_regular_event_no_error(self):
        event = {
            "id": "ghi789",
            "timestamp": "2026-04-14T13:37:49",
            "source": "agent",
            "kind": "ActionEvent",
        }
        
        error = analyze_event(event, event_index=5, is_last_event=False)
        assert error is None

    def test_message_event_no_error(self):
        event = {
            "id": "jkl012",
            "timestamp": "2026-04-14T13:37:49",
            "source": "user",
            "kind": "MessageEvent",
        }
        
        error = analyze_event(event, event_index=1, is_last_event=False)
        assert error is None

    def test_observation_event_no_error(self):
        """Observation events with non-zero exit codes should NOT be flagged as errors."""
        event = {
            "id": "mno345",
            "timestamp": "2026-04-14T13:37:49",
            "source": "environment",
            "kind": "ObservationEvent",
            "observation": {
                "kind": "TerminalObservation",
                "exit_code": 1,
            },
        }
        
        error = analyze_event(event, event_index=10, is_last_event=False)
        # Non-zero exit codes are NOT tracked as agent errors
        assert error is None


class TestErrorSummary:
    """Tests for ErrorSummary dataclass."""

    def test_empty_summary(self):
        summary = ErrorSummary(conversation_id="test123")
        
        assert summary.total_errors == 0
        assert summary.terminal_count == 0
        assert summary.recovered_count == 0
        assert not summary.has_terminal_error
        assert not summary.has_errors

    def test_add_terminal_error(self):
        summary = ErrorSummary(conversation_id="test123")
        error = ErrorInfo(
            event_index=10,
            event_id="abc",
            timestamp=None,
            error_type=ErrorType.CONVERSATION_ERROR,
            severity=ErrorSeverity.TERMINAL,
        )
        
        summary.add_error(error)
        
        assert summary.total_errors == 1
        assert summary.terminal_count == 1
        assert summary.recovered_count == 0
        assert summary.has_terminal_error
        assert summary.has_errors
        assert summary.error_counts == {"ConversationError": 1}

    def test_add_recovered_error(self):
        summary = ErrorSummary(conversation_id="test123")
        error = ErrorInfo(
            event_index=10,
            event_id="abc",
            timestamp=None,
            error_type=ErrorType.AGENT_ERROR,
            severity=ErrorSeverity.RECOVERED,
        )
        
        summary.add_error(error)
        
        assert summary.total_errors == 1
        assert summary.terminal_count == 0
        assert summary.recovered_count == 1
        assert not summary.has_terminal_error
        assert summary.has_errors

    def test_execution_status_error_is_terminal(self):
        summary = ErrorSummary(
            conversation_id="test123",
            execution_status="error",
        )
        
        assert summary.has_terminal_error
        assert summary.has_errors


class TestFormatErrorTypeCounts:
    """Tests for format_error_type_counts function."""

    def test_empty_counts(self):
        assert format_error_type_counts({}) == ""

    def test_single_error(self):
        result = format_error_type_counts({"ConversationError": 1})
        assert result == "ConversationError"

    def test_multiple_same_type(self):
        result = format_error_type_counts({"AgentError": 3})
        assert result == "AgentError x3"

    def test_multiple_types(self):
        result = format_error_type_counts({
            "ConversationError": 1,
            "AgentError": 2,
        })
        # Should be sorted by count (descending)
        assert "AgentError x2" in result
        assert "ConversationError" in result
