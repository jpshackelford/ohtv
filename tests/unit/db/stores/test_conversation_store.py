"""Unit tests for ConversationStore."""

import sqlite3
from datetime import datetime, timezone

import pytest

from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore


class TestUpsert:
    """Tests for ConversationStore.upsert()."""

    def test_inserts_new_conversation(self, conversation_store, db_conn):
        conv = Conversation(id="conv-1", location="/path/to/conv-1")
        
        conversation_store.upsert(conv)
        db_conn.commit()
        
        result = conversation_store.get("conv-1")
        assert result is not None

    def test_updates_existing_conversation_location(self, conversation_store, db_conn):
        conversation_store.upsert(Conversation(id="conv-1", location="/old/path"))
        db_conn.commit()
        
        conversation_store.upsert(Conversation(id="conv-1", location="/new/path"))
        db_conn.commit()
        
        result = conversation_store.get("conv-1")
        assert result.location == "/new/path"

    def test_does_not_create_duplicate_on_upsert(self, conversation_store, db_conn):
        conversation_store.upsert(Conversation(id="conv-1", location="/path1"))
        conversation_store.upsert(Conversation(id="conv-1", location="/path2"))
        db_conn.commit()
        
        cursor = db_conn.execute("SELECT COUNT(*) FROM conversations WHERE id = ?", ("conv-1",))
        count = cursor.fetchone()[0]
        assert count == 1


class TestGet:
    """Tests for ConversationStore.get()."""

    def test_returns_conversation_when_exists(self, conversation_store, db_conn):
        conversation_store.upsert(Conversation(id="conv-1", location="/path/to/conv"))
        db_conn.commit()
        
        result = conversation_store.get("conv-1")
        
        assert result.id == "conv-1"
        assert result.location == "/path/to/conv"

    def test_returns_none_when_not_exists(self, conversation_store):
        result = conversation_store.get("nonexistent")
        
        assert result is None


class TestDelete:
    """Tests for ConversationStore.delete()."""

    def test_removes_existing_conversation(self, conversation_store, db_conn):
        conversation_store.upsert(Conversation(id="conv-1", location="/path"))
        db_conn.commit()
        
        conversation_store.delete("conv-1")
        db_conn.commit()
        
        assert conversation_store.get("conv-1") is None

    def test_returns_true_when_deleted(self, conversation_store, db_conn):
        conversation_store.upsert(Conversation(id="conv-1", location="/path"))
        db_conn.commit()
        
        result = conversation_store.delete("conv-1")
        
        assert result is True

    def test_returns_false_when_not_exists(self, conversation_store):
        result = conversation_store.delete("nonexistent")
        
        assert result is False


class TestUpdateMetadata:
    """Tests for ConversationStore.update_metadata() (Issue #86)."""

    def test_updates_title_only_leaves_labels_untouched(
        self, conversation_store, db_conn
    ):
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/path",
                title="Original",
                labels={"qa": "smoke"},
            )
        )
        db_conn.commit()

        updated = conversation_store.update_metadata("conv1", title="Renamed")
        db_conn.commit()

        assert updated is True
        result = conversation_store.get("conv1")
        assert result.title == "Renamed"
        # Labels untouched because we did not pass the kwarg.
        assert result.labels == {"qa": "smoke"}

    def test_updates_labels_only_leaves_title_untouched(
        self, conversation_store, db_conn
    ):
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/path",
                title="Original",
                labels=None,
            )
        )
        db_conn.commit()

        updated = conversation_store.update_metadata(
            "conv1", labels={"qa": "smoke"}
        )
        db_conn.commit()

        assert updated is True
        result = conversation_store.get("conv1")
        assert result.title == "Original"
        assert result.labels == {"qa": "smoke"}

    def test_updates_both_title_and_labels(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="conv1", location="/path", title="Old", labels=None)
        )
        db_conn.commit()

        updated = conversation_store.update_metadata(
            "conv1", title="New", labels={"k": "v"}
        )
        db_conn.commit()

        assert updated is True
        result = conversation_store.get("conv1")
        assert result.title == "New"
        assert result.labels == {"k": "v"}

    def test_clears_title_when_passed_none(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", title="Original")
        )
        db_conn.commit()

        updated = conversation_store.update_metadata("conv1", title=None)
        db_conn.commit()

        assert updated is True
        assert conversation_store.get("conv1").title is None

    def test_normalizes_empty_dict_labels_to_null(
        self, conversation_store, db_conn
    ):
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", labels={"qa": "smoke"})
        )
        db_conn.commit()

        updated = conversation_store.update_metadata("conv1", labels={})
        db_conn.commit()

        assert updated is True
        result = conversation_store.get("conv1")
        assert result.labels is None

    def test_clears_labels_when_passed_none(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", labels={"qa": "smoke"})
        )
        db_conn.commit()

        updated = conversation_store.update_metadata("conv1", labels=None)
        db_conn.commit()

        assert updated is True
        assert conversation_store.get("conv1").labels is None

    def test_normalizes_dashed_conversation_id(
        self, conversation_store, db_conn
    ):
        """ID with dashes must find the row stored without dashes."""
        conversation_store.upsert(
            Conversation(
                id="abc1234567890123456789012345678",
                location="/p",
                title="Old",
            )
        )
        db_conn.commit()

        # Caller passes a dashed UUID form. Normalization strips all dashes.
        dashed = "abc12345-6789-0123-4567-89012345678"
        updated = conversation_store.update_metadata(dashed, title="New")
        db_conn.commit()

        assert updated is True
        assert (
            conversation_store.get("abc1234567890123456789012345678").title == "New"
        )

    def test_returns_false_when_conversation_missing(self, conversation_store):
        updated = conversation_store.update_metadata(
            "nonexistent", title="X", labels={"k": "v"}
        )
        assert updated is False

    def test_noop_call_returns_true_when_row_exists(
        self, conversation_store, db_conn
    ):
        """Calling with no fields is a successful no-op only when the row exists."""
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", title="X")
        )
        db_conn.commit()

        # Both kwargs omitted -> sentinel _UNSET -> nothing to write
        updated = conversation_store.update_metadata("conv1")
        assert updated is True
        # Title preserved
        assert conversation_store.get("conv1").title == "X"

    def test_noop_call_returns_false_when_row_missing(self, conversation_store):
        updated = conversation_store.update_metadata("nonexistent")
        assert updated is False

    def test_does_not_touch_unrelated_columns(
        self, conversation_store, db_conn
    ):
        """update_metadata must NOT clobber selected_repository, etc."""
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/p",
                title="Old",
                selected_repository="owner/repo",
                event_count=42,
                source="cloud",
            )
        )
        db_conn.commit()

        conversation_store.update_metadata("conv1", title="New")
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.title == "New"
        # Other columns intact.
        assert result.selected_repository == "owner/repo"
        assert result.event_count == 42
        assert result.source == "cloud"
        assert result.location == "/p"

    def test_persists_across_connection(
        self, conversation_store, db_conn
    ):
        """Update must hit a real UPDATE statement (not just in-memory cache)."""
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", title="Old")
        )
        db_conn.commit()

        conversation_store.update_metadata("conv1", title="New")
        db_conn.commit()

        # Re-read via direct SQL to confirm persistence
        cursor = db_conn.execute("SELECT title FROM conversations WHERE id = ?", ("conv1",))
        row = cursor.fetchone()
        assert row[0] == "New"


class TestUpdateMetadataIssue87:
    """Tests for the Issue #87 extension of ConversationStore.update_metadata().

    Adds ``selected_repository`` and ``created_at`` keyword args with the
    same _UNSET sentinel semantics as ``title``/``labels``.
    """

    def test_updates_selected_repository_only(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/p",
                title="Same",
                selected_repository="old/repo",
            )
        )
        db_conn.commit()

        conversation_store.update_metadata(
            "conv1", selected_repository="new/repo"
        )
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.selected_repository == "new/repo"
        # Title untouched
        assert result.title == "Same"

    def test_clears_selected_repository_when_passed_none(
        self, conversation_store, db_conn
    ):
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/p",
                selected_repository="old/repo",
            )
        )
        db_conn.commit()

        conversation_store.update_metadata("conv1", selected_repository=None)
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.selected_repository is None

    def test_updates_created_at(self, conversation_store, db_conn):
        original = datetime(2020, 1, 1, tzinfo=timezone.utc)
        new = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", created_at=original)
        )
        db_conn.commit()

        conversation_store.update_metadata("conv1", created_at=new)
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.created_at == new

    def test_clears_created_at_when_passed_none(
        self, conversation_store, db_conn
    ):
        original = datetime(2020, 1, 1, tzinfo=timezone.utc)
        conversation_store.upsert(
            Conversation(id="conv1", location="/p", created_at=original)
        )
        db_conn.commit()

        conversation_store.update_metadata("conv1", created_at=None)
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.created_at is None

    def test_updates_all_four_fields_together(self, conversation_store, db_conn):
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/p",
                title="Old",
                selected_repository="old/repo",
                created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
        )
        db_conn.commit()

        new_created = datetime(2024, 6, 15, tzinfo=timezone.utc)
        conversation_store.update_metadata(
            "conv1",
            title="New",
            labels={"team": "platform"},
            selected_repository="new/repo",
            created_at=new_created,
        )
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.title == "New"
        assert result.labels == {"team": "platform"}
        assert result.selected_repository == "new/repo"
        assert result.created_at == new_created

    def test_skips_unset_fields(self, conversation_store, db_conn):
        """Fields not passed must remain unchanged (sentinel semantics)."""
        original = datetime(2020, 1, 1, tzinfo=timezone.utc)
        conversation_store.upsert(
            Conversation(
                id="conv1",
                location="/p",
                title="Original title",
                selected_repository="org/repo",
                created_at=original,
            )
        )
        db_conn.commit()

        # Touch only labels — everything else must remain intact.
        conversation_store.update_metadata("conv1", labels={"x": "y"})
        db_conn.commit()

        result = conversation_store.get("conv1")
        assert result.title == "Original title"
        assert result.selected_repository == "org/repo"
        assert result.created_at == original
        assert result.labels == {"x": "y"}

    def test_rejects_string_for_created_at(
        self, conversation_store, db_conn
    ):
        """created_at must be a datetime — refuse strings to prevent silent
        ISO-format mismatches between callers.
        """
        conversation_store.upsert(
            Conversation(id="conv1", location="/p")
        )
        db_conn.commit()
        with pytest.raises(TypeError, match="created_at must be datetime"):
            conversation_store.update_metadata(
                "conv1", created_at="2024-01-01T00:00:00Z"
            )

    def test_normalizes_dashed_id_for_new_fields(
        self, conversation_store, db_conn
    ):
        """Dashed UUIDs must be normalized when writing #87 fields too."""
        conversation_store.upsert(
            Conversation(
                id="abc123def4561234567890123456abcd",  # 32 chars, normalized
                location="/p",
                selected_repository="old/repo",
            )
        )
        db_conn.commit()

        # Pass with dashes (UUID format)
        conversation_store.update_metadata(
            "abc123de-f456-1234-5678-90123456abcd",
            selected_repository="new/repo",
        )
        db_conn.commit()

        result = conversation_store.get("abc123def4561234567890123456abcd")
        assert result.selected_repository == "new/repo"

    def test_returns_true_when_noop_with_unset_fields(
        self, conversation_store, db_conn
    ):
        """All four fields unset + row exists → True (matches pre-#87 noop semantics)."""
        conversation_store.upsert(
            Conversation(id="conv1", location="/p")
        )
        db_conn.commit()
        # All four args unset.
        assert conversation_store.update_metadata("conv1") is True


# ---------------------------------------------------------------------------
# Issue #125 — roots-only default on list_by_date_range
# ---------------------------------------------------------------------------


class TestListByDateRangeIncludeSubs:
    """Cluster: #125. ``gen objs/titles/run`` multi-conv mode must not
    pull agent-delegated sub-conversations as independent rows.

    These tests exercise the contract directly on ``list_by_date_range``
    so a regression at the orchestration layer (cli.py wiring) can be
    distinguished from one at the SQL layer. The DB-layer guarantee is:

    * ``include_subs=False`` (default) → only rows where
      ``id = root_conversation_id`` (i.e. roots) are returned.
    * ``include_subs=True`` → every row that matches the other filters
      is returned, subs and roots alike.

    Fixtures use dashless IDs throughout per AGENTS.md item #14.
    """

    def _seed_root_and_subs(
        self, conversation_store, db_conn, *, created_at: str | None = None
    ):
        """1 root + 2 subs in the same tree (one chain via grand-child).

        Returns the (root_id, sub_id, grandchild_id) triple. All three
        rows share the root's ``root_conversation_id``.
        """
        # Root.
        conversation_store.upsert(
            Conversation(
                id="r0001",
                location="/tmp/r0001",
                source="cloud",
                event_count=10,
                created_at=datetime.fromisoformat(created_at) if created_at else None,
            )
        )
        # Sub (delegated from root).
        conversation_store.upsert(
            Conversation(
                id="s0001",
                location="/tmp/s0001",
                source="cloud",
                event_count=5,
                parent_conversation_id="r0001",
                created_at=datetime.fromisoformat(created_at) if created_at else None,
            )
        )
        # Grand-child (delegated from sub).
        conversation_store.upsert(
            Conversation(
                id="g0001",
                location="/tmp/g0001",
                source="cloud",
                event_count=3,
                parent_conversation_id="s0001",
                created_at=datetime.fromisoformat(created_at) if created_at else None,
            )
        )
        db_conn.commit()
        return "r0001", "s0001", "g0001"

    def test_excludes_subs_by_default(self, conversation_store, db_conn):
        root_id, sub_id, grandchild_id = self._seed_root_and_subs(
            conversation_store, db_conn
        )
        result = conversation_store.list_by_date_range()
        ids = {c.id for c in result}
        assert ids == {root_id}, (
            "Default include_subs=False must return only the root; "
            f"got {ids}"
        )

    def test_includes_subs_when_flag_set(self, conversation_store, db_conn):
        root_id, sub_id, grandchild_id = self._seed_root_and_subs(
            conversation_store, db_conn
        )
        result = conversation_store.list_by_date_range(include_subs=True)
        ids = {c.id for c in result}
        assert ids == {root_id, sub_id, grandchild_id}, (
            f"include_subs=True must return roots + subs; got {ids}"
        )

    def test_pure_root_set_unchanged_by_flag(self, conversation_store, db_conn):
        """A tree with no subs returns the same row both ways — the
        flag is a no-op when there's nothing to filter out."""
        conversation_store.upsert(
            Conversation(id="lone", location="/tmp/lone", source="cloud")
        )
        db_conn.commit()

        default_ids = {c.id for c in conversation_store.list_by_date_range()}
        with_subs_ids = {
            c.id for c in conversation_store.list_by_date_range(include_subs=True)
        }
        assert default_ids == with_subs_ids == {"lone"}

    def test_orphan_sub_is_its_own_root_and_appears_by_default(
        self, conversation_store, db_conn
    ):
        """Per AGENTS.md item #32 + migration 020 orphan policy: a sub
        whose parent isn't in the local DB gets ``root_conversation_id
        = id`` and is therefore a root for this query's purposes. The
        ``gen`` family will still see it (which is the right call —
        we have no way to identify it as a sub without the parent's
        provenance)."""
        conversation_store.upsert(
            Conversation(
                id="orph0",
                location="/tmp/orph0",
                source="cloud",
                parent_conversation_id="ghostroot",
            )
        )
        db_conn.commit()

        default_ids = {c.id for c in conversation_store.list_by_date_range()}
        assert default_ids == {"orph0"}

    def test_date_filter_still_applies_with_subs_excluded(
        self, conversation_store, db_conn
    ):
        """``since`` / ``until`` are AND-ed with the roots predicate."""
        root_id, _, _ = self._seed_root_and_subs(
            conversation_store, db_conn, created_at="2024-03-15T10:00:00+00:00"
        )
        # Add another root outside the window.
        conversation_store.upsert(
            Conversation(
                id="rold0",
                location="/tmp/rold0",
                source="cloud",
                created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            )
        )
        db_conn.commit()

        result = conversation_store.list_by_date_range(
            since=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        ids = {c.id for c in result}
        assert ids == {root_id}

    def test_source_filter_still_applies_with_subs_excluded(
        self, conversation_store, db_conn
    ):
        """``source`` filter is AND-ed with the roots predicate."""
        self._seed_root_and_subs(conversation_store, db_conn)
        # A local-source root should also exist for filter sanity.
        conversation_store.upsert(
            Conversation(id="localroot", location="/tmp/localroot", source="local")
        )
        db_conn.commit()

        cloud_result = conversation_store.list_by_date_range(source="cloud")
        assert {c.id for c in cloud_result} == {"r0001"}

        local_result = conversation_store.list_by_date_range(source="local")
        assert {c.id for c in local_result} == {"localroot"}

    def test_guard_raises_when_migration_020_missing(self, db_conn):
        """A schema without ``root_conversation_id`` → loud failure.

        Message must reference migration ``020`` and ``ohtv db scan``
        so users know how to fix it. Mirrors the guard pattern from
        #123 / #124 (per PR #153). We tear down migration 020's
        column + supporting index to mimic a pre-020 dataset.
        """
        # Drop the partial index + view first — both reference the column.
        db_conn.execute("DROP INDEX IF EXISTS idx_conversations_root")
        db_conn.execute("DROP VIEW IF EXISTS conversations_by_root")
        db_conn.execute("ALTER TABLE conversations DROP COLUMN root_conversation_id")
        db_conn.commit()

        store = ConversationStore(db_conn)
        with pytest.raises(RuntimeError) as exc_info:
            store.list_by_date_range()  # default include_subs=False
        msg = str(exc_info.value)
        assert "migration 020" in msg, f"Guard must reference '020', got: {msg}"
        assert "ohtv db scan" in msg, f"Guard must hint 'ohtv db scan', got: {msg}"
        # Cluster wording: the message should say "gen" since this
        # path is reached from the gen-family commands.
        assert "gen" in msg

    def test_guard_does_not_fire_when_include_subs_true(self, db_conn):
        """Callers that opt in to subs don't need migration 020 — the
        guard only fires when the SQL predicate is about to be added.
        This is what lets pre-020 callers (e.g. legacy ``list``)
        continue to work via the explicit ``include_subs=True`` opt-out
        in ``cli.py``.
        """
        # Seed a row first (the FK / index structure tolerates the
        # column being present; we only drop it below to simulate
        # the pre-020 surface).
        store = ConversationStore(db_conn)
        store.upsert(Conversation(id="legacy", location="/tmp/legacy", source="cloud"))
        db_conn.commit()

        db_conn.execute("DROP INDEX IF EXISTS idx_conversations_root")
        db_conn.execute("DROP VIEW IF EXISTS conversations_by_root")
        db_conn.execute("ALTER TABLE conversations DROP COLUMN root_conversation_id")
        db_conn.commit()

        # The select statement references root_conversation_id via
        # ``_ALL_COLUMNS``; with the column gone the query raises
        # OperationalError. That's expected — the guard's promise is
        # only about the ``include_subs=False`` predicate path. We
        # therefore can't usefully ``SELECT *`` from a column-stripped
        # row. Instead, verify the function does NOT raise the
        # RuntimeError guard (the SQL error is a separate failure
        # mode and not the one we're asserting on).
        try:
            store.list_by_date_range(include_subs=True)
        except RuntimeError as e:
            pytest.fail(
                f"include_subs=True must not trip the migration-020 guard; "
                f"got: {e}"
            )
        except sqlite3.OperationalError:
            # Acceptable — the underlying SELECT can't run because we
            # tore down the ``_ALL_COLUMNS`` shape. The point of this
            # test is just that the *guard* doesn't fire.
            pass
