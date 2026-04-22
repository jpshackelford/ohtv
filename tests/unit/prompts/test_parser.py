import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile
from ohtv.prompts.parser import (
    parse_frontmatter,
    parse_event_filter,
    parse_context_level,
    parse_prompt_file,
    parse_input_config,
)
from ohtv.prompts.metadata import EventFilter, ContextLevel, InputConfig


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


class TestParseInputConfig:
    """Tests for parse_input_config()"""
    
    def test_empty_dict_returns_default(self):
        """Test parsing empty dict returns single mode defaults"""
        cfg = parse_input_config({})
        assert cfg.mode == "single"
        assert cfg.source is None
        assert cfg.period is None
        assert cfg.min_items == 1
    
    def test_single_mode_explicit(self):
        """Test parsing explicit single mode"""
        cfg = parse_input_config({"mode": "single"})
        assert cfg.mode == "single"
        assert cfg.source is None
    
    def test_aggregate_mode_with_source(self):
        """Test parsing aggregate mode with source"""
        cfg = parse_input_config({
            "mode": "aggregate",
            "source": "objs.brief"
        })
        assert cfg.mode == "aggregate"
        assert cfg.source == "objs.brief"
        assert cfg.period is None
    
    def test_aggregate_mode_with_period(self):
        """Test parsing aggregate mode with period"""
        cfg = parse_input_config({
            "mode": "aggregate",
            "source": "objs.brief",
            "period": "week"
        })
        assert cfg.mode == "aggregate"
        assert cfg.source == "objs.brief"
        assert cfg.period == "week"
    
    def test_aggregate_mode_missing_source_raises(self):
        """Test that aggregate mode without source raises error"""
        with pytest.raises(ValueError, match="requires 'source'"):
            parse_input_config({"mode": "aggregate"})
    
    def test_invalid_period_raises(self):
        """Test that invalid period value raises error"""
        with pytest.raises(ValueError, match="Invalid period"):
            parse_input_config({
                "mode": "aggregate",
                "source": "objs.brief",
                "period": "quarter"  # Invalid
            })
    
    def test_valid_period_values(self):
        """Test all valid period values"""
        for period in ["week", "day", "month"]:
            cfg = parse_input_config({
                "mode": "aggregate",
                "source": "objs.brief",
                "period": period
            })
            assert cfg.period == period
    
    def test_min_items_custom(self):
        """Test custom min_items value"""
        cfg = parse_input_config({
            "mode": "aggregate",
            "source": "objs.brief",
            "min_items": 5
        })
        assert cfg.min_items == 5


class TestParsePromptFileWithInput:
    """Tests for parse_prompt_file() with input config"""
    
    def test_prompt_without_input_has_default(self):
        """Test prompt without input section has single mode default"""
        content = """---
id: test.simple
---
Template"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.input_config.mode == "single"
            assert meta.is_aggregate is False
            assert meta.has_period is False
        finally:
            path.unlink()
    
    def test_prompt_with_aggregate_input(self):
        """Test prompt with aggregate input section"""
        content = """---
id: reports.weekly
input:
  mode: aggregate
  source: objs.brief
  period: week
  min_items: 2
---
Aggregate prompt template"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.input_config.mode == "aggregate"
            assert meta.input_config.source == "objs.brief"
            assert meta.input_config.period == "week"
            assert meta.input_config.min_items == 2
            assert meta.is_aggregate is True
            assert meta.has_period is True
        finally:
            path.unlink()
    
    def test_prompt_with_aggregate_no_period(self):
        """Test aggregate prompt without period"""
        content = """---
id: themes.all
input:
  mode: aggregate
  source: objs.brief
---
Theme discovery prompt"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.is_aggregate is True
            assert meta.has_period is False
            assert meta.input_config.period is None
        finally:
            path.unlink()
