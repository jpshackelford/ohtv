"""Data store for change references and conversation contributions.

This store backs the contribution tracking tables (created by migration 016):

- ``change_refs`` - PRs and direct pushes to main, deduplicated per repo
- ``conversation_contributions`` - many-to-many links between conversations
  and the changes they created/pushed/merged

The store is intentionally narrow and generic: it knows how to upsert PR
and direct-push change refs and how to record contributions of any type.
This keeps the per-conversation processing logic (see
``ohtv.db.stages.contributions``) free of SQL concerns and lets follow-up
features (e.g. issue #79 - direct push detection) reuse the same store
without modification.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal, Sequence

ChangeType = Literal["pr", "direct_push"]
ContributionType = Literal["created", "pushed", "merged"]


@dataclass(frozen=True)
class ChangeRef:
    """A row from the ``change_refs`` table."""

    id: int
    repo_id: int
    change_type: ChangeType
    pr_number: int | None
    commit_range: str | None
    branch: str | None
    status: str


@dataclass(frozen=True)
class Contribution:
    """A row from the ``conversation_contributions`` table."""

    id: int
    conversation_id: str
    change_ref_id: int
    contribution_type: ContributionType


class ContributionsStore:
    """Data access for ``change_refs`` and ``conversation_contributions``."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- change_refs ----------------------------------------------------

    def get_or_create_pr_change_ref(
        self,
        repo_id: int,
        pr_number: int,
        branch: str | None = None,
    ) -> int:
        """Return the change_ref ID for a PR, creating it if needed.

        PRs are uniquely identified by ``(repo_id, pr_number)``. If a row
        already exists, its ID is returned unchanged - ``branch`` and
        ``status`` are not modified on lookup so we never clobber data a
        future stage (or manual fetch) may have populated. A new row is
        created with ``status='pending'`` and the supplied ``branch``.

        Args:
            repo_id: Foreign key into ``repositories``.
            pr_number: PR or MR number (e.g. ``42`` for ``#42``).
            branch: Optional head branch name, recorded on creation only.

        Returns:
            The integer ID of the (existing or newly inserted) change_ref.
        """
        cursor = self.conn.execute(
            "SELECT id FROM change_refs "
            "WHERE repo_id = ? AND change_type = 'pr' AND pr_number = ?",
            (repo_id, pr_number),
        )
        row = cursor.fetchone()
        if row is not None:
            return row[0] if not isinstance(row, sqlite3.Row) else row["id"]

        cursor = self.conn.execute(
            """
            INSERT INTO change_refs (repo_id, change_type, pr_number, branch, status)
            VALUES (?, 'pr', ?, ?, 'pending')
            RETURNING id
            """,
            (repo_id, pr_number, branch),
        )
        return cursor.fetchone()[0]

    def get_or_create_direct_push_change_ref(
        self,
        repo_id: int,
        commit_range: str,
        branch: str | None = None,
    ) -> int:
        """Return the change_ref ID for a direct push, creating it if needed.

        Direct pushes are uniquely identified by ``(repo_id, commit_range)``.
        This method is provided so a future stage (issue #79) can detect
        pushes that bypass PRs without needing to add a new store.

        Args:
            repo_id: Foreign key into ``repositories``.
            commit_range: A unique identifier for the push - typically the
                ``oldsha..newsha`` range from ``git push`` output.
            branch: Optional branch name, recorded on creation only.

        Returns:
            The integer ID of the (existing or newly inserted) change_ref.
        """
        cursor = self.conn.execute(
            "SELECT id FROM change_refs "
            "WHERE repo_id = ? AND change_type = 'direct_push' "
            "AND commit_range = ?",
            (repo_id, commit_range),
        )
        row = cursor.fetchone()
        if row is not None:
            return row[0] if not isinstance(row, sqlite3.Row) else row["id"]

        cursor = self.conn.execute(
            """
            INSERT INTO change_refs
                (repo_id, change_type, commit_range, branch, status)
            VALUES (?, 'direct_push', ?, ?, 'pending')
            RETURNING id
            """,
            (repo_id, commit_range, branch),
        )
        return cursor.fetchone()[0]

    def get_change_ref(self, change_ref_id: int) -> ChangeRef | None:
        """Fetch a single change_ref by ID, or None if it does not exist."""
        cursor = self.conn.execute(
            "SELECT id, repo_id, change_type, pr_number, commit_range, "
            "branch, status FROM change_refs WHERE id = ?",
            (change_ref_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_change_ref(row)

    def list_pr_change_refs(self, repo_id: int) -> Sequence[ChangeRef]:
        """List all PR change_refs for a repository, ordered by pr_number."""
        cursor = self.conn.execute(
            "SELECT id, repo_id, change_type, pr_number, commit_range, "
            "branch, status FROM change_refs "
            "WHERE repo_id = ? AND change_type = 'pr' "
            "ORDER BY pr_number",
            (repo_id,),
        )
        return [_row_to_change_ref(row) for row in cursor.fetchall()]

    # ---- conversation_contributions ------------------------------------

    def record_contribution(
        self,
        conversation_id: str,
        change_ref_id: int,
        contribution_type: ContributionType,
    ) -> None:
        """Record a contribution, ignoring exact duplicates.

        The ``(conversation_id, change_ref_id, contribution_type)`` triple
        is unique in the schema; ``INSERT OR IGNORE`` keeps the method
        idempotent so callers can replay events safely.
        """
        self.conn.execute(
            """
            INSERT OR IGNORE INTO conversation_contributions
                (conversation_id, change_ref_id, contribution_type)
            VALUES (?, ?, ?)
            """,
            (conversation_id, change_ref_id, contribution_type),
        )

    def delete_contributions_for_conversation(self, conversation_id: str) -> int:
        """Delete all contributions for a conversation.

        Used by the stage to make reprocessing idempotent: clear the prior
        state for this conversation, then re-derive contributions from the
        current actions. Returns the number of rows deleted.

        Note: this does NOT delete ``change_refs`` themselves - those are
        shared across conversations (many-to-many) and may still be
        referenced by other contributors.
        """
        cursor = self.conn.execute(
            "DELETE FROM conversation_contributions WHERE conversation_id = ?",
            (conversation_id,),
        )
        return cursor.rowcount

    def get_contributions_for_conversation(
        self, conversation_id: str
    ) -> Sequence[Contribution]:
        """Return all contributions made by a conversation, ordered by id."""
        cursor = self.conn.execute(
            "SELECT id, conversation_id, change_ref_id, contribution_type "
            "FROM conversation_contributions "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )
        return [_row_to_contribution(row) for row in cursor.fetchall()]

    def get_contributors_for_change_ref(
        self, change_ref_id: int
    ) -> Sequence[Contribution]:
        """Return all contributions made to a change_ref, ordered by id."""
        cursor = self.conn.execute(
            "SELECT id, conversation_id, change_ref_id, contribution_type "
            "FROM conversation_contributions "
            "WHERE change_ref_id = ? ORDER BY id",
            (change_ref_id,),
        )
        return [_row_to_contribution(row) for row in cursor.fetchall()]


def _row_to_change_ref(row: sqlite3.Row | tuple) -> ChangeRef:
    """Convert a ``change_refs`` row to a :class:`ChangeRef`.

    Works for both ``Row`` (dict-like) and plain-tuple cursors.
    """
    if isinstance(row, sqlite3.Row):
        return ChangeRef(
            id=row["id"],
            repo_id=row["repo_id"],
            change_type=row["change_type"],
            pr_number=row["pr_number"],
            commit_range=row["commit_range"],
            branch=row["branch"],
            status=row["status"],
        )
    return ChangeRef(
        id=row[0],
        repo_id=row[1],
        change_type=row[2],
        pr_number=row[3],
        commit_range=row[4],
        branch=row[5],
        status=row[6],
    )


def _row_to_contribution(row: sqlite3.Row | tuple) -> Contribution:
    """Convert a ``conversation_contributions`` row to a :class:`Contribution`."""
    if isinstance(row, sqlite3.Row):
        return Contribution(
            id=row["id"],
            conversation_id=row["conversation_id"],
            change_ref_id=row["change_ref_id"],
            contribution_type=row["contribution_type"],
        )
    return Contribution(
        id=row[0],
        conversation_id=row[1],
        change_ref_id=row[2],
        contribution_type=row[3],
    )
