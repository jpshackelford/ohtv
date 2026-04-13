"""Fixtures for pre-populated database states.

Provides:
- YAML-based fixture loading (preferred for test data)
- DatabaseBuilder for programmatic construction (when needed)
"""

import sqlite3
from pathlib import Path

import yaml

from ohtv.db import migrate
from ohtv.db.models import Conversation, LinkType, Reference, RefType, Repository
from ohtv.db.stores import ConversationStore, LinkStore, ReferenceStore, RepoStore

DB_STATES_DIR = Path(__file__).parent / "db_states"


def create_test_db() -> sqlite3.Connection:
    """Create a fresh in-memory database with migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def load_db_state(name: str) -> sqlite3.Connection:
    """Load a database state from a YAML fixture file.
    
    Args:
        name: Name of the fixture file (without .yaml extension)
              e.g., "github_refs" loads db_states/github_refs.yaml
    
    Returns:
        In-memory database connection with the fixture data loaded
        
    Example YAML format:
        conversations:
          - id: conv-1
            location: /path/to/conv-1
        
        repositories:
          - canonical_url: https://github.com/owner/repo
            fqn: owner/repo
            short_name: repo
        
        references:
          - type: issue  # or "pr"
            url: https://github.com/owner/repo/issues/1
            fqn: owner/repo#1
            display_name: repo #1
        
        links:
          repos:
            - conversation: conv-1
              repo_url: https://github.com/owner/repo
              type: write  # or "read"
          refs:
            - conversation: conv-1
              ref_url: https://github.com/owner/repo/issues/1
              type: read
    """
    yaml_path = DB_STATES_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        available = [p.stem for p in DB_STATES_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"DB state fixture '{name}' not found. Available: {available}"
        )
    
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    
    conn = create_test_db()
    _load_yaml_data(conn, data)
    conn.commit()
    return conn


def _load_yaml_data(conn: sqlite3.Connection, data: dict) -> None:
    """Load YAML data into a database connection."""
    conv_store = ConversationStore(conn)
    repo_store = RepoStore(conn)
    ref_store = ReferenceStore(conn)
    link_store = LinkStore(conn)
    
    # Track IDs for linking
    repo_ids: dict[str, int] = {}
    ref_ids: dict[str, int] = {}
    
    # Load conversations
    for conv in data.get("conversations", []):
        conv_store.upsert(Conversation(id=conv["id"], location=conv["location"]))
    
    # Load repositories
    for repo in data.get("repositories", []):
        repo_id = repo_store.upsert(Repository(
            id=None,
            canonical_url=repo["canonical_url"],
            fqn=repo["fqn"],
            short_name=repo["short_name"],
        ))
        repo_ids[repo["canonical_url"]] = repo_id
    
    # Load references
    for ref in data.get("references", []):
        ref_type = RefType.ISSUE if ref["type"] == "issue" else RefType.PR
        ref_id = ref_store.upsert(Reference(
            id=None,
            ref_type=ref_type,
            url=ref["url"],
            fqn=ref["fqn"],
            display_name=ref["display_name"],
        ))
        ref_ids[ref["url"]] = ref_id
    
    # Load links
    links = data.get("links", {})
    
    for link in links.get("repos", []):
        link_type = LinkType.WRITE if link["type"] == "write" else LinkType.READ
        repo_id = repo_ids[link["repo_url"]]
        link_store.link_repo(link["conversation"], repo_id, link_type)
    
    for link in links.get("refs", []):
        link_type = LinkType.WRITE if link["type"] == "write" else LinkType.READ
        ref_id = ref_ids[link["ref_url"]]
        link_store.link_ref(link["conversation"], ref_id, link_type)


class DatabaseBuilder:
    """Builder for creating pre-populated test databases programmatically.
    
    Prefer YAML fixtures for static test data. Use this builder when you need
    dynamic or parameterized test data.
    
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


# Convenience functions for common states (now backed by YAML)

def empty_db() -> sqlite3.Connection:
    """Empty database with only migrations applied."""
    return load_db_state("empty")


def db_with_github_refs() -> sqlite3.Connection:
    """Database with a conversation linked to GitHub repo, issue, and PR."""
    return load_db_state("github_refs")


def db_with_multi_repo() -> sqlite3.Connection:
    """Database with multiple conversations across multiple repos."""
    return load_db_state("multi_repo")
