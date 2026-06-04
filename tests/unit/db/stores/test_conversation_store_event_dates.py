"""Unit tests for ``ConversationStore.list_by_event_date_range`` (Issue #180).

Covers the INNER-JOIN semantics against ``conversation_engagement``,
the overlap predicate on ``[first_event_ts, last_event_ts]``, and the
roots-only / source-filter plumbing shared with
:meth:`ConversationStore.list_by_date_range`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore


def _seed_engagement(
    db_conn,
    conversation_id: str,
    *,
    first_event_ts: datetime,
    last_event_ts: datetime,
    engaged_seconds: int = 0,
) -> None:
    """Insert one ``conversation_engagement`` row for the given conv id."""
    total = int((last_event_ts - first_event_ts).total_seconds())
    db_conn.execute(
        "INSERT INTO conversation_engagement "
        "(conversation_id, threshold_seconds, first_event_ts, "
        "last_event_ts, total_duration_seconds, engaged_seconds, "
        "attention_periods, follow_up_user_message_count, "
        "attended_user_message_count, processed_at, event_count) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, 1)",
        (
            conversation_id,
            420,
            first_event_ts.isoformat(),
            last_event_ts.isoformat(),
            total,
            engaged_seconds,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db_conn.commit()


def _seed_conv(
    store: ConversationStore,
    db_conn,
    conv_id: str,
    *,
    created_at: datetime,
    source: str = "cloud",
    event_count: int = 5,
) -> None:
    store.upsert(
        Conversation(
            id=conv_id,
            location=f"/tmp/{conv_id}",
            event_count=event_count,
            created_at=created_at,
            source=source,
        )
    )
    db_conn.commit()


# Compact 32-char hex ids that pass the LocalSource pattern.
ID_OLD_FRESH = "a" * 32  # created_at old, last_event_ts recent
ID_OLD_STALE = "b" * 32  # both old
ID_NEW = "c" * 32  # both new
ID_NO_ENGAGEMENT = "d" * 32  # has conversations row, no engagement row


class TestListByEventDateRange:
    def test_since_uses_last_event_ts(self, conversation_store, db_conn):
        """Round-trip test from the issue: conversation created 30d ago
        with last_event_ts now appears under --event-dates --since (T₀-7d)
        but not under plain --since (T₀-7d)."""
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=30),
        )
        _seed_engagement(
            db_conn, ID_OLD_FRESH,
            first_event_ts=T0 - timedelta(days=30),
            last_event_ts=T0,
        )

        since = T0 - timedelta(days=7)

        # Plain since: created_at (T₀-30d) is BEFORE T₀-7d → excluded
        plain = conversation_store.list_by_date_range(since=since)
        assert [c.id for c in plain] == []

        # Event-dates since: last_event_ts (T₀) >= T₀-7d → included
        event = conversation_store.list_by_event_date_range(since=since)
        assert [c.id for c in event] == [ID_OLD_FRESH]

    def test_until_uses_first_event_ts(self, conversation_store, db_conn):
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=30),
        )
        _seed_engagement(
            db_conn, ID_OLD_FRESH,
            first_event_ts=T0 - timedelta(days=30),
            last_event_ts=T0,
        )

        # first_event_ts (T₀-30d) <= until (T₀-15d) → included
        included = conversation_store.list_by_event_date_range(
            until=T0 - timedelta(days=15)
        )
        assert [c.id for c in included] == [ID_OLD_FRESH]

        # first_event_ts (T₀-30d) > until (T₀-31d) → excluded
        excluded = conversation_store.list_by_event_date_range(
            until=T0 - timedelta(days=31)
        )
        assert [c.id for c in excluded] == []

    def test_overlap_predicate(self, conversation_store, db_conn):
        """Combined ``since`` + ``until`` uses interval overlap:
        ``[first, last]`` overlaps ``[since, until]``."""
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=30),
        )
        # Event span: [T₀-20d, T₀]
        _seed_engagement(
            db_conn, ID_OLD_FRESH,
            first_event_ts=T0 - timedelta(days=20),
            last_event_ts=T0,
        )

        # [T₀-5d, T₀+5d] overlaps [T₀-20d, T₀] → included
        assert conversation_store.list_by_event_date_range(
            since=T0 - timedelta(days=5),
            until=T0 + timedelta(days=5),
        ) != []

        # [T₀+1d, T₀+5d] is disjoint from [T₀-20d, T₀] → excluded
        assert conversation_store.list_by_event_date_range(
            since=T0 + timedelta(days=1),
            until=T0 + timedelta(days=5),
        ) == []

    def test_missing_engagement_row_excluded(
        self, conversation_store, db_conn
    ):
        """INNER JOIN semantics: a conv with no engagement row is
        excluded under --event-dates, but a plain --since still
        includes it."""
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _seed_conv(
            conversation_store, db_conn, ID_NO_ENGAGEMENT,
            created_at=T0 - timedelta(days=1),
        )
        since = T0 - timedelta(days=7)

        # Plain since: included (created_at is in range)
        plain = conversation_store.list_by_date_range(since=since)
        assert {c.id for c in plain} == {ID_NO_ENGAGEMENT}

        # Event-dates since: excluded (no engagement row)
        event = conversation_store.list_by_event_date_range(since=since)
        assert [c.id for c in event] == []

    def test_no_filters_returns_all_with_engagement(
        self, conversation_store, db_conn
    ):
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=30),
        )
        _seed_conv(
            conversation_store, db_conn, ID_NO_ENGAGEMENT,
            created_at=T0,
        )
        _seed_engagement(
            db_conn, ID_OLD_FRESH,
            first_event_ts=T0 - timedelta(days=30),
            last_event_ts=T0 - timedelta(days=1),
        )

        # Bare call still INNER-JOINs against engagement.
        result = conversation_store.list_by_event_date_range()
        assert {c.id for c in result} == {ID_OLD_FRESH}

    def test_source_filter(self, conversation_store, db_conn):
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=30),
            source="cloud",
        )
        _seed_conv(
            conversation_store, db_conn, ID_NEW,
            created_at=T0,
            source="local",
        )
        for cid in (ID_OLD_FRESH, ID_NEW):
            _seed_engagement(
                db_conn, cid,
                first_event_ts=T0 - timedelta(days=1),
                last_event_ts=T0,
            )

        cloud_only = conversation_store.list_by_event_date_range(
            since=T0 - timedelta(days=7), source="cloud"
        )
        assert [c.id for c in cloud_only] == [ID_OLD_FRESH]

        local_only = conversation_store.list_by_event_date_range(
            since=T0 - timedelta(days=7), source="local"
        )
        assert [c.id for c in local_only] == [ID_NEW]

    def test_orders_by_last_event_ts_desc(self, conversation_store, db_conn):
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        # Two conversations with the SAME created_at but different
        # last_event_ts. ``list_by_date_range`` would tie-break on
        # SQLite ordering; ``list_by_event_date_range`` MUST order by
        # ``last_event_ts DESC``.
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=5),
        )
        _seed_conv(
            conversation_store, db_conn, ID_NEW,
            created_at=T0 - timedelta(days=5),
        )
        _seed_engagement(
            db_conn, ID_OLD_FRESH,
            first_event_ts=T0 - timedelta(days=5),
            last_event_ts=T0 - timedelta(days=2),  # older event
        )
        _seed_engagement(
            db_conn, ID_NEW,
            first_event_ts=T0 - timedelta(days=5),
            last_event_ts=T0,  # newer event
        )

        result = conversation_store.list_by_event_date_range(
            since=T0 - timedelta(days=7)
        )
        assert [c.id for c in result] == [ID_NEW, ID_OLD_FRESH]


class TestListByEventDateRangeRootsOnly:
    """Roots-only predicate (``include_subs=False``) mirrors #125."""

    def test_excludes_sub_by_default(self, conversation_store, db_conn):
        T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        # Root conv:
        _seed_conv(
            conversation_store, db_conn, ID_OLD_FRESH,
            created_at=T0 - timedelta(days=5),
        )
        _seed_engagement(
            db_conn, ID_OLD_FRESH,
            first_event_ts=T0 - timedelta(days=5),
            last_event_ts=T0,
        )

        # Sub conv (parent = root). Migration 020 auto-resolves
        # root_conversation_id via ConversationStore.upsert's parent
        # walk, so passing parent_conversation_id is enough.
        conversation_store.upsert(
            Conversation(
                id=ID_NEW,
                location="/tmp/sub",
                event_count=5,
                created_at=T0 - timedelta(days=4),
                source="cloud",
                parent_conversation_id=ID_OLD_FRESH,
            )
        )
        _seed_engagement(
            db_conn, ID_NEW,
            first_event_ts=T0 - timedelta(days=4),
            last_event_ts=T0,
        )

        # include_subs=False (default): only root surfaces.
        roots_only = conversation_store.list_by_event_date_range(
            since=T0 - timedelta(days=7)
        )
        assert [c.id for c in roots_only] == [ID_OLD_FRESH]

        # include_subs=True: both root + sub.
        with_subs = conversation_store.list_by_event_date_range(
            since=T0 - timedelta(days=7), include_subs=True
        )
        assert {c.id for c in with_subs} == {ID_OLD_FRESH, ID_NEW}


class TestMigration024Indexes:
    """Verify migration 024 creates the two indexes that make
    ``list_by_event_date_range`` query-plan-cheap."""

    def test_last_event_ts_index_exists(self, db_conn):
        cur = db_conn.execute(
            "PRAGMA index_list('conversation_engagement')"
        )
        names = {row[1] for row in cur.fetchall()}
        assert "idx_conv_engagement_last_event_ts" in names

    def test_first_event_ts_index_exists(self, db_conn):
        cur = db_conn.execute(
            "PRAGMA index_list('conversation_engagement')"
        )
        names = {row[1] for row in cur.fetchall()}
        assert "idx_conv_engagement_first_event_ts" in names
