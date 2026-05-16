"""Tests for numeric lookback parsing in -D and -W options."""

from datetime import datetime
from unittest.mock import patch

import pytest

from ohtv.cli import (
    _get_day_lookback_bounds,
    _get_week_bounds,
    _get_week_lookback_bounds,
    _parse_date_filters,
    _parse_numeric_lookback,
)


class TestParseNumericLookback:
    """Tests for _parse_numeric_lookback function."""
    
    def test_positive_integer(self):
        """Positive integers return the integer."""
        assert _parse_numeric_lookback("1") == 1
        assert _parse_numeric_lookback("3") == 3
        assert _parse_numeric_lookback("7") == 7
        assert _parse_numeric_lookback("100") == 100
    
    def test_zero_returns_none(self):
        """Zero is not a valid lookback period."""
        assert _parse_numeric_lookback("0") is None
    
    def test_negative_returns_none(self):
        """Negative numbers are not valid."""
        assert _parse_numeric_lookback("-1") is None
        assert _parse_numeric_lookback("-5") is None
    
    def test_none_returns_none(self):
        """None input returns None."""
        assert _parse_numeric_lookback(None) is None
    
    def test_non_numeric_returns_none(self):
        """Non-numeric strings return None."""
        assert _parse_numeric_lookback("today") is None
        assert _parse_numeric_lookback("2026-05-15") is None
        assert _parse_numeric_lookback("abc") is None
        assert _parse_numeric_lookback("3d") is None  # This is for --since, not -D
    
    def test_leading_zeros_parsed(self):
        """Leading zeros are parsed as numbers, not dates."""
        assert _parse_numeric_lookback("07") == 7
        assert _parse_numeric_lookback("03") == 3
    
    def test_float_returns_none(self):
        """Floating point strings are not valid."""
        assert _parse_numeric_lookback("3.5") is None
        assert _parse_numeric_lookback("1.0") is None


class TestGetDayLookbackBounds:
    """Tests for _get_day_lookback_bounds function."""
    
    @patch("ohtv.cli.datetime")
    def test_one_day_is_today(self, mock_dt):
        """N=1 should return today only."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        start, end = _get_day_lookback_bounds(1)
        
        assert start.date() == mock_now.date()
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0
        
        assert end.date() == mock_now.date()
        assert end.hour == 23
        assert end.minute == 59
        assert end.second == 59
    
    @patch("ohtv.cli.datetime")
    def test_three_days(self, mock_dt):
        """N=3 should return today and 2 days back."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        start, end = _get_day_lookback_bounds(3)
        
        # Start should be May 13 at midnight
        expected_start = datetime(2026, 5, 13, 0, 0, 0, 0)
        assert start == expected_start
        
        # End should be May 15 at 23:59:59
        assert end.date() == mock_now.date()
        assert end.hour == 23
    
    @patch("ohtv.cli.datetime")
    def test_seven_days(self, mock_dt):
        """N=7 should return a full week of days."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        start, end = _get_day_lookback_bounds(7)
        
        # Start should be May 9 at midnight (6 days back from May 15)
        expected_start = datetime(2026, 5, 9, 0, 0, 0, 0)
        assert start == expected_start
        
        # Check the range spans exactly 7 days
        days_diff = (end.date() - start.date()).days
        assert days_diff == 6  # 7 days = 6 full days between start and end


class TestGetWeekLookbackBounds:
    """Tests for _get_week_lookback_bounds function."""
    
    @patch("ohtv.cli.datetime")
    def test_one_week_is_current_week(self, mock_dt):
        """N=1 should return only the current week."""
        # Thursday, May 15, 2026
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        start, end = _get_week_lookback_bounds(1)
        
        # Current week starts on Sunday, May 10, 2026
        expected_week_start = datetime(2026, 5, 10, 0, 0, 0, 0)
        assert start == expected_week_start
        
        # End should be today (May 15) at 23:59:59
        assert end.date() == mock_now.date()
        assert end.hour == 23
    
    @patch("ohtv.cli.datetime")
    def test_two_weeks(self, mock_dt):
        """N=2 should return this week and last week."""
        # Thursday, May 15, 2026
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        start, end = _get_week_lookback_bounds(2)
        
        # Should start at Sunday, May 3, 2026 (one week back from current week)
        expected_start = datetime(2026, 5, 3, 0, 0, 0, 0)
        assert start == expected_start
        
        # End should still be today
        assert end.date() == mock_now.date()
    
    @patch("ohtv.cli.datetime")
    def test_four_weeks(self, mock_dt):
        """N=4 should return the last 4 weeks."""
        # Thursday, May 15, 2026
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        start, end = _get_week_lookback_bounds(4)
        
        # Should start at Sunday, April 19, 2026 (3 weeks back from current week start)
        expected_start = datetime(2026, 4, 19, 0, 0, 0, 0)
        assert start == expected_start


class TestParseDateFiltersNumericLookback:
    """Tests for _parse_date_filters with numeric lookback."""
    
    @patch("ohtv.cli.datetime")
    def test_day_numeric_lookback(self, mock_dt):
        """Numeric value for day should use lookback."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        since, until = _parse_date_filters(None, None, "3", None)
        
        # Should span 3 days: May 13-15
        assert since.date() == datetime(2026, 5, 13).date()
        assert until.date() == datetime(2026, 5, 15).date()
    
    @patch("ohtv.cli.datetime")
    def test_week_numeric_lookback(self, mock_dt):
        """Numeric value for week should use lookback."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        since, until = _parse_date_filters(None, None, None, "2")
        
        # Should span 2 weeks: May 3 - May 15
        assert since.date() == datetime(2026, 5, 3).date()
        assert until.date() == datetime(2026, 5, 15).date()
    
    @patch("ohtv.cli.datetime")
    def test_day_one_same_as_today_flag(self, mock_dt):
        """Day=1 should behave like -D (today)."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        since1, until1 = _parse_date_filters(None, None, "1", None)
        since2, until2 = _parse_date_filters(None, None, "today", None)
        
        assert since1.date() == since2.date()
        assert until1.date() == until2.date()
    
    @patch("ohtv.cli.datetime")
    def test_week_one_same_as_week_flag(self, mock_dt):
        """Week=1 should behave like -W (this week)."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        since1, until1 = _parse_date_filters(None, None, None, "1")
        since2, until2 = _parse_date_filters(None, None, None, "today")
        
        # Both should start at the same week start
        assert since1.date() == since2.date()
    
    def test_day_date_still_works(self):
        """Specific date values should still parse correctly."""
        since, until = _parse_date_filters(None, None, "2026-05-15", None)
        
        assert since.date() == datetime(2026, 5, 15).date()
        assert until.date() == datetime(2026, 5, 15).date()
    
    def test_week_date_still_works(self):
        """Week containing specific date should still work."""
        since, until = _parse_date_filters(None, None, None, "2026-05-15")
        
        # May 15, 2026 is Thursday, week starts Sunday May 10
        assert since.date() == datetime(2026, 5, 10).date()
        # Week ends Saturday May 16
        assert until.date() == datetime(2026, 5, 16).date()
    
    @patch("ohtv.cli.datetime")
    def test_zero_ignored(self, mock_dt):
        """Zero should be ignored (not a valid lookback)."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        # Zero is not a valid lookback - will be passed to _parse_date_option
        # which will fail to parse it
        import click
        with pytest.raises(click.BadParameter):
            _parse_date_filters(None, None, "0", None)
    
    @patch("ohtv.cli.datetime")
    def test_negative_ignored(self, mock_dt):
        """Negative numbers should be ignored (not a valid lookback)."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        # Negative is not a valid lookback - will be passed to _parse_date_option
        import click
        with pytest.raises(click.BadParameter):
            _parse_date_filters(None, None, "-5", None)
    
    @patch("ohtv.cli.datetime")
    def test_explicit_since_until_not_overridden(self, mock_dt):
        """Explicit --since/--until should not be overridden by numeric lookback."""
        mock_now = datetime(2026, 5, 15, 14, 30, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        
        # If since_date is provided, day lookback shouldn't override it
        since, until = _parse_date_filters("2026-05-10", None, "3", None)
        
        # Since should be explicitly set date, not lookback
        assert since.date() == datetime(2026, 5, 10).date()
        # Until should be from lookback
        assert until.date() == datetime(2026, 5, 15).date()


class TestGetWeekBoundsHelper:
    """Tests for _get_week_bounds helper (used by week lookback)."""
    
    def test_sunday_is_week_start(self):
        """Sunday should be the start of its own week."""
        sunday = datetime(2026, 5, 10, 12, 0, 0)  # Sunday
        start, end = _get_week_bounds(sunday)
        
        assert start.date() == sunday.date()
        assert start.hour == 0
        assert start.minute == 0
        assert end.date() == datetime(2026, 5, 16).date()  # Saturday
    
    def test_saturday_is_week_end(self):
        """Saturday should be the end of its week."""
        saturday = datetime(2026, 5, 16, 12, 0, 0)  # Saturday
        start, end = _get_week_bounds(saturday)
        
        assert start.date() == datetime(2026, 5, 10).date()  # Sunday
        assert end.date() == saturday.date()
    
    def test_midweek_day(self):
        """Midweek day should be in correct week."""
        thursday = datetime(2026, 5, 14, 12, 0, 0)  # Thursday
        start, end = _get_week_bounds(thursday)
        
        assert start.date() == datetime(2026, 5, 10).date()  # Sunday
        assert end.date() == datetime(2026, 5, 16).date()  # Saturday
