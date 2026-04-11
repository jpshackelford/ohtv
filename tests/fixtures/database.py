"""Fixtures for pre-populated database states.

Provides factory functions and builders for creating test database states.
"""

import sqlite3

from ohtv.db import migrate
from ohtv.db.models import Conversation, LinkType, Reference, RefType, Repository
from ohtv.db.stores import ConversationStore, LinkStore, ReferenceStore, RepoStore


def create_test_db() -> sqlite3.Connection:
    """Create a fresh in-memory database with migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


class DatabaseBuilder:
    """Builder for creating pre-populated test databases.
    
    Usage:
        db = (DatabaseBuilder()
            .with_conversation("conv-1", "/path/to/conv-1")
            .with_repo("https://github.com/owner/repo", "owner/repo", "repo")
            .with_link_repo("conv-1", "https://github.com/owner/repo", LinkType.WRITE)
            .build())
    """
    
    def __init__(self):
        self._conn = create_test_db()
        self._repos: dict[str, int] = {}  # url -> id
        self._refs: dict[str, int] = {}   # url -> id
    
    def with_conversation(self, conv_id: str, location: str) -> "DatabaseBuilder":
        """Add a conversation to the database."""
        store = ConversationStore(self._conn)
        store.upsert(Conversation(id=conv_id, location=location))
        return self
    
    def with_repo(
        self, canonical_url: str, fqn: str, short_name: str
    ) -> "DatabaseBuilder":
        """Add a repository to the database."""
        store = RepoStore(self._conn)
        repo_id = store.upsert(Repository(
            id=None,
            canonical_url=canonical_url,
            fqn=fqn,
            short_name=short_name,
        ))
        self._repos[canonical_url] = repo_id
        return self
    
    def with_issue(
        self, url: str, fqn: str, display_name: str
    ) -> "DatabaseBuilder":
        """Add an issue reference to the database."""
        store = ReferenceStore(self._conn)
        ref_id = store.upsert(Reference(
            id=None,
            ref_type=RefType.ISSUE,
            url=url,
            fqn=fqn,
            display_name=display_name,
        ))
        self._refs[url] = ref_id
        return self
    
    def with_pr(
        self, url: str, fqn: str, display_name: str
    ) -> "DatabaseBuilder":
        """Add a PR reference to the database."""
        store = ReferenceStore(self._conn)
        ref_id = store.upsert(Reference(
            id=None,
            ref_type=RefType.PR,
            url=url,
            fqn=fqn,
            display_name=display_name,
        ))
        self._refs[url] = ref_id
        return self
    
    def with_link_repo(
        self, conv_id: str, repo_url: str, link_type: LinkType
    ) -> "DatabaseBuilder":
        """Link a conversation to a repository."""
        if repo_url not in self._repos:
            raise ValueError(f"Repo not found: {repo_url}. Add it with with_repo() first.")
        store = LinkStore(self._conn)
        store.link_repo(conv_id, self._repos[repo_url], link_type)
        return self
    
    def with_link_ref(
        self, conv_id: str, ref_url: str, link_type: LinkType
    ) -> "DatabaseBuilder":
        """Link a conversation to a reference (issue or PR)."""
        if ref_url not in self._refs:
            raise ValueError(f"Ref not found: {ref_url}. Add it with with_issue() or with_pr() first.")
        store = LinkStore(self._conn)
        store.link_ref(conv_id, self._refs[ref_url], link_type)
        return self
    
    def build(self) -> sqlite3.Connection:
        """Finalize and return the database connection."""
        self._conn.commit()
        return self._conn


# Pre-built database states for common test scenarios

def empty_db() -> sqlite3.Connection:
    """Empty database with only migrations applied."""
    return create_test_db()


def db_with_single_conversation() -> sqlite3.Connection:
    """Database with one conversation, no links."""
    return (DatabaseBuilder()
        .with_conversation("conv-1", "/path/to/conv-1")
        .build())


def db_with_github_refs() -> sqlite3.Connection:
    """Database with a conversation linked to GitHub repo, issue, and PR.
    
    This matches the sample conversation in fixtures/conversations/conv-with-github-refs/
    """
    return (DatabaseBuilder()
        .with_conversation("conv-with-github-refs", "/conversations/conv-with-github-refs")
        .with_repo("https://github.com/acme/webapp", "acme/webapp", "webapp")
        .with_issue(
            "https://github.com/acme/webapp/issues/42",
            "acme/webapp#42",
            "webapp #42"
        )
        .with_pr(
            "https://github.com/acme/webapp/pull/99",
            "acme/webapp#99",
            "webapp #99"
        )
        .with_link_repo("conv-with-github-refs", "https://github.com/acme/webapp", LinkType.WRITE)
        .with_link_ref("conv-with-github-refs", "https://github.com/acme/webapp/issues/42", LinkType.READ)
        .with_link_ref("conv-with-github-refs", "https://github.com/acme/webapp/pull/99", LinkType.WRITE)
        .build())
