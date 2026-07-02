"""Tests for engagement computation."""

import pytest
from datetime import datetime, timezone

from ohtv_utils.metrics.engagement import (
    DEFAULT_SUSTAINED_ATTENTION_SECONDS,
    DEFAULT_THRESHOLD_SECONDS,
    EngagementMetrics,
    compute_engagement,
)


class TestComputeEngagement:
    """Tests for compute_engagement function."""

    def test_no_follow_ups(self):
        """Zero engagement with only initial prompt."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            }
        ]
        metrics = compute_engagement(events)
        assert metrics.engaged_seconds == 0
        assert metrics.attention_periods == 0
        assert metrics.follow_up_user_message_count == 0

    def test_single_follow_up_within_threshold(self):
        """Engagement with one follow-up within threshold."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:02:00Z",
            },
        ]
        metrics = compute_engagement(events)
        assert metrics.engaged_seconds == 120  # 2 minutes
        assert metrics.attention_periods == 1
        assert metrics.follow_up_user_message_count == 1
        assert metrics.attended_user_message_count == 1

    def test_follow_up_exceeds_threshold(self):
        """No engagement when gap exceeds threshold."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:30:00Z",  # 29 min gap from action
            },
        ]
        metrics = compute_engagement(events, threshold_seconds=10 * 60)  # 10 min
        assert metrics.engaged_seconds == 0
        assert metrics.attention_periods == 0
        assert metrics.attended_user_message_count == 0

    def test_multiple_attention_periods(self):
        """Multiple distinct attention periods."""
        events = [
            # First period
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:02:00Z",
            },
            # Large gap (30 min) - exceeds 5 min threshold
            # Second period - action more than 5 min away from previous user message
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:40:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:41:00Z",  # Within threshold of 10:40, but way past 10:02
            },
        ]
        metrics = compute_engagement(
            events, threshold_seconds=5 * 60, sustained_attention_seconds=10 * 60
        )
        # Second follow-up passes silence gate (gap from 10:40 action is 1 min < 5 min threshold)
        # but fails sustained attention cap (user-to-user gap is 39 min > 10 min cap)
        # so it's a zero-duration touch, creating a second period
        assert metrics.attention_periods == 2
        assert metrics.follow_up_user_message_count == 2

    def test_sustained_attention_cap(self):
        """Sustained attention cap limits block extension."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            # Long gap but action within threshold of next message
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T12:58:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T13:00:00Z",  # 2 min from last action
            },
        ]
        # With 1h cap, user-to-user gap (3h) exceeds cap → zero-duration touch
        metrics = compute_engagement(
            events, threshold_seconds=5 * 60, sustained_attention_seconds=60 * 60
        )
        assert metrics.engaged_seconds == 0  # Touch has zero duration
        assert metrics.attention_periods == 1  # But still counts as a period
        assert metrics.attended_user_message_count == 1

    def test_merge_adjacent_periods(self):
        """Merge adjacent periods within threshold."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:02:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:03:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:04:00Z",
            },
        ]
        metrics = compute_engagement(events)
        assert metrics.attention_periods == 1  # Merged into one
        assert metrics.engaged_seconds == 240  # 4 minutes total

    def test_ignore_assistant_messages(self):
        """Ignore assistant messages in engagement calculation."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "assistant",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:02:00Z",
            },
        ]
        metrics = compute_engagement(events)
        assert metrics.attention_periods == 1
        assert metrics.follow_up_user_message_count == 1

    def test_malformed_event_tolerance(self):
        """Tolerate malformed events."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            "not a dict",
            {"kind": "ActionEvent"},  # Missing timestamp
            {"timestamp": "invalid"},  # Invalid timestamp
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:02:00Z",
            },
        ]
        metrics = compute_engagement(events)
        assert metrics.engaged_seconds == 120

    def test_empty_events(self):
        """Handle empty events list."""
        metrics = compute_engagement([])
        assert metrics.engaged_seconds == 0
        assert metrics.attention_periods == 0
        assert metrics.first_event_ts is None
        assert metrics.last_event_ts is None

    def test_total_duration_seconds(self):
        """Calculate total duration from first to last event."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:05:00Z",
            },
        ]
        metrics = compute_engagement(events)
        assert metrics.total_duration_seconds == 300  # 5 minutes

    def test_custom_thresholds(self):
        """Use custom threshold values."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "kind": "ActionEvent",
                "timestamp": "2024-01-01T10:01:00Z",
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "timestamp": "2024-01-01T10:10:00Z",  # 9 min gap
            },
        ]
        # With 5 min threshold, should be unattended
        metrics = compute_engagement(events, threshold_seconds=5 * 60)
        assert metrics.engaged_seconds == 0

        # With 10 min threshold, should be attended
        metrics = compute_engagement(events, threshold_seconds=10 * 60)
        assert metrics.engaged_seconds == 600


class TestEngagementMetrics:
    """Tests for EngagementMetrics dataclass."""

    def test_dataclass_creation(self):
        """Create EngagementMetrics instance."""
        metrics = EngagementMetrics(
            engaged_seconds=300,
            attention_periods=2,
            follow_up_user_message_count=3,
            attended_user_message_count=2,
        )
        assert metrics.engaged_seconds == 300
        assert metrics.attention_periods == 2

    def test_total_duration_with_timestamps(self):
        """Calculate total duration property."""
        first = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        last = datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc)
        metrics = EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=0,
            attended_user_message_count=0,
            first_event_ts=first,
            last_event_ts=last,
        )
        assert metrics.total_duration_seconds == 300

    def test_total_duration_without_timestamps(self):
        """Total duration is None without timestamps."""
        metrics = EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=0,
            attended_user_message_count=0,
        )
        assert metrics.total_duration_seconds is None


class TestParseTimestamp:
    """Tests for timestamp parsing."""

    def test_iso_format_with_z(self):
        """Parse ISO-8601 timestamp with Z suffix."""
        from ohtv_utils.metrics.engagement import _parse_timestamp

        ts = _parse_timestamp("2024-01-01T10:00:00Z")
        assert ts == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_iso_format_without_z(self):
        """Parse ISO-8601 timestamp without Z (assumes UTC)."""
        from ohtv_utils.metrics.engagement import _parse_timestamp

        ts = _parse_timestamp("2024-01-01T10:00:00")
        assert ts == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_iso_format_with_offset(self):
        """Parse ISO-8601 timestamp with timezone offset."""
        from ohtv_utils.metrics.engagement import _parse_timestamp

        ts = _parse_timestamp("2024-01-01T10:00:00+05:00")
        assert ts is not None  # Parses but strips offset

    def test_invalid_timestamp(self):
        """Return None for invalid timestamp."""
        from ohtv_utils.metrics.engagement import _parse_timestamp

        assert _parse_timestamp("not a timestamp") is None
        assert _parse_timestamp(None) is None
        assert _parse_timestamp(123) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
