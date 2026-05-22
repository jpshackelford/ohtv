"""Unit tests for ConversationStore."""

from ohtv.db.models import Conversation


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
