"""Command-line interface for ohtv."""

import json
import re
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ohtv.config import Config
from ohtv.logging import setup_logging
from ohtv.sync import SyncAbortedError, SyncAuthError, SyncManager, SyncResult

console = Console()

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


@main.command()
@click.argument("conversation_id")
@click.option("--source", type=click.Choice(["local", "cloud"]), help="Data source")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output")
def refs(conversation_id: str, source: str | None, verbose: bool) -> None:
    """Extract repository, issue, and PR references from a conversation."""
    _init_logging(verbose=verbose)
    config = Config.from_env()

    # Determine which directory to use
    src = source or config.source
    conv_dir = _find_conversation_dir(config, conversation_id, src)

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


def _find_conversation_dir(config: Config, conv_id: str, source: str) -> Path | None:
    """Find conversation directory, supporting partial ID matching."""
    base_dir = config.cloud_conversations_dir if source == "cloud" else config.local_conversations_dir

    if not base_dir.exists():
        return None

    # Try exact match first
    exact = base_dir / conv_id
    if exact.exists():
        return exact

    # Try prefix match
    matches = [d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith(conv_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        console.print(f"[yellow]Ambiguous ID:[/yellow] {len(matches)} matches. Provide more characters.")
        for m in matches[:5]:
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
