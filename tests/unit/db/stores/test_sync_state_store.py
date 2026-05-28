"""Unit tests for :class:`ohtv.db.stores.SyncStateStore` (Issue #111)."""

from __future__ import annotations

import pytest

from ohtv.db.stores import SyncStateStore


@pytest.fixture
def state(db_conn) -> SyncStateStore:
    return SyncStateStore(db_conn)


class TestGetSet:
    def test_get_unknown_key_returns_default(self, state):
        assert state.get("nope") is None
        assert state.get("nope", default="x") == "x"

    def test_set_then_get_round_trip(self, state, db_conn):
        state.set("last_snapshot_id", "snap-42")
        db_conn.commit()
        assert state.get("last_snapshot_id") == "snap-42"

    def test_set_overwrites_existing_value(self, state, db_conn):
        state.set("k", "first")
        db_conn.commit()
        state.set("k", "second")
        db_conn.commit()
        assert state.get("k") == "second"

    def test_set_stores_non_string_values_via_sqlite_coercion(self, state, db_conn):
        """SQLite stores the value verbatim (no application-level coercion).

        Callers wanting string canonicalization should convert before
        calling ``set()``. This test documents the actual behaviour so
        a future refactor that adds eager ``str()`` coercion would
        break it intentionally.
        """
        state.set("count", 1234)
        db_conn.commit()
        # SQLite TEXT column receives int — ``sqlite3`` will return it
        # as the original type (no schema-driven type coercion).
        assert state.get("count") == 1234

    def test_set_none_clears_value(self, state, db_conn):
        state.set("k", "value")
        db_conn.commit()
        state.set("k", None)
        db_conn.commit()
        # NULL value reads back as None.
        assert state.get("k") is None


class TestSnapshotBookkeepingKeys:
    """The keys #111 writes to ``sync_kv`` are conventional, not enforced.

    The store is a thin k/v wrapper; these tests document the intent
    and catch regressions if the engine's key naming drifts.
    """

    def test_snapshot_id_key_round_trip(self, state, db_conn):
        state.set("last_snapshot_id", "abc123")
        db_conn.commit()
        assert state.get("last_snapshot_id") == "abc123"

    def test_snapshot_completed_at_key_round_trip(self, state, db_conn):
        state.set("last_snapshot_completed_at", "2024-06-01T00:00:00Z")
        db_conn.commit()
        assert state.get("last_snapshot_completed_at") == "2024-06-01T00:00:00Z"

    def test_snapshot_count_key_round_trip(self, state, db_conn):
        state.set("last_snapshot_count", 1234)
        db_conn.commit()
        assert state.get("last_snapshot_count") == 1234
