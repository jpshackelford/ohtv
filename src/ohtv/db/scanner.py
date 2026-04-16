"""Conversation scanner for discovering and registering conversations.

Scans the filesystem for conversations and updates the database with
current state (location, mtime, event count, and metadata). Uses mtime
as a fast filter to skip unchanged conversations.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ohtv.config import get_openhands_dir
from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore


@dataclass
class ScanResult:
    """Result of a scan operation."""
    total_on_disk: int
    new_registered: int
    updated: int
    unchanged: int
    removed: int


def count_events(events_dir: Path) -> int:
    """Count event files in a conversation's events directory."""
    if not events_dir.exists():
        return 0
    return sum(1 for f in events_dir.iterdir() if f.name.startswith("event-"))


def get_events_mtime(events_dir: Path) -> float | None:
    """Get the modification time of the events directory."""
    if not events_dir.exists():
        return None
    return events_dir.stat().st_mtime


def discover_conversations(base_dir: Path, source: str) -> list[tuple[str, Path, str]]:
    """Discover conversation directories under a base path.
    
    Returns list of (conversation_id, conversation_path, source) tuples.
    Looks for directories containing an 'events' subdirectory.
    """
    conversations = []
    if not base_dir.exists():
        return conversations
    
    for entry in base_dir.iterdir():
        if entry.is_dir():
            events_dir = entry / "events"
            if events_dir.exists() and events_dir.is_dir():
                conversations.append((entry.name, entry, source))
    
    return conversations


def extract_metadata(conv_path: Path, source: str) -> dict:
    """Extract metadata from a conversation directory.
    
    Args:
        conv_path: Path to conversation directory
        source: Source identifier ('local' or 'cloud')
    
    Returns:
        Dict with title, created_at, updated_at, selected_repository
    """
    timestamps_are_utc = source != "local"
    
    title = None
    selected_repository = None
    created_at = None
    updated_at = None
    
    # Try to read from base_state.json
    base_state = conv_path / "base_state.json"
    if base_state.exists():
        try:
            data = json.loads(base_state.read_text())
            title = data.get("title")
            selected_repository = data.get("selected_repository")
            created_at = _parse_datetime(data.get("created_at"), timestamps_are_utc)
            updated_at = _parse_datetime(data.get("updated_at"), timestamps_are_utc)
        except (json.JSONDecodeError, OSError):
            pass
    
    # Prefer timestamps from events for accuracy
    event_timestamps = _get_event_timestamps(conv_path, timestamps_are_utc)
    if event_timestamps:
        created_at = event_timestamps[0]
        updated_at = event_timestamps[1]
    
    # Last resort: file mtime
    if created_at is None and base_state.exists():
        try:
            file_mtime = datetime.fromtimestamp(base_state.stat().st_mtime, tz=timezone.utc)
            created_at = file_mtime
            updated_at = file_mtime
        except OSError:
            pass
    
    # Get title from first user message if not present
    if not title:
        title = _get_title_from_first_user_message(conv_path)
    
    return {
        "title": title,
        "created_at": created_at,
        "updated_at": updated_at,
        "selected_repository": selected_repository,
    }


def _parse_datetime(value: str | None, assume_utc: bool = True) -> datetime | None:
    """Parse ISO 8601 datetime string."""
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
        local_dt = naive_dt.astimezone()
        return local_dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _get_event_timestamps(conv_path: Path, timestamps_are_utc: bool) -> tuple[datetime, datetime] | None:
    """Get first and last event timestamps."""
    events_dir = conv_path / "events"
    if not events_dir.exists():
        return None
    
    event_files = sorted(events_dir.glob("event-*.json"))
    if not event_files:
        return None
    
    first_ts = _get_event_timestamp(event_files[0], timestamps_are_utc)
    last_ts = _get_event_timestamp(event_files[-1], timestamps_are_utc)
    
    if first_ts and last_ts:
        return (first_ts, last_ts)
    return None


def _get_event_timestamp(event_file: Path, timestamps_are_utc: bool) -> datetime | None:
    """Extract timestamp from an event file."""
    try:
        data = json.loads(event_file.read_text())
        return _parse_datetime(data.get("timestamp"), timestamps_are_utc)
    except (json.JSONDecodeError, OSError):
        return None


def _get_title_from_first_user_message(conv_path: Path, max_length: int = 60) -> str | None:
    """Extract title from the first user message."""
    events_dir = conv_path / "events"
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


def _truncate_title(text: str, max_length: int) -> str:
    """Truncate text to max_length, breaking at word boundary."""
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_length:
        return first_line
    truncated = first_line[:max_length].rsplit(" ", 1)[0]
    return truncated + "..."


def scan_conversations(
    conn: sqlite3.Connection,
    force: bool = False,
    remove_missing: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> ScanResult:
    """Scan filesystem for conversations and update database.
    
    Args:
        conn: Database connection
        force: If True, update all conversations regardless of mtime
        remove_missing: If True, remove DB entries for conversations no longer on disk
        on_progress: Optional callback(current, total, conv_id) for progress updates
        
    Returns:
        ScanResult with counts of what changed
    """
    store = ConversationStore(conn)
    openhands_dir = get_openhands_dir()
    
    # Discover from both local CLI and synced cloud locations
    local_dir = openhands_dir / "conversations"
    cloud_dir = openhands_dir / "cloud" / "conversations"
    
    all_discovered = []
    all_discovered.extend(discover_conversations(local_dir, "local"))
    all_discovered.extend(discover_conversations(cloud_dir, "cloud"))
    
    total = len(all_discovered)
    
    # Track IDs we've seen on disk
    seen_ids = set()
    
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    
    for i, (conv_id, conv_path, source) in enumerate(all_discovered):
        if on_progress:
            on_progress(i, total, conv_id)
        
        seen_ids.add(conv_id)
        events_dir = conv_path / "events"
        
        current_mtime = get_events_mtime(events_dir)
        current_count = count_events(events_dir)
        
        existing = store.get(conv_id)
        
        if existing is None:
            # New conversation - extract metadata
            metadata = extract_metadata(conv_path, source)
            store.upsert(Conversation(
                id=conv_id,
                location=str(conv_path),
                events_mtime=current_mtime,
                event_count=current_count,
                title=metadata["title"],
                created_at=metadata["created_at"],
                updated_at=metadata["updated_at"],
                selected_repository=metadata["selected_repository"],
                source=source,
            ))
            new_count += 1
        elif force or _has_changed(existing, current_mtime, current_count):
            # Changed or forced update - re-extract metadata
            metadata = extract_metadata(conv_path, source)
            store.upsert(Conversation(
                id=conv_id,
                location=str(conv_path),
                registered_at=existing.registered_at,  # Preserve original
                events_mtime=current_mtime,
                event_count=current_count,
                title=metadata["title"],
                created_at=metadata["created_at"],
                updated_at=metadata["updated_at"],
                selected_repository=metadata["selected_repository"],
                source=source,
            ))
            updated_count += 1
        else:
            unchanged_count += 1
    
    # Signal completion
    if on_progress:
        on_progress(total, total, "")
    
    # Handle missing conversations
    removed_count = 0
    if remove_missing:
        all_registered = store.list_all()
        for conv in all_registered:
            if conv.id not in seen_ids:
                store.delete(conv.id)
                removed_count += 1
    
    return ScanResult(
        total_on_disk=len(all_discovered),
        new_registered=new_count,
        updated=updated_count,
        unchanged=unchanged_count,
        removed=removed_count,
    )


def _has_changed(existing: Conversation, current_mtime: float | None, current_count: int) -> bool:
    """Check if a conversation has changed since last scan."""
    # If we don't have mtime info, assume changed
    if existing.events_mtime is None or current_mtime is None:
        return True
    
    # mtime increased means something changed
    if current_mtime > existing.events_mtime:
        return True
    
    # Event count changed (shouldn't happen without mtime change, but be safe)
    if current_count != existing.event_count:
        return True
    
    return False


def get_changed_conversations(conn: sqlite3.Connection) -> list[Conversation]:
    """Get conversations that have changed since last scan.
    
    Useful for finding conversations that need reprocessing without
    actually updating the database.
    """
    store = ConversationStore(conn)
    openhands_dir = get_openhands_dir()
    
    local_dir = openhands_dir / "conversations"
    cloud_dir = openhands_dir / "cloud" / "conversations"
    
    changed = []
    
    all_discovered = (
        discover_conversations(local_dir, "local") +
        discover_conversations(cloud_dir, "cloud")
    )
    
    for conv_id, conv_path, source in all_discovered:
        events_dir = conv_path / "events"
        current_mtime = get_events_mtime(events_dir)
        current_count = count_events(events_dir)
        
        existing = store.get(conv_id)
        
        if existing is None or _has_changed(existing, current_mtime, current_count):
            metadata = extract_metadata(conv_path, source)
            changed.append(Conversation(
                id=conv_id,
                location=str(conv_path),
                events_mtime=current_mtime,
                event_count=current_count,
                title=metadata["title"],
                created_at=metadata["created_at"],
                updated_at=metadata["updated_at"],
                selected_repository=metadata["selected_repository"],
                source=source,
            ))
    
    return changed
