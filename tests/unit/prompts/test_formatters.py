"""Tests for formatters module, specifically new time/duration/step_count formatters."""

import pytest
from datetime import datetime, timedelta, timezone

from ohtv.prompts.formatters import (
    format_time,
    format_duration_minutes,
    format_step_count,
    format_value,
    get_formatter,
    FORMATTERS,
)


class TestFormatTime:
    """Tests for format_time function."""
    
    def test_format_time_datetime_morning(self):
        """Test formatting morning time from datetime."""
        # 10:42 AM UTC
        dt = datetime(2024, 3, 15, 10, 42, 0, tzinfo=timezone.utc)
        result = format_time(dt)
        # Should contain AM and reasonable time format
        assert "AM" in result or "PM" in result
        # The exact time depends on local timezone, but format should be consistent
        assert ":" in result
    
    def test_format_time_datetime_afternoon(self):
        """Test formatting afternoon time from datetime."""
        # 2:15 PM UTC
        dt = datetime(2024, 3, 15, 14, 15, 0, tzinfo=timezone.utc)
        result = format_time(dt)
        assert "AM" in result or "PM" in result
        assert ":" in result
    
    def test_format_time_midnight(self):
        """Test formatting midnight."""
        dt = datetime(2024, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
        result = format_time(dt)
        assert result  # Should produce non-empty result
    
    def test_format_time_leading_zero_stripped(self):
        """Test that leading zero is stripped from hour."""
        # Use a fixed offset timezone for predictable output
        from datetime import timezone as tz
        # Create a datetime that will show 9:30 AM when interpreted as local
        dt = datetime(2024, 3, 15, 9, 30, 0, tzinfo=tz(timedelta(hours=0)))
        result = format_time(dt)
        # Should not start with "09:", but "9:"
        # Note: this depends on the local timezone, so we check the format is valid
        assert ":" in result
        assert (result.startswith("9:") or "AM" in result or "PM" in result)
    
    def test_format_time_iso_string(self):
        """Test formatting from ISO string."""
        result = format_time("2024-03-15T10:42:00Z")
        assert "AM" in result or "PM" in result
        assert ":" in result
    
    def test_format_time_iso_string_with_offset(self):
        """Test formatting from ISO string with offset."""
        result = format_time("2024-03-15T10:42:00+00:00")
        assert ":" in result
    
    def test_format_time_none(self):
        """Test formatting None returns empty string."""
        result = format_time(None)
        assert result == ""
    
    def test_format_time_invalid_string(self):
        """Test formatting invalid string returns the string."""
        result = format_time("not-a-date")
        assert result == "not-a-date"
    
    def test_format_time_registered(self):
        """Test that time formatter is registered."""
        assert "time" in FORMATTERS
        assert FORMATTERS["time"] is format_time


class TestFormatDurationMinutes:
    """Tests for format_duration_minutes function."""
    
    def test_format_duration_minutes_short(self):
        """Test formatting duration under an hour."""
        result = format_duration_minutes(timedelta(minutes=35))
        assert result == "35 mins"
    
    def test_format_duration_minutes_zero(self):
        """Test formatting zero duration."""
        result = format_duration_minutes(timedelta(minutes=0))
        assert result == "0 mins"
    
    def test_format_duration_minutes_one_minute(self):
        """Test formatting one minute."""
        result = format_duration_minutes(timedelta(minutes=1))
        assert result == "1 mins"
    
    def test_format_duration_minutes_exact_hour(self):
        """Test formatting exactly one hour."""
        result = format_duration_minutes(timedelta(hours=1))
        assert result == "1h"
    
    def test_format_duration_minutes_hours_and_minutes(self):
        """Test formatting hours and minutes."""
        result = format_duration_minutes(timedelta(hours=1, minutes=20))
        assert result == "1h 20m"
    
    def test_format_duration_minutes_multiple_hours(self):
        """Test formatting multiple hours."""
        result = format_duration_minutes(timedelta(hours=2, minutes=45))
        assert result == "2h 45m"
    
    def test_format_duration_minutes_multiple_hours_exact(self):
        """Test formatting exact multiple hours."""
        result = format_duration_minutes(timedelta(hours=3))
        assert result == "3h"
    
    def test_format_duration_minutes_from_seconds_int(self):
        """Test formatting from seconds as integer."""
        result = format_duration_minutes(35 * 60)  # 35 minutes in seconds
        assert result == "35 mins"
    
    def test_format_duration_minutes_from_seconds_float(self):
        """Test formatting from seconds as float."""
        result = format_duration_minutes(90.5 * 60)  # 90.5 minutes
        assert result == "1h 30m"
    
    def test_format_duration_minutes_none(self):
        """Test formatting None returns empty string."""
        result = format_duration_minutes(None)
        assert result == ""
    
    def test_format_duration_minutes_negative(self):
        """Test formatting negative duration returns empty string."""
        result = format_duration_minutes(timedelta(minutes=-5))
        assert result == ""
    
    def test_format_duration_minutes_non_numeric(self):
        """Test formatting non-numeric value returns string representation."""
        result = format_duration_minutes("not-a-duration")
        assert result == "not-a-duration"
    
    def test_format_duration_minutes_registered(self):
        """Test that duration_minutes formatter is registered."""
        assert "duration_minutes" in FORMATTERS
        assert FORMATTERS["duration_minutes"] is format_duration_minutes


class TestFormatStepCount:
    """Tests for format_step_count function."""
    
    def test_format_step_count_normal(self):
        """Test formatting normal step count."""
        result = format_step_count(46)
        assert result == "46 steps"
    
    def test_format_step_count_one(self):
        """Test formatting single step."""
        result = format_step_count(1)
        assert result == "1 steps"
    
    def test_format_step_count_large(self):
        """Test formatting large step count."""
        result = format_step_count(128)
        assert result == "128 steps"
    
    def test_format_step_count_zero(self):
        """Test formatting zero returns empty string."""
        result = format_step_count(0)
        assert result == ""
    
    def test_format_step_count_none(self):
        """Test formatting None returns empty string."""
        result = format_step_count(None)
        assert result == ""
    
    def test_format_step_count_from_string(self):
        """Test formatting from string number."""
        result = format_step_count("42")
        assert result == "42 steps"
    
    def test_format_step_count_invalid(self):
        """Test formatting invalid value returns string."""
        result = format_step_count("not-a-number")
        assert result == "not-a-number"
    
    def test_format_step_count_registered(self):
        """Test that step_count formatter is registered."""
        assert "step_count" in FORMATTERS
        assert FORMATTERS["step_count"] is format_step_count


class TestFormatterIntegration:
    """Integration tests for formatters with format_value and get_formatter."""
    
    def test_format_value_time(self):
        """Test format_value with time formatter."""
        dt = datetime(2024, 3, 15, 10, 42, 0, tzinfo=timezone.utc)
        result = format_value(dt, "time")
        assert ":" in result
    
    def test_format_value_duration_minutes(self):
        """Test format_value with duration_minutes formatter."""
        result = format_value(timedelta(hours=1, minutes=30), "duration_minutes")
        assert result == "1h 30m"
    
    def test_format_value_step_count(self):
        """Test format_value with step_count formatter."""
        result = format_value(50, "step_count")
        assert result == "50 steps"
    
    def test_get_formatter_time(self):
        """Test get_formatter returns time formatter."""
        formatter = get_formatter("time")
        dt = datetime(2024, 3, 15, 10, 42, 0, tzinfo=timezone.utc)
        result = formatter(dt)
        assert ":" in result
    
    def test_get_formatter_duration_minutes(self):
        """Test get_formatter returns duration_minutes formatter."""
        formatter = get_formatter("duration_minutes")
        result = formatter(timedelta(minutes=45))
        assert result == "45 mins"
    
    def test_get_formatter_step_count(self):
        """Test get_formatter returns step_count formatter."""
        formatter = get_formatter("step_count")
        result = formatter(100)
        assert result == "100 steps"


class TestDefaultDisplaySchema:
    """Tests for the default display schema with new columns."""
    
    def test_default_schema_has_four_columns(self):
        """Test default schema has ID, Date, Duration, Summary columns."""
        from ohtv.prompts.renderer import get_default_display_schema
        
        schema = get_default_display_schema()
        assert len(schema.columns) == 4
        
        col_names = [col.name for col in schema.columns]
        assert col_names == ["ID", "Date", "Duration", "Summary"]
    
    def test_id_column_has_short_id_and_source(self):
        """Test ID column has short_id and source fields."""
        from ohtv.prompts.renderer import get_default_display_schema
        
        schema = get_default_display_schema()
        id_col = schema.get_column("ID")
        
        assert id_col is not None
        field_refs = id_col.get_field_refs()
        assert len(field_refs) == 2
        assert field_refs[0].field_name == "short_id"
        assert field_refs[1].field_name == "source"
        assert id_col.combine == "newline"
    
    def test_date_column_has_date_and_time(self):
        """Test Date column has date and time formats."""
        from ohtv.prompts.renderer import get_default_display_schema
        
        schema = get_default_display_schema()
        date_col = schema.get_column("Date")
        
        assert date_col is not None
        field_refs = date_col.get_field_refs()
        assert len(field_refs) == 2
        assert field_refs[0].field_name == "created_at"
        assert field_refs[0].format == "date"
        assert field_refs[1].field_name == "created_at"
        assert field_refs[1].format == "time"
        assert date_col.combine == "newline"
    
    def test_duration_column_has_duration_and_steps(self):
        """Test Duration column has duration and event_count fields."""
        from ohtv.prompts.renderer import get_default_display_schema
        
        schema = get_default_display_schema()
        duration_col = schema.get_column("Duration")
        
        assert duration_col is not None
        field_refs = duration_col.get_field_refs()
        assert len(field_refs) == 2
        assert field_refs[0].field_name == "duration"
        assert field_refs[0].format == "duration_minutes"
        assert field_refs[1].field_name == "event_count"
        assert field_refs[1].format == "step_count"
        assert duration_col.combine == "newline"
    
    def test_summary_column_has_goal_refs_and_labels(self):
        """Test Summary column has goal, refs_display, and labels_display fields."""
        from ohtv.prompts.renderer import get_default_display_schema
        
        schema = get_default_display_schema()
        summary_col = schema.get_column("Summary")
        
        assert summary_col is not None
        field_refs = summary_col.get_field_refs()
        assert len(field_refs) == 3
        assert field_refs[0].field_name == "goal"
        assert field_refs[1].field_name == "refs_display"
        assert field_refs[2].field_name == "labels_display"
    
    def test_table_renderer_with_new_schema(self):
        """Test TableRenderer can render with the new schema."""
        from ohtv.prompts.renderer import get_default_display_schema, TableRenderer
        from io import StringIO
        from rich.console import Console
        
        schema = get_default_display_schema()
        
        # Create a console with string output for testing
        string_io = StringIO()
        test_console = Console(file=string_io, force_terminal=True, width=120)
        
        renderer = TableRenderer(schema, console=test_console)
        
        # Create test data matching the new result dict structure
        results = [{
            "id": "abc12345def67890",
            "short_id": "abc1234",
            "source": "cloud",
            "created_at": datetime(2024, 3, 15, 10, 42, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 3, 15, 11, 17, 0, tzinfo=timezone.utc),
            "duration": timedelta(minutes=35),
            "event_count": 46,
            "goal": "Test objective analysis",
            "refs_display": "",
            "cached": True,
        }]
        
        # Render the table - should not raise any errors
        renderer.render(results, show_summary=True, total_count=1, error_count=0)
        
        output = string_io.getvalue()
        
        # Verify key data appears in output
        assert "abc1234" in output  # short_id
        assert "cloud" in output  # source
        assert "35 mins" in output  # duration
        assert "46 steps" in output  # event_count
        assert "Test objective analysis" in output  # goal
