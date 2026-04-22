"""Temporal query extraction for time-aware RAG.

Uses an LLM to pre-process questions and extract temporal constraints
before retrieval. Converts relative time references ("yesterday", "last week")
into absolute date ranges.

Environment variables:
- LLM_MODEL: Model to use for extraction (default: openai/gpt-4o-mini)
- LLM_API_KEY: API key for LiteLLM proxy
- LLM_BASE_URL: Base URL for LiteLLM proxy (optional)
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import litellm

litellm.suppress_debug_info = True

log = logging.getLogger("ohtv")

DEFAULT_EXTRACTION_MODEL = "openai/gpt-4o-mini"


@dataclass
class TemporalQuery:
    """Decomposed query with temporal constraints extracted.
    
    Attributes:
        start_date: Lower bound for date filtering (None = no lower bound)
        end_date: Upper bound for date filtering (None = no upper bound)
        cleaned_query: Query with time references removed for better embedding
        has_temporal_intent: Whether the original query had temporal constraints
    """
    start_date: datetime | None
    end_date: datetime | None
    cleaned_query: str
    has_temporal_intent: bool


# Month name mapping (shared between extraction and cleaning)
MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Build month pattern once for reuse
_MONTH_PATTERN = '|'.join(MONTH_NAMES.keys())


@dataclass
class TemporalPattern:
    """A temporal pattern with its regex and date calculation logic.
    
    Attributes:
        name: Descriptive name for logging/debugging
        regex: Compiled regex pattern to match
        calculate: Function (now, match) -> (start_date, end_date)
        removal_pattern: Optional separate regex for cleaning (uses main regex if None)
    """
    name: str
    regex: re.Pattern
    calculate: Callable[[datetime, re.Match | None], tuple[datetime, datetime]]
    removal_pattern: re.Pattern | None = None


EXTRACTION_PROMPT = """You are a query analyzer that extracts temporal (time-based) constraints from user questions.

Given a question about conversations/work history, extract:
1. start_date: The earliest date to include (ISO 8601 format, UTC)
2. end_date: The latest date to include (ISO 8601 format, UTC)  
3. cleaned_query: The question with time references removed, keeping the semantic intent

Current date/time: {current_datetime}

Rules:
- "yesterday" = yesterday's full day (00:00:00 to 23:59:59)
- "last week" = the 7 days before today
- "last month" = the 30 days before today
- "past N days/weeks/months" = N * respective time period before today
- "this week" = from start of current week (Monday) to now
- "today" = today's full day so far
- "recently" = last 7 days (reasonable default)
- If no temporal reference, return null for dates and original query unchanged
- For vague references like "a while ago", use null (don't guess)
- For future references ("next week"), use null (we can't search the future)

Respond ONLY with valid JSON in this exact format:
{{
  "start_date": "2026-04-20T00:00:00Z" or null,
  "end_date": "2026-04-21T23:59:59Z" or null,
  "cleaned_query": "the question without time references",
  "has_temporal_intent": true or false
}}

Question: {question}"""


def extract_temporal_filter(
    question: str,
    current_date: datetime | None = None,
    model: str | None = None,
) -> TemporalQuery:
    """Extract temporal constraints from a question using an LLM.
    
    Args:
        question: The user's question
        current_date: Current date/time for relative calculations (default: now UTC)
        model: LLM model for extraction (default: LLM_MODEL env var or gpt-4o-mini)
    
    Returns:
        TemporalQuery with extracted date bounds and cleaned query
    
    Raises:
        RuntimeError: If LLM configuration is missing or API call fails
    """
    if current_date is None:
        current_date = datetime.now(timezone.utc)
    
    # First try fast regex-based extraction for common patterns
    fast_result = _fast_extract(question, current_date)
    if fast_result is not None:
        log.debug("Using fast temporal extraction: %s", fast_result)
        return fast_result
    
    # Fall back to LLM extraction for complex cases
    return _llm_extract(question, current_date, model)


def _infer_year_for_month(month_num: int, current_date: datetime) -> int:
    """Infer the most likely year for a month reference.
    
    If the month is in the future relative to current date, assume last year.
    Otherwise assume current year.
    """
    if month_num > current_date.month:
        return current_date.year - 1
    return current_date.year


def _get_month_end(year: int, month: int) -> datetime:
    """Get the last moment of a given month."""
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
    return datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)


def _build_temporal_patterns() -> list[TemporalPattern]:
    """Build the list of temporal patterns.
    
    Each pattern has a regex and a calculation function that takes (current_date, match)
    and returns (start_date, end_date).
    """
    
    def today_start(now: datetime) -> datetime:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    def today_end(now: datetime) -> datetime:
        return now.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    patterns = [
        # Simple patterns
        TemporalPattern(
            name="yesterday",
            regex=re.compile(r'\byesterday\b', re.IGNORECASE),
            calculate=lambda now, m: (today_start(now) - timedelta(days=1), today_start(now)),
        ),
        TemporalPattern(
            name="today",
            regex=re.compile(r'\btoday\b', re.IGNORECASE),
            calculate=lambda now, m: (today_start(now), today_end(now)),
        ),
        TemporalPattern(
            name="this_week",
            regex=re.compile(r'\bthis week\b', re.IGNORECASE),
            calculate=lambda now, m: (
                today_start(now) - timedelta(days=now.weekday()),
                now,
            ),
        ),
        TemporalPattern(
            name="last_week",
            regex=re.compile(r'\blast week\b', re.IGNORECASE),
            calculate=lambda now, m: (today_start(now) - timedelta(days=7), today_start(now)),
        ),
        TemporalPattern(
            name="last_month",
            regex=re.compile(r'\blast month\b', re.IGNORECASE),
            calculate=lambda now, m: (today_start(now) - timedelta(days=30), today_start(now)),
        ),
        TemporalPattern(
            name="recently",
            regex=re.compile(r'\brecent(ly)?\b', re.IGNORECASE),
            calculate=lambda now, m: (today_start(now) - timedelta(days=7), now),
        ),
        # Vague quantifiers
        TemporalPattern(
            name="few_days_ago",
            regex=re.compile(r'\b(a\s+)?few\s+days?\s+(ago|back)\b', re.IGNORECASE),
            calculate=lambda now, m: (
                today_start(now) - timedelta(days=5),
                today_start(now) - timedelta(days=2),
            ),
        ),
        TemporalPattern(
            name="few_weeks_ago",
            regex=re.compile(r'\b(a\s+)?few\s+weeks?\s+(ago|back)\b', re.IGNORECASE),
            calculate=lambda now, m: (
                today_start(now) - timedelta(weeks=4),
                today_start(now) - timedelta(weeks=2),
            ),
        ),
        TemporalPattern(
            name="couple_days_ago",
            regex=re.compile(r'\b(a\s+)?couple\s+(of\s+)?days?\s+(ago|back)\b', re.IGNORECASE),
            calculate=lambda now, m: (
                today_start(now) - timedelta(days=3),
                today_start(now) - timedelta(days=1),
            ),
        ),
        TemporalPattern(
            name="couple_weeks_ago",
            regex=re.compile(r'\b(a\s+)?couple\s+(of\s+)?weeks?\s+(ago|back)\b', re.IGNORECASE),
            calculate=lambda now, m: (
                today_start(now) - timedelta(weeks=3),
                today_start(now) - timedelta(weeks=1),
            ),
        ),
        # Numeric patterns
        TemporalPattern(
            name="past_n_units",
            regex=re.compile(r'\bpast\s+(\d+)\s+(day|week|month)s?\b', re.IGNORECASE),
            calculate=lambda now, m: (
                now - _unit_to_delta(int(m.group(1)), m.group(2)),
                now,
            ),
        ),
        TemporalPattern(
            name="n_units_ago",
            regex=re.compile(r'\b(\d+)\s+(day|week|month)s?\s+(ago|back)\b', re.IGNORECASE),
            calculate=lambda now, m: (
                (target := now - _unit_to_delta(int(m.group(1)), m.group(2))) - timedelta(days=1),
                target + timedelta(days=1),
            )[0:2],  # walrus operator trick for temp variable
        ),
        # Month qualifiers (must come before generic "in <month>")
        TemporalPattern(
            name="early_month",
            regex=re.compile(rf'\bearly\s+({_MONTH_PATTERN})\b', re.IGNORECASE),
            calculate=lambda now, m: _month_range(m.group(1), now, 1, 10),
        ),
        TemporalPattern(
            name="mid_month",
            regex=re.compile(rf'\bmid[-\s]?({_MONTH_PATTERN})\b', re.IGNORECASE),
            calculate=lambda now, m: _month_range(m.group(1), now, 10, 20),
        ),
        TemporalPattern(
            name="late_month",
            regex=re.compile(rf'\blate\s+({_MONTH_PATTERN})\b', re.IGNORECASE),
            calculate=lambda now, m: _month_range_to_end(m.group(1), now, 20),
        ),
        TemporalPattern(
            name="in_month",
            regex=re.compile(rf'\bin\s+({_MONTH_PATTERN})\b', re.IGNORECASE),
            calculate=lambda now, m: _full_month_range(m.group(1), now),
        ),
    ]
    return patterns


def _unit_to_delta(n: int, unit: str) -> timedelta:
    """Convert a numeric amount and unit to a timedelta."""
    unit = unit.lower()
    if unit == "day":
        return timedelta(days=n)
    elif unit == "week":
        return timedelta(weeks=n)
    else:  # month
        return timedelta(days=n * 30)


def _month_range(
    month_name: str, current_date: datetime, start_day: int, end_day: int
) -> tuple[datetime, datetime]:
    """Calculate a date range within a specific month."""
    month_num = MONTH_NAMES[month_name.lower()]
    year = _infer_year_for_month(month_num, current_date)
    start = datetime(year, month_num, start_day, tzinfo=timezone.utc)
    end = datetime(year, month_num, end_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def _month_range_to_end(
    month_name: str, current_date: datetime, start_day: int
) -> tuple[datetime, datetime]:
    """Calculate a date range from a day to the end of a month."""
    month_num = MONTH_NAMES[month_name.lower()]
    year = _infer_year_for_month(month_num, current_date)
    start = datetime(year, month_num, start_day, tzinfo=timezone.utc)
    end = _get_month_end(year, month_num)
    return start, end


def _full_month_range(month_name: str, current_date: datetime) -> tuple[datetime, datetime]:
    """Calculate a date range for a full month."""
    month_num = MONTH_NAMES[month_name.lower()]
    year = _infer_year_for_month(month_num, current_date)
    start = datetime(year, month_num, 1, tzinfo=timezone.utc)
    end = _get_month_end(year, month_num)
    return start, end


# Build patterns once at module load
TEMPORAL_PATTERNS = _build_temporal_patterns()

# Keywords for quick check (avoids regex on non-temporal queries)
TEMPORAL_KEYWORDS = [
    "yesterday", "today", "last week", "this week", "last month",
    "this month", "past", "recent", "ago", "before", "after",
    "since", "until", "week", "month", "day", "back",
    "few days", "few weeks", "couple", "early", "mid", "late",
]


def _fast_extract(question: str, current_date: datetime) -> TemporalQuery | None:
    """Fast regex-based extraction for common temporal patterns.
    
    Returns None if the pattern isn't recognized (will fall back to LLM).
    """
    q_lower = question.lower()
    
    # Quick check: skip regex if no temporal keywords present
    has_month_name = any(m in q_lower for m in MONTH_NAMES.keys())
    has_temporal_keyword = any(kw in q_lower for kw in TEMPORAL_KEYWORDS)
    
    if not has_temporal_keyword and not has_month_name:
        return TemporalQuery(
            start_date=None,
            end_date=None,
            cleaned_query=question,
            has_temporal_intent=False,
        )
    
    # Try each pattern in order
    for pattern in TEMPORAL_PATTERNS:
        match = pattern.regex.search(q_lower)
        if match:
            start_date, end_date = pattern.calculate(current_date, match)
            return TemporalQuery(
                start_date=start_date,
                end_date=end_date,
                cleaned_query=_remove_temporal_refs(question),
                has_temporal_intent=True,
            )
    
    # Pattern not recognized, fall back to LLM
    return None


def _remove_temporal_refs(question: str) -> str:
    """Remove temporal references from a question using the pattern registry.
    
    Uses the same patterns as extraction to ensure consistency.
    """
    result = question
    
    # Remove matches for all registered patterns
    for pattern in TEMPORAL_PATTERNS:
        removal_regex = pattern.removal_pattern or pattern.regex
        result = removal_regex.sub('', result)
    
    # Also remove "in the" which often precedes temporal references
    result = re.sub(r'\bin the\s+', ' ', result, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    result = re.sub(r'\s+', ' ', result).strip()
    
    # Remove dangling prepositions
    result = re.sub(r'\b(from|in|during|over|within)\s*$', '', result).strip()
    result = re.sub(r'^\s*(from|in|during|over|within)\b', '', result).strip()
    
    return result if result else question


def _llm_extract(
    question: str,
    current_date: datetime,
    model: str | None = None,
) -> TemporalQuery:
    """Extract temporal constraints using an LLM."""
    if model is None:
        model = os.environ.get("LLM_MODEL", DEFAULT_EXTRACTION_MODEL)
    
    api_key = os.environ.get("LLM_API_KEY")
    api_base = os.environ.get("LLM_BASE_URL")
    
    if not api_key:
        # If no API key, return query unchanged (graceful degradation)
        log.warning("LLM_API_KEY not set, skipping temporal extraction")
        return TemporalQuery(
            start_date=None,
            end_date=None,
            cleaned_query=question,
            has_temporal_intent=False,
        )
    
    prompt = EXTRACTION_PROMPT.format(
        current_datetime=current_date.isoformat(),
        question=question,
    )
    
    log.debug("Extracting temporal filter with model %s", model)
    
    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            api_base=api_base,
            temperature=0,  # Deterministic output
        )
        
        content = response.choices[0].message.content.strip()
        
        # Parse JSON response
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                log.warning("Failed to parse temporal extraction response: %s", content)
                return TemporalQuery(
                    start_date=None,
                    end_date=None,
                    cleaned_query=question,
                    has_temporal_intent=False,
                )
        
        # Parse dates
        start_date = None
        end_date = None
        
        if data.get("start_date"):
            try:
                start_date = datetime.fromisoformat(data["start_date"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        
        if data.get("end_date"):
            try:
                end_date = datetime.fromisoformat(data["end_date"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        
        return TemporalQuery(
            start_date=start_date,
            end_date=end_date,
            cleaned_query=data.get("cleaned_query", question),
            has_temporal_intent=data.get("has_temporal_intent", bool(start_date or end_date)),
        )
        
    except Exception as e:
        log.warning("Temporal extraction failed: %s", e)
        return TemporalQuery(
            start_date=None,
            end_date=None,
            cleaned_query=question,
            has_temporal_intent=False,
        )
