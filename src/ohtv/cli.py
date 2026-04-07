"""Command-line interface for ohtv."""

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from click import Context, HelpFormatter
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from ohtv.config import Config


# Commands that use LLM and consume tokens
LLM_COMMANDS = {"objectives"}


class SectionedGroup(click.Group):
    """Custom Click group that separates commands into sections based on LLM usage."""

    def format_commands(self, ctx: Context, formatter: HelpFormatter) -> None:
        """Format commands into separate sections for LLM and non-LLM commands."""
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands.append((subcommand, cmd))

        if not commands:
            return

        limit = formatter.width - 6 - max(len(cmd[0]) for cmd in commands)

        # Separate into LLM and non-LLM commands
        standard_commands = []
        llm_commands = []

        for subcommand, cmd in commands:
            help_text = cmd.get_short_help_str(limit)
            if subcommand in LLM_COMMANDS:
                llm_commands.append((subcommand, help_text))
            else:
                standard_commands.append((subcommand, help_text))

        # Write standard commands first
        if standard_commands:
            with formatter.section("Commands"):
                formatter.write_dl(standard_commands)

        # Write LLM commands in separate section
        if llm_commands:
            with formatter.section("Analysis Commands (require LLM, consume tokens)"):
                formatter.write_dl(llm_commands)


from ohtv.logging import setup_logging
from ohtv.sources import ConversationInfo, LocalSource
from ohtv.sync import SyncAbortedError, SyncAuthError, SyncManager, SyncResult

console = Console()

# Minimum datetime for sorting (timezone-aware)
MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


# =============================================================================
# Interaction Detection Types and Patterns
# =============================================================================

# Interaction types for each ref category
REPO_INTERACTIONS = {"cloned", "pushed"}
PR_INTERACTIONS = {"created", "pushed", "commented", "merged", "closed", "reviewed"}
ISSUE_INTERACTIONS = {"created", "commented", "closed"}

# Command patterns to detect interactions
INTERACTION_COMMAND_PATTERNS = {
    "git_push": re.compile(r"git\s+push"),
    "git_clone": re.compile(r"git\s+clone"),
    "gh_pr_create": re.compile(r"gh\s+pr\s+create"),
    "gh_pr_comment": re.compile(r"gh\s+pr\s+comment\s+(\d+)"),
    "gh_pr_review": re.compile(r"gh\s+pr\s+review\s+(\d+)"),
    "gh_pr_merge": re.compile(r"gh\s+pr\s+merge\s+(\d+)"),
    "gh_pr_close": re.compile(r"gh\s+pr\s+close\s+(\d+)"),
    "gh_issue_create": re.compile(r"gh\s+issue\s+create"),
    "gh_issue_comment": re.compile(r"gh\s+issue\s+comment\s+(\d+)"),
    "gh_issue_close": re.compile(r"gh\s+issue\s+close\s+(\d+)"),
}

# Patterns to extract repo/PR/issue from commands and outputs
REPO_FLAG_PATTERN = re.compile(r"--repo\s+([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)")
PR_NUMBER_PATTERN = re.compile(r"gh\s+pr\s+(?:view|comment|review|merge|close|checks|diff)\s+(\d+)")
ISSUE_NUMBER_PATTERN = re.compile(r"gh\s+issue\s+(?:view|comment|close)\s+(\d+)")

# Output patterns for extraction
OUTPUT_REPO_PATTERN = re.compile(r"To\s+https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)(?:\.git)?")
OUTPUT_PR_PATTERN = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/pull/(\d+)")
OUTPUT_ISSUE_PATTERN = re.compile(r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/issues/(\d+)")
MERGE_SUCCESS_PATTERN = re.compile(r"✓\s+(?:Squashed and merged|Merged|Rebased and merged)\s+pull request\s+([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)#(\d+)")
CLONE_URL_PATTERN = re.compile(r"git\s+clone\s+(?:--[a-z-]+\s+)*(?:https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)|git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+))")

# Map command patterns to interaction types
PATTERN_TO_INTERACTION = {
    "git_push": ("repo", "pushed"),
    "git_clone": ("repo", "cloned"),
    "gh_pr_create": ("pr", "created"),
    "gh_pr_comment": ("pr", "commented"),
    "gh_pr_review": ("pr", "reviewed"),
    "gh_pr_merge": ("pr", "merged"),
    "gh_pr_close": ("pr", "closed"),
    "gh_issue_create": ("issue", "created"),
    "gh_issue_comment": ("issue", "commented"),
    "gh_issue_close": ("issue", "closed"),
}


@dataclass
class ExtractedRef:
    """A reference extracted from a command."""
    ref_type: str  # "repo", "pr", "issue"
    owner: str | None
    repo: str | None
    number: int | None  # PR or issue number
    url: str | None  # Constructed URL if possible


@dataclass
class RefInteractions:
    """Tracks interactions for all refs in a conversation."""
    repos: dict[str, set[str]] = field(default_factory=dict)  # url -> set of interactions
    prs: dict[str, set[str]] = field(default_factory=dict)
    issues: dict[str, set[str]] = field(default_factory=dict)


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


@click.group(cls=SectionedGroup)
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
@click.option("--max", "-n", "limit", type=int, help="Maximum conversations to show (default: 10)")
@click.option("--all", "-A", "show_all", is_flag=True, help="Show all conversations (no limit)")
@click.option("--offset", "-k", type=int, default=0, help="Skip first N conversations")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format (default: table)",
)
@click.option("--output", "-o", type=click.Path(), help="Write output to file")
@click.option("--include-empty", "-e", is_flag=True, help="Include conversations with no events")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def list_conversations(
    reverse: bool,
    limit: int | None,
    show_all: bool,
    offset: int,
    fmt: str,
    output: str | None,
    include_empty: bool,
    verbose: bool,
) -> None:
    """List available conversations from local and cloud sources."""
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Load conversations from both sources
    conversations = _load_all_conversations(config)

    # Filter out empty conversations (0 events) unless --include-empty
    if not include_empty:
        conversations = [c for c in conversations if c.event_count > 0]

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
    # Default to 10 unless --all or explicit -n is provided
    if offset:
        conversations = conversations[offset:]
    if not show_all:
        effective_limit = limit if limit is not None else 10
        conversations = conversations[:effective_limit]

    # Track if we're using default limit (for hint message)
    using_default_limit = not show_all and limit is None

    # Format output
    output_text = _format_list_output(conversations, fmt, total_count, local_count, cloud_count)

    # Write to file or stdout
    if output:
        Path(output).write_text(output_text)
        console.print(f"[green]Written to {output}[/green]")
    else:
        if fmt == "table":
            # For table format, we use rich console directly
            _print_list_table(
                conversations, total_count, local_count, cloud_count,
                show_hint=using_default_limit and len(conversations) < total_count,
            )
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
        # Convert UTC to local time for display
        started = ""
        if conv.created_at:
            local_time = conv.created_at.astimezone()
            started = local_time.strftime("%Y-%m-%d %H:%M")
        writer.writerow([
            conv.id,
            conv.source,
            started,
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
    *,
    show_hint: bool = False,
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
        # Convert UTC to local time for display
        started = ""
        if conv.created_at:
            local_time = conv.created_at.astimezone()
            started = local_time.strftime("%Y-%m-%d %H:%M")
        table.add_row(
            conv.short_id,
            f"[{source_style}]{conv.source}[/{source_style}]",
            started,
            _format_duration(conv.duration) if conv.duration else "",
            str(conv.event_count),
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

    # Hint for default limit
    if show_hint:
        console.print("[dim]Use -A to show all, or -n to change limit[/dim]")


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
@click.option("--refs", "-R", "show_refs", is_flag=True, help="Show git refs with write actions")
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
    show_refs: bool,
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

    result = _find_conversation_dir(config, conversation_id)
    if not result:
        console.print(f"[red]Error:[/red] Conversation not found: {conversation_id}")
        raise SystemExit(1)
    conv_dir, is_cloud = result

    # Expand shorthand flags
    if include_all:
        user_messages = agent_messages = include_finish = True
        action_summaries = action_details = outputs = thinking = timestamps = True
        show_refs = True
    if messages:
        user_messages = agent_messages = include_finish = True

    # Load conversation info
    conv_id, title = _get_conversation_info(conv_dir)

    # Load and count events
    events = _load_events(conv_dir)
    event_counts = _count_events_by_type(events)
    first_ts, last_ts = _get_event_time_range(events, is_cloud=is_cloud)

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
        # Show refs after stats if requested
        if show_refs:
            _show_refs_summary(conv_dir)
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

    # Show refs after main output if requested
    if show_refs:
        _show_refs_summary(conv_dir)


def _show_refs_summary(conv_dir: Path) -> None:
    """Show refs with write actions as a summary section."""
    extracted = _extract_refs_from_conversation(conv_dir)
    if not any(extracted.values()):
        return

    interactions = _detect_interactions_from_conversation(conv_dir, extracted)
    _display_actions_only(interactions)


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


def _get_event_time_range(events: list[dict], is_cloud: bool = True) -> tuple[datetime | None, datetime | None]:
    """Get first and last timestamps from events.

    Args:
        events: List of event dictionaries
        is_cloud: If True, timestamps are in UTC. If False, in local time.
    """
    if not events:
        return None, None

    timestamps = []
    for event in events:
        ts_str = event.get("timestamp")
        if ts_str:
            ts = _parse_event_datetime(ts_str, assume_utc=is_cloud)
            if ts:
                timestamps.append(ts)

    if not timestamps:
        return None, None

    return min(timestamps), max(timestamps)


def _parse_event_datetime(value: str | None, assume_utc: bool = True) -> datetime | None:
    """Parse ISO 8601 datetime string from event.

    Args:
        value: ISO 8601 datetime string
        assume_utc: If True, treat naive timestamps as UTC.
                    If False, treat as local time and convert to UTC.
    """
    if not value:
        return None
    value = value.rstrip("Z")
    if "+" in value:
        value = value.split("+")[0]
    try:
        naive_dt = datetime.fromisoformat(value)
        if assume_utc:
            return naive_dt.replace(tzinfo=timezone.utc)
        # Treat as local time, then convert to UTC
        local_dt = naive_dt.astimezone()  # Attach local timezone
        return local_dt.astimezone(timezone.utc)
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

    # Convert to local time for display
    started_str = first_ts.astimezone().strftime('%Y-%m-%d %H:%M:%S') if first_ts else 'N/A'
    ended_str = last_ts.astimezone().strftime('%Y-%m-%d %H:%M:%S') if last_ts else 'N/A'

    if fmt == "text":
        lines = [
            f"Conversation: {conv_id}",
            f"Title: {title or '(none)'}",
            "",
            f"Started:  {started_str}",
            f"Ended:    {ended_str}",
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
        f"**Started:** {started_str}",
        f"**Ended:** {ended_str}",
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
@click.option("--actions", "-a", is_flag=True, help="Show only refs with write actions (created, pushed, etc.)")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def refs(conversation_id: str, actions: bool, verbose: bool) -> None:
    """Extract repository, issue, and PR references from a conversation.

    Shows what actions were taken on each reference:
    - Repositories: cloned, pushed
    - Pull Requests: created, pushed, commented, merged, closed, reviewed
    - Issues: created, commented, closed

    References without detected interactions are shown without annotation.
    Use --actions to show only refs where write actions were detected.
    """
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Search both local and cloud sources
    result = _find_conversation_dir(config, conversation_id)

    if not result:
        console.print(f"[red]Error:[/red] Conversation '{conversation_id}' not found")
        raise SystemExit(1)
    conv_dir, _ = result  # We don't need is_cloud for refs

    # Get conversation metadata
    conv_id, title = _get_conversation_info(conv_dir)
    _display_conversation_header(conv_id, title)

    # Extract references from events
    extracted = _extract_refs_from_conversation(conv_dir)

    if not any(extracted.values()):
        console.print("[dim]No repository references found.[/dim]")
        return

    # Detect interactions for each ref
    interactions = _detect_interactions_from_conversation(conv_dir, extracted)

    # Show only actions summary if requested
    if actions:
        _display_actions_only(interactions)
    else:
        _display_refs(extracted, interactions)


@main.command()
@click.argument("conversation_id")
@click.option("--refresh", "-r", is_flag=True, help="Force re-analysis (ignore cache)")
@click.option("--model", "-m", help="LLM model to use for analysis")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def objectives(
    conversation_id: str,
    refresh: bool,
    model: str | None,
    json_output: bool,
    verbose: bool,
) -> None:
    """Analyze user objectives in a conversation.

    Uses an LLM to extract and categorize the user's primary and subordinate
    objectives from the conversation. Results are cached for quick subsequent
    lookups.

    Requires LLM_API_KEY environment variable to be set.
    """
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Find conversation
    result = _find_conversation_dir(config, conversation_id)
    if not result:
        console.print(f"[red]Error:[/red] Conversation '{conversation_id}' not found")
        raise SystemExit(1)

    conv_dir, _ = result

    # Get conversation metadata for display
    conv_id, title = _get_conversation_info(conv_dir)

    # Import analysis module (lazy to avoid loading SDK unless needed)
    try:
        from ohtv.analysis import ObjectiveAnalysis, analyze_objectives, get_cached_analysis
    except ImportError as e:
        console.print(f"[red]Error:[/red] Analysis module not available: {e}")
        raise SystemExit(1)

    # Check for cached analysis first if not refreshing
    if not refresh:
        cached = get_cached_analysis(conv_dir)
        if cached:
            if json_output:
                console.print(cached.model_dump_json(indent=2))
            else:
                _display_objectives(conv_id, title, cached)
            return

    # Run analysis
    try:
        analysis = analyze_objectives(conv_dir, model=model, force_refresh=refresh)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
    except RuntimeError as e:
        console.print(f"[red]Analysis failed:[/red] {e}")
        raise SystemExit(1)
    except Exception as e:
        # Catch LLM configuration errors
        if "api_key" in str(e).lower() or "LLM_" in str(e):
            console.print(
                "[red]Error:[/red] LLM not configured. Set LLM_API_KEY environment variable."
            )
            console.print("[dim]Hint: export LLM_API_KEY=your-api-key[/dim]")
        else:
            console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if json_output:
        console.print(analysis.model_dump_json(indent=2))
    else:
        _display_objectives(conv_id, title, analysis)


def _display_objectives(conv_id: str, title: str, analysis: "ObjectiveAnalysis") -> None:
    """Display objective analysis with rich formatting."""
    from ohtv.analysis import Objective, ObjectiveStatus

    # Header
    _display_conversation_header(conv_id, title)

    # Summary
    if analysis.summary:
        console.print(f"\n[bold]Summary:[/bold] {analysis.summary}")

    # Status colors
    status_colors = {
        ObjectiveStatus.ACHIEVED: "green",
        ObjectiveStatus.PARTIALLY_ACHIEVED: "yellow",
        ObjectiveStatus.NOT_ACHIEVED: "red",
        ObjectiveStatus.IN_PROGRESS: "blue",
        ObjectiveStatus.UNCLEAR: "dim",
    }

    status_icons = {
        ObjectiveStatus.ACHIEVED: "✓",
        ObjectiveStatus.PARTIALLY_ACHIEVED: "◐",
        ObjectiveStatus.NOT_ACHIEVED: "✗",
        ObjectiveStatus.IN_PROGRESS: "→",
        ObjectiveStatus.UNCLEAR: "?",
    }

    def add_objective_to_tree(tree: Tree, obj: Objective, level: int = 0) -> None:
        """Recursively add objectives to tree."""
        color = status_colors.get(obj.status, "white")
        icon = status_icons.get(obj.status, "•")

        # Format the objective
        status_label = obj.status.value.replace("_", " ").title()
        text = f"[{color}]{icon}[/{color}] {obj.description} [{color}][{status_label}][/{color}]"

        # Add evidence if present
        if obj.evidence:
            text += f"\n   [dim]Evidence: {obj.evidence[:100]}{'...' if len(obj.evidence) > 100 else ''}[/dim]"

        branch = tree.add(text)

        # Add subordinates
        for sub in obj.subordinates:
            add_objective_to_tree(branch, sub, level + 1)

    # Build and display tree
    if analysis.primary_objectives:
        console.print("\n[bold]Objectives:[/bold]")
        tree = Tree("[bold]Primary Objectives[/bold]")
        for obj in analysis.primary_objectives:
            add_objective_to_tree(tree, obj)
        console.print(tree)
    else:
        console.print("\n[dim]No objectives identified.[/dim]")

    # Footer with metadata
    console.print(
        f"\n[dim]Analyzed: {analysis.analyzed_at.strftime('%Y-%m-%d %H:%M')} UTC • Model: {analysis.model_used}[/dim]"
    )


def _find_conversation_dir(config: Config, conv_id: str) -> tuple[Path, bool] | None:
    """Find conversation directory across both local and cloud sources.

    Returns:
        Tuple of (directory_path, is_cloud_source) or None if not found
    """
    # Search both directories - local first, then cloud
    dirs_to_search = [
        (config.local_conversations_dir, False),  # (path, is_cloud)
        (config.cloud_conversations_dir, True),
    ]

    all_matches: list[tuple[Path, bool]] = []

    for base_dir, is_cloud in dirs_to_search:
        if not base_dir.exists():
            continue

        # Try exact match first
        exact = base_dir / conv_id
        if exact.exists():
            return (exact, is_cloud)

        # Collect prefix matches
        matches = [(d, is_cloud) for d in base_dir.iterdir() if d.is_dir() and d.name.startswith(conv_id)]
        all_matches.extend(matches)

    if len(all_matches) == 1:
        return all_matches[0]
    if len(all_matches) > 1:
        console.print(f"[yellow]Ambiguous ID:[/yellow] {len(all_matches)} matches. Provide more characters.")
        for m, _ in all_matches[:5]:
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


# =============================================================================
# Interaction Detection Functions
# =============================================================================


def _normalize_ref_url(url: str) -> str:
    """Normalize a URL for comparison (remove .git suffix, trailing slashes)."""
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def _extract_ref_from_command(command: str, output: str, pattern_type: str) -> ExtractedRef | None:
    """Extract the target ref from a command and its output."""
    # First, try to get repo from --repo flag (most reliable for gh commands)
    repo_match = REPO_FLAG_PATTERN.search(command)
    owner, repo = (repo_match.group(1), repo_match.group(2)) if repo_match else (None, None)

    # For PR commands, extract number
    if pattern_type in ("gh_pr_comment", "gh_pr_review", "gh_pr_merge", "gh_pr_close"):
        num_match = PR_NUMBER_PATTERN.search(command)
        if num_match:
            number = int(num_match.group(1))
            if owner and repo:
                return ExtractedRef(
                    ref_type="pr",
                    owner=owner,
                    repo=repo,
                    number=number,
                    url=f"https://github.com/{owner}/{repo}/pull/{number}",
                )
            # Try to get repo from output
            pr_url_match = OUTPUT_PR_PATTERN.search(output)
            if pr_url_match:
                return ExtractedRef(
                    ref_type="pr",
                    owner=pr_url_match.group(1),
                    repo=pr_url_match.group(2),
                    number=int(pr_url_match.group(3)),
                    url=f"https://github.com/{pr_url_match.group(1)}/{pr_url_match.group(2)}/pull/{pr_url_match.group(3)}",
                )
        # Check merge success pattern
        if pattern_type == "gh_pr_merge":
            merge_match = MERGE_SUCCESS_PATTERN.search(output)
            if merge_match:
                return ExtractedRef(
                    ref_type="pr",
                    owner=merge_match.group(1),
                    repo=merge_match.group(2),
                    number=int(merge_match.group(3)),
                    url=f"https://github.com/{merge_match.group(1)}/{merge_match.group(2)}/pull/{merge_match.group(3)}",
                )

    # For issue commands
    if pattern_type in ("gh_issue_comment", "gh_issue_close"):
        num_match = ISSUE_NUMBER_PATTERN.search(command)
        if num_match:
            number = int(num_match.group(1))
            if owner and repo:
                return ExtractedRef(
                    ref_type="issue",
                    owner=owner,
                    repo=repo,
                    number=number,
                    url=f"https://github.com/{owner}/{repo}/issues/{number}",
                )

    # For gh pr create - look for created PR URL in output
    if pattern_type == "gh_pr_create":
        pr_url_match = OUTPUT_PR_PATTERN.search(output)
        if pr_url_match:
            return ExtractedRef(
                ref_type="pr",
                owner=pr_url_match.group(1),
                repo=pr_url_match.group(2),
                number=int(pr_url_match.group(3)),
                url=f"https://github.com/{pr_url_match.group(1)}/{pr_url_match.group(2)}/pull/{pr_url_match.group(3)}",
            )

    # For gh issue create - look for created issue URL in output
    if pattern_type == "gh_issue_create":
        issue_url_match = OUTPUT_ISSUE_PATTERN.search(output)
        if issue_url_match:
            return ExtractedRef(
                ref_type="issue",
                owner=issue_url_match.group(1),
                repo=issue_url_match.group(2),
                number=int(issue_url_match.group(3)),
                url=f"https://github.com/{issue_url_match.group(1)}/{issue_url_match.group(2)}/issues/{issue_url_match.group(3)}",
            )

    # For git push - extract repo from output
    if pattern_type == "git_push":
        repo_match = OUTPUT_REPO_PATTERN.search(output)
        if repo_match:
            return ExtractedRef(
                ref_type="repo",
                owner=repo_match.group(1),
                repo=repo_match.group(2),
                number=None,
                url=f"https://github.com/{repo_match.group(1)}/{repo_match.group(2)}",
            )

    # For git clone - extract repo from command
    if pattern_type == "git_clone":
        clone_match = CLONE_URL_PATTERN.search(command)
        if clone_match:
            # Groups 1,2 for https, groups 3,4 for ssh
            owner = clone_match.group(1) or clone_match.group(3)
            repo = clone_match.group(2) or clone_match.group(4)
            if owner and repo:
                # Remove .git suffix from repo name
                if repo.endswith(".git"):
                    repo = repo[:-4]
                return ExtractedRef(
                    ref_type="repo",
                    owner=owner,
                    repo=repo,
                    number=None,
                    url=f"https://github.com/{owner}/{repo}",
                )

    return None


def _detect_interactions_from_conversation(conv_dir: Path, refs: dict[str, set[str]]) -> RefInteractions:
    """Detect interactions from conversation events and match to refs.

    Scans terminal actions for interaction patterns (git push, gh pr comment, etc.)
    and correlates successful commands with the refs found in the conversation.
    """
    interactions = RefInteractions()
    events_dir = conv_dir / "events"

    if not events_dir.exists():
        return interactions

    # Normalize all refs for matching
    norm_repos = {_normalize_ref_url(url): url for url in refs["repos"]}
    norm_prs = {_normalize_ref_url(url): url for url in refs["prs"]}
    norm_issues = {_normalize_ref_url(url): url for url in refs["issues"]}

    # Load all events
    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            event = json.loads(event_file.read_text())
            events.append(event)
        except (json.JSONDecodeError, OSError):
            continue

    # Scan for command patterns
    for i, event in enumerate(events):
        if event.get("kind") != "ActionEvent":
            continue

        action = event.get("action")
        if not action or action.get("kind") != "TerminalAction":
            continue

        command = action.get("command", "")
        if not command:
            continue

        # Check each pattern
        for pattern_name, pattern in INTERACTION_COMMAND_PATTERNS.items():
            if not pattern.search(command):
                continue

            # Get observation output and exit code
            output = ""
            exit_code = None
            if i + 1 < len(events):
                next_event = events[i + 1]
                if next_event.get("kind") == "ObservationEvent":
                    obs = next_event.get("observation", {})
                    exit_code = obs.get("exit_code")
                    content = obs.get("content", [])
                    if content and isinstance(content, list):
                        output = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
                    elif isinstance(content, str):
                        output = content

            # Only count successful interactions
            if exit_code != 0:
                continue

            # Extract ref from command/output
            extracted_ref = _extract_ref_from_command(command, output, pattern_name)
            if not extracted_ref or not extracted_ref.url:
                continue

            # Match to conversation refs
            norm_url = _normalize_ref_url(extracted_ref.url)
            ref_type, interaction_type = PATTERN_TO_INTERACTION.get(pattern_name, (None, None))

            if ref_type == "repo" and norm_url in norm_repos:
                orig_url = norm_repos[norm_url]
                if orig_url not in interactions.repos:
                    interactions.repos[orig_url] = set()
                interactions.repos[orig_url].add(interaction_type)

            elif ref_type == "pr" and norm_url in norm_prs:
                orig_url = norm_prs[norm_url]
                if orig_url not in interactions.prs:
                    interactions.prs[orig_url] = set()
                interactions.prs[orig_url].add(interaction_type)
                # Also mark repo as pushed if this was a push to a PR
                if interaction_type == "pushed":
                    repo_url = f"https://github.com/{extracted_ref.owner}/{extracted_ref.repo}"
                    norm_repo_url = _normalize_ref_url(repo_url)
                    if norm_repo_url in norm_repos:
                        orig_repo_url = norm_repos[norm_repo_url]
                        if orig_repo_url not in interactions.repos:
                            interactions.repos[orig_repo_url] = set()
                        interactions.repos[orig_repo_url].add("pushed")

            elif ref_type == "issue" and norm_url in norm_issues:
                orig_url = norm_issues[norm_url]
                if orig_url not in interactions.issues:
                    interactions.issues[orig_url] = set()
                interactions.issues[orig_url].add(interaction_type)

            # For git push, also check if it matches a repo
            if ref_type == "repo" and pattern_name == "git_push":
                # Check if any PR belongs to this repo - mark repo as pushed
                for pr_url in refs["prs"]:
                    if extracted_ref.owner and extracted_ref.repo:
                        if f"/{extracted_ref.owner}/{extracted_ref.repo}/" in pr_url:
                            if pr_url not in interactions.prs:
                                interactions.prs[pr_url] = set()
                            interactions.prs[pr_url].add("pushed")

    return interactions


def _display_actions_only(interactions: RefInteractions) -> None:
    """Display only refs with detected write actions."""
    # Collect all interactions with their URLs
    action_items: list[tuple[str, str, str]] = []  # (action, url, category)

    # Priority order for actions (most significant first)
    action_priority = {
        "created": 1,
        "merged": 2,
        "pushed": 3,
        "commented": 4,
        "reviewed": 5,
        "closed": 6,
        "cloned": 7,
    }

    for url, url_actions in interactions.repos.items():
        for action in url_actions:
            action_items.append((action, url, "repo"))

    for url, url_actions in interactions.prs.items():
        for action in url_actions:
            action_items.append((action, url, "pr"))

    for url, url_actions in interactions.issues.items():
        for action in url_actions:
            action_items.append((action, url, "issue"))

    if not action_items:
        console.print("\n[dim]No write actions detected.[/dim]")
        return

    # Sort by priority
    action_items.sort(key=lambda x: action_priority.get(x[0], 99))

    console.print()
    for action, url, category in action_items:
        # Shorten URL for display
        short_url = url.replace("https://github.com/", "")
        # Color based on action type
        if action in ("created", "merged"):
            style = "green"
        elif action in ("pushed", "commented", "reviewed"):
            style = "yellow"
        else:
            style = "dim"
        console.print(f"  [{style}]{action}[/{style}] {short_url}")


def _display_refs(refs: dict[str, set[str]], interactions: RefInteractions | None = None) -> None:
    """Display extracted references organized by category with interaction annotations."""
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
                # Get interactions for this URL
                annotation = ""
                if interactions:
                    interaction_dict = getattr(interactions, key, {})
                    url_interactions = interaction_dict.get(url, set())
                    if url_interactions:
                        sorted_interactions = sorted(url_interactions)
                        annotation = f" [dim]\\[{', '.join(sorted_interactions)}][/dim]"
                console.print(f"  • {url}{annotation}")


if __name__ == "__main__":
    main()
