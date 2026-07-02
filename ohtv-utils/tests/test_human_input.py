"""Tests for human input counting."""

import pytest

from ohtv_utils.metrics.human_input import HumanInputMetrics, count_human_input


class TestCountHumanInput:
    """Tests for count_human_input function."""

    def test_single_user_message(self):
        """Count single initial message."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hello world"}]
                },
            }
        ]
        metrics = count_human_input(events)
        assert metrics.initial_prompt_words == 2
        assert metrics.followup_message_count == 0
        assert metrics.followup_word_count == 0

    def test_initial_plus_followups(self):
        """Count initial and follow-up messages."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hello world"}]
                },
            },
            {
                "kind": "MessageEvent",
                "source": "assistant",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hi there"}]
                },
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "How are you"}]
                },
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Tell me more"}]
                },
            },
        ]
        metrics = count_human_input(events)
        assert metrics.initial_prompt_words == 2
        assert metrics.followup_message_count == 2
        assert metrics.followup_word_count == 6  # "How are you" + "Tell me more"

    def test_no_user_messages(self):
        """Handle conversations with no user messages."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "assistant",
                "llm_message": {
                    "content": [{"type": "text", "text": "Hello"}]
                },
            }
        ]
        metrics = count_human_input(events)
        assert metrics.initial_prompt_words == 0
        assert metrics.followup_message_count == 0
        assert metrics.followup_word_count == 0

    def test_empty_events_list(self):
        """Handle empty events list."""
        metrics = count_human_input([])
        assert metrics.initial_prompt_words == 0
        assert metrics.followup_message_count == 0
        assert metrics.followup_word_count == 0

    def test_multiple_text_items(self):
        """Sum words across multiple text items in one message."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [
                        {"type": "text", "text": "First part"},
                        {"type": "text", "text": "Second part"},
                    ]
                },
            }
        ]
        metrics = count_human_input(events)
        assert metrics.initial_prompt_words == 4  # "First part Second part"

    def test_ignore_non_text_items(self):
        """Ignore non-text content items."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "image", "url": "http://example.com/img.png"},
                        {"type": "text", "text": "World"},
                    ]
                },
            }
        ]
        metrics = count_human_input(events)
        assert metrics.initial_prompt_words == 2  # "Hello World"

    def test_ignore_non_message_events(self):
        """Ignore ActionEvent and other non-MessageEvent types."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "User message"}]
                },
            },
            {
                "kind": "ActionEvent",
                "source": "user",  # Should be ignored
                "action": {"command": "ls"},
            },
        ]
        metrics = count_human_input(events)
        assert metrics.followup_message_count == 0

    def test_malformed_event_tolerant(self):
        """Tolerate malformed events without crashing."""
        events = [
            "not a dict",
            {},
            {"kind": "MessageEvent"},  # Missing source
            {"kind": "MessageEvent", "source": "user"},  # Missing llm_message (0 words, counts as initial)
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {"content": "not a list"},  # 0 words (follow-up)
            },
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [{"type": "text", "text": "Valid message"}]
                },  # 2 words (follow-up)
            },
        ]
        metrics = count_human_input(events)
        # First user message (even malformed) counts as initial with 0 words
        assert metrics.initial_prompt_words == 0
        # Subsequent user messages are follow-ups
        assert metrics.followup_message_count == 2
        assert metrics.followup_word_count == 2  # Only the valid one contributes words

    def test_whitespace_splitting(self):
        """Word counts use whitespace splitting."""
        events = [
            {
                "kind": "MessageEvent",
                "source": "user",
                "llm_message": {
                    "content": [
                        {"type": "text", "text": "one  two   three"}
                    ]  # Multiple spaces
                },
            }
        ]
        metrics = count_human_input(events)
        assert metrics.initial_prompt_words == 3


class TestHumanInputMetrics:
    """Tests for HumanInputMetrics dataclass."""

    def test_dataclass_creation(self):
        """Create HumanInputMetrics instance."""
        metrics = HumanInputMetrics(
            initial_prompt_words=10, followup_word_count=20, followup_message_count=3
        )
        assert metrics.initial_prompt_words == 10
        assert metrics.followup_word_count == 20
        assert metrics.followup_message_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
