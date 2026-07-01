"""Human input counting - separates initial prompt from follow-up messages.

Word counts use whitespace splitting (str.split()) for simple, reproducible
counts. Non-text content items are ignored.
"""

from dataclasses import dataclass


@dataclass
class HumanInputMetrics:
    """Word and message counts for human input in a conversation.

    Attributes:
        initial_prompt_words: Word count of the first user message
        followup_word_count: Total words across all follow-up user messages
        followup_message_count: Number of follow-up user messages (not including initial)
    """

    initial_prompt_words: int
    followup_word_count: int
    followup_message_count: int


def count_human_input(events: list[dict]) -> HumanInputMetrics:
    """Count human input, separating initial prompt from follow-ups.

    The first MessageEvent with source == "user" is treated as the initial
    prompt. All subsequent user messages are follow-ups.

    Word counts use whitespace splitting (str.split()) for simple,
    reproducible counts. Non-text content items are ignored.

    Malformed events (missing/wrong-typed fields) are tolerated and
    contribute zero words.

    Args:
        events: Ordered list of conversation events (from event-*.json files).

    Returns:
        HumanInputMetrics with separate counts for initial prompt and
        follow-up messages.

    Example:
        >>> events = [
        ...     {"kind": "MessageEvent", "source": "user",
        ...      "llm_message": {"content": [{"type": "text", "text": "Hello world"}]}},
        ...     {"kind": "MessageEvent", "source": "assistant",
        ...      "llm_message": {"content": [{"type": "text", "text": "Hi there"}]}},
        ...     {"kind": "MessageEvent", "source": "user",
        ...      "llm_message": {"content": [{"type": "text", "text": "How are you"}]}},
        ... ]
        >>> metrics = count_human_input(events)
        >>> metrics.initial_prompt_words
        2
        >>> metrics.followup_message_count
        1
        >>> metrics.followup_word_count
        3
    """
    initial_prompt_words = 0
    followup_word_count = 0
    followup_message_count = 0
    found_initial = False

    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("kind") != "MessageEvent":
            continue
        if event.get("source") != "user":
            continue

        words = _count_words_in_message(event)

        if not found_initial:
            initial_prompt_words = words
            found_initial = True
        else:
            followup_word_count += words
            followup_message_count += 1

    return HumanInputMetrics(
        initial_prompt_words=initial_prompt_words,
        followup_word_count=followup_word_count,
        followup_message_count=followup_message_count,
    )


def _count_words_in_message(event: dict) -> int:
    """Extract text from a MessageEvent and return word count.

    Text is read from llm_message.content[].text where type is "text".
    Multiple text items in the same message are summed.

    Args:
        event: MessageEvent dictionary

    Returns:
        Total word count across all text content items
    """
    llm_message = event.get("llm_message")
    if not isinstance(llm_message, dict):
        return 0

    content_list = llm_message.get("content")
    if not isinstance(content_list, list):
        return 0

    words = 0
    for item in content_list:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            words += len(text.split())
    return words
