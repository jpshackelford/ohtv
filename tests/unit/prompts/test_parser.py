import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile
from ohtv.prompts.parser import (
    parse_frontmatter,
    parse_event_filter,
    parse_context_level,
    parse_prompt_file,
)
from ohtv.prompts.metadata import EventFilter, ContextLevel


class TestParseFrontmatter:
    """Tests for parse_frontmatter()"""
    
    def test_no_frontmatter(self):
        """Test content with no frontmatter"""
        content = "Just regular content"
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content
    
    def test_valid_frontmatter(self):
        """Test content with valid YAML frontmatter"""
        content = """---
id: test.prompt
family: test
variant: basic
---
Prompt content here"""
        fm, body = parse_frontmatter(content)
        assert fm["id"] == "test.prompt"
        assert fm["family"] == "test"
        assert fm["variant"] == "basic"
        assert body == "Prompt content here"
    
    def test_empty_frontmatter(self):
        """Test with empty frontmatter section"""
        content = """---
---
Content"""
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == "Content"
    
    def test_invalid_yaml(self):
        """Test with invalid YAML in frontmatter"""
        content = """---
invalid: yaml: structure:::
---
Content"""
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content  # Returns original content on parse error
    
    def test_incomplete_frontmatter_markers(self):
        """Test with only opening frontmatter marker"""
        content = """---
key: value
More content without closing marker"""
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content


class TestParseEventFilter:
    """Tests for parse_event_filter()"""
    
    def test_empty_dict(self):
        """Test parsing empty dict returns wildcard filter"""
        f = parse_event_filter({})
        assert f.source == "*"
        assert f.kind == "*"
        assert f.tool is None
    
    def test_with_source(self):
        """Test parsing filter with source"""
        f = parse_event_filter({"source": "user"})
        assert f.source == "user"
        assert f.kind == "*"
    
    def test_with_kind(self):
        """Test parsing filter with kind"""
        f = parse_event_filter({"kind": "MessageEvent"})
        assert f.source == "*"
        assert f.kind == "MessageEvent"
    
    def test_with_tool(self):
        """Test parsing filter with tool"""
        f = parse_event_filter({"tool": "terminal"})
        assert f.source == "*"
        assert f.kind == "*"
        assert f.tool == "terminal"
    
    def test_all_fields(self):
        """Test parsing filter with all fields"""
        f = parse_event_filter({
            "source": "agent",
            "kind": "ActionEvent",
            "tool": "finish"
        })
        assert f.source == "agent"
        assert f.kind == "ActionEvent"
        assert f.tool == "finish"


class TestParseContextLevel:
    """Tests for parse_context_level()"""
    
    def test_minimal_context_level(self):
        """Test parsing minimal context level"""
        ctx = parse_context_level({
            "number": 1,
            "name": "minimal",
            "include": [{"kind": "MessageEvent"}]
        })
        assert ctx.number == 1
        assert ctx.name == "minimal"
        assert len(ctx.include) == 1
        assert ctx.include[0].kind == "MessageEvent"
        assert len(ctx.exclude) == 0
        assert ctx.truncate == 0
    
    def test_with_exclude(self):
        """Test parsing context level with exclude"""
        ctx = parse_context_level({
            "number": 2,
            "name": "full",
            "include": [{}],
            "exclude": [{"kind": "ActionEvent", "tool": "terminal"}]
        })
        assert ctx.number == 2
        assert len(ctx.exclude) == 1
        assert ctx.exclude[0].tool == "terminal"
    
    def test_with_truncate(self):
        """Test parsing context level with truncate"""
        ctx = parse_context_level({
            "number": 1,
            "name": "truncated",
            "include": [{}],
            "truncate": 1000
        })
        assert ctx.truncate == 1000
    
    def test_multiple_include_filters(self):
        """Test parsing context level with multiple include filters"""
        ctx = parse_context_level({
            "number": 3,
            "name": "multi",
            "include": [
                {"kind": "MessageEvent"},
                {"kind": "ErrorEvent"},
                {"kind": "ActionEvent", "tool": "finish"}
            ]
        })
        assert len(ctx.include) == 3
        assert ctx.include[0].kind == "MessageEvent"
        assert ctx.include[1].kind == "ErrorEvent"
        assert ctx.include[2].tool == "finish"


class TestParsePromptFile:
    """Tests for parse_prompt_file()"""
    
    def test_plain_prompt_file(self):
        """Test parsing file with no frontmatter"""
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Just a prompt template")
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.content == "Just a prompt template"
            assert meta.variant == path.stem
            assert len(meta.context_levels) == 0
        finally:
            path.unlink()
    
    def test_with_frontmatter(self):
        """Test parsing file with YAML frontmatter"""
        content = """---
id: custom.test
family: custom
variant: test
description: Test prompt
default: true
default_context: 2
tags:
  - test
  - example
---
Prompt template content"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.id == "custom.test"
            assert meta.family == "custom"
            assert meta.variant == "test"
            assert meta.description == "Test prompt"
            assert meta.default is True
            assert meta.default_context == 2
            assert "test" in meta.tags
            assert "example" in meta.tags
            assert meta.content == "Prompt template content"
            assert len(meta.content_hash) == 16
        finally:
            path.unlink()
    
    def test_with_context_levels(self):
        """Test parsing file with context level definitions"""
        content = """---
id: test.contextual
context_levels:
  - number: 1
    name: brief
    include:
      - kind: MessageEvent
  - number: 2
    name: detailed
    include:
      - kind: "*"
    exclude:
      - tool: terminal
---
Template"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert len(meta.context_levels) == 2
            assert 1 in meta.context_levels
            assert 2 in meta.context_levels
            assert meta.context_levels[1].name == "brief"
            assert meta.context_levels[2].name == "detailed"
            assert len(meta.context_levels[2].exclude) == 1
        finally:
            path.unlink()
    
    def test_infers_family_from_path(self):
        """Test that family is inferred from parent directory"""
        import tempfile
        import shutil
        
        # Create temp directory structure
        tmpdir = Path(tempfile.mkdtemp())
        prompts_dir = tmpdir / "prompts" / "objs"
        prompts_dir.mkdir(parents=True)
        
        prompt_file = prompts_dir / "brief.md"
        prompt_file.write_text("Test prompt")
        
        try:
            meta = parse_prompt_file(prompt_file)
            assert meta.family == "objs"
            assert meta.variant == "brief"
            assert meta.id == "objs.brief"
        finally:
            shutil.rmtree(tmpdir)
