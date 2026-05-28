"""Unit tests for :class:`ohtv.db.stores.CloudListingStore` (Issue #111).

These tests exercise the snapshot lifecycle, the set-diff query
helpers (``missing_locally`` / ``stale_locally`` / ``removed_from_cloud``),
and id normalization in isolation from the sync engine.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ohtv.db.stores import CloudListingStore, ConversationStore


_UTC = timezone.utc


@pytest.fixture
def listing(db_conn) -> CloudListingStore:
    return CloudListingStore(db_conn)


@pytest.fixture
def conversations(db_conn) -> ConversationStore:
    return ConversationStore(db_conn)


def _seed_conversation_row(
    db_conn, conv_id: str, *, cloud_updated_at: str | None = None
) -> None:
    """Insert a minimal ``conversations`` row for set-diff tests."""
    db_conn.execute(
        """
        INSERT INTO conversations (
            id, location, registered_at, event_count, source, cloud_updated_at
        )
        VALUES (?, ?, '2024-01-01T00:00:00Z', 0, 'cloud', ?)
        """,
        (conv_id, f"/tmp/{conv_id}", cloud_updated_at),
    )


class TestSnapshotLifecycle:
    """``start_snapshot`` → ``upsert_row`` → ``commit_snapshot``."""

    def test_start_snapshot_returns_unique_id(self, listing):
        a = listing.start_snapshot()
        b = listing.start_snapshot()
        assert a != b

    def test_upsert_row_persists_payload(self, listing, db_conn):
        snap = listing.start_snapshot()
        listing.upsert_row(
            snap,
            {
                "id": "abc",
                "title": "t",
                "updated_at": "2024-06-01T00:00:00Z",
                "created_at": "2024-06-01T00:00:00Z",
                "tags": {"env": "prod"},
                "selected_repository": "org/repo",
                "selected_branch": "main",
            },
        )
        db_conn.commit()

        row = listing.get("abc")
        assert row is not None
        assert row["conversation_id"] == "abc"
        assert row["title"] == "t"
        assert row["selected_repository"] == "org/repo"

    def test_upsert_normalizes_dashed_ids(self, listing, db_conn):
        """Dashed ids are normalized to undashed at write-time, and
        ``get`` accepts either form (symmetric normalization)."""
        snap = listing.start_snapshot()
        dashed = "00000000-0000-0000-0000-000000000001"
        undashed = "00000000000000000000000000000001"
        listing.upsert_row(snap, {"id": dashed, "updated_at": "2024-01-01T00:00:00Z"})
        db_conn.commit()

        # Both forms resolve to the same row (id-form invariance).
        row_undashed = listing.get(undashed)
        row_dashed = listing.get(dashed)
        assert row_undashed is not None
        assert row_dashed is not None
        # Stored canonical form is undashed.
        assert row_undashed["conversation_id"] == undashed

    def test_upsert_row_dedupes_by_id(self, listing, db_conn):
        """Two ``upsert_row`` calls with the same id collapse to one row.

        This is the pagination-dedup guarantee: keyset drift can yield
        an id on two consecutive pages, and the second write must
        overwrite (not duplicate) the first.
        """
        snap = listing.start_snapshot()
        listing.upsert_row(snap, {"id": "x", "updated_at": "2024-01-01T00:00:00Z"})
        listing.upsert_row(snap, {"id": "x", "updated_at": "2024-06-01T00:00:00Z"})
        db_conn.commit()

        # SELECT COUNT(*) to verify physical dedup at the table level.
        rows = list(db_conn.execute("SELECT * FROM cloud_listing"))
        assert len(rows) == 1
        assert rows[0]["updated_at"] == "2024-06-01T00:00:00Z"

    def test_commit_snapshot_prunes_prior_snapshots(self, listing, db_conn):
        old_snap = listing.start_snapshot()
        listing.upsert_row(old_snap, {"id": "old", "updated_at": "2024-01-01T00:00:00Z"})
        listing.commit_snapshot(old_snap)
        db_conn.commit()

        new_snap = listing.start_snapshot()
        listing.upsert_row(new_snap, {"id": "new", "updated_at": "2024-06-01T00:00:00Z"})
        listing.commit_snapshot(new_snap)
        db_conn.commit()

        # Old row was atomically swapped out.
        assert listing.get("old") is None
        assert listing.get("new") is not None

    def test_abandon_snapshot_preserves_prior_snapshot(self, listing, db_conn):
        """A failed listing must NOT clobber the previous committed snapshot."""
        committed = listing.start_snapshot()
        listing.upsert_row(committed, {"id": "stable", "updated_at": "2024-01-01T00:00:00Z"})
        listing.commit_snapshot(committed)
        db_conn.commit()

        # Half-finished listing — fails before commit_snapshot.
        in_flight = listing.start_snapshot()
        listing.upsert_row(in_flight, {"id": "partial", "updated_at": "2024-06-01T00:00:00Z"})
        listing.abandon_snapshot(in_flight)
        db_conn.commit()

        # The committed snapshot survived; the in-flight rows were dropped.
        assert listing.get("stable") is not None
        assert listing.get("partial") is None

    def test_missing_id_returns_none(self, listing):
        assert listing.get("does-not-exist") is None


class TestSetDiffHelpers:
    """``missing_locally`` / ``stale_locally`` / ``removed_from_cloud``."""

    def _commit_snapshot(self, listing, db_conn, payloads):
        snap = listing.start_snapshot()
        for p in payloads:
            listing.upsert_row(snap, p)
        listing.commit_snapshot(snap)
        db_conn.commit()
        return snap

    def test_missing_locally_yields_ids_not_in_conversations(
        self, listing, db_conn
    ):
        self._commit_snapshot(
            listing,
            db_conn,
            [
                {"id": "a", "updated_at": "2024-01-01T00:00:00Z"},
                {"id": "b", "updated_at": "2024-01-01T00:00:00Z"},
            ],
        )
        _seed_conversation_row(db_conn, "a", cloud_updated_at="2024-01-01T00:00:00Z")
        db_conn.commit()

        assert set(listing.missing_locally()) == {"b"}

    def test_stale_locally_uses_inequality_not_greater_than(
        self, listing, db_conn
    ):
        """The stale check uses ``!=`` so a backdated cloud timestamp also
        counts as stale (Issue #111 scenario #3)."""
        self._commit_snapshot(
            listing,
            db_conn,
            [{"id": "a", "updated_at": "2024-01-01T00:00:00Z"}],
        )
        _seed_conversation_row(db_conn, "a", cloud_updated_at="2024-06-01T00:00:00Z")
        db_conn.commit()

        # Local has the NEWER ts; cloud was rewound. Stale check must yield "a".
        assert set(listing.stale_locally()) == {"a"}

    def test_stale_locally_null_local_ts_is_stale(self, listing, db_conn):
        self._commit_snapshot(
            listing,
            db_conn,
            [{"id": "a", "updated_at": "2024-01-01T00:00:00Z"}],
        )
        _seed_conversation_row(db_conn, "a", cloud_updated_at=None)
        db_conn.commit()

        assert set(listing.stale_locally()) == {"a"}

    def test_stale_locally_matching_ts_is_fresh(self, listing, db_conn):
        self._commit_snapshot(
            listing,
            db_conn,
            [{"id": "a", "updated_at": "2024-01-01T00:00:00Z"}],
        )
        _seed_conversation_row(db_conn, "a", cloud_updated_at="2024-01-01T00:00:00Z")
        db_conn.commit()

        assert list(listing.stale_locally()) == []

    def test_removed_from_cloud_yields_local_only_rows(
        self, listing, db_conn
    ):
        self._commit_snapshot(
            listing,
            db_conn,
            [{"id": "a", "updated_at": "2024-01-01T00:00:00Z"}],
        )
        _seed_conversation_row(db_conn, "a", cloud_updated_at="2024-01-01T00:00:00Z")
        _seed_conversation_row(db_conn, "ghost", cloud_updated_at=None)
        db_conn.commit()

        assert set(listing.removed_from_cloud()) == {"ghost"}


class TestUpsertValidation:
    def test_missing_id_raises(self, listing):
        snap = listing.start_snapshot()
        with pytest.raises(ValueError, match="missing 'id'"):
            listing.upsert_row(snap, {"title": "no id here"})

    def test_unknown_keys_silently_dropped(self, listing, db_conn):
        snap = listing.start_snapshot()
        listing.upsert_row(
            snap,
            {
                "id": "x",
                "updated_at": "2024-01-01T00:00:00Z",
                "future_api_field": "ignored",
            },
        )
        db_conn.commit()
        assert listing.get("x") is not None

    def test_fetched_at_defaults_to_now(self, listing, db_conn):
        snap = listing.start_snapshot()
        listing.upsert_row(snap, {"id": "x", "updated_at": "2024-01-01T00:00:00Z"})
        db_conn.commit()

        row = listing.get("x")
        # ``fetched_at`` should be a parseable iso timestamp.
        assert row["fetched_at"]
        datetime.fromisoformat(row["fetched_at"].rstrip("Z"))


class TestJSONColumnSerialization:
    def test_tags_dict_round_trip(self, listing, db_conn):
        snap = listing.start_snapshot()
        listing.upsert_row(
            snap,
            {
                "id": "x",
                "updated_at": "2024-01-01T00:00:00Z",
                "tags": {"team": "platform", "env": "prod"},
            },
        )
        db_conn.commit()
        row = listing.get("x")
        # tags column stores JSON text — caller is responsible for decoding.
        assert isinstance(row["tags"], str)
        assert "platform" in row["tags"]

    def test_sub_conversation_ids_list_round_trip(self, listing, db_conn):
        snap = listing.start_snapshot()
        listing.upsert_row(
            snap,
            {
                "id": "x",
                "updated_at": "2024-01-01T00:00:00Z",
                "sub_conversation_ids": ["a", "b"],
            },
        )
        db_conn.commit()
        row = listing.get("x")
        assert isinstance(row["sub_conversation_ids"], str)
        assert "a" in row["sub_conversation_ids"]

    def test_pr_number_list_round_trip(self, listing, db_conn):
        """Regression: the live cloud API returns ``pr_number`` as an
        ``Array<int>`` (e.g. ``[133]``). The PR-#133 fixture set never
        populated this field so CI missed the
        ``sqlite3.ProgrammingError: type 'list' is not supported``
        crash that the first manual sync hit. Asserting the list shape
        round-trips locks in the JSON encoding."""
        snap = listing.start_snapshot()
        listing.upsert_row(
            snap,
            {
                "id": "x",
                "updated_at": "2024-01-01T00:00:00Z",
                "pr_number": [133],
            },
        )
        db_conn.commit()
        row = listing.get("x")
        # Stored as JSON text — matches tags / sub_conversation_ids policy.
        assert isinstance(row["pr_number"], str)
        assert "133" in row["pr_number"]

    def test_pr_number_empty_list_round_trip(self, listing, db_conn):
        """The common case for non-PR conversations: ``pr_number=[]``.
        sqlite3 would still reject the raw list before JSON encoding."""
        snap = listing.start_snapshot()
        listing.upsert_row(
            snap,
            {
                "id": "x",
                "updated_at": "2024-01-01T00:00:00Z",
                "pr_number": [],
            },
        )
        db_conn.commit()
        row = listing.get("x")
        assert row["pr_number"] == "[]"
