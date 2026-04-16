"""Unified conversation listing with database-first approach.

This module provides a single entry point for listing conversations that:
1. Uses the database when available and populated (fast)
2. Falls back to filesystem when database is unavailable (slower)
3. Returns ConversationInfo objects compatible with existing code

The database stores metadata (title, timestamps) that would otherwise
require reading multiple files per conversation.
"""

import logging
from datetime import datetime
from pathlib import Path

from ohtv.config import Config
from ohtv.sources.base import ConversationInfo

log = logging.getLogger("ohtv")


def get_conversations(
    config: Config,
    since: datetime | None = None,
    until: datetime | None = None,
    source: str | None = None,
    use_db: bool = True,
) -> list[ConversationInfo]:
    """Get conversations with optional filtering.
    
    Uses database when available for fast metadata access.
    Falls back to filesystem scanning when database is unavailable.
    
    Args:
        config: Application configuration
        since: Include conversations created on or after this time
        until: Include conversations created before this time
        source: Filter by source ('local', 'cloud', or None for all)
        use_db: If True (default), try database first. If False, always use filesystem.
    
    Returns:
        List of ConversationInfo objects, sorted by created_at descending
    """
    if use_db:
        try:
            conversations = _get_conversations_from_db(config, since, until, source)
            if conversations is not None:
                log.debug("Listed %d conversations from database", len(conversations))
                return conversations
        except Exception as e:
            log.debug("Database listing failed, falling back to filesystem: %s", e)
    
    # Fallback to filesystem
    conversations = _get_conversations_from_filesystem(config, source)
    
    # Apply date filters manually
    if since:
        conversations = [c for c in conversations if c.created_at and c.created_at >= since]
    if until:
        conversations = [c for c in conversations if c.created_at and c.created_at < until]
    
    log.debug("Listed %d conversations from filesystem", len(conversations))
    return conversations


def _get_conversations_from_db(
    config: Config,
    since: datetime | None,
    until: datetime | None,
    source: str | None,
) -> list[ConversationInfo] | None:
    """Get conversations from database.
    
    Returns None if database is unavailable or empty.
    Automatically runs migrations and maintenance tasks if needed.
    """
    from ohtv.db import get_connection, get_db_path, ensure_db_ready
    from ohtv.db.stores import ConversationStore
    
    db_path = get_db_path()
    if not db_path.exists():
        return None
    
    with get_connection() as conn:
        # Run migrations and any pending maintenance (like metadata backfill)
        ensure_db_ready(conn, show_progress=True)
        
        store = ConversationStore(conn)
        
        # Check if database has metadata populated
        if store.count_with_metadata() == 0:
            log.debug("Database has no metadata, falling back to filesystem")
            return None
        
        # Query with filters
        db_conversations = store.list_by_date_range(since=since, until=until, source=source)
        
        # Convert to ConversationInfo
        return [_db_conv_to_info(c) for c in db_conversations]


def _db_conv_to_info(db_conv) -> ConversationInfo:
    """Convert database Conversation to ConversationInfo."""
    from ohtv.db.models import Conversation
    
    # Format ID with dashes for compatibility
    conv_id = db_conv.id
    if len(conv_id) == 32 and "-" not in conv_id:
        conv_id = f"{conv_id[:8]}-{conv_id[8:12]}-{conv_id[12:16]}-{conv_id[16:20]}-{conv_id[20:]}"
    
    return ConversationInfo(
        id=conv_id,
        title=db_conv.title,
        created_at=db_conv.created_at,
        updated_at=db_conv.updated_at,
        event_count=db_conv.event_count,
        selected_repository=db_conv.selected_repository,
        source=db_conv.source or "local",
        dir_name=db_conv.id,  # Directory name is ID without dashes
    )


def _get_conversations_from_filesystem(
    config: Config,
    source: str | None,
) -> list[ConversationInfo]:
    """Get conversations by scanning filesystem (slow path)."""
    from ohtv.sources import LocalSource
    
    conversations = []
    
    # Collect from requested sources
    if source is None or source == "local":
        local_source = LocalSource(config.local_conversations_dir, "local")
        conversations.extend(local_source.list_conversations())
    
    if source is None or source == "cloud":
        cloud_source = LocalSource(config.synced_conversations_dir, "cloud")
        conversations.extend(cloud_source.list_conversations())
    
    # Extra paths (if configured)
    if source is None:
        for extra_path in config.extra_conversation_paths:
            extra_source = LocalSource(extra_path, extra_path.name)
            conversations.extend(extra_source.list_conversations())
    
    # Sort by created_at descending
    def sort_key(c):
        if c.created_at is None:
            return datetime.min
        return c.created_at
    
    conversations.sort(key=sort_key, reverse=True)
    
    return conversations


def is_db_available_with_metadata() -> bool:
    """Check if database is available and has metadata populated.
    
    Useful for determining whether fast path is available.
    Note: This doesn't run maintenance - use get_conversations() for that.
    """
    try:
        from ohtv.db import get_connection, get_db_path, migrate
        from ohtv.db.stores import ConversationStore
        from ohtv.db.maintenance import get_pending_tasks
        
        db_path = get_db_path()
        if not db_path.exists():
            return False
        
        with get_connection() as conn:
            migrate(conn)
            
            # If there are pending maintenance tasks, we may need to run them
            # Return True so that get_conversations() will run them
            pending = get_pending_tasks(conn)
            if pending:
                return True  # Let get_conversations handle maintenance
            
            store = ConversationStore(conn)
            return store.count_with_metadata() > 0
    except Exception:
        return False
