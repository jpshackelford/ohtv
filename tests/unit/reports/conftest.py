"""Test fixtures for ohtv.reports.

Each test gets a fresh in-memory SQLite database with the full
migration history applied. There is no mocking of the DB layer —
real schema, real foreign keys, real CHECK constraints.

Helper functions ``seed_repo``, ``seed_conversation``, ``seed_pr``,
``seed_contribution`` and ``seed_human_input`` make per-test setup
surgical.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from ohtv.db.migrations import migrate


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory DB with migrations applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    migrate(c)
    try:
        yield c
    finally:
        c.close()


def seed_repo(
    conn: sqlite3.Connection,
    *,
    canonical_url: str,
    fqn: str | None = None,
    short_name: str | None = None,
) -> int:
    """Insert a repository and return its id."""
    fqn = fqn or canonical_url.rsplit("/", 2)[-2] + "/" + canonical_url.rsplit("/", 1)[-1]
    short_name = short_name or fqn.split("/")[-1]
    cur = conn.execute(
        "INSERT INTO repositories (canonical_url, fqn, short_name) "
        "VALUES (?, ?, ?) RETURNING id",
        (canonical_url, fqn, short_name),
    )
    repo_id = cur.fetchone()["id"]
    conn.commit()
    return repo_id


def seed_conversation(
    conn: sqlite3.Connection,
    conv_id: str,
    *,
    parent_conversation_id: str | None = None,
    root_conversation_id: str | None = None,
) -> None:
    """Insert a minimal conversations row.

    Issue #124: ``parent_conversation_id`` / ``root_conversation_id``
    let tests seed sub-conversation trees. When ``root_conversation_id``
    is not passed, it defaults to ``conv_id`` (i.e., this row is its
    own root), which preserves the pre-#124 behaviour of every
    existing test seeding only roots.
    """
    if root_conversation_id is None:
        root_conversation_id = conv_id
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, parent_conversation_id, root_conversation_id) "
        "VALUES (?, ?, ?, ?)",
        (
            conv_id,
            f"/tmp/{conv_id}",
            parent_conversation_id,
            root_conversation_id,
        ),
    )
    conn.commit()


def seed_pr(
    conn: sqlite3.Connection,
    *,
    repo_id: int,
    pr_number: int,
    status: str = "merged",
    merged_at: str | datetime | None = None,
    lines_added: int | None = 100,
    lines_removed: int | None = 25,
    files_changed: int | None = 3,
) -> int:
    """Insert a change_refs row (PR) and return its id.

    Defaults produce a merged PR with sensible LOC numbers. Pass
    ``lines_added=None`` to model the "LOC not yet fetched" case.
    """
    if isinstance(merged_at, datetime):
        merged_at = merged_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        """
        INSERT INTO change_refs
            (repo_id, change_type, pr_number, status, merged_at,
             lines_added, lines_removed, files_changed)
        VALUES (?, 'pr', ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (repo_id, pr_number, status, merged_at, lines_added, lines_removed, files_changed),
    )
    row_id = cur.fetchone()["id"]
    conn.commit()
    return row_id


def seed_direct_push(
    conn: sqlite3.Connection,
    *,
    repo_id: int,
    commit_range: str,
    status: str = "merged",
    merged_at: str | datetime | None = None,
    lines_added: int | None = 50,
    lines_removed: int | None = 5,
) -> int:
    """Insert a direct-push change_refs row."""
    if isinstance(merged_at, datetime):
        merged_at = merged_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        """
        INSERT INTO change_refs
            (repo_id, change_type, commit_range, status, merged_at,
             lines_added, lines_removed)
        VALUES (?, 'direct_push', ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (repo_id, commit_range, status, merged_at, lines_added, lines_removed),
    )
    row_id = cur.fetchone()["id"]
    conn.commit()
    return row_id


def seed_contribution(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    change_ref_id: int,
    contribution_type: str = "merged",
) -> None:
    """Insert a conversation_contributions row."""
    conn.execute(
        """
        INSERT INTO conversation_contributions
            (conversation_id, change_ref_id, contribution_type)
        VALUES (?, ?, ?)
        """,
        (conversation_id, change_ref_id, contribution_type),
    )
    conn.commit()


def seed_human_input(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    initial_prompt_words: int = 0,
    initial_prompt_source: str = "human",
    followup_word_count: int = 0,
    followup_message_count: int = 0,
    processed_at: str = "2024-05-01T00:00:00Z",
    event_count: int = 1,
) -> None:
    """Insert a conversation_human_input row."""
    conn.execute(
        """
        INSERT INTO conversation_human_input
            (conversation_id, initial_prompt_words, initial_prompt_source,
             followup_word_count, followup_message_count,
             processed_at, event_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            initial_prompt_words,
            initial_prompt_source,
            followup_word_count,
            followup_message_count,
            processed_at,
            event_count,
        ),
    )
    conn.commit()
