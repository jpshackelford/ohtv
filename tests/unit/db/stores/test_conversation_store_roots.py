"""Tests for ConversationStore root-conversation surface. Issue #122.

Covers:

* Write-time root resolution: roots get self, subs inherit parent's
  root, grand-children walk to the top.
* ``list_roots`` returns one row per tree with subs rolled up.
* ``list_roots`` filters apply at the root grain.
* Idempotency: re-upserting the same row doesn't regress
  ``root_conversation_id`` (COALESCE preserve).
* ``record_cloud_download`` resolves root from parent the same way.
* ``count_roots`` / ``count_subs`` / ``count_trees_with_subs`` for
  the ``db status`` reporting.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore


# ---------------------------------------------------------------------------
# Write-time root resolution
# ---------------------------------------------------------------------------


class TestUpsertRootResolution:
    def test_lone_root_gets_self(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="root1", location="/tmp/r", source="cloud")
        )
        db_conn.commit()
        result = conversation_store.get("root1")
        assert result.root_conversation_id == "root1"

    def test_sub_inherits_parent_root(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="root1", location="/tmp/r", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="sub1",
                location="/tmp/s",
                source="cloud",
                parent_conversation_id="root1",
            )
        )
        db_conn.commit()
        result = conversation_store.get("sub1")
        assert result.root_conversation_id == "root1"

    def test_grandchild_walks_to_root(self, conversation_store, db_conn):
        # Per AC #4: 1 root + 1 sub + 1 grand-child → all resolve to
        # the same root.
        conversation_store.upsert(
            Conversation(id="r", location="/tmp/r", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="s",
                location="/tmp/s",
                source="cloud",
                parent_conversation_id="r",
            )
        )
        conversation_store.upsert(
            Conversation(
                id="g",
                location="/tmp/g",
                source="cloud",
                parent_conversation_id="s",
            )
        )
        db_conn.commit()

        for conv_id in ("r", "s", "g"):
            assert conversation_store.get(conv_id).root_conversation_id == "r"

    def test_orphan_sub_becomes_own_root(self, conversation_store, db_conn):
        # Parent not in the local DB — sub becomes its own root.
        conversation_store.upsert(
            Conversation(
                id="orph",
                location="/tmp/o",
                source="cloud",
                parent_conversation_id="ghost",
            )
        )
        db_conn.commit()
        assert conversation_store.get("orph").root_conversation_id == "orph"

    def test_local_source_is_always_its_own_root(self, conversation_store, db_conn):
        # Local CLI rows are root by definition (no delegation).
        conversation_store.upsert(
            Conversation(id="cli1", location="/tmp/cli1", source="local")
        )
        db_conn.commit()
        assert conversation_store.get("cli1").root_conversation_id == "cli1"

    def test_dashed_parent_id_is_normalized(self, conversation_store, db_conn):
        # AGENTS.md item #14: ids are stored dashless. The parent
        # lookup must match across formats.
        conversation_store.upsert(
            Conversation(id="parentabc", location="/tmp/p", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="subxyz",
                location="/tmp/s",
                source="cloud",
                parent_conversation_id="parent-abc",
            )
        )
        db_conn.commit()
        # Sub stored its parent dashless.
        sub = conversation_store.get("subxyz")
        assert sub.parent_conversation_id == "parentabc"
        # Root resolved through the normalized parent.
        assert sub.root_conversation_id == "parentabc"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestUpsertIdempotency:
    def test_rescanning_does_not_regress_root(self, conversation_store, db_conn):
        """Per AC #plan item 9: re-scanner pass must not flip root.

        Scenario: sync writes (parent="r", root="r") for "s". Then
        the scanner does a plain upsert without parent context
        (parent=None). The COALESCE for parent preserves "r"; the
        store re-resolves root from that effective parent and writes
        "r" again. End state: root still "r".
        """
        # Initial sync-style write.
        conversation_store.upsert(
            Conversation(id="r", location="/tmp/r", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="s",
                location="/tmp/s",
                source="cloud",
                parent_conversation_id="r",
            )
        )
        db_conn.commit()
        assert conversation_store.get("s").root_conversation_id == "r"

        # Scanner-style re-pass with no parent info.
        conversation_store.upsert(
            Conversation(
                id="s",
                location="/tmp/s",
                source="cloud",
                title="updated title",
                # Note: no parent_conversation_id — extract_metadata
                # in a stale-snapshot scenario.
            )
        )
        db_conn.commit()

        result = conversation_store.get("s")
        # Title moved forward (proves the upsert ran).
        assert result.title == "updated title"
        # Root preserved.
        assert result.root_conversation_id == "r"
        assert result.parent_conversation_id == "r"


# ---------------------------------------------------------------------------
# list_roots
# ---------------------------------------------------------------------------


def _seed_tree(store: ConversationStore, conn) -> None:
    """1 root + 1 sub + 1 grand-child, all under "root1" — AC #4."""
    store.upsert(
        Conversation(
            id="root1",
            location="/tmp/root1",
            source="cloud",
            title="tree title",
            event_count=5,
            selected_repository="acme/repo",
            created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
    )
    store.upsert(
        Conversation(
            id="sub1",
            location="/tmp/sub1",
            source="cloud",
            event_count=7,
            parent_conversation_id="root1",
            created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        )
    )
    store.upsert(
        Conversation(
            id="grand1",
            location="/tmp/grand1",
            source="cloud",
            event_count=2,
            parent_conversation_id="sub1",
            created_at=datetime(2026, 5, 9, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        )
    )
    conn.commit()


class TestListRoots:
    def test_returns_exactly_one_row_for_three_node_tree(
        self, conversation_store, db_conn
    ):
        # Per AC #4.
        _seed_tree(conversation_store, db_conn)
        roots = conversation_store.list_roots()
        assert len(roots) == 1
        assert roots[0].id == "root1"
        assert roots[0].conversation_count == 3
        assert roots[0].sub_count == 2
        assert roots[0].event_count == 5 + 7 + 2

    def test_display_fields_come_from_root(self, conversation_store, db_conn):
        _seed_tree(conversation_store, db_conn)
        root = conversation_store.list_roots()[0]
        assert root.title == "tree title"
        assert root.source == "cloud"
        assert root.selected_repository == "acme/repo"
        assert root.location == "/tmp/root1"

    def test_time_fields_span_subtree(self, conversation_store, db_conn):
        _seed_tree(conversation_store, db_conn)
        root = conversation_store.list_roots()[0]
        # grand1 has earliest created_at (2026-05-09).
        assert root.created_at == datetime(2026, 5, 9, tzinfo=timezone.utc)
        # grand1 has latest updated_at (2026-05-14).
        assert root.updated_at == datetime(2026, 5, 14, tzinfo=timezone.utc)

    def test_two_trees_two_rows(self, conversation_store, db_conn):
        # Tree A.
        conversation_store.upsert(
            Conversation(
                id="rA",
                location="/tmp/rA",
                source="cloud",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        conversation_store.upsert(
            Conversation(
                id="sA",
                location="/tmp/sA",
                source="cloud",
                parent_conversation_id="rA",
                created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            )
        )
        # Tree B.
        conversation_store.upsert(
            Conversation(
                id="rB",
                location="/tmp/rB",
                source="cloud",
                created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
            )
        )
        db_conn.commit()

        roots = conversation_store.list_roots()
        assert len(roots) == 2
        # Ordered by created_at DESC (MIN over subtree).
        assert roots[0].id == "rB"  # 2026-05-03
        assert roots[1].id == "rA"  # MIN(2026-05-01, 2026-05-02) = 2026-05-01

    def test_orders_by_created_at_desc(self, conversation_store, db_conn):
        for n, day in enumerate(["08", "12", "03"]):
            conversation_store.upsert(
                Conversation(
                    id=f"r{n}",
                    location=f"/tmp/r{n}",
                    source="cloud",
                    created_at=datetime(2026, 5, int(day), tzinfo=timezone.utc),
                )
            )
        db_conn.commit()
        roots = conversation_store.list_roots()
        assert [r.id for r in roots] == ["r1", "r0", "r2"]


class TestListRootsFilters:
    def test_filters_since(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(
                id="old",
                location="/tmp/old",
                source="cloud",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        conversation_store.upsert(
            Conversation(
                id="new",
                location="/tmp/new",
                source="cloud",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        db_conn.commit()
        roots = conversation_store.list_roots(
            since=datetime(2026, 3, 1, tzinfo=timezone.utc)
        )
        assert [r.id for r in roots] == ["new"]

    def test_filters_until(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(
                id="old",
                location="/tmp/old",
                source="cloud",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        conversation_store.upsert(
            Conversation(
                id="new",
                location="/tmp/new",
                source="cloud",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        )
        db_conn.commit()
        roots = conversation_store.list_roots(
            until=datetime(2026, 3, 1, tzinfo=timezone.utc)
        )
        assert [r.id for r in roots] == ["old"]

    def test_filters_source(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="c", location="/tmp/c", source="cloud")
        )
        conversation_store.upsert(
            Conversation(id="l", location="/tmp/l", source="local")
        )
        db_conn.commit()
        roots = conversation_store.list_roots(source="cloud")
        assert [r.id for r in roots] == ["c"]

    def test_filters_selected_repository(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(
                id="a",
                location="/tmp/a",
                source="cloud",
                selected_repository="acme/foo",
            )
        )
        conversation_store.upsert(
            Conversation(
                id="b",
                location="/tmp/b",
                source="cloud",
                selected_repository="other/bar",
            )
        )
        db_conn.commit()
        roots = conversation_store.list_roots(selected_repository="acme/foo")
        assert [r.id for r in roots] == ["a"]

    def test_repo_filter_applies_at_root_grain_not_sub(
        self, conversation_store, db_conn
    ):
        """A sub with repo X does NOT make the root tree match
        ``selected_repository=X``. Tree is identified by root's value."""
        conversation_store.upsert(
            Conversation(
                id="rt",
                location="/tmp/rt",
                source="cloud",
                selected_repository="acme/foo",
            )
        )
        conversation_store.upsert(
            Conversation(
                id="sb",
                location="/tmp/sb",
                source="cloud",
                selected_repository="other/bar",
                parent_conversation_id="rt",
            )
        )
        db_conn.commit()
        # Filter by sub's repo — root tree shows repo="acme/foo", not
        # "other/bar". Tree should not match.
        roots = conversation_store.list_roots(selected_repository="other/bar")
        assert roots == []

        roots = conversation_store.list_roots(selected_repository="acme/foo")
        assert len(roots) == 1


# ---------------------------------------------------------------------------
# Count helpers
# ---------------------------------------------------------------------------


class TestCountHelpers:
    def test_count_roots_lone_roots(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="a", location="/a", source="cloud")
        )
        conversation_store.upsert(
            Conversation(id="b", location="/b", source="cloud")
        )
        db_conn.commit()
        assert conversation_store.count_roots() == 2
        assert conversation_store.count_subs() == 0
        assert conversation_store.count_trees_with_subs() == 0

    def test_count_roots_and_subs(self, conversation_store, db_conn):
        # 2 roots, 3 subs across 2 trees.
        conversation_store.upsert(
            Conversation(id="r1", location="/r1", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="s1a",
                location="/s1a",
                source="cloud",
                parent_conversation_id="r1",
            )
        )
        conversation_store.upsert(
            Conversation(
                id="s1b",
                location="/s1b",
                source="cloud",
                parent_conversation_id="r1",
            )
        )
        conversation_store.upsert(
            Conversation(id="r2", location="/r2", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="s2a",
                location="/s2a",
                source="cloud",
                parent_conversation_id="r2",
            )
        )
        db_conn.commit()
        assert conversation_store.count_roots() == 2
        assert conversation_store.count_subs() == 3
        assert conversation_store.count_trees_with_subs() == 2

    def test_count_trees_does_not_count_lone_roots(
        self, conversation_store, db_conn
    ):
        """A standalone root (no subs) is not a "tree with subs"."""
        conversation_store.upsert(
            Conversation(id="lone", location="/l", source="cloud")
        )
        conversation_store.upsert(
            Conversation(id="rt", location="/r", source="cloud")
        )
        conversation_store.upsert(
            Conversation(
                id="sb",
                location="/s",
                source="cloud",
                parent_conversation_id="rt",
            )
        )
        db_conn.commit()
        assert conversation_store.count_roots() == 2
        assert conversation_store.count_trees_with_subs() == 1


# ---------------------------------------------------------------------------
# record_cloud_download
# ---------------------------------------------------------------------------


class TestRecordCloudDownloadRoot:
    def test_root_gets_self(self, conversation_store, db_conn):
        conversation_store.record_cloud_download(
            "newid",
            location="/path",
            cloud_updated_at="2026-05-29T00:00:00Z",
        )
        db_conn.commit()
        assert conversation_store.get("newid").root_conversation_id == "newid"

    def test_sub_inherits_root_from_parent(self, conversation_store, db_conn):
        conversation_store.record_cloud_download(
            "root_id",
            location="/p_root",
            cloud_updated_at="2026-05-29T00:00:00Z",
        )
        conversation_store.record_cloud_download(
            "sub_id",
            location="/p_sub",
            cloud_updated_at="2026-05-29T00:00:00Z",
            parent_conversation_id="root_id",
        )
        db_conn.commit()
        assert conversation_store.get("sub_id").root_conversation_id == "root_id"

    def test_sub_created_before_parent_falls_back_to_self(
        self, conversation_store, db_conn
    ):
        """Race: sub downloaded before parent. Falls back to own id,
        which the migration's orphan policy mirrors. A later scanner
        pass cannot fix it unless the scanner re-resolves — that's a
        known limitation documented in the PR description."""
        conversation_store.record_cloud_download(
            "sub_first",
            location="/p_sub",
            cloud_updated_at="2026-05-29T00:00:00Z",
            parent_conversation_id="parent_later",
        )
        db_conn.commit()
        # Parent isn't in DB yet — orphan fallback.
        assert (
            conversation_store.get("sub_first").root_conversation_id
            == "sub_first"
        )
