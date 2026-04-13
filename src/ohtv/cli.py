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

from ohtv.actions import READ_ACTIONS, WRITE_ACTIONS
from ohtv.config import Config


# Commands that use LLM and consume tokens
LLM_COMMANDS = {"objectives", "summary"}


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
        
    Returns:
        FilterResult with filtered conversations and metadata
    """
    show_all = initial_show_all
    
    # Any filter implies --all (show all matching records)
    if any([since, until, pr_filter, repo_filter, action_filter]):
        show_all = True
    
    # Load conversations from both sources
    conversations = _load_all_conversations(config)
    
    # Filter out empty conversations unless requested
    if not include_empty:
        conversations = [c for c in conversations if c.event_count > 0]
    
    # Apply date filtering
    conversations = _filter_by_date_range(conversations, since, until)
    
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

    # Format output
    output_text = _format_list_output(
        conversations, fmt, total_count, local_count, cloud_count, refs_map=refs_map
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
) -> str:
    """Format conversation list for output."""
    if fmt == "json":
        return _format_list_json(conversations, refs_map=refs_map)
    if fmt == "csv":
        return _format_list_csv(conversations, refs_map=refs_map)
    # Table format is handled separately with rich
    return ""


def _format_list_json(
    conversations: list[ConversationInfo],
    *,
    refs_map: dict[str, list[str]] | None = None,
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
        items.append(item)
    return json.dumps(items, indent=2)


def _format_list_csv(
    conversations: list[ConversationInfo],
    *,
    refs_map: dict[str, list[str]] | None = None,
) -> str:
    """Format conversations as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["id", "source", "started", "duration", "events", "title", "repository"]
    if refs_map is not None:
        headers.append("refs")
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
) -> None:
    """Print conversations as a rich table."""
    from ohtv.filters import normalize_conversation_id
    
    if possible_match_ids is None:
        possible_match_ids = set()
    
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", width=7)
    table.add_column("Source", width=6)
    table.add_column("Started", width=16)
    table.add_column("Duration", width=10, justify="right")
    table.add_column("Events", width=6, justify="right")
    table.add_column("Title", no_wrap=False)

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
        
        table.add_row(
            id_display,
            f"[{source_style}]{conv.source}[/{source_style}]",
            started,
            _format_duration(conv.duration) if conv.duration else "",
            str(conv.event_count),
            title_text,
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
    
    # Legend for possible matches
    if possible_match_ids:
        console.print(f"[dim][yellow]*[/yellow] = possible match (action target not available)[/dim]")

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

    # If no content flags specified (and not stats-only), show summary only
    show_content = (
        user_messages or agent_messages or include_finish or
        action_summaries or action_details or show_outputs or thinking
    )

    # Stats-only mode: show statistics and exit
    if stats or not show_content:
        output_text = _format_show_stats(
            conv_id, title, first_ts, last_ts, event_counts, fmt
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
            f"  Thinking:         {event_counts['thinking']}",
            f"  Observations:     {event_counts['observations']}",
            f"  Finish:           {event_counts['finish']}",
            "  ─────────────────────",
            f"  Total:            {total}",
        ]
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
) -> str:
    """Format full output with events."""
    if fmt == "json":
        return _format_show_json(conv_id, title, first_ts, last_ts, event_counts, events)

    # For markdown and text formats
    header = _format_show_stats(conv_id, title, first_ts, last_ts, event_counts, fmt)
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


@main.command()
@click.argument("conversation_id")
@click.option("--refresh", "-r", is_flag=True, help="Force re-analysis (ignore cache)")
@click.option("--model", "-m", help="LLM model to use for analysis")
@click.option(
    "--detail",
    "-d",
    type=click.Choice(["brief", "standard", "detailed"]),
    default="brief",
    help="Output detail: brief (default), standard (with outcomes), detailed (full analysis)",
)
@click.option("--assess", "-a", is_flag=True, help="Assess whether objectives were achieved")
@click.option(
    "--context",
    "-c",
    type=click.Choice(["minimal", "default", "full"]),
    default="default",
    help="Context level: minimal (user only), default (user+finish), full (all messages)",
)
@click.option("--no-outputs", is_flag=True, help="Don't show outputs (repos, PRs, issues modified)")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def objectives(
    conversation_id: str,
    refresh: bool,
    model: str | None,
    detail: str,
    assess: bool,
    context: str,
    no_outputs: bool,
    json_output: bool,
    verbose: bool,
) -> None:
    """Identify what the user hopes to achieve in a conversation.

    By default, outputs a brief 1-2 sentence description of the user's goal,
    followed by any outputs (repositories pushed, PRs created/merged, issues
    modified). Use --no-outputs to hide the outputs section.

    \b
    Detail levels:
      brief     - Just the goal (1-2 sentences) [default]
      standard  - Goal + primary/secondary outcomes (3-6 bullets each)
      detailed  - Full hierarchical objectives with subordinates

    \b
    Use --assess to add status assessment (achieved/not achieved/in_progress)
    to any detail level. Without --assess, only the objectives are shown.

    \b
    Context levels (how much conversation to analyze):
      minimal   - User messages only (lowest tokens)
      default   - User messages + finish action
      full      - All messages + action summaries (highest tokens)

    Note: --assess requires at least 'default' context to see the outcome.

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
        from ohtv.analysis import ObjectiveAnalysis, analyze_objectives, get_cached_analysis, load_events
    except ImportError as e:
        console.print(f"[red]Error:[/red] Analysis module not available: {e}")
        raise SystemExit(1)

    # Check for cached analysis first if not refreshing
    analysis = None
    if not refresh:
        analysis = get_cached_analysis(conv_dir, context=context, detail=detail, assess=assess)  # type: ignore[arg-type]

    # Run analysis if not cached
    if analysis is None:
        # Load events to show progress info
        events = load_events(conv_dir)
        event_count = len(events) if events else 0

        # Show status spinner for potentially long-running analysis
        status_msg = f"Analyzing {event_count} events"
        if event_count > 100:
            status_msg += " (this may take a minute)"

        try:
            with console.status(f"[bold blue]{status_msg}...[/bold blue]"):
                analysis = analyze_objectives(
                    conv_dir, model=model, context=context, detail=detail, assess=assess, force_refresh=refresh  # type: ignore[arg-type]
                )
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

    # Display results
    if json_output:
        console.print(analysis.model_dump_json(indent=2))
    else:
        _display_objectives(conv_id, title, analysis)

        # Show outputs (repos, PRs, issues) unless suppressed
        if not no_outputs:
            _display_outputs(conv_dir)


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


@main.command()
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
@click.option("--refresh", "-r", is_flag=True, help="Force re-analysis (ignore cache)")
@click.option("--model", "-m", help="LLM model to use for analysis")
@click.option(
    "--format", "-F", "fmt",
    type=click.Choice(["table", "json", "markdown"]),
    default="table",
    help="Output format (default: table)",
)
@click.option("--no-outputs", is_flag=True, help="Don't show outputs (repos, PRs, issues modified)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation for large result sets")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def summary(
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
    refresh: bool,
    model: str | None,
    fmt: str,
    no_outputs: bool,
    yes: bool,
    verbose: bool,
) -> None:
    """Summarize goals for multiple conversations.

    Analyzes selected conversations and displays a table of their goals.
    Uses the most token-efficient settings (minimal context, brief output)
    and caches results to avoid repeated LLM calls.

    \b
    Date filtering examples:
      -D           Today's conversations
      -W           This week's conversations
      -S 2024-01-01  Conversations since Jan 1, 2024
      -U 2024-06-30  Conversations until June 30, 2024

    Requires LLM_API_KEY environment variable to be set.
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

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

    # Safety threshold for LLM analysis - require confirmation for large batches
    SUMMARY_CONFIRM_THRESHOLD = 20
    
    if len(conversations) > SUMMARY_CONFIRM_THRESHOLD and not yes:
        from rich.prompt import Confirm
        console.print(f"[yellow]Warning:[/yellow] About to analyze {len(conversations)} conversations.")
        console.print("[dim]This may take a while and use significant LLM tokens.[/dim]")
        if not Confirm.ask("Do you want to continue?", console=console, default=False):
            console.print("[dim]Aborted. Use --yes to skip this confirmation.[/dim]")
            return

    # Import analysis module
    try:
        from ohtv.analysis import analyze_objectives, get_cached_analysis
    except ImportError as e:
        console.print(f"[red]Error:[/red] Analysis module not available: {e}")
        raise SystemExit(1)

    # Analyze each conversation with progress indicator
    results: list[dict] = []
    errors: list[tuple[str, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Analyzing {len(conversations)} conversations...",
            total=len(conversations),
        )

        for conv in conversations:
            # Find conversation directory (use lookup_id which is the directory name)
            result = _find_conversation_dir(config, conv.lookup_id)
            if not result:
                errors.append((conv.short_id, "Not found"))
                progress.advance(task)
                continue

            conv_dir, _ = result

            # Check cache first (use minimal context, brief detail, no assessment)
            analysis = None
            from_cache = False
            if not refresh:
                analysis = get_cached_analysis(
                    conv_dir, context="minimal", detail="brief", assess=False
                )
                from_cache = analysis is not None

            # Run analysis if not cached
            if analysis is None:
                try:
                    analysis = analyze_objectives(
                        conv_dir,
                        model=model,
                        context="minimal",
                        detail="brief",
                        assess=False,
                        force_refresh=refresh,
                    )
                except (ValueError, RuntimeError) as e:
                    errors.append((conv.short_id, str(e)[:50]))
                    progress.advance(task)
                    continue
                except Exception as e:
                    if "api_key" in str(e).lower() or "LLM_" in str(e):
                        console.print(
                            "\n[red]Error:[/red] LLM not configured. Set LLM_API_KEY environment variable."
                        )
                        console.print("[dim]Hint: export LLM_API_KEY=your-api-key[/dim]")
                        raise SystemExit(1)
                    errors.append((conv.short_id, str(e)[:50]))
                    progress.advance(task)
                    continue

            # Store result (include conv_dir for outputs extraction)
            results.append({
                "id": conv.id,
                "short_id": conv.short_id,
                "source": conv.source,
                "created_at": conv.created_at,
                "goal": analysis.goal or "(no goal identified)",
                "cached": from_cache,
                "conv_dir": conv_dir,
            })

            progress.advance(task)

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
        _print_summary_table(results, total_count, len(errors), include_outputs=not no_outputs)

    # Show errors if any
    if errors and fmt == "table":
        console.print(f"\n[yellow]Failed to analyze {len(errors)} conversation(s):[/yellow]")
        for short_id, error in errors[:5]:  # Show first 5 errors
            console.print(f"  [dim]{short_id}:[/dim] {error}")
        if len(errors) > 5:
            console.print(f"  [dim]... and {len(errors) - 5} more[/dim]")


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
) -> None:
    """Print summary results as a table."""
    table = Table(show_header=True, header_style="bold", show_lines=True)
    table.add_column("ID", style="cyan", width=7, no_wrap=True)
    table.add_column("Date", width=10, no_wrap=True)
    table.add_column("Summary", no_wrap=False)

    for r in results:
        date_str = ""
        if r["created_at"]:
            local_time = r["created_at"].astimezone()
            date_str = local_time.strftime("%Y-%m-%d")

        # Build the summary cell content
        summary_parts = [r["goal"]]

        # Add refs/outputs if present
        if include_outputs and r.get("outputs"):
            ref_lines = _format_refs_for_summary(r["outputs"])
            summary_parts.extend(ref_lines)

        summary_cell = "\n".join(summary_parts)

        table.add_row(
            r["short_id"],
            date_str,
            summary_cell,
        )

    console.print(table)

    # Summary line: "Showing 5 of 100 (3/5 cached)"
    showing = len(results)
    cached = sum(1 for r in results if r.get("cached", False))

    summary_parts = [f"Showing {showing} of {total_count}"]
    if showing > 0:
        summary_parts.append(f"({cached}/{showing} cached)")
    if error_count > 0:
        summary_parts.append(f"{error_count} failed")

    console.print(f"[dim]{' '.join(summary_parts)}[/dim]")


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
    """Find conversation directory across both local and cloud sources.

    Returns:
        Tuple of (directory_path, is_cloud_source) or None if not found
    """
    # Normalize conv_id - remove dashes for directory lookup
    # (ConversationInfo.id has dashes, but directory names don't)
    normalized_id = conv_id.replace("-", "")
    
    # Search both directories - local first, then cloud
    dirs_to_search = [
        (config.local_conversations_dir, False),  # (path, is_cloud)
        (config.cloud_conversations_dir, True),
    ]

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
    """
    refs: dict[str, set[str]] = {
        "repos": set(),
        "issues": set(),
        "prs": set(),
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

    return refs


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
@click.argument("stage", type=click.Choice(["refs", "actions", "all"]))
@click.option("--force", "-f", is_flag=True, help="Reprocess all conversations, ignoring stage completion")
@click.option("--conversation", "-c", help="Process only this conversation ID")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def db_process(stage: str, force: bool, conversation: str | None, verbose: bool) -> None:
    """Run a processing stage on conversations.
    
    Processes conversations that need it (never processed or have new events).
    Use --force to reprocess all conversations regardless of status.
    
    \b
    Available stages:
      refs     - Extract repository, issue, and PR references
      actions  - Recognize actions (file edits, git ops, PRs, etc.)
      all      - Run all stages in sequence
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
    
    Discovers conversations from both local CLI (~/.openhands/conversations/)
    and synced cloud (~/.openhands/cloud/conversations/) directories.
    
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


if __name__ == "__main__":
    main()
