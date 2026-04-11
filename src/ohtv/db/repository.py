"""Repository pattern for database access.

Provides clean interfaces for CRUD operations on indexed entities.
"""

import sqlite3
from typing import Sequence

from ohtv.db.models import (
    Conversation,
    Issue,
    LinkType,
    PullRequest,
    Repository,
)


class ConversationRepository:
    """Data access for conversations."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, conversation: Conversation) -> None:
        """Insert or update a conversation."""
        self.conn.execute(
            "INSERT OR REPLACE INTO conversations (id, location) VALUES (?, ?)",
            (conversation.id, conversation.location),
        )
    
    def get(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        cursor = self.conn.execute(
            "SELECT id, location FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row:
            return Conversation(id=row["id"], location=row["location"])
        return None
    
    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if deleted."""
        cursor = self.conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return cursor.rowcount > 0


class RepoRepository:
    """Data access for repositories."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, repo: Repository) -> int:
        """Insert or update a repository. Returns the repo ID."""
        cursor = self.conn.execute(
            """
            INSERT INTO repositories (canonical_url, fqn, short_name)
            VALUES (?, ?, ?)
            ON CONFLICT(canonical_url) DO UPDATE SET
                fqn = excluded.fqn,
                short_name = excluded.short_name
            RETURNING id
            """,
            (repo.canonical_url, repo.fqn, repo.short_name),
        )
        return cursor.fetchone()[0]
    
    def get_by_url(self, canonical_url: str) -> Repository | None:
        """Get a repository by its canonical URL."""
        cursor = self.conn.execute(
            "SELECT id, canonical_url, fqn, short_name FROM repositories WHERE canonical_url = ?",
            (canonical_url,),
        )
        row = cursor.fetchone()
        if row:
            return Repository(
                id=row["id"],
                canonical_url=row["canonical_url"],
                fqn=row["fqn"],
                short_name=row["short_name"],
            )
        return None
    
    def search_by_name(self, name: str) -> Sequence[Repository]:
        """Search repositories by FQN or short name."""
        cursor = self.conn.execute(
            "SELECT id, canonical_url, fqn, short_name FROM repositories WHERE fqn LIKE ? OR short_name LIKE ?",
            (f"%{name}%", f"%{name}%"),
        )
        return [
            Repository(
                id=row["id"],
                canonical_url=row["canonical_url"],
                fqn=row["fqn"],
                short_name=row["short_name"],
            )
            for row in cursor.fetchall()
        ]


class IssueRepository:
    """Data access for issues."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, issue: Issue) -> int:
        """Insert or update an issue. Returns the issue ID."""
        cursor = self.conn.execute(
            """
            INSERT INTO issues (url, fqn, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                fqn = excluded.fqn,
                display_name = excluded.display_name
            RETURNING id
            """,
            (issue.url, issue.fqn, issue.display_name),
        )
        return cursor.fetchone()[0]
    
    def get_by_url(self, url: str) -> Issue | None:
        """Get an issue by its URL."""
        cursor = self.conn.execute(
            "SELECT id, url, fqn, display_name FROM issues WHERE url = ?",
            (url,),
        )
        row = cursor.fetchone()
        if row:
            return Issue(
                id=row["id"],
                url=row["url"],
                fqn=row["fqn"],
                display_name=row["display_name"],
            )
        return None
    
    def search_by_fqn(self, fqn: str) -> Sequence[Issue]:
        """Search issues by FQN pattern."""
        cursor = self.conn.execute(
            "SELECT id, url, fqn, display_name FROM issues WHERE fqn LIKE ?",
            (f"%{fqn}%",),
        )
        return [
            Issue(
                id=row["id"],
                url=row["url"],
                fqn=row["fqn"],
                display_name=row["display_name"],
            )
            for row in cursor.fetchall()
        ]


class PRRepository:
    """Data access for pull requests."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, pr: PullRequest) -> int:
        """Insert or update a pull request. Returns the PR ID."""
        cursor = self.conn.execute(
            """
            INSERT INTO pull_requests (url, fqn, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                fqn = excluded.fqn,
                display_name = excluded.display_name
            RETURNING id
            """,
            (pr.url, pr.fqn, pr.display_name),
        )
        return cursor.fetchone()[0]
    
    def get_by_url(self, url: str) -> PullRequest | None:
        """Get a PR by its URL."""
        cursor = self.conn.execute(
            "SELECT id, url, fqn, display_name FROM pull_requests WHERE url = ?",
            (url,),
        )
        row = cursor.fetchone()
        if row:
            return PullRequest(
                id=row["id"],
                url=row["url"],
                fqn=row["fqn"],
                display_name=row["display_name"],
            )
        return None
    
    def search_by_fqn(self, fqn: str) -> Sequence[PullRequest]:
        """Search PRs by FQN pattern."""
        cursor = self.conn.execute(
            "SELECT id, url, fqn, display_name FROM pull_requests WHERE fqn LIKE ?",
            (f"%{fqn}%",),
        )
        return [
            PullRequest(
                id=row["id"],
                url=row["url"],
                fqn=row["fqn"],
                display_name=row["display_name"],
            )
            for row in cursor.fetchall()
        ]


class LinkRepository:
    """Data access for conversation-entity links."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def link_repo(self, conversation_id: str, repo_id: int, link_type: LinkType) -> None:
        """Link a conversation to a repository.
        
        If the conversation already has a link to this repo, updates the link type
        only if the new type is WRITE (upgrades read to write).
        """
        self.conn.execute(
            """
            INSERT INTO conversation_repos (conversation_id, repo_id, link_type)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id, repo_id) DO UPDATE SET
                link_type = CASE 
                    WHEN excluded.link_type = 'write' THEN 'write'
                    ELSE conversation_repos.link_type
                END
            """,
            (conversation_id, repo_id, link_type.value),
        )
    
    def link_issue(self, conversation_id: str, issue_id: int, link_type: LinkType) -> None:
        """Link a conversation to an issue."""
        self.conn.execute(
            """
            INSERT INTO conversation_issues (conversation_id, issue_id, link_type)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id, issue_id) DO UPDATE SET
                link_type = CASE 
                    WHEN excluded.link_type = 'write' THEN 'write'
                    ELSE conversation_issues.link_type
                END
            """,
            (conversation_id, issue_id, link_type.value),
        )
    
    def link_pr(self, conversation_id: str, pr_id: int, link_type: LinkType) -> None:
        """Link a conversation to a pull request."""
        self.conn.execute(
            """
            INSERT INTO conversation_prs (conversation_id, pr_id, link_type)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id, pr_id) DO UPDATE SET
                link_type = CASE 
                    WHEN excluded.link_type = 'write' THEN 'write'
                    ELSE conversation_prs.link_type
                END
            """,
            (conversation_id, pr_id, link_type.value),
        )
    
    def get_conversations_for_repo(
        self, repo_id: int, link_type: LinkType | None = None
    ) -> Sequence[tuple[str, LinkType]]:
        """Get all conversations linked to a repository.
        
        Args:
            repo_id: The repository ID
            link_type: Optional filter for link type. If None, returns all.
            
        Returns:
            List of (conversation_id, link_type) tuples
        """
        if link_type:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_repos WHERE repo_id = ? AND link_type = ?",
                (repo_id, link_type.value),
            )
        else:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_repos WHERE repo_id = ?",
                (repo_id,),
            )
        return [(row["conversation_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_conversations_for_issue(
        self, issue_id: int, link_type: LinkType | None = None
    ) -> Sequence[tuple[str, LinkType]]:
        """Get all conversations linked to an issue."""
        if link_type:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_issues WHERE issue_id = ? AND link_type = ?",
                (issue_id, link_type.value),
            )
        else:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_issues WHERE issue_id = ?",
                (issue_id,),
            )
        return [(row["conversation_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_conversations_for_pr(
        self, pr_id: int, link_type: LinkType | None = None
    ) -> Sequence[tuple[str, LinkType]]:
        """Get all conversations linked to a pull request."""
        if link_type:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_prs WHERE pr_id = ? AND link_type = ?",
                (pr_id, link_type.value),
            )
        else:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_prs WHERE pr_id = ?",
                (pr_id,),
            )
        return [(row["conversation_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_repos_for_conversation(self, conversation_id: str) -> Sequence[tuple[int, LinkType]]:
        """Get all repos linked to a conversation."""
        cursor = self.conn.execute(
            "SELECT repo_id, link_type FROM conversation_repos WHERE conversation_id = ?",
            (conversation_id,),
        )
        return [(row["repo_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_issues_for_conversation(self, conversation_id: str) -> Sequence[tuple[int, LinkType]]:
        """Get all issues linked to a conversation."""
        cursor = self.conn.execute(
            "SELECT issue_id, link_type FROM conversation_issues WHERE conversation_id = ?",
            (conversation_id,),
        )
        return [(row["issue_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_prs_for_conversation(self, conversation_id: str) -> Sequence[tuple[int, LinkType]]:
        """Get all PRs linked to a conversation."""
        cursor = self.conn.execute(
            "SELECT pr_id, link_type FROM conversation_prs WHERE conversation_id = ?",
            (conversation_id,),
        )
        return [(row["pr_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
