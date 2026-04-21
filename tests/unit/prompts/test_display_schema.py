"""Tests for display schema parsing and rendering."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from ohtv.prompts.metadata import DisplaySchema, ColumnDef, FieldRef
from ohtv.prompts.parser import (
    parse_field_ref,
    parse_column_def,
    parse_display_schema,
    parse_prompt_file,
)
from ohtv.prompts.formatters import (
    format_date,
    format_status_badge,
    format_bullet_list,
    format_truncate,
    format_value,
    get_formatter,
    parse_format_spec,
)


class TestFieldRef:
    """Tests for FieldRef dataclass."""
    
    def test_basic_field_ref(self):
        """Test basic field reference creation."""
        ref = FieldRef(field_name="goal")
        assert ref.field_name == "goal"
        assert ref.format is None
        assert ref.prefix is None
    
    def test_field_ref_with_format(self):
        """Test field reference with format."""
        ref = FieldRef(field_name="created_at", format="date")
        assert ref.field_name == "created_at"
        assert ref.format == "date"
    
    def test_field_ref_with_prefix(self):
        """Test field reference with prefix."""
        ref = FieldRef(field_name="outcomes", format="bullet_list", prefix="Primary:")
        assert ref.field_name == "outcomes"
        assert ref.prefix == "Primary:"


class TestColumnDef:
    """Tests for ColumnDef dataclass."""
    
    def test_single_field_column(self):
        """Test column with single field."""
        col = ColumnDef(name="ID", field="short_id", width=7)
        refs = col.get_field_refs()
        assert len(refs) == 1
        assert refs[0].field_name == "short_id"
    
    def test_multi_field_column(self):
        """Test column with multiple fields."""
        col = ColumnDef(
            name="Summary",
            fields=[
                FieldRef(field_name="goal"),
                FieldRef(field_name="outcomes", format="bullet_list"),
            ],
            combine="newline"
        )
        refs = col.get_field_refs()
        assert len(refs) == 2
        assert refs[0].field_name == "goal"
        assert refs[1].field_name == "outcomes"
    
    def test_fields_with_strings(self):
        """Test column where fields contains string shortcuts."""
        col = ColumnDef(
            name="Summary",
            fields=["goal", "status"]
        )
        refs = col.get_field_refs()
        assert len(refs) == 2
        assert refs[0].field_name == "goal"
        assert refs[1].field_name == "status"
    
    def test_show_when_filtering(self):
        """Test show_when attribute."""
        col = ColumnDef(name="Status", field="status", show_when="standard_assess")
        assert col.show_when == "standard_assess"


class TestDisplaySchema:
    """Tests for DisplaySchema dataclass."""
    
    def test_empty_schema(self):
        """Test empty display schema."""
        schema = DisplaySchema()
        assert len(schema.columns) == 0
    
    def test_get_column(self):
        """Test get_column method."""
        schema = DisplaySchema(columns=[
            ColumnDef(name="ID", field="short_id"),
            ColumnDef(name="Date", field="created_at"),
        ])
        col = schema.get_column("ID")
        assert col is not None
        assert col.field == "short_id"
    
    def test_get_column_not_found(self):
        """Test get_column returns None for unknown column."""
        schema = DisplaySchema(columns=[
            ColumnDef(name="ID", field="short_id"),
        ])
        assert schema.get_column("Unknown") is None


class TestParseFieldRef:
    """Tests for parse_field_ref function."""
    
    def test_string_input(self):
        """Test parsing string as field name."""
        ref = parse_field_ref("goal")
        assert ref.field_name == "goal"
        assert ref.format is None
    
    def test_dict_input(self):
        """Test parsing dict with all fields."""
        ref = parse_field_ref({
            "field": "outcomes",
            "format": "bullet_list",
            "prefix": "Results:"
        })
        assert ref.field_name == "outcomes"
        assert ref.format == "bullet_list"
        assert ref.prefix == "Results:"
    
    def test_dict_minimal(self):
        """Test parsing dict with only field."""
        ref = parse_field_ref({"field": "status"})
        assert ref.field_name == "status"
        assert ref.format is None


class TestParseColumnDef:
    """Tests for parse_column_def function."""
    
    def test_single_field(self):
        """Test parsing column with single field."""
        col = parse_column_def({
            "name": "ID",
            "field": "short_id",
            "width": 7
        })
        assert col.name == "ID"
        assert col.field == "short_id"
        assert col.width == 7
    
    def test_multiple_fields(self):
        """Test parsing column with multiple fields."""
        col = parse_column_def({
            "name": "Summary",
            "fields": [
                "goal",
                {"field": "outcomes", "format": "bullet_list"}
            ],
            "combine": "newline"
        })
        assert col.name == "Summary"
        assert len(col.fields) == 2
        assert col.combine == "newline"
    
    def test_with_format(self):
        """Test parsing column with format."""
        col = parse_column_def({
            "name": "Date",
            "field": "created_at",
            "format": "date"
        })
        assert col.format == "date"


class TestParseDisplaySchema:
    """Tests for parse_display_schema function."""
    
    def test_full_schema(self):
        """Test parsing complete display schema."""
        schema = parse_display_schema({
            "table": {
                "columns": [
                    {"name": "ID", "field": "short_id", "width": 7},
                    {"name": "Date", "field": "created_at", "format": "date"},
                    {"name": "Summary", "field": "goal"}
                ]
            }
        })
        assert len(schema.columns) == 3
        assert schema.columns[0].name == "ID"
        assert schema.columns[1].format == "date"
    
    def test_empty_schema(self):
        """Test parsing empty display section."""
        schema = parse_display_schema({})
        assert len(schema.columns) == 0
    
    def test_no_columns(self):
        """Test parsing display with no columns."""
        schema = parse_display_schema({"table": {}})
        assert len(schema.columns) == 0


class TestPromptFileWithDisplay:
    """Tests for parsing prompt files with display sections."""
    
    def test_prompt_with_display_section(self):
        """Test parsing prompt file with display section."""
        content = """---
id: test.variant
description: Test prompt

display:
  table:
    columns:
      - name: ID
        field: short_id
        width: 7
      - name: Status
        field: status
        format: status_badge
---
Prompt content"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.display is not None
            assert len(meta.display.columns) == 2
            assert meta.display.columns[0].name == "ID"
            assert meta.display.columns[1].format == "status_badge"
        finally:
            path.unlink()
    
    def test_prompt_without_display_section(self):
        """Test parsing prompt file without display section."""
        content = """---
id: test.basic
---
Simple prompt"""
        
        with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        
        try:
            meta = parse_prompt_file(path)
            assert meta.display is None
        finally:
            path.unlink()


class TestFormatters:
    """Tests for field formatters."""
    
    def test_format_date_datetime(self):
        """Test formatting datetime object."""
        dt = datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = format_date(dt)
        assert "2024-03-15" in result
    
    def test_format_date_string(self):
        """Test formatting ISO string."""
        result = format_date("2024-03-15T10:30:00Z")
        assert "2024-03-15" in result
    
    def test_format_date_none(self):
        """Test formatting None."""
        result = format_date(None)
        assert result == ""
    
    def test_format_status_badge_achieved(self):
        """Test formatting achieved status."""
        result = format_status_badge("achieved")
        assert "✅" in result
    
    def test_format_status_badge_not_achieved(self):
        """Test formatting not_achieved status."""
        result = format_status_badge("not_achieved")
        assert "❌" in result
    
    def test_format_status_badge_in_progress(self):
        """Test formatting in_progress status."""
        result = format_status_badge("in_progress")
        assert "🔄" in result
    
    def test_format_bullet_list(self):
        """Test formatting list as bullets."""
        result = format_bullet_list(["item1", "item2", "item3"])
        assert "• item1" in result
        assert "• item2" in result
        assert "• item3" in result
    
    def test_format_bullet_list_empty(self):
        """Test formatting empty list."""
        result = format_bullet_list([])
        assert result == ""
    
    def test_format_truncate(self):
        """Test truncating long text."""
        result = format_truncate("This is a very long text that needs to be truncated", "20")
        assert len(result) == 20
        assert result.endswith("…")
    
    def test_format_truncate_short_text(self):
        """Test truncate with short text."""
        result = format_truncate("Short", "50")
        assert result == "Short"


class TestFormatSpecParsing:
    """Tests for format specification parsing."""
    
    def test_simple_spec(self):
        """Test parsing simple format spec."""
        name, args = parse_format_spec("date")
        assert name == "date"
        assert args is None
    
    def test_spec_with_args(self):
        """Test parsing format spec with arguments."""
        name, args = parse_format_spec("truncate(50)")
        assert name == "truncate"
        assert args == "50"
    
    def test_none_spec(self):
        """Test parsing None spec."""
        name, args = parse_format_spec(None)
        assert name == "plain"
        assert args is None


class TestGetFormatter:
    """Tests for get_formatter function."""
    
    def test_get_date_formatter(self):
        """Test getting date formatter."""
        formatter = get_formatter("date")
        dt = datetime(2024, 3, 15, tzinfo=timezone.utc)
        assert "2024-03-15" in formatter(dt)
    
    def test_get_truncate_formatter_with_args(self):
        """Test getting truncate formatter with length arg."""
        formatter = get_formatter("truncate(10)")
        result = formatter("This is a long text")
        assert len(result) == 10
    
    def test_get_unknown_formatter(self):
        """Test getting unknown formatter returns plain."""
        formatter = get_formatter("unknown_format")
        result = formatter("test value")
        assert result == "test value"


class TestFormatValue:
    """Tests for format_value function."""
    
    def test_format_value_date(self):
        """Test format_value with date."""
        dt = datetime(2024, 3, 15, tzinfo=timezone.utc)
        result = format_value(dt, "date")
        assert "2024-03-15" in result
    
    def test_format_value_status_badge(self):
        """Test format_value with status_badge."""
        result = format_value("achieved", "status_badge")
        assert "✅" in result
    
    def test_format_value_none_format(self):
        """Test format_value with None format uses plain."""
        result = format_value(["a", "b"], None)
        assert result == "a, b"


class TestTableRenderer:
    """Tests for TableRenderer class."""
    
    def test_nested_field_access(self):
        """Test nested field access like user.name."""
        from ohtv.prompts.renderer import TableRenderer
        
        schema = DisplaySchema(columns=[
            ColumnDef(name="Author", field="user.name"),
        ])
        renderer = TableRenderer(schema)
        
        data = {"user": {"name": "Alice", "email": "alice@example.com"}}
        value = renderer._get_field_value(data, "user.name")
        assert value == "Alice"
    
    def test_nested_field_access_deep(self):
        """Test deeply nested field access."""
        from ohtv.prompts.renderer import TableRenderer
        
        schema = DisplaySchema(columns=[])
        renderer = TableRenderer(schema)
        
        data = {"level1": {"level2": {"level3": "deep_value"}}}
        value = renderer._get_field_value(data, "level1.level2.level3")
        assert value == "deep_value"
    
    def test_nested_field_access_missing(self):
        """Test nested field access with missing intermediate key."""
        from ohtv.prompts.renderer import TableRenderer
        
        schema = DisplaySchema(columns=[])
        renderer = TableRenderer(schema)
        
        data = {"user": {"name": "Bob"}}
        value = renderer._get_field_value(data, "user.email.domain")
        assert value is None
    
    def test_nested_field_access_non_dict(self):
        """Test nested field access when intermediate value is not a dict."""
        from ohtv.prompts.renderer import TableRenderer
        
        schema = DisplaySchema(columns=[])
        renderer = TableRenderer(schema)
        
        data = {"user": "string_value"}
        value = renderer._get_field_value(data, "user.name")
        assert value is None


class TestTruncateFormatterEdgeCases:
    """Additional tests for truncate formatter edge cases."""
    
    def test_truncate_with_invalid_args(self):
        """Test truncate gracefully handles non-numeric args."""
        result = format_truncate("This is a test string", "invalid")
        # Should fall back to default of 50
        assert result == "This is a test string"  # String is shorter than 50
    
    def test_truncate_with_empty_args(self):
        """Test truncate with empty string args."""
        result = format_truncate("A" * 100, "")
        # Should fall back to default of 50
        assert len(result) == 50
        assert result.endswith("…")
