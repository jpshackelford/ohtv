"""Data store for references (issues, PRs, etc)."""

import sqlite3
from typing import Sequence

from ohtv.db.models import Reference, RefType


class ReferenceStore:
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
