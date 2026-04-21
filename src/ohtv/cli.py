"""Command-line interface for ohtv."""

import csv
import io
import json
import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import click
from click import Context, HelpFormatter
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from ohtv.actions import READ_ACTIONS, WRITE_ACTIONS
from ohtv.config import Config
from ohtv.db.utils import generate_unique_source_names

if TYPE_CHECKING:
    from ohtv.prompts import DisplaySchema

log = logging.getLogger("ohtv")


# Commands that use LLM and consume tokens
LLM_COMMANDS = {"gen"}


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
REPO_INTERACTIONS = {"cloned", "pushed", "committed"}
PR_INTERACTIONS = {"created", "pushed", "commented", "merged", "closed", "reviewed"}
ISSUE_INTERACTIONS = {"created", "commented", "closed"}

# Command patterns to detect interactions
INTERACTION_COMMAND_PATTERNS = {
    # Write interactions
    "git_push": re.compile(r"git\s+push"),
    "git_clone": re.compile(r"git\s+clone"),
    "git_commit": re.compile(r"git\s+commit"),
    "gh_pr_create": re.compile(r"gh\s+pr\s+create"),
    "gh_pr_comment": re.compile(r"gh\s+pr\s+comment\s+(\d+)"),
    "gh_pr_review": re.compile(r"gh\s+pr\s+review\s+(\d+)"),
    "gh_pr_merge": re.compile(r"gh\s+pr\s+merge\s+(\d+)"),
    "gh_pr_close": re.compile(r"gh\s+pr\s+close\s+(\d+)"),
    "gh_issue_create": re.compile(r"gh\s+issue\s+create"),
    "gh_issue_comment": re.compile(r"gh\s+issue\s+comment\s+(\d+)"),
    "gh_issue_close": re.compile(r"gh\s+issue\s+close\s+(\d+)"),
    # Read/research interactions
    "git_fetch": re.compile(r"git\s+fetch"),
    "git_pull": re.compile(r"git\s+pull"),
    "gh_repo_view": re.compile(r"gh\s+repo\s+view"),
    "gh_repo_clone": re.compile(r"gh\s+repo\s+clone"),
    "gh_api": re.compile(r"gh\s+api\s+"),
    "gh_browse": re.compile(r"gh\s+browse"),
    "gh_pr_view": re.compile(r"gh\s+pr\s+view\s+(\d+)"),
    "gh_pr_diff": re.compile(r"gh\s+pr\s+diff\s+(\d+)"),
    "gh_pr_checks": re.compile(r"gh\s+pr\s+checks\s+(\d+)"),
    "gh_issue_view": re.compile(r"gh\s+issue\s+view\s+(\d+)"),
}

# Pattern to extract working directory from cd command
CD_PATH_PATTERN = re.compile(r"cd\s+([^\s;&|]+)")

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
    # Write interactions
    "git_push": ("repo", "pushed"),
    "git_clone": ("repo", "cloned"),
    "git_commit": ("repo", "committed"),
    "gh_pr_create": ("pr", "created"),
    "gh_pr_comment": ("pr", "commented"),
    "gh_pr_review": ("pr", "reviewed"),
    "gh_pr_merge": ("pr", "merged"),
    "gh_pr_close": ("pr", "closed"),
    "gh_issue_create": ("issue", "created"),
    "gh_issue_comment": ("issue", "commented"),
    "gh_issue_close": ("issue", "closed"),
    # Read/research interactions
    "git_fetch": ("repo", "fetched"),
    "git_pull": ("repo", "pulled"),
    "gh_repo_view": ("repo", "viewed"),
    "gh_repo_clone": ("repo", "cloned"),
    "gh_api": ("repo", "api_called"),
    "gh_browse": ("repo", "browsed"),
    "gh_pr_view": ("pr", "viewed"),
    "gh_pr_diff": ("pr", "viewed"),
    "gh_pr_checks": ("pr", "viewed"),
    "gh_issue_view": ("issue", "viewed"),
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
    unpushed_commits: set[str] = field(default_factory=set)  # working dirs with commits but no push


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
@click.option("--force", "-f", is_flag=True, help="Re-download all conversations (cleans local data first)")
@click.option("--since", type=click.DateTime(), help="Only sync conversations updated after date")
@click.option("--dry-run", is_flag=True, help="Show what would sync without downloading")
@click.option("--max-new", "-n", type=int, help="Maximum number of NEW conversations to sync")
@click.option("--status", "-s", is_flag=True, help="Show sync status")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output for cron jobs")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def sync(
    force: bool,
    since: datetime | None,
    dry_run: bool,
    max_new: int | None,
    status: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Sync cloud conversations to local storage.
    
    Use -n/--max-new to limit the number of NEW conversations synced.
    Updates to existing conversations are always synced (no limit).
    
    After syncing, automatically indexes conversations and runs all
    processing stages (refs, actions, branch_context, push_pr_links).
    
    Combining --force with -n resets local storage to only the N most
    recent conversations (destructive operation, requires confirmation).
    """
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
        # Handle --force -n combination (reset to N newest)
        if force and max_new is not None:
            result = _run_force_reset(manager, max_new, dry_run, quiet)
        else:
            result = _run_sync(manager, force, since, dry_run, max_new, quiet)
        
        if not quiet:
            _show_result(result, dry_run)
        
        # Always run processing stages after sync (unless dry-run)
        if not dry_run:
            _run_post_sync_processing(quiet, verbose)
            
    except SyncAuthError as e:
        console.print(f"[red]Authentication error:[/red] {e}")
        raise SystemExit(1)
    except SyncAbortedError as e:
        console.print(f"[red]Sync aborted:[/red] {e}")
        raise SystemExit(1)


def _run_force_reset(
    manager: SyncManager,
    max_new: int,
    dry_run: bool,
    quiet: bool,
) -> SyncResult:
    """Handle --force -n combination: reset to N newest conversations."""
    from rich.prompt import Confirm
    
    current_count = manager.get_local_conversation_count()
    
    if not quiet:
        console.print(f"[yellow]Warning:[/yellow] This will delete {current_count} local conversation(s) "
                      f"and sync up to {max_new} of the most recent from cloud.")
        console.print()
        if dry_run:
            console.print("[yellow]DRY RUN[/yellow] - showing what would be synced:")
        else:
            if not Confirm.ask("Proceed?", console=console, default=False):
                console.print("[dim]Cancelled.[/dim]")
                raise SystemExit(0)
    
    on_progress = None if quiet else _make_progress_callback()
    return manager.reset_to_n_newest(max_new, dry_run=dry_run, on_progress=on_progress)


@main.command()
@click.argument("action", required=False, type=click.Choice(["set"]))
@click.argument("key", required=False)
@click.argument("value", required=False)
def config(action: str | None, key: str | None, value: str | None) -> None:
    """View and manage ohtv configuration.
    
    \b
    Without arguments, shows current configuration with sources.
    
    \b
    Usage:
      ohtv config                    Show current configuration
      ohtv config set KEY VALUE      Set a configuration value
    
    \b
    Configurable keys:
      local_conversations_dir    Path to local CLI conversations
      synced_conversations_dir   Path to synced cloud conversations
      cloud_api_url              OpenHands Cloud API URL
      source                     Default source: 'local' or 'cloud'
      extra_conversation_paths   Additional conversation directories (colon-separated)
    
    \b
    Configuration priority (highest first):
      1. Environment variables (OHTV_*, OH_API_KEY)
      2. Config file (~/.ohtv/config.toml)
      3. Defaults
    """
    from ohtv.config import CONFIGURABLE_KEYS, save_config_value
    
    if action == "set":
        if not key or not value:
            console.print("[red]Error:[/red] Usage: ohtv config set KEY VALUE")
            raise SystemExit(1)
        try:
            save_config_value(key, value)
            console.print(f"[green]✓[/green] Set {key} = {value}")
            console.print(f"[dim]Saved to {Config.from_env().with_sources().config_file_path}[/dim]")
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
        return
    
    # Show configuration
    _show_config()


def _show_config() -> None:
    """Display current configuration with sources."""
    cfg = Config.from_env().with_sources()
    
    table = Table(title="Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_column("Source", style="dim")
    
    def _source_style(source: str) -> str:
        if source == "env":
            return "[yellow]env[/yellow]"
        elif source == "file":
            return "[green]file[/green]"
        return "[dim]default[/dim]"
    
    table.add_row(
        "local_conversations_dir",
        str(cfg.local_conversations_dir.value),
        _source_style(cfg.local_conversations_dir.source),
    )
    table.add_row(
        "synced_conversations_dir",
        str(cfg.synced_conversations_dir.value),
        _source_style(cfg.synced_conversations_dir.source),
    )
    table.add_row(
        "cloud_api_url",
        str(cfg.cloud_api_url.value),
        _source_style(cfg.cloud_api_url.source),
    )
    table.add_row(
        "api_key",
        str(cfg.api_key.value),
        _source_style(cfg.api_key.source),
    )
    table.add_row(
        "source",
        str(cfg.source.value),
        _source_style(cfg.source.source),
    )
    table.add_row(
        "extra_conversation_paths",
        str(cfg.extra_conversation_paths.value) if cfg.extra_conversation_paths.value else "[dim]None[/dim]",
        _source_style(cfg.extra_conversation_paths.source),
    )
    
    console.print()
    console.print(table)
    
    # Show data directories
    console.print()
    console.print("[bold]Data Directories[/bold]")
    ohtv_dir = cfg.ohtv_dir
    console.print(f"  ohtv_dir:      {ohtv_dir.value} ({_source_style(ohtv_dir.source)})")
    console.print(f"  manifest:      {cfg.manifest_path}")
    console.print(f"  config_file:   {cfg.config_file_path}")
    
    # Show if manifest exists
    if cfg.manifest_path.exists():
        console.print(f"  [green]✓[/green] manifest exists")
    else:
        console.print(f"  [yellow]![/yellow] manifest not found")


def _run_post_sync_processing(quiet: bool, verbose: bool) -> None:
    """Run all processing stages after sync."""
    from ohtv.db import get_connection, migrate, scan_conversations
    from ohtv.db.stages import STAGES
    from ohtv.db.stores import ConversationStore, StageStore
    
    if not quiet:
        console.print("\n[bold]Running processing stages...[/bold]")
    
    with get_connection() as conn:
        migrate(conn)
        
        # Scan to register any new conversations
        scan_result = scan_conversations(conn)
        conn.commit()
        
        if not quiet and scan_result.new_registered > 0:
            console.print(f"[dim]Registered {scan_result.new_registered} new conversation(s)[/dim]")
        
        conv_store = ConversationStore(conn)
        stage_store = StageStore(conn)
        
        # Get conversations that need processing
        all_convs = conv_store.list_all()
        
        for stage_name, processor in STAGES.items():
            needs_processing = []
            for conv in all_convs:
                if stage_store.needs_processing(conv.id, stage_name, conv.event_count):
                    needs_processing.append(conv)
            
            if not needs_processing:
                if not quiet:
                    console.print(f"  {stage_name}: [dim]up to date[/dim]")
                continue
            
            if not quiet:
                console.print(f"  {stage_name}: processing {len(needs_processing)} conversation(s)...")
            
            for conv in needs_processing:
                try:
                    processor(conn, conv)
                except Exception as e:
                    if verbose:
                        console.print(f"    [red]Error processing {conv.id}:[/red] {e}")
            
            # Commit after each stage to save progress
            conn.commit()
    
    if not quiet:
        console.print("[green]✓[/green] Processing complete")


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
    max_new: int | None,
    quiet: bool,
) -> SyncResult:
    """Execute sync with progress display."""
    if not quiet:
        _print_sync_header(force, since, dry_run, max_new)

    on_progress = None if quiet else _make_progress_callback()
    return manager.sync(force=force, since=since, dry_run=dry_run, max_new=max_new, on_progress=on_progress)


def _print_sync_header(force: bool, since: datetime | None, dry_run: bool, max_new: int | None) -> None:
    """Print sync operation header."""
    mode = "[yellow]DRY RUN[/yellow] " if dry_run else ""
    limit_suffix = f" (max {max_new} new)" if max_new is not None else ""
    if force:
        console.print(f"{mode}Syncing all cloud conversations (force){limit_suffix}...")
    elif since:
        console.print(f"{mode}Syncing conversations since {since.isoformat()}{limit_suffix}...")
    else:
        console.print(f"{mode}Syncing cloud conversations{limit_suffix}...")


def _make_progress_callback():
    """Create progress callback for sync."""

    def callback(conv_id: str, title: str, action: str) -> None:
        short_id = conv_id[:7]
        status_style = {
            "new": "green",
            "updated": "yellow",
            "unchanged": "dim",
            "failed": "red",
            "skipped": "dim cyan",
        }
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
    if result.skipped_new:
        console.print(f"  [cyan]Skipped:   {result.skipped_new} additional available[/cyan]")

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


def _parse_date_option(value: str | None) -> datetime | None:
    """Parse a date option value, supporting 'today' keyword and standard formats."""
    if value is None:
        return None
    if value.lower() == "today":
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # Try parsing with click's DateTime
    try:
        return click.DateTime().convert(value, None, None)
    except click.BadParameter:
        raise click.BadParameter(f"Invalid date format: {value}")


def _get_week_bounds(date: datetime) -> tuple[datetime, datetime]:
    """Get the start (Sunday) and end (Saturday) of the week containing the date."""
    # weekday() returns 0=Monday, 6=Sunday
    # We want Sunday as start of week
    days_since_sunday = (date.weekday() + 1) % 7
    week_start = date - timedelta(days=days_since_sunday)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return week_start, week_end


def _get_day_bounds(date: datetime) -> tuple[datetime, datetime]:
    """Get the start and end of a day."""
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
    return day_start, day_end


def _filter_by_date_range(
    conversations: list[ConversationInfo],
    since: datetime | None,
    until: datetime | None,
) -> list[ConversationInfo]:
    """Filter conversations by created_at date range."""
    if since is None and until is None:
        return conversations

    filtered = []
    for conv in conversations:
        if conv.created_at is None:
            continue
        # Normalize to naive datetime for comparison (strip timezone)
        created = conv.created_at.replace(tzinfo=None) if conv.created_at.tzinfo else conv.created_at
        if since and created < since:
            continue
        if until and created > until:
            continue
        filtered.append(conv)
    return filtered


def _filter_by_pr(
    conversations: list[ConversationInfo],
    pr_filter: str,
) -> list[ConversationInfo]:
    """Filter conversations by PR reference.
    
    Requires the database to be initialized and refs to be indexed.
    """
    from ohtv.filters import (
        filter_conversations_by_ids,
        get_conversation_ids_for_pr,
        is_db_available,
    )
    
    if not is_db_available():
        console.print("[yellow]Warning:[/yellow] Database not initialized. Run 'ohtv db scan && ohtv db process refs' first.")
        console.print("[dim]PR filtering requires indexed conversations.[/dim]")
        return []
    
    conversation_ids, matched_prs = get_conversation_ids_for_pr(pr_filter)
    
    if not matched_prs:
        console.print(f"[yellow]Warning:[/yellow] No PRs found matching '{pr_filter}'")
        console.print("[dim]Try 'ohtv db status' to check indexed PRs.[/dim]")
        return []
    
    if len(matched_prs) > 1:
        console.print(f"[dim]Matched {len(matched_prs)} PRs: {', '.join(matched_prs)}[/dim]")
    else:
        console.print(f"[dim]Filtering by PR: {matched_prs[0]}[/dim]")
    
    return filter_conversations_by_ids(conversations, conversation_ids)


def _parse_date_filters(
    since_date: str | None,
    until_date: str | None,
    day_date: str | None,
    week_date: str | None,
) -> tuple[datetime | None, datetime | None]:
    """Parse date filter options and apply shortcuts.
    
    Returns:
        Tuple of (since, until) datetime objects
    """
    since = _parse_date_option(since_date)
    until = _parse_date_option(until_date)
    
    # Handle --day shortcut
    if day_date is not None:
        day = _parse_date_option(day_date)
        if day:
            day_start, day_end = _get_day_bounds(day)
            since = since or day_start
            until = until or day_end
    
    # Handle --week shortcut
    if week_date is not None:
        week = _parse_date_option(week_date)
        if week:
            week_start, week_end = _get_week_bounds(week)
            since = since or week_start
            until = until or week_end
    
    return since, until


@dataclass
class FilterResult:
    """Result of applying conversation filters."""
    conversations: list[ConversationInfo]
    possible_match_ids: set[str]  # IDs that are ambiguous matches (action+repo)
    show_all: bool  # Whether filters imply showing all results


def _apply_conversation_filters(
    config: Config,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    pr_filter: str | None = None,
    repo_filter: str | None = None,
    action_filter: str | None = None,
    include_empty: bool = False,
    initial_show_all: bool = False,
    errors_only: bool = False,
) -> FilterResult:
    """Apply all conversation filters and return filtered results.
    
    This centralizes the filtering logic used by both `list` and `summary` commands.
    
    Args:
        config: Application configuration
        since: Filter conversations after this datetime
        until: Filter conversations before this datetime
        pr_filter: PR reference filter (URL, FQN, or short name)
        repo_filter: Repository filter (URL, FQN, or name)
        action_filter: Action type filter (e.g., "git-push", "pushed")
        include_empty: Include conversations with 0 events
        initial_show_all: Initial value for show_all flag
        errors_only: Only include conversations with agent/LLM errors
        
    Returns:
        FilterResult with filtered conversations and metadata
    """
    show_all = initial_show_all
    
    # Any filter implies --all (show all matching records)
    if any([since, until, pr_filter, repo_filter, action_filter, errors_only]):
        show_all = True
    
    # Load conversations from both sources, with date filtering pushed to DB
    conversations = _load_all_conversations(config, since=since, until=until)
    
    # Filter out empty conversations unless requested
    if not include_empty:
        conversations = [c for c in conversations if c.event_count > 0]
    
    # Apply PR filtering (requires database)
    if pr_filter is not None:
        conversations = _filter_by_pr(conversations, pr_filter)
    
    # Track possible matches (for action+repo combined filter)
    possible_match_ids: set[str] = set()
    
    # Apply action filtering (optionally combined with repo for precise matching)
    if action_filter is not None:
        conversations, possible_match_ids = _filter_by_action(
            conversations, action_filter, repo_filter
        )
        # If action+repo combined, skip separate repo filter
        if repo_filter is not None:
            repo_filter = None  # Already handled in _filter_by_action
    
    # Apply repo filtering (requires database) - only if not already combined with action
    if repo_filter is not None:
        conversations = _filter_by_repo(conversations, repo_filter)
    
    # Apply error filtering
    if errors_only:
        conversations = _filter_by_errors(config, conversations)
    
    return FilterResult(
        conversations=conversations,
        possible_match_ids=possible_match_ids,
        show_all=show_all,
    )


def _filter_by_repo(
    conversations: list[ConversationInfo],
    repo_filter: str,
) -> list[ConversationInfo]:
    """Filter conversations by repository reference.
    
    Requires the database to be initialized and refs to be indexed.
    """
    from ohtv.filters import (
        filter_conversations_by_ids,
        get_conversation_ids_for_repo,
        is_db_available,
    )
    
    if not is_db_available():
        console.print("[yellow]Warning:[/yellow] Database not initialized. Run 'ohtv db scan && ohtv db process refs' first.")
        console.print("[dim]Repo filtering requires indexed conversations.[/dim]")
        return []
    
    conversation_ids, matched_repos = get_conversation_ids_for_repo(repo_filter)
    
    if not matched_repos:
        console.print(f"[yellow]Warning:[/yellow] No repos found matching '{repo_filter}'")
        console.print("[dim]Try 'ohtv db status' to check indexed repos.[/dim]")
        return []
    
    if len(matched_repos) > 1:
        console.print(f"[dim]Matched {len(matched_repos)} repos: {', '.join(matched_repos)}[/dim]")
    else:
        console.print(f"[dim]Filtering by repo: {matched_repos[0]}[/dim]")
    
    return filter_conversations_by_ids(conversations, conversation_ids)


def _filter_by_action(
    conversations: list[ConversationInfo],
    action_filter: str,
    repo_filter: str | None = None,
) -> tuple[list[ConversationInfo], set[str]]:
    """Filter conversations by action type, optionally combined with repo.
    
    When combined with repo filter, tries to do precise matching:
    - If action has target URL, match against repo URL (definite match)
    - If action has no target, match on write link to repo (possible match)
    
    Returns:
        Tuple of (filtered_conversations, possible_match_ids)
        - possible_match_ids: IDs marked with * (ambiguous matches)
    """
    from ohtv.filters import (
        filter_conversations_by_ids,
        get_conversation_ids_for_action,
        get_conversation_ids_for_action_and_repo,
        get_valid_action_types,
        is_db_available,
        normalize_action_type,
    )
    
    if not is_db_available():
        console.print("[yellow]Warning:[/yellow] Database not initialized. Run 'ohtv db scan && ohtv db process actions' first.")
        console.print("[dim]Action filtering requires indexed conversations.[/dim]")
        return [], set()
    
    action_type = normalize_action_type(action_filter)
    valid_types = get_valid_action_types()
    
    if action_type not in valid_types:
        console.print(f"[yellow]Warning:[/yellow] Unknown action type '{action_filter}'")
        console.print(f"[dim]Valid types: {', '.join(sorted(valid_types))}[/dim]")
        return [], set()
    
    if repo_filter:
        # Combined action + repo filter with precise matching
        definite, possible, action_type, matched_repos = get_conversation_ids_for_action_and_repo(
            action_filter, repo_filter
        )
        
        if not matched_repos:
            console.print(f"[yellow]Warning:[/yellow] No repos found matching '{repo_filter}'")
            return [], set()
        
        all_matches = definite | possible
        
        if not all_matches:
            console.print(f"[dim]No conversations with '{action_type}' action for {', '.join(matched_repos)}[/dim]")
            return [], set()
        
        repo_info = matched_repos[0] if len(matched_repos) == 1 else f"{len(matched_repos)} repos"
        
        if possible:
            console.print(f"[dim]Filtering by action '{action_type}' + repo ({repo_info}): {len(definite)} definite, {len(possible)} possible matches[/dim]")
        else:
            console.print(f"[dim]Filtering by action '{action_type}' + repo ({repo_info}): {len(definite)} matches[/dim]")
        
        return filter_conversations_by_ids(conversations, all_matches), possible
    else:
        # Action filter only
        conversation_ids, action_type = get_conversation_ids_for_action(action_filter)
        
        if not conversation_ids:
            console.print(f"[dim]No conversations with '{action_type}' action[/dim]")
            return [], set()
        
        console.print(f"[dim]Filtering by action '{action_type}': {len(conversation_ids)} matches[/dim]")
        return filter_conversations_by_ids(conversations, conversation_ids), set()


def _count_uncached_conversations_fast(
    conversations: list[ConversationInfo],
    config: Config,
    context: str,
    detail: str,
    assess: bool,
) -> int:
    """Count conversations needing analysis using fast DB lookup.
    
    Uses the database to check cache status in O(1) instead of
    loading event files for each conversation. Falls back to
    slow file-based checking if DB is not available.
    
    Returns:
        Number of conversations that need LLM analysis
    """
    try:
        from ohtv.db import get_connection, get_db_path, migrate
        from ohtv.db.stores import AnalysisCacheStore
        from ohtv.analysis.cache import make_cache_key
        
        db_path = get_db_path()
        if not db_path.exists():
            log.debug("DB not found, falling back to slow cache check")
            return _count_uncached_conversations_slow(conversations, config, context, detail, assess)
        
        # Build cache key for these parameters
        cache_key = make_cache_key(context, detail, assess)
        
        # Normalize conversation IDs (remove dashes)
        conv_ids = [c.lookup_id.replace("-", "") for c in conversations]
        
        with get_connection() as conn:
            migrate(conn)
            store = AnalysisCacheStore(conn)
            
            # Get cache status for all conversations in one query
            status_map = store.get_cache_status_batch(conv_ids, cache_key)
            
            # Count those needing analysis
            uncached_count = 0
            for conv_id in conv_ids:
                status = status_map.get(conv_id)
                if status is None or status.needs_analysis:
                    uncached_count += 1
            
            log.debug(
                "Fast cache check: %d of %d need analysis (key=%s)",
                uncached_count, len(conversations), cache_key
            )
            return uncached_count
            
    except Exception as e:
        log.debug("Fast cache check failed, falling back to slow: %s", e)
        return _count_uncached_conversations_slow(conversations, config, context, detail, assess)


def _count_uncached_conversations_slow(
    conversations: list[ConversationInfo],
    config: Config,
    context: str,
    detail: str,
    assess: bool,
) -> int:
    """Count uncached conversations using file-based checking (slow).
    
    This is the fallback when the database is not available.
    """
    from ohtv.analysis import get_cached_analysis
    from ohtv.analysis.objectives import _cache_manager
    from ohtv.analysis.cache import load_events
    
    uncached_count = 0
    for conv in conversations:
        result = _find_conversation_dir(config, conv.lookup_id)
        if result:
            conv_dir, _ = result
            cached = get_cached_analysis(
                conv_dir, context=context, detail=detail, assess=assess
            )
            if cached is None:
                # Also check for skip marker (counts as "cached" since we won't call LLM)
                events = load_events(conv_dir)
                skip_reason = _cache_manager.is_skipped(conv_dir, len(events))
                if skip_reason is None:
                    uncached_count += 1
        else:
            # Can't find dir = will fail anyway, count as uncached
            uncached_count += 1
    
    return uncached_count


def _filter_by_errors(
    config: Config,
    conversations: list[ConversationInfo],
) -> list[ConversationInfo]:
    """Filter conversations to only those with agent/LLM errors.
    
    Analyzes each conversation for ConversationErrorEvent and AgentErrorEvent.
    Also populates error_count, error_types, has_terminal_error fields.
    """
    from ohtv.errors import analyze_conversation_lazy, format_error_type_counts
    
    filtered = []
    for conv in conversations:
        conv_dir = _get_conversation_dir(config, conv)
        if conv_dir is None:
            continue
        
        summary = analyze_conversation_lazy(conv_dir, conv.id)
        if summary and summary.has_errors:
            # Populate error fields on ConversationInfo
            conv.error_count = summary.total_errors
            conv.error_types = summary.error_counts
            conv.has_terminal_error = summary.has_terminal_error
            conv.execution_status = summary.execution_status
            filtered.append(conv)
    
    if filtered:
        console.print(f"[dim]Found {len(filtered)} conversation(s) with errors[/dim]")
    else:
        console.print("[dim]No conversations with agent/LLM errors found[/dim]")
    
    return filtered


def _get_conversation_dir(config: Config, conv: ConversationInfo) -> Path | None:
    """Get the directory path for a conversation."""
    lookup_id = conv.lookup_id
    
    if conv.source == "local":
        conv_dir = config.local_conversations_dir / lookup_id
    elif conv.source == "cloud":
        conv_dir = config.synced_conversations_dir / lookup_id
    else:
        # Extra source - need to find the right directory
        for extra_dir in config.extra_conversation_paths:
            conv_dir = extra_dir / lookup_id
            if conv_dir.exists():
                return conv_dir
        return None
    
    return conv_dir if conv_dir.exists() else None


def _populate_error_info(
    config: Config,
    conversations: list[ConversationInfo],
) -> None:
    """Populate error fields for conversations that don't have them yet."""
    from ohtv.errors import analyze_conversation_lazy
    
    for conv in conversations:
        if conv.error_count is not None:
            continue  # Already populated
        
        conv_dir = _get_conversation_dir(config, conv)
        if conv_dir is None:
            continue
        
        summary = analyze_conversation_lazy(conv_dir, conv.id)
        if summary:
            conv.error_count = summary.total_errors
            conv.error_types = summary.error_counts
            conv.has_terminal_error = summary.has_terminal_error
            conv.execution_status = summary.execution_status
        else:
            conv.error_count = 0
            conv.error_types = {}
            conv.has_terminal_error = False


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
@click.option("--since", "-S", "since_date", help="Show conversations from DATE onwards")
@click.option("--until", "-U", "until_date", help="Show conversations up to DATE")
@click.option("--day", "-D", "day_date", is_flag=False, flag_value="today", default=None,
              help="Show conversations from a single day (default: today)")
@click.option("--week", "-W", "week_date", is_flag=False, flag_value="today", default=None,
              help="Show conversations from the week containing DATE (default: today, weeks start Sunday)")
@click.option("--pr", "pr_filter", help="Filter by PR (URL, owner/repo#N, or repo#N)")
@click.option("--repo", "repo_filter", help="Filter by repo (URL, owner/repo, or repo name)")
@click.option("--action", "action_filter", help="Filter by action type (e.g., git-push, pushed, open-pr)")
@click.option("--refs", "-R", "show_refs", is_flag=True, help="Show git refs (repos, PRs, issues) from database")
@click.option("--with-errors", "-E", "with_errors", is_flag=True, help="Include error info column (agent/LLM errors)")
@click.option("--errors-only", "errors_only", is_flag=True, help="Show only conversations with agent/LLM errors")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def list_conversations(
    reverse: bool,
    limit: int | None,
    show_all: bool,
    offset: int,
    fmt: str,
    output: str | None,
    include_empty: bool,
    since_date: str | None,
    until_date: str | None,
    day_date: str | None,
    week_date: str | None,
    pr_filter: str | None,
    repo_filter: str | None,
    action_filter: str | None,
    show_refs: bool,
    with_errors: bool,
    errors_only: bool,
    verbose: bool,
) -> None:
    """List available conversations from local and cloud sources."""
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Parse date filters and apply shortcuts
    since, until = _parse_date_filters(since_date, until_date, day_date, week_date)

    # Apply all conversation filters
    filter_result = _apply_conversation_filters(
        config,
        since=since,
        until=until,
        pr_filter=pr_filter,
        repo_filter=repo_filter,
        action_filter=action_filter,
        include_empty=include_empty,
        initial_show_all=show_all,
        errors_only=errors_only,
    )
    
    conversations = filter_result.conversations
    possible_match_ids = filter_result.possible_match_ids
    show_all = filter_result.show_all

    total_count = len(conversations)
    local_count = sum(1 for c in conversations if c.source == "local")
    cloud_count = total_count - local_count

    # Sort by created_at (newest first by default)
    conversations = sorted(
        conversations,
        key=lambda c: _normalize_datetime_for_sort(c.created_at),
        reverse=not reverse,
    )

    # Apply offset and limit
    # Explicit -n takes precedence over show_all implied by filters
    if offset:
        conversations = conversations[offset:]
    if limit is not None:
        # Explicit limit always applies
        conversations = conversations[:limit]
    elif not show_all:
        # Default limit when no filters and no explicit -n
        conversations = conversations[:10]

    # Track if we're using default limit (for hint message)
    using_default_limit = not show_all and limit is None

    # Load refs from database if requested
    refs_map: dict[str, list[str]] | None = None
    if show_refs:
        refs_map = _load_refs_for_conversations(conversations)

    # Populate error info if requested (and not already populated by errors_only filter)
    show_errors = with_errors or errors_only
    if show_errors and not errors_only:
        _populate_error_info(config, conversations)

    # Format output
    output_text = _format_list_output(
        conversations, fmt, total_count, local_count, cloud_count, 
        refs_map=refs_map, show_errors=show_errors
    )

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
                possible_match_ids=possible_match_ids,
                refs_map=refs_map,
                show_errors=show_errors,
                hide_title=errors_only,
            )
        else:
            # For JSON and CSV, use plain print to avoid rich styling
            print(output_text)


@main.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Number of results (default: 10)")
@click.option("--exact", is_flag=True, help="Use keyword search (FTS5) instead of semantic")
@click.option("--since", "-S", "since_date", help="Filter by date (YYYY-MM-DD or relative)")
@click.option("--min-score", "-s", type=float, default=0.0, help="Minimum similarity score (0-1)")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format (default: table)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def search(
    query: str,
    limit: int,
    exact: bool,
    since_date: str | None,
    min_score: float,
    fmt: str,
    verbose: bool,
) -> None:
    """Search conversations semantically or by keyword.
    
    Uses embedding-based semantic search to find conversations by concept/intent
    rather than exact keyword matches. Falls back to keyword search with --exact.
    
    \b
    Before searching, build embeddings with:
      ohtv db embed
    
    \b
    Examples:
      ohtv search "fix authentication bugs"
      ohtv search "docker deployment" -n 20
      ohtv search "API changes" --since 7d
      ohtv search "error 404" --exact           # Keyword search
      ohtv ask "how did we fix the auth bug"    # For question answering
    """
    import time
    from ohtv.db import get_connection, get_db_path, migrate
    from ohtv.db.stores import ConversationStore, EmbeddingStore
    
    _init_logging(verbose=verbose)
    config = Config.from_env()
    db_path = get_db_path()
    
    if not db_path.exists():
        console.print("[yellow]No database found.[/yellow]")
        console.print("[dim]Run 'ohtv db scan' and 'ohtv db embed' first.[/dim]")
        raise SystemExit(1)
    
    with get_connection() as conn:
        migrate(conn)
        
        embed_store = EmbeddingStore(conn)
        conv_store = ConversationStore(conn)
        
        # Check if we have embeddings
        embed_count = embed_store.count()
        if embed_count == 0 and not exact:
            console.print("[yellow]No embeddings found.[/yellow]")
            console.print("[dim]Run 'ohtv db embed' to build embeddings for semantic search.[/dim]")
            console.print("[dim]Or use --exact for keyword search.[/dim]")
            raise SystemExit(1)
        
        start_time = time.perf_counter()
        
        if exact:
            # FTS5 keyword search
            raw_results = embed_store.search_fts(query, limit=limit)
            # Convert to have consistent interface
            results = [
                type("Result", (), {
                    "conversation_id": r.conversation_id,
                    "score": r.score,
                    "rank": r.rank,
                    "best_match_type": "keyword",
                })()
                for r in raw_results
            ]
            search_type = "keyword"
        else:
            # Semantic search - embed the query
            try:
                from ohtv.analysis.embeddings import get_embedding
                query_result = get_embedding(query)
                query_embedding = query_result.embedding
            except RuntimeError as e:
                console.print(f"[red]Error:[/red] {e}")
                console.print("[dim]Make sure LLM_API_KEY is set.[/dim]")
                raise SystemExit(1)
            
            # Use aggregated search (best match per conversation)
            results = embed_store.search_conversations(
                query_embedding,
                limit=limit,
                min_score=min_score,
            )
            search_type = "semantic"
        
        search_time = time.perf_counter() - start_time
        
        # Filter by date if specified
        if since_date:
            since = _parse_date_option(since_date)
            if since:
                filtered_results = []
                for r in results:
                    conv = conv_store.get(r.conversation_id)
                    if conv and conv.created_at and conv.created_at >= since:
                        filtered_results.append(r)
                results = filtered_results
        
        # Load conversation metadata for display
        conv_metadata = {}
        for r in results:
            conv = conv_store.get(r.conversation_id)
            if conv:
                conv_metadata[r.conversation_id] = conv
        
        if fmt == "json":
            _print_search_json(results, conv_metadata, search_time, search_type)
        else:
            _print_search_results(results, conv_metadata, search_time, search_type, query)


def _format_time_ago(dt: datetime) -> str:
    """Format a datetime as a human-readable 'time ago' string."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    diff = now - dt
    seconds = int(diff.total_seconds())
    
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:  # 7 days
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif seconds < 2592000:  # 30 days
        weeks = seconds // 604800
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        return dt.strftime("%Y-%m-%d")


def _print_search_results(
    results: list,
    conv_metadata: dict,
    search_time: float,
    search_type: str,
    query: str,
) -> None:
    """Display search results in a rich format."""
    if not results:
        console.print(f"[dim]No matches found for '{query}'[/dim]")
        return
    
    # Header
    console.print(f"\nFound [bold]{len(results)}[/bold] match(es) ({search_type}, {search_time:.2f}s):\n")
    
    # Results
    for r in results:
        conv = conv_metadata.get(r.conversation_id)
        conv_id = r.conversation_id
        short_id = conv_id[:8] if len(conv_id) > 8 else conv_id
        
        # Title and score
        title = conv.title if conv and conv.title else "(no title)"
        if len(title) > 60:
            title = title[:57] + "..."
        
        # Time ago
        time_str = ""
        if conv and conv.created_at:
            time_str = _format_time_ago(conv.created_at)
        
        # Format score
        score_str = f"[dim][{r.score:.2f}][/dim]"
        
        console.print(f"[cyan][{r.rank}][/cyan] [bold]{short_id}[/bold] - \"{title}\" ({time_str}) {score_str}")
    
    console.print(f"\n[dim]Use 'ohtv show <id>' to view full conversation.[/dim]")


def _print_search_json(
    results: list,
    conv_metadata: dict,
    search_time: float,
    search_type: str,
) -> None:
    """Output search results as JSON."""
    output = {
        "search_type": search_type,
        "search_time_seconds": search_time,
        "result_count": len(results),
        "results": [],
    }
    
    for r in results:
        conv = conv_metadata.get(r.conversation_id)
        item = {
            "rank": r.rank,
            "conversation_id": r.conversation_id,
            "score": r.score,
            "title": conv.title if conv else None,
            "created_at": conv.created_at.isoformat() if conv and conv.created_at else None,
        }
        output["results"].append(item)
    
    print(json.dumps(output, indent=2))


@main.command("ask")
@click.argument("question")
@click.option("--context", "-c", default=5, help="Number of context chunks to use (default: 5)")
@click.option("--min-score", "-s", type=float, default=0.3, help="Minimum similarity score (0-1)")
@click.option("--model", "-m", help="LLM model for answer generation")
@click.option("--show-context", is_flag=True, help="Show retrieved context chunks")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def ask(
    question: str,
    context: int,
    min_score: float,
    model: str | None,
    show_context: bool,
    verbose: bool,
) -> None:
    """Ask a question about your conversations (RAG).
    
    Uses semantic search to find relevant context from your conversations,
    then generates an answer using an LLM. This is like search but provides
    a synthesized answer instead of just listing matches.
    
    \b
    Before asking, build embeddings with:
      ohtv db embed
    
    \b
    Examples:
      ohtv ask "how did we fix the authentication bug?"
      ohtv ask "what changes were made to the API?" --context 10
      ohtv ask "summarize the docker deployment work" --show-context
    """
    from ohtv.db import get_connection, get_db_path, migrate
    from ohtv.db.stores import ConversationStore, EmbeddingStore
    from ohtv.analysis.rag import RAGAnswerer
    
    _init_logging(verbose=verbose)
    db_path = get_db_path()
    
    if not db_path.exists():
        console.print("[yellow]No database found.[/yellow]")
        console.print("[dim]Run 'ohtv db scan' and 'ohtv db embed' first.[/dim]")
        raise SystemExit(1)
    
    with get_connection() as conn:
        migrate(conn)
        
        embed_store = EmbeddingStore(conn)
        conv_store = ConversationStore(conn)
        
        # Check if we have embeddings
        embed_count = embed_store.count()
        if embed_count == 0:
            console.print("[yellow]No embeddings found.[/yellow]")
            console.print("[dim]Run 'ohtv db embed' to build embeddings first.[/dim]")
            raise SystemExit(1)
        
        console.print("[dim]Searching for relevant context...[/dim]")
        
        # Use RAGAnswerer for context retrieval and answer generation
        answerer = RAGAnswerer(embed_store, conv_store, model=model)
        
        try:
            result = answerer.answer_question(
                question,
                max_context_chunks=context,
                min_score=min_score,
            )
        except ValueError as e:
            console.print(f"[yellow]{e}[/yellow]")
            console.print("[dim]Try lowering --min-score or building more embeddings.[/dim]")
            raise SystemExit(1)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print("[dim]Make sure LLM_API_KEY is set.[/dim]")
            raise SystemExit(1)
        
        # Show context if requested
        if show_context:
            console.print(f"\n[bold]Retrieved Context ({len(result.context_chunks)} chunks):[/bold]")
            console.print("-" * 60)
            for chunk in result.context_chunks:
                console.print(f"[cyan]{chunk.title}[/cyan] ({chunk.embed_type}, score: {chunk.score:.2f})")
                preview = chunk.source_text[:200] + "..." if len(chunk.source_text) > 200 else chunk.source_text
                console.print(f"[dim]{preview}[/dim]")
                console.print()
            console.print("-" * 60)
        
        # Display answer
        console.print(f"\n[bold]Answer:[/bold]\n")
        console.print(result.answer)
        
        # Show sources
        console.print(f"\n[dim]─────────────────────────────────────────────────[/dim]")
        console.print(f"[dim]Sources ({len(result.source_conversation_ids)} conversations):[/dim]")
        for conv_id in result.source_conversation_ids:
            conv = conv_store.get(conv_id)
            title = conv.title if conv and conv.title else "(no title)"
            short_title = title[:50] + "..." if len(title) > 50 else title
            console.print(f"[dim]  • [{conv_id[:8]}] {short_title}[/dim]")
        
        console.print(f"\n[dim]Search: {result.search_time_seconds:.2f}s | Generation: {result.generation_time_seconds:.2f}s | Model: {result.model}[/dim]")


def _load_all_conversations(
    config: Config,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[ConversationInfo]:
    """Load conversations from local, cloud, and extra directories.
    
    Uses database when available for fast metadata access, with date filtering
    pushed down to the database query. Falls back to filesystem scanning when
    database is unavailable.
    
    Args:
        config: Application configuration
        since: Optional filter for conversations created on or after this time
        until: Optional filter for conversations created before this time
    """
    # Try database-first approach
    try:
        from ohtv.conversations import get_conversations, is_db_available_with_metadata
        
        if is_db_available_with_metadata():
            # Use fast database path with date filtering pushed down
            conversations = get_conversations(config, since=since, until=until, use_db=True)
            log.debug("Loaded %d conversations from database (fast path)", len(conversations))
            return conversations
    except Exception as e:
        log.debug("Database loading failed, using filesystem: %s", e)
    
    # Fallback to filesystem (slow path)
    conversations: list[ConversationInfo] = []

    # Load local conversations
    local_source = LocalSource(config.local_conversations_dir, source_name="local")
    conversations.extend(local_source.list_conversations())

    # Load cloud conversations (synced)
    cloud_source = LocalSource(config.synced_conversations_dir, source_name="cloud")
    conversations.extend(cloud_source.list_conversations())

    # Load extra conversation paths
    # Note: Extra paths are assumed to use UTC timestamps (like cloud conversations).
    # If you're pointing to local CLI conversations, timestamps may display incorrectly.
    extra_source_names = generate_unique_source_names(config.extra_conversation_paths)
    for path, source_name in zip(config.extra_conversation_paths, extra_source_names):
        if not path.exists():
            log.warning("Skipping nonexistent conversation path: %s", path)
            continue
        if not path.is_dir():
            log.warning("Skipping non-directory conversation path: %s", path)
            continue
        extra_source = LocalSource(path, source_name=source_name)
        conversations.extend(extra_source.list_conversations())

    # Apply date filtering for filesystem path (DB path has it already)
    if since or until:
        conversations = _filter_by_date_range(conversations, since, until)
    
    log.debug("Loaded %d conversations from filesystem (slow path)", len(conversations))
    return conversations


def _load_refs_for_conversations(
    conversations: list[ConversationInfo],
) -> dict[str, list[str]]:
    """Load refs from database for a list of conversations.
    
    Returns a dict mapping conversation_id -> list of ref display strings.
    Refs are formatted as "repo#N" for PRs/issues, or "owner/repo" for repos.
    """
    from ohtv.db import get_connection, get_db_path, LinkStore, ReferenceStore, RepoStore
    from ohtv.filters import normalize_conversation_id
    
    refs_map: dict[str, list[str]] = {}
    
    db_path = get_db_path()
    if not db_path.exists():
        return refs_map
    
    with get_connection() as conn:
        link_store = LinkStore(conn)
        ref_store = ReferenceStore(conn)
        repo_store = RepoStore(conn)
        
        for conv in conversations:
            refs_list: list[str] = []
            # Normalize ID (database stores without dashes)
            conv_id = normalize_conversation_id(conv.id)
            
            # Get repos for this conversation
            repo_links = link_store.get_repos_for_conversation(conv_id)
            for repo_id, link_type in repo_links:
                repo = repo_store.get_by_id(repo_id)
                if repo:
                    # Use short_name for brevity in table
                    refs_list.append(repo.short_name)
            
            # Get refs (PRs/issues) for this conversation
            ref_links = link_store.get_refs_for_conversation(conv_id)
            for ref_id, link_type in ref_links:
                ref = ref_store.get_by_id(ref_id)
                if ref:
                    # Use display_name (e.g., "repo #123")
                    refs_list.append(ref.display_name)
            
            if refs_list:
                refs_map[conv.id] = refs_list
    
    return refs_map


def _format_list_output(
    conversations: list[ConversationInfo],
    fmt: str,
    total_count: int,
    local_count: int,
    cloud_count: int,
    *,
    refs_map: dict[str, list[str]] | None = None,
    show_errors: bool = False,
) -> str:
    """Format conversation list for output."""
    if fmt == "json":
        return _format_list_json(conversations, refs_map=refs_map, show_errors=show_errors)
    if fmt == "csv":
        return _format_list_csv(conversations, refs_map=refs_map, show_errors=show_errors)
    # Table format is handled separately with rich
    return ""


def _format_list_json(
    conversations: list[ConversationInfo],
    *,
    refs_map: dict[str, list[str]] | None = None,
    show_errors: bool = False,
) -> str:
    """Format conversations as JSON."""
    items = []
    for conv in conversations:
        item = {
            "id": conv.id,
            "source": conv.source,
            "title": conv.title,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            "duration_seconds": conv.duration.total_seconds() if conv.duration else None,
            "event_count": conv.event_count,
            "selected_repository": conv.selected_repository,
        }
        if refs_map is not None:
            item["refs"] = refs_map.get(conv.id, [])
        if show_errors and conv.error_count is not None:
            item["error_count"] = conv.error_count
            item["error_types"] = conv.error_types or {}
            item["has_terminal_error"] = conv.has_terminal_error
            item["execution_status"] = conv.execution_status
        items.append(item)
    return json.dumps(items, indent=2)


def _format_list_csv(
    conversations: list[ConversationInfo],
    *,
    refs_map: dict[str, list[str]] | None = None,
    show_errors: bool = False,
) -> str:
    """Format conversations as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["id", "source", "started", "duration", "events", "title", "repository"]
    if refs_map is not None:
        headers.append("refs")
    if show_errors:
        headers.extend(["errors", "error_types", "terminal"])
    writer.writerow(headers)

    for conv in conversations:
        # Convert UTC to local time for display
        started = ""
        if conv.created_at:
            local_time = conv.created_at.astimezone()
            started = local_time.strftime("%Y-%m-%d %H:%M")
        row = [
            conv.id,
            conv.source,
            started,
            _format_duration(conv.duration) if conv.duration else "",
            conv.event_count or "",
            conv.title or "",
            conv.selected_repository or "",
        ]
        if refs_map is not None:
            row.append("; ".join(refs_map.get(conv.id, [])))
        if show_errors:
            from ohtv.errors import format_error_type_counts
            row.append(conv.error_count if conv.error_count else "")
            row.append(format_error_type_counts(conv.error_types or {}))
            row.append("yes" if conv.has_terminal_error else "")
        writer.writerow(row)

    return output.getvalue()


def _print_list_table(
    conversations: list[ConversationInfo],
    total_count: int,
    local_count: int,
    cloud_count: int,
    *,
    show_hint: bool = False,
    possible_match_ids: set[str] | None = None,
    refs_map: dict[str, list[str]] | None = None,
    show_errors: bool = False,
    hide_title: bool = False,
) -> None:
    """Print conversations as a rich table."""
    from ohtv.errors import format_error_type_counts
    from ohtv.filters import normalize_conversation_id
    
    if possible_match_ids is None:
        possible_match_ids = set()
    
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Started", no_wrap=True)
    table.add_column("Duration", justify="right", no_wrap=True)
    table.add_column("Events", justify="right", no_wrap=True)
    if show_errors:
        table.add_column("Errors", no_wrap=True)
    if not hide_title:
        table.add_column("Title", no_wrap=False, max_width=40)

    # Normalize possible_match_ids for comparison (they may not have dashes)
    normalized_possible = {normalize_conversation_id(pid) for pid in possible_match_ids}
    
    for conv in conversations:
        source_style = "blue" if conv.source == "cloud" else "green"
        # Convert UTC to local time for display
        started = ""
        if conv.created_at:
            local_time = conv.created_at.astimezone()
            started = local_time.strftime("%Y-%m-%d %H:%M")
        
        # Mark possible matches with * suffix
        id_display = conv.short_id
        if normalize_conversation_id(conv.id) in normalized_possible:
            id_display = f"{conv.short_id}[yellow]*[/yellow]"
        
        # Build title cell content (title + optional refs)
        title_text = (conv.title or "")[:60] + ("..." if conv.title and len(conv.title) > 60 else "")
        if refs_map is not None:
            refs = refs_map.get(conv.id, [])
            if refs:
                refs_str = ", ".join(refs)
                title_text = f"{title_text}\n[dim]Refs: {refs_str}[/dim]"
        
        # Build error info column
        error_text = ""
        if show_errors:
            if conv.error_count and conv.error_count > 0:
                type_counts = format_error_type_counts(conv.error_types or {})
                severity_tag = "[red]TERM[/red]" if conv.has_terminal_error else "[yellow]RCVR[/yellow]"
                if type_counts:
                    error_text = f"{conv.error_count} {severity_tag}: [dim]{type_counts}[/dim]"
                else:
                    error_text = f"{conv.error_count} {severity_tag}"
            else:
                error_text = "[dim]-[/dim]"
        
        row = [
            id_display,
            f"[{source_style}]{conv.source}[/{source_style}]",
            started,
            _format_duration(conv.duration) if conv.duration else "",
            str(conv.event_count),
        ]
        if show_errors:
            row.append(error_text)
        if not hide_title:
            row.append(title_text)
        
        table.add_row(*row)

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
    
    # Legends
    if possible_match_ids:
        console.print(f"[dim][yellow]*[/yellow] = possible match (action target not available)[/dim]")
    if show_errors:
        console.print(f"[dim][red]TERM[/red] = terminal error, [yellow]RCVR[/yellow] = recovered[/dim]")

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
@click.option("--action-details", "-d", is_flag=True, help="Include human-readable tool call details")
@click.option("--trunc-output", "-o", "trunc_output", is_flag=True, help="Include tool outputs (truncated)")
@click.option("--full-output", "-O", "full_output", is_flag=True, help="Include tool outputs (full)")
@click.option("--debug-tool-call", is_flag=True, help="Include raw tool_call JSON and observation metadata")
@click.option("--thinking", "-t", is_flag=True, help="Include thinking/reasoning blocks")
@click.option("--timestamps", "-T", is_flag=True, help="Include timestamps on events")
@click.option("--refs", "-R", "show_refs", is_flag=True, help="Show git refs with write actions")
@click.option("--actions", "-X", "show_actions", is_flag=True, help="Show recognized actions (from DB)")
@click.option("--all", "-A", "include_all", is_flag=True, help="Include everything")
@click.option("--messages", "-m", is_flag=True, help="Shorthand for -u -a -f")
@click.option("--stats", "-S", is_flag=True, help="Show only statistics, no content")
@click.option("--reverse", "-r", is_flag=True, help="Show newest events first")
@click.option("--max", "-n", "limit", type=int, help="Maximum number of events to show")
@click.option("--offset", "-k", type=int, default=0, help="Skip first N events")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["text", "markdown", "json"]),
    default="text",
    help="Output format (default: text)",
)
@click.option("--file", type=click.Path(), help="Write output to file")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def show(
    conversation_id: str,
    user_messages: bool,
    agent_messages: bool,
    include_finish: bool,
    action_summaries: bool,
    action_details: bool,
    trunc_output: bool,
    full_output: bool,
    debug_tool_call: bool,
    thinking: bool,
    timestamps: bool,
    show_refs: bool,
    show_actions: bool,
    include_all: bool,
    messages: bool,
    stats: bool,
    reverse: bool,
    limit: int | None,
    offset: int,
    fmt: str,
    file: str | None,
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

    # Normalize output flags: full_output implies trunc_output behavior (but full)
    show_outputs = trunc_output or full_output

    # Expand shorthand flags
    if include_all:
        user_messages = agent_messages = include_finish = True
        action_summaries = action_details = True
        full_output = show_outputs = True
        debug_tool_call = thinking = timestamps = True
        show_refs = True
        show_actions = True
    if messages:
        user_messages = agent_messages = include_finish = True

    # Load conversation info
    conv_id, title = _get_conversation_info(conv_dir)

    # Load and count events
    events = _load_events(conv_dir)
    event_counts = _count_events_by_type(events)
    first_ts, last_ts = _get_event_time_range(events, is_cloud=is_cloud)
    
    # Analyze for errors
    from ohtv.errors import analyze_conversation
    error_summary = analyze_conversation(conv_dir, conv_id)

    # If no content flags specified (and not stats-only), show summary only
    show_content = (
        user_messages or agent_messages or include_finish or
        action_summaries or action_details or show_outputs or thinking
    )

    # Stats-only mode: show statistics and exit
    if stats or not show_content:
        output_text = _format_show_stats(
            conv_id, title, first_ts, last_ts, event_counts, fmt, error_summary
        )
        _write_or_print_output(output_text, file, fmt)
        # Show refs after stats if requested
        if show_refs:
            _show_refs_summary(conv_dir)
        # Show actions if requested
        if show_actions:
            _show_actions_summary(conv_id)
        return

    # Filter events based on flags
    filtered_events = _filter_events(
        events,
        user_messages=user_messages,
        agent_messages=agent_messages,
        include_finish=include_finish,
        action_summaries=action_summaries,
        action_details=action_details,
        outputs=show_outputs,
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
        full_output=full_output,
        debug_tool_call=debug_tool_call,
        error_summary=error_summary,
    )

    _write_or_print_output(output_text, file, fmt)

    # Show refs after main output if requested
    if show_refs:
        _show_refs_summary(conv_dir)
    
    # Show actions if requested
    if show_actions:
        _show_actions_summary(conv_id)


def _show_actions_summary(conv_id: str) -> None:
    """Show recognized actions from the database."""
    from ohtv.db import get_connection, get_db_path
    from ohtv.db.stores import ActionStore, StageStore
    
    db_path = get_db_path()
    if not db_path.exists():
        console.print("\n[dim]Actions not available (run 'ohtv db init' first)[/dim]")
        return
    
    with get_connection() as conn:
        action_store = ActionStore(conn)
        actions = action_store.get_by_conversation(conv_id)
        
        if not actions:
            # Check if actions stage has been processed for this conversation
            stage_store = StageStore(conn)
            stage_record = stage_store.get(conv_id, "actions")
            if stage_record:
                console.print("\n[dim]No recognized actions in this conversation[/dim]")
            else:
                console.print("\n[dim]Actions not indexed (run 'ohtv db process actions' first)[/dim]")
            return
        
        # Group actions by type for summary
        by_type: dict[str, list] = {}
        for action in actions:
            type_name = action.action_type.value
            if type_name not in by_type:
                by_type[type_name] = []
            by_type[type_name].append(action)
        
        console.print("\n[bold]Recognized Actions[/bold]")
        
        # Sort by count descending
        for type_name in sorted(by_type.keys(), key=lambda t: -len(by_type[t])):
            action_list = by_type[type_name]
            count = len(action_list)
            
            # Show count and some examples
            if count <= 3:
                targets = [a.target for a in action_list if a.target]
                target_str = ", ".join(targets[:3]) if targets else ""
                if target_str:
                    console.print(f"  {type_name}: {count} ({target_str})")
                else:
                    console.print(f"  {type_name}: {count}")
            else:
                # Show count with sample
                samples = [a.target for a in action_list[:2] if a.target]
                sample_str = ", ".join(samples) if samples else ""
                if sample_str:
                    console.print(f"  {type_name}: {count} ({sample_str}, ...)")
                else:
                    console.print(f"  {type_name}: {count}")


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
        "thinking": 0,
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
                elif tool_name == "think":
                    counts["thinking"] += 1
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
                elif tool_name == "think" and thinking:
                    # Include think actions when -t flag is used
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
    error_summary: "ErrorSummary | None" = None,
) -> str:
    """Format statistics-only output."""
    from ohtv.errors import ErrorSummary
    
    duration = (last_ts - first_ts) if (first_ts and last_ts) else None
    total = sum(event_counts.values())

    if fmt == "json":
        result = {
            "id": conv_id,
            "title": title,
            "started": first_ts.isoformat() if first_ts else None,
            "ended": last_ts.isoformat() if last_ts else None,
            "duration_seconds": duration.total_seconds() if duration else None,
            "counts": event_counts,
            "total_events": total,
        }
        if error_summary:
            result["errors"] = {
                "total": error_summary.total_errors,
                "terminal": error_summary.terminal_count,
                "recovered": error_summary.recovered_count,
                "has_terminal_error": error_summary.has_terminal_error,
                "error_counts": error_summary.error_counts,
            }
        return json.dumps(result, indent=2)

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
            f"  Thinking:         {event_counts['thinking']}",
            f"  Observations:     {event_counts['observations']}",
            f"  Finish:           {event_counts['finish']}",
            "  ─────────────────────",
            f"  Total:            {total}",
        ]
        # Add error info if present
        if error_summary and error_summary.has_errors:
            lines.append("")
            lines.append("Errors:")
            lines.append(f"  Terminal:         {error_summary.terminal_count}")
            lines.append(f"  Recovered:        {error_summary.recovered_count}")
            if error_summary.error_counts:
                types_str = ", ".join(f"{k}: {v}" for k, v in error_summary.error_counts.items())
                lines.append(f"  Types:            {types_str}")
        return "\n".join(lines)

    # Markdown format
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
        f"| Thinking | {event_counts['thinking']} |",
        f"| Observations | {event_counts['observations']} |",
        f"| Finish | {event_counts['finish']} |",
        f"| **Total** | **{total}** |",
    ])
    # Add error info if present
    if error_summary and error_summary.has_errors:
        lines.extend([
            "",
            "**Errors:**",
            f"- Terminal: {error_summary.terminal_count}",
            f"- Recovered: {error_summary.recovered_count}",
        ])
        if error_summary.error_counts:
            types_str = ", ".join(f"{k}: {v}" for k, v in error_summary.error_counts.items())
            lines.append(f"- Types: {types_str}")
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
    full_output: bool = False,
    debug_tool_call: bool = False,
    error_summary: "ErrorSummary | None" = None,
) -> str:
    """Format full output with events."""
    if fmt == "json":
        return _format_show_json(conv_id, title, first_ts, last_ts, event_counts, events, error_summary)

    # For markdown and text formats
    header = _format_show_stats(conv_id, title, first_ts, last_ts, event_counts, fmt, error_summary)
    separator = "\n---\n\n" if fmt == "markdown" else "\n" + "=" * 60 + "\n\n"

    event_lines = []
    for event in events:
        formatted = _format_event(
            event, fmt, timestamps, action_details, thinking,
            full_output=full_output, debug_tool_call=debug_tool_call,
        )
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
    error_summary: "ErrorSummary | None" = None,
) -> str:
    """Format output as JSON."""
    duration = (last_ts - first_ts) if (first_ts and last_ts) else None
    total = sum(event_counts.values())

    formatted_events = []
    for event in events:
        formatted_events.append(_extract_event_data(event))

    result = {
        "id": conv_id,
        "title": title,
        "started": first_ts.isoformat() if first_ts else None,
        "ended": last_ts.isoformat() if last_ts else None,
        "duration_seconds": duration.total_seconds() if duration else None,
        "counts": event_counts,
        "total_events": total,
        "events": formatted_events,
    }
    if error_summary:
        result["errors"] = {
            "total": error_summary.total_errors,
            "terminal": error_summary.terminal_count,
            "recovered": error_summary.recovered_count,
            "has_terminal_error": error_summary.has_terminal_error,
            "error_counts": error_summary.error_counts,
        }
    return json.dumps(result, indent=2)


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


def _extract_thinking_content(event: dict) -> str:
    """Extract thinking/reasoning content from an action event.

    Handles multiple formats:
    - Think tool (cloud): action.thought contains the thought text
    - Think tool (local CLI): thought field as list of content items
    - General reasoning: reasoning_content field
    - Thinking blocks: thinking_blocks list with type="thinking"
    """
    parts = []

    # Think tool: action.thought (cloud format)
    action = event.get("action", {})
    if isinstance(action, dict):
        action_thought = action.get("thought", "")
        if action_thought and isinstance(action_thought, str):
            parts.append(action_thought)

    # Think tool: thought field (local CLI format - list of content items)
    thought = event.get("thought", [])
    if isinstance(thought, list):
        for item in thought:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)
    elif isinstance(thought, str) and thought:
        parts.append(thought)

    # General reasoning content
    reasoning = event.get("reasoning_content", "")
    if reasoning:
        parts.append(reasoning)

    # Thinking blocks (alternative format)
    thinking_blocks = event.get("thinking_blocks", [])
    if isinstance(thinking_blocks, list):
        for block in thinking_blocks:
            if isinstance(block, dict) and block.get("type") == "thinking":
                text = block.get("thinking", "")
                if text:
                    parts.append(text)

    return "\n\n".join(parts)


def _format_event(
    event: dict,
    fmt: str,
    timestamps: bool,
    action_details: bool,
    thinking: bool,
    full_output: bool = False,
    debug_tool_call: bool = False,
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
            thinking_content = _extract_thinking_content(event)
            if thinking_content:
                if fmt == "markdown":
                    lines.append(f"### {ts_prefix}Thinking")
                    # Quote each line for markdown blockquote
                    quoted = "\n> ".join(thinking_content.split("\n"))
                    lines.append(f"> {quoted}")
                else:
                    lines.append(f"{ts_prefix}THINKING: {thinking_content}")

        # Action summary or details
        if fmt == "markdown":
            lines.append(f"## {ts_prefix}Action: {tool_name}")
            if summary:
                lines.append(f"*{summary}*")
            if action_details:
                detail_text = _format_action_details(tool_name, action)
                if detail_text:
                    lines.append(f"```\n{detail_text}\n```")
            if debug_tool_call:
                tool_call = event.get("tool_call", {})
                if tool_call:
                    lines.append("**Raw tool_call:**")
                    lines.append(f"```json\n{json.dumps(tool_call, indent=2)}\n```")
        else:
            lines.append(f"{ts_prefix}ACTION ({tool_name}): {summary}")
            if action_details:
                detail_text = _format_action_details(tool_name, action)
                if detail_text:
                    lines.append(detail_text)
            if debug_tool_call:
                tool_call = event.get("tool_call", {})
                if tool_call:
                    lines.append(f"  [tool_call: {json.dumps(tool_call)}]")

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
        obs = event.get("observation", {})
        content = _extract_observation_content(event)
        exit_code = obs.get("exit_code")

        # Build header with exit code
        exit_info = f" [exit: {exit_code}]" if exit_code is not None else ""

        # Add metadata for debug mode
        metadata_info = ""
        if debug_tool_call:
            metadata = obs.get("metadata", {})
            working_dir = metadata.get("working_dir") or obs.get("path", "")
            if working_dir:
                metadata_info = f" cwd: {working_dir}"

        if fmt == "markdown":
            lines.append(f"## {ts_prefix}Output ({tool_name}){exit_info}")
            if metadata_info:
                lines.append(f"*{metadata_info.strip()}*")
            lines.append("```")
            if full_output:
                lines.append(content)
            else:
                lines.append(content[:2000] if len(content) > 2000 else content)
                if len(content) > 2000:
                    lines.append(f"... (truncated, {len(content)} chars total)")
            lines.append("```")
        else:
            header = f"{ts_prefix}OUTPUT ({tool_name}){exit_info}:"
            if metadata_info:
                header = f"{ts_prefix}OUTPUT ({tool_name}){exit_info} [{metadata_info.strip()}]:"
            lines.append(header)
            if full_output:
                lines.append(content)
            else:
                truncated = content[:2000] if len(content) > 2000 else content
                lines.append(truncated)
                if len(content) > 2000:
                    lines.append(f"... (truncated, {len(content)} chars total)")

    return "\n".join(lines)


def _format_action_details(tool_name: str, action: dict) -> str:
    """Format action details in a human-readable way based on tool type."""
    action_kind = action.get("kind", "")

    if action_kind == "TerminalAction" or tool_name == "terminal":
        command = action.get("command", "")
        if command:
            return f"$ {command}"
        return ""

    elif action_kind == "FileEditorAction" or tool_name == "file_editor":
        cmd = action.get("command", "")
        path = action.get("path", "")
        if cmd == "view":
            view_range = action.get("view_range")
            if view_range:
                return f"view {path} [lines {view_range[0]}-{view_range[1]}]"
            return f"view {path}"
        elif cmd == "create":
            return f"create {path}"
        elif cmd == "str_replace":
            return f"edit {path} (str_replace)"
        elif cmd == "insert":
            line = action.get("insert_line", "?")
            return f"edit {path} (insert after line {line})"
        elif cmd == "undo_edit":
            return f"undo_edit {path}"
        return f"{cmd} {path}" if cmd else path

    elif action_kind == "ThinkAction" or tool_name == "think":
        thought = action.get("thought", "")
        if thought:
            return thought[:200] + "..." if len(thought) > 200 else thought
        return ""

    elif action_kind == "FinishAction" or tool_name == "finish":
        message = action.get("message", "")
        if message:
            return message[:200] + "..." if len(message) > 200 else message
        return ""

    # For other tools, show key parameters (excluding 'kind')
    params = {k: v for k, v in action.items() if k != "kind" and v is not None}
    if params:
        # Format as key=value pairs
        parts = []
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 100:
                v = v[:100] + "..."
            parts.append(f"{k}={v}")
        return ", ".join(parts)
    return ""


@main.command()
@click.argument("conversation_id")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def errors(
    conversation_id: str,
    fmt: str,
    verbose: bool,
) -> None:
    """Show agent/LLM error summary for a conversation.
    
    Analyzes a conversation for ConversationErrorEvent and AgentErrorEvent
    occurrences. These are errors that impact agent behavior - not routine
    terminal command failures.
    
    Terminal errors cause the conversation to stop. Recovered errors occurred
    but the agent continued working.
    
    Example:
    
        ohtv errors abc123
    """
    from ohtv.errors import analyze_conversation, format_error_type_counts
    
    _init_logging(verbose=verbose)
    config = Config.from_env()
    
    result = _find_conversation_dir(config, conversation_id)
    if not result:
        console.print(f"[red]Error:[/red] Conversation not found: {conversation_id}")
        raise SystemExit(1)
    conv_dir, is_cloud = result
    
    # Get conversation info
    conv_id, title = _get_conversation_info(conv_dir)
    
    # Analyze for errors
    summary = analyze_conversation(conv_dir, conv_id)
    
    if fmt == "json":
        output = {
            "conversation_id": summary.conversation_id,
            "execution_status": summary.execution_status,
            "total_errors": summary.total_errors,
            "terminal_count": summary.terminal_count,
            "recovered_count": summary.recovered_count,
            "has_terminal_error": summary.has_terminal_error,
            "error_counts": summary.error_counts,
            "errors": [
                {
                    "event_index": e.event_index,
                    "event_id": e.event_id,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "error_type": e.error_type.value,
                    "severity": e.severity.value,
                    "code": e.code,
                    "message": e.message,
                    "tool_name": e.tool_name,
                }
                for e in summary.errors
            ],
        }
        print(json.dumps(output, indent=2))
        return
    
    # Text output
    console.print(f"[bold]Error Summary for[/bold] [cyan]{conv_id[:12]}...[/cyan]")
    if title:
        console.print(f"[dim]{title[:60]}{'...' if len(title) > 60 else ''}[/dim]")
    console.print()
    
    if not summary.has_errors:
        console.print("[green]✓[/green] No agent/LLM errors in this conversation")
        if summary.execution_status:
            console.print(f"[dim]Execution status: {summary.execution_status}[/dim]")
        return
    
    # Overview
    status_color = "red" if summary.has_terminal_error else "yellow"
    status_text = "TERMINAL" if summary.has_terminal_error else "RECOVERED"
    console.print(f"[bold]Overview:[/bold] {summary.total_errors} error(s) [{status_color}]{status_text}[/{status_color}]")
    if summary.execution_status:
        console.print(f"[dim]Execution status: {summary.execution_status}[/dim]")
    console.print()
    
    # Terminal errors (if any)
    terminal_errors = [e for e in summary.errors if e.severity.value == "terminal"]
    if terminal_errors:
        console.print("[bold red]Terminal Error(s):[/bold red]")
        for err in terminal_errors:
            _print_error_detail(err)
        console.print()
    
    # Recovered errors (if any)
    recovered_errors = [e for e in summary.errors if e.severity.value == "recovered"]
    if recovered_errors:
        console.print("[bold yellow]Recovered Error(s):[/bold yellow]")
        for err in recovered_errors:
            _print_error_detail(err)


def _print_error_detail(err) -> None:
    """Print details for a single error."""
    from ohtv.errors import ErrorInfo
    
    # Timestamp
    ts_str = ""
    if err.timestamp:
        local_time = err.timestamp.astimezone()
        ts_str = local_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Header line
    console.print(f"  [dim][{err.event_index}][/dim] {ts_str} [bold]{err.error_type.value}[/bold]")
    
    # Code (if present)
    if err.code:
        console.print(f"       Code: [cyan]{err.code}[/cyan]")
    
    # Tool name (if present)
    if err.tool_name:
        console.print(f"       Tool: {err.tool_name}")
    
    # Message/detail
    if err.message:
        # Truncate long messages
        msg = err.message
        if len(msg) > 200:
            msg = msg[:200] + "..."
        console.print(f"       Detail: {msg}")


@main.command()
@click.argument("conversation_id", required=False)
@click.option("--max", "-n", "limit", type=int, help="Maximum conversations to process")
@click.option("--all", "-A", "show_all", is_flag=True, help="Process all matching conversations (no limit)")
@click.option("--offset", "-k", type=int, default=0, help="Skip first N conversations")
@click.option("--since", "-S", "since_date", help="Process conversations from DATE onwards")
@click.option("--until", "-U", "until_date", help="Process conversations up to DATE")
@click.option("--day", "-D", "day_date", is_flag=False, flag_value="today", default=None,
              help="Process conversations from a single day (default: today)")
@click.option("--week", "-W", "week_date", is_flag=False, flag_value="today", default=None,
              help="Process conversations from the week containing DATE (default: today)")
@click.option("--pr", "pr_filter", help="Filter by PR (URL, owner/repo#N, or repo#N)")
@click.option("--repo", "repo_filter", help="Filter by repo (URL, owner/repo, or repo name)")
@click.option("--action", "action_filter", help="Filter by action type (e.g., git-push, pushed, open-pr)")
@click.option("--reverse", is_flag=True, help="Show oldest first (default: newest first)")
@click.option("--prs-only", is_flag=True, help="Output only PR/MR references")
@click.option("--repos-only", is_flag=True, help="Output only repository references")
@click.option("--issues-only", is_flag=True, help="Output only issue references")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["table", "lines", "csv", "json"]),
    default=None,
    help="Output format (default: table for rich display, or specify for machine-readable)",
)
@click.option("-1", "one_per_line", is_flag=True, help="Shorthand for --format lines")
@click.option("--actions", "-a", is_flag=True, help="Show only refs with detected interactions (read or write)")
@click.option("--write-only", "-w", is_flag=True, help="Show only refs with write actions (pushed, created, merged, etc.)")
@click.option("--no-index", is_flag=True, help="Skip database indexing (faster, but refs won't be queryable)")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def refs(
    conversation_id: str | None,
    limit: int | None,
    show_all: bool,
    offset: int,
    since_date: str | None,
    until_date: str | None,
    day_date: str | None,
    week_date: str | None,
    pr_filter: str | None,
    repo_filter: str | None,
    action_filter: str | None,
    reverse: bool,
    prs_only: bool,
    repos_only: bool,
    issues_only: bool,
    fmt: str | None,
    one_per_line: bool,
    actions: bool,
    write_only: bool,
    no_index: bool,
    verbose: bool,
) -> None:
    """Extract repository, issue, and PR references from conversations.

    \b
    Single conversation mode:
      ohtv refs abc123              # Rich display of refs from one conversation
      ohtv refs abc123 --prs-only -1  # Just PR URLs, one per line

    \b
    Multi-conversation mode (requires at least one filter):
      ohtv refs -D --prs-only -1      # All PRs from today's conversations
      ohtv refs -W --repos-only       # Repos from this week
      ohtv refs --pr owner/repo#42    # Refs from conversations that touched PR#42

    \b
    Output formats:
      table   Rich formatted display (default for single conversation)
      lines   One URL per line (for piping)
      csv     Comma-separated URLs
      json    JSON object with refs by type

    Shows what actions were taken on each reference:
    - Repositories: cloned, pushed
    - Pull Requests: created, pushed, commented, merged, closed, reviewed
    - Issues: created, commented, closed

    By default, indexes conversations in the database for future queries.
    Use --no-index to skip this (faster for one-off lookups).
    """
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Handle -1 shorthand
    if one_per_line:
        fmt = "lines"

    # Validate ref type filters (mutually exclusive)
    type_filters = [prs_only, repos_only, issues_only]
    if sum(type_filters) > 1:
        console.print("[red]Error:[/red] --prs-only, --repos-only, and --issues-only are mutually exclusive")
        raise SystemExit(1)

    # Determine mode based on arguments
    has_filters = any([since_date, until_date, day_date, week_date, pr_filter, repo_filter, action_filter])

    if conversation_id:
        # Single conversation mode
        _refs_single_conversation(
            config=config,
            conversation_id=conversation_id,
            prs_only=prs_only,
            repos_only=repos_only,
            issues_only=issues_only,
            fmt=fmt,
            actions=actions,
            write_only=write_only,
            no_index=no_index,
            verbose=verbose,
        )
    elif has_filters:
        # Multi-conversation mode
        _refs_multi_conversation(
            config=config,
            limit=limit,
            show_all=show_all,
            offset=offset,
            since_date=since_date,
            until_date=until_date,
            day_date=day_date,
            week_date=week_date,
            pr_filter=pr_filter,
            repo_filter=repo_filter,
            action_filter=action_filter,
            reverse=reverse,
            prs_only=prs_only,
            repos_only=repos_only,
            issues_only=issues_only,
            fmt=fmt,
            actions=actions,
            write_only=write_only,
            no_index=no_index,
            verbose=verbose,
        )
    else:
        # No conversation_id and no filters - show help
        console.print("[yellow]Usage:[/yellow] Provide a conversation ID or at least one filter.")
        console.print()
        console.print("Examples:")
        console.print("  ohtv refs abc123              # Refs from specific conversation")
        console.print("  ohtv refs -D --prs-only -1    # PRs from today, one per line")
        console.print("  ohtv refs -W                  # All refs from this week")
        console.print()
        console.print("Run [bold]ohtv refs --help[/bold] for full options.")
        raise SystemExit(1)


def _refs_single_conversation(
    *,
    config: Config,
    conversation_id: str,
    prs_only: bool,
    repos_only: bool,
    issues_only: bool,
    fmt: str | None,
    actions: bool,
    write_only: bool,
    no_index: bool,
    verbose: bool,
) -> None:
    """Handle refs command for a single conversation."""
    # Search both local and cloud sources
    result = _find_conversation_dir(config, conversation_id)

    if not result:
        console.print(f"[red]Error:[/red] Conversation '{conversation_id}' not found")
        raise SystemExit(1)
    conv_dir, _ = result  # We don't need is_cloud for refs

    # Get conversation metadata
    conv_id, title = _get_conversation_info(conv_dir)

    # Index conversation in DB (unless --no-index)
    if not no_index:
        _ensure_refs_indexed(conv_id, conv_dir, verbose)

    # Extract references from events
    extracted = _extract_refs_from_conversation(conv_dir)

    # Apply type filter if specified
    if prs_only:
        extracted = {"repos": set(), "issues": set(), "prs": extracted["prs"]}
    elif repos_only:
        extracted = {"repos": extracted["repos"], "issues": set(), "prs": set()}
    elif issues_only:
        extracted = {"repos": set(), "issues": extracted["issues"], "prs": set()}

    if not any(extracted.values()):
        if fmt in ("lines", "csv", "json"):
            # Machine-readable: output empty result
            _output_refs_formatted(extracted, fmt)
        else:
            console.print("[dim]No repository references found.[/dim]")
        return

    # Detect interactions for each ref
    interactions = _detect_interactions_from_conversation(conv_dir, extracted)

    # Filter by write actions only if requested
    if write_only:
        extracted = _filter_refs_by_write_actions(extracted, interactions)
        if not any(extracted.values()):
            if fmt in ("lines", "csv", "json"):
                _output_refs_formatted(extracted, fmt)
            else:
                console.print("[dim]No write actions detected.[/dim]")
            return
    # Filter by any actions if requested (read or write)
    elif actions:
        extracted = _filter_refs_by_actions(extracted, interactions)
        if not any(extracted.values()):
            if fmt in ("lines", "csv", "json"):
                _output_refs_formatted(extracted, fmt)
            else:
                console.print("[dim]No interactions detected.[/dim]")
            return

    # Output based on format
    if fmt in ("lines", "csv", "json"):
        _output_refs_formatted(extracted, fmt)
    else:
        # Rich display (default)
        _display_conversation_header(conv_id, title)
        if write_only:
            _display_write_actions_only(interactions)
        elif actions:
            _display_actions_only(interactions)
        else:
            _display_refs(extracted, interactions)


def _refs_multi_conversation(
    *,
    config: Config,
    limit: int | None,
    show_all: bool,
    offset: int,
    since_date: str | None,
    until_date: str | None,
    day_date: str | None,
    week_date: str | None,
    pr_filter: str | None,
    repo_filter: str | None,
    action_filter: str | None,
    reverse: bool,
    prs_only: bool,
    repos_only: bool,
    issues_only: bool,
    fmt: str | None,
    actions: bool,
    write_only: bool,
    no_index: bool,
    verbose: bool,
) -> None:
    """Handle refs command for multiple conversations (filtered)."""
    # Parse date filters
    since, until = _parse_date_filters(since_date, until_date, day_date, week_date)

    # Apply conversation filters
    filter_result = _apply_conversation_filters(
        config,
        since=since,
        until=until,
        pr_filter=pr_filter,
        repo_filter=repo_filter,
        action_filter=action_filter,
        include_empty=False,
        initial_show_all=show_all,
    )

    conversations = filter_result.conversations
    show_all = filter_result.show_all

    # Sort by created_at (newest first by default)
    conversations = sorted(
        conversations,
        key=lambda c: _normalize_datetime_for_sort(c.created_at),
        reverse=not reverse,
    )

    # Apply offset and limit
    if offset:
        conversations = conversations[offset:]
    if limit is not None:
        conversations = conversations[:limit]
    elif not show_all:
        conversations = conversations[:10]

    if not conversations:
        if fmt in ("lines", "csv", "json"):
            _output_refs_formatted({"repos": set(), "issues": set(), "prs": set()}, fmt)
        else:
            console.print("[dim]No conversations found matching the criteria.[/dim]")
        return

    # Aggregate refs from all conversations
    aggregated: dict[str, set[str]] = {
        "repos": set(),
        "issues": set(),
        "prs": set(),
    }

    for conv in conversations:
        # Find conversation directory
        result = _find_conversation_dir(config, conv.id)
        if not result:
            continue
        conv_dir, _ = result

        # Index if needed
        if not no_index:
            _ensure_refs_indexed(conv.id, conv_dir, verbose)

        # Extract refs
        extracted = _extract_refs_from_conversation(conv_dir)

        # Filter by write actions only if requested
        if write_only:
            interactions = _detect_interactions_from_conversation(conv_dir, extracted)
            extracted = _filter_refs_by_write_actions(extracted, interactions)
        # Filter by any actions if requested (read or write)
        elif actions:
            interactions = _detect_interactions_from_conversation(conv_dir, extracted)
            extracted = _filter_refs_by_actions(extracted, interactions)

        # Aggregate
        aggregated["repos"].update(extracted["repos"])
        aggregated["issues"].update(extracted["issues"])
        aggregated["prs"].update(extracted["prs"])

    # Apply type filter
    if prs_only:
        aggregated = {"repos": set(), "issues": set(), "prs": aggregated["prs"]}
    elif repos_only:
        aggregated = {"repos": aggregated["repos"], "issues": set(), "prs": set()}
    elif issues_only:
        aggregated = {"repos": set(), "issues": aggregated["issues"], "prs": set()}

    if not any(aggregated.values()):
        if fmt in ("lines", "csv", "json"):
            _output_refs_formatted(aggregated, fmt)
        else:
            console.print("[dim]No repository references found.[/dim]")
        return

    # Output based on format
    if fmt in ("lines", "csv", "json"):
        _output_refs_formatted(aggregated, fmt)
    else:
        # Rich display for table format or default
        console.print(f"[dim]Aggregated from {len(conversations)} conversation(s)[/dim]")
        _display_refs(aggregated, interactions=None)


def _filter_refs_by_actions(
    refs: dict[str, set[str]],
    interactions: RefInteractions,
) -> dict[str, set[str]]:
    """Filter refs to only include those with any detected interactions (read or write)."""
    return {
        "repos": refs["repos"] & set(interactions.repos.keys()),
        "issues": refs["issues"] & set(interactions.issues.keys()),
        "prs": refs["prs"] & set(interactions.prs.keys()),
    }


def _filter_refs_by_write_actions(
    refs: dict[str, set[str]],
    interactions: RefInteractions,
) -> dict[str, set[str]]:
    """Filter refs to only include those with write actions (not just read).
    
    Write actions: pushed, committed, created, commented, reviewed, merged, closed
    Read actions (excluded): cloned, fetched, pulled, viewed, browsed, api_called
    """
    result: dict[str, set[str]] = {
        "repos": set(),
        "issues": set(),
        "prs": set(),
    }
    
    # Filter repos - only include if any interaction is a write action
    for url in refs["repos"]:
        url_actions = interactions.repos.get(url, set())
        if url_actions & WRITE_ACTIONS:
            result["repos"].add(url)
    
    # Filter issues - only include if any interaction is a write action
    for url in refs["issues"]:
        url_actions = interactions.issues.get(url, set())
        if url_actions & WRITE_ACTIONS:
            result["issues"].add(url)
    
    # Filter PRs - only include if any interaction is a write action
    for url in refs["prs"]:
        url_actions = interactions.prs.get(url, set())
        if url_actions & WRITE_ACTIONS:
            result["prs"].add(url)
    
    return result


def _output_refs_formatted(refs: dict[str, set[str]], fmt: str) -> None:
    """Output refs in machine-readable format."""
    # Collect all URLs
    all_urls: list[str] = []
    all_urls.extend(sorted(refs["repos"]))
    all_urls.extend(sorted(refs["issues"]))
    all_urls.extend(sorted(refs["prs"]))

    if fmt == "lines":
        for url in all_urls:
            print(url)
    elif fmt == "csv":
        print(",".join(all_urls))
    elif fmt == "json":
        output = {
            "repos": sorted(refs["repos"]),
            "issues": sorted(refs["issues"]),
            "prs": sorted(refs["prs"]),
        }
        print(json.dumps(output, indent=2))


def _ensure_refs_indexed(conv_id: str, conv_dir: Path, verbose: bool = False) -> None:
    """Ensure conversation is indexed with refs in the database.
    
    Runs scan + refs processing if needed, silently.
    """
    from ohtv.db import get_connection, migrate
    from ohtv.db.models import Conversation
    from ohtv.db.scanner import count_events, get_events_mtime
    from ohtv.db.stages import process_refs
    from ohtv.db.stores import ConversationStore, StageStore
    
    with get_connection() as conn:
        migrate(conn)
        
        # Check if conversation needs processing
        conv_store = ConversationStore(conn)
        stage_store = StageStore(conn)
        
        conv = conv_store.get(conv_id)
        events_dir = conv_dir / "events"
        current_event_count = count_events(events_dir)
        
        needs_processing = False
        
        if conv is None:
            # Not registered - register it
            conv = Conversation(
                id=conv_id,
                location=str(conv_dir),
                events_mtime=get_events_mtime(events_dir),
                event_count=current_event_count,
            )
            conv_store.upsert(conv)
            needs_processing = True
            if verbose:
                console.print(f"[dim]Registered conversation in database[/dim]")
        elif stage_store.needs_processing(conv_id, "refs", current_event_count):
            # Update event count if needed
            if conv.event_count != current_event_count:
                conv = Conversation(
                    id=conv_id,
                    location=str(conv_dir),
                    events_mtime=get_events_mtime(events_dir),
                    event_count=current_event_count,
                )
                conv_store.upsert(conv)
            needs_processing = True
        
        if needs_processing:
            if verbose:
                console.print(f"[dim]Indexing refs...[/dim]")
            process_refs(conn, conv)
        
        conn.commit()


def _display_objectives(conv_id: str, title: str, analysis: "ObjectiveAnalysis") -> None:
    """Display objective analysis with rich formatting."""
    detail_level = getattr(analysis, "detail_level", "brief")
    has_assessment = getattr(analysis, "assess", False)

    # Status formatting
    status_colors = {
        "achieved": "green",
        "not_achieved": "red",
        "in_progress": "blue",
    }
    status_icons = {
        "achieved": "✓",
        "not_achieved": "✗",
        "in_progress": "→",
    }

    def format_status(status: str | None) -> str:
        if not status:
            return ""
        color = status_colors.get(status, "white")
        icon = status_icons.get(status, "•")
        label = status.replace("_", " ").title()
        return f" [{color}]{icon} {label}[/{color}]"

    # Brief mode - minimal output
    if detail_level == "brief":
        if analysis.goal:
            status_str = format_status(analysis.status) if has_assessment else ""
            console.print(f"\n[bold]Goal:[/bold] {analysis.goal}{status_str}")
        else:
            console.print("\n[dim]No goal identified.[/dim]")
        return

    # Standard mode - goal + outcomes
    if detail_level == "standard":
        if analysis.goal:
            status_str = format_status(analysis.status) if has_assessment else ""
            console.print(f"\n[bold]Goal:[/bold] {analysis.goal}{status_str}")

        if analysis.primary_outcomes:
            console.print("\n[bold]Primary Outcomes:[/bold]")
            for outcome in analysis.primary_outcomes:
                console.print(f"  • {outcome}")

        if analysis.secondary_outcomes:
            console.print("\n[bold]Secondary Outcomes:[/bold]")
            for outcome in analysis.secondary_outcomes:
                console.print(f"  • {outcome}")

        if not analysis.goal and not analysis.primary_outcomes:
            console.print("\n[dim]No objectives identified.[/dim]")
        return

    # Detailed mode - full hierarchical analysis (legacy behavior)
    from ohtv.analysis import Objective, ObjectiveStatus

    # Header
    _display_conversation_header(conv_id, title)

    # Summary
    if analysis.summary:
        console.print(f"\n[bold]Summary:[/bold] {analysis.summary}")

    # Status colors
    status_colors = {
        ObjectiveStatus.ACHIEVED: "green",
        ObjectiveStatus.NOT_ACHIEVED: "red",
        ObjectiveStatus.IN_PROGRESS: "blue",
    }

    status_icons = {
        ObjectiveStatus.ACHIEVED: "✓",
        ObjectiveStatus.NOT_ACHIEVED: "✗",
        ObjectiveStatus.IN_PROGRESS: "→",
    }

    def add_objective_to_tree(tree: Tree, obj: Objective, level: int = 0) -> None:
        """Recursively add objectives to tree."""
        # Only show status formatting when assessment is present
        if has_assessment and obj.status:
            color = status_colors.get(obj.status, "white")
            icon = status_icons.get(obj.status, "•")
            status_label = obj.status.value.replace("_", " ").title()
            text = f"[{color}]{icon}[/{color}] {obj.description} [{color}][{status_label}][/{color}]"

            # Add evidence if present
            if obj.evidence:
                text += f"\n   [dim]Evidence: {obj.evidence[:100]}{'...' if len(obj.evidence) > 100 else ''}[/dim]"
        else:
            # No assessment - just show bullet and description
            text = f"• {obj.description}"

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
    context_level = getattr(analysis, "context_level", "default")
    console.print(
        f"\n[dim]Analyzed: {analysis.analyzed_at.strftime('%Y-%m-%d %H:%M')} UTC • "
        f"Model: {analysis.model_used} • Context: {context_level}[/dim]"
    )


def _display_outputs(conv_dir: Path) -> None:
    """Display outputs (repos, PRs, issues modified) for a conversation."""
    # Extract references and detect interactions
    refs = _extract_refs_from_conversation(conv_dir)

    # Even if no refs, we might have unpushed commits to warn about
    interactions = _detect_interactions_from_conversation(conv_dir, refs)

    # Show items that have write actions or unpushed commits
    has_actions = (
        any(interactions.repos.values())
        or any(interactions.prs.values())
        or any(interactions.issues.values())
    )
    has_unpushed = bool(interactions.unpushed_commits)

    if not has_actions and not has_unpushed:
        return  # Nothing to display

    console.print("\n[bold]Outputs:[/bold]")
    _display_actions_only(interactions)


def _get_conversation_outputs(conv_dir: Path) -> dict:
    """Extract outputs (repos, PRs, issues with interactions) from a conversation.

    Returns a dict with:
        - refs: dict with 'repos', 'prs', 'issues' sets of URLs
        - interactions: RefInteractions object with write actions
        - unpushed_commits: set of directory paths with commits but no push
    
    Note: Repos are filtered to only include those with detected interactions,
    to avoid noise from incidental mentions (error messages, user pastes, etc.).
    PRs and issues are kept as-is since their URLs are specific enough.
    """
    refs = _extract_refs_from_conversation(conv_dir)
    interactions = _detect_interactions_from_conversation(conv_dir, refs)

    # Filter repos to only those with detected interactions
    # This matches the behavior of database indexing in refs.py
    filtered_repos = {
        url for url in refs["repos"]
        if url in interactions.repos
    }
    refs["repos"] = filtered_repos

    return {
        "refs": refs,
        "interactions": interactions,
        "unpushed_commits": interactions.unpushed_commits,
    }


def _format_refs_for_summary(outputs: dict | None) -> list[str]:
    """Format refs info for display in summary table.

    Returns a list of formatted lines to append to summary cell.
    """
    if not outputs:
        return []

    refs = outputs.get("refs", {})
    interactions = outputs.get("interactions")
    unpushed_commits = outputs.get("unpushed_commits", set())

    lines = []

    # Format repos with interactions
    repos = sorted(refs.get("repos", set()))
    if repos:
        repo_parts = []
        for url in repos:
            short_url = url.replace("https://github.com/", "").replace("https://gitlab.com/", "").replace("https://bitbucket.org/", "")
            annotation = ""
            if interactions and url in interactions.repos:
                actions = sorted(interactions.repos[url])
                annotation = f" [dim]\\[{', '.join(actions)}][/dim]"
            repo_parts.append(f"{short_url}{annotation}")
        lines.append("[blue]Repos:[/blue] " + ", ".join(repo_parts))

    # Format PRs with interactions
    prs = sorted(refs.get("prs", set()))
    if prs:
        pr_parts = []
        for url in prs:
            short_url = url.replace("https://github.com/", "").replace("https://gitlab.com/", "").replace("https://bitbucket.org/", "")
            annotation = ""
            if interactions and url in interactions.prs:
                actions = sorted(interactions.prs[url])
                annotation = f" [dim]\\[{', '.join(actions)}][/dim]"
            pr_parts.append(f"{short_url}{annotation}")
        lines.append("[green]PRs:[/green] " + ", ".join(pr_parts))

    # Format issues with interactions
    issues = sorted(refs.get("issues", set()))
    if issues:
        issue_parts = []
        for url in issues:
            short_url = url.replace("https://github.com/", "").replace("https://gitlab.com/", "").replace("https://bitbucket.org/", "")
            annotation = ""
            if interactions and url in interactions.issues:
                actions = sorted(interactions.issues[url])
                annotation = f" [dim]\\[{', '.join(actions)}][/dim]"
            issue_parts.append(f"{short_url}{annotation}")
        lines.append("[yellow]Issues:[/yellow] " + ", ".join(issue_parts))

    # Format unpushed commits warning
    if unpushed_commits:
        unpushed_parts = []
        for path in sorted(unpushed_commits):
            display_path = path.replace(str(Path.home()), "~")
            unpushed_parts.append(display_path)
        lines.append("[bold yellow]⚠ Unpushed:[/bold yellow] " + ", ".join(unpushed_parts))

    return lines


def _print_summary_table(
    results: list[dict],
    total_count: int,
    error_count: int,
    *,
    include_outputs: bool = True,
    display_schema: "DisplaySchema | None" = None,
    variant: str | None = None,
) -> None:
    """Print summary results as a table.
    
    Args:
        results: List of result dictionaries from analysis
        total_count: Total number of conversations (for summary)
        error_count: Number of errors
        include_outputs: Whether to include refs/outputs in output
        display_schema: Optional display schema from prompt for variant-aware rendering
        variant: Current prompt variant name (for show_when filtering)
    """
    from ohtv.prompts import TableRenderer, get_default_display_schema, DisplaySchema
    
    # Use display schema if provided, otherwise fall back to default
    schema = display_schema if display_schema and display_schema.columns else get_default_display_schema()
    
    # Add refs/outputs to results if needed (for default schema with Summary column)
    if include_outputs:
        for r in results:
            if r.get("outputs"):
                # Store formatted refs in result for display schema access
                ref_lines = _format_refs_for_summary(r["outputs"])
                r["refs_display"] = "\n".join(ref_lines) if ref_lines else ""
    
    # Use TableRenderer for schema-based rendering
    renderer = TableRenderer(schema, console=console)
    
    renderer.render(
        results,
        variant=variant,
        show_summary=True,
        total_count=total_count,
        error_count=error_count,
    )


def _format_refs_for_markdown(outputs: dict | None) -> list[str]:
    """Format refs info for markdown output.

    Returns a list of markdown sub-items.
    """
    if not outputs:
        return []

    refs = outputs.get("refs", {})
    interactions = outputs.get("interactions")
    unpushed_commits = outputs.get("unpushed_commits", set())

    lines = []

    # Format repos with interactions
    for url in sorted(refs.get("repos", set())):
        short_url = url.replace("https://github.com/", "").replace("https://gitlab.com/", "").replace("https://bitbucket.org/", "")
        annotation = ""
        if interactions and url in interactions.repos:
            actions = sorted(interactions.repos[url])
            annotation = f" [{', '.join(actions)}]"
        lines.append(f"  - Repo: {short_url}{annotation}")

    # Format PRs with interactions
    for url in sorted(refs.get("prs", set())):
        short_url = url.replace("https://github.com/", "").replace("https://gitlab.com/", "").replace("https://bitbucket.org/", "")
        annotation = ""
        if interactions and url in interactions.prs:
            actions = sorted(interactions.prs[url])
            annotation = f" [{', '.join(actions)}]"
        lines.append(f"  - PR: {short_url}{annotation}")

    # Format issues with interactions
    for url in sorted(refs.get("issues", set())):
        short_url = url.replace("https://github.com/", "").replace("https://gitlab.com/", "").replace("https://bitbucket.org/", "")
        annotation = ""
        if interactions and url in interactions.issues:
            actions = sorted(interactions.issues[url])
            annotation = f" [{', '.join(actions)}]"
        lines.append(f"  - Issue: {short_url}{annotation}")

    # Format unpushed commits warning
    for path in sorted(unpushed_commits):
        display_path = path.replace(str(Path.home()), "~")
        lines.append(f"  - ⚠️ Unpushed: {display_path}")

    return lines


def _format_summary_markdown(results: list[dict], *, include_outputs: bool = True) -> str:
    """Format summary results as markdown."""
    lines = []

    for r in results:
        date_str = ""
        if r["created_at"]:
            local_time = r["created_at"].astimezone()
            date_str = local_time.strftime("%Y-%m-%d")

        # Format as a list item with date and goal
        lines.append(f"- **{r['short_id']}** ({date_str}): {r['goal']}")

        # Add refs/outputs as sub-items if present
        if include_outputs and r.get("outputs"):
            ref_lines = _format_refs_for_markdown(r["outputs"])
            lines.extend(ref_lines)

    return "\n".join(lines)


def _find_conversation_dir(config: Config, conv_id: str) -> tuple[Path, bool] | None:
    """Find conversation directory across local, cloud, and extra sources.

    Returns:
        Tuple of (directory_path, is_cloud_source) or None if not found
        Note: is_cloud_source indicates whether timestamps are UTC (True) or local (False)
    """
    # Normalize conv_id - remove dashes for directory lookup
    # (ConversationInfo.id has dashes, but directory names don't)
    normalized_id = conv_id.replace("-", "")
    
    # Search all directories - local first, then cloud, then extra
    dirs_to_search = [
        (config.local_conversations_dir, False),  # (path, is_cloud)
        (config.synced_conversations_dir, True),
    ]
    
    # Add extra paths (assume UTC timestamps like cloud)
    for extra_path in config.extra_conversation_paths:
        dirs_to_search.append((extra_path, True))

    all_matches: list[tuple[Path, bool]] = []

    for base_dir, is_cloud in dirs_to_search:
        if not base_dir.exists():
            continue

        # Try exact match first (with normalized ID)
        exact = base_dir / normalized_id
        if exact.exists():
            return (exact, is_cloud)

        # Collect prefix matches (using normalized ID for comparison)
        matches = [(d, is_cloud) for d in base_dir.iterdir() if d.is_dir() and d.name.startswith(normalized_id)]
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


def _extract_context_urls(events_dir: Path) -> set[str]:
    """Extract URLs from system context (SystemPromptEvent) to exclude from refs.

    These are URLs that appear in skills, prompts, or other system-injected context
    rather than actual repository work done during the conversation.
    """
    context_urls: set[str] = set()

    # Look for SystemPromptEvent (typically event-00000)
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            event = json.loads(event_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        if event.get("kind") != "SystemPromptEvent":
            continue

        # Extract URLs from dynamic_context (contains skills info)
        dynamic_ctx = event.get("dynamic_context", {})
        if isinstance(dynamic_ctx, dict):
            ctx_text = dynamic_ctx.get("text", "")
            if ctx_text:
                _extract_all_urls(ctx_text, context_urls)

        # Extract URLs from system_prompt
        sys_prompt = event.get("system_prompt", {})
        if isinstance(sys_prompt, dict):
            prompt_text = sys_prompt.get("text", "")
            if prompt_text:
                _extract_all_urls(prompt_text, context_urls)

        # Also check tools descriptions (may contain example URLs)
        tools = event.get("tools", [])
        for tool in tools:
            if isinstance(tool, dict):
                desc = tool.get("description", "")
                if desc:
                    _extract_all_urls(desc, context_urls)

    return context_urls


def _extract_all_urls(text: str, url_set: set[str]) -> None:
    """Extract all git hosting URLs from text into the given set."""
    for pattern_name, pattern in GIT_URL_PATTERNS.items():
        for match in pattern.finditer(text):
            url = match.group(0).rstrip(".,;:)]}>")
            # Normalize to base URL (without .git suffix)
            url = url.rstrip("/").removesuffix(".git")
            url_set.add(url)


def _extract_refs_from_conversation(conv_dir: Path) -> dict[str, set[str]]:
    """Extract git references from conversation events.

    Filters out noise by:
    1. Excluding refs from noisy MCP tools (web search, fetch, browser)
    2. Excluding refs from noisy terminal commands (curl, gh list, gh search, etc.)
    3. Excluding refs from system context (skills, prompts)

    This ensures we only capture refs that represent actual work, not
    incidental mentions from web searches, changelogs, or bulk listings.
    
    Also queries the database for branch refs (from branch_context stage).
    """
    refs: dict[str, set[str]] = {
        "repos": set(),
        "issues": set(),
        "prs": set(),
        "branches": set(),
    }

    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return refs

    # First pass: get URLs to exclude (from system context)
    context_urls = _extract_context_urls(events_dir)

    # Second pass: extract refs from events, filtering by event type
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            content = event_file.read_text()
            data = json.loads(content)

            # Check if this event should be excluded
            if _is_noisy_event(data):
                continue

            _extract_refs_from_text(content, refs)
        except (json.JSONDecodeError, OSError):
            continue

    # Filter out context URLs from repos
    # (PRs and issues are specific enough that they're unlikely to be in context)
    filtered_repos = set()
    for repo_url in refs["repos"]:
        normalized = repo_url.rstrip("/").removesuffix(".git")
        # Check if this URL or any prefix of it appears in context
        is_context = any(
            normalized == ctx_url or normalized.startswith(ctx_url + "/")
            for ctx_url in context_urls
        )
        if not is_context:
            filtered_repos.add(repo_url)

    refs["repos"] = filtered_repos
    
    # Query database for branch refs (from branch_context stage)
    refs["branches"] = _get_branch_refs_from_db(conv_dir)

    return refs


def _get_branch_refs_from_db(conv_dir: Path) -> set[str]:
    """Get branch refs from the database for a conversation."""
    from ohtv.db import get_connection, get_db_path
    from ohtv.db.models import RefType
    from ohtv.db.stores import LinkStore, ReferenceStore
    from ohtv.filters import normalize_conversation_id
    
    db_path = get_db_path()
    if not db_path.exists():
        return set()
    
    # Get conversation ID from directory name
    conv_id = normalize_conversation_id(conv_dir.name)
    
    try:
        with get_connection(db_path) as conn:
            link_store = LinkStore(conn)
            ref_store = ReferenceStore(conn)
            
            # Get all refs linked to this conversation
            ref_links = link_store.get_refs_for_conversation(conv_id)
            
            branch_urls = set()
            for ref_id, link_type in ref_links:
                ref = ref_store.get_by_id(ref_id)
                if ref and ref.ref_type == RefType.BRANCH:
                    branch_urls.add(ref.url)
            
            return branch_urls
    except Exception:
        return set()


# MCP tools that return web content (changelogs, search results, etc.)
_NOISY_MCP_TOOL_PATTERNS = [
    "tavily",       # Web search/extract
    "fetch",        # Web fetching
    "playwright",   # Browser automation
    "browser",      # Browser tools
]

# Terminal commands that produce bulk/noisy output
_NOISY_TERMINAL_COMMANDS = [
    # Web fetching
    "curl ",
    "curl\t",
    "wget ",
    "wget\t",
    # Bulk listing commands
    "gh pr list",
    "gh issue list",
    "gh run list",
    "gh release list",
    # Search commands (return many results)
    "gh search ",
    # Release notes contain many historical PRs
    "gh release view",
]


def _is_noisy_event(data: dict) -> bool:
    """Check if an event is likely to produce noisy refs.

    Returns True if the event should be excluded from ref extraction.
    """
    # Check for noisy MCP tool observations
    observation = data.get("observation")
    if isinstance(observation, dict):
        obs_kind = observation.get("kind", "")
        tool_name = observation.get("tool_name", "")

        # MCPToolObservation with noisy tool
        if "MCPToolObservation" in obs_kind or tool_name:
            tool_lower = tool_name.lower()
            for pattern in _NOISY_MCP_TOOL_PATTERNS:
                if pattern in tool_lower:
                    return True

        # BrowserObservation
        if obs_kind == "BrowserObservation":
            return True

        # TerminalObservation with noisy command
        if obs_kind == "TerminalObservation":
            command = observation.get("command", "")
            if isinstance(command, str):
                cmd_lower = command.lower()
                for pattern in _NOISY_TERMINAL_COMMANDS:
                    if pattern in cmd_lower:
                        return True

    return False


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
    url_lower = url.lower()
    
    # Skip template patterns
    template_indicators = [
        "{", "}", "...", "example", "username", "repo.git",
        "/user/", "/owner/", "/repo/", "/your-", "/my-",
    ]
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
    
    # Skip GitHub non-repo paths that look like repos
    github_non_repo_paths = [
        "/orgs/", "/organizations/", "/user-attachments/",
        "/apps/", "/settings/", "/marketplace/", "/sponsors/",
        "/features/", "/enterprise/", "/pricing/", "/security/",
        "/login/", "/users/",  # OAuth and user profile pages
    ]
    if any(path in url_lower for path in github_non_repo_paths):
        return False
    
    # Skip GitLab/Bitbucket system paths
    gitlab_system_paths = [
        "gitlab.com/api/", "gitlab.com/help/",
        "gitlab.com/org/", "gitlab.com/team/",  # Generic placeholders in docs
    ]
    if any(path in url_lower for path in gitlab_system_paths):
        return False
    
    bitbucket_system_paths = [
        "bitbucket.org/site/",  # OAuth endpoints
    ]
    if any(path in url_lower for path in bitbucket_system_paths):
        return False
    
    # Skip generic placeholder repo names commonly used in docs/examples
    # These appear as github.com/org/plugin, github.com/openai/plugins etc.
    generic_repo_names = [
        "/org/plugin", "/org/plugins",
        "/team/plugin", "/team/plugins",
        "/openai/plugins",  # Common example in MCP docs
        "/oauth/",  # OAuth examples (e.g., gitlab.com/oauth/discovery)
    ]
    if any(name in url_lower for name in generic_repo_names):
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
    if pattern_type in ("git_clone", "gh_repo_clone"):
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
        # gh repo clone uses owner/repo format directly
        if pattern_type == "gh_repo_clone":
            gh_clone_match = re.search(r"gh\s+repo\s+clone\s+([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)", command)
            if gh_clone_match:
                return ExtractedRef(
                    ref_type="repo",
                    owner=gh_clone_match.group(1),
                    repo=gh_clone_match.group(2),
                    number=None,
                    url=f"https://github.com/{gh_clone_match.group(1)}/{gh_clone_match.group(2)}",
                )

    # For git fetch/pull - extract repo from output or use --repo flag
    if pattern_type in ("git_fetch", "git_pull"):
        # Check for remote URL in output (e.g., "From https://github.com/owner/repo")
        from_match = re.search(r"From\s+https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)", output)
        if from_match:
            return ExtractedRef(
                ref_type="repo",
                owner=from_match.group(1),
                repo=from_match.group(2),
                number=None,
                url=f"https://github.com/{from_match.group(1)}/{from_match.group(2)}",
            )
        # Also check for SSH format
        from_ssh_match = re.search(r"From\s+git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)", output)
        if from_ssh_match:
            repo_name = from_ssh_match.group(2)
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            return ExtractedRef(
                ref_type="repo",
                owner=from_ssh_match.group(1),
                repo=repo_name,
                number=None,
                url=f"https://github.com/{from_ssh_match.group(1)}/{repo_name}",
            )

    # For gh repo view - extract owner/repo from command
    if pattern_type == "gh_repo_view":
        # gh repo view owner/repo or gh repo view (uses current repo)
        view_match = re.search(r"gh\s+repo\s+view\s+([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)", command)
        if view_match:
            return ExtractedRef(
                ref_type="repo",
                owner=view_match.group(1),
                repo=view_match.group(2),
                number=None,
                url=f"https://github.com/{view_match.group(1)}/{view_match.group(2)}",
            )
        # If no explicit repo, try to get from output
        if owner and repo:
            return ExtractedRef(
                ref_type="repo",
                owner=owner,
                repo=repo,
                number=None,
                url=f"https://github.com/{owner}/{repo}",
            )

    # For gh api - extract repo from URL path
    if pattern_type == "gh_api":
        # gh api repos/owner/repo/... or gh api /repos/owner/repo/...
        api_match = re.search(r"gh\s+api\s+/?repos/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)", command)
        if api_match:
            return ExtractedRef(
                ref_type="repo",
                owner=api_match.group(1),
                repo=api_match.group(2),
                number=None,
                url=f"https://github.com/{api_match.group(1)}/{api_match.group(2)}",
            )

    # For gh browse - use --repo flag or current repo context
    if pattern_type == "gh_browse":
        if owner and repo:
            return ExtractedRef(
                ref_type="repo",
                owner=owner,
                repo=repo,
                number=None,
                url=f"https://github.com/{owner}/{repo}",
            )

    # For gh pr view/diff/checks - extract PR number and repo
    if pattern_type in ("gh_pr_view", "gh_pr_diff", "gh_pr_checks"):
        num_match = re.search(r"gh\s+pr\s+(?:view|diff|checks)\s+(\d+)", command)
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

    # For gh issue view - extract issue number and repo
    if pattern_type == "gh_issue_view":
        num_match = re.search(r"gh\s+issue\s+view\s+(\d+)", command)
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
            # Try to get repo from output
            issue_url_match = OUTPUT_ISSUE_PATTERN.search(output)
            if issue_url_match:
                return ExtractedRef(
                    ref_type="issue",
                    owner=issue_url_match.group(1),
                    repo=issue_url_match.group(2),
                    number=int(issue_url_match.group(3)),
                    url=f"https://github.com/{issue_url_match.group(1)}/{issue_url_match.group(2)}/issues/{issue_url_match.group(3)}",
                )

    return None


def _extract_working_dir(command: str) -> str | None:
    """Extract working directory from a command with cd prefix."""
    cd_match = CD_PATH_PATTERN.search(command)
    if cd_match:
        return cd_match.group(1)
    return None


def _detect_interactions_from_conversation(conv_dir: Path, refs: dict[str, set[str]]) -> RefInteractions:
    """Detect interactions from conversation events and match to refs.

    Scans terminal actions for interaction patterns (git push, gh pr comment, etc.)
    and correlates successful commands with the refs found in the conversation.
    Also tracks commits without corresponding pushes to warn about unpushed work.
    """
    interactions = RefInteractions()
    events_dir = conv_dir / "events"

    if not events_dir.exists():
        return interactions

    # Normalize all refs for matching
    norm_repos = {_normalize_ref_url(url): url for url in refs["repos"]}
    norm_prs = {_normalize_ref_url(url): url for url in refs["prs"]}
    norm_issues = {_normalize_ref_url(url): url for url in refs["issues"]}

    # Track commits and pushes by working directory to detect unpushed work
    committed_dirs: set[str] = set()
    pushed_dirs: set[str] = set()

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

            # Track commits and pushes by working directory
            working_dir = _extract_working_dir(command)
            if pattern_name == "git_commit" and working_dir:
                committed_dirs.add(working_dir)
            elif pattern_name == "git_push" and working_dir:
                pushed_dirs.add(working_dir)

            # Extract ref from command/output
            extracted_ref = _extract_ref_from_command(command, output, pattern_name)
            
            # For git_commit, we don't have a URL but still want to track it
            if pattern_name == "git_commit":
                # Git commit doesn't produce a URL, but we track it for unpushed detection
                continue
            
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

    # Identify directories with commits but no push
    interactions.unpushed_commits = committed_dirs - pushed_dirs

    return interactions


def _display_actions_only(interactions: RefInteractions) -> None:
    """Display refs with any detected interactions (read or write)."""
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
        "fetched": 8,
        "pulled": 9,
        "viewed": 10,
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

    if not action_items and not interactions.unpushed_commits:
        console.print("\n[dim]No interactions detected.[/dim]")
        return

    if action_items:
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
            elif action in WRITE_ACTIONS:
                style = "cyan"
            else:
                style = "dim"
            console.print(f"  [{style}]{action}[/{style}] {short_url}")

    # Show warning for unpushed commits
    if interactions.unpushed_commits:
        console.print("\n[bold yellow]⚠ Unpushed Commits[/bold yellow]")
        for path in sorted(interactions.unpushed_commits):
            # Shorten home directory paths for readability
            display_path = path.replace(str(Path.home()), "~")
            console.print(f"  • [yellow]{display_path}[/yellow]")


def _display_write_actions_only(interactions: RefInteractions) -> None:
    """Display refs with only write actions (excluding read-only like cloned, viewed)."""
    # Collect only write interactions with their URLs
    action_items: list[tuple[str, str, str]] = []  # (action, url, category)

    # Priority order for write actions (most significant first)
    action_priority = {
        "created": 1,
        "merged": 2,
        "pushed": 3,
        "commented": 4,
        "reviewed": 5,
        "closed": 6,
        "committed": 7,
    }

    for url, url_actions in interactions.repos.items():
        for action in url_actions:
            if action in WRITE_ACTIONS:
                action_items.append((action, url, "repo"))

    for url, url_actions in interactions.prs.items():
        for action in url_actions:
            if action in WRITE_ACTIONS:
                action_items.append((action, url, "pr"))

    for url, url_actions in interactions.issues.items():
        for action in url_actions:
            if action in WRITE_ACTIONS:
                action_items.append((action, url, "issue"))

    if not action_items and not interactions.unpushed_commits:
        console.print("\n[dim]No write actions detected.[/dim]")
        return

    if action_items:
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
                style = "cyan"
            console.print(f"  [{style}]{action}[/{style}] {short_url}")

    # Show warning for unpushed commits
    if interactions.unpushed_commits:
        console.print("\n[bold yellow]⚠ Unpushed Commits[/bold yellow]")
        for path in sorted(interactions.unpushed_commits):
            # Shorten home directory paths for readability
            display_path = path.replace(str(Path.home()), "~")
            console.print(f"  • [yellow]{display_path}[/yellow]")


def _display_refs(refs: dict[str, set[str]], interactions: RefInteractions | None = None) -> None:
    """Display extracted references organized by category with interaction annotations."""
    categories = [
        ("Repositories", "repos", "blue"),
        ("Issues", "issues", "yellow"),
        ("Pull Requests / Merge Requests", "prs", "green"),
        ("Branches", "branches", "cyan"),
    ]

    for title, key, color in categories:
        urls = sorted(refs.get(key, set()))
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

    # Show warning for unpushed commits
    if interactions and interactions.unpushed_commits:
        console.print("\n[bold yellow]⚠ Unpushed Commits[/bold yellow]")
        for path in sorted(interactions.unpushed_commits):
            # Shorten home directory paths for readability
            display_path = path.replace(str(Path.home()), "~")
            console.print(f"  • [yellow]{display_path}[/yellow]")


# =============================================================================
# Database Commands
# =============================================================================


@main.group()
def db() -> None:
    """Manage the conversation index database."""


@db.command("init")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed migration output")
def db_init(verbose: bool) -> None:
    """Initialize or migrate the database.
    
    Creates the database if it doesn't exist, or applies any pending
    migrations if it does. Safe to run multiple times.
    """
    from ohtv.db import get_connection, get_db_path, migrate
    
    db_path = get_db_path()
    existed = db_path.exists()
    
    with get_connection() as conn:
        applied = migrate(conn)
    
    if not existed:
        console.print(f"[green]✓[/green] Created database: {db_path}")
    
    if applied:
        console.print(f"[green]✓[/green] Applied {len(applied)} migration(s):")
        for migration_name in applied:
            if verbose:
                console.print(f"  • {migration_name}")
    elif existed:
        console.print(f"[dim]Database up to date: {db_path}[/dim]")


@db.command("process")
@click.argument("stage", type=click.Choice(["refs", "actions", "branch_context", "push_pr_links", "all"]))
@click.option("--force", "-f", is_flag=True, help="Reprocess all conversations, ignoring stage completion")
@click.option("--conversation", "-c", help="Process only this conversation ID")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def db_process(stage: str, force: bool, conversation: str | None, verbose: bool) -> None:
    """Run a processing stage on conversations.
    
    Processes conversations that need it (never processed or have new events).
    Use --force to reprocess all conversations regardless of status.
    
    \b
    Available stages:
      refs           - Extract repository, issue, and PR references
      actions        - Recognize actions (file edits, git ops, PRs, etc.)
      branch_context - Track branches and create branch refs
      push_pr_links  - Correlate git pushes with PRs via branch matching
      all            - Run all stages in sequence
    """
    from ohtv.db import get_connection, get_db_path, migrate, scan_conversations
    from ohtv.db.stages import STAGES
    from ohtv.db.stores import ConversationStore, StageStore
    
    # Handle "all" - run all stages in sequence
    if stage == "all":
        for stage_name in STAGES:
            console.print(f"\n[bold]Running stage: {stage_name}[/bold]")
            _run_process_stage(stage_name, force, conversation, verbose)
        return
    
    _run_process_stage(stage, force, conversation, verbose)


def _run_process_stage(stage: str, force: bool, conversation: str | None, verbose: bool) -> None:
    """Run a single processing stage."""
    from ohtv.db import get_connection, get_db_path, migrate, scan_conversations
    from ohtv.db.stages import STAGES
    from ohtv.db.stores import ConversationStore, StageStore
    
    if stage not in STAGES:
        console.print(f"[red]Error:[/red] Unknown stage '{stage}'")
        raise SystemExit(1)
    
    processor = STAGES[stage]
    db_path = get_db_path()
    
    # Auto-init and scan if needed
    if not db_path.exists():
        console.print("[dim]Initializing database...[/dim]")
    
    with get_connection() as conn:
        migrate(conn)
        
        # Auto-scan to ensure conversations are registered
        scan_result = scan_conversations(conn)
        if scan_result.new_registered > 0:
            console.print(f"[dim]Registered {scan_result.new_registered} new conversation(s)[/dim]")
        
        conv_store = ConversationStore(conn)
        stage_store = StageStore(conn)
        
        # Determine which conversations to process
        if conversation:
            # Process specific conversation
            conv = conv_store.get(conversation)
            if not conv:
                console.print(f"[red]Error:[/red] Conversation '{conversation}' not found in database")
                console.print("[dim]Run 'ohtv db scan' first to register conversations[/dim]")
                raise SystemExit(1)
            
            if force:
                stage_store.clear_stage(stage, conversation)
            
            if stage_store.needs_processing(conversation, stage, conv.event_count):
                conversations_to_process = [conv]
            else:
                conversations_to_process = []
                console.print(f"[dim]Conversation already processed for '{stage}' stage[/dim]")
        else:
            # Process all pending conversations
            if force:
                cleared = stage_store.clear_stage(stage)
                if verbose and cleared > 0:
                    console.print(f"[dim]Cleared {cleared} stage record(s)[/dim]")
            
            pending = stage_store.get_pending_conversations(stage)
            conversations_to_process = []
            for conv_id, event_count in pending:
                conv = conv_store.get(conv_id)
                if conv:
                    conversations_to_process.append(conv)
        
        if not conversations_to_process:
            console.print(f"[dim]No conversations need processing for '{stage}' stage[/dim]")
            conn.commit()
            return
        
        # Process conversations with progress bar
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
        
        processed = 0
        errors = 0
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current]}[/dim]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Processing '{stage}'",
                total=len(conversations_to_process),
                current="",
            )
            
            for conv in conversations_to_process:
                progress.update(task, current=conv.id[:12] + "...")
                try:
                    processor(conn, conv)
                    processed += 1
                except Exception as e:
                    errors += 1
                    if verbose:
                        console.print(f"[red]Error processing {conv.id}:[/red] {e}")
                progress.advance(task)
        
        conn.commit()
    
    # Display results
    if processed > 0:
        console.print(f"[green]✓[/green] Processed {processed} conversation(s) for '{stage}' stage")
    if errors > 0:
        console.print(f"[yellow]![/yellow] {errors} error(s) during processing")


@db.command("scan")
@click.option("--force", "-f", is_flag=True, help="Update all conversations regardless of mtime")
@click.option("--remove-missing", is_flag=True, help="Remove DB entries for conversations no longer on disk")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def db_scan(force: bool, remove_missing: bool, verbose: bool) -> None:
    """Scan filesystem and register conversations in the database.
    
    Discovers conversations from local CLI (~/.openhands/conversations/),
    synced cloud (~/.openhands/cloud/conversations/), and any extra paths
    configured via extra_conversation_paths setting.
    
    Uses mtime for fast change detection - only updates conversations whose
    events directory has been modified since last scan.
    
    Use --force after restoring from backup or copying files, as these
    operations may change mtimes without changing content.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from ohtv.db import get_connection, get_db_path, migrate, scan_conversations
    
    db_path = get_db_path()
    
    # Auto-init if needed
    if not db_path.exists():
        console.print("[dim]Initializing database...[/dim]")
    
    with get_connection() as conn:
        migrate(conn)
        
        # Use progress bar for scan
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Scanning"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current]}[/dim]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Scanning", total=None, current="discovering...")
            
            def on_progress(current: int, total: int, conv_id: str):
                if progress.tasks[task].total != total:
                    progress.update(task, total=total)
                progress.update(task, completed=current, current=conv_id[:12] + "..." if conv_id else "")
            
            result = scan_conversations(
                conn, force=force, remove_missing=remove_missing, on_progress=on_progress
            )
        
        conn.commit()
    
    # Display results
    if result.new_registered > 0:
        console.print(f"[green]✓[/green] Registered {result.new_registered} new conversation(s)")
    
    if result.updated > 0:
        console.print(f"[green]✓[/green] Updated {result.updated} conversation(s)")
    
    if result.removed > 0:
        console.print(f"[yellow]![/yellow] Removed {result.removed} missing conversation(s)")
    
    if result.new_registered == 0 and result.updated == 0 and result.removed == 0:
        console.print(f"[dim]No changes. {result.unchanged} conversation(s) up to date.[/dim]")
    elif verbose:
        console.print(f"[dim]{result.unchanged} unchanged, {result.total_on_disk} total on disk[/dim]")


@db.command("status")
def db_status() -> None:
    """Show database status and statistics."""
    from ohtv.db import get_connection, get_db_path
    from ohtv.db.stores import ActionStore
    
    db_path = get_db_path()
    
    if not db_path.exists():
        console.print(f"[yellow]Database not initialized.[/yellow]")
        console.print(f"Run [bold]ohtv db init[/bold] to create it.")
        return
    
    # Get file size
    size_bytes = db_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    
    console.print(f"[bold]Database:[/bold] {db_path}")
    console.print(f"[bold]Size:[/bold] {size_str}")
    
    with get_connection() as conn:
        # Count records in each table
        tables = [
            ("conversations", "Conversations"),
            ("repositories", "Repositories"),
            ("refs", "References (issues/PRs)"),
            ("conversation_repos", "Repo Links"),
            ("conversation_refs", "Reference Links"),
            ("actions", "Actions"),
        ]
        
        console.print("\n[bold]Records:[/bold]")
        for table_name, display_name in tables:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            console.print(f"  {display_name}: {count}")
        
        # Show breakdown by ref type
        cursor = conn.execute(
            "SELECT ref_type, COUNT(*) FROM refs GROUP BY ref_type"
        )
        ref_counts = cursor.fetchall()
        if ref_counts:
            console.print("\n[bold]References by type:[/bold]")
            for row in ref_counts:
                console.print(f"  {row[0]}: {row[1]}")
        
        # Show breakdown by action type
        action_store = ActionStore(conn)
        action_counts = action_store.count_by_type()
        if action_counts:
            console.print("\n[bold]Actions by type:[/bold]")
            for action_type, count in action_counts.items():
                console.print(f"  {action_type}: {count}")


@db.command("index-cache")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def db_index_cache(verbose: bool) -> None:
    """Index existing analysis cache files into the database.
    
    Scans all conversation directories for objective_analysis.json files
    and imports their metadata into the database for fast cache lookup.
    
    This enables the summary command to quickly determine which conversations
    need analysis without reading event files.
    """
    from datetime import datetime
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from ohtv.db import get_connection, migrate
    from ohtv.db.stores import AnalysisCacheStore, ConversationStore
    from ohtv.db.stores.analysis_cache_store import AnalysisCacheEntry, AnalysisSkipEntry
    
    config = Config.from_env()
    
    with get_connection() as conn:
        migrate(conn)
        
        conv_store = ConversationStore(conn)
        cache_store = AnalysisCacheStore(conn)
        
        # Get all registered conversations
        conversations = conv_store.list_all()
        if not conversations:
            console.print("[yellow]No conversations registered. Run 'ohtv db scan' first.[/yellow]")
            return
        
        indexed = 0
        skipped = 0
        errors = 0
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Indexing cache files"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current]}[/dim]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                "Indexing",
                total=len(conversations),
                current="",
            )
            
            for conv in conversations:
                progress.update(task, current=conv.id[:12] + "...")
                
                # Find cache file
                conv_dir = Path(conv.location)
                cache_file = conv_dir / "objective_analysis.json"
                
                if not cache_file.exists():
                    progress.advance(task)
                    continue
                
                try:
                    cache_data = json.loads(cache_file.read_text())
                    
                    # Check for skip marker
                    if "skipped" in cache_data:
                        skip_info = cache_data["skipped"]
                        entry = AnalysisSkipEntry(
                            conversation_id=conv.id,
                            event_count=cache_data.get("event_count", 0),
                            reason=skip_info.get("reason", "unknown"),
                            skipped_at=datetime.fromisoformat(skip_info.get("at", datetime.now().isoformat())),
                        )
                        cache_store.upsert_skip(entry)
                        skipped += 1
                    
                    # Index each analysis
                    analyses = cache_data.get("analyses", {})
                    for cache_key, analysis_data in analyses.items():
                        entry = AnalysisCacheEntry(
                            conversation_id=conv.id,
                            cache_key=cache_key,
                            event_count=analysis_data.get("event_count", 0),
                            content_hash=analysis_data.get("content_hash", ""),
                            analyzed_at=datetime.fromisoformat(analysis_data.get("analyzed_at", datetime.now().isoformat())),
                        )
                        cache_store.upsert_cache(entry)
                        indexed += 1
                        
                except (json.JSONDecodeError, KeyError) as e:
                    errors += 1
                    if verbose:
                        console.print(f"[red]Error reading {cache_file}:[/red] {e}")
                
                progress.advance(task)
        
        conn.commit()
    
    # Display results
    if indexed > 0:
        console.print(f"[green]✓[/green] Indexed {indexed} cached analysis entries")
    if skipped > 0:
        console.print(f"[dim]{skipped} skip markers indexed[/dim]")
    if errors > 0:
        console.print(f"[yellow]![/yellow] {errors} error(s) reading cache files")
    if indexed == 0 and skipped == 0 and errors == 0:
        console.print("[dim]No cache files found to index.[/dim]")


@db.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def db_reset(yes: bool) -> None:
    """Delete the database and start fresh.
    
    This removes all indexed data including conversations, refs, and actions.
    The source conversation files are NOT affected.
    """
    from ohtv.db import get_db_path
    
    db_path = get_db_path()
    
    if not db_path.exists():
        console.print("[dim]No database to delete.[/dim]")
        return
    
    # Get size for display
    size_bytes = db_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    
    if not yes:
        from rich.prompt import Confirm
        console.print(f"[yellow]Warning:[/yellow] This will delete the database at:")
        console.print(f"  {db_path} ({size_str})")
        console.print()
        if not Confirm.ask("Are you sure?", console=console, default=False):
            console.print("[dim]Cancelled.[/dim]")
            return
    
    db_path.unlink()
    console.print(f"[green]✓[/green] Deleted database ({size_str})")
    console.print("[dim]Run 'ohtv db init' or 'ohtv db process all' to recreate.[/dim]")


@db.command("embed")
@click.option("--force", "-f", is_flag=True, help="Rebuild all embeddings")
@click.option("--estimate", is_flag=True, help="Show cost estimate only, don't embed")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def db_embed(force: bool, estimate: bool, yes: bool, verbose: bool) -> None:
    """Build embeddings for semantic search and RAG.
    
    Generates multiple embeddings per conversation for optimal search:
    - analysis: Goal + outcomes from cached LLM analysis
    - summary: User messages + refs + file paths  
    - content: File contents + outputs (chunked if large)
    
    Uses the same LLM_API_KEY and LLM_BASE_URL as the gen command.
    
    \b
    Environment variables:
      EMBEDDING_MODEL  Model to use (default: openai/text-embedding-3-small)
      LLM_API_KEY      Required - API key for embedding service
      LLM_BASE_URL     Optional - Base URL for LiteLLM proxy
    
    \b
    Examples:
      ohtv db embed                # Build embeddings for new conversations
      ohtv db embed --force        # Rebuild all embeddings
      ohtv db embed --estimate     # Show cost estimate without embedding
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.prompt import Confirm
    from ohtv.db import get_connection, get_db_path, migrate
    from ohtv.db.stores import ConversationStore, EmbeddingStore
    from ohtv.analysis.embeddings import (
        EmbeddingStats, estimate_cost, get_embedding_model, embed_conversation_full,
        estimate_conversation_tokens, build_summary_text
    )
    from ohtv.analysis.cache import load_events
    
    _init_logging(verbose=verbose)
    config = Config.from_env()
    db_path = get_db_path()
    
    # Auto-init if needed
    if not db_path.exists():
        console.print("[dim]Initializing database...[/dim]")
    
    with get_connection() as conn:
        migrate(conn)
        
        conv_store = ConversationStore(conn)
        embed_store = EmbeddingStore(conn)
        
        # Get all conversations
        all_convs = conv_store.list_all()
        if not all_convs:
            console.print("[dim]No conversations found. Run 'ohtv db scan' first.[/dim]")
            return
        
        # Determine which need embedding
        if force:
            to_embed = all_convs
        else:
            existing = set(embed_store.list_conversation_ids())
            to_embed = [c for c in all_convs if c.id not in existing]
        
        if not to_embed:
            count = embed_store.count_conversations()
            total_embeddings = embed_store.count()
            by_type = embed_store.count_by_type()
            console.print(f"[dim]All {count} conversations already embedded ({total_embeddings} total embeddings).[/dim]")
            if by_type:
                type_str = ", ".join(f"{t}: {c}" for t, c in by_type.items())
                console.print(f"[dim]  By type: {type_str}[/dim]")
            console.print("[dim]Use --force to rebuild all embeddings.[/dim]")
            return
        
        # Estimate tokens and cost
        model = get_embedding_model()
        total_tokens = 0
        total_embeddings = 0
        valid_convs = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Estimating"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current]}[/dim]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                "Estimating",
                total=len(to_embed),
                current="calculating tokens..."
            )
            
            for conv in to_embed:
                short_id = conv.id[:12]
                progress.update(task, current=short_id)
                
                conv_dir = Path(conv.location)
                if not conv_dir.exists():
                    progress.advance(task)
                    continue
                
                tokens, num_embeddings = estimate_conversation_tokens(conv_dir)
                if tokens == 0:
                    progress.advance(task)
                    continue
                
                total_tokens += tokens
                total_embeddings += num_embeddings
                valid_convs.append((conv, conv_dir, tokens, num_embeddings))
                progress.advance(task)
        
        if not valid_convs:
            console.print("[dim]No conversations with content to embed.[/dim]")
            return
        
        estimated_cost = estimate_cost(total_tokens, model)
        
        # Show estimate
        console.print(f"\n[bold]Embedding Summary[/bold]")
        console.print(f"  Model: {model}")
        console.print(f"  Conversations: {len(valid_convs)}")
        console.print(f"  Embeddings to create: ~{total_embeddings}")
        console.print(f"  Estimated tokens: ~{total_tokens:,}")
        console.print(f"  Estimated cost: [green]${estimated_cost:.4f}[/green]")
        
        if estimate:
            console.print("\n[dim]Use 'ohtv db embed' to build embeddings.[/dim]")
            return
        
        # Confirm if > 20 conversations
        if len(valid_convs) > 20 and not yes:
            console.print()
            if not Confirm.ask(
                f"Embed {len(valid_convs)} conversations (~${estimated_cost:.4f})?",
                console=console,
                default=True,
            ):
                console.print("[dim]Cancelled.[/dim]")
                return
        
        # Build embeddings with progress bar (parallel processing)
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        
        embedded = 0
        skipped = 0
        errors = 0
        actual_tokens = 0
        actual_embeddings = 0
        error_counts: dict[str, int] = {}  # error message -> count
        
        # Use parallel processing for embedding API calls
        # For cloud APIs: 20 workers (API rate limits are the bottleneck)
        # For Ollama: 2 workers (local model can't handle high concurrency)
        if model.startswith("ollama/"):
            max_workers = min(2, len(valid_convs)) if len(valid_convs) > 1 else 1
        else:
            max_workers = min(20, len(valid_convs)) if len(valid_convs) > 1 else 1
        
        # Thread-safe lock for counters
        _lock = threading.Lock()
        start_time = time.perf_counter()
        processed_count = 0  # all processed (for rate calculation)
        
        def _format_rate(processed: int, new_embeds: int, elapsed: float) -> str:
            """Format processing rate."""
            if elapsed < 0.1 or processed == 0:
                return ""
            rate = processed / (elapsed / 60.0)
            if new_embeds > 0:
                new_rate = new_embeds / (elapsed / 60.0)
                return f"{rate:.0f}/min ({new_rate:.0f} new)"
            return f"{rate:.0f}/min"
        
        def _embed_one(conv, conv_dir) -> tuple[EmbeddingStats | None, str | None]:
            """Embed a single conversation. Returns (stats, error_msg)."""
            import sqlite3
            
            max_retries = 5
            retry_delay = 0.5  # seconds
            
            # Each thread gets its own connection (SQLite connections aren't thread-safe)
            with get_connection() as thread_conn:
                for attempt in range(max_retries):
                    try:
                        stats = embed_conversation_full(
                            conv_dir,
                            thread_conn,
                            model=model,
                            skip_existing=not force,
                        )
                        
                        log.debug("Embedded %s: %d embeddings created", conv.id[:12], stats.embeddings_created)
                        
                        # Also update FTS for keyword search
                        if stats.embeddings_created > 0:
                            events = load_events(conv_dir)
                            if events:
                                summary = build_summary_text(events)
                                if summary:
                                    thread_embed_store = EmbeddingStore(thread_conn)
                                    thread_embed_store.upsert_fts(conv.id, summary)
                        
                        thread_conn.commit()
                        log.debug("Committed %s", conv.id[:12])
                        return stats, None
                    except sqlite3.OperationalError as e:
                        log.debug("SQLite error on %s (attempt %d): %s", conv.id[:12], attempt + 1, e)
                        if "database is locked" in str(e) and attempt < max_retries - 1:
                            time.sleep(retry_delay * (attempt + 1))  # exponential backoff
                            continue
                        return None, str(e)
                    except Exception as e:
                        log.debug("Error on %s: %s", conv.id[:12], e)
                        return None, str(e)
            
            return None, "database is locked (max retries exceeded)"
        
        interrupted = False
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Embedding"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[dim]{task.fields[rate]}[/dim]"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task(
                    "Embedding",
                    total=len(valid_convs),
                    rate="starting..."
                )
                
                if max_workers == 1:
                    # Sequential processing
                    for conv, conv_dir, _, _ in valid_convs:
                        stats, err_msg = _embed_one(conv, conv_dir)
                        processed_count += 1
                        
                        if err_msg:
                            errors += 1
                            error_counts[err_msg] = error_counts.get(err_msg, 0) + 1
                            if verbose:
                                console.print(f"\n[red]Error embedding {conv.id[:12]}:[/red] {err_msg}")
                        elif stats:
                            if stats.embeddings_created == 0:
                                skipped += 1
                            else:
                                embedded += 1
                                actual_tokens += stats.total_tokens
                                actual_embeddings += stats.embeddings_created
                        
                        elapsed = time.perf_counter() - start_time
                        progress.update(task, advance=1, rate=_format_rate(processed_count, embedded, elapsed))
                else:
                    # Parallel processing with ThreadPoolExecutor
                    executor = ThreadPoolExecutor(max_workers=max_workers)
                    try:
                        future_to_conv = {
                            executor.submit(_embed_one, conv, conv_dir): (conv, conv_dir)
                            for conv, conv_dir, _, _ in valid_convs
                        }
                        
                        # Use timeout to allow Ctrl+C to be detected
                        pending = set(future_to_conv.keys())
                        while pending:
                            # Wait with timeout so KeyboardInterrupt can be caught
                            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                            
                            for future in done:
                                conv, conv_dir = future_to_conv[future]
                                
                                try:
                                    stats, err_msg = future.result()
                                except Exception as e:
                                    err_msg = str(e)
                                    stats = None
                                
                                with _lock:
                                    processed_count += 1
                                    if err_msg:
                                        errors += 1
                                        error_counts[err_msg] = error_counts.get(err_msg, 0) + 1
                                        if verbose:
                                            console.print(f"\n[red]Error embedding {conv.id[:12]}:[/red] {err_msg}")
                                    elif stats:
                                        if stats.embeddings_created == 0:
                                            skipped += 1
                                        else:
                                            embedded += 1
                                            actual_tokens += stats.total_tokens
                                            actual_embeddings += stats.embeddings_created
                                    
                                    elapsed = time.perf_counter() - start_time
                                
                                progress.update(task, advance=1, rate=_format_rate(processed_count, embedded, elapsed))
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)
        except KeyboardInterrupt:
            interrupted = True
            console.print("\n[yellow]Interrupted! Partial results saved.[/yellow]")
        
        # Log deduplicated errors to file
        for err_msg, count in error_counts.items():
            log.error("Embedding error (%d occurrences): %s", count, err_msg)
        
        # Display results
        if embedded > 0:
            actual_cost = estimate_cost(actual_tokens, model)
            console.print(f"\n[green]✓[/green] Embedded {embedded} conversation(s)")
            console.print(f"  Embeddings created: {actual_embeddings}")
            console.print(f"  Tokens: {actual_tokens:,}")
            console.print(f"  Cost: [green]${actual_cost:.4f}[/green]")
        
        if skipped > 0:
            console.print(f"[dim]{skipped} conversation(s) skipped (no content or already embedded)[/dim]")
        
        if errors > 0:
            console.print(f"[yellow]![/yellow] {errors} error(s)")
            # Show top errors with counts
            sorted_errors = sorted(error_counts.items(), key=lambda x: -x[1])
            for err_msg, count in sorted_errors[:3]:  # Show top 3
                msg = err_msg if len(err_msg) <= 80 else err_msg[:80] + "..."
                console.print(f"[dim]  ({count}x) {msg}[/dim]")
            if len(sorted_errors) > 3:
                console.print(f"[dim]  ... and {len(sorted_errors) - 3} more error types[/dim]")
            console.print(f"[dim]  See ~/.ohtv/logs/ohtv.log for details[/dim]")
        
        total = embed_store.count()
        conv_count = embed_store.count_conversations()
        by_type = embed_store.count_by_type()
        console.print(f"\n[dim]Total: {total} embeddings for {conv_count} conversations[/dim]")
        if by_type:
            type_str = ", ".join(f"{t}: {c}" for t, c in by_type.items())
            console.print(f"[dim]  By type: {type_str}[/dim]")
        console.print("[dim]Use 'ohtv search <query>' or 'ohtv ask <question>' for search.[/dim]")


# =============================================================================
# Prompts Commands
# =============================================================================


@main.command()
@click.argument("action", required=False, type=click.Choice(["init", "list", "show", "reset"]))
@click.argument("name", required=False)
@click.option("--all", "-a", "reset_all", is_flag=True, help="Reset all prompts to defaults")
def prompts(action: str | None, name: str | None, reset_all: bool) -> None:
    """View and customize LLM analysis prompts.
    
    \b
    Without arguments, shows prompt status (default vs customized).
    
    \b
    Actions:
      init   Copy missing prompts to ~/.ohtv/prompts/ for customization
      list   Show all prompts with their status
      show   Display the content of a specific prompt
      reset  Reset a prompt to its default (undo customizations)
    
    \b
    Examples:
      ohtv prompts              # Show prompt status
      ohtv prompts init         # Copy missing prompts for customization
      ohtv prompts show brief   # Show the brief prompt content
      ohtv prompts reset brief  # Reset brief prompt to default
      ohtv prompts reset --all  # Reset all prompts to defaults
    """
    from ohtv.prompts import (
        PROMPT_NAMES,
        clear_prompt_cache,
        discover_prompts,
        get_default_prompts_dir,
        get_prompt,
        get_user_prompts_dir,
        init_user_prompts,
        list_families,
        list_prompts,
        list_variants,
        resolve_prompt,
    )
    
    if action is None or action == "list":
        _show_prompts_family_structure()
        return
    
    if action == "init":
        copied = init_user_prompts()
        if copied:
            console.print(f"[green]✓[/green] Copied {len(copied)} prompt(s) to {get_user_prompts_dir()}/")
            for prompt_path in sorted(copied):
                # Display as "family/variant.md" (e.g., "objectives/brief.md")
                console.print(f"  • {prompt_path}.md")
            console.print()
            console.print("[dim]Edit these files to customize prompts.[/dim]")
        else:
            console.print("[dim]All prompts already initialized. Use 'reset' to undo customizations.[/dim]")
        return
    
    if action == "show":
        if not name:
            console.print("[red]Error:[/red] Please specify a prompt name.")
            console.print(f"[dim]Available prompts: {', '.join(PROMPT_NAMES)}[/dim]")
            return
        if name not in PROMPT_NAMES:
            console.print(f"[red]Error:[/red] Unknown prompt: {name}")
            console.print(f"[dim]Available prompts: {', '.join(PROMPT_NAMES)}[/dim]")
            return
        try:
            content = get_prompt(name)
            console.print(f"[bold]Prompt: {name}[/bold]")
            console.print()
            console.print(content)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
        return
    
    if action == "reset":
        user_dir = get_user_prompts_dir()
        default_dir = get_default_prompts_dir()
        
        if name:
            # Reset specific prompt - support both "variant" and "family/variant" formats
            if "/" in name:
                family, variant = name.split("/", 1)
            elif name in PROMPT_NAMES:
                family, variant = "objs", name
            else:
                # Try to find it in discovered prompts
                try:
                    meta = resolve_prompt("objs", name)
                    family, variant = "objs", name
                except ValueError:
                    console.print(f"[red]Error:[/red] Unknown prompt: {name}")
                    console.print(f"[dim]Available prompts: {', '.join(PROMPT_NAMES)}[/dim]")
                    return
            
            user_path = user_dir / family / f"{variant}.md"
            if not user_path.exists():
                console.print(f"[dim]No user prompt to reset: {name}[/dim]")
                return
            
            default_path = default_dir / family / f"{variant}.md"
            if default_path.exists():
                user_path.write_text(default_path.read_text())
                console.print(f"[green]✓[/green] Reset {family}/{variant} to default")
            else:
                user_path.unlink()
                console.print(f"[green]✓[/green] Removed {family}/{variant} (will use built-in default)")
            
            # Clear cache so changes take effect
            clear_prompt_cache()
        elif reset_all:
            # Reset all prompts - find all user prompt files in family directories
            reset_count = 0
            for user_prompt in user_dir.rglob("*.md"):
                # Skip flat files
                if user_prompt.parent == user_dir:
                    continue
                
                rel_path = user_prompt.relative_to(user_dir)
                default_path = default_dir / rel_path
                
                if default_path.exists():
                    user_prompt.write_text(default_path.read_text())
                    reset_count += 1
                else:
                    user_prompt.unlink()
                    reset_count += 1
            
            if reset_count:
                console.print(f"[green]✓[/green] Reset {reset_count} prompt(s) to defaults")
                clear_prompt_cache()
            else:
                console.print("[dim]No user prompts to reset.[/dim]")
        else:
            console.print("[yellow]Specify a prompt name or use --all to reset all.[/yellow]")
            console.print(f"[dim]Available prompts: {', '.join(PROMPT_NAMES)}[/dim]")
        return


def _show_prompts_family_structure() -> None:
    """Display prompts organized by family and variant."""
    from ohtv.prompts import list_families, list_variants, resolve_prompt, get_user_prompts_dir
    
    console.print("[bold]Prompt Families:[/bold]")
    console.print()
    
    families = list_families()
    if not families:
        console.print("[dim]No prompts found.[/dim]")
        return
    
    for family in families:
        console.print(f"  [cyan]{family}/[/cyan]")
        
        variants = list_variants(family)
        for variant in variants:
            try:
                meta = resolve_prompt(family, variant)
                default_marker = " [green](default)[/green]" if meta.default else ""
                description = meta.description or ""
                
                # Truncate description if too long
                if len(description) > 60:
                    description = description[:57] + "..."
                
                console.print(f"    {variant:<20} {default_marker:<18} {description}")
            except Exception as e:
                log.exception("Failed to resolve prompt %s/%s", family, variant)
                console.print(f"    {variant:<20} [red]error: {e}[/red]")
        
        console.print()
    
    user_dir = get_user_prompts_dir()
    console.print(f"[dim]User prompts directory: {user_dir}[/dim]")
    console.print("[dim]Run 'ohtv prompts init' to copy prompts for customization.[/dim]")


def _show_prompts_status(prompts_list: list[dict], user_dir) -> None:
    """Display prompt status in a table (legacy)."""
    table = Table(title="LLM Analysis Prompts")
    table.add_column("Prompt", style="cyan")
    table.add_column("Status")
    table.add_column("Location", style="dim")
    
    for prompt_info in prompts_list:
        name = prompt_info["name"]
        status = prompt_info["status"]
        
        if status == "customized":
            status_display = "[green]customized[/green]"
            location = str(prompt_info["user_path"])
        elif status == "copied":
            status_display = "[dim]copied (unchanged)[/dim]"
            location = str(prompt_info["user_path"])
        elif status == "default":
            status_display = "[dim]default[/dim]"
            location = "(built-in)"
        else:
            status_display = "[red]missing[/red]"
            location = ""
        
        table.add_row(name, status_display, location)
    
    console.print(table)
    console.print()
    console.print(f"[dim]User prompts directory: {user_dir}[/dim]")
    console.print("[dim]Run 'ohtv prompts init' to copy prompts for customization.[/dim]")


# =============================================================================
# Gen Commands (new unified interface)
# =============================================================================


@main.group()
def gen() -> None:
    """Generate LLM-powered analysis of conversations (requires LLM_API_KEY)."""


@gen.command("objs")
@click.argument("conversation_id", required=False)
@click.option("--variant", "-v", help="Prompt variant (brief, standard, detailed, brief_assess, etc.)")
@click.option("--context", "-c", help="Context level (by name or number: 1=minimal, 2=standard, 3=full)")
@click.option("--model", "-m", help="LLM model to use for analysis")
@click.option("--refresh", "-r", "refresh", is_flag=True, help="Force re-analysis (refresh cache)")
@click.option("--no-outputs", is_flag=True, help="Don't show outputs (repos, PRs, issues modified)")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--verbose", is_flag=True, help="Show debug output")
# Multi-conversation options (when conversation_id is not provided)
@click.option("--max", "-n", "limit", type=int, help="Maximum conversations to analyze (default: 10)")
@click.option("--all", "-A", "show_all", is_flag=True, help="Analyze all conversations (no limit)")
@click.option("--offset", "-k", type=int, default=0, help="Skip first N conversations")
@click.option("--since", "-S", "since_date", help="Analyze conversations from DATE onwards")
@click.option("--until", "-U", "until_date", help="Analyze conversations up to DATE")
@click.option("--day", "-D", "day_date", is_flag=False, flag_value="today", default=None,
              help="Analyze conversations from a single day (default: today)")
@click.option("--week", "-W", "week_date", is_flag=False, flag_value="today", default=None,
              help="Analyze conversations from the week containing DATE (default: today)")
@click.option("--pr", "pr_filter", help="Filter by PR (URL, owner/repo#N, or repo#N)")
@click.option("--repo", "repo_filter", help="Filter by repo (URL, owner/repo, or repo name)")
@click.option("--action", "action_filter", help="Filter by action type (e.g., git-push, pushed, open-pr)")
@click.option("--reverse", is_flag=True, help="Show oldest first (default: newest first)")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["table", "json", "markdown"]),
    default="table",
    help="Output format for multi-conversation mode (default: table)",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation for large result sets")
@click.option("--quiet", "-q", is_flag=True, help="Generate/cache summaries without displaying output")
def gen_objs_cmd(
    conversation_id: str | None,
    variant: str | None,
    context: str | None,
    model: str | None,
    refresh: bool,
    no_outputs: bool,
    json_output: bool,
    verbose: bool,
    # Multi-conversation options
    limit: int | None,
    show_all: bool,
    offset: int,
    since_date: str | None,
    until_date: str | None,
    day_date: str | None,
    week_date: str | None,
    pr_filter: str | None,
    repo_filter: str | None,
    action_filter: str | None,
    reverse: bool,
    fmt: str,
    yes: bool,
    quiet: bool,
) -> None:
    """Identify what the user hopes to achieve in a conversation.
    
    Uses the extensible prompt system with family/variant organization.
    
    \b
    SINGLE-CONVERSATION MODE (with conversation_id):
      ohtv gen objs abc123              # Use default variant
      ohtv gen objs abc123 -v brief     # Brief variant
      ohtv gen objs abc123 -c 1         # Context level 1 (minimal)
    
    \b
    MULTI-CONVERSATION MODE (without conversation_id):
      ohtv gen objs                     # Analyze last 10 conversations
      ohtv gen objs --day               # Today's conversations
      ohtv gen objs --week              # This week's conversations
      ohtv gen objs --pr repo#42        # Conversations for a PR
      ohtv gen objs --all               # All conversations (no limit)
    
    \b
    Variants (objs family):
      brief           - Just the goal (1-2 sentences) [default for multi]
      brief_assess    - Goal + status assessment
      standard        - Goal + primary/secondary outcomes
      standard_assess - Standard + status assessment  
      detailed        - Full hierarchical objectives
      detailed_assess - Detailed + status assessment
    
    \b
    Context levels (how much conversation to generate from):
      1 / minimal   - User messages only (lowest tokens) [default for multi]
      2 / standard  - User messages + finish action (recommended)
      3 / full      - All messages + action summaries (highest tokens)
    
    Requires LLM_API_KEY environment variable to be set.
    """
    # Check if filters are being used (multi-conversation options)
    has_filters = any([
        limit is not None, show_all, offset > 0, since_date, until_date,
        day_date, week_date, pr_filter, repo_filter, action_filter, reverse
    ])
    
    # Error if both conversation_id and filters are provided
    if conversation_id is not None and has_filters:
        raise click.UsageError(
            "Cannot use filters (--day, --week, --since, --until, --pr, --repo, "
            "--action, -n, --all, --offset, --reverse) with a specific conversation_id.\n"
            "Either analyze a single conversation: ohtv gen objs <conversation_id>\n"
            "Or analyze multiple conversations: ohtv gen objs --day"
        )
    
    if conversation_id is None:
        # Multi-conversation mode
        _run_batch_objectives_analysis(
            variant=variant,
            context=context,
            model=model,
            refresh=refresh,
            no_outputs=no_outputs,
            verbose=verbose,
            limit=limit,
            show_all=show_all,
            offset=offset,
            since_date=since_date,
            until_date=until_date,
            day_date=day_date,
            week_date=week_date,
            pr_filter=pr_filter,
            repo_filter=repo_filter,
            action_filter=action_filter,
            reverse=reverse,
            fmt=fmt,
            yes=yes,
            quiet=quiet,
        )
    else:
        # Single-conversation mode - use --json for JSON output
        _run_objectives_analysis(
            conversation_id=conversation_id,
            variant=variant,
            context=context,
            model=model,
            refresh=refresh,
            no_outputs=no_outputs,
            json_output=json_output,
            verbose=verbose,
        )


def _run_batch_objectives_analysis(
    *,
    variant: str | None = None,
    context: str | None = None,
    model: str | None = None,
    refresh: bool = False,
    no_outputs: bool = False,
    verbose: bool = False,
    limit: int | None = None,
    show_all: bool = False,
    offset: int = 0,
    since_date: str | None = None,
    until_date: str | None = None,
    day_date: str | None = None,
    week_date: str | None = None,
    pr_filter: str | None = None,
    repo_filter: str | None = None,
    action_filter: str | None = None,
    reverse: bool = False,
    fmt: str = "table",
    yes: bool = False,
    quiet: bool = False,
) -> None:
    """Run objectives analysis on multiple conversations.
    
    This is the batch/summary mode, ported from the legacy `summary` command.
    Uses minimal context + brief detail by default for token efficiency.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Parse date filters and apply shortcuts
    since, until = _parse_date_filters(since_date, until_date, day_date, week_date)

    # Apply all conversation filters (reuses same logic as list command)
    filter_result = _apply_conversation_filters(
        config,
        since=since,
        until=until,
        pr_filter=pr_filter,
        repo_filter=repo_filter,
        action_filter=action_filter,
        include_empty=False,  # Summary always excludes empty
        initial_show_all=show_all,
    )
    
    conversations = filter_result.conversations
    show_all = filter_result.show_all
    total_count = len(conversations)

    # Sort by created_at (newest first by default)
    conversations = sorted(
        conversations,
        key=lambda c: _normalize_datetime_for_sort(c.created_at),
        reverse=not reverse,
    )

    # Apply offset and limit
    # Explicit -n takes precedence over show_all implied by filters
    if offset:
        conversations = conversations[offset:]
    if limit is not None:
        # Explicit limit always applies
        conversations = conversations[:limit]
    elif not show_all:
        # Default limit when no filters and no explicit -n
        conversations = conversations[:10]

    if not conversations:
        console.print("[dim]No conversations found matching the criteria.[/dim]")
        return

    # Import analysis module
    try:
        from ohtv.analysis import analyze_objectives, get_cached_analysis
    except ImportError as e:
        console.print(f"[red]Error:[/red] Analysis module not available: {e}")
        raise SystemExit(1)

    # Map variant to detail+assess for cache compatibility
    # Default to brief for multi-conversation mode (token efficient)
    detail = "brief"
    assess = False
    effective_variant = variant if variant else "brief"
    if variant:
        assess = variant.endswith("_assess")
        detail = variant.replace("_assess", "")
    
    # Default to minimal context for multi-conversation mode (token efficient)
    context_value = context if context else "minimal"
    
    # Resolve prompt metadata to get display schema (if variant has one)
    from ohtv.prompts import resolve_prompt
    display_schema = None
    try:
        prompt_meta = resolve_prompt("objs", effective_variant)
        display_schema = prompt_meta.display
    except ValueError as e:
        # Unknown variant or malformed prompt - fall back to default display
        log.debug("Could not load display schema for variant '%s': %s", effective_variant, e)

    # Safety threshold for LLM analysis - require confirmation for large batches
    SUMMARY_CONFIRM_THRESHOLD = 20
    
    # Count how many actually need LLM computation (for progress bar and confirmation)
    if refresh:
        # --refresh forces all to be recomputed
        uncached_count = len(conversations)
    else:
        # Use fast DB-based cache check
        uncached_count = _count_uncached_conversations_fast(
            conversations, config, context_value, detail, assess
        )
    
    # Get model name for display (short form if available)
    def _get_model_display_name() -> str:
        """Get a display-friendly model name."""
        import os
        os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
        from openhands.sdk import LLM
        llm = LLM.load_from_env()
        if model:
            # User specified a model, use that
            return model.split("/")[-1] if "/" in model else model
        # Try to get clean name from model_info, fall back to model string
        if llm.model_info and llm.model_info.get("key"):
            return llm.model_info["key"]
        return llm.model.split("/")[-1] if "/" in llm.model else llm.model
    
    # Only prompt if we actually need to run LLM on many conversations
    if uncached_count > SUMMARY_CONFIRM_THRESHOLD and not yes:
        from rich.prompt import Confirm
        cached_count = len(conversations) - uncached_count
        model_name = _get_model_display_name()
        console.print(f"[yellow]Warning:[/yellow] About to analyze {uncached_count} conversations with [cyan]{model_name}[/cyan].")
        if cached_count > 0:
            console.print(f"[dim]({cached_count} already cached and will be skipped)[/dim]")
        console.print("[dim]This may take a while and use significant LLM tokens.[/dim]")
        if not Confirm.ask("Do you want to continue?", console=console, default=False):
            console.print("[dim]Aborted. Use --yes to skip this confirmation.[/dim]")
            return

    # Analyze each conversation with progress indicator
    results: list[dict] = []
    errors: list[tuple[str, str]] = []
    total_cost = 0.0
    import time
    import signal
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    start_time = time.perf_counter()
    processed_count = 0
    
    # Use parallel processing for multiple uncached conversations
    # 20 workers to maximize throughput (LLM API rate limits are the real bottleneck)
    max_workers = 20 if uncached_count > 1 else 1
    
    # Thread-safe counters and shutdown flag for parallel mode
    _lock = threading.Lock()
    _shutdown_requested = False
    
    def _handle_shutdown(signum, frame):
        """Handle SIGINT/SIGTERM - request graceful shutdown."""
        nonlocal _shutdown_requested
        _shutdown_requested = True
        console.print("\n[yellow]Shutdown requested - finishing current work...[/yellow]")
    
    # Install signal handlers for graceful shutdown
    old_sigint = signal.signal(signal.SIGINT, _handle_shutdown)
    old_sigterm = signal.signal(signal.SIGTERM, _handle_shutdown)

    def _format_rate(count: int, elapsed: float) -> str:
        """Format processing rate as conv/min."""
        if elapsed < 0.1 or count == 0:
            return "-- conv/min"
        rate = count / (elapsed / 60.0)
        return f"{rate:.1f} conv/min"

    def _analyze_one(conv) -> tuple[dict | None, tuple[str, str] | None, float, bool]:
        """Analyze a single conversation. Returns (result_dict, error_tuple, cost, from_cache)."""
        result = _find_conversation_dir(config, conv.lookup_id)
        if not result:
            return None, (conv.short_id, "Not found"), 0.0, False
        
        conv_dir, _ = result
        
        try:
            analysis_result = analyze_objectives(
                conv_dir,
                model=model,
                context=context_value,
                detail=detail,
                assess=assess,
                force_refresh=refresh,
            )
            analysis = analysis_result.analysis
            # Extract display goal: use goal field, or summary for detailed mode,
            # or first primary objective's description as fallback
            display_goal = analysis.goal
            if not display_goal and analysis.detail_level == "detailed":
                if analysis.summary:
                    display_goal = analysis.summary
                elif analysis.primary_objectives:
                    display_goal = analysis.primary_objectives[0].description
            
            # Build result dict with all analysis fields for display schema rendering
            result_dict = {
                "id": conv.id,
                "short_id": conv.short_id,
                "source": conv.source,
                "created_at": conv.created_at,
                "goal": display_goal or "(no goal identified)",
                "cached": analysis_result.from_cache,
                "conv_dir": conv_dir,
                # Include all analysis fields for variant-aware rendering
                "status": analysis.status,
                "primary_outcomes": analysis.primary_outcomes,
                "secondary_outcomes": analysis.secondary_outcomes,
                "primary_objectives": [
                    {
                        "description": obj.description,
                        "status": obj.status.value if obj.status else None,
                        "evidence": obj.evidence,
                    }
                    for obj in analysis.primary_objectives
                ] if analysis.primary_objectives else [],
                "summary": analysis.summary,
                "detail_level": analysis.detail_level,
                "assess": analysis.assess,
            }
            return result_dict, None, analysis_result.cost, analysis_result.from_cache
        except (ValueError, RuntimeError) as e:
            return None, (conv.short_id, str(e)[:50]), 0.0, False
        except Exception as e:
            if "api_key" in str(e).lower() or "LLM_" in str(e):
                raise  # Re-raise auth errors to handle at top level
            return None, (conv.short_id, str(e)[:50]), 0.0, False

    # Show progress for LLM analysis (skip if all cached)
    # Note: --quiet only suppresses final output, not progress bar or confirmation
    show_progress = uncached_count > 0
    progress_ctx = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[green]$[/green]{task.fields[cost]:.4f}"),
        TextColumn("[dim]{task.fields[rate]}[/dim]"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) if show_progress else nullcontext()

    with progress_ctx as progress:
        task = None
        if show_progress:
            task = progress.add_task(
                f"Analyzing {uncached_count} conversations...",
                total=uncached_count,
                cost=0.0,
                rate="-- conv/min",
            )

        if max_workers == 1:
            # Sequential processing (original behavior)
            for conv in conversations:
                if _shutdown_requested:
                    break
                result_dict, error_tuple, cost, from_cache = _analyze_one(conv)
                
                if error_tuple:
                    errors.append(error_tuple)
                    if task is not None:
                        progress.advance(task)
                elif result_dict:
                    results.append(result_dict)
                    if not from_cache:
                        total_cost += cost
                        processed_count += 1
                        elapsed = time.perf_counter() - start_time
                        if task is not None:
                            progress.update(
                                task,
                                advance=1,
                                cost=total_cost,
                                rate=_format_rate(processed_count, elapsed),
                            )
        else:
            # Parallel processing with ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_conv = {executor.submit(_analyze_one, conv): conv for conv in conversations}
                
                # Process results as they complete
                for future in as_completed(future_to_conv):
                    # Check for shutdown - cancel pending futures and exit
                    if _shutdown_requested:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    
                    try:
                        result_dict, error_tuple, cost, from_cache = future.result()
                    except Exception as e:
                        if "api_key" in str(e).lower() or "LLM_" in str(e):
                            # Cancel remaining futures and raise
                            executor.shutdown(wait=False, cancel_futures=True)
                            console.print(
                                "\n[red]Error:[/red] LLM not configured. Set LLM_API_KEY environment variable."
                            )
                            console.print("[dim]Hint: export LLM_API_KEY=your-api-key[/dim]")
                            raise SystemExit(1)
                        conv = future_to_conv[future]
                        with _lock:
                            errors.append((conv.short_id, str(e)[:50]))
                        if task is not None:
                            progress.advance(task)
                        continue
                    
                    # All list modifications protected by lock for thread safety
                    with _lock:
                        if error_tuple:
                            errors.append(error_tuple)
                        elif result_dict:
                            results.append(result_dict)
                            if not from_cache:
                                total_cost += cost
                                processed_count += 1
                                elapsed = time.perf_counter() - start_time
                    
                    # Progress updates outside lock (Rich Progress is thread-safe)
                    if error_tuple:
                        if task is not None:
                            progress.advance(task)
                    elif result_dict and not from_cache:
                        if task is not None:
                            progress.update(
                                task,
                                advance=1,
                                cost=total_cost,
                                rate=_format_rate(processed_count, elapsed),
                            )
    
    # Restore original signal handlers
    signal.signal(signal.SIGINT, old_sigint)
    signal.signal(signal.SIGTERM, old_sigterm)
    
    # Calculate final rate for summary
    total_elapsed = time.perf_counter() - start_time
    final_rate = _format_rate(processed_count, total_elapsed) if processed_count > 0 else None
    
    # If shutdown was requested, show what we completed and exit
    if _shutdown_requested:
        if results:
            console.print(f"[yellow]Interrupted - showing {len(results)} completed results[/yellow]")
        else:
            console.print("[yellow]Interrupted - no results to show[/yellow]")
            return

    # Skip all output if --quiet is enabled
    if quiet:
        return

    # Extract outputs for each conversation if needed
    if not no_outputs:
        for r in results:
            r["outputs"] = _get_conversation_outputs(r["conv_dir"])

    # Output results
    if fmt == "json":
        json_results = []
        for r in results:
            item = {
                "id": r["id"],
                "source": r["source"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "goal": r["goal"],
            }
            if not no_outputs and r.get("outputs"):
                outputs = r["outputs"]
                refs = outputs.get("refs", {})
                interactions = outputs.get("interactions")
                unpushed = outputs.get("unpushed_commits", set())

                item["refs"] = {
                    "repos": [
                        {"url": url, "actions": sorted(interactions.repos.get(url, [])) if interactions else []}
                        for url in sorted(refs.get("repos", set()))
                    ],
                    "prs": [
                        {"url": url, "actions": sorted(interactions.prs.get(url, [])) if interactions else []}
                        for url in sorted(refs.get("prs", set()))
                    ],
                    "issues": [
                        {"url": url, "actions": sorted(interactions.issues.get(url, [])) if interactions else []}
                        for url in sorted(refs.get("issues", set()))
                    ],
                }
                if unpushed:
                    item["unpushed_commits"] = sorted(unpushed)
            json_results.append(item)
        print(json.dumps(json_results, indent=2))
    elif fmt == "markdown":
        print(_format_summary_markdown(results, include_outputs=not no_outputs))
    else:
        _print_summary_table(
            results, total_count, len(errors),
            include_outputs=not no_outputs,
            display_schema=display_schema,
            variant=effective_variant,
        )

    # Show cost and rate summary if any LLM calls were made
    if total_cost > 0 and fmt == "table":
        rate_str = f" ({final_rate})" if final_rate else ""
        console.print(f"[dim]LLM cost: [green]${total_cost:.4f}[/green]{rate_str}[/dim]")

    # Show errors if any
    if errors and fmt == "table":
        console.print(f"\n[yellow]Failed to analyze {len(errors)} conversation(s):[/yellow]")
        for short_id, error in errors[:5]:  # Show first 5 errors
            console.print(f"  [dim]{short_id}:[/dim] {error}")
        if len(errors) > 5:
            console.print(f"  [dim]... and {len(errors) - 5} more[/dim]")


def _run_objectives_analysis(
    conversation_id: str,
    variant: str | None = None,
    context: str | None = None,
    model: str | None = None,
    refresh: bool = False,
    no_outputs: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    detail: str | None = None,
    assess: bool | None = None,
) -> None:
    """Shared implementation for objectives analysis.
    
    This function supports both the new variant-based interface and the legacy
    detail+assess interface for backward compatibility.
    
    Args:
        conversation_id: Conversation ID to analyze
        variant: Prompt variant (new interface)
        context: Context level name or number (new interface)
        model: LLM model to use
        refresh: Force re-analysis
        no_outputs: Don't show outputs
        json_output: Output as JSON
        verbose: Show debug output
        detail: Detail level (legacy interface: brief, standard, detailed)
        assess: Add assessment (legacy interface)
    """
    _init_logging(verbose=verbose)
    config = Config.from_env()
    
    # Import prompts discovery functions
    from ohtv.prompts import resolve_prompt, resolve_context, list_variants
    
    # Resolve variant from legacy parameters if needed
    if variant is None and detail is not None:
        # Legacy interface: map detail+assess to variant
        variant = detail
        if assess:
            variant = f"{detail}_assess"
    
    # Find conversation
    result = _find_conversation_dir(config, conversation_id)
    if not result:
        console.print(f"[red]Error:[/red] Conversation '{conversation_id}' not found")
        raise SystemExit(1)
    
    conv_dir, _ = result
    conv_id, title = _get_conversation_info(conv_dir)
    
    # Resolve prompt metadata
    try:
        prompt_meta = resolve_prompt("objs", variant)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        available = list_variants("objs")
        console.print(f"[dim]Available variants: {', '.join(available)}[/dim]")
        raise SystemExit(1)
    
    # Resolve context level
    try:
        if context is not None:
            # Try as int first
            try:
                context_num = int(context)
                context_level = resolve_context(prompt_meta, context_num)
            except ValueError:
                # Try as name
                context_level = resolve_context(prompt_meta, context)
        else:
            # Use default context from prompt
            context_level = resolve_context(prompt_meta, None)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(f"[dim]Available context levels:[/dim]")
        for level_num, level in sorted(prompt_meta.context_levels.items()):
            console.print(f"  {level_num} ({level.name})")
        raise SystemExit(1)
    
    # Import analysis module
    try:
        from ohtv.analysis import analyze_objectives, get_cached_analysis, load_events
    except ImportError as e:
        console.print(f"[red]Error:[/red] Analysis module not available: {e}")
        raise SystemExit(1)
    
    # Extract detail level and assess flag from variant for cache compatibility
    variant_name = prompt_meta.variant
    has_assess = variant_name.endswith("_assess")
    detail_level = variant_name.replace("_assess", "")
    
    # Use context level name for cache (minimal, default, full)
    legacy_context = context_level.name
    
    # Check cache if not refreshing
    analysis = None
    analysis_cost = 0.0
    if not refresh:
        analysis = get_cached_analysis(
            conv_dir, 
            context=legacy_context,  # type: ignore[arg-type]
            detail=detail_level,  # type: ignore[arg-type]
            assess=has_assess
        )
    
    # Run analysis if not cached
    if analysis is None:
        events = load_events(conv_dir)
        event_count = len(events) if events else 0
        
        status_msg = f"Analyzing {event_count} events"
        if event_count > 100:
            status_msg += " (this may take a minute)"
        
        try:
            with console.status(f"[bold blue]{status_msg}...[/bold blue]"):
                result = analyze_objectives(
                    conv_dir,
                    model=model,
                    context=legacy_context,  # type: ignore[arg-type]
                    detail=detail_level,  # type: ignore[arg-type]
                    assess=has_assess,
                    force_refresh=refresh
                )
                analysis = result.analysis
                analysis_cost = result.cost
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
        except RuntimeError as e:
            console.print(f"[red]Analysis failed:[/red] {e}")
            raise SystemExit(1)
        except Exception as e:
            if "api_key" in str(e).lower() or "LLM_" in str(e):
                console.print(
                    "[red]Error:[/red] LLM not configured. Set LLM_API_KEY environment variable."
                )
                console.print("[dim]Hint: export LLM_API_KEY=your-api-key[/dim]")
            else:
                console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
    
    # Display results
    if json_output:
        console.print(analysis.model_dump_json(indent=2))
    else:
        _display_objectives(conv_id, title, analysis)
        
        if not no_outputs:
            _display_outputs(conv_dir)
        
        if analysis_cost > 0:
            console.print(f"\n[dim]LLM cost: [green]${analysis_cost:.4f}[/green][/dim]")


if __name__ == "__main__":
    main()
