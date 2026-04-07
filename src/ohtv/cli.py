"""Command-line interface for ohtv."""

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ohtv.config import Config
from ohtv.logging import setup_logging
from ohtv.sources import ConversationInfo, LocalSource
from ohtv.sync import SyncAbortedError, SyncAuthError, SyncManager, SyncResult

console = Console()

# Minimum datetime for sorting (timezone-aware)
MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def _normalize_datetime_for_sort(dt: datetime | None) -> datetime:
    """Normalize datetime for sorting, handling None and timezone-naive values."""
    if dt is None:
        return MIN_DATETIME
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

# URL patterns for git hosting platforms
GIT_URL_PATTERNS = {
    # GitHub
    "github_pr": re.compile(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/pull/(\d+)"
    ),
    "github_issue": re.compile(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/issues/(\d+)"
    ),
    "github_repo": re.compile(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)(?:/|$|\.git)"
    ),
    # GitLab
    "gitlab_mr": re.compile(
        r"https://gitlab\.com/([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*)/([a-zA-Z0-9_.-]+)/-/merge_requests/(\d+)"
    ),
    "gitlab_issue": re.compile(
        r"https://gitlab\.com/([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*)/([a-zA-Z0-9_.-]+)/-/issues/(\d+)"
    ),
    "gitlab_repo": re.compile(
        r"https://gitlab\.com/([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*)/([a-zA-Z0-9_.-]+)(?:/|$|\.git)"
    ),
    # Bitbucket
    "bitbucket_pr": re.compile(
        r"https://bitbucket\.org/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/pull-requests/(\d+)"
    ),
    "bitbucket_issue": re.compile(
        r"https://bitbucket\.org/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/issues/(\d+)"
    ),
    "bitbucket_repo": re.compile(
        r"https://bitbucket\.org/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)(?:/|$|\.git)"
    ),
}


def _init_logging(verbose: bool = False) -> None:
    """Initialize logging for the CLI."""
    setup_logging(verbose=verbose)


@click.group()
@click.version_option()
def main() -> None:
    """OpenHands Trajectory Viewer - view and sync conversation histories."""


@main.command()
@click.option("--force", "-f", is_flag=True, help="Re-download all conversations")
@click.option("--since", type=click.DateTime(), help="Only sync conversations updated after date")
@click.option("--dry-run", is_flag=True, help="Show what would sync without downloading")
@click.option("--status", "-s", is_flag=True, help="Show sync status")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output for cron jobs")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def sync(
    force: bool,
    since: datetime | None,
    dry_run: bool,
    status: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Sync cloud conversations to local storage."""
    _init_logging(verbose=verbose)

    config = Config.from_env()
    manager = SyncManager(config)

    if status:
        _show_status(manager)
        return

    if not config.api_key:
        _error_no_api_key()
        return

    try:
        result = _run_sync(manager, force, since, dry_run, quiet)
        if not quiet:
            _show_result(result, dry_run)
    except SyncAuthError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        raise SystemExit(1)
    except SyncAbortedError as e:
        console.print(f"[red]Sync aborted:[/red] {e}")
        raise SystemExit(1)


def _show_status(manager: SyncManager) -> None:
    """Display sync status."""
    status = manager.get_status()
    table = Table(title="Cloud Sync Status", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    last_sync = status["last_sync_at"]
    table.add_row("Last sync", _format_time(last_sync) if last_sync else "Never")
    table.add_row("Total synced", f"{status['total_conversations']} conversations")
    table.add_row("Total events", str(status["total_events"]))
    table.add_row("Sync count", str(status["sync_count"]))

    pending = status["pending_retries"]
    if pending > 0:
        table.add_row("Pending retries", f"[red]{pending} failed[/red]")

    console.print(table)


def _error_no_api_key() -> None:
    """Show error for missing API key."""
    console.print("[red]Error:[/red] API key required. Set OH_API_KEY environment variable.")
    raise SystemExit(1)


def _run_sync(
    manager: SyncManager,
    force: bool,
    since: datetime | None,
    dry_run: bool,
    quiet: bool,
) -> SyncResult:
    """Execute sync with progress display."""
    if not quiet:
        _print_sync_header(force, since, dry_run)

    on_progress = None if quiet else _make_progress_callback()
    return manager.sync(force=force, since=since, dry_run=dry_run, on_progress=on_progress)


def _print_sync_header(force: bool, since: datetime | None, dry_run: bool) -> None:
    """Print sync operation header."""
    mode = "[yellow]DRY RUN[/yellow] " if dry_run else ""
    if force:
        console.print(f"{mode}Syncing all cloud conversations (force)...")
    elif since:
        console.print(f"{mode}Syncing conversations since {since.isoformat()}...")
    else:
        console.print(f"{mode}Syncing cloud conversations...")


def _make_progress_callback():
    """Create progress callback for sync."""

    def callback(conv_id: str, title: str, action: str) -> None:
        short_id = conv_id[:7]
        status_style = {"new": "green", "updated": "yellow", "unchanged": "dim", "failed": "red"}
        style = status_style.get(action, "")
        console.print(f"  [{style}]{short_id}[/{style}] {title[:40]}... ({action})")

    return callback


def _show_result(result: SyncResult, dry_run: bool) -> None:
    """Display sync result summary."""
    console.print()
    if dry_run:
        console.print("[yellow]Would sync:[/yellow]")
    else:
        console.print("[green]Sync complete:[/green]")

    console.print(f"  New:       {result.new}")
    console.print(f"  Updated:   {result.updated}")
    console.print(f"  Unchanged: {result.unchanged}")
    if result.failed:
        console.print(f"  [red]Failed:    {result.failed}[/red]")

    if result.errors:
        _show_errors(result.errors)


def _show_errors(errors: list[tuple[str, str]], max_show: int = 5) -> None:
    """Display error details."""
    console.print()
    console.print(f"[red]First {min(len(errors), max_show)} errors:[/red]")
    for conv_id, error in errors[:max_show]:
        console.print(f"  {conv_id[:7]}: {error[:80]}")
    if len(errors) > max_show:
        console.print(f"  ... and {len(errors) - max_show} more")


def _format_time(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


@main.command("list")
@click.option("--reverse", "-r", is_flag=True, help="Show oldest first (default: newest first)")
@click.option("--max", "-n", "limit", type=int, help="Maximum number of conversations to show")
@click.option("--offset", "-k", type=int, default=0, help="Skip first N conversations")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format (default: table)",
)
@click.option("--output", "-o", type=click.Path(), help="Write output to file")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def list_conversations(
    reverse: bool,
    limit: int | None,
    offset: int,
    fmt: str,
    output: str | None,
    verbose: bool,
) -> None:
    """List available conversations from local and cloud sources."""
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Load conversations from both sources
    conversations = _load_all_conversations(config)
    total_count = len(conversations)
    local_count = sum(1 for c in conversations if c.source == "local")
    cloud_count = total_count - local_count

    # Sort by created_at (newest first by default)
    # Use a sort key that handles None and normalizes timezone awareness
    conversations = sorted(
        conversations,
        key=lambda c: _normalize_datetime_for_sort(c.created_at),
        reverse=not reverse,
    )

    # Apply offset and limit
    if offset:
        conversations = conversations[offset:]
    if limit:
        conversations = conversations[:limit]

    # Format output
    output_text = _format_list_output(conversations, fmt, total_count, local_count, cloud_count)

    # Write to file or stdout
    if output:
        Path(output).write_text(output_text)
        console.print(f"[green]Written to {output}[/green]")
    else:
        if fmt == "table":
            # For table format, we use rich console directly
            _print_list_table(conversations, total_count, local_count, cloud_count)
        else:
            # For JSON and CSV, use plain print to avoid rich styling
            print(output_text)


def _load_all_conversations(config: Config) -> list[ConversationInfo]:
    """Load conversations from both local and cloud directories."""
    conversations: list[ConversationInfo] = []

    # Load local conversations
    local_source = LocalSource(config.local_conversations_dir, source_name="local")
    conversations.extend(local_source.list_conversations())

    # Load cloud conversations (synced)
    cloud_source = LocalSource(config.cloud_conversations_dir, source_name="cloud")
    conversations.extend(cloud_source.list_conversations())

    return conversations


def _format_list_output(
    conversations: list[ConversationInfo],
    fmt: str,
    total_count: int,
    local_count: int,
    cloud_count: int,
) -> str:
    """Format conversation list for output."""
    if fmt == "json":
        return _format_list_json(conversations)
    if fmt == "csv":
        return _format_list_csv(conversations)
    # Table format is handled separately with rich
    return ""


def _format_list_json(conversations: list[ConversationInfo]) -> str:
    """Format conversations as JSON."""
    items = []
    for conv in conversations:
        items.append({
            "id": conv.id,
            "source": conv.source,
            "title": conv.title,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            "duration_seconds": conv.duration.total_seconds() if conv.duration else None,
            "event_count": conv.event_count,
            "selected_repository": conv.selected_repository,
        })
    return json.dumps(items, indent=2)


def _format_list_csv(conversations: list[ConversationInfo]) -> str:
    """Format conversations as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "source", "started", "duration", "events", "title", "repository"])

    for conv in conversations:
        writer.writerow([
            conv.id,
            conv.source,
            conv.created_at.strftime("%Y-%m-%d %H:%M") if conv.created_at else "",
            _format_duration(conv.duration) if conv.duration else "",
            conv.event_count or "",
            conv.title or "",
            conv.selected_repository or "",
        ])

    return output.getvalue()


def _print_list_table(
    conversations: list[ConversationInfo],
    total_count: int,
    local_count: int,
    cloud_count: int,
) -> None:
    """Print conversations as a rich table."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", width=7)
    table.add_column("Source", width=6)
    table.add_column("Started", width=16)
    table.add_column("Duration", width=10, justify="right")
    table.add_column("Events", width=6, justify="right")
    table.add_column("Title", no_wrap=False)

    for conv in conversations:
        source_style = "blue" if conv.source == "cloud" else "green"
        table.add_row(
            conv.short_id,
            f"[{source_style}]{conv.source}[/{source_style}]",
            conv.created_at.strftime("%Y-%m-%d %H:%M") if conv.created_at else "",
            _format_duration(conv.duration) if conv.duration else "",
            str(conv.event_count) if conv.event_count else "",
            (conv.title or "")[:60] + ("..." if conv.title and len(conv.title) > 60 else ""),
        )

    console.print(table)

    # Summary line
    showing = len(conversations)
    parts = []
    if cloud_count > 0:
        parts.append(f"{cloud_count} cloud")
    if local_count > 0:
        parts.append(f"{local_count} local")

    summary = f"Showing {showing} of {total_count} conversations"
    if parts:
        summary += f" ({', '.join(parts)})"
    console.print(f"[dim]{summary}[/dim]")


def _format_duration(duration: timedelta | None) -> str:
    """Format a timedelta as a human-readable duration string."""
    if duration is None:
        return ""

    total_seconds = int(duration.total_seconds())
    if total_seconds < 0:
        return ""

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes > 0:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@main.command()
@click.argument("conversation_id")
@click.option("--user-messages", "-u", is_flag=True, help="Include user's messages")
@click.option("--agent-messages", "-a", is_flag=True, help="Include agent's response messages")
@click.option("--finish", "-f", "include_finish", is_flag=True, help="Include finish action message")
@click.option("--action-summaries", "-s", is_flag=True, help="Include brief tool call summaries")
@click.option("--action-details", "-d", is_flag=True, help="Include full tool call details")
@click.option("--outputs", "-O", is_flag=True, help="Include tool call outputs/observations")
@click.option("--thinking", "-t", is_flag=True, help="Include thinking/reasoning blocks")
@click.option("--timestamps", "-T", is_flag=True, help="Include timestamps on events")
@click.option("--all", "-A", "include_all", is_flag=True, help="Include everything")
@click.option("--messages", "-m", is_flag=True, help="Shorthand for -u -a -f")
@click.option("--stats", "-S", is_flag=True, help="Show only statistics, no content")
@click.option("--reverse", "-r", is_flag=True, help="Show newest events first")
@click.option("--max", "-n", "limit", type=int, help="Maximum number of events to show")
@click.option("--offset", "-k", type=int, default=0, help="Skip first N events")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["markdown", "json", "text"]),
    default="markdown",
    help="Output format (default: markdown)",
)
@click.option("--output", "-o", type=click.Path(), help="Write output to file")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def show(
    conversation_id: str,
    user_messages: bool,
    agent_messages: bool,
    include_finish: bool,
    action_summaries: bool,
    action_details: bool,
    outputs: bool,
    thinking: bool,
    timestamps: bool,
    include_all: bool,
    messages: bool,
    stats: bool,
    reverse: bool,
    limit: int | None,
    offset: int,
    fmt: str,
    output: str | None,
    verbose: bool,
) -> None:
    """Show a conversation's content and statistics."""
    _init_logging(verbose=verbose)
    config = Config.from_env()

    conv_dir = _find_conversation_dir(config, conversation_id)
    if not conv_dir:
        console.print(f"[red]Error:[/red] Conversation not found: {conversation_id}")
        raise SystemExit(1)

    # Expand shorthand flags
    if include_all:
        user_messages = agent_messages = include_finish = True
        action_summaries = action_details = outputs = thinking = timestamps = True
    if messages:
        user_messages = agent_messages = include_finish = True

    # Load conversation info
    conv_id, title = _get_conversation_info(conv_dir)

    # Load and count events
    events = _load_events(conv_dir)
    event_counts = _count_events_by_type(events)
    first_ts, last_ts = _get_event_time_range(events)

    # If no content flags specified (and not stats-only), show summary only
    show_content = (
        user_messages or agent_messages or include_finish or
        action_summaries or action_details or outputs or thinking
    )

    # Stats-only mode: show statistics and exit
    if stats or not show_content:
        output_text = _format_show_stats(
            conv_id, title, first_ts, last_ts, event_counts, fmt
        )
        _write_or_print_output(output_text, output, fmt)
        return

    # Filter events based on flags
    filtered_events = _filter_events(
        events,
        user_messages=user_messages,
        agent_messages=agent_messages,
        include_finish=include_finish,
        action_summaries=action_summaries,
        action_details=action_details,
        outputs=outputs,
        thinking=thinking,
    )

    # Sort events (oldest first by default)
    filtered_events = sorted(
        filtered_events,
        key=lambda e: e.get("timestamp", ""),
        reverse=reverse,
    )

    # Apply offset and limit
    if offset:
        filtered_events = filtered_events[offset:]
    if limit:
        filtered_events = filtered_events[:limit]

    # Format output
    output_text = _format_show_output(
        conv_id=conv_id,
        title=title,
        first_ts=first_ts,
        last_ts=last_ts,
        event_counts=event_counts,
        events=filtered_events,
        fmt=fmt,
        timestamps=timestamps,
        action_details=action_details,
        thinking=thinking,
    )

    _write_or_print_output(output_text, output, fmt)


def _write_or_print_output(output_text: str, output_path: str | None, fmt: str) -> None:
    """Write output to file or print to console."""
    if output_path:
        Path(output_path).write_text(output_text)
        console.print(f"[green]Written to {output_path}[/green]")
    elif fmt == "markdown":
        console.print(output_text)
    else:
        print(output_text)


def _load_events(conv_dir: Path) -> list[dict]:
    """Load all events from a conversation directory."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return []

    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
            events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events


def _count_events_by_type(events: list[dict]) -> dict[str, int]:
    """Count events by type."""
    counts: dict[str, int] = {
        "user_messages": 0,
        "agent_messages": 0,
        "actions": 0,
        "observations": 0,
        "finish": 0,
        "other": 0,
    }

    for event in events:
        source = event.get("source", "")
        kind = event.get("kind", "")

        if source == "user" and kind == "MessageEvent":
            counts["user_messages"] += 1
        elif source == "agent":
            if kind == "ActionEvent":
                tool_name = event.get("tool_name", "")
                if tool_name == "finish":
                    counts["finish"] += 1
                else:
                    counts["actions"] += 1
            elif kind == "MessageEvent":
                counts["agent_messages"] += 1
            else:
                counts["other"] += 1
        elif source == "environment" and kind == "ObservationEvent":
            counts["observations"] += 1
        else:
            counts["other"] += 1

    return counts


def _get_event_time_range(events: list[dict]) -> tuple[datetime | None, datetime | None]:
    """Get first and last timestamps from events."""
    if not events:
        return None, None

    timestamps = []
    for event in events:
        ts_str = event.get("timestamp")
        if ts_str:
            ts = _parse_event_datetime(ts_str)
            if ts:
                timestamps.append(ts)

    if not timestamps:
        return None, None

    return min(timestamps), max(timestamps)


def _parse_event_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string from event."""
    if not value:
        return None
    value = value.rstrip("Z")
    if "+" in value:
        value = value.split("+")[0]
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _filter_events(
    events: list[dict],
    user_messages: bool,
    agent_messages: bool,
    include_finish: bool,
    action_summaries: bool,
    action_details: bool,
    outputs: bool,
    thinking: bool,
) -> list[dict]:
    """Filter events based on content flags."""
    include_actions = action_summaries or action_details

    filtered = []
    for event in events:
        source = event.get("source", "")
        kind = event.get("kind", "")

        if source == "user" and kind == "MessageEvent" and user_messages:
            filtered.append(event)
        elif source == "agent":
            if kind == "ActionEvent":
                tool_name = event.get("tool_name", "")
                if tool_name == "finish" and include_finish:
                    filtered.append(event)
                elif tool_name != "finish" and include_actions:
                    filtered.append(event)
            elif kind == "MessageEvent" and agent_messages:
                filtered.append(event)
        elif source == "environment" and kind == "ObservationEvent" and outputs:
            filtered.append(event)

    return filtered


def _format_show_stats(
    conv_id: str,
    title: str | None,
    first_ts: datetime | None,
    last_ts: datetime | None,
    event_counts: dict[str, int],
    fmt: str,
) -> str:
    """Format statistics-only output."""
    duration = (last_ts - first_ts) if (first_ts and last_ts) else None
    total = sum(event_counts.values())

    if fmt == "json":
        return json.dumps({
            "id": conv_id,
            "title": title,
            "started": first_ts.isoformat() if first_ts else None,
            "ended": last_ts.isoformat() if last_ts else None,
            "duration_seconds": duration.total_seconds() if duration else None,
            "counts": event_counts,
            "total_events": total,
        }, indent=2)

    if fmt == "text":
        lines = [
            f"Conversation: {conv_id}",
            f"Title: {title or '(none)'}",
            "",
            f"Started:  {first_ts.strftime('%Y-%m-%d %H:%M:%S') if first_ts else 'N/A'}",
            f"Ended:    {last_ts.strftime('%Y-%m-%d %H:%M:%S') if last_ts else 'N/A'}",
            f"Duration: {_format_duration(duration) if duration else 'N/A'}",
            "",
            "Event Counts:",
            f"  User messages:    {event_counts['user_messages']}",
            f"  Agent messages:   {event_counts['agent_messages']}",
            f"  Actions:          {event_counts['actions']}",
            f"  Observations:     {event_counts['observations']}",
            f"  Finish:           {event_counts['finish']}",
            "  ─────────────────────",
            f"  Total:            {total}",
        ]
        return "\n".join(lines)

    # Markdown format (default)
    lines = [
        f"# Conversation: {conv_id}",
    ]
    if title:
        lines.append(f"**Title:** {title}")
    lines.extend([
        "",
        f"**Started:** {first_ts.strftime('%Y-%m-%d %H:%M:%S') if first_ts else 'N/A'}",
        f"**Ended:** {last_ts.strftime('%Y-%m-%d %H:%M:%S') if last_ts else 'N/A'}",
        f"**Duration:** {_format_duration(duration) if duration else 'N/A'}",
        "",
        "| Type | Count |",
        "|------|-------|",
        f"| User messages | {event_counts['user_messages']} |",
        f"| Agent messages | {event_counts['agent_messages']} |",
        f"| Actions | {event_counts['actions']} |",
        f"| Observations | {event_counts['observations']} |",
        f"| Finish | {event_counts['finish']} |",
        f"| **Total** | **{total}** |",
    ])
    return "\n".join(lines)


def _format_show_output(
    conv_id: str,
    title: str | None,
    first_ts: datetime | None,
    last_ts: datetime | None,
    event_counts: dict[str, int],
    events: list[dict],
    fmt: str,
    timestamps: bool,
    action_details: bool,
    thinking: bool,
) -> str:
    """Format full output with events."""
    if fmt == "json":
        return _format_show_json(conv_id, title, first_ts, last_ts, event_counts, events)

    # For markdown and text formats
    header = _format_show_stats(conv_id, title, first_ts, last_ts, event_counts, fmt)
    separator = "\n---\n\n" if fmt == "markdown" else "\n" + "=" * 60 + "\n\n"

    event_lines = []
    for event in events:
        formatted = _format_event(event, fmt, timestamps, action_details, thinking)
        if formatted:
            event_lines.append(formatted)

    events_text = "\n\n".join(event_lines)
    return header + separator + events_text


def _format_show_json(
    conv_id: str,
    title: str | None,
    first_ts: datetime | None,
    last_ts: datetime | None,
    event_counts: dict[str, int],
    events: list[dict],
) -> str:
    """Format output as JSON."""
    duration = (last_ts - first_ts) if (first_ts and last_ts) else None
    total = sum(event_counts.values())

    formatted_events = []
    for event in events:
        formatted_events.append(_extract_event_data(event))

    return json.dumps({
        "id": conv_id,
        "title": title,
        "started": first_ts.isoformat() if first_ts else None,
        "ended": last_ts.isoformat() if last_ts else None,
        "duration_seconds": duration.total_seconds() if duration else None,
        "counts": event_counts,
        "total_events": total,
        "events": formatted_events,
    }, indent=2)


def _extract_event_data(event: dict) -> dict:
    """Extract relevant data from an event for JSON output."""
    result = {
        "id": event.get("id"),
        "timestamp": event.get("timestamp"),
        "source": event.get("source"),
        "kind": event.get("kind"),
    }

    source = event.get("source", "")
    kind = event.get("kind", "")

    if source == "user" and kind == "MessageEvent":
        result["content"] = _extract_message_content(event)
    elif source == "agent":
        if kind == "ActionEvent":
            result["tool_name"] = event.get("tool_name")
            result["summary"] = event.get("summary")
            result["action"] = event.get("action")
            if event.get("reasoning_content"):
                result["reasoning"] = event.get("reasoning_content")
            if event.get("thinking_blocks"):
                result["thinking_blocks"] = event.get("thinking_blocks")
        elif kind == "MessageEvent":
            result["content"] = _extract_message_content(event)
    elif source == "environment" and kind == "ObservationEvent":
        result["observation"] = _extract_observation_content(event)

    return result


def _extract_message_content(event: dict) -> str:
    """Extract text content from a message event."""
    llm_msg = event.get("llm_message", {})
    content = llm_msg.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    if isinstance(content, str):
        return content

    # Fallback for direct content field
    return event.get("content", "")


def _extract_observation_content(event: dict) -> str:
    """Extract text content from an observation event."""
    obs = event.get("observation", {})
    content = obs.get("content", [])

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    if isinstance(content, str):
        return content

    return ""


def _format_event(
    event: dict,
    fmt: str,
    timestamps: bool,
    action_details: bool,
    thinking: bool,
) -> str:
    """Format a single event for display."""
    source = event.get("source", "")
    kind = event.get("kind", "")
    ts = event.get("timestamp", "")

    lines = []
    ts_prefix = f"[{ts[:19]}] " if timestamps and ts else ""

    if source == "user" and kind == "MessageEvent":
        content = _extract_message_content(event)
        if fmt == "markdown":
            lines.append(f"## {ts_prefix}User")
            lines.append(content)
        else:
            lines.append(f"{ts_prefix}USER:")
            lines.append(content)

    elif source == "agent" and kind == "ActionEvent":
        tool_name = event.get("tool_name", "unknown")
        summary = event.get("summary", "")
        action = event.get("action", {})

        # Thinking/reasoning content
        if thinking:
            reasoning = event.get("reasoning_content", "")
            thinking_blocks = event.get("thinking_blocks", [])
            if reasoning:
                if fmt == "markdown":
                    lines.append(f"### {ts_prefix}Thinking")
                    lines.append(f"> {reasoning}")
                else:
                    lines.append(f"{ts_prefix}THINKING: {reasoning}")
            elif thinking_blocks:
                for block in thinking_blocks:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        if fmt == "markdown":
                            lines.append(f"### {ts_prefix}Thinking")
                            lines.append(f"> {block.get('thinking', '')}")
                        else:
                            lines.append(f"{ts_prefix}THINKING: {block.get('thinking', '')}")

        # Action summary or details
        if fmt == "markdown":
            if action_details:
                lines.append(f"## {ts_prefix}Action: {tool_name}")
                if summary:
                    lines.append(f"*{summary}*")
                lines.append("```json")
                lines.append(json.dumps(action, indent=2))
                lines.append("```")
            else:
                lines.append(f"## {ts_prefix}Action: {tool_name}")
                if summary:
                    lines.append(summary)
        else:
            if action_details:
                lines.append(f"{ts_prefix}ACTION ({tool_name}): {summary}")
                lines.append(json.dumps(action, indent=2))
            else:
                lines.append(f"{ts_prefix}ACTION ({tool_name}): {summary}")

    elif source == "agent" and kind == "MessageEvent":
        content = _extract_message_content(event)
        if fmt == "markdown":
            lines.append(f"## {ts_prefix}Agent")
            lines.append(content)
        else:
            lines.append(f"{ts_prefix}AGENT:")
            lines.append(content)

    elif source == "environment" and kind == "ObservationEvent":
        tool_name = event.get("tool_name", "unknown")
        content = _extract_observation_content(event)
        if fmt == "markdown":
            lines.append(f"## {ts_prefix}Output ({tool_name})")
            lines.append("```")
            lines.append(content[:2000] if len(content) > 2000 else content)
            if len(content) > 2000:
                lines.append(f"... (truncated, {len(content)} chars total)")
            lines.append("```")
        else:
            lines.append(f"{ts_prefix}OUTPUT ({tool_name}):")
            truncated = content[:2000] if len(content) > 2000 else content
            lines.append(truncated)
            if len(content) > 2000:
                lines.append(f"... (truncated, {len(content)} chars total)")

    return "\n".join(lines)


@main.command()
@click.argument("conversation_id")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def refs(conversation_id: str, verbose: bool) -> None:
    """Extract repository, issue, and PR references from a conversation."""
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Search both local and cloud sources
    conv_dir = _find_conversation_dir(config, conversation_id)

    if not conv_dir:
        console.print(f"[red]Error:[/red] Conversation '{conversation_id}' not found")
        raise SystemExit(1)

    # Get conversation metadata
    conv_id, title = _get_conversation_info(conv_dir)
    _display_conversation_header(conv_id, title)

    # Extract references from events
    extracted = _extract_refs_from_conversation(conv_dir)

    if not any(extracted.values()):
        console.print("[dim]No repository references found.[/dim]")
        return

    _display_refs(extracted)


def _find_conversation_dir(config: Config, conv_id: str) -> Path | None:
    """Find conversation directory across both local and cloud sources."""
    # Search both directories
    dirs_to_search = [
        config.local_conversations_dir,
        config.cloud_conversations_dir,
    ]

    all_matches: list[Path] = []

    for base_dir in dirs_to_search:
        if not base_dir.exists():
            continue

        # Try exact match first
        exact = base_dir / conv_id
        if exact.exists():
            return exact

        # Collect prefix matches
        matches = [d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith(conv_id)]
        all_matches.extend(matches)

    if len(all_matches) == 1:
        return all_matches[0]
    if len(all_matches) > 1:
        console.print(f"[yellow]Ambiguous ID:[/yellow] {len(all_matches)} matches. Provide more characters.")
        for m in all_matches[:5]:
            console.print(f"  {m.name}")
        return None

    return None


def _get_conversation_info(conv_dir: Path) -> tuple[str, str]:
    """Get conversation ID and title from metadata or first user message."""
    conv_id = conv_dir.name
    title = ""

    # Try to get title from base_state.json
    base_state = conv_dir / "base_state.json"
    if base_state.exists():
        try:
            data = json.loads(base_state.read_text())
            title = data.get("title", "")
            if data.get("id"):
                conv_id = data["id"]
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: extract title from first user message
    if not title:
        title = _get_title_from_first_user_message(conv_dir)

    return conv_id, title


def _get_title_from_first_user_message(conv_dir: Path, max_length: int = 60) -> str:
    """Extract title from the first user message in conversation."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return ""

    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
            if data.get("source") != "user":
                continue

            # Try llm_message.content[].text format (cloud)
            llm_msg = data.get("llm_message", {})
            content = llm_msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        return _truncate_title(text, max_length)

            # Try direct content field (local CLI format)
            if data.get("content"):
                return _truncate_title(data["content"], max_length)

        except (json.JSONDecodeError, OSError):
            continue

    return ""


def _truncate_title(text: str, max_length: int) -> str:
    """Truncate text to max_length, breaking at word boundary."""
    # Take first line only
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_length:
        return first_line
    # Break at word boundary
    truncated = first_line[:max_length].rsplit(" ", 1)[0]
    return truncated + "..."


def _display_conversation_header(conv_id: str, title: str) -> None:
    """Display conversation title and ID."""
    if title:
        console.print(f"[bold]{title}[/bold]")
    console.print(f"[dim]{conv_id}[/dim]")


def _extract_refs_from_conversation(conv_dir: Path) -> dict[str, set[str]]:
    """Extract all git references from conversation events."""
    refs: dict[str, set[str]] = {
        "repos": set(),
        "issues": set(),
        "prs": set(),
    }

    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return refs

    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            content = event_file.read_text()
            _extract_refs_from_text(content, refs)
        except (json.JSONDecodeError, OSError):
            continue

    return refs


def _extract_refs_from_text(text: str, refs: dict[str, set[str]]) -> None:
    """Extract git URLs from text and categorize them."""
    # Extract PRs/MRs first (most specific)
    for pattern_name in ["github_pr", "gitlab_mr", "bitbucket_pr"]:
        for match in GIT_URL_PATTERNS[pattern_name].finditer(text):
            url = _normalize_url(match.group(0), pattern_name)
            if url and _is_real_ref(url):
                refs["prs"].add(url)

    # Extract issues
    for pattern_name in ["github_issue", "gitlab_issue", "bitbucket_issue"]:
        for match in GIT_URL_PATTERNS[pattern_name].finditer(text):
            url = _normalize_url(match.group(0), pattern_name)
            if url and _is_real_ref(url):
                refs["issues"].add(url)

    # Extract repos (excluding template patterns and API URLs)
    for pattern_name in ["github_repo", "gitlab_repo", "bitbucket_repo"]:
        for match in GIT_URL_PATTERNS[pattern_name].finditer(text):
            # Skip if this is part of a PR or issue URL
            full_url = match.group(0)
            if "/pull/" in text[match.start():match.end()+20] or "/issues/" in text[match.start():match.end()+20]:
                continue
            url = _normalize_repo_url(match)
            if url and _is_real_ref(url):
                refs["repos"].add(url)


def _normalize_url(url: str, pattern_name: str) -> str:
    """Clean up URL, removing trailing characters."""
    # Remove trailing punctuation that might have been captured
    url = url.rstrip(".,;:)]}>")
    # Remove markdown link artifacts
    if "](" in url:
        url = url.split("](")[0]
    return url


def _normalize_repo_url(match: re.Match) -> str:
    """Build a clean repo URL from match groups."""
    full = match.group(0)
    # Remove .git suffix and trailing slash
    url = full.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # Remove any trailing path components for repo-only URL
    parts = url.split("/")
    # Keep https://github.com/owner/repo
    if "github.com" in url or "bitbucket.org" in url:
        if len(parts) >= 5:
            url = "/".join(parts[:5])
    elif "gitlab.com" in url:
        # GitLab may have nested groups
        if len(parts) >= 5:
            url = "/".join(parts[:5])
    return url


def _is_real_ref(url: str) -> bool:
    """Check if URL is a real reference (not a template or placeholder)."""
    # Skip template patterns
    template_indicators = [
        "{", "}", "...", "example", "username", "repo.git",
        "/user/", "/owner/", "/repo/", "/your-", "/my-",
    ]
    url_lower = url.lower()
    if any(t in url_lower for t in template_indicators):
        return False
    # Skip common placeholder names
    placeholder_patterns = [
        r"/USER/", r"/OWNER/", r"/REPO$", r"/REPO/",
        r"/user/repo", r"/owner/repo", r"/your-repo",
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return False
    # Skip API URLs
    if "api.github.com" in url:
        return False
    return True


def _display_refs(refs: dict[str, set[str]]) -> None:
    """Display extracted references organized by category."""
    categories = [
        ("Repositories", "repos", "blue"),
        ("Issues", "issues", "yellow"),
        ("Pull Requests / Merge Requests", "prs", "green"),
    ]

    for title, key, color in categories:
        urls = sorted(refs[key])
        if urls:
            console.print(f"\n[bold {color}]{title}[/bold {color}]")
            for url in urls:
                console.print(f"  • {url}")


if __name__ == "__main__":
    main()
