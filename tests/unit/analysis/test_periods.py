"""Tests for period iteration utilities."""

import pytest
from datetime import date

from ohtv.analysis.periods import (
    PeriodInfo,
    get_week_start,
    get_month_start,
    get_month_end,
    make_week_period,
    make_day_period,
    make_month_period,
    iterate_periods,
    get_last_n_periods,
    compute_period_state_hash,
    get_date_range_for_periods,
)


class TestGetWeekStart:
    """Tests for get_week_start()"""
    
    def test_monday_is_week_start(self):
        """Test that Monday returns itself"""
        monday = date(2024, 1, 8)  # A Monday
        assert get_week_start(monday) == monday
    
    def test_wednesday_returns_monday(self):
        """Test that Wednesday returns the preceding Monday"""
        wednesday = date(2024, 1, 10)
        assert get_week_start(wednesday) == date(2024, 1, 8)
    
    def test_sunday_returns_monday(self):
        """Test that Sunday returns the Monday of that week"""
        sunday = date(2024, 1, 14)
        assert get_week_start(sunday) == date(2024, 1, 8)
    
    def test_week_starts_sunday_option(self):
        """Test week_starts_monday=False"""
        wednesday = date(2024, 1, 10)
        assert get_week_start(wednesday, week_starts_monday=False) == date(2024, 1, 7)


class TestGetMonthStartEnd:
    """Tests for get_month_start() and get_month_end()"""
    
    def test_month_start_mid_month(self):
        """Test getting month start from mid-month date"""
        assert get_month_start(date(2024, 1, 15)) == date(2024, 1, 1)
    
    def test_month_start_first_day(self):
        """Test getting month start from first day"""
        assert get_month_start(date(2024, 1, 1)) == date(2024, 1, 1)
    
    def test_month_end_january(self):
        """Test month end for January (31 days)"""
        assert get_month_end(date(2024, 1, 15)) == date(2024, 1, 31)
    
    def test_month_end_february_leap(self):
        """Test month end for February in leap year"""
        assert get_month_end(date(2024, 2, 1)) == date(2024, 2, 29)
    
    def test_month_end_february_non_leap(self):
        """Test month end for February in non-leap year"""
        assert get_month_end(date(2023, 2, 1)) == date(2023, 2, 28)
    
    def test_month_end_december(self):
        """Test month end for December"""
        assert get_month_end(date(2024, 12, 15)) == date(2024, 12, 31)


class TestMakePeriods:
    """Tests for make_*_period() functions"""
    
    def test_make_day_period(self):
        """Test creating a day period"""
        p = make_day_period(date(2024, 4, 15))
        assert p.type == "day"
        assert p.start == date(2024, 4, 15)
        assert p.end == date(2024, 4, 15)
        assert p.label == "Apr 15, 2024"
        assert p.iso == "2024-04-15"
    
    def test_make_week_period(self):
        """Test creating a week period"""
        p = make_week_period(date(2024, 4, 8))  # Monday
        assert p.type == "week"
        assert p.start == date(2024, 4, 8)
        assert p.end == date(2024, 4, 14)
        assert "Apr 08, 2024" in p.label
        assert p.iso == "2024-W15"
    
    def test_make_month_period(self):
        """Test creating a month period"""
        p = make_month_period(date(2024, 4, 15))
        assert p.type == "month"
        assert p.start == date(2024, 4, 1)
        assert p.end == date(2024, 4, 30)
        assert p.label == "April 2024"
        assert p.iso == "2024-04"


class TestPeriodInfoContains:
    """Tests for PeriodInfo.contains()"""
    
    def test_date_in_period(self):
        """Test date within period"""
        p = make_week_period(date(2024, 4, 8))
        assert p.contains(date(2024, 4, 10)) is True
    
    def test_date_before_period(self):
        """Test date before period start"""
        p = make_week_period(date(2024, 4, 8))
        assert p.contains(date(2024, 4, 7)) is False
    
    def test_date_after_period(self):
        """Test date after period end"""
        p = make_week_period(date(2024, 4, 8))
        assert p.contains(date(2024, 4, 15)) is False
    
    def test_start_date_inclusive(self):
        """Test period start date is inclusive"""
        p = make_week_period(date(2024, 4, 8))
        assert p.contains(date(2024, 4, 8)) is True
    
    def test_end_date_inclusive(self):
        """Test period end date is inclusive"""
        p = make_week_period(date(2024, 4, 8))
        assert p.contains(date(2024, 4, 14)) is True


class TestIteratePeriods:
    """Tests for iterate_periods()"""
    
    def test_iterate_days(self):
        """Test iterating over days"""
        periods = list(iterate_periods(
            date(2024, 1, 1), date(2024, 1, 3), "day"
        ))
        assert len(periods) == 3
        assert periods[0].iso == "2024-01-01"
        assert periods[1].iso == "2024-01-02"
        assert periods[2].iso == "2024-01-03"
    
    def test_iterate_weeks(self):
        """Test iterating over weeks"""
        periods = list(iterate_periods(
            date(2024, 1, 1), date(2024, 1, 21), "week"
        ))
        # Should cover weeks starting Dec 25, Jan 1, Jan 8, Jan 15
        assert len(periods) >= 3
        assert all(p.type == "week" for p in periods)
    
    def test_iterate_months(self):
        """Test iterating over months"""
        periods = list(iterate_periods(
            date(2024, 1, 15), date(2024, 3, 15), "month"
        ))
        assert len(periods) == 3
        assert periods[0].iso == "2024-01"
        assert periods[1].iso == "2024-02"
        assert periods[2].iso == "2024-03"
    
    def test_iterate_single_day_range(self):
        """Test iterating when start equals end"""
        periods = list(iterate_periods(
            date(2024, 1, 1), date(2024, 1, 1), "day"
        ))
        assert len(periods) == 1
    
    def test_iterate_empty_range(self):
        """Test iterating with end before start returns nothing meaningful"""
        # This tests behavior when end < start
        periods = list(iterate_periods(
            date(2024, 1, 10), date(2024, 1, 1), "day"
        ))
        assert len(periods) == 0


class TestGetLastNPeriods:
    """Tests for get_last_n_periods()"""
    
    def test_last_4_weeks(self):
        """Test getting last 4 weeks"""
        periods = get_last_n_periods(4, "week", date(2024, 4, 15))
        assert len(periods) == 4
        # Should be oldest first
        assert periods[0].start < periods[-1].start
        # Last period should contain reference date
        assert periods[-1].contains(date(2024, 4, 15))
    
    def test_last_3_months(self):
        """Test getting last 3 months"""
        periods = get_last_n_periods(3, "month", date(2024, 4, 15))
        assert len(periods) == 3
        assert periods[0].iso == "2024-02"
        assert periods[1].iso == "2024-03"
        assert periods[2].iso == "2024-04"
    
    def test_last_7_days(self):
        """Test getting last 7 days"""
        periods = get_last_n_periods(7, "day", date(2024, 4, 15))
        assert len(periods) == 7
        assert periods[-1].iso == "2024-04-15"
        assert periods[0].iso == "2024-04-09"
    
    def test_default_reference_is_today(self):
        """Test that default reference date is today"""
        periods = get_last_n_periods(1, "day")
        assert len(periods) == 1
        assert periods[0].iso == date.today().isoformat()


class TestComputePeriodStateHash:
    """Tests for compute_period_state_hash()"""
    
    def test_same_inputs_same_hash(self):
        """Test that same inputs produce same hash"""
        period = make_week_period(date(2024, 4, 8))
        convs = [{"id": "abc", "event_count": 10}]
        
        hash1 = compute_period_state_hash(period, convs, "agg123", "src456")
        hash2 = compute_period_state_hash(period, convs, "agg123", "src456")
        assert hash1 == hash2
    
    def test_different_conversation_changes_hash(self):
        """Test that different conversations produce different hash"""
        period = make_week_period(date(2024, 4, 8))
        convs1 = [{"id": "abc", "event_count": 10}]
        convs2 = [{"id": "xyz", "event_count": 10}]
        
        hash1 = compute_period_state_hash(period, convs1, "agg", "src")
        hash2 = compute_period_state_hash(period, convs2, "agg", "src")
        assert hash1 != hash2
    
    def test_different_event_count_changes_hash(self):
        """Test that event count change produces different hash"""
        period = make_week_period(date(2024, 4, 8))
        convs1 = [{"id": "abc", "event_count": 10}]
        convs2 = [{"id": "abc", "event_count": 15}]
        
        hash1 = compute_period_state_hash(period, convs1, "agg", "src")
        hash2 = compute_period_state_hash(period, convs2, "agg", "src")
        assert hash1 != hash2
    
    def test_different_prompt_hash_changes_hash(self):
        """Test that prompt change produces different hash"""
        period = make_week_period(date(2024, 4, 8))
        convs = [{"id": "abc", "event_count": 10}]
        
        hash1 = compute_period_state_hash(period, convs, "agg1", "src")
        hash2 = compute_period_state_hash(period, convs, "agg2", "src")
        assert hash1 != hash2
    
    def test_hash_is_16_chars(self):
        """Test that hash is 16 characters"""
        period = make_week_period(date(2024, 4, 8))
        h = compute_period_state_hash(period, [], "agg", "src")
        assert len(h) == 16


class TestGetDateRangeForPeriods:
    """Tests for get_date_range_for_periods()"""
    
    def test_single_period(self):
        """Test date range for single period"""
        periods = [make_week_period(date(2024, 4, 8))]
        start, end = get_date_range_for_periods(periods)
        assert start == date(2024, 4, 8)
        assert end == date(2024, 4, 14)
    
    def test_multiple_periods(self):
        """Test date range for multiple periods"""
        periods = [
            make_week_period(date(2024, 4, 1)),
            make_week_period(date(2024, 4, 8)),
            make_week_period(date(2024, 4, 15)),
        ]
        start, end = get_date_range_for_periods(periods)
        assert start == date(2024, 4, 1)
        assert end == date(2024, 4, 21)
    
    def test_empty_periods_returns_today(self):
        """Test empty periods returns today"""
        start, end = get_date_range_for_periods([])
        assert start == date.today()
        assert end == date.today()
