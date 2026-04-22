"""Tests for temporal query extraction."""

from datetime import datetime, timedelta, timezone

import pytest

from ohtv.analysis.temporal import (
    TemporalQuery,
    _fast_extract,
    _remove_temporal_refs,
    extract_temporal_filter,
)


class TestFastExtract:
    """Test fast regex-based temporal extraction."""
    
    def test_no_temporal_intent(self):
        """Questions without temporal keywords should not be filtered."""
        now = datetime.now(timezone.utc)
        result = _fast_extract("how did we fix the authentication bug?", now)
        assert result is not None
        assert result.has_temporal_intent is False
        assert result.start_date is None
        assert result.end_date is None
        assert result.cleaned_query == "how did we fix the authentication bug?"
    
    def test_yesterday(self):
        """'yesterday' should filter to previous day."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what did we work on yesterday?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        assert result.start_date == datetime(2026, 4, 21, 0, 0, 0, tzinfo=timezone.utc)
        assert result.end_date == datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc)
        assert "yesterday" not in result.cleaned_query.lower()
    
    def test_today(self):
        """'today' should filter to current day."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what happened today?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        assert result.start_date == datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc)
        assert result.end_date.date() == now.date()
    
    def test_this_week(self):
        """'this week' should filter from Monday to now."""
        # April 22, 2026 is a Wednesday
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what did we work on this week?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        # Week starts Monday = April 20
        assert result.start_date == datetime(2026, 4, 20, 0, 0, 0, tzinfo=timezone.utc)
        assert result.end_date == now
    
    def test_last_week(self):
        """'last week' should filter to 7 days before today."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("show me last week's conversations", now)
        assert result is not None
        assert result.has_temporal_intent is True
        assert result.start_date == datetime(2026, 4, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert result.end_date == datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc)
    
    def test_last_month(self):
        """'last month' should filter to 30 days before today."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what did we do last month?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        assert result.start_date == datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)
        assert result.end_date == datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc)
    
    def test_past_n_days(self):
        """'past N days' should filter to N days ago."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what did we work on in the past 3 days?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        expected_start = now - timedelta(days=3)
        assert result.start_date.date() == expected_start.date()
        assert result.end_date == now
    
    def test_past_n_weeks(self):
        """'past N weeks' should filter to N weeks ago."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what happened in the past 2 weeks?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        expected_start = now - timedelta(weeks=2)
        assert result.start_date.date() == expected_start.date()
    
    def test_n_days_ago(self):
        """'N days ago' should filter around that date."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what did we discuss 5 days ago?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        target = now - timedelta(days=5)
        # Should create a range around the target date
        assert result.start_date.date() == (target - timedelta(days=1)).date()
        assert result.end_date.date() == (target + timedelta(days=1)).date()
    
    def test_recently(self):
        """'recently' should default to last 7 days."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("what did we work on recently?", now)
        assert result is not None
        assert result.has_temporal_intent is True
        assert result.start_date.date() == (now - timedelta(days=7)).date()
        assert result.end_date == now
    
    def test_recent_without_ly(self):
        """'recent' should also work."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = _fast_extract("show me recent API changes", now)
        assert result is not None
        assert result.has_temporal_intent is True
    
    def test_complex_pattern_returns_none(self):
        """Complex patterns not matching fast extract should return None."""
        now = datetime.now(timezone.utc)
        # "a while ago" is temporal but not handled by fast extract
        result = _fast_extract("what did we work on a while ago?", now)
        # Should still be None because "while" isn't in our temporal keywords
        # Actually, "ago" is in our keywords, so it will be detected as temporal
        # but not matched by fast extract
        assert result is None  # Falls through to LLM


class TestRemoveTemporalRefs:
    """Test removal of temporal references from queries."""
    
    def test_remove_yesterday(self):
        result = _remove_temporal_refs("What did we work on yesterday?")
        assert "yesterday" not in result.lower()
        assert "work on" in result.lower()
    
    def test_remove_past_n_days(self):
        result = _remove_temporal_refs("What happened in the past 7 days?")
        assert "past 7 days" not in result.lower()
        assert "happened" in result.lower()
    
    def test_remove_multiple_refs(self):
        result = _remove_temporal_refs("What did we do yesterday and recently?")
        assert "yesterday" not in result.lower()
        assert "recently" not in result.lower()
    
    def test_preserve_semantic_content(self):
        result = _remove_temporal_refs("What API changes were made last week?")
        assert "API changes" in result
        assert "made" in result
        assert "last week" not in result.lower()


class TestExtractTemporalFilterIntegration:
    """Integration tests for extract_temporal_filter."""
    
    def test_defaults_to_current_time(self):
        """Should use current time if not provided."""
        # This should not raise
        result = extract_temporal_filter("what happened yesterday?")
        assert result.has_temporal_intent is True
        assert result.start_date is not None
    
    def test_passes_through_non_temporal(self):
        """Non-temporal questions should pass through unchanged."""
        result = extract_temporal_filter("how do I deploy to production?")
        assert result.has_temporal_intent is False
        assert result.cleaned_query == "how do I deploy to production?"
    
    def test_fast_extract_for_simple_patterns(self):
        """Simple patterns should use fast extraction without LLM."""
        now = datetime(2026, 4, 22, 14, 30, 0, tzinfo=timezone.utc)
        result = extract_temporal_filter("what happened yesterday?", current_date=now)
        assert result.has_temporal_intent is True
        # Fast extract should handle this
        assert result.start_date is not None


class TestTemporalQueryDataclass:
    """Test TemporalQuery dataclass."""
    
    def test_dataclass_fields(self):
        """Verify all expected fields exist."""
        query = TemporalQuery(
            start_date=datetime(2026, 4, 21, tzinfo=timezone.utc),
            end_date=datetime(2026, 4, 22, tzinfo=timezone.utc),
            cleaned_query="what happened?",
            has_temporal_intent=True,
        )
        assert query.start_date is not None
        assert query.end_date is not None
        assert query.cleaned_query == "what happened?"
        assert query.has_temporal_intent is True
    
    def test_nullable_dates(self):
        """Dates can be None for unbounded queries."""
        query = TemporalQuery(
            start_date=None,
            end_date=None,
            cleaned_query="show me everything",
            has_temporal_intent=False,
        )
        assert query.start_date is None
        assert query.end_date is None
