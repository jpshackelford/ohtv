"""Repository pattern for database access.

Provides clean interfaces for CRUD operations on indexed entities.
"""

import sqlite3
from typing import Sequence

from ohtv.db.models import (
    Conversation,
    LinkType,
    Reference,
    RefType,
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


class ReferenceRepository:
    """Data access for references (issues, PRs, etc)."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def upsert(self, ref: Reference) -> int:
        """Insert or update a reference. Returns the reference ID."""
        cursor = self.conn.execute(
            """
            INSERT INTO refs (ref_type, url, fqn, display_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                ref_type = excluded.ref_type,
                fqn = excluded.fqn,
                display_name = excluded.display_name
            RETURNING id
            """,
            (ref.ref_type.value, ref.url, ref.fqn, ref.display_name),
        )
        return cursor.fetchone()[0]
    
    def get_by_url(self, url: str) -> Reference | None:
        """Get a reference by its URL."""
        cursor = self.conn.execute(
            "SELECT id, ref_type, url, fqn, display_name FROM refs WHERE url = ?",
            (url,),
        )
        row = cursor.fetchone()
        if row:
            return Reference(
                id=row["id"],
                ref_type=RefType(row["ref_type"]),
                url=row["url"],
                fqn=row["fqn"],
                display_name=row["display_name"],
            )
        return None
    
    def search_by_fqn(
        self, fqn: str, ref_type: RefType | None = None
    ) -> Sequence[Reference]:
        """Search references by FQN pattern, optionally filtered by type."""
        if ref_type:
            cursor = self.conn.execute(
                "SELECT id, ref_type, url, fqn, display_name FROM refs WHERE fqn LIKE ? AND ref_type = ?",
                (f"%{fqn}%", ref_type.value),
            )
        else:
            cursor = self.conn.execute(
                "SELECT id, ref_type, url, fqn, display_name FROM refs WHERE fqn LIKE ?",
                (f"%{fqn}%",),
            )
        return [
            Reference(
                id=row["id"],
                ref_type=RefType(row["ref_type"]),
                url=row["url"],
                fqn=row["fqn"],
                display_name=row["display_name"],
            )
            for row in cursor.fetchall()
        ]
    
    def list_by_type(self, ref_type: RefType) -> Sequence[Reference]:
        """List all references of a given type."""
        cursor = self.conn.execute(
            "SELECT id, ref_type, url, fqn, display_name FROM refs WHERE ref_type = ?",
            (ref_type.value,),
        )
        return [
            Reference(
                id=row["id"],
                ref_type=RefType(row["ref_type"]),
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
    
    def link_ref(self, conversation_id: str, ref_id: int, link_type: LinkType) -> None:
        """Link a conversation to a reference (issue, PR, etc).
        
        If the conversation already has a link to this ref, updates the link type
        only if the new type is WRITE (upgrades read to write).
        """
        self.conn.execute(
            """
            INSERT INTO conversation_refs (conversation_id, ref_id, link_type)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id, ref_id) DO UPDATE SET
                link_type = CASE 
                    WHEN excluded.link_type = 'write' THEN 'write'
                    ELSE conversation_refs.link_type
                END
            """,
            (conversation_id, ref_id, link_type.value),
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
    
    def get_conversations_for_ref(
        self, ref_id: int, link_type: LinkType | None = None
    ) -> Sequence[tuple[str, LinkType]]:
        """Get all conversations linked to a reference.
        
        Args:
            ref_id: The reference ID
            link_type: Optional filter for link type. If None, returns all.
            
        Returns:
            List of (conversation_id, link_type) tuples
        """
        if link_type:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_refs WHERE ref_id = ? AND link_type = ?",
                (ref_id, link_type.value),
            )
        else:
            cursor = self.conn.execute(
                "SELECT conversation_id, link_type FROM conversation_refs WHERE ref_id = ?",
                (ref_id,),
            )
        return [(row["conversation_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_repos_for_conversation(self, conversation_id: str) -> Sequence[tuple[int, LinkType]]:
        """Get all repos linked to a conversation."""
        cursor = self.conn.execute(
            "SELECT repo_id, link_type FROM conversation_repos WHERE conversation_id = ?",
            (conversation_id,),
        )
        return [(row["repo_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
    
    def get_refs_for_conversation(
        self, conversation_id: str, ref_type: RefType | None = None
    ) -> Sequence[tuple[int, LinkType]]:
        """Get all references linked to a conversation, optionally filtered by type."""
        if ref_type:
            cursor = self.conn.execute(
                """
                SELECT cr.ref_id, cr.link_type 
                FROM conversation_refs cr
                JOIN refs r ON cr.ref_id = r.id
                WHERE cr.conversation_id = ? AND r.ref_type = ?
                """,
                (conversation_id, ref_type.value),
            )
        else:
            cursor = self.conn.execute(
                "SELECT ref_id, link_type FROM conversation_refs WHERE conversation_id = ?",
                (conversation_id,),
            )
        return [(row["ref_id"], LinkType(row["link_type"])) for row in cursor.fetchall()]
