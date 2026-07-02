"""Daily/weekly worklog generation with LLM synthesis.

Generates worklogs showing conversations with synthesized titles and purposes,
PR/issue links, and engagement metrics. Outputs to HTML, markdown, or text.

This module follows the pattern established by velocity.py — pure data layer
with no Click/Rich dependencies beyond optional formatters. The main entry
point :func:`generate_worklog` returns a structured WorklogReport that
CLI/automation can render in multiple formats.

Key design:
* Uses existing DB tables (conversations, conversation_engagement, change_refs)
* Loads events from filesystem only for LLM synthesis
* Batched LLM synthesis (similar to titles.py pattern)
* Multiple output formats with rich styling
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ohtv.analysis.cache import load_events
from ohtv.analysis.transcript import extract_message_content

log = logging.getLogger("ohtv")


# =============================================================================
# Data structures
# =============================================================================


@dataclass
class WorklogEntry:
    """A single conversation entry in the worklog."""

    conversation_id: str
    title: str
    created_at: datetime | None
    
    # Engagement metrics
    engaged_seconds: int | None = None
    engaged_count: int | None = None
    first_event_ts: datetime | None = None
    last_event_ts: datetime | None = None
    
    # Synthesis results
    synthesized_title: str | None = None
    purpose: str | None = None
    
    # Outcomes (PRs/issues)
    refs: list[tuple[str, int | None, str, str | None, str | None, str | None]] = field(
        default_factory=list
    )
    
    # Derived display fields
    engagement_display: str = ""
    time_display: str = ""


@dataclass
class WorklogReport:
    """Complete worklog data structure."""

    date_label: str  # e.g., "2026-07-01 Wednesday" or "2026-W27"
    entries: list[WorklogEntry]
    total_count: int
    engaged_count: int
    synthesis_cost: float = 0.0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Query logic
# =============================================================================


def query_conversations_for_worklog(
    conn: sqlite3.Connection,
    since: date | None = None,
    until: date | None = None,
    engaged_only: bool = False,
    min_engaged_seconds: int = 0,
    source: str | None = None,
    repo_filter: str | None = None,
) -> list[dict]:
    """Query conversations with engagement data.
    
    Args:
        conn: Database connection
        since: Start date (inclusive)
        until: End date (inclusive)
        engaged_only: If True, exclude conversations with 0 engagement
        min_engaged_seconds: Minimum engaged time threshold
        source: Filter by source ('local' or 'cloud')
        repo_filter: Filter by selected_repository
    
    Returns:
        List of conversation dicts with engagement metrics
    """
    query = """
        SELECT
            c.id,
            c.title,
            c.created_at,
            ce.engaged_seconds,
            ce.engaged_count,
            ce.first_event_ts,
            ce.last_event_ts
        FROM conversations c
        LEFT JOIN conversation_engagement ce ON c.id = ce.conversation_id
        WHERE 1=1
    """
    
    params: list[Any] = []
    
    # Date filtering
    if since:
        query += " AND date(c.created_at) >= ?"
        params.append(since.isoformat())
    if until:
        query += " AND date(c.created_at) <= ?"
        params.append(until.isoformat())
    
    # Source filtering
    if source:
        query += " AND c.source = ?"
        params.append(source)
    
    # Repository filtering
    if repo_filter:
        query += " AND c.selected_repository LIKE ?"
        params.append(f"%{repo_filter}%")
    
    # Engagement filtering
    if engaged_only or min_engaged_seconds > 0:
        query += " AND ce.engaged_seconds IS NOT NULL"
        if engaged_only:
            query += " AND ce.engaged_seconds > 0"
        if min_engaged_seconds > 0:
            query += " AND ce.engaged_seconds >= ?"
            params.append(min_engaged_seconds)
    
    query += " ORDER BY c.created_at DESC"
    
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    
    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "engaged_seconds": row[3],
            "engaged_count": row[4],
            "first_event_ts": row[5],
            "last_event_ts": row[6],
        })
    
    return result


# =============================================================================
# Context extraction
# =============================================================================


def extract_worklog_context(
    conv_dir: Path, conv_id: str, conn: sqlite3.Connection
) -> dict:
    """Extract context needed for LLM synthesis.
    
    Args:
        conv_dir: Path to conversation directory
        conv_id: Conversation ID (normalized, no dashes)
        conn: Database connection
    
    Returns:
        Dict with user_messages, finish_message, and refs
    """
    # Load events from filesystem
    events = load_events(conv_dir)
    
    # Extract user messages (first 5 for context)
    user_messages = []
    for event in events:
        if (
            event.get("kind") == "MessageEvent"
            and event.get("source") == "user"
        ):
            content = extract_message_content(event)
            if content:
                user_messages.append(content)
            if len(user_messages) >= 5:
                break
    
    # Extract finish message (agent's summary)
    finish_message = None
    for event in reversed(events):
        if event.get("tool_name") == "finish":
            action = event.get("action", {})
            if isinstance(action, dict):
                finish_message = action.get("message")
                if finish_message:
                    break
    
    # Query refs from database
    refs_query = """
        SELECT
            change_type,
            pr_or_issue_number,
            title,
            state,
            repo_full_name,
            url
        FROM change_refs
        WHERE conversation_id = ?
        ORDER BY first_mention_idx
    """
    cursor = conn.execute(refs_query, (conv_id,))
    refs = cursor.fetchall()
    
    return {
        "user_messages": user_messages,
        "finish_message": finish_message,
        "refs": refs,
    }


# =============================================================================
# LLM synthesis
# =============================================================================


def synthesize_worklog_entries(
    entries_with_context: list[dict], model: str = "gpt-4o-mini"
) -> tuple[dict[str, tuple[str, str]], float]:
    """Batch-synthesize worklog entries using LLM.
    
    Args:
        entries_with_context: List of dicts with 'id' and 'context' keys
        model: LLM model to use
    
    Returns:
        Tuple of (results_dict, total_cost) where results_dict maps
        conv_id -> (synthesized_title, purpose)
    """
    from openhands.sdk import LLM
    
    # Load prompt
    prompt = _load_worklog_prompt()
    
    # Build batch input
    batch_input = []
    for entry in entries_with_context:
        context = entry.get("context", {})
        batch_input.append({
            "id": entry["id"],
            "title": entry.get("title", ""),
            "user_messages": context.get("user_messages", [])[:3],
            "finish_message": context.get("finish_message"),
            "refs": [
                {
                    "type": ref[0],
                    "number": ref[1],
                    "title": ref[2],
                }
                for ref in context.get("refs", [])
            ],
        })
    
    # Call LLM
    llm = LLM.load_from_env(model=model)
    
    try:
        response = llm.complete(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(batch_input, indent=2)},
            ],
            model=model,
            temperature=0.3,  # Lower temp for consistency
        )
        
        # Extract cost
        cost = 0.0
        if hasattr(response, "metrics") and response.metrics:
            cost = getattr(response.metrics, "accumulated_cost", 0.0)
        
        # Parse response
        content = response.choices[0].message.content
        results_list = json.loads(content)
        
        # Build results dict
        results = {}
        for item in results_list:
            conv_id = item["id"]
            synthesized_title = item.get("title", "")
            purpose = item.get("purpose", "")
            results[conv_id] = (synthesized_title, purpose)
        
        return results, cost
    
    except Exception as e:
        log.warning(f"LLM synthesis failed: {e}")
        # Return empty results on error
        return {}, 0.0


def _load_worklog_prompt() -> str:
    """Load the worklog synthesis prompt."""
    from pathlib import Path
    
    # Try to load from package first
    package_prompt = Path(__file__).parent.parent / "prompts" / "worklog" / "default.md"
    if package_prompt.exists():
        return package_prompt.read_text()
    
    # Try user's ~/.ohtv/prompts/worklog/default.md
    from ohtv.config import get_ohtv_dir
    user_prompt = get_ohtv_dir() / "prompts" / "worklog" / "default.md"
    if user_prompt.exists():
        return user_prompt.read_text()
    
    # Fallback inline prompt if file doesn't exist yet
    return """You are a technical assistant helping generate a daily worklog.

For each conversation provided, generate:
1. A concise, action-oriented title (≤50 chars, Title Case, may start with emoji)
2. A 2-3 sentence purpose/outcome summary

Focus on:
- Concrete outcomes (PRs opened, bugs fixed, features implemented)
- Clear problem statements and solutions
- Technical specifics (not generic phrasing like "worked on...")

Output format: JSON array with objects containing "id", "title", and "purpose" fields.

Example:
[
  {
    "id": "abc123",
    "title": "🔧 Fix SSO redirect loop in Canvas integration",
    "purpose": "Resolved authentication redirect loop affecting Canvas SSO users. Root cause was session cookie domain mismatch. Implemented fix with integration test to prevent regression."
  }
]
"""


# =============================================================================
# Main generation function
# =============================================================================


def generate_worklog(
    conn: sqlite3.Connection,
    conversations_base_dir: Path,
    since: date | None = None,
    until: date | None = None,
    engaged_only: bool = False,
    min_engaged_seconds: int = 0,
    source: str | None = None,
    repo_filter: str | None = None,
    synthesis_model: str | None = "gpt-4o-mini",
    timezone_name: str = "America/New_York",
) -> WorklogReport:
    """Generate worklog data structure.
    
    Args:
        conn: Database connection
        conversations_base_dir: Base directory containing conversation subdirs
        since: Start date (inclusive)
        until: End date (inclusive)
        engaged_only: If True, exclude conversations with 0 engagement
        min_engaged_seconds: Minimum engaged time threshold
        source: Filter by source ('local' or 'cloud')
        repo_filter: Filter by selected_repository
        synthesis_model: LLM model for synthesis (None to skip synthesis)
        timezone_name: Timezone for display formatting
    
    Returns:
        WorklogReport with all data ready for rendering
    """
    from zoneinfo import ZoneInfo
    
    # Get timezone
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        log.warning(f"Unknown timezone {timezone_name}, using America/New_York")
        tz = ZoneInfo("America/New_York")
    
    # Query conversations
    conversations = query_conversations_for_worklog(
        conn,
        since=since,
        until=until,
        engaged_only=engaged_only,
        min_engaged_seconds=min_engaged_seconds,
        source=source,
        repo_filter=repo_filter,
    )
    
    log.info(f"Found {len(conversations)} conversations for worklog")
    
    # Build entries
    entries = []
    entries_with_context = []
    
    for conv in conversations:
        # Create entry
        entry = WorklogEntry(
            conversation_id=conv["id"],
            title=conv["title"] or "Untitled conversation",
            created_at=_parse_datetime(conv["created_at"]),
            engaged_seconds=conv["engaged_seconds"],
            engaged_count=conv["engaged_count"],
            first_event_ts=_parse_datetime(conv["first_event_ts"]),
            last_event_ts=_parse_datetime(conv["last_event_ts"]),
        )
        
        # Format engagement display
        if entry.engaged_seconds:
            entry.engagement_display = _format_duration(entry.engaged_seconds)
        else:
            entry.engagement_display = "0 min"
        
        # Format time display (in user's timezone)
        if entry.created_at:
            local_time = entry.created_at.astimezone(tz)
            entry.time_display = local_time.strftime("%I:%M %p %Z")
        else:
            entry.time_display = ""
        
        # Load context and refs if we need synthesis
        conv_dir = conversations_base_dir / conv["id"]
        if synthesis_model and conv_dir.exists():
            context = extract_worklog_context(conv_dir, conv["id"], conn)
            entry.refs = context["refs"]
            
            # Store for batch synthesis
            entries_with_context.append({
                "id": conv["id"],
                "title": entry.title,
                "context": context,
            })
        else:
            # Just load refs without context
            refs_query = """
                SELECT
                    change_type,
                    pr_or_issue_number,
                    title,
                    state,
                    repo_full_name,
                    url
                FROM change_refs
                WHERE conversation_id = ?
                ORDER BY first_mention_idx
            """
            cursor = conn.execute(refs_query, (conv["id"],))
            entry.refs = cursor.fetchall()
        
        entries.append(entry)
    
    # Batch synthesize titles and purposes
    total_cost = 0.0
    if synthesis_model and entries_with_context:
        log.info(f"Synthesizing {len(entries_with_context)} entries with {synthesis_model}")
        results, cost = synthesize_worklog_entries(entries_with_context, synthesis_model)
        total_cost = cost
        
        # Apply synthesis results
        for entry in entries:
            if entry.conversation_id in results:
                synth_title, purpose = results[entry.conversation_id]
                entry.synthesized_title = synth_title
                entry.purpose = purpose
    
    # Build date label
    date_label = _format_date_range(since, until)
    
    # Count engaged conversations
    engaged_count = sum(
        1 for e in entries if e.engaged_seconds and e.engaged_seconds > 0
    )
    
    return WorklogReport(
        date_label=date_label,
        entries=entries,
        total_count=len(entries),
        engaged_count=engaged_count,
        synthesis_cost=total_cost,
    )


# =============================================================================
# Helper functions
# =============================================================================


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse a datetime value from DB."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # Try ISO format
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                # Naive datetime, assume UTC
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


def _format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds} sec"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{hours}h"


def _format_date_range(since: date | None, until: date | None) -> str:
    """Format a date range for display."""
    if since and until:
        if since == until:
            return since.strftime("%Y-%m-%d %A")
        else:
            return f"{since.isoformat()} to {until.isoformat()}"
    elif since:
        return f"Since {since.isoformat()}"
    elif until:
        return f"Until {until.isoformat()}"
    else:
        return "All time"


# =============================================================================
# Rendering functions
# =============================================================================


def render_text(report: WorklogReport) -> str:
    """Render worklog as plain text."""
    lines = []
    
    # Header
    lines.append("=" * 70)
    lines.append(f"📋 Worklog for {report.date_label}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(
        f"{report.total_count} conversations "
        f"({report.engaged_count} with meaningful engagement)"
    )
    lines.append("")
    
    # Entries
    for i, entry in enumerate(report.entries, 1):
        lines.append("-" * 70)
        
        # Use synthesized title if available
        title = entry.synthesized_title or entry.title
        lines.append(f"{i}. {title}")
        
        # Time and engagement
        details = []
        if entry.time_display:
            details.append(entry.time_display)
        if entry.engagement_display:
            details.append(f"Engagement: {entry.engagement_display}")
        if details:
            lines.append("   " + " • ".join(details))
        lines.append("")
        
        # Purpose
        if entry.purpose:
            lines.append(f"   {entry.purpose}")
            lines.append("")
        
        # Outcomes
        if entry.refs:
            lines.append("   Outcomes:")
            for ref in entry.refs:
                change_type, number, title, state, repo, url = ref
                if change_type == "pull_request":
                    badge = "✓" if state in ("closed", "merged") else "→"
                    lines.append(f"   {badge} PR #{number}: {title[:60]}")
                elif change_type == "issue":
                    badge = "✓" if state == "closed" else "→"
                    lines.append(f"   {badge} Issue #{number}: {title[:60]}")
            lines.append("")
    
    lines.append("=" * 70)
    lines.append(
        f"Generated at {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    if report.synthesis_cost > 0:
        lines.append(f"Synthesis cost: ${report.synthesis_cost:.4f}")
    lines.append("")
    
    return "\n".join(lines)


def render_markdown(report: WorklogReport) -> str:
    """Render worklog as markdown."""
    lines = []
    
    # Header
    lines.append(f"# 📋 Worklog for {report.date_label}")
    lines.append("")
    lines.append(
        f"**{report.total_count} conversations** "
        f"({report.engaged_count} engaged)"
    )
    if report.synthesis_cost > 0:
        lines.append(f" • Cost: ${report.synthesis_cost:.4f}")
    lines.append(f" • Generated at {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    
    # Entries
    for i, entry in enumerate(report.entries, 1):
        # Use synthesized title if available
        title = entry.synthesized_title or entry.title
        lines.append(f"## {i}. {title}")
        lines.append("")
        
        # Time and engagement
        details = []
        if entry.time_display:
            details.append(f"**Time:** {entry.time_display}")
        if entry.engagement_display:
            details.append(f"**Engagement:** {entry.engagement_display}")
        if details:
            lines.append(" • ".join(details))
            lines.append("")
        
        # Purpose
        if entry.purpose:
            lines.append(entry.purpose)
            lines.append("")
        
        # Outcomes
        if entry.refs:
            lines.append("**Outcomes:**")
            lines.append("")
            for ref in entry.refs:
                change_type, number, title, state, repo, url = ref
                if change_type == "pull_request":
                    badge = "✓" if state in ("closed", "merged") else "→"
                    if url:
                        lines.append(f"- {badge} [PR #{number}]({url}): {title}")
                    else:
                        lines.append(f"- {badge} PR #{number}: {title}")
                elif change_type == "issue":
                    badge = "✓" if state == "closed" else "→"
                    if url:
                        lines.append(f"- {badge} [Issue #{number}]({url}): {title}")
                    else:
                        lines.append(f"- {badge} Issue #{number}: {title}")
            lines.append("")
    
    return "\n".join(lines)


def render_html(report: WorklogReport) -> str:
    """Render worklog as styled HTML."""
    entries_html = []
    
    for i, entry in enumerate(report.entries, 1):
        # Use synthesized title if available
        title = entry.synthesized_title or entry.title
        
        # Engagement badge color
        if entry.engaged_seconds:
            if entry.engaged_seconds < 300:  # < 5 min
                badge_color = "#6c757d"  # gray
            elif entry.engaged_seconds < 900:  # < 15 min
                badge_color = "#ffc107"  # yellow
            else:
                badge_color = "#28a745"  # green
        else:
            badge_color = "#6c757d"
        
        # Build outcomes HTML
        outcomes_html = ""
        if entry.refs:
            outcomes_html = '<div class="outcomes"><strong>Outcomes:</strong><ul>'
            for ref in entry.refs:
                change_type, number, title_text, state, repo, url = ref
                if change_type == "pull_request":
                    badge = "✓" if state in ("closed", "merged") else "→"
                    if url:
                        outcomes_html += f'<li>{badge} <a href="{url}">PR #{number}</a>: {title_text}</li>'
                    else:
                        outcomes_html += f"<li>{badge} PR #{number}: {title_text}</li>"
                elif change_type == "issue":
                    badge = "✓" if state == "closed" else "→"
                    if url:
                        outcomes_html += f'<li>{badge} <a href="{url}">Issue #{number}</a>: {title_text}</li>'
                    else:
                        outcomes_html += f"<li>{badge} Issue #{number}: {title_text}</li>"
            outcomes_html += "</ul></div>"
        
        # Build entry HTML
        entry_html = f"""
        <div class="entry">
            <div class="entry-header">
                <h3>{i}. {title}</h3>
                <div class="meta">
                    <span class="time">{entry.time_display or 'N/A'}</span>
                    <span class="badge" style="background-color: {badge_color};">
                        {entry.engagement_display}
                    </span>
                </div>
            </div>
            {f'<p class="purpose">{entry.purpose}</p>' if entry.purpose else ''}
            {outcomes_html}
        </div>
        """
        entries_html.append(entry_html)
    
    # Build complete HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Worklog - {report.date_label}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }}
        
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        
        header h1 {{
            font-size: 2em;
            margin-bottom: 10px;
        }}
        
        header .summary {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .content {{
            padding: 40px;
        }}
        
        .entry {{
            margin-bottom: 40px;
            padding-bottom: 30px;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .entry:last-child {{
            border-bottom: none;
        }}
        
        .entry-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
        }}
        
        .entry-header h3 {{
            flex: 1;
            font-size: 1.4em;
            color: #2c3e50;
            margin-right: 20px;
        }}
        
        .meta {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 8px;
            white-space: nowrap;
        }}
        
        .meta .time {{
            font-size: 0.9em;
            color: #666;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            color: white;
            font-size: 0.85em;
            font-weight: 600;
        }}
        
        .purpose {{
            font-size: 1em;
            color: #555;
            line-height: 1.7;
            margin-bottom: 15px;
        }}
        
        .outcomes {{
            margin-top: 15px;
        }}
        
        .outcomes strong {{
            color: #2c3e50;
            display: block;
            margin-bottom: 8px;
        }}
        
        .outcomes ul {{
            list-style: none;
            padding-left: 0;
        }}
        
        .outcomes li {{
            padding: 6px 0;
            color: #555;
        }}
        
        .outcomes a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 500;
        }}
        
        .outcomes a:hover {{
            text-decoration: underline;
        }}
        
        footer {{
            background: #f8f9fa;
            padding: 20px 40px;
            text-align: center;
            font-size: 0.9em;
            color: #666;
            border-top: 1px solid #e0e0e0;
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            
            header, .content, footer {{
                padding: 20px;
            }}
            
            .entry-header {{
                flex-direction: column;
            }}
            
            .meta {{
                align-items: flex-start;
                margin-top: 10px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📋 Worklog for {report.date_label}</h1>
            <div class="summary">
                {report.total_count} conversations ({report.engaged_count} engaged)
                {f' • Cost: ${report.synthesis_cost:.4f}' if report.synthesis_cost > 0 else ''}
            </div>
        </header>
        
        <div class="content">
            {''.join(entries_html)}
        </div>
        
        <footer>
            Generated at {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
        </footer>
    </div>
</body>
</html>
"""
    
    return html
