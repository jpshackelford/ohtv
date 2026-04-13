"""Add 'branch' to ref_type CHECK constraint.

Branches are now tracked as first-class refs, enabling:
- Branch refs visible in `ohtv refs` output
- Foundation for push-to-PR correlation
- Tracking branches worked on in conversations

SQLite doesn't support modifying CHECK constraints directly, so we need to
recreate the refs table with the updated constraint.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add branch to ref_type CHECK constraint."""
    
    # SQLite doesn't support ALTER CHECK CONSTRAINT, so we recreate the table
    
    # 1. Create new table with updated constraint
    conn.execute("""
        CREATE TABLE refs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_type TEXT NOT NULL CHECK(ref_type IN ('issue', 'pr', 'branch')),
            url TEXT UNIQUE NOT NULL,
            fqn TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
    """)
    
    # 2. Copy existing data
    conn.execute("""
        INSERT INTO refs_new (id, ref_type, url, fqn, display_name)
        SELECT id, ref_type, url, fqn, display_name FROM refs
    """)
    
    # 3. Drop old table
    conn.execute("DROP TABLE refs")
    
    # 4. Rename new table
    conn.execute("ALTER TABLE refs_new RENAME TO refs")
    
    # 5. Recreate index
    conn.execute("CREATE INDEX idx_refs_type ON refs(ref_type)")
