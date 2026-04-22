"""Period iteration utilities for aggregate analysis jobs.

Provides functions to iterate over time periods (weeks, days, months)
within a date range, with support for period metadata generation.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterator, Literal


@dataclass
class PeriodInfo:
    """Metadata about a specific time period.
    
    Provides human-readable labels and machine-parseable identifiers
    for use in aggregate analysis prompts.
    """
    type: Literal["week", "day", "month"]
    start: date
    end: date
    label: str
    iso: str

    def contains(self, dt: datetime | date) -> bool:
        """Check if a datetime falls within this period."""
        if isinstance(dt, datetime):
            dt = dt.date()
        return self.start <= dt <= self.end

    def to_dict(self) -> dict:
        """Convert to dict for template rendering."""
        return {
            "type": self.type,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "label": self.label,
            "iso": self.iso,
        }


def get_week_start(dt: date, week_starts_monday: bool = True) -> date:
    """Get the start of the week containing the given date.
    
    Args:
        dt: Date to find week start for
        week_starts_monday: If True, weeks start Monday (ISO); if False, Sunday
        
    Returns:
        Date of the week's start day
    """
    if week_starts_monday:
        return dt - timedelta(days=dt.weekday())
    else:
        # weekday() returns 0 for Monday, so Sunday is 6
        return dt - timedelta(days=(dt.weekday() + 1) % 7)


def get_month_start(dt: date) -> date:
    """Get the first day of the month containing the given date."""
    return dt.replace(day=1)


def get_month_end(dt: date) -> date:
    """Get the last day of the month containing the given date."""
    # Go to first of next month, then back one day
    if dt.month == 12:
        next_month = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        next_month = dt.replace(month=dt.month + 1, day=1)
    return next_month - timedelta(days=1)


def make_week_period(start: date) -> PeriodInfo:
    """Create a PeriodInfo for a week starting at the given date."""
    end = start + timedelta(days=6)
    iso_week = start.isocalendar()
    return PeriodInfo(
        type="week",
        start=start,
        end=end,
        label=f"Week of {start.strftime('%b %d, %Y')}",
        iso=f"{iso_week.year}-W{iso_week.week:02d}",
    )


def make_day_period(dt: date) -> PeriodInfo:
    """Create a PeriodInfo for a single day."""
    return PeriodInfo(
        type="day",
        start=dt,
        end=dt,
        label=dt.strftime("%b %d, %Y"),
        iso=dt.isoformat(),
    )


def make_month_period(dt: date) -> PeriodInfo:
    """Create a PeriodInfo for the month containing the given date."""
    start = get_month_start(dt)
    end = get_month_end(dt)
    return PeriodInfo(
        type="month",
        start=start,
        end=end,
        label=start.strftime("%B %Y"),
        iso=start.strftime("%Y-%m"),
    )


def iterate_periods(
    start_date: date,
    end_date: date,
    period_type: Literal["week", "day", "month"],
) -> Iterator[PeriodInfo]:
    """Iterate over periods between start and end dates.
    
    Args:
        start_date: First date to include
        end_date: Last date to include
        period_type: Type of period to iterate over
        
    Yields:
        PeriodInfo for each period overlapping the date range
    """
    if period_type == "day":
        current = start_date
        while current <= end_date:
            yield make_day_period(current)
            current += timedelta(days=1)
    
    elif period_type == "week":
        # Start from the week containing start_date
        current = get_week_start(start_date)
        while current <= end_date:
            yield make_week_period(current)
            current += timedelta(weeks=1)
    
    elif period_type == "month":
        # Start from the month containing start_date
        current = get_month_start(start_date)
        while current <= end_date:
            yield make_month_period(current)
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)


def get_last_n_periods(
    n: int,
    period_type: Literal["week", "day", "month"],
    reference_date: date | None = None,
) -> list[PeriodInfo]:
    """Get the last N periods ending with the current period.
    
    Args:
        n: Number of periods to return
        period_type: Type of period
        reference_date: Reference date (defaults to today)
        
    Returns:
        List of PeriodInfo objects, oldest first
    """
    if reference_date is None:
        reference_date = date.today()
    
    periods = []
    
    if period_type == "day":
        for i in range(n - 1, -1, -1):
            periods.append(make_day_period(reference_date - timedelta(days=i)))
    
    elif period_type == "week":
        current_week_start = get_week_start(reference_date)
        for i in range(n - 1, -1, -1):
            week_start = current_week_start - timedelta(weeks=i)
            periods.append(make_week_period(week_start))
    
    elif period_type == "month":
        # Go back n-1 months from current month
        current = get_month_start(reference_date)
        month_list = []
        for _ in range(n):
            month_list.append(current)
            # Go back one month
            if current.month == 1:
                current = current.replace(year=current.year - 1, month=12)
            else:
                current = current.replace(month=current.month - 1)
        # Reverse to get oldest first
        for m in reversed(month_list):
            periods.append(make_month_period(m))
    
    return periods


def compute_period_state_hash(
    period: PeriodInfo,
    conversations: list[dict],
    aggregate_prompt_hash: str,
    source_prompt_hash: str,
) -> str:
    """Compute a state hash for cache invalidation.
    
    The hash changes when any of these change:
    - Set of conversations in the period
    - Event count of any conversation
    - Aggregate job prompt
    - Source job prompt
    
    Args:
        period: The period being analyzed
        conversations: List of conversation dicts with 'id' and 'event_count' keys
        aggregate_prompt_hash: Hash of the aggregate prompt content
        source_prompt_hash: Hash of the source job prompt content
        
    Returns:
        16-character hash string for cache key
    """
    # Sort conversations by ID for deterministic hashing
    sorted_convs = sorted(conversations, key=lambda c: c.get("id", ""))
    
    # Build hash input
    hash_parts = [
        f"period:{period.iso}",
        f"agg_prompt:{aggregate_prompt_hash}",
        f"src_prompt:{source_prompt_hash}",
    ]
    for conv in sorted_convs:
        hash_parts.append(f"conv:{conv.get('id', '')}:{conv.get('event_count', 0)}")
    
    hash_input = "\n".join(hash_parts)
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def get_date_range_for_periods(
    periods: list[PeriodInfo],
) -> tuple[date, date]:
    """Get the overall date range spanning all periods.
    
    Args:
        periods: List of periods
        
    Returns:
        Tuple of (start_date, end_date)
    """
    if not periods:
        today = date.today()
        return today, today
    
    start = min(p.start for p in periods)
    end = max(p.end for p in periods)
    return start, end
