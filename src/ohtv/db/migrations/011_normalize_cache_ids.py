"""Migration 011: Normalize conversation IDs in analysis_cache.

This migration fixes a bug where some conversation IDs in analysis_cache
were stored with dashes while embeddings use normalized (no-dash) IDs.
This caused false "missing embeddings" reports because the JOIN couldn't
match dashed IDs to their corresponding embeddings.

The fix:
1. For each dashed entry, check if a normalized entry with same cache_key exists
2. If normalized exists, delete the dashed duplicate
3. If normalized doesn't exist, update the dashed entry to use normalized ID
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Normalize dashed conversation IDs in analysis_cache table."""
    cursor = conn.cursor()
    
    # Find all dashed entries
    cursor.execute(
        """
        SELECT conversation_id, cache_key
        FROM analysis_cache
        WHERE conversation_id LIKE '%-%'
        """
    )
    dashed_entries = cursor.fetchall()
    
    if not dashed_entries:
        return  # Nothing to migrate
    
    deleted = 0
    updated = 0
    
    for conv_id, cache_key in dashed_entries:
        normalized_id = conv_id.replace("-", "")
        
        # Check if normalized version exists
        cursor.execute(
            """
            SELECT 1 FROM analysis_cache
            WHERE conversation_id = ? AND cache_key = ?
            """,
            (normalized_id, cache_key),
        )
        normalized_exists = cursor.fetchone() is not None
        
        if normalized_exists:
            # Delete the dashed duplicate
            cursor.execute(
                """
                DELETE FROM analysis_cache
                WHERE conversation_id = ? AND cache_key = ?
                """,
                (conv_id, cache_key),
            )
            deleted += 1
        else:
            # Update dashed to normalized
            cursor.execute(
                """
                UPDATE analysis_cache
                SET conversation_id = ?
                WHERE conversation_id = ? AND cache_key = ?
                """,
                (normalized_id, conv_id, cache_key),
            )
            updated += 1
    
    conn.commit()
    
    # Log results (visible in debug logs)
    import logging
    log = logging.getLogger("ohtv")
    log.info(
        "Migration 011: Normalized %d dashed entries (deleted=%d duplicates, updated=%d)",
        len(dashed_entries), deleted, updated,
    )
