"""Tests for prompt discovery and resolution."""

import shutil
import tempfile
from pathlib import Path

import pytest

from ohtv.prompts.discovery import (
    clear_prompt_cache,
    discover_prompts,
    get_prompts_dirs,
    list_families,
    list_variants,
    resolve_context,
    resolve_prompt,
)
from ohtv.prompts.metadata import PromptMetadata


class TestGetPromptsDirs:
    """Tests for get_prompts_dirs()"""
    
    def test_returns_two_directories(self):
        """Test that get_prompts_dirs returns user and default directories"""
        dirs = get_prompts_dirs()
        assert len(dirs) == 2
        assert all(isinstance(d, Path) for d in dirs)
    
    def test_user_dir_first(self):
        """Test that user directory comes before default directory"""
        dirs = get_prompts_dirs()
        user_dir, default_dir = dirs
        assert "prompts" in str(user_dir)
        assert ".ohtv" in str(user_dir) or "ohtv" in str(user_dir)
        assert "prompts" in str(default_dir)


class TestDiscoverPrompts:
    """Tests for discover_prompts()"""
    
    def setup_method(self):
        """Clear cache before each test"""
        clear_prompt_cache()
    
    def test_discovers_default_prompts(self):
        """Test that discover_prompts finds prompts in default directory"""
        prompts = discover_prompts()
        
        assert isinstance(prompts, dict)
        assert len(prompts) > 0
        
        # Check that objectives family exists
        assert "objectives" in prompts
        assert "brief" in prompts["objectives"]
        
        # Check that metadata is correct type
        brief = prompts["objectives"]["brief"]
        assert isinstance(brief, PromptMetadata)
        assert brief.family == "objectives"
        assert brief.variant == "brief"
    
    def test_organizes_by_family_and_variant(self):
        """Test that prompts are organized by family then variant"""
        prompts = discover_prompts()
        
        for family, variants in prompts.items():
            assert isinstance(family, str)
            assert isinstance(variants, dict)
            
            for variant, meta in variants.items():
                assert isinstance(variant, str)
                assert isinstance(meta, PromptMetadata)
                assert meta.family == family
                assert meta.variant == variant
    
    def test_caches_results(self):
        """Test that discover_prompts caches results"""
        result1 = discover_prompts()
        result2 = discover_prompts()
        
        # Should be the same object (cached)
        assert result1 is result2
    
    def test_clear_cache(self):
        """Test that clear_prompt_cache invalidates cache"""
        result1 = discover_prompts()
        clear_prompt_cache()
        result2 = discover_prompts()
        
        # Should be different objects (cache cleared)
        assert result1 is not result2


class TestUserOverride:
    """Tests for user prompt override functionality"""
    
    def setup_method(self):
        """Set up temporary directories for testing"""
        clear_prompt_cache()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.user_dir = self.temp_dir / "user" / "prompts"
        self.default_dir = self.temp_dir / "default" / "prompts"
        
        self.user_dir.mkdir(parents=True)
        self.default_dir.mkdir(parents=True)
    
    def teardown_method(self):
        """Clean up temporary directories"""
        clear_prompt_cache()
        shutil.rmtree(self.temp_dir)
    
    def test_user_prompts_override_defaults(self, monkeypatch):
        """Test that user prompts override default prompts"""
        # Create default prompt
        family_dir = self.default_dir / "test_family"
        family_dir.mkdir()
        default_prompt = family_dir / "variant1.md"
        default_prompt.write_text("""---
id: test_family.variant1
family: test_family
variant: variant1
description: Default version
---
Default content""")
        
        # Create user override
        user_family_dir = self.user_dir / "test_family"
        user_family_dir.mkdir()
        user_prompt = user_family_dir / "variant1.md"
        user_prompt.write_text("""---
id: test_family.variant1
family: test_family
variant: variant1
description: User version
---
User content""")
        
        # Mock get_prompts_dirs to use our temp directories
        def mock_get_prompts_dirs():
            return [self.user_dir, self.default_dir]
        
        monkeypatch.setattr("ohtv.prompts.discovery.get_prompts_dirs", mock_get_prompts_dirs)
        clear_prompt_cache()
        
        prompts = discover_prompts()
        
        # Should have user version
        assert "test_family" in prompts
        assert "variant1" in prompts["test_family"]
        meta = prompts["test_family"]["variant1"]
        assert meta.description == "User version"
        assert meta.content == "User content"


class TestListFamilies:
    """Tests for list_families()"""
    
    def setup_method(self):
        clear_prompt_cache()
    
    def test_returns_sorted_list(self):
        """Test that list_families returns sorted list of family names"""
        families = list_families()
        
        assert isinstance(families, list)
        assert len(families) > 0
        assert all(isinstance(f, str) for f in families)
        
        # Should be sorted
        assert families == sorted(families)
    
    def test_includes_known_families(self):
        """Test that known families are included"""
        families = list_families()
        assert "objectives" in families


class TestListVariants:
    """Tests for list_variants()"""
    
    def setup_method(self):
        clear_prompt_cache()
    
    def test_returns_sorted_list(self):
        """Test that list_variants returns sorted list of variant names"""
        variants = list_variants("objectives")
        
        assert isinstance(variants, list)
        assert len(variants) > 0
        assert all(isinstance(v, str) for v in variants)
        
        # Should be sorted
        assert variants == sorted(variants)
    
    def test_includes_known_variants(self):
        """Test that known variants are included"""
        variants = list_variants("objectives")
        assert "brief" in variants
        assert "detailed" in variants
    
    def test_unknown_family_raises_error(self):
        """Test that unknown family raises ValueError"""
        with pytest.raises(ValueError, match="Unknown prompt family"):
            list_variants("nonexistent_family")


class TestResolvePrompt:
    """Tests for resolve_prompt()"""
    
    def setup_method(self):
        clear_prompt_cache()
    
    def test_resolve_with_explicit_variant(self):
        """Test resolving prompt with explicit variant"""
        meta = resolve_prompt("objectives", "brief")
        
        assert isinstance(meta, PromptMetadata)
        assert meta.family == "objectives"
        assert meta.variant == "brief"
        assert len(meta.content) > 0
    
    def test_resolve_with_default_variant(self):
        """Test resolving prompt with default variant (None)"""
        meta = resolve_prompt("objectives")
        
        assert isinstance(meta, PromptMetadata)
        assert meta.family == "objectives"
        assert meta.default is True  # Should be the default variant
    
    def test_resolve_unknown_family_raises_error(self):
        """Test that unknown family raises ValueError"""
        with pytest.raises(ValueError, match="Unknown prompt family"):
            resolve_prompt("nonexistent_family")
    
    def test_resolve_unknown_variant_raises_error(self):
        """Test that unknown variant raises ValueError"""
        with pytest.raises(ValueError, match="Unknown variant"):
            resolve_prompt("objectives", "nonexistent_variant")
    
    def test_resolve_without_default_raises_error(self, monkeypatch):
        """Test that family without default variant raises error"""
        # Create temp family without default
        temp_dir = Path(tempfile.mkdtemp())
        try:
            family_dir = temp_dir / "prompts" / "no_default"
            family_dir.mkdir(parents=True)
            
            prompt_file = family_dir / "variant1.md"
            prompt_file.write_text("""---
id: no_default.variant1
family: no_default
variant: variant1
default: false
---
Content""")
            
            def mock_get_prompts_dirs():
                return [temp_dir / "prompts"]
            
            monkeypatch.setattr("ohtv.prompts.discovery.get_prompts_dirs", mock_get_prompts_dirs)
            clear_prompt_cache()
            
            with pytest.raises(ValueError, match="No default variant"):
                resolve_prompt("no_default")
        finally:
            shutil.rmtree(temp_dir)
            clear_prompt_cache()


class TestResolveContext:
    """Tests for resolve_context()"""
    
    def setup_method(self):
        clear_prompt_cache()
    
    def test_resolve_by_number(self):
        """Test resolving context level by number"""
        meta = resolve_prompt("objectives", "brief")
        ctx = resolve_context(meta, 1)
        
        assert ctx.number == 1
        assert ctx.name == "minimal"
    
    def test_resolve_by_name(self):
        """Test resolving context level by name"""
        meta = resolve_prompt("objectives", "brief")
        ctx = resolve_context(meta, "minimal")
        
        assert ctx.number == 1
        assert ctx.name == "minimal"
    
    def test_resolve_with_none_uses_default(self):
        """Test that None uses prompt's default context"""
        meta = resolve_prompt("objectives", "brief")
        ctx = resolve_context(meta, None)
        
        # Should use default_context from prompt
        assert ctx.number == meta.default_context
    
    def test_resolve_unknown_number_raises_error(self):
        """Test that unknown context number raises ValueError"""
        meta = resolve_prompt("objectives", "brief")
        
        with pytest.raises(ValueError, match="Unknown context level"):
            resolve_context(meta, 999)
    
    def test_resolve_unknown_name_raises_error(self):
        """Test that unknown context name raises ValueError"""
        meta = resolve_prompt("objectives", "brief")
        
        with pytest.raises(ValueError, match="Unknown context level"):
            resolve_context(meta, "nonexistent_level")
    
    def test_all_context_levels_accessible(self):
        """Test that all context levels can be accessed"""
        meta = resolve_prompt("objectives", "brief")
        
        # Test all defined context levels
        for number in meta.context_levels.keys():
            ctx = resolve_context(meta, number)
            assert ctx.number == number
            assert len(ctx.include) > 0  # Should have filters


class TestIntegration:
    """Integration tests for discovery system"""
    
    def setup_method(self):
        clear_prompt_cache()
    
    def test_full_workflow(self):
        """Test complete workflow of discovering and resolving prompts"""
        # Discover all prompts
        prompts = discover_prompts()
        assert len(prompts) > 0
        
        # List families
        families = list_families()
        assert "objectives" in families
        
        # List variants for a family
        variants = list_variants("objectives")
        assert "brief" in variants
        
        # Resolve default prompt
        meta = resolve_prompt("objectives")
        assert meta.default is True
        
        # Resolve specific variant
        brief_meta = resolve_prompt("objectives", "brief")
        assert brief_meta.variant == "brief"
        
        # Resolve context
        ctx = resolve_context(brief_meta, 1)
        assert ctx.number == 1
    
    def test_prompt_metadata_completeness(self):
        """Test that discovered prompts have complete metadata"""
        meta = resolve_prompt("objectives", "brief")
        
        # Check all important fields are populated
        assert meta.id
        assert meta.family == "objectives"
        assert meta.variant == "brief"
        assert meta.description
        assert meta.content
        assert meta.content_hash
        assert meta.path
        assert meta.path.exists()
        assert len(meta.context_levels) > 0
        assert meta.default_context >= 1
