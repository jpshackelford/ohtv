"""Tests for migration 025: sustained-attention cap (Issue #184).

Covers:

* Schema additions — the two new columns + the new index exist on
  ``conversation_engagement`` after migration.
* Defaults — pre-v2 rows back-fill to ``sustained_attention_seconds =
  3600`` and ``algorithm_version = 1``.
* Stage-row clearing — any pre-existing ``conversation_stages`` rows
  with ``stage = 'engagement'`` are deleted so the next processing
  pass auto-recomputes (the "user doesn't have to remember --force"
  guarantee from Issue #184's earlier comment).
* Sibling-stage rows untouched — clearing only affects the
  ``'engagement'`` stage; other stages are not invalidated.
* Idempotency — the per-step apply path skips the ALTER TABLEs if
  the columns already exist; re-running through ``migrate`` is a
  no-op.

Mirrors the fixture style of ``test_020_root_conversation_id.py``.
"""

from __future__ import annotations

import sqlite3

import pytest

from ohtv.db.migrations import (
    apply_migration,
    get_applied_migrations,
    get_pending_migrations,
    migrate,
)

MIGRATION_NAME = "025_sustained_attention.py"


@pytest.fixture
def fresh_db():
    """In-memory DB with all migrations applied through 025."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_through_024():
    """In-memory DB with migrations applied through 024 only.

    Used to seed pre-025 state then run 025 manually to exercise
    the column defaults and the stage-row clearing against a
    populated DB.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Ensure the _migrations bookkeeping table exists before we start
    # poking individual migration files at the connection.
    get_applied_migrations(conn)

    pending = [p for p in get_pending_migrations() if p.name < MIGRATION_NAME]
    for path in pending:
        apply_migration(conn, path)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA index_list({table})")}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_columns_present_after_migration(fresh_db):
    cols = _column_names(fresh_db, "conversation_engagement")
    assert "sustained_attention_seconds" in cols
    assert "algorithm_version" in cols


def test_index_created(fresh_db):
    indexes = _index_names(fresh_db, "conversation_engagement")
    assert "idx_conv_engagement_attention_window" in indexes


# ---------------------------------------------------------------------------
# Defaults — pre-v2 rows backfill cleanly
# ---------------------------------------------------------------------------


def test_existing_engagement_rows_get_default_values(db_through_024):
    """A pre-025 engagement row must back-fill T_a=3600 + version=1."""
    conn = db_through_024
    # Insert a conversation + a v1-style engagement row (no T_a / version cols).
    conn.execute(
        "INSERT INTO conversations (id, location, event_count) "
        "VALUES ('c1', '/tmp/c1', 10)"
    )
    conn.execute(
        """
        INSERT INTO conversation_engagement (
            conversation_id, threshold_seconds, first_event_ts,
            last_event_ts, total_duration_seconds, engaged_seconds,
            attention_periods, follow_up_user_message_count,
            attended_user_message_count, processed_at, event_count
        ) VALUES (?, 720, ?, ?, 100, 100, 1, 1, 1, ?, 10)
        """,
        ("c1", "2024-01-01T00:00:00+00:00", "2024-01-01T00:01:40+00:00",
         "2024-01-01T00:02:00+00:00"),
    )
    conn.commit()

    # Apply 025.
    pending = get_pending_migrations()
    migration_025 = next(m for m in pending if m.name == MIGRATION_NAME)
    apply_migration(conn, migration_025)

    row = conn.execute(
        "SELECT sustained_attention_seconds, algorithm_version "
        "FROM conversation_engagement WHERE conversation_id = 'c1'"
    ).fetchone()
    assert row["sustained_attention_seconds"] == 3600
    assert row["algorithm_version"] == 1


# ---------------------------------------------------------------------------
# Stage-row clearing — auto-invalidation
# ---------------------------------------------------------------------------


def test_engagement_stage_rows_cleared_on_upgrade(db_through_024):
    """Pre-025 engagement stage rows must be cleared so the next pass recomputes."""
    conn = db_through_024
    conn.execute(
        "INSERT INTO conversations (id, location, event_count) "
        "VALUES ('c1', '/tmp/c1', 10)"
    )
    conn.execute(
        "INSERT INTO conversation_stages "
        "(conversation_id, stage, completed_at, event_count) "
        "VALUES ('c1', 'engagement', '2024-01-01T00:00:00+00:00', 10)"
    )
    conn.commit()

    # Sanity: row present before upgrade.
    before = conn.execute(
        "SELECT COUNT(*) AS n FROM conversation_stages "
        "WHERE stage = 'engagement'"
    ).fetchone()
    assert before["n"] == 1

    # Apply 025.
    pending = get_pending_migrations()
    migration_025 = next(m for m in pending if m.name == MIGRATION_NAME)
    apply_migration(conn, migration_025)

    after = conn.execute(
        "SELECT COUNT(*) AS n FROM conversation_stages "
        "WHERE stage = 'engagement'"
    ).fetchone()
    assert after["n"] == 0, (
        "Issue #184: engagement stage rows must be auto-invalidated so "
        "the next ``ohtv db process engagement`` pass recomputes under "
        "the v2 algorithm."
    )


def test_sibling_stage_rows_untouched_on_upgrade(db_through_024):
    """Only the ``'engagement'`` stage is invalidated; refs/actions/etc. remain."""
    conn = db_through_024
    conn.execute(
        "INSERT INTO conversations (id, location, event_count) "
        "VALUES ('c1', '/tmp/c1', 10)"
    )
    for stage_name in ("refs", "actions", "summaries", "human_input"):
        conn.execute(
            "INSERT INTO conversation_stages "
            "(conversation_id, stage, completed_at, event_count) "
            "VALUES (?, ?, '2024-01-01T00:00:00+00:00', 10)",
            ("c1", stage_name),
        )
    # Plus an engagement row to confirm IT gets cleared.
    conn.execute(
        "INSERT INTO conversation_stages "
        "(conversation_id, stage, completed_at, event_count) "
        "VALUES ('c1', 'engagement', '2024-01-01T00:00:00+00:00', 10)"
    )
    conn.commit()

    pending = get_pending_migrations()
    migration_025 = next(m for m in pending if m.name == MIGRATION_NAME)
    apply_migration(conn, migration_025)

    surviving = {
        row["stage"]
        for row in conn.execute(
            "SELECT stage FROM conversation_stages WHERE conversation_id = 'c1'"
        )
    }
    assert surviving == {"refs", "actions", "summaries", "human_input"}


# ---------------------------------------------------------------------------
# Engagement data rows are NOT deleted (only the stage tracker is cleared)
# ---------------------------------------------------------------------------


def test_engagement_data_rows_preserved_on_upgrade(db_through_024):
    """The metric data persists across the upgrade — only the stage
    tracker is cleared. Downstream queries see stale v1 numbers until
    the next processing pass, but the row is not lost."""
    conn = db_through_024
    conn.execute(
        "INSERT INTO conversations (id, location, event_count) "
        "VALUES ('c1', '/tmp/c1', 10)"
    )
    conn.execute(
        """
        INSERT INTO conversation_engagement (
            conversation_id, threshold_seconds, first_event_ts,
            last_event_ts, total_duration_seconds, engaged_seconds,
            attention_periods, follow_up_user_message_count,
            attended_user_message_count, processed_at, event_count
        ) VALUES (?, 720, ?, ?, 100, 100, 1, 1, 1, ?, 10)
        """,
        ("c1", "2024-01-01T00:00:00+00:00", "2024-01-01T00:01:40+00:00",
         "2024-01-01T00:02:00+00:00"),
    )
    conn.commit()

    pending = get_pending_migrations()
    migration_025 = next(m for m in pending if m.name == MIGRATION_NAME)
    apply_migration(conn, migration_025)

    surviving = conn.execute(
        "SELECT engaged_seconds, attention_periods, algorithm_version "
        "FROM conversation_engagement WHERE conversation_id = 'c1'"
    ).fetchone()
    assert surviving is not None
    assert surviving["engaged_seconds"] == 100
    assert surviving["attention_periods"] == 1
    # Backfilled to v1 so the next processing pass can detect it's stale.
    assert surviving["algorithm_version"] == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_migration_recorded_after_apply(fresh_db):
    """``migrate(conn)`` should not re-apply 025 on a fresh DB."""
    applied = get_applied_migrations(fresh_db)
    assert MIGRATION_NAME in applied
