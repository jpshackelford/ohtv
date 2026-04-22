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


def _fast_extract(question: str, current_date: datetime) -> TemporalQuery | None:
    """Fast regex-based extraction for common temporal patterns.
    
    Returns None if the pattern isn't recognized (will fall back to LLM).
    """
    q_lower = question.lower()
    
    # Month name mapping
    month_names = {
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
    
    # No temporal intent - check for temporal keywords
    temporal_keywords = [
        "yesterday", "today", "last week", "this week", "last month",
        "this month", "past", "recent", "ago", "before", "after",
        "since", "until", "week", "month", "day", "back",
        "few days", "few weeks", "couple", "early", "mid", "late",
    ]
    # Also check for month names
    has_month_name = any(m in q_lower for m in month_names.keys())
    has_temporal_keyword = any(kw in q_lower for kw in temporal_keywords)
    
    if not has_temporal_keyword and not has_month_name:
        return TemporalQuery(
            start_date=None,
            end_date=None,
            cleaned_query=question,
            has_temporal_intent=False,
        )
    
    today_start = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = current_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # "yesterday"
    if re.search(r'\byesterday\b', q_lower):
        yesterday = today_start - timedelta(days=1)
        return TemporalQuery(
            start_date=yesterday,
            end_date=today_start,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "today"
    if re.search(r'\btoday\b', q_lower):
        return TemporalQuery(
            start_date=today_start,
            end_date=today_end,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "this week"
    if re.search(r'\bthis week\b', q_lower):
        # Start of week (Monday)
        days_since_monday = current_date.weekday()
        week_start = today_start - timedelta(days=days_since_monday)
        return TemporalQuery(
            start_date=week_start,
            end_date=current_date,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "last week"
    if re.search(r'\blast week\b', q_lower):
        return TemporalQuery(
            start_date=today_start - timedelta(days=7),
            end_date=today_start,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "last month"
    if re.search(r'\blast month\b', q_lower):
        return TemporalQuery(
            start_date=today_start - timedelta(days=30),
            end_date=today_start,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "a few days ago" / "a few days back" / "few days ago"
    if re.search(r'\b(a\s+)?few\s+days?\s+(ago|back)\b', q_lower):
        # "a few" typically means 3-5, we'll use ~4 days with a range
        return TemporalQuery(
            start_date=today_start - timedelta(days=5),
            end_date=today_start - timedelta(days=2),
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "a few weeks ago" / "a few weeks back"
    if re.search(r'\b(a\s+)?few\s+weeks?\s+(ago|back)\b', q_lower):
        # "a few weeks" = ~2-4 weeks
        return TemporalQuery(
            start_date=today_start - timedelta(weeks=4),
            end_date=today_start - timedelta(weeks=2),
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "a couple days ago" / "couple of days ago"
    if re.search(r'\b(a\s+)?couple\s+(of\s+)?days?\s+(ago|back)\b', q_lower):
        return TemporalQuery(
            start_date=today_start - timedelta(days=3),
            end_date=today_start - timedelta(days=1),
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "a couple weeks ago" / "couple of weeks ago"
    if re.search(r'\b(a\s+)?couple\s+(of\s+)?weeks?\s+(ago|back)\b', q_lower):
        return TemporalQuery(
            start_date=today_start - timedelta(weeks=3),
            end_date=today_start - timedelta(weeks=1),
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "past N days/weeks"
    match = re.search(r'\bpast\s+(\d+)\s+(day|week|month)s?\b', q_lower)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if unit == "day":
            delta = timedelta(days=n)
        elif unit == "week":
            delta = timedelta(weeks=n)
        else:  # month
            delta = timedelta(days=n * 30)
        return TemporalQuery(
            start_date=current_date - delta,
            end_date=current_date,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "N days/weeks ago" or "N days/weeks back"
    match = re.search(r'\b(\d+)\s+(day|week|month)s?\s+(ago|back)\b', q_lower)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if unit == "day":
            delta = timedelta(days=n)
        elif unit == "week":
            delta = timedelta(weeks=n)
        else:  # month
            delta = timedelta(days=n * 30)
        # For "N days ago", search around that period
        target = current_date - delta
        return TemporalQuery(
            start_date=target - timedelta(days=1),
            end_date=target + timedelta(days=1),
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "recently" or "recent"
    if re.search(r'\brecent(ly)?\b', q_lower):
        return TemporalQuery(
            start_date=today_start - timedelta(days=7),
            end_date=current_date,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # Month with qualifier: "early March", "mid-March", "late March", "in March"
    # Build regex pattern for all month names
    month_pattern = '|'.join(month_names.keys())
    
    # "early <month>" - first 10 days
    match = re.search(rf'\bearly\s+({month_pattern})\b', q_lower)
    if match:
        month_num = month_names[match.group(1)]
        year = _infer_year_for_month(month_num, current_date)
        start = datetime(year, month_num, 1, tzinfo=timezone.utc)
        end = datetime(year, month_num, 10, 23, 59, 59, tzinfo=timezone.utc)
        return TemporalQuery(
            start_date=start,
            end_date=end,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "mid-<month>" or "mid <month>" - days 10-20
    match = re.search(rf'\bmid[-\s]?({month_pattern})\b', q_lower)
    if match:
        month_num = month_names[match.group(1)]
        year = _infer_year_for_month(month_num, current_date)
        start = datetime(year, month_num, 10, tzinfo=timezone.utc)
        end = datetime(year, month_num, 20, 23, 59, 59, tzinfo=timezone.utc)
        return TemporalQuery(
            start_date=start,
            end_date=end,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "late <month>" - days 20-end
    match = re.search(rf'\blate\s+({month_pattern})\b', q_lower)
    if match:
        month_num = month_names[match.group(1)]
        year = _infer_year_for_month(month_num, current_date)
        start = datetime(year, month_num, 20, tzinfo=timezone.utc)
        # Get last day of month
        if month_num == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        else:
            end = datetime(year, month_num + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        return TemporalQuery(
            start_date=start,
            end_date=end,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # "in <month>" - whole month
    match = re.search(rf'\bin\s+({month_pattern})\b', q_lower)
    if match:
        month_num = month_names[match.group(1)]
        year = _infer_year_for_month(month_num, current_date)
        start = datetime(year, month_num, 1, tzinfo=timezone.utc)
        # Get last day of month
        if month_num == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        else:
            end = datetime(year, month_num + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        return TemporalQuery(
            start_date=start,
            end_date=end,
            cleaned_query=_remove_temporal_refs(question),
            has_temporal_intent=True,
        )
    
    # Pattern not recognized, fall back to LLM
    return None


def _infer_year_for_month(month_num: int, current_date: datetime) -> int:
    """Infer the most likely year for a month reference.
    
    If the month is in the future relative to current date, assume last year.
    Otherwise assume current year.
    """
    current_month = current_date.month
    current_year = current_date.year
    
    # If the referenced month is after the current month, it's probably last year
    if month_num > current_month:
        return current_year - 1
    return current_year


def _remove_temporal_refs(question: str) -> str:
    """Remove common temporal references from a question.
    
    Keeps the semantic intent while removing time-specific words.
    """
    # Month names for pattern building
    month_names = (
        "january|jan|february|feb|march|mar|april|apr|may|june|jun|"
        "july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec"
    )
    
    patterns = [
        r'\byesterday\b',
        r'\btoday\b',
        r'\bthis week\b',
        r'\blast week\b',
        r'\bthis month\b',
        r'\blast month\b',
        r'\bpast\s+\d+\s+(day|week|month)s?\b',
        r'\b\d+\s+(day|week|month)s?\s+(ago|back)\b',
        r'\b(a\s+)?few\s+(day|week)s?\s+(ago|back)\b',
        r'\b(a\s+)?couple\s+(of\s+)?(day|week)s?\s+(ago|back)\b',
        r'\brecent(ly)?\b',
        r'\bin the\s+',  # "in the past week" -> "past week" already handled
        # Month patterns
        rf'\bearly\s+({month_names})\b',
        rf'\bmid[-\s]?({month_names})\b',
        rf'\blate\s+({month_names})\b',
        rf'\bin\s+({month_names})\b',
    ]
    
    result = question
    for pattern in patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE)
    
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
