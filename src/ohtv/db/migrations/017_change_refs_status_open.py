"""Widen ``change_refs.status`` CHECK constraint to include ``'open'``.

PR #76 / migration 016 added the ``change_refs`` table with a CHECK
constraint of ``status IN ('pending', 'fetched', 'merged', 'closed')``.

Issue #80 (this PR) requires the ``ohtv fetch-loc`` command to set
``status='open'`` for PRs that are still open on GitHub, both because:

1. The issue body explicitly requires AC #11: *"For non-merged PRs the
   row's ``status`` is updated to ``open`` or ``closed``."*
2. The idempotency cache predicate also references ``open``:
   ``(change_type='pr' AND status IN ('merged','open','closed'))``.
   Without this status value, open PRs would never be considered
   "cached" and would be re-fetched on every run, breaking AC #5.

SQLite does not support ``ALTER TABLE ... DROP CHECK``, and renaming
the table breaks foreign-key references in dependent tables. We use
the canonical "12-step ALTER TABLE" pattern from
https://sqlite.org/lang_altertable.html#otheralter:

1. Disable FK enforcement (``PRAGMA foreign_keys = OFF``).
2. Create a *new* table under a temporary name with the wider CHECK.
3. Copy data from the original table.
4. Drop the original table.
5. Rename the new table to the original name. Because no other table
   references the temp name, this rename does not perturb any FKs.
6. Recreate the original indexes.
7. Re-enable FK enforcement.

Row IDs are preserved verbatim so any existing
``conversation_contributions.change_ref_id`` rows resolve correctly
after the swap.

This migration is intentionally minimal — no new columns, no new
indexes, no behavioural changes for already-stored rows. The only
delta is the broader value enum.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Recreate ``change_refs`` with a widened ``status`` CHECK constraint."""

    fk_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        # 1. Create the replacement table under a temporary name.
        #    Same shape as migration 016, plus ``'open'`` in the CHECK.
        conn.execute("""
            CREATE TABLE change_refs_new (
                id INTEGER PRIMARY KEY,
                repo_id INTEGER NOT NULL,
                change_type TEXT NOT NULL CHECK(change_type IN ('pr', 'direct_push')),
                pr_number INTEGER,
                commit_range TEXT,
                branch TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'fetched', 'merged', 'closed', 'open')),
                merged_at TEXT,
                lines_added INTEGER,
                lines_removed INTEGER,
                files_changed INTEGER,
                fetched_at TEXT,
                FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE,
                CHECK (
                    (change_type = 'pr' AND pr_number IS NOT NULL) OR
                    (change_type = 'direct_push' AND commit_range IS NOT NULL)
                )
            )
        """)

        # 2. Copy data, preserving primary keys.
        conn.execute("""
            INSERT INTO change_refs_new
                (id, repo_id, change_type, pr_number, commit_range, branch,
                 status, merged_at, lines_added, lines_removed,
                 files_changed, fetched_at)
            SELECT
                id, repo_id, change_type, pr_number, commit_range, branch,
                status, merged_at, lines_added, lines_removed,
                files_changed, fetched_at
            FROM change_refs
        """)

        # 3. Drop the original. This also drops the indexes attached to it.
        conn.execute("DROP TABLE change_refs")

        # 4. Rename the new table into place. No other table references
        #    ``change_refs_new``, so this rename does not modify any FK
        #    references in dependent tables.
        conn.execute("ALTER TABLE change_refs_new RENAME TO change_refs")

        # 5. Recreate the original indexes (they were dropped with the
        #    original table).
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_change_refs_pr_unique "
            "ON change_refs(repo_id, pr_number) WHERE change_type = 'pr'"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_change_refs_push_unique "
            "ON change_refs(repo_id, commit_range) "
            "WHERE change_type = 'direct_push'"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_change_refs_repo "
            "ON change_refs(repo_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_change_refs_type "
            "ON change_refs(change_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_change_refs_status "
            "ON change_refs(status)"
        )
    finally:
        if fk_enabled:
            conn.execute("PRAGMA foreign_keys = ON")
