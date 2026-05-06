"""Migration 012: Normalize conversation IDs in conversations table.

This migration fixes a bug where some conversation IDs were stored with dashes
(from base_state.json) while the scanner uses directory names (no dashes).
This caused duplicate entries in the conversations table.

Strategy:
1. Find all dashed conversation IDs that have a normalized counterpart
2. For those duplicates, delete all references to the dashed ID from child tables
3. Delete the dashed entry from conversations table
4. For dashed IDs without a normalized counterpart, update them and their references

The dashed entries typically have empty source/title fields because they were
created via _ensure_refs_indexed before the scanner processed them.
"""

import sqlite3
import logging

log = logging.getLogger("ohtv")

# Tables that have conversation_id foreign keys
CHILD_TABLES = [
    "conversation_repos",  # renamed from repo_links
    "conversation_refs",   # renamed from ref_links
    "actions",
    "conversation_stages",
    "analysis_cache",
    "analysis_skips",
    "embeddings",
]


def upgrade(conn: sqlite3.Connection) -> None:
    """Normalize dashed conversation IDs in conversations table."""
    cursor = conn.cursor()
    
    # Temporarily disable foreign key constraints for the bulk update
    cursor.execute("PRAGMA foreign_keys = OFF")
    
    try:
        # Find all dashed entries in conversations
        cursor.execute(
            """
            SELECT id FROM conversations WHERE id LIKE '%-%'
            """
        )
        dashed_entries = [row[0] for row in cursor.fetchall()]
        
        if not dashed_entries:
            log.info("Migration 012: No dashed conversation IDs found")
            return
        
        deleted_convs = 0
        updated_convs = 0
        
        for conv_id in dashed_entries:
            normalized_id = conv_id.replace("-", "")
            
            # Check if normalized version exists
            cursor.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (normalized_id,),
            )
            normalized_exists = cursor.fetchone() is not None
            
            if normalized_exists:
                # Delete records from child tables that reference the dashed ID
                for table in CHILD_TABLES:
                    if _table_exists(cursor, table):
                        cursor.execute(
                            f"DELETE FROM {table} WHERE conversation_id = ?",
                            (conv_id,),
                        )
                
                # Delete the dashed conversation entry
                cursor.execute(
                    "DELETE FROM conversations WHERE id = ?",
                    (conv_id,),
                )
                deleted_convs += 1
            else:
                # No normalized version - update this entry and all references
                for table in CHILD_TABLES:
                    if _table_exists(cursor, table):
                        cursor.execute(
                            f"UPDATE {table} SET conversation_id = ? WHERE conversation_id = ?",
                            (normalized_id, conv_id),
                        )
                
                cursor.execute(
                    "UPDATE conversations SET id = ? WHERE id = ?",
                    (normalized_id, conv_id),
                )
                updated_convs += 1
        
        conn.commit()
        
        log.info(
            "Migration 012: Normalized %d dashed conversation IDs "
            "(deleted=%d duplicates, updated=%d orphans)",
            len(dashed_entries), deleted_convs, updated_convs,
        )
    finally:
        # Re-enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None
