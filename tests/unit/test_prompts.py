"""Tests for ohtv.prompts module."""

import hashlib
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from ohtv.prompts import (
    get_prompt,
    get_prompt_hash,
    get_default_prompts_dir,
    get_user_prompts_dir,
    PROMPT_NAMES,
)


class TestGetPrompt:
    """Tests for get_prompt function."""

    def test_loads_default_prompts(self):
        """All default prompts should be loadable."""
        for name in PROMPT_NAMES:
            prompt = get_prompt(name)
            assert prompt, f"Prompt '{name}' should not be empty"
            assert isinstance(prompt, str)

    def test_raises_on_unknown_prompt(self):
        """Should raise ValueError for unknown prompt names."""
        with pytest.raises(ValueError, match="Unknown prompt"):
            get_prompt("nonexistent_prompt")

    def test_prompts_contain_expected_content(self):
        """Brief prompt should contain JSON format instructions."""
        prompt = get_prompt("brief")
        assert "json" in prompt.lower() or "JSON" in prompt


class TestGetPromptHash:
    """Tests for get_prompt_hash function."""

    def test_returns_16_char_hex_string(self):
        """Hash should be exactly 16 hex characters."""
        for name in PROMPT_NAMES:
            hash_val = get_prompt_hash(name)
            assert len(hash_val) == 16, f"Hash for '{name}' should be 16 chars"
            assert all(c in "0123456789abcdef" for c in hash_val)

    def test_hash_matches_content(self):
        """Hash should match SHA256 of prompt content."""
        for name in PROMPT_NAMES:
            content = get_prompt(name)
            expected = hashlib.sha256(content.encode()).hexdigest()[:16]
            actual = get_prompt_hash(name)
            assert actual == expected, f"Hash mismatch for '{name}'"

    def test_raises_on_unknown_prompt(self):
        """Should raise ValueError for unknown prompt names."""
        with pytest.raises(ValueError, match="Unknown prompt"):
            get_prompt_hash("nonexistent_prompt")

    def test_different_prompts_have_different_hashes(self):
        """Different prompts should have different hashes."""
        hashes = {name: get_prompt_hash(name) for name in PROMPT_NAMES}
        unique_hashes = set(hashes.values())
        # Allow some collisions but not all the same
        assert len(unique_hashes) > 1, "All prompts have same hash - unexpected"


class TestPromptDirectories:
    """Tests for prompt directory functions."""

    def test_default_prompts_dir_exists(self):
        """Default prompts directory should exist in package."""
        dir_path = get_default_prompts_dir()
        assert dir_path.exists()
        assert dir_path.is_dir()

    def test_default_prompts_dir_has_all_prompts(self):
        """Default prompts directory should contain all prompt files."""
        dir_path = get_default_prompts_dir()
        for name in PROMPT_NAMES:
            prompt_file = dir_path / f"{name}.md"
            assert prompt_file.exists(), f"Missing default prompt: {name}.md"

    def test_user_prompts_dir_is_in_ohtv_dir(self):
        """User prompts directory should be under ~/.ohtv/."""
        dir_path = get_user_prompts_dir()
        assert "ohtv" in str(dir_path).lower()
        assert dir_path.name == "prompts"


class TestPromptHashCacheInvalidation:
    """Tests for cache invalidation when prompts change."""

    def test_cache_invalidates_on_prompt_hash_mismatch(self, tmp_path):
        """Cache should invalidate when prompt hash changes."""
        from ohtv.analysis.cache import AnalysisCacheManager, CachedAnalysis
        
        # Create a simple test model
        class TestAnalysis(CachedAnalysis):
            test_field: str = "test"
        
        manager = AnalysisCacheManager("test_cache.json", TestAnalysis)
        
        # Create a fake conversation directory with events
        conv_dir = tmp_path / "test_conv"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "event-001.json").write_text(json.dumps({"kind": "test"}))
        
        events = [{"kind": "test"}]
        content_hash = "abc123"
        old_prompt_hash = "oldhash12345678"
        new_prompt_hash = "newhash87654321"
        
        # Save analysis with old prompt hash
        analysis = TestAnalysis(
            conversation_id="test_conv",
            analyzed_at=datetime.now(timezone.utc),
            model_used="test-model",
            event_count=1,
            content_hash=content_hash,
            prompt_hash=old_prompt_hash,
        )
        manager.save(conv_dir, analysis)
        
        # Try to load with same prompt hash - should succeed
        loaded = manager.load_cached(
            conv_dir, events, content_hash,
            prompt_hash=old_prompt_hash,
        )
        assert loaded is not None
        assert loaded.prompt_hash == old_prompt_hash
        
        # Try to load with different prompt hash - should fail
        loaded = manager.load_cached(
            conv_dir, events, content_hash,
            prompt_hash=new_prompt_hash,
        )
        assert loaded is None

    def test_cache_loads_when_no_prompt_hash_stored(self, tmp_path):
        """Cache without stored prompt_hash should load (backward compat)."""
        from ohtv.analysis.cache import AnalysisCacheManager, CachedAnalysis
        
        class TestAnalysis(CachedAnalysis):
            test_field: str = "test"
        
        manager = AnalysisCacheManager("test_cache.json", TestAnalysis)
        
        conv_dir = tmp_path / "test_conv"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "event-001.json").write_text(json.dumps({"kind": "test"}))
        
        events = [{"kind": "test"}]
        content_hash = "abc123"
        
        # Save analysis WITHOUT prompt hash (simulate old cache)
        analysis = TestAnalysis(
            conversation_id="test_conv",
            analyzed_at=datetime.now(timezone.utc),
            model_used="test-model",
            event_count=1,
            content_hash=content_hash,
            prompt_hash=None,  # No prompt hash
        )
        manager.save(conv_dir, analysis)
        
        # Load without providing prompt_hash - should succeed
        loaded = manager.load_cached(conv_dir, events, content_hash)
        assert loaded is not None
        
        # Load WITH prompt_hash but cached has None - should succeed (no validation)
        loaded = manager.load_cached(
            conv_dir, events, content_hash,
            prompt_hash="somehash12345678",
        )
        assert loaded is not None

    def test_cache_loads_when_no_prompt_hash_provided(self, tmp_path):
        """Cache with stored prompt_hash loads if no hash provided for validation."""
        from ohtv.analysis.cache import AnalysisCacheManager, CachedAnalysis
        
        class TestAnalysis(CachedAnalysis):
            test_field: str = "test"
        
        manager = AnalysisCacheManager("test_cache.json", TestAnalysis)
        
        conv_dir = tmp_path / "test_conv"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (events_dir / "event-001.json").write_text(json.dumps({"kind": "test"}))
        
        events = [{"kind": "test"}]
        content_hash = "abc123"
        stored_hash = "storedhash12345"
        
        # Save analysis WITH prompt hash
        analysis = TestAnalysis(
            conversation_id="test_conv",
            analyzed_at=datetime.now(timezone.utc),
            model_used="test-model",
            event_count=1,
            content_hash=content_hash,
            prompt_hash=stored_hash,
        )
        manager.save(conv_dir, analysis)
        
        # Load WITHOUT providing prompt_hash - should succeed (no validation)
        loaded = manager.load_cached(conv_dir, events, content_hash)
        assert loaded is not None
        assert loaded.prompt_hash == stored_hash
