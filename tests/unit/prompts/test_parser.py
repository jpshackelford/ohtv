import pytest
from pathlib import Path
from ohtv.prompts.parser import (
    parse_frontmatter,
    parse_event_filter,
    parse_context_level,
    parse_prompt_file
)
from ohtv.prompts.metadata import EventFilter, ContextLevel


class TestParseFrontmatter:
    """Tests for parse_frontmatter()"""
    
    def test_valid_frontmatter(self):
        """Test parsing valid YAML frontmatter"""
        content = """---
id: test.prompt
family: test
variant: prompt
---
This is the prompt content.
"""
        frontmatter, prompt = parse_frontmatter(content)
        assert frontmatter == {
            "id": "test.prompt",
            "family": "test",
            "variant": "prompt"
        }
        assert prompt == "This is the prompt content.\n"
    
    def test_no_frontmatter(self):
        """Test content without frontmatter"""
        content = "This is just prompt content."
        frontmatter, prompt = parse_frontmatter(content)
        assert frontmatter == {}
        assert prompt == content
    
    def test_empty_frontmatter(self):
        """Test empty frontmatter section"""
        content = """---
---
Prompt content here.
"""
        frontmatter, prompt = parse_frontmatter(content)
        assert frontmatter == {}
        assert prompt == "Prompt content here.\n"
    
    def test_incomplete_frontmatter(self):
        """Test content with only opening delimiter"""
        content = """---
This is not valid frontmatter.
"""
        frontmatter, prompt = parse_frontmatter(content)
        assert frontmatter == {}
        assert prompt == content
    
    def test_invalid_yaml(self):
        """Test that invalid YAML returns empty frontmatter"""
        content = """---
this: is: invalid: yaml:
---
Prompt content.
"""
        frontmatter, prompt = parse_frontmatter(content)
        assert frontmatter == {}
        assert prompt == content
    
    def test_frontmatter_with_lists_and_dicts(self):
        """Test parsing complex frontmatter structures"""
        content = """---
tags:
  - analysis
  - objectives
context_levels:
  - number: 1
    name: minimal
---
Content here.
"""
        frontmatter, prompt = parse_frontmatter(content)
        assert "tags" in frontmatter
        assert frontmatter["tags"] == ["analysis", "objectives"]
        assert "context_levels" in frontmatter
        assert prompt == "Content here.\n"


class TestParseEventFilter:
    """Tests for parse_event_filter()"""
    
    def test_empty_dict(self):
        """Test parsing empty dict returns defaults"""
        f = parse_event_filter({})
        assert f.source == "*"
        assert f.kind == "*"
        assert f.tool is None
    
    def test_with_source(self):
        """Test parsing filter with source"""
        f = parse_event_filter({"source": "user"})
        assert f.source == "user"
        assert f.kind == "*"
        assert f.tool is None
    
    def test_with_kind(self):
        """Test parsing filter with kind"""
        f = parse_event_filter({"kind": "MessageEvent"})
        assert f.source == "*"
        assert f.kind == "MessageEvent"
        assert f.tool is None
    
    def test_with_tool(self):
        """Test parsing filter with tool"""
        f = parse_event_filter({"tool": "finish"})
        assert f.source == "*"
        assert f.kind == "*"
        assert f.tool == "finish"
    
    def test_all_fields(self):
        """Test parsing filter with all fields"""
        f = parse_event_filter({
            "source": "agent",
            "kind": "ActionEvent",
            "tool": "terminal"
        })
        assert f.source == "agent"
        assert f.kind == "ActionEvent"
        assert f.tool == "terminal"


class TestParseContextLevel:
    """Tests for parse_context_level()"""
    
    def test_minimal_context_level(self):
        """Test parsing minimal context level"""
        ctx = parse_context_level(1, {
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
        ctx = parse_context_level(2, {
            "name": "full",
            "include": [{}],
            "exclude": [{"kind": "ActionEvent", "tool": "terminal"}]
        })
        assert ctx.number == 2
        assert len(ctx.exclude) == 1
        assert ctx.exclude[0].tool == "terminal"
    
    def test_with_truncate(self):
        """Test parsing context level with truncate"""
        ctx = parse_context_level(1, {
            "name": "truncated",
            "include": [{}],
            "truncate": 1000
        })
        assert ctx.truncate == 1000
    
    def test_multiple_include_filters(self):
        """Test parsing context level with multiple include filters"""
        ctx = parse_context_level(3, {
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
    
    def test_file_without_frontmatter(self, tmp_path):
        """Test parsing file without frontmatter (backward compat)"""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "brief.md"
        prompt_file.write_text("This is a simple prompt.")
        
        meta = parse_prompt_file(prompt_file)
        assert meta.id == "default.brief"
        assert meta.family == "default"
        assert meta.variant == "brief"
        assert meta.content == "This is a simple prompt."
        assert meta.path == prompt_file
        assert len(meta.content_hash) == 16
    
    def test_file_in_subdirectory(self, tmp_path):
        """Test path inference for files in subdirectories"""
        prompt_dir = tmp_path / "objectives"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "detailed.md"
        prompt_file.write_text("Objective extraction prompt.")
        
        meta = parse_prompt_file(prompt_file)
        assert meta.family == "objectives"
        assert meta.variant == "detailed"
        assert meta.id == "objectives.detailed"
    
    def test_file_with_frontmatter(self, tmp_path):
        """Test parsing file with complete frontmatter"""
        prompt_file = tmp_path / "test.md"
        content = """---
id: custom.id
family: custom
variant: test
description: A test prompt
default: true
default_context: 2
tags:
  - test
  - analysis
context_levels:
  - number: 1
    name: minimal
    include:
      - kind: MessageEvent
  - number: 2
    name: full
    include:
      - source: "*"
    truncate: 500
---
This is the prompt content.
Multiple lines here.
"""
        prompt_file.write_text(content)
        
        meta = parse_prompt_file(prompt_file)
        assert meta.id == "custom.id"
        assert meta.family == "custom"
        assert meta.variant == "test"
        assert meta.description == "A test prompt"
        assert meta.default is True
        assert meta.default_context == 2
        assert meta.tags == ["test", "analysis"]
        assert len(meta.context_levels) == 2
        assert 1 in meta.context_levels
        assert 2 in meta.context_levels
        assert meta.context_levels[1].name == "minimal"
        assert meta.context_levels[2].truncate == 500
        assert meta.content == "This is the prompt content.\nMultiple lines here.\n"
    
    def test_content_hash_uniqueness(self, tmp_path):
        """Test that different content produces different hashes"""
        file1 = tmp_path / "prompt1.md"
        file2 = tmp_path / "prompt2.md"
        file1.write_text("Content A")
        file2.write_text("Content B")
        
        meta1 = parse_prompt_file(file1)
        meta2 = parse_prompt_file(file2)
        assert meta1.content_hash != meta2.content_hash
    
    def test_content_hash_same_for_same_content(self, tmp_path):
        """Test that same content produces same hash"""
        file1 = tmp_path / "prompt1.md"
        file2 = tmp_path / "prompt2.md"
        file1.write_text("Same content")
        file2.write_text("Same content")
        
        meta1 = parse_prompt_file(file1)
        meta2 = parse_prompt_file(file2)
        assert meta1.content_hash == meta2.content_hash
    
    def test_content_hash_excludes_frontmatter(self, tmp_path):
        """Test that content hash only includes prompt content, not frontmatter"""
        file1 = tmp_path / "with_fm.md"
        file2 = tmp_path / "without_fm.md"
        
        file1.write_text("""---
id: test.one
---
Prompt content here.""")
        file2.write_text("Prompt content here.")
        
        meta1 = parse_prompt_file(file1)
        meta2 = parse_prompt_file(file2)
        assert meta1.content_hash == meta2.content_hash
    
    def test_optional_fields(self, tmp_path):
        """Test that optional fields have correct defaults"""
        prompt_file = tmp_path / "minimal.md"
        prompt_file.write_text("Minimal prompt")
        
        meta = parse_prompt_file(prompt_file)
        assert meta.description == ""
        assert meta.default is False
        assert meta.context_levels == {}
        assert meta.default_context == 1
        assert meta.output_schema is None
        assert meta.handler is None
        assert meta.tags == []
    
    def test_with_output_schema_and_handler(self, tmp_path):
        """Test parsing prompt with output_schema and handler"""
        prompt_file = tmp_path / "schema.md"
        content = """---
id: test.schema
output_schema:
  type: object
  properties:
    result: string
handler: ohtv.analysis.test:TestHandler
---
Prompt with schema.
"""
        prompt_file.write_text(content)
        
        meta = parse_prompt_file(prompt_file)
        assert meta.output_schema is not None
        assert meta.output_schema["type"] == "object"
        assert meta.handler == "ohtv.analysis.test:TestHandler"
