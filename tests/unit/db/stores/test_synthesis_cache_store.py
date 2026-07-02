"""Unit tests for SynthesisCacheStore (Issue #191)."""

import sqlite3
from datetime import datetime

import pytest

from ohtv.db.stores.synthesis_cache_store import (
    SynthesisCacheEntry,
    SynthesisCacheStore,
)


@pytest.fixture
def db():
    """In-memory database with conversations and conversation_synthesis tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    
    # Create conversations table (minimal schema for testing)
    conn.execute("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            updated_at TEXT
        )
    """)
    
    # Create conversation_synthesis table
    conn.execute("""
        CREATE TABLE conversation_synthesis (
            conversation_id TEXT PRIMARY KEY,
            conversation_updated_at TEXT NOT NULL,
            synthesized_title TEXT,
            synthesized_objective TEXT,
            worklog_purpose TEXT,
            synthesis_model TEXT,
            synthesis_version TEXT NOT NULL,
            synthesized_at TEXT NOT NULL,
            tokens_used INTEGER,
            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id)
                ON DELETE CASCADE
        )
    """)
    
    # Insert test conversation
    conn.execute(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)",
        ("abc123", "2024-01-01T00:00:00Z")
    )
    conn.commit()
    
    yield conn
    conn.close()


def test_upsert_title_new_entry(db):
    """Test inserting a new title cache entry."""
    store = SynthesisCacheStore(db)
    
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Verify entry was created
    cursor = db.execute(
        "SELECT * FROM conversation_synthesis WHERE conversation_id = ?",
        ("abc123",)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["synthesized_title"] == "Fix Auth Bug"
    assert row["synthesis_model"] == "gpt-4o-mini"
    assert row["synthesis_version"] == "v1"
    assert row["tokens_used"] == 10


def test_upsert_title_update_existing(db):
    """Test updating an existing title cache entry."""
    store = SynthesisCacheStore(db)
    
    # Insert initial entry
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Update with new title
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-02T00:00:00Z",
        title="Refactor Auth Module",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=12
    )
    db.commit()
    
    # Verify entry was updated
    cursor = db.execute(
        "SELECT * FROM conversation_synthesis WHERE conversation_id = ?",
        ("abc123",)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["synthesized_title"] == "Refactor Auth Module"
    assert row["conversation_updated_at"] == "2024-01-02T00:00:00Z"
    assert row["tokens_used"] == 12


def test_get_cached_title_hit(db):
    """Test cache hit when all validation fields match."""
    store = SynthesisCacheStore(db)
    
    # Insert cached title
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Cache hit with matching validation fields
    cached = store.get_cached_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v1"
    )
    
    assert cached == "Fix Auth Bug"


def test_get_cached_title_miss_updated_at(db):
    """Test cache miss when conversation updated_at differs."""
    store = SynthesisCacheStore(db)
    
    # Insert cached title
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Cache miss with different updated_at
    cached = store.get_cached_title(
        conv_id="abc123",
        conv_updated_at="2024-01-02T00:00:00Z",  # Different!
        model="gpt-4o-mini",
        version="v1"
    )
    
    assert cached is None


def test_get_cached_title_miss_model(db):
    """Test cache miss when model differs."""
    store = SynthesisCacheStore(db)
    
    # Insert cached title
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Cache miss with different model
    cached = store.get_cached_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="haiku",  # Different!
        version="v1"
    )
    
    assert cached is None


def test_get_cached_title_miss_version(db):
    """Test cache miss when synthesis version differs."""
    store = SynthesisCacheStore(db)
    
    # Insert cached title
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Cache miss with different version
    cached = store.get_cached_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v2"  # Different!
    )
    
    assert cached is None


def test_get_cached_title_miss_no_entry(db):
    """Test cache miss when no entry exists."""
    store = SynthesisCacheStore(db)
    
    # No entry for this conversation
    cached = store.get_cached_title(
        conv_id="xyz789",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v1"
    )
    
    assert cached is None


def test_id_normalization(db):
    """Test that conversation IDs are normalized (dashes removed)."""
    store = SynthesisCacheStore(db)
    
    # Insert with dashed ID
    store.upsert_title(
        conv_id="abc-123-def",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Verify stored without dashes
    cursor = db.execute(
        "SELECT conversation_id FROM conversation_synthesis"
    )
    row = cursor.fetchone()
    assert row["conversation_id"] == "abc123def"
    
    # Retrieve with dashed ID should work
    cached = store.get_cached_title(
        conv_id="abc-123-def",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v1"
    )
    assert cached == "Fix Auth Bug"


def test_upsert_objective(db):
    """Test upserting objective cache entries."""
    store = SynthesisCacheStore(db)
    
    store.upsert_objective(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        objective="Implement user authentication",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=20
    )
    db.commit()
    
    # Verify entry was created
    cursor = db.execute(
        "SELECT * FROM conversation_synthesis WHERE conversation_id = ?",
        ("abc123",)
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["synthesized_objective"] == "Implement user authentication"


def test_get_cached_objective(db):
    """Test retrieving cached objective."""
    store = SynthesisCacheStore(db)
    
    # Insert cached objective
    store.upsert_objective(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        objective="Implement user authentication",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=20
    )
    db.commit()
    
    # Cache hit
    cached = store.get_cached_objective(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v1"
    )
    
    assert cached == "Implement user authentication"


def test_count_cached_titles(db):
    """Test counting conversations with cached titles."""
    store = SynthesisCacheStore(db)
    
    # Insert conversation with title only
    db.execute(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)",
        ("def456", "2024-01-01T00:00:00Z")
    )
    
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    
    # Insert conversation with objective only
    store.upsert_objective(
        conv_id="def456",
        conv_updated_at="2024-01-01T00:00:00Z",
        objective="Add feature",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=15
    )
    db.commit()
    
    assert store.count_cached_titles() == 1
    assert store.count_cached_objectives() == 1


def test_count_stale_entries(db):
    """Test counting stale cache entries."""
    store = SynthesisCacheStore(db)
    
    # Insert cached title
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    db.commit()
    
    # Initially not stale
    assert store.count_stale_entries() == 0
    
    # Update conversation timestamp to make cache stale
    db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        ("2024-01-02T00:00:00Z", "abc123")
    )
    db.commit()
    
    # Now stale
    assert store.count_stale_entries() == 1


def test_get_total_tokens_saved(db):
    """Test getting total tokens saved estimate."""
    store = SynthesisCacheStore(db)
    
    # Insert conversation for second entry
    db.execute(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)",
        ("def456", "2024-01-01T00:00:00Z")
    )
    
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    
    store.upsert_title(
        conv_id="def456",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Add Feature",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=15
    )
    db.commit()
    
    assert store.get_total_tokens_saved() == 25


def test_clear_all(db):
    """Test clearing all cache entries."""
    store = SynthesisCacheStore(db)
    
    # Insert two entries
    db.execute(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)",
        ("def456", "2024-01-01T00:00:00Z")
    )
    
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    
    store.upsert_title(
        conv_id="def456",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Add Feature",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=15
    )
    db.commit()
    
    # Clear all
    deleted = store.clear_all()
    db.commit()
    
    assert deleted == 2
    assert store.count_cached_titles() == 0


def test_clear_stale(db):
    """Test clearing only stale cache entries."""
    store = SynthesisCacheStore(db)
    
    # Insert two conversations
    db.execute(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)",
        ("def456", "2024-01-01T00:00:00Z")
    )
    
    # Insert two cached titles
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    
    store.upsert_title(
        conv_id="def456",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Add Feature",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=15
    )
    db.commit()
    
    # Make one entry stale
    db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        ("2024-01-02T00:00:00Z", "abc123")
    )
    db.commit()
    
    # Clear stale
    deleted = store.clear_stale()
    db.commit()
    
    assert deleted == 1
    assert store.count_cached_titles() == 1
    
    # Verify correct entry was deleted
    cached = store.get_cached_title(
        conv_id="def456",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v1"
    )
    assert cached == "Add Feature"


def test_delete_for_conversation(db):
    """Test deleting cache entry for a specific conversation."""
    store = SynthesisCacheStore(db)
    
    # Insert conversation and cache entry
    db.execute(
        "INSERT INTO conversations (id, updated_at) VALUES (?, ?)",
        ("def456", "2024-01-01T00:00:00Z")
    )
    
    store.upsert_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Fix Auth Bug",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=10
    )
    
    store.upsert_title(
        conv_id="def456",
        conv_updated_at="2024-01-01T00:00:00Z",
        title="Add Feature",
        model="gpt-4o-mini",
        version="v1",
        tokens_used=15
    )
    db.commit()
    
    # Delete one conversation's cache
    store.delete_for_conversation("abc123")
    db.commit()
    
    assert store.count_cached_titles() == 1
    
    # Verify correct entry was deleted
    cached = store.get_cached_title(
        conv_id="abc123",
        conv_updated_at="2024-01-01T00:00:00Z",
        model="gpt-4o-mini",
        version="v1"
    )
    assert cached is None
