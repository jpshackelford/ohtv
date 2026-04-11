"""Conversation scanner for discovering and registering conversations.

Scans the filesystem for conversations and updates the database with
current state (location, mtime, event count). Uses mtime as a fast
filter to skip unchanged conversations.
"""

import sqlite3
from dataclasses import dataclass
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


def discover_conversations(base_dir: Path) -> list[tuple[str, Path]]:
    """Discover conversation directories under a base path.
    
    Returns list of (conversation_id, conversation_path) tuples.
    Looks for directories containing an 'events' subdirectory.
    """
    conversations = []
    if not base_dir.exists():
        return conversations
    
    for entry in base_dir.iterdir():
        if entry.is_dir():
            events_dir = entry / "events"
            if events_dir.exists() and events_dir.is_dir():
                conversations.append((entry.name, entry))
    
    return conversations


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
    all_discovered.extend(discover_conversations(local_dir))
    all_discovered.extend(discover_conversations(cloud_dir))
    
    total = len(all_discovered)
    
    # Track IDs we've seen on disk
    seen_ids = set()
    
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    
    for i, (conv_id, conv_path) in enumerate(all_discovered):
        if on_progress:
            on_progress(i, total, conv_id)
        
        seen_ids.add(conv_id)
        events_dir = conv_path / "events"
        
        current_mtime = get_events_mtime(events_dir)
        current_count = count_events(events_dir)
        
        existing = store.get(conv_id)
        
        if existing is None:
            # New conversation
            store.upsert(Conversation(
                id=conv_id,
                location=str(conv_path),
                events_mtime=current_mtime,
                event_count=current_count,
            ))
            new_count += 1
        elif force or _has_changed(existing, current_mtime, current_count):
            # Changed or forced update
            store.upsert(Conversation(
                id=conv_id,
                location=str(conv_path),
                registered_at=existing.registered_at,  # Preserve original
                events_mtime=current_mtime,
                event_count=current_count,
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
    
    for conv_id, conv_path in discover_conversations(local_dir) + discover_conversations(cloud_dir):
        events_dir = conv_path / "events"
        current_mtime = get_events_mtime(events_dir)
        current_count = count_events(events_dir)
        
        existing = store.get(conv_id)
        
        if existing is None or _has_changed(existing, current_mtime, current_count):
            changed.append(Conversation(
                id=conv_id,
                location=str(conv_path),
                events_mtime=current_mtime,
                event_count=current_count,
            ))
    
    return changed
