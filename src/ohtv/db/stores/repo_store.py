"""Data store for git repositories."""

import sqlite3
from typing import Sequence

from ohtv.db.models import Repository


class RepoStore:
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
