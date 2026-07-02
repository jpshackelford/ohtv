"""Daily/weekly worklog generation with LLM synthesis.

Generates worklogs showing what was accomplished with:
- LLM-synthesized summaries (not raw quotes)
- PR/issue links with context
- Engagement-based filtering
- Multiple output formats (HTML, markdown, text)

Usage:
    from ohtv.reports.worklog import generate_worklog

    data = generate_worklog(
        since=date(2026, 7, 1),
        until=date(2026, 7, 1),
        engaged_only=True,
        min_engaged_seconds=300
    )
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable

from ohtv.analysis.cache import load_events
from ohtv.analysis.transcript import extract_message_content
from ohtv.config import Config

log = logging.getLogger("ohtv")


# =============================================================================
# Constants
# =============================================================================

#: Default batch size for LLM synthesis (similar to titles.py)
DEFAULT_BATCH_SIZE = 20

#: Default LLM model for synthesis
DEFAULT_SYNTHESIS_MODEL = "gpt-4o-mini"


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class WorklogEntry:
    """A single conversation entry in the worklog.
    
    Attributes:
        conversation_id: Conversation ID (dashless format)
        title: Original conversation title
        created_at: Conversation creation time
        engaged_seconds: Total engaged time (0 for fire-and-forget)
        attention_periods: Number of distinct attention spans
        synthesized_title: LLM-generated concise title (None if synthesis disabled)
        purpose: LLM-generated purpose/outcome summary (None if synthesis disabled)
        outcomes: List of PR/issue outcomes with badges
        user_messages: First few user messages for context
        finish_message: Agent's final finish message
    """
    conversation_id: str
    title: str
    created_at: datetime
    engaged_seconds: int = 0
    attention_periods: int = 0
    synthesized_title: str | None = None
    purpose: str | None = None
    outcomes: list[str] = field(default_factory=list)
    user_messages: list[str] = field(default_factory=list)
    finish_message: str | None = None


@dataclass
class WorklogReport:
    """Complete worklog report data.
    
    Attributes:
        date_range: Human-readable date range string
        since: Start date (inclusive)
        until: End date (inclusive)
        entries: List of worklog entries, sorted by created_at
        total_count: Total conversations in report
        engaged_count: Conversations with meaningful engagement (>60s)
        generated_at: Report generation timestamp
        synthesis_cost: Total LLM synthesis cost (dollars)
    """
    date_range: str
    since: date
    until: date
    entries: list[WorklogEntry]
    total_count: int
    engaged_count: int
    generated_at: datetime
    synthesis_cost: float = 0.0


# =============================================================================
# Database Queries
# =============================================================================


def query_conversations_for_worklog(
    conn: sqlite3.Connection,
    since: date,
    until: date,
    engaged_only: bool = False,
    min_engaged_seconds: int = 0,
    selected_repository: str | None = None,
) -> list[dict]:
    """Query conversations with engagement data for worklog.
    
    Args:
        conn: Database connection
        since: Start date (inclusive)
        until: End date (inclusive)
        engaged_only: Only conversations with engagement > 0
        min_engaged_seconds: Minimum engaged time threshold
        selected_repository: Filter by repository
        
    Returns:
        List of conversation dicts with engagement metrics
    """
    # Convert dates to datetime with timezone
    since_dt = datetime.combine(since, time.min, tzinfo=timezone.utc)
    until_dt = datetime.combine(until, time.max, tzinfo=timezone.utc)
    
    # Build query
    query = """
        SELECT 
            c.id,
            c.title,
            c.created_at,
            c.selected_repository,
            COALESCE(ce.engaged_seconds, 0) AS engaged_seconds,
            COALESCE(ce.attention_periods, 0) AS attention_periods,
            ce.first_event_ts,
            ce.last_event_ts
        FROM conversations c
        LEFT JOIN conversation_engagement ce ON c.id = ce.conversation_id
        WHERE c.created_at >= ? AND c.created_at <= ?
    """
    params = [since_dt.isoformat(), until_dt.isoformat()]
    
    if engaged_only:
        query += " AND ce.engaged_seconds > 0"
    
    if min_engaged_seconds > 0:
        query += " AND ce.engaged_seconds >= ?"
        params.append(min_engaged_seconds)
    
    if selected_repository:
        query += " AND c.selected_repository = ?"
        params.append(selected_repository)
    
    query += " ORDER BY c.created_at ASC"
    
    rows = conn.execute(query, params).fetchall()
    
    return [
        {
            "id": row[0],
            "title": row[1],
            "created_at": datetime.fromisoformat(row[2]) if row[2] else None,
            "selected_repository": row[3],
            "engaged_seconds": row[4],
            "attention_periods": row[5],
            "first_event_ts": row[6],
            "last_event_ts": row[7],
        }
        for row in rows
    ]


def query_refs_for_conversation(
    conn: sqlite3.Connection, conversation_id: str
) -> list[tuple]:
    """Query PR/issue refs for a conversation.
    
    Queries from the refs table via conversation_refs to get PRs and issues
    mentioned in the conversation. Note: The refs table doesn't track state,
    so all refs are returned with state='open'.
    
    Args:
        conn: Database connection
        conversation_id: Conversation ID (dashless)
        
    Returns:
        List of tuples: (change_type, number, title, state, repo, url)
        where change_type is 'pr' or 'issue', number is extracted from fqn,
        and state is always 'open'
    """
    query = """
        SELECT 
            r.ref_type,
            SUBSTR(r.fqn, INSTR(r.fqn, '#') + 1) AS number,
            r.display_name AS title,
            'open' AS state,
            SUBSTR(r.fqn, 1, INSTR(r.fqn, '#') - 1) AS repo,
            r.url
        FROM conversation_refs cr
        JOIN refs r ON r.id = cr.ref_id
        WHERE cr.conversation_id = ?
        ORDER BY r.id
    """
    return conn.execute(query, [conversation_id]).fetchall()


# =============================================================================
# Context Extraction
# =============================================================================


def extract_worklog_context(
    conversation_id: str,
    conn: sqlite3.Connection,
) -> dict:
    """Extract context needed for worklog synthesis.
    
    Args:
        conversation_id: Conversation ID (dashless)
        conn: Database connection
        
    Returns:
        Dict with 'user_messages', 'agent_messages', 'finish_message', 'refs'
    """
    # Find conversation directory
    conv_dir = _find_conversation_dir(conversation_id)
    if not conv_dir:
        log.warning(f"Conversation directory not found: {conversation_id}")
        return {
            "user_messages": [],
            "agent_messages": [],
            "finish_message": None,
            "refs": [],
        }
    
    # Load events
    events = load_events(conv_dir)
    
    # Extract first 5 user messages
    user_messages = []
    for event in events:
        if event.get("kind") == "MessageEvent" and event.get("source") == "user":
            content = extract_message_content(event)
            if content:
                user_messages.append(content)
            if len(user_messages) >= 5:
                break
    
    # Extract last 3 agent messages
    agent_messages = []
    for event in reversed(events):
        if event.get("kind") == "MessageEvent" and event.get("source") == "agent":
            content = extract_message_content(event)
            if content:
                agent_messages.insert(0, content)
            if len(agent_messages) >= 3:
                break
    
    # Get finish message (highest value!)
    finish_msg = None
    for event in reversed(events):
        if event.get("tool_name") == "finish":
            finish_msg = event.get("action", {}).get("message")
            if finish_msg:
                break
    
    # Query refs from database
    refs = query_refs_for_conversation(conn, conversation_id)
    
    return {
        "user_messages": user_messages,
        "agent_messages": agent_messages,
        "finish_message": finish_msg,
        "refs": refs,
    }


def _find_conversation_dir(conversation_id: str) -> Path | None:
    """Find conversation directory in local/cloud sources.
    
    Args:
        conversation_id: Conversation ID (with or without dashes)
        
    Returns:
        Path to conversation directory, or None if not found
    """
    # Normalize ID (remove dashes)
    normalized_id = conversation_id.replace("-", "")
    
    # Load config to get conversation directories
    config = Config.from_env()
    
    # Try local conversations first
    local_dir = config.local_conversations_dir / normalized_id
    if local_dir.exists():
        return local_dir
    
    # Try cloud conversations
    cloud_dir = config.synced_conversations_dir / normalized_id
    if cloud_dir.exists():
        return cloud_dir
    
    return None


# =============================================================================
# Outcome Formatting
# =============================================================================


def format_outcomes(refs: list[tuple]) -> list[str]:
    """Format PR/issue outcomes with state badges.
    
    Args:
        refs: List of tuples (change_type, number, title, state, repo, url)
        
    Returns:
        List of formatted outcome strings with HTML
    """
    outcomes = []
    for ref in refs:
        change_type, number, title, state, repo, url = ref
        
        # Truncate title
        title_display = title[:60] if title and len(title) > 60 else title or "Untitled"
        
        if change_type == "pr":
            # Badge: ✓ for closed/merged, → for open
            badge = "✓" if state in ("closed", "merged") else "→"
            outcomes.append(
                f'{badge} <a href="{html.escape(url or "")}">PR #{number}</a>: {html.escape(title_display)}'
            )
        elif change_type == "issue":
            # Badge: ✓ for closed, → for open
            badge = "✓" if state == "closed" else "→"
            outcomes.append(
                f'{badge} <a href="{html.escape(url or "")}">Issue #{number}</a>: {html.escape(title_display)}'
            )
    
    return outcomes


# =============================================================================
# LLM Synthesis
# =============================================================================


# Type alias for LLM callable (similar to titles.py pattern)
LLMCallable = Callable[[str, str], tuple[str, float]]


def _default_llm_callable(model: str | None) -> LLMCallable:
    """Build an LLM callable backed by OpenHands SDK."""
    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
    
    from openhands.sdk import LLM, Message, TextContent
    
    base = LLM.load_from_env()
    if model:
        llm = LLM(model=model, api_key=base.api_key, base_url=base.base_url)
    else:
        llm = base
    
    def _call(system_prompt: str, user_prompt: str) -> tuple[str, float]:
        messages = [
            Message(role="system", content=[TextContent(type="text", text=system_prompt)]),
            Message(role="user", content=[TextContent(type="text", text=user_prompt)]),
        ]
        response = llm.completion(messages)
        text = ""
        for item in response.message.content:
            if hasattr(item, "text"):
                text += item.text
        cost = response.metrics.accumulated_cost
        return text, cost
    
    return _call


def _load_synthesis_prompt() -> str:
    """Load worklog synthesis prompt from prompts/worklog/synthesis.md."""
    # Load prompt directly from file since worklog is not yet in the prompt family system
    prompt_file = Path(__file__).parent.parent / "prompts" / "worklog" / "synthesis.md"
    if prompt_file.exists():
        return prompt_file.read_text()
    
    # Fallback: inline prompt if file not found
    return """You are a technical worklog assistant. Your job is to synthesize conversation histories into concise, actionable worklog entries.

For each conversation, generate:
1. **Title** (≤50 chars): A clear, imperative statement of what was accomplished. Use Title Case. Optional leading emoji if it adds clarity.
2. **Purpose** (2-3 sentences): A brief outcome summary emphasizing concrete results (PRs opened, bugs fixed, features implemented).

Guidelines:
- Focus on outcomes and deliverables, not process
- Be specific: mention technologies, features, bug types
- Avoid generic phrases like "worked on", "looked into", "explored"
- If PRs/issues are mentioned, incorporate them naturally
- Use past tense for completed work
- Keep it professional but concise

Respond with a JSON array of objects, each with "id", "title", and "purpose" fields."""


def _format_batch_input(entries: list[WorklogEntry], contexts: dict[str, dict]) -> str:
    """Format batch input for LLM synthesis."""
    items = []
    for entry in entries:
        ctx = contexts.get(entry.conversation_id, {})
        refs = ctx.get("refs", [])
        
        item = {
            "id": entry.conversation_id,
            "title": entry.title,
            "user_messages": ctx.get("user_messages", [])[:3],  # First 3 only
            "finish_message": ctx.get("finish_message"),
            "refs": [
                {"type": r[0], "number": r[1], "title": r[2], "state": r[3]}
                for r in refs
            ],
        }
        items.append(item)
    
    return (
        "Synthesize concise worklog entries for the following conversations. "
        "Respond with JSON only.\n\n"
        f"{json.dumps(items, ensure_ascii=False, indent=2)}"
    )


def _parse_synthesis_response(response_text: str) -> dict[str, dict]:
    """Parse LLM synthesis response.
    
    Expected format:
    [
        {
            "id": "conversation_id",
            "title": "Short concise title",
            "purpose": "2-3 sentence outcome summary"
        },
        ...
    ]
    
    Returns:
        Dict mapping conversation_id -> {"title": str, "purpose": str}
    """
    text = response_text.strip()
    
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM response is not valid JSON: {e}") from e
    
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
    
    results = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        conv_id = item.get("id")
        title = item.get("title")
        purpose = item.get("purpose")
        if not isinstance(conv_id, str) or not conv_id.strip():
            continue
        
        results[conv_id.strip()] = {
            "title": title.strip() if isinstance(title, str) else None,
            "purpose": purpose.strip() if isinstance(purpose, str) else None,
        }
    
    return results


def synthesize_worklog_entries(
    entries: list[WorklogEntry],
    contexts: dict[str, dict],
    model: str = DEFAULT_SYNTHESIS_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    llm_call: LLMCallable | None = None,
) -> tuple[dict[str, dict], float]:
    """Batch-synthesize worklog entries using LLM.
    
    Args:
        entries: List of WorklogEntry objects to synthesize
        contexts: Dict mapping conversation_id -> context dict
        model: LLM model to use
        batch_size: Conversations per batch
        llm_call: Optional LLM callable (for testing)
        
    Returns:
        Tuple of (results_dict, total_cost)
        results_dict maps conversation_id -> {"title": str, "purpose": str}
    """
    if not entries:
        return {}, 0.0
    
    if llm_call is None:
        llm_call = _default_llm_callable(model)
    
    system_prompt = _load_synthesis_prompt()
    all_results = {}
    total_cost = 0.0
    
    # Process in batches
    for i in range(0, len(entries), batch_size):
        batch = entries[i : i + batch_size]
        user_prompt = _format_batch_input(batch, contexts)
        
        try:
            response_text, cost = llm_call(system_prompt, user_prompt)
            total_cost += cost
            
            results = _parse_synthesis_response(response_text)
            all_results.update(results)
            
        except (ValueError, json.JSONDecodeError) as e:
            log.warning(f"Failed to parse batch synthesis response: {e}")
            # Fall back to single-conv retry for this batch
            for entry in batch:
                try:
                    single_prompt = _format_batch_input([entry], contexts)
                    response_text, cost = llm_call(system_prompt, single_prompt)
                    total_cost += cost
                    
                    results = _parse_synthesis_response(response_text)
                    all_results.update(results)
                except Exception as retry_err:
                    log.warning(
                        f"Failed to synthesize {entry.conversation_id}: {retry_err}"
                    )
    
    return all_results, total_cost


# =============================================================================
# Core Generation
# =============================================================================


def generate_worklog(
    conn: sqlite3.Connection,
    since: date,
    until: date,
    engaged_only: bool = False,
    min_engaged_seconds: int = 0,
    selected_repository: str | None = None,
    synthesis_model: str | None = None,
    enable_synthesis: bool = True,
) -> WorklogReport:
    """Generate worklog report data.
    
    Args:
        conn: Database connection
        since: Start date (inclusive)
        until: End date (inclusive)
        engaged_only: Only conversations with engagement > 0
        min_engaged_seconds: Minimum engaged time threshold
        selected_repository: Filter by repository
        synthesis_model: LLM model for synthesis (None = default)
        enable_synthesis: Whether to run LLM synthesis
        
    Returns:
        WorklogReport with all entries and metadata
    """
    # Query conversations
    log.info(f"Querying conversations from {since} to {until}")
    conversations = query_conversations_for_worklog(
        conn,
        since=since,
        until=until,
        engaged_only=engaged_only,
        min_engaged_seconds=min_engaged_seconds,
        selected_repository=selected_repository,
    )
    
    if not conversations:
        log.info("No conversations found for worklog")
        return WorklogReport(
            date_range=_format_date_range(since, until),
            since=since,
            until=until,
            entries=[],
            total_count=0,
            engaged_count=0,
            generated_at=datetime.now(timezone.utc),
        )
    
    log.info(f"Found {len(conversations)} conversations")
    
    # Extract context for each conversation
    contexts = {}
    for conv in conversations:
        conv_id = conv["id"]
        contexts[conv_id] = extract_worklog_context(conv_id, conn)
    
    # Create entries
    entries = []
    for conv in conversations:
        conv_id = conv["id"]
        ctx = contexts[conv_id]
        
        entry = WorklogEntry(
            conversation_id=conv_id,
            title=conv["title"] or "Untitled",
            created_at=conv["created_at"],
            engaged_seconds=conv["engaged_seconds"],
            attention_periods=conv["attention_periods"],
            outcomes=format_outcomes(ctx["refs"]),
            user_messages=ctx["user_messages"],
            finish_message=ctx["finish_message"],
        )
        entries.append(entry)
    
    # LLM synthesis
    synthesis_cost = 0.0
    if enable_synthesis and entries:
        log.info(f"Synthesizing {len(entries)} entries with {synthesis_model or DEFAULT_SYNTHESIS_MODEL}")
        results, synthesis_cost = synthesize_worklog_entries(
            entries,
            contexts,
            model=synthesis_model or DEFAULT_SYNTHESIS_MODEL,
        )
        
        # Apply synthesis results
        for entry in entries:
            if entry.conversation_id in results:
                synth = results[entry.conversation_id]
                entry.synthesized_title = synth.get("title")
                entry.purpose = synth.get("purpose")
    
    # Count engaged conversations (>60s)
    engaged_count = sum(1 for e in entries if e.engaged_seconds > 60)
    
    return WorklogReport(
        date_range=_format_date_range(since, until),
        since=since,
        until=until,
        entries=entries,
        total_count=len(entries),
        engaged_count=engaged_count,
        generated_at=datetime.now(timezone.utc),
        synthesis_cost=synthesis_cost,
    )


def _format_date_range(since: date, until: date) -> str:
    """Format date range for display."""
    if since == until:
        return since.strftime("%Y-%m-%d %A")
    return f"{since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}"


# =============================================================================
# Renderers
# =============================================================================


def render_text(report: WorklogReport) -> str:
    """Render worklog as plain text."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"📋 Worklog for {report.date_range}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(
        f"{report.total_count} conversations ({report.engaged_count} with meaningful engagement)"
    )
    lines.append("")
    
    for i, entry in enumerate(report.entries, 1):
        lines.append("-" * 70)
        
        # Title
        title = entry.synthesized_title or entry.title
        lines.append(f"{i}. {title}")
        
        # Time and engagement
        time_str = entry.created_at.strftime("%I:%M %p %Z") if entry.created_at else "Unknown time"
        eng_mins = entry.engaged_seconds // 60
        lines.append(f"   {time_str} • Engagement: {eng_mins} min")
        lines.append("")
        
        # Purpose
        if entry.purpose:
            lines.append(f"   {entry.purpose}")
            lines.append("")
        
        # Outcomes
        if entry.outcomes:
            lines.append("   Outcomes:")
            for outcome in entry.outcomes:
                # Strip HTML tags for text output using regex
                clean_outcome = re.sub(r'<[^>]+>', ' ', outcome).strip()
                # Collapse multiple spaces
                clean_outcome = re.sub(r'\s+', ' ', clean_outcome)
                lines.append(f"   {clean_outcome}")
            lines.append("")
    
    lines.append("=" * 70)
    lines.append(f"Generated at {report.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if report.synthesis_cost > 0:
        lines.append(f"Synthesis cost: ${report.synthesis_cost:.4f}")
    lines.append("=" * 70)
    
    return "\n".join(lines)


def render_markdown(report: WorklogReport) -> str:
    """Render worklog as markdown."""
    lines = []
    lines.append(f"# 📋 Worklog for {report.date_range}")
    lines.append("")
    lines.append(
        f"**{report.total_count} conversations** ({report.engaged_count} engaged) • "
        f"Generated at {report.generated_at.strftime('%Y-%m-%d %H:%M %Z')}"
    )
    lines.append("")
    
    for i, entry in enumerate(report.entries, 1):
        # Title
        title = entry.synthesized_title or entry.title
        lines.append(f"## {i}. {title}")
        lines.append("")
        
        # Time and engagement
        time_str = entry.created_at.strftime("%I:%M %p %Z") if entry.created_at else "Unknown time"
        eng_mins = entry.engaged_seconds // 60
        lines.append(f"**{time_str}** • Engagement: {eng_mins} min")
        lines.append("")
        
        # Purpose
        if entry.purpose:
            lines.append(entry.purpose)
            lines.append("")
        
        # Outcomes
        if entry.outcomes:
            lines.append("**Outcomes:**")
            for outcome in entry.outcomes:
                lines.append(f"- {outcome}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    if report.synthesis_cost > 0:
        lines.append(f"*Synthesis cost: ${report.synthesis_cost:.4f}*")
        lines.append("")
    
    return "\n".join(lines)


def render_html(report: WorklogReport) -> str:
    """Render worklog as HTML with styling."""
    # HTML template with gradient header and card styling
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Worklog - {html.escape(report.date_range)}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            text-align: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}
        .header .meta {{
            font-size: 0.95rem;
            opacity: 0.9;
        }}
        .container {{
            max-width: 900px;
            margin: 2rem auto;
            padding: 0 1rem;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border-left: 4px solid #667eea;
        }}
        .card-title {{
            font-size: 1.3rem;
            font-weight: 600;
            color: #2d3748;
            margin-bottom: 0.5rem;
        }}
        .card-meta {{
            color: #718096;
            font-size: 0.9rem;
            margin-bottom: 1rem;
        }}
        .engagement-badge {{
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 500;
            margin-left: 0.5rem;
        }}
        .engagement-low {{
            background: #e2e8f0;
            color: #4a5568;
        }}
        .engagement-medium {{
            background: #fef3c7;
            color: #92400e;
        }}
        .engagement-high {{
            background: #d1fae5;
            color: #065f46;
        }}
        .purpose {{
            color: #4a5568;
            margin-bottom: 1rem;
            line-height: 1.7;
        }}
        .outcomes {{
            margin-top: 1rem;
        }}
        .outcomes-title {{
            font-weight: 600;
            color: #2d3748;
            margin-bottom: 0.5rem;
        }}
        .outcome {{
            padding: 0.3rem 0;
            color: #4a5568;
        }}
        .outcome a {{
            color: #667eea;
            text-decoration: none;
        }}
        .outcome a:hover {{
            text-decoration: underline;
        }}
        .footer {{
            text-align: center;
            color: #718096;
            font-size: 0.85rem;
            margin: 2rem 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 Worklog for {html.escape(report.date_range)}</h1>
        <div class="meta">
            {report.total_count} conversations ({report.engaged_count} with meaningful engagement) • 
            Generated {report.generated_at.strftime('%Y-%m-%d %H:%M %Z')}
        </div>
    </div>
    
    <div class="container">
"""
    
    # Add each entry as a card
    for i, entry in enumerate(report.entries, 1):
        title = html.escape(entry.synthesized_title or entry.title)
        time_str = entry.created_at.strftime("%I:%M %p %Z") if entry.created_at else "Unknown time"
        eng_mins = entry.engaged_seconds // 60
        
        # Engagement badge color
        if eng_mins < 5:
            badge_class = "engagement-low"
        elif eng_mins < 15:
            badge_class = "engagement-medium"
        else:
            badge_class = "engagement-high"
        
        html_content += f"""
        <div class="card">
            <div class="card-title">{i}. {title}</div>
            <div class="card-meta">
                {time_str}
                <span class="engagement-badge {badge_class}">
                    Engagement: {eng_mins} min
                </span>
            </div>
"""
        
        if entry.purpose:
            html_content += f"""
            <div class="purpose">{html.escape(entry.purpose)}</div>
"""
        
        if entry.outcomes:
            html_content += """
            <div class="outcomes">
                <div class="outcomes-title">Outcomes:</div>
"""
            for outcome in entry.outcomes:
                html_content += f"""
                <div class="outcome">{outcome}</div>
"""
            html_content += """
            </div>
"""
        
        html_content += """
        </div>
"""
    
    # Footer
    html_content += """
    </div>
    
    <div class="footer">
"""
    if report.synthesis_cost > 0:
        html_content += f"""
        Synthesis cost: ${report.synthesis_cost:.4f}
"""
    html_content += """
    </div>
</body>
</html>
"""
    
    return html_content
