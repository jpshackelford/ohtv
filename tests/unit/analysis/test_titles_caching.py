"""Integration tests for cached title generation (Issue #191)."""

import sqlite3

import pytest

from ohtv.analysis.titles import (
    SYNTHESIS_SCHEMA_VERSION,
    generate_titles_with_cache,
)
from ohtv.db.migrations import migrate
from ohtv.db.stores.synthesis_cache_store import SynthesisCacheStore


@pytest.fixture
def db_with_cache():
    """In-memory database with full schema including synthesis cache."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    
    # Apply all migrations to get full schema
    migrate(conn)
    
    # Insert test conversations (location is required)
    conn.execute(
        "INSERT INTO conversations (id, location, updated_at, source) VALUES (?, ?, ?, ?)",
        ("abc123", "/path/to/conv1", "2024-01-01T00:00:00Z", "cloud")
    )
    conn.execute(
        "INSERT INTO conversations (id, location, updated_at, source) VALUES (?, ?, ?, ?)",
        ("def456", "/path/to/conv2", "2024-01-02T00:00:00Z", "cloud")
    )
    conn.execute(
        "INSERT INTO conversations (id, location, updated_at, source) VALUES (?, ?, ?, ?)",
        ("ghi789", "/path/to/conv3", "2024-01-03T00:00:00Z", "cloud")
    )
    conn.commit()
    
    yield conn
    conn.close()


def make_mock_llm_call():
    """Factory that returns a mock LLM callable."""
    def mock_llm_call(system_prompt: str, user_prompt: str):
        """Mock LLM callable that returns static titles."""
        import json
        import re
        
        # Find the JSON array in the prompt (may span multiple lines)
        # Look for the text between "Respond with JSON only." and end
        match = re.search(r'\[\s*\{.*?\}\s*\]', user_prompt, re.DOTALL)
        if match:
            items = json.loads(match.group(0))
        else:
            items = []
        
        # Generate mock titles
        results = []
        for item in items:
            conv_id = item["id"]
            desc = item["description"]
            # Simple title based on first few words of description
            words = desc.split()[:3]
            title = " ".join(words).title()
            results.append({"id": conv_id, "title": title})
        
        response = json.dumps(results, indent=2)
        cost = 0.01 * len(items)  # Mock cost
        return response, cost
    
    return mock_llm_call


def test_empty_cache_synthesizes_all(db_with_cache, monkeypatch):
    """Test that empty cache results in LLM synthesis for all conversations."""
    conversations = [
        ("abc123", "2024-01-01T00:00:00Z", "Fix auth bug"),
        ("def456", "2024-01-02T00:00:00Z", "Add new feature"),
    ]
    
    # Mock database connection
    import ohtv.db as db_module
    from contextlib import contextmanager
    
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
    
    result = generate_titles_with_cache(
        conversations, 
        model="gpt-4o-mini",
        llm_call=make_mock_llm_call()
    )
    
    assert result.cache_hits == 0
    assert result.cache_misses == 2
    assert len(result.titles) == 2
    assert result.cost > 0
    assert "abc123" in result.titles
    assert "def456" in result.titles
    assert result.was_cached["abc123"] is False
    assert result.was_cached["def456"] is False


def test_full_cache_hits_all(db_with_cache):
    """Test that full cache results in all cache hits."""
    store = SynthesisCacheStore(db_with_cache)
    
    # Pre-populate cache
    store.upsert_title(
        "abc123", "2024-01-01T00:00:00Z", "Fix Auth Bug",
        "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION, 10
    )
    store.upsert_title(
        "def456", "2024-01-02T00:00:00Z", "Add New Feature",
        "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION, 12
    )
    db_with_cache.commit()
    
    conversations = [
        ("abc123", "2024-01-01T00:00:00Z", "Fix auth bug"),
        ("def456", "2024-01-02T00:00:00Z", "Add new feature"),
    ]
    
    # Mock database connection
    import ohtv.db as db_module
    original_get_ready_connection = db_module.get_ready_connection
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        result = generate_titles_with_cache(conversations, model="gpt-4o-mini")
        
        assert result.cache_hits == 2
        assert result.cache_misses == 0
        assert len(result.titles) == 2
        assert result.cost == 0  # No LLM calls
        assert result.titles["abc123"] == "Fix Auth Bug"
        assert result.titles["def456"] == "Add New Feature"
        assert result.was_cached["abc123"] is True
        assert result.was_cached["def456"] is True
    
    finally:
        monkeypatch.setattr(db_module, "get_ready_connection", original_get_ready_connection)


def test_mixed_cache_hits_and_misses(db_with_cache, monkeypatch):
    """Test mixed cache hits and misses."""
    store = SynthesisCacheStore(db_with_cache)
    
    # Pre-populate cache for one conversation
    store.upsert_title(
        "abc123", "2024-01-01T00:00:00Z", "Fix Auth Bug",
        "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION, 10
    )
    db_with_cache.commit()
    
    conversations = [
        ("abc123", "2024-01-01T00:00:00Z", "Fix auth bug"),
        ("def456", "2024-01-02T00:00:00Z", "Add new feature"),
    ]
    
    # Patch LLM call
    import ohtv.analysis.titles as titles_module
    monkeypatch.setattr(titles_module, "_default_llm_callable", lambda model: make_mock_llm_call())
    
    # Mock database connection
    import ohtv.db as db_module
    original_get_ready_connection = db_module.get_ready_connection
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    try:
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        result = generate_titles_with_cache(conversations, model="gpt-4o-mini")
        
        assert result.cache_hits == 1
        assert result.cache_misses == 1
        assert len(result.titles) == 2
        assert result.cost > 0  # LLM call for one conversation
        assert result.titles["abc123"] == "Fix Auth Bug"
        assert "def456" in result.titles
        assert result.was_cached["abc123"] is True
        assert result.was_cached["def456"] is False
    
    finally:
        monkeypatch.setattr(db_module, "get_ready_connection", original_get_ready_connection)


def test_force_refresh_bypasses_cache(db_with_cache, monkeypatch):
    """Test that force_refresh bypasses cache."""
    store = SynthesisCacheStore(db_with_cache)
    
    # Pre-populate cache
    store.upsert_title(
        "abc123", "2024-01-01T00:00:00Z", "Old Title",
        "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION, 10
    )
    db_with_cache.commit()
    
    conversations = [
        ("abc123", "2024-01-01T00:00:00Z", "Fix auth bug"),
    ]
    
    # Patch LLM call
    import ohtv.analysis.titles as titles_module
    monkeypatch.setattr(titles_module, "_default_llm_callable", lambda model: make_mock_llm_call())
    
    # Mock database connection
    import ohtv.db as db_module
    original_get_ready_connection = db_module.get_ready_connection
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    try:
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        result = generate_titles_with_cache(
            conversations, 
            model="gpt-4o-mini",
            force_refresh=True
        )
        
        assert result.cache_hits == 0
        assert result.cache_misses == 1
        assert len(result.titles) == 1
        assert result.cost > 0
        assert result.titles["abc123"] != "Old Title"  # New title generated
        assert result.was_cached["abc123"] is False
    
    finally:
        monkeypatch.setattr(db_module, "get_ready_connection", original_get_ready_connection)


def test_cache_invalidation_on_updated_at_change(db_with_cache):
    """Test that cache invalidates when conversation updated_at changes."""
    store = SynthesisCacheStore(db_with_cache)
    
    # Pre-populate cache with old updated_at
    store.upsert_title(
        "abc123", "2024-01-01T00:00:00Z", "Old Title",
        "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION, 10
    )
    db_with_cache.commit()
    
    conversations = [
        ("abc123", "2024-01-02T00:00:00Z", "Fix auth bug"),  # Different updated_at
    ]
    
    # Mock database connection
    import ohtv.db as db_module
    original_get_ready_connection = db_module.get_ready_connection
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    
    # Patch LLM call
    import ohtv.analysis.titles as titles_module
    monkeypatch.setattr(titles_module, "_default_llm_callable", lambda model: make_mock_llm_call())
    
    try:
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        result = generate_titles_with_cache(conversations, model="gpt-4o-mini")
        
        # Cache miss due to updated_at mismatch
        assert result.cache_hits == 0
        assert result.cache_misses == 1
    
    finally:
        monkeypatch.setattr(db_module, "get_ready_connection", original_get_ready_connection)


def test_cache_invalidation_on_model_change(db_with_cache):
    """Test that cache invalidates when model changes."""
    store = SynthesisCacheStore(db_with_cache)
    
    # Pre-populate cache with gpt-4o-mini
    store.upsert_title(
        "abc123", "2024-01-01T00:00:00Z", "Old Title",
        "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION, 10
    )
    db_with_cache.commit()
    
    conversations = [
        ("abc123", "2024-01-01T00:00:00Z", "Fix auth bug"),
    ]
    
    # Mock database connection
    import ohtv.db as db_module
    original_get_ready_connection = db_module.get_ready_connection
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    
    # Patch LLM call
    import ohtv.analysis.titles as titles_module
    monkeypatch.setattr(titles_module, "_default_llm_callable", lambda model: make_mock_llm_call())
    
    try:
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        # Request with different model
        result = generate_titles_with_cache(conversations, model="haiku")
        
        # Cache miss due to model mismatch
        assert result.cache_hits == 0
        assert result.cache_misses == 1
    
    finally:
        monkeypatch.setattr(db_module, "get_ready_connection", original_get_ready_connection)


def test_new_titles_cached_after_generation(db_with_cache, monkeypatch):
    """Test that newly generated titles are cached."""
    store = SynthesisCacheStore(db_with_cache)
    
    conversations = [
        ("abc123", "2024-01-01T00:00:00Z", "Fix auth bug"),
    ]
    
    # Patch LLM call
    import ohtv.analysis.titles as titles_module
    monkeypatch.setattr(titles_module, "_default_llm_callable", lambda model: make_mock_llm_call())
    
    # Mock database connection
    import ohtv.db as db_module
    original_get_ready_connection = db_module.get_ready_connection
    
    from contextlib import contextmanager
    @contextmanager
    def mock_get_ready_connection():
        yield db_with_cache
    
    try:
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        # First call - cache miss
        result1 = generate_titles_with_cache(conversations, model="gpt-4o-mini")
        assert result1.cache_misses == 1
        
        # Verify entry was cached
        cached = store.get_cached_title(
            "abc123", "2024-01-01T00:00:00Z", "gpt-4o-mini", SYNTHESIS_SCHEMA_VERSION
        )
        assert cached is not None
        assert cached == result1.titles["abc123"]
        
        # Second call - cache hit (without LLM patch - would fail if LLM is called)
        monkeypatch.undo()  # Remove LLM patch
        monkeypatch.setattr(db_module, "get_ready_connection", mock_get_ready_connection)
        
        result2 = generate_titles_with_cache(conversations, model="gpt-4o-mini")
        assert result2.cache_hits == 1
        assert result2.cache_misses == 0
        assert result2.cost == 0
        assert result2.titles["abc123"] == result1.titles["abc123"]
    
    finally:
        monkeypatch.setattr(db_module, "get_ready_connection", original_get_ready_connection)
