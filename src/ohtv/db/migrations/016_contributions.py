"""Database schema for contribution tracking.

Creates three tables for tracking PR/push contributions and human input metrics:

- change_refs: Tracks PRs and direct pushes to main (repo_id, change_type, pr_number, etc.)
- conversation_contributions: Links conversations to changes they contributed to
- conversation_human_input: Stores human word/message counts per conversation

These tables enable metrics collection for understanding contribution patterns
and human involvement in AI-assisted development workflows.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create contribution tracking tables."""

    # change_refs: Tracks PRs and direct pushes to main
    # Note: We use separate unique indexes instead of a composite unique constraint
    # because SQLite treats NULL as distinct in unique constraints, which would
    # allow duplicate entries when pr_number or commit_range is NULL.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS change_refs (
            id INTEGER PRIMARY KEY,
            repo_id INTEGER NOT NULL,
            change_type TEXT NOT NULL CHECK(change_type IN ('pr', 'direct_push')),
            pr_number INTEGER,
            commit_range TEXT,
            branch TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            merged_at TEXT,
            lines_added INTEGER,
            lines_removed INTEGER,
            files_changed INTEGER,
            fetched_at TEXT,
            FOREIGN KEY (repo_id) REFERENCES repositories(id),
            -- Enforce that PRs have pr_number and direct_pushes have commit_range
            CHECK (
                (change_type = 'pr' AND pr_number IS NOT NULL) OR
                (change_type = 'direct_push' AND commit_range IS NOT NULL)
            )
        )
    """)
    # Separate unique indexes to properly prevent duplicates:
    # - PRs are unique by repo_id + pr_number
    # - Direct pushes are unique by repo_id + commit_range
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_change_refs_pr_unique ON change_refs(repo_id, pr_number) WHERE change_type = 'pr'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_change_refs_push_unique ON change_refs(repo_id, commit_range) WHERE change_type = 'direct_push'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_refs_repo ON change_refs(repo_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_refs_type ON change_refs(change_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_change_refs_status ON change_refs(status)")

    # conversation_contributions: Links conversations to changes they contributed to
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_contributions (
            id INTEGER PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            change_ref_id INTEGER NOT NULL,
            contribution_type TEXT NOT NULL CHECK(contribution_type IN ('created', 'pushed', 'merged')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (change_ref_id) REFERENCES change_refs(id),
            UNIQUE (conversation_id, change_ref_id, contribution_type)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_contributions_conv ON conversation_contributions(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_contributions_change ON conversation_contributions(change_ref_id)")

    # conversation_human_input: Stores human word/message counts per conversation
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_human_input (
            conversation_id TEXT PRIMARY KEY,
            initial_prompt_words INTEGER NOT NULL DEFAULT 0,
            initial_prompt_source TEXT NOT NULL DEFAULT 'unknown' CHECK(initial_prompt_source IN ('human', 'automation', 'unknown')),
            followup_word_count INTEGER NOT NULL DEFAULT 0,
            followup_message_count INTEGER NOT NULL DEFAULT 0,
            processed_at TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_human_input_source ON conversation_human_input(initial_prompt_source)")
