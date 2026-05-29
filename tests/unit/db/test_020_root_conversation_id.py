"""Tests for migration 020: root_conversation_id (Issue #122).

Covers:

* Schema additions — column, index, view exist after migration.
* Idempotency — re-running 020 is a no-op (column add and view drop/recreate).
* Backfill semantics — root, sub, grand-child, orphan, multi-tree.
* Post-condition invariant — every row has a non-NULL
  ``root_conversation_id`` after backfill.
* View shape — ``conversations_by_root`` columns, group-by behavior,
  display roll-up policy.

Mirrors the fixture style of ``test_018_set_diff_sync_schema.py`` —
in-memory DB with all migrations applied, plus a separate
"through-019" fixture for exercising the populated-DB upgrade path.
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

MIGRATION_NAME = "020_root_conversation_id.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_db():
    """In-memory DB with all migrations applied through 020."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_through_019():
    """In-memory DB with migrations applied through 019 only.

    Used to seed pre-020 state then run 020 manually to exercise
    the backfill against a populated DB.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    get_applied_migrations(conn)

    pending = [p for p in get_pending_migrations() if p.name < MIGRATION_NAME]
    for path in pending:
        apply_migration(conn, path)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()


def _apply_020(conn: sqlite3.Connection) -> None:
    """Apply just the 020 migration to a connection."""
    for path in get_pending_migrations():
        if path.name == MIGRATION_NAME:
            apply_migration(conn, path)
            conn.commit()
            return
    raise RuntimeError(f"could not find migration {MIGRATION_NAME}")


def _insert_conv(
    conn: sqlite3.Connection,
    conv_id: str,
    *,
    parent_id: str | None = None,
    title: str = "test",
    source: str = "cloud",
    event_count: int = 0,
    created_at: str | None = None,
    updated_at: str | None = None,
    selected_repository: str | None = None,
) -> None:
    """Raw insert directly into ``conversations``. Bypasses the
    store so we can seed pre-020 state in ``db_through_019`` without
    pulling in the post-020 column."""
    conn.execute(
        """
        INSERT INTO conversations (
            id, location, registered_at, event_count, source, title,
            created_at, updated_at, selected_repository,
            parent_conversation_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conv_id,
            f"/tmp/{conv_id}",
            "2026-05-29T00:00:00+00:00",
            event_count,
            source,
            title,
            created_at,
            updated_at,
            selected_repository,
            parent_id,
        ),
    )


# ---------------------------------------------------------------------------
# Schema additions
# ---------------------------------------------------------------------------


class TestSchemaAdditions:
    def test_root_conversation_id_column_exists(self, fresh_db):
        cols = {
            r["name"] for r in fresh_db.execute("PRAGMA table_info(conversations)")
        }
        assert "root_conversation_id" in cols

    def test_root_conversation_id_column_is_nullable(self, fresh_db):
        cols = {
            r["name"]: r
            for r in fresh_db.execute("PRAGMA table_info(conversations)")
        }
        # Migration uses ADD COLUMN with no NOT NULL clause (required
        # for ALTER TABLE on populated tables in older SQLite).
        assert cols["root_conversation_id"]["notnull"] == 0

    def test_root_index_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name='idx_conversations_root'"
        ).fetchone()
        assert row is not None

    def test_view_exists(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='conversations_by_root'"
        ).fetchone()
        assert row is not None


class TestIdempotency:
    def test_upgrade_twice_is_safe(self, db_through_019):
        # Call the migration's upgrade() directly. The bookkeeping
        # wrapper (apply_migration) won't let the same file run twice;
        # idempotency means the SQL inside upgrade() is safe to re-run
        # in the rare case of a partial-apply recovery.
        import importlib.util

        from ohtv.db.migrations import MIGRATIONS_DIR

        path = MIGRATIONS_DIR / MIGRATION_NAME
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        module.upgrade(db_through_019)
        # Second invocation must not raise.
        module.upgrade(db_through_019)
        db_through_019.commit()

        # View should still exist (DROP + CREATE pattern handles
        # second-run cleanly).
        row = db_through_019.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='conversations_by_root'"
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Backfill semantics
# ---------------------------------------------------------------------------


class TestBackfillRootOnly:
    def test_lone_root_gets_self_as_root(self, db_through_019):
        _insert_conv(db_through_019, "abc", parent_id=None)
        db_through_019.commit()
        _apply_020(db_through_019)

        row = db_through_019.execute(
            "SELECT root_conversation_id FROM conversations WHERE id = 'abc'"
        ).fetchone()
        assert row["root_conversation_id"] == "abc"


class TestBackfillRootSubChain:
    def test_root_sub_grandchild_all_resolve_to_root(self, db_through_019):
        # 3-deep chain: root → sub → grand-child.
        _insert_conv(db_through_019, "root1", parent_id=None)
        _insert_conv(db_through_019, "sub1", parent_id="root1")
        _insert_conv(db_through_019, "grand1", parent_id="sub1")
        db_through_019.commit()

        _apply_020(db_through_019)

        rows = {
            r["id"]: r["root_conversation_id"]
            for r in db_through_019.execute(
                "SELECT id, root_conversation_id FROM conversations"
            )
        }
        assert rows == {
            "root1": "root1",
            "sub1": "root1",
            "grand1": "root1",
        }


class TestBackfillOrphan:
    def test_sub_with_missing_parent_becomes_own_root(self, db_through_019):
        # Sub points at a parent that isn't in the DB.
        _insert_conv(db_through_019, "orphan", parent_id="missing_parent")
        db_through_019.commit()

        _apply_020(db_through_019)

        row = db_through_019.execute(
            "SELECT root_conversation_id FROM conversations WHERE id = 'orphan'"
        ).fetchone()
        # Orphan policy: own id. Better than NULL (groupable) and
        # better than crashing.
        assert row["root_conversation_id"] == "orphan"


class TestBackfillMultiTree:
    def test_multiple_trees_each_resolve_to_own_root(self, db_through_019):
        _insert_conv(db_through_019, "rootA", parent_id=None)
        _insert_conv(db_through_019, "subA", parent_id="rootA")
        _insert_conv(db_through_019, "rootB", parent_id=None)
        _insert_conv(db_through_019, "subB1", parent_id="rootB")
        _insert_conv(db_through_019, "subB2", parent_id="rootB")
        db_through_019.commit()

        _apply_020(db_through_019)

        rows = {
            r["id"]: r["root_conversation_id"]
            for r in db_through_019.execute(
                "SELECT id, root_conversation_id FROM conversations"
            )
        }
        assert rows == {
            "rootA": "rootA",
            "subA": "rootA",
            "rootB": "rootB",
            "subB1": "rootB",
            "subB2": "rootB",
        }


class TestBackfillInvariant:
    def test_every_row_has_non_null_root_after_backfill(self, db_through_019):
        _insert_conv(db_through_019, "r", parent_id=None)
        _insert_conv(db_through_019, "s", parent_id="r")
        _insert_conv(db_through_019, "g", parent_id="s")
        _insert_conv(db_through_019, "orphan", parent_id="ghost")
        db_through_019.commit()

        _apply_020(db_through_019)

        nulls = db_through_019.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE root_conversation_id IS NULL"
        ).fetchone()[0]
        assert nulls == 0


# ---------------------------------------------------------------------------
# View shape
# ---------------------------------------------------------------------------


class TestViewShape:
    def test_view_columns(self, fresh_db):
        # Inserting one row lets us inspect the view's pragma.
        cols = [
            r["name"]
            for r in fresh_db.execute(
                "SELECT name FROM pragma_table_info('conversations_by_root')"
            )
        ]
        expected = {
            "id",
            "title",
            "source",
            "selected_repository",
            "labels",
            "location",
            "created_at",
            "updated_at",
            "event_count",
            "conversation_count",
            "sub_count",
        }
        assert set(cols) == expected

    def test_view_groups_subs_onto_root(self, fresh_db):
        # Use raw inserts to construct a tree with known sums.
        from ohtv.db.stores import ConversationStore
        from ohtv.db.models import Conversation

        store = ConversationStore(fresh_db)
        store.upsert(
            Conversation(
                id="rt", location="/tmp/rt", title="root title",
                source="cloud", event_count=10,
                selected_repository="acme/repo",
            )
        )
        store.upsert(
            Conversation(
                id="sb", location="/tmp/sb", title="sub title",
                source="cloud", event_count=20,
                parent_conversation_id="rt",
            )
        )
        fresh_db.commit()

        rows = list(
            fresh_db.execute(
                "SELECT id, title, source, selected_repository, "
                "event_count, conversation_count, sub_count "
                "FROM conversations_by_root"
            )
        )
        # Exactly one row (one tree).
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == "rt"
        # Display fields: root's value.
        assert row["title"] == "root title"
        assert row["source"] == "cloud"
        assert row["selected_repository"] == "acme/repo"
        # Quantitative: SUM.
        assert row["event_count"] == 30
        assert row["conversation_count"] == 2
        assert row["sub_count"] == 1


class TestViewTimeRollup:
    def test_view_picks_min_created_max_updated(self, fresh_db):
        from ohtv.db.stores import ConversationStore
        from ohtv.db.models import Conversation
        from datetime import datetime, timezone

        store = ConversationStore(fresh_db)
        store.upsert(
            Conversation(
                id="rt",
                location="/tmp/rt",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
                source="cloud",
            )
        )
        store.upsert(
            Conversation(
                id="sb",
                location="/tmp/sb",
                created_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
                source="cloud",
                parent_conversation_id="rt",
            )
        )
        fresh_db.commit()

        row = fresh_db.execute(
            "SELECT created_at, updated_at FROM conversations_by_root"
        ).fetchone()
        # MIN of the two.
        assert row["created_at"].startswith("2026-04-28")
        # MAX of the two.
        assert row["updated_at"].startswith("2026-05-05")
