"""Data store for conversation-entity links."""

import sqlite3
from typing import Sequence

from ohtv.db.models import LinkType, RefType


class LinkStore:
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
