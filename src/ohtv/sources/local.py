"""Local filesystem data source for conversations."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ohtv.sources.base import ConversationInfo

log = logging.getLogger("ohtv")


class LocalSource:
    """Read conversations from local filesystem."""

    def __init__(self, conversations_dir: Path, source_name: str = "local"):
        self.conversations_dir = conversations_dir
        self.source_name = source_name
        # Cloud conversations store timestamps in UTC, local CLI uses local time
        self._timestamps_are_utc = source_name != "local"

    def list_conversations(self) -> list[ConversationInfo]:
        """List all conversations in the directory."""
        if not self.conversations_dir.exists():
            log.debug("Conversations dir does not exist: %s", self.conversations_dir)
            return []

        conversations = []
        for conv_dir in self.conversations_dir.iterdir():
            if not conv_dir.is_dir():
                continue
            conv_info = self._load_conversation_info(conv_dir)
            if conv_info:
                conversations.append(conv_info)

        return conversations

    def _load_conversation_info(self, conv_dir: Path) -> ConversationInfo | None:
        """Load conversation info from a directory."""
        conv_id = conv_dir.name
        base_state = conv_dir / "base_state.json"

        title = None
        selected_repository = None

        if base_state.exists():
            try:
                data = json.loads(base_state.read_text())
                title = data.get("title")
                selected_repository = data.get("selected_repository")
                if data.get("id"):
                    conv_id = data["id"]
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to read base_state.json for %s: %s", conv_id, e)

        # Always derive timestamps from events for accurate duration
        # (base_state timestamps may not reflect actual conversation span)
        timestamps = self._get_event_timestamps(conv_dir)
        created_at = timestamps[0] if timestamps else None
        updated_at = timestamps[1] if timestamps else None

        # Fallback: get title from first user message if not present
        if not title:
            title = self._get_title_from_first_user_message(conv_dir)

        event_count = self._count_events(conv_dir)

        return ConversationInfo(
            id=conv_id,
            title=title,
            created_at=created_at,
            updated_at=updated_at,
            event_count=event_count,
            selected_repository=selected_repository,
            source=self.source_name,
        )

    def _count_events(self, conv_dir: Path) -> int:
        """Count events in a conversation directory."""
        events_dir = conv_dir / "events"
        if not events_dir.exists():
            return 0
        return len(list(events_dir.glob("event-*.json")))

    def _get_event_timestamps(self, conv_dir: Path) -> tuple[datetime, datetime] | None:
        """Get first and last event timestamps."""
        events_dir = conv_dir / "events"
        if not events_dir.exists():
            return None

        event_files = sorted(events_dir.glob("event-*.json"))
        if not event_files:
            return None

        first_ts = self._get_event_timestamp(event_files[0])
        last_ts = self._get_event_timestamp(event_files[-1])

        if first_ts and last_ts:
            return (first_ts, last_ts)
        return None

    def _get_event_timestamp(self, event_file: Path) -> datetime | None:
        """Extract timestamp from an event file."""
        try:
            data = json.loads(event_file.read_text())
            return _parse_datetime(data.get("timestamp"), assume_utc=self._timestamps_are_utc)
        except (json.JSONDecodeError, OSError):
            return None

    def _get_title_from_first_user_message(self, conv_dir: Path, max_length: int = 60) -> str | None:
        """Extract title from the first user message."""
        events_dir = conv_dir / "events"
        if not events_dir.exists():
            return None

        for event_file in sorted(events_dir.glob("event-*.json")):
            try:
                data = json.loads(event_file.read_text())
                if data.get("source") != "user":
                    continue

                # Try llm_message.content[].text format (cloud)
                llm_msg = data.get("llm_message", {})
                content = llm_msg.get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            return _truncate_title(text, max_length)

                # Try direct content field (local CLI format)
                if data.get("content"):
                    return _truncate_title(data["content"], max_length)

            except (json.JSONDecodeError, OSError):
                continue

        return None


def _parse_datetime(value: str | None, assume_utc: bool = True) -> datetime | None:
    """Parse ISO 8601 datetime string.

    Args:
        value: ISO 8601 datetime string
        assume_utc: If True, treat naive timestamps as UTC.
                    If False, treat as local time and convert to UTC.
    """
    if not value:
        return None
    value = value.rstrip("Z")
    if "+" in value:
        value = value.split("+")[0]
    try:
        naive_dt = datetime.fromisoformat(value)
        if assume_utc:
            return naive_dt.replace(tzinfo=timezone.utc)
        # Treat as local time, then convert to UTC
        local_dt = naive_dt.astimezone()  # Attach local timezone
        return local_dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _truncate_title(text: str, max_length: int) -> str:
    """Truncate text to max_length, breaking at word boundary."""
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_length:
        return first_line
    truncated = first_line[:max_length].rsplit(" ", 1)[0]
    return truncated + "..."
