"""Tests for date filter parsing functions."""

from datetime import datetime, timezone

import pytest

from ohtv.filters import parse_date_filter


class TestParseDateFilter:
    """Tests for parse_date_filter function."""
    
    def test_absolute_date(self):
        """Parse YYYY-MM-DD format."""
        result = parse_date_filter("2026-04-15")
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 15
        assert result.tzinfo == timezone.utc
    
    def test_relative_days(self):
        """Parse Nd format (N days ago)."""
        result = parse_date_filter("7d")
        assert result is not None
        # Should be 7 days ago from now
        now = datetime.now(timezone.utc)
        expected_date = (now.replace(hour=0, minute=0, second=0, microsecond=0)).date()
        from datetime import timedelta
        assert (expected_date - result.date()).days == 7
    
    def test_relative_weeks(self):
        """Parse Nw format (N weeks ago)."""
        result = parse_date_filter("2w")
        assert result is not None
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        expected = now - timedelta(weeks=2)
        assert result.date() == expected.replace(hour=0, minute=0, second=0, microsecond=0).date()
    
    def test_relative_months(self):
        """Parse Nm format (N months ago, ~30 days)."""
        result = parse_date_filter("1m")
        assert result is not None
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        expected = now - timedelta(days=30)
        assert result.date() == expected.replace(hour=0, minute=0, second=0, microsecond=0).date()
    
    def test_today_keyword(self):
        """Parse 'today' keyword."""
        result = parse_date_filter("today")
        assert result is not None
        today = datetime.now(timezone.utc).date()
        assert result.date() == today
    
    def test_yesterday_keyword(self):
        """Parse 'yesterday' keyword."""
        result = parse_date_filter("yesterday")
        assert result is not None
        from datetime import timedelta
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        assert result.date() == yesterday
    
    def test_case_insensitive(self):
        """Keywords and relative dates are case-insensitive."""
        assert parse_date_filter("TODAY") is not None
        assert parse_date_filter("Yesterday") is not None
        assert parse_date_filter("7D") is not None
        assert parse_date_filter("2W") is not None
    
    def test_strips_whitespace(self):
        """Whitespace is trimmed."""
        result = parse_date_filter("  7d  ")
        assert result is not None
    
    def test_invalid_returns_none(self):
        """Invalid formats return None."""
        assert parse_date_filter("invalid") is None
        assert parse_date_filter("2026-13-01") is None  # Invalid month
        assert parse_date_filter("2026-04-32") is None  # Invalid day
        assert parse_date_filter("7days") is None  # Wrong format
        assert parse_date_filter("") is None  # Empty after strip
    
    def test_midnight_utc(self):
        """All parsed dates are at midnight UTC."""
        result = parse_date_filter("2026-04-15")
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.tzinfo == timezone.utc
