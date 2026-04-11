"""Initial schema for conversation indexing.

Creates tables for:
- conversations: Basic tracking with ID and disk location
- repositories: Git repos with canonical URL, FQN, and short name
- issues: Issue references with URL, FQN, and display name
- pull_requests: PR references with URL, FQN, and display name
- conversation_repos: Links between conversations and repos
- conversation_issues: Links between conversations and issues
- conversation_prs: Links between conversations and PRs

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
    
    # Issues: URL, FQN (owner/repo#123), display name (repo #123)
    conn.execute("""
        CREATE TABLE issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            fqn TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_issues_fqn ON issues(fqn)")
    
    # Pull requests: URL, FQN (owner/repo#456), display name (repo #456)
    conn.execute("""
        CREATE TABLE pull_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            fqn TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_prs_fqn ON pull_requests(fqn)")
    
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
    
    # Link table: conversations <-> issues
    conn.execute("""
        CREATE TABLE conversation_issues (
            conversation_id TEXT NOT NULL,
            issue_id INTEGER NOT NULL,
            link_type TEXT NOT NULL CHECK(link_type IN ('read', 'write')),
            PRIMARY KEY (conversation_id, issue_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_conv_issues_issue ON conversation_issues(issue_id)")
    
    # Link table: conversations <-> pull requests
    conn.execute("""
        CREATE TABLE conversation_prs (
            conversation_id TEXT NOT NULL,
            pr_id INTEGER NOT NULL,
            link_type TEXT NOT NULL CHECK(link_type IN ('read', 'write')),
            PRIMARY KEY (conversation_id, pr_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (pr_id) REFERENCES pull_requests(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX idx_conv_prs_pr ON conversation_prs(pr_id)")
