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
