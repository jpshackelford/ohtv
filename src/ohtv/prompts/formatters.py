"""Field formatters for display schema rendering.

Formatters transform raw field values into display-ready strings.
Each formatter is a function that takes a value and optional args, returning a string.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Callable


def format_date(value: Any, args: str | None = None) -> str:
    """Format a datetime value as YYYY-MM-DD.
    
    Args:
        value: A datetime object or ISO format string
        args: Unused
        
    Returns:
        Formatted date string, or empty string if value is None
    """
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        local_time = value.astimezone()
        return local_time.strftime("%Y-%m-%d")
    return str(value)


def format_status_badge(value: Any, args: str | None = None) -> str:
    """Format a status value with emoji badge.
    
    Args:
        value: Status string (achieved, not_achieved, in_progress)
        args: Unused
        
    Returns:
        Emoji + text representation
    """
    if value is None:
        return ""
    status = str(value).lower()
    badges = {
        "achieved": "✅",
        "not_achieved": "❌",
        "in_progress": "🔄",
    }
    badge = badges.get(status, "❓")
    return f"{badge}"


def format_bullet_list(value: Any, args: str | None = None) -> str:
    """Format a list as bullet points.
    
    Args:
        value: A list of strings
        args: Unused
        
    Returns:
        Bullet-formatted string with newlines
    """
    if value is None:
        return ""
    if not isinstance(value, list):
        return str(value)
    if not value:
        return ""
    return "\n".join(f"• {item}" for item in value)


def format_truncate(value: Any, args: str | None = None) -> str:
    """Truncate a string with ellipsis.
    
    Args:
        value: String to truncate
        args: Max length as string (e.g., "50"), defaults to 50
        
    Returns:
        Truncated string with ellipsis if exceeded
    """
    if value is None:
        return ""
    text = str(value)
    max_len = int(args) if args and args.isdigit() else 50
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def format_plain(value: Any, args: str | None = None) -> str:
    """Default formatter that converts value to string.
    
    Args:
        value: Any value
        args: Unused
        
    Returns:
        String representation
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def format_time(value: Any, args: str | None = None) -> str:
    """Format a datetime value as HH:MM AM/PM.
    
    Args:
        value: A datetime object or ISO format string
        args: Unused
        
    Returns:
        Formatted time string (e.g., "10:42 AM"), or empty string if value is None
    """
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        local_time = value.astimezone()
        return local_time.strftime("%I:%M %p").lstrip("0")
    return str(value)


def format_duration_minutes(value: Any, args: str | None = None) -> str:
    """Format a timedelta as 'N mins' or 'Nh Mm'.
    
    Args:
        value: A timedelta object or number of seconds
        args: Unused
        
    Returns:
        Human-readable duration string (e.g., "35 mins", "1h 20m")
    """
    if value is None:
        return ""
    
    # Convert to total seconds
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
    elif isinstance(value, (int, float)):
        total_seconds = int(value)
    else:
        return str(value)
    
    if total_seconds < 0:
        return ""
    
    total_minutes = total_seconds // 60
    
    if total_minutes < 60:
        return f"{total_minutes} mins"
    
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h {minutes}m"


def format_step_count(value: Any, args: str | None = None) -> str:
    """Format integer as 'N steps'.
    
    Args:
        value: An integer event count
        args: Unused
        
    Returns:
        Formatted string (e.g., "46 steps"), or empty string if value is None/0
    """
    if value is None or value == 0:
        return ""
    try:
        count = int(value)
        return f"{count} steps"
    except (TypeError, ValueError):
        return str(value)


# Registry of available formatters
FORMATTERS: dict[str, Callable[[Any, str | None], str]] = {
    "date": format_date,
    "time": format_time,
    "duration_minutes": format_duration_minutes,
    "step_count": format_step_count,
    "status_badge": format_status_badge,
    "bullet_list": format_bullet_list,
    "truncate": format_truncate,
    "plain": format_plain,
}


def parse_format_spec(format_spec: str | None) -> tuple[str, str | None]:
    """Parse a format specification into formatter name and args.
    
    Args:
        format_spec: Format specification like "truncate(50)" or "date"
        
    Returns:
        Tuple of (formatter_name, args) where args may be None
    """
    if format_spec is None:
        return "plain", None
    
    # Check for function-style spec: "truncate(50)"
    match = re.match(r"(\w+)\(([^)]*)\)", format_spec)
    if match:
        return match.group(1), match.group(2)
    
    return format_spec, None


def get_formatter(format_spec: str | None) -> Callable[[Any], str]:
    """Get a formatter function for the given specification.
    
    Args:
        format_spec: Format specification like "truncate(50)" or "date"
        
    Returns:
        Formatter function that takes a value and returns formatted string
    """
    name, args = parse_format_spec(format_spec)
    formatter = FORMATTERS.get(name, format_plain)
    return lambda value: formatter(value, args)


def format_value(value: Any, format_spec: str | None = None) -> str:
    """Format a value using the specified format.
    
    Args:
        value: Value to format
        format_spec: Format specification (e.g., "date", "truncate(50)")
        
    Returns:
        Formatted string
    """
    formatter = get_formatter(format_spec)
    return formatter(value)
