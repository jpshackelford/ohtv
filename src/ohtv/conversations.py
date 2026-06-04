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
    include_subs: bool = False,
    event_dates: bool = False,
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
        include_subs: When False (default, Issue #125), exclude
            agent-delegated sub-conversations from the result. On the
            DB path this is enforced via a SQL predicate against the
            ``root_conversation_id`` column (migration 020). On the
            filesystem fallback, sub/root identity is not recoverable
            from ``ConversationInfo`` alone, so the flag is logged and
            the FS path returns its rows unchanged — documented as
            "skip the FS roots filter cleanly" in the issue brief.
        event_dates: Issue #180. When True, interpret ``since`` / ``until``
            against ``conversation_engagement.last_event_ts`` /
            ``first_event_ts`` instead of ``conversations.created_at``.
            Conversations without an engagement row are excluded.
            Requires the DB path (no FS fallback semantics).

    Returns:
        List of ConversationInfo objects, sorted by created_at descending
    """
    if use_db:
        try:
            conversations = _get_conversations_from_db(
                config, since, until, source, include_subs, event_dates
            )
            if conversations is not None:
                log.debug("Listed %d conversations from database", len(conversations))
                return conversations
        except Exception as e:
            log.debug("Database listing failed, falling back to filesystem: %s", e)

    # Fallback to filesystem
    conversations = _get_conversations_from_filesystem(config, source)

    if not include_subs:
        # FS path has no parent/root metadata — the DB-first design
        # means this branch only runs when the DB is unavailable
        # (fresh checkout, or DB read failed above). Surface at
        # WARNING level so users notice the silent degradation:
        # the requested ``include_subs=False`` becomes a no-op here
        # and subs slip back into the result set (PR #154 review).
        log.warning(
            "Filesystem fallback cannot distinguish root vs sub conversations; "
            "include_subs=False has no effect. Run 'ohtv db scan' to enable "
            "roots-only filtering (Issue #125)."
        )

    if event_dates:
        # Issue #180: ``--event-dates`` reads from
        # ``conversation_engagement`` which only exists in the DB. On
        # the FS fallback we have no way to honor the column swap, so
        # the requested predicate would silently degrade to created_at.
        # Surface a WARNING — the same shape as the include_subs note
        # above — and proceed with created_at semantics so the caller
        # still gets a usable result rather than crashing.
        log.warning(
            "Filesystem fallback cannot honor --event-dates; falling back "
            "to conversations.created_at. Run 'ohtv db scan' and "
            "'ohtv db process engagement' (Issue #180)."
        )

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
    include_subs: bool = False,
    event_dates: bool = False,
) -> list[ConversationInfo] | None:
    """Get conversations from database.

    Returns None if database is unavailable or empty.
    Automatically runs migrations and maintenance tasks if needed.

    ``include_subs`` is plumbed through to
    :meth:`ConversationStore.list_by_date_range` — see Issue #125.

    ``event_dates`` (Issue #180) switches the date predicate from
    :meth:`ConversationStore.list_by_date_range` (filters on
    ``conversations.created_at``) to
    :meth:`ConversationStore.list_by_event_date_range` (filters on
    ``conversation_engagement.last_event_ts`` /
    ``first_event_ts``). The downstream method enforces the INNER JOIN
    against ``conversation_engagement`` so conversations without an
    engagement row are excluded.
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

        # Query with filters (Issue #180: column swap when event_dates=True)
        if event_dates:
            db_conversations = store.list_by_event_date_range(
                since=since,
                until=until,
                source=source,
                include_subs=include_subs,
            )
        else:
            db_conversations = store.list_by_date_range(
                since=since,
                until=until,
                source=source,
                include_subs=include_subs,
            )

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

    Useful for determining whether fast path is available. Maintenance is
    applied transparently via :func:`get_ready_connection` (AGENTS.md item
    #25), so this probe is safe to call on a fresh checkout.
    """
    try:
        from ohtv.db import get_db_path, get_ready_connection
        from ohtv.db.stores import ConversationStore

        db_path = get_db_path()
        if not db_path.exists():
            return False

        with get_ready_connection() as conn:
            store = ConversationStore(conn)
            return store.count_with_metadata() > 0
    except Exception:
        return False
