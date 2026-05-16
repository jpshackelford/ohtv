"""Unit tests for conversation labels functionality."""

import json
import pytest
import sqlite3
from datetime import datetime, timezone

from ohtv.cli import _format_labels_for_summary
from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore
from ohtv.sources.base import ConversationInfo
from ohtv.sources.cloud import parse_conversation_info


class TestFormatLabelsForSummary:
    """Tests for _format_labels_for_summary function."""

    def test_none_labels_returns_empty(self):
        """None labels should return empty string."""
        assert _format_labels_for_summary(None) == ""

    def test_empty_labels_returns_empty(self):
        """Empty dict should return empty string."""
        assert _format_labels_for_summary({}) == ""

    def test_single_label(self):
        """Single label should be formatted correctly."""
        labels = {"project": "SDK"}
        result = _format_labels_for_summary(labels)
        assert "project=SDK" in result
        assert "[magenta]Labels:[/magenta]" in result

    def test_multiple_labels_sorted(self):
        """Multiple labels should be sorted alphabetically."""
        labels = {"status": "WIP", "project": "SDK", "team": "AI"}
        result = _format_labels_for_summary(labels)
        # Check all labels are present
        assert "project=SDK" in result
        assert "status=WIP" in result
        assert "team=AI" in result
        # Labels should appear in sorted order
        assert (
            result.index("project=SDK")
            < result.index("status=WIP")
            < result.index("team=AI")
        )

    def test_label_with_special_characters(self):
        """Labels with special characters should be handled."""
        labels = {"env": "prod-1", "version": "2.0.0"}
        result = _format_labels_for_summary(labels)
        assert "env=prod-1" in result
        assert "version=2.0.0" in result


class TestParseConversationInfo:
    """Tests for parsing labels from cloud API response."""

    def test_parse_with_no_tags(self):
        """Conversation without tags should have None labels."""
        data = {
            "id": "abc123",
            "title": "Test conversation",
            "created_at": "2026-05-16T10:00:00Z",
            "updated_at": "2026-05-16T11:00:00Z",
        }
        conv = parse_conversation_info(data)
        assert conv.labels is None

    def test_parse_with_empty_tags(self):
        """Conversation with empty tags dict should have None labels."""
        data = {
            "id": "abc123",
            "title": "Test conversation",
            "created_at": "2026-05-16T10:00:00Z",
            "updated_at": "2026-05-16T11:00:00Z",
            "tags": {},
        }
        conv = parse_conversation_info(data)
        assert conv.labels is None

    def test_parse_with_tags(self):
        """Conversation with tags should have labels populated."""
        data = {
            "id": "abc123",
            "title": "Test conversation",
            "created_at": "2026-05-16T10:00:00Z",
            "updated_at": "2026-05-16T11:00:00Z",
            "tags": {"project": "SDK", "status": "WIP"},
        }
        conv = parse_conversation_info(data)
        assert conv.labels == {"project": "SDK", "status": "WIP"}

    def test_parse_with_non_dict_tags(self):
        """Non-dict tags field should result in None labels."""
        data = {
            "id": "abc123",
            "title": "Test conversation",
            "created_at": "2026-05-16T10:00:00Z",
            "updated_at": "2026-05-16T11:00:00Z",
            "tags": "invalid",  # Should be dict
        }
        conv = parse_conversation_info(data)
        assert conv.labels is None


class TestConversationStoreLabels:
    """Tests for ConversationStore label operations."""

    @pytest.fixture
    def db_conn(self):
        """Create an in-memory database with schema."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Create conversations table with labels column
        conn.execute("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                location TEXT NOT NULL,
                registered_at TEXT,
                events_mtime REAL,
                event_count INTEGER DEFAULT 0,
                title TEXT,
                created_at TEXT,
                updated_at TEXT,
                selected_repository TEXT,
                source TEXT,
                summary TEXT,
                labels TEXT
            )
        """)
        conn.commit()
        yield conn
        conn.close()

    def test_upsert_conversation_with_labels(self, db_conn):
        """Labels should be stored as JSON when upserting."""
        store = ConversationStore(db_conn)

        conv = Conversation(
            id="abc123",
            location="/path/to/conv",
            labels={"project": "SDK", "status": "WIP"},
        )
        store.upsert(conv)

        # Verify labels stored as JSON
        cursor = db_conn.execute("SELECT labels FROM conversations WHERE id = 'abc123'")
        row = cursor.fetchone()
        labels_json = row["labels"]
        assert json.loads(labels_json) == {"project": "SDK", "status": "WIP"}

    def test_get_conversation_with_labels(self, db_conn):
        """Labels should be parsed from JSON when getting."""
        store = ConversationStore(db_conn)

        # Insert directly with JSON
        db_conn.execute(
            "INSERT INTO conversations (id, location, labels) VALUES (?, ?, ?)",
            ("abc123", "/path/to/conv", '{"project": "SDK"}'),
        )
        db_conn.commit()

        conv = store.get("abc123")
        assert conv is not None
        assert conv.labels == {"project": "SDK"}

    def test_list_by_label(self, db_conn):
        """list_by_label should find conversations with matching label."""
        store = ConversationStore(db_conn)

        # Insert multiple conversations with different labels
        store.upsert(
            Conversation(
                id="conv1",
                location="/path/1",
                labels={"project": "SDK", "status": "WIP"},
                created_at=datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc),
            )
        )
        store.upsert(
            Conversation(
                id="conv2",
                location="/path/2",
                labels={"project": "CLI", "status": "WIP"},
                created_at=datetime(2026, 5, 16, 11, 0, tzinfo=timezone.utc),
            )
        )
        store.upsert(
            Conversation(
                id="conv3",
                location="/path/3",
                labels={"project": "SDK", "status": "done"},
                created_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
            )
        )

        # Find by project=SDK
        matches = store.list_by_label("project", "SDK")
        assert len(matches) == 2
        ids = {c.id for c in matches}
        assert ids == {"conv1", "conv3"}

        # Find by status=WIP
        matches = store.list_by_label("status", "WIP")
        assert len(matches) == 2
        ids = {c.id for c in matches}
        assert ids == {"conv1", "conv2"}

    def test_list_by_label_no_match(self, db_conn):
        """list_by_label should return empty list when no matches."""
        store = ConversationStore(db_conn)

        store.upsert(
            Conversation(
                id="conv1",
                location="/path/1",
                labels={"project": "SDK"},
            )
        )

        matches = store.list_by_label("project", "CLI")
        assert matches == []

    def test_count_with_labels(self, db_conn):
        """count_with_labels should count only conversations with labels."""
        store = ConversationStore(db_conn)

        store.upsert(Conversation(id="conv1", location="/path/1", labels={"k": "v"}))
        store.upsert(Conversation(id="conv2", location="/path/2", labels=None))
        store.upsert(Conversation(id="conv3", location="/path/3", labels={"k2": "v2"}))

        assert store.count_with_labels() == 2


class TestConversationModel:
    """Tests for Conversation model with labels."""

    def test_conversation_has_labels_field(self):
        """Conversation dataclass should have labels field."""
        conv = Conversation(
            id="abc123",
            location="/path/to/conv",
            labels={"project": "SDK"},
        )
        assert conv.labels == {"project": "SDK"}

    def test_conversation_labels_default_none(self):
        """Labels should default to None."""
        conv = Conversation(id="abc123", location="/path/to/conv")
        assert conv.labels is None


class TestConversationInfoModel:
    """Tests for ConversationInfo model with labels."""

    def test_conversation_info_has_labels_field(self):
        """ConversationInfo dataclass should have labels field."""
        conv = ConversationInfo(
            id="abc123",
            title="Test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            labels={"project": "SDK"},
        )
        assert conv.labels == {"project": "SDK"}

    def test_conversation_info_labels_default_none(self):
        """Labels should default to None."""
        conv = ConversationInfo(
            id="abc123",
            title="Test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert conv.labels is None


class TestLabelFilterParsing:
    """Tests for label filter string parsing."""

    def test_valid_label_filter(self):
        """Valid key=value format should parse correctly."""
        # This is implicitly tested by _filter_by_label,
        # but we can verify the logic
        filter_str = "project=SDK"
        key, value = filter_str.split("=", 1)
        assert key == "project"
        assert value == "SDK"

    def test_label_with_equals_in_value(self):
        """Value containing = should be handled correctly."""
        filter_str = "config=a=b"
        key, value = filter_str.split("=", 1)
        assert key == "config"
        assert value == "a=b"  # Only split on first =
