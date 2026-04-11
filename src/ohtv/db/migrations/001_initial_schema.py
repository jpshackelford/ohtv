"""Initial schema for conversation indexing.

Creates tables for:
- conversations: Basic tracking with ID and disk location
- repositories: Git repos with canonical URL, FQN, and short name
- references: Unified table for issues, PRs, etc. with type discriminator
- conversation_repos: Links between conversations and repos
- conversation_refs: Links between conversations and references

Link tables track whether the relationship is READ or WRITE.
WRITE implies READ, so only one link type per relationship.
"""

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply the initial schema."""
    
    # Conversations: minimal tracking - ID and location only
    conn.execute("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL
        )
    """)
    
    # Repositories: canonical URL, FQN (owner/repo), short name (repo)
    conn.execute("""
        CREATE TABLE repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_url TEXT NOT NULL UNIQUE,
            fqn TEXT NOT NULL,
            short_name TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_repos_fqn ON repositories(fqn)")
    conn.execute("CREATE INDEX idx_repos_short_name ON repositories(short_name)")
    
    # Refs: unified table for issues, PRs, and future types
    # ref_type: 'issue', 'pr', etc. (extensible)
    conn.execute("""
        CREATE TABLE refs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_type TEXT NOT NULL CHECK(ref_type IN ('issue', 'pr')),
            url TEXT NOT NULL UNIQUE,
            fqn TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_refs_type ON refs(ref_type)")
    conn.execute("CREATE INDEX idx_refs_fqn ON refs(fqn)")
    
    # Link table: conversations <-> repositories
    # link_type: 'read' or 'write' (write implies read)
    conn.execute("""
        CREATE TABLE conversation_repos (
            conversation_id TEXT NOT NULL,
            repo_id INTEGER NOT NULL,
            link_type TEXT NOT NULL CHECK(link_type IN ('read', 'write')),
            PRIMARY KEY (conversation_id, repo_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_conv_repos_repo ON conversation_repos(repo_id)")
    
    # Link table: conversations <-> refs (issues, PRs, etc.)
    conn.execute("""
        CREATE TABLE conversation_refs (
            conversation_id TEXT NOT NULL,
            ref_id INTEGER NOT NULL,
            link_type TEXT NOT NULL CHECK(link_type IN ('read', 'write')),
            PRIMARY KEY (conversation_id, ref_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (ref_id) REFERENCES refs(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_conv_refs_ref ON conversation_refs(ref_id)")
