"""Sync cloud conversations to local storage."""

import json
import logging
import shutil
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from ohtv.config import Config, get_manifest_path
from ohtv.exporter import TrajectoryExporter, count_events
from ohtv.sources.cloud import CloudClient, RateLimitExceededError

log = logging.getLogger("ohtv")

# Number of parallel workers for API calls
# Conservative value to avoid overwhelming rate limits on download API
DEFAULT_MAX_WORKERS = 3


class SyncAuthError(Exception):
    """Raised when API authentication fails."""


class SyncAbortedError(Exception):
    """Raised when sync is aborted due to too many failures."""


@dataclass
class SyncResult:
    """Results of a sync operation."""

    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    skipped_new: int = 0  # New conversations skipped due to max_new limit
    errors: list[tuple[str, str]] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    total_to_process: int = 0  # Total conversations to process (for progress display)

    @property
    def total_synced(self) -> int:
        return self.new + self.updated

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

    @property
    def has_skipped_new(self) -> bool:
        return self.skipped_new > 0
    
    @property
    def processed_count(self) -> int:
        """Total processed (excluding skipped_new which aren't processed)."""
        return self.new + self.updated + self.unchanged + self.failed


@dataclass
class MetadataRefreshResult:
    """Results of a metadata-only refresh (Issue #86).

    Reports what was learned from comparing the cloud listing against the
    local manifest. Does NOT modify ``manifest.last_sync_at`` or
    ``manifest.sync_count`` — this is an out-of-band pass that never
    downloads trajectories.
    """

    checked: int = 0
    title_changed: int = 0
    labels_changed: int = 0
    both_changed: int = 0
    unchanged: int = 0
    new_on_cloud: int = 0       # In cloud listing but not in manifest (count only)
    missing_on_cloud: int = 0   # In manifest but not in cloud listing (count only)
    errors: list[tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def total_changed(self) -> int:
        """Number of manifest entries that received at least one change."""
        # both_changed counts a single conv whose title and labels both differ.
        # title_changed and labels_changed are individual field counters; their
        # sum minus both_changed (which we counted in BOTH columns) gives the
        # number of entries touched at least once.
        return self.title_changed + self.labels_changed - self.both_changed

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


@dataclass
class RepairResult:
    """Results of a repair operation."""

    cloud_count: int = 0
    manifest_count: int = 0
    disk_counts_by_dir: dict[str, int] = field(default_factory=dict)  # Directory path -> count
    ghost_entries: list[str] = field(default_factory=list)  # In manifest but not on disk
    orphaned_files: list[str] = field(default_factory=list)  # On disk but not in manifest
    added_to_manifest: int = 0
    removed_from_manifest: int = 0

    @property
    def disk_count(self) -> int:
        """Total conversations on disk across all directories."""
        return sum(self.disk_counts_by_dir.values())

    @property
    def is_consistent(self) -> bool:
        return not self.ghost_entries and not self.orphaned_files

    @property
    def cloud_disk_match(self) -> bool:
        return self.cloud_count == self.disk_count


@dataclass
class SyncManifest:
    """Persistent sync state."""

    last_sync_at: datetime | None
    sync_count: int
    conversations: dict[str, dict]  # id -> {title, updated_at, event_count, downloaded_at}
    failed_ids: list[str] = field(default_factory=list)  # IDs that failed last sync

    @classmethod
    def load(cls, path: Path) -> "SyncManifest":
        """Load manifest from file or create empty."""
        if not path.exists():
            return cls(last_sync_at=None, sync_count=0, conversations={}, failed_ids=[])
        data = json.loads(path.read_text())
        return cls(
            last_sync_at=_parse_datetime(data.get("last_sync_at")),
            sync_count=data.get("sync_count", 0),
            conversations=data.get("conversations", {}),
            failed_ids=data.get("failed_ids", []),
        )

    def save(self, path: Path) -> None:
        """Save manifest to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_sync_at": _format_datetime(self.last_sync_at),
            "sync_count": self.sync_count,
            "conversations": self.conversations,
            "failed_ids": self.failed_ids,
        }
        path.write_text(json.dumps(data, indent=2))


class SyncManager:
    """Orchestrates sync of cloud conversations."""

    def __init__(self, config: Config):
        self.config = config
        self.manifest_path = get_manifest_path()
        self.manifest = SyncManifest.load(self.manifest_path)
        self.exporter = TrajectoryExporter(config.synced_conversations_dir)

    def sync(
        self,
        force: bool = False,
        since: datetime | None = None,
        dry_run: bool = False,
        max_new: int | None = None,
        on_progress: Callable[[str, str, str], None] | None = None,
        parallel: bool = True,
        shutdown_check: Callable[[], bool] | None = None,
    ) -> SyncResult:
        """Sync conversations from cloud.
        
        Args:
            force: Re-download all conversations (clears local before re-download)
            since: Only sync conversations updated after this date
            dry_run: Show what would sync without downloading
            max_new: Maximum number of NEW conversations to sync (no limit on updates)
            on_progress: Callback for progress updates (conv_id, title, action)
            parallel: Use parallel downloads (default True, uses 20 workers)
            shutdown_check: Optional function that returns True to request graceful shutdown
        """
        if not self.config.api_key:
            raise ValueError("API key required. Set OPENHANDS_API_KEY or OH_API_KEY environment variable.")

        cutoff = self._determine_cutoff(force, since)
        log.info("Starting sync (force=%s, cutoff=%s, dry_run=%s, max_new=%s, parallel=%s)", 
                 force, cutoff, dry_run, max_new, parallel)

        try:
            with CloudClient(self.config.cloud_api_url, self.config.api_key) as client:
                conversations = client.search_all_conversations(updated_since=cutoff)
                conversations = self._add_failed_conversations(conversations)
                log.info("Found %d conversations to process", len(conversations))
                return self._process_conversations(
                    client, conversations, force, dry_run, max_new, on_progress, 
                    parallel=parallel, shutdown_check=shutdown_check
                )
        except httpx.HTTPStatusError as e:
            log.error("HTTP error during sync: %s %s", e.response.status_code, e.response.reason_phrase)
            if e.response.status_code in (401, 403):
                raise SyncAuthError(f"Authentication failed (HTTP {e.response.status_code}). Check your API key.")
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.error("Network error during sync: %s", e)
            raise SyncAbortedError(f"Network error: {e}")

    def _add_failed_conversations(self, conversations: list[dict]) -> list[dict]:
        """Add previously failed conversations to the sync list for retry."""
        if not self.manifest.failed_ids:
            return conversations

        existing_ids = {c["id"] for c in conversations}
        retry_count = 0

        for failed_id in self.manifest.failed_ids:
            if failed_id not in existing_ids:
                conversations.append({
                    "id": failed_id,
                    "title": "(retry)",
                    "updated_at": "",
                })
                retry_count += 1

        if retry_count > 0:
            log.info("Adding %d previously failed conversations for retry", retry_count)

        return conversations

    def _determine_cutoff(self, force: bool, since: datetime | None) -> datetime | None:
        """Determine the cutoff date for syncing."""
        if force:
            return None
        if since:
            return since
        return self.manifest.last_sync_at

    def _process_conversations(
        self,
        client: CloudClient,
        conversations: list[dict],
        force: bool,
        dry_run: bool,
        max_new: int | None,
        on_progress: Callable[[str, str, str], None] | None,
        parallel: bool = True,
        shutdown_check: Callable[[], bool] | None = None,
    ) -> SyncResult:
        """Process each conversation that needs syncing.
        
        Args:
            client: Cloud API client
            conversations: List of conversation dicts from API
            force: Re-download all conversations
            dry_run: Don't actually download, just report what would happen
            max_new: Limit on number of new conversations to sync
            on_progress: Callback for progress updates
            parallel: Use parallel downloads (default True)
            shutdown_check: Optional function that returns True to request graceful shutdown
        """
        result = SyncResult()
        
        # Phase 1: Determine what action to take for each conversation
        # This handles max_new limit correctly before parallel processing
        work_items = self._categorize_conversations(conversations, force, max_new, result)
        
        # Set total for progress display (excluding skipped items)
        result.total_to_process = sum(1 for _, action in work_items if action != "skipped")
        
        # Phase 2: Handle dry-run or unchanged (no download needed)
        # Also notify progress callback of total on first call
        first_progress_call = True
        to_download = []
        for conv, action in work_items:
            if action in ("unchanged", "skipped") or dry_run:
                self._update_result(result, action)
                if on_progress:
                    # Pass total on first call so progress bar can set its total
                    if first_progress_call:
                        on_progress(conv["id"], conv.get("title", "")[:50], action, result.total_to_process)
                        first_progress_call = False
                    else:
                        on_progress(conv["id"], conv.get("title", "")[:50], action)
            else:
                to_download.append((conv, action))
        
        # Phase 3: Download conversations (parallel or sequential)
        if to_download:
            # If no items were processed in phase 2, pass total on first download callback
            pass_total = first_progress_call
            if parallel and len(to_download) > 1:
                self._download_parallel(client, to_download, result, on_progress, shutdown_check, pass_total)
            else:
                self._download_sequential(client, to_download, result, on_progress, shutdown_check, pass_total)

        if not dry_run:
            self._finalize_sync(result)
        return result

    def _categorize_conversations(
        self,
        conversations: list[dict],
        force: bool,
        max_new: int | None,
        result: SyncResult,
    ) -> list[tuple[dict, str]]:
        """Determine action for each conversation, respecting max_new limit.
        
        Returns list of (conv, action) tuples.
        """
        work_items = []
        new_count = 0
        
        for conv in conversations:
            conv_id = conv["id"]
            cloud_updated_at = conv.get("updated_at", "")
            action = self._determine_action(conv_id, cloud_updated_at, force)
            
            # Handle max_new limit
            if action == "new":
                if max_new is not None and new_count >= max_new:
                    action = "skipped"
                    result.skipped_new += 1
                else:
                    new_count += 1
            
            work_items.append((conv, action))
        
        return work_items

    def _download_sequential(
        self,
        client: CloudClient,
        work_items: list[tuple[dict, str]],
        result: SyncResult,
        on_progress: Callable[[str, str, str], None] | None,
        shutdown_check: Callable[[], bool] | None = None,
        pass_total_on_first: bool = False,
    ) -> None:
        """Download conversations sequentially."""
        consecutive_failures = 0
        max_consecutive_failures = 5
        first_callback = True
        
        for conv, planned_action in work_items:
            if shutdown_check and shutdown_check():
                log.info("Shutdown requested, stopping sync")
                break
            
            conv_id = conv["id"]
            cloud_updated_at = conv.get("updated_at", "")
            title = conv.get("title", "")[:50]
            
            # Clean up for force mode
            if planned_action == "updated":
                self._cleanup_conversation_dir(conv_id)
            
            actual_action = self._download_and_update(
                client, conv, conv_id, cloud_updated_at, planned_action, result
            )
            self._update_result(result, actual_action)
            if on_progress:
                if first_callback and pass_total_on_first:
                    on_progress(conv_id, title, actual_action, result.total_to_process)
                    first_callback = False
                else:
                    on_progress(conv_id, title, actual_action)
            
            consecutive_failures = self._check_abort(actual_action, consecutive_failures, max_consecutive_failures)

    def _download_parallel(
        self,
        client: CloudClient,
        work_items: list[tuple[dict, str]],
        result: SyncResult,
        on_progress: Callable[[str, str, str], None] | None,
        shutdown_check: Callable[[], bool] | None = None,
        pass_total_on_first: bool = False,
    ) -> None:
        """Download conversations in parallel using a thread pool.
        
        Rate limiting is handled by a shared rate limiter in the CloudClient,
        so when one worker hits a 429, all workers will pause before making
        new requests.
        """
        max_workers = min(DEFAULT_MAX_WORKERS, len(work_items))
        log.info("Starting parallel download with %d workers for %d conversations", 
                 max_workers, len(work_items))
        
        # Thread-safe lock for result updates
        lock = threading.Lock()
        total_failures = 0
        max_total_failures = len(work_items) // 2 + 5  # Allow up to ~50% failures before aborting
        abort_requested = False
        first_callback = [True]  # Mutable for thread-safe first-call detection
        
        def download_one(item: tuple[dict, str]) -> tuple[dict, str, str]:
            """Download a single conversation. Returns (conv, planned_action, actual_action)."""
            conv, planned_action = item
            conv_id = conv["id"]
            cloud_updated_at = conv.get("updated_at", "")
            
            # Clean up for force mode (thread-safe - each conv has its own dir)
            if planned_action == "updated":
                self._cleanup_conversation_dir(conv_id)
            
            actual_action = self._download_and_update(
                client, conv, conv_id, cloud_updated_at, planned_action, result
            )
            return conv, planned_action, actual_action
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {executor.submit(download_one, item): item for item in work_items}
            
            pending = set(future_to_item.keys())
            while pending:
                # Check for shutdown
                if shutdown_check and shutdown_check():
                    log.info("Shutdown requested, cancelling remaining downloads")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                
                if abort_requested:
                    log.info("Aborting due to too many failures")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                
                # Wait with timeout to allow shutdown check
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                
                for future in done:
                    try:
                        conv, planned_action, actual_action = future.result()
                    except SyncAuthError:
                        # Re-raise auth errors - they apply to all requests
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise
                    except Exception as e:
                        # Unexpected error in the download function
                        item = future_to_item[future]
                        conv, _ = item
                        log.error("Unexpected error downloading %s: %s", conv["id"], e)
                        actual_action = "failed"
                        with lock:
                            self._record_failure(result, conv["id"], str(e))
                    
                    # Update result (thread-safe)
                    with lock:
                        self._update_result(result, actual_action)
                        if actual_action == "failed":
                            total_failures += 1
                            if total_failures >= max_total_failures:
                                abort_requested = True
                    
                    # Progress callback
                    if on_progress:
                        with lock:
                            is_first = first_callback[0]
                            if is_first:
                                first_callback[0] = False
                        
                        if is_first and pass_total_on_first:
                            on_progress(conv["id"], conv.get("title", "")[:50], actual_action, result.total_to_process)
                        else:
                            on_progress(conv["id"], conv.get("title", "")[:50], actual_action)

    def _check_abort(self, action: str, consecutive_failures: int, max_failures: int) -> int:
        """Check if we should abort due to too many consecutive failures."""
        if action == "failed":
            consecutive_failures += 1
            if consecutive_failures >= max_failures:
                log.error("Aborting after %d consecutive failures", max_failures)
                raise SyncAbortedError(f"Aborting after {max_failures} consecutive failures")
            return consecutive_failures
        return 0  # Reset on success

    def _cleanup_conversation_dir(self, conv_id: str) -> None:
        """Remove existing conversation directory before re-download."""
        conv_dir = self.config.synced_conversations_dir / conv_id
        if conv_dir.exists():
            log.debug("Cleaning up existing directory for %s", conv_id)
            shutil.rmtree(conv_dir)

    def _determine_action(self, conv_id: str, cloud_updated_at: str, force: bool) -> str:
        """Determine what action to take for a conversation."""
        local_info = self.manifest.conversations.get(conv_id)
        if not local_info:
            return "new"
        if force or local_info.get("updated_at", "") < cloud_updated_at:
            return "updated"
        return "unchanged"

    def _download_and_update(
        self,
        client: CloudClient,
        conv: dict,
        conv_id: str,
        cloud_updated_at: str,
        action: str,
        result: SyncResult,
    ) -> str:
        """Download conversation and update manifest."""
        try:
            log.debug("Downloading %s", conv_id)
            zip_bytes = client.download_trajectory(conv_id)
            conv_dir = self.exporter.export_from_zip_bytes(conv_id, zip_bytes)
            self._update_manifest_entry(conv, conv_id, cloud_updated_at, conv_dir)
            log.debug("Downloaded %s (%s)", conv_id, action)
            return action
        except httpx.HTTPStatusError as e:
            return self._handle_http_error(e, conv_id, result)
        except RateLimitExceededError as e:
            log.warning("Rate limit exceeded for %s: %s", conv_id, e)
            self._record_failure(result, conv_id, "Rate limit exceeded after retries")
            return "failed"
        except Exception as e:
            log.warning("Failed to download %s: %s", conv_id, e)
            self._record_failure(result, conv_id, str(e))
            return "failed"

    def _record_failure(self, result: SyncResult, conv_id: str, error: str) -> None:
        """Record a download failure."""
        result.errors.append((conv_id, error))
        result.failed_ids.append(conv_id)

    def _handle_http_error(
        self, error: httpx.HTTPStatusError, conv_id: str, result: SyncResult
    ) -> str:
        """Handle HTTP errors, raising for auth failures."""
        status = error.response.status_code
        if status in (401, 403):
            log.error("Authentication failed for %s: HTTP %s", conv_id, status)
            raise SyncAuthError(f"Authentication failed (HTTP {status}). Check your API key.")
        log.warning("HTTP error for %s: %s %s", conv_id, status, error.response.reason_phrase)
        self._record_failure(result, conv_id, f"HTTP {status}: {error.response.reason_phrase}")
        return "failed"

    def _update_manifest_entry(
        self,
        conv: dict,
        conv_id: str,
        cloud_updated_at: str,
        conv_dir: Path,
    ) -> None:
        """Update the manifest with new conversation info."""
        # Extract labels/tags from API response (may be empty dict or None)
        tags = conv.get("tags")
        labels = tags if tags and isinstance(tags, dict) and len(tags) > 0 else None
        
        self.manifest.conversations[conv_id] = {
            "title": conv.get("title"),
            "updated_at": cloud_updated_at,
            "event_count": count_events(conv_dir),
            "downloaded_at": _format_datetime(datetime.now(timezone.utc)),
            "labels": labels,
        }

    def _update_result(self, result: SyncResult, action: str) -> None:
        """Update result counters based on action."""
        if action == "new":
            result.new += 1
        elif action == "updated":
            result.updated += 1
        elif action == "unchanged":
            result.unchanged += 1
        elif action == "failed":
            result.failed += 1
        elif action == "skipped":
            result.skipped_new += 1

    def _finalize_sync(self, result: SyncResult) -> None:
        """Update and save manifest after sync."""
        self.manifest.failed_ids = result.failed_ids
        self.manifest.sync_count += 1

        # Don't advance cutoff if there were failures or skipped new conversations
        if result.has_failures:
            log.warning(
                "Sync complete with %d failures. Not advancing cutoff. "
                "Run 'ohtv sync' again to retry failed conversations.",
                result.failed,
            )
        elif result.has_skipped_new:
            log.info(
                "Sync complete. Synced %d new, %d additional available. "
                "Not advancing cutoff so skipped conversations remain visible.",
                result.new, result.skipped_new,
            )
        else:
            self.manifest.last_sync_at = datetime.now(timezone.utc)
            log.info("Sync complete. Total conversations: %d", len(self.manifest.conversations))

        self.manifest.save(self.manifest_path)

    def get_status(self) -> dict:
        """Get current sync status."""
        total_events = sum(c.get("event_count", 0) for c in self.manifest.conversations.values())
        return {
            "last_sync_at": self.manifest.last_sync_at,
            "sync_count": self.manifest.sync_count,
            "total_conversations": len(self.manifest.conversations),
            "total_events": total_events,
            "pending_retries": len(self.manifest.failed_ids),
        }

    def get_local_conversation_count(self) -> int:
        """Get count of locally synced conversations."""
        return len(self.manifest.conversations)

    def repair(
        self,
        fix: bool = False,
        check_cloud: bool = True,
    ) -> RepairResult:
        """Check and optionally repair sync state consistency.
        
        Compares:
        1. Manifest entries vs actual files on disk
        2. Total cloud conversations vs local count
        
        Scans all configured directories:
        - synced_conversations_dir (cloud-synced)
        - local_conversations_dir (local CLI)
        - extra_conversation_paths (additional sources)
        
        Args:
            fix: If True, repair inconsistencies (add orphaned files to manifest,
                 remove ghost entries)
            check_cloud: If True, query cloud API for total conversation count
        
        Returns:
            RepairResult with counts and lists of discrepancies
        """
        result = RepairResult()
        
        # Get manifest conversation IDs (normalized without dashes)
        manifest_ids = set(self.manifest.conversations.keys())
        result.manifest_count = len(manifest_ids)
        
        # Build list of all directories to scan
        all_dirs: list[Path] = []
        synced_dir = self.config.synced_conversations_dir
        all_dirs.append(synced_dir)
        all_dirs.append(self.config.local_conversations_dir)
        all_dirs.extend(self.config.extra_conversation_paths)
        
        # Scan all directories for conversation counts
        disk_ids: set[str] = set()  # IDs from synced dir only (for ghost/orphan detection)
        for conv_dir in all_dirs:
            count = self._count_conversations_in_dir(conv_dir)
            if count > 0:
                result.disk_counts_by_dir[str(conv_dir)] = count
            
            # For ghost/orphan detection, only check synced directory
            if conv_dir == synced_dir and conv_dir.exists():
                for d in conv_dir.iterdir():
                    if d.is_dir():
                        conv_id = d.name.replace("-", "")
                        disk_ids.add(conv_id)
        
        # Find discrepancies (only in synced directory)
        result.ghost_entries = sorted(manifest_ids - disk_ids)
        result.orphaned_files = sorted(disk_ids - manifest_ids)
        
        log.info(
            "Repair check: manifest=%d, disk=%d, ghosts=%d, orphaned=%d",
            result.manifest_count, result.disk_count,
            len(result.ghost_entries), len(result.orphaned_files)
        )
        
        # Check cloud count if requested and API key available
        if check_cloud and self.config.api_key:
            try:
                with CloudClient(self.config.cloud_api_url, self.config.api_key) as client:
                    result.cloud_count = client.count_conversations()
                    log.info("Cloud conversation count: %d", result.cloud_count)
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403):
                    raise SyncAuthError(f"Authentication failed (HTTP {e.response.status_code}). Check your API key.")
                log.warning("Failed to get cloud count: HTTP %s", e.response.status_code)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                log.warning("Failed to get cloud count: %s", e)
        
        # Apply fixes if requested
        if fix:
            # Remove ghost entries from manifest
            for ghost_id in result.ghost_entries:
                del self.manifest.conversations[ghost_id]
                result.removed_from_manifest += 1
            
            # Add orphaned files to manifest
            for orphan_id in result.orphaned_files:
                conv_dir = self._find_conversation_dir(orphan_id)
                if conv_dir:
                    self.manifest.conversations[orphan_id] = {
                        "title": None,  # Unknown - could fetch from cloud if needed
                        "updated_at": None,
                        "event_count": count_events(conv_dir),
                        "downloaded_at": _format_datetime(datetime.now(timezone.utc)),
                    }
                    result.added_to_manifest += 1
            
            if result.removed_from_manifest > 0 or result.added_to_manifest > 0:
                self.manifest.save(self.manifest_path)
                log.info(
                    "Repair applied: removed %d ghost entries, added %d orphaned files",
                    result.removed_from_manifest, result.added_to_manifest
                )
        
        return result

    # ------------------------------------------------------------------ #
    # Metadata-only refresh (Issue #86)
    # ------------------------------------------------------------------ #

    def update_metadata(
        self,
        *,
        dry_run: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
        client: CloudClient | None = None,
    ) -> MetadataRefreshResult:
        """Refresh cached ``title`` and ``labels`` for synced conversations.

        Lists every cloud conversation (unfiltered by ``updated_at``), then
        for each manifest entry that also appears in the listing, rewrites
        the manifest's ``title``/``labels`` fields and the DB row when
        they differ. Never downloads trajectories.

        Args:
            dry_run: If True, count diffs but do not write the manifest or
                DB. Manifest file mtime is preserved.
            on_progress: Optional callback ``(processed, total)`` invoked
                after each manifest entry is checked. Useful for CLI
                progress bars.
            client: Optional pre-opened CloudClient to reuse (e.g. from
                an auto-run after a normal sync). If None, opens a new
                client using ``self.config``.

        Returns:
            MetadataRefreshResult with diff counts and any errors.

        Raises:
            ValueError: If no API key is configured.
            SyncAuthError: On 401/403 from the cloud API.
            SyncAbortedError: On unrecoverable network errors.
        """
        if not self.config.api_key:
            raise ValueError(
                "API key required. Set OPENHANDS_API_KEY or OH_API_KEY environment variable."
            )

        import time as _time
        start = _time.perf_counter()
        result = MetadataRefreshResult()

        try:
            if client is not None:
                cloud_by_id = self._fetch_cloud_listing_by_id(client)
            else:
                with CloudClient(self.config.cloud_api_url, self.config.api_key) as new_client:
                    cloud_by_id = self._fetch_cloud_listing_by_id(new_client)
        except httpx.HTTPStatusError as e:
            log.error("HTTP error during metadata refresh: %s %s",
                      e.response.status_code, e.response.reason_phrase)
            if e.response.status_code in (401, 403):
                raise SyncAuthError(
                    f"Authentication failed (HTTP {e.response.status_code}). Check your API key."
                )
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.error("Network error during metadata refresh: %s", e)
            raise SyncAbortedError(f"Network error: {e}")

        # Compute diffs against the manifest. We snapshot the manifest IDs up
        # front so changes during iteration are deterministic.
        manifest_ids = list(self.manifest.conversations.keys())
        cloud_ids = set(cloud_by_id.keys())
        result.new_on_cloud = len(cloud_ids - set(manifest_ids))
        manifest_only = [cid for cid in manifest_ids if cid not in cloud_by_id]
        result.missing_on_cloud = len(manifest_only)

        in_both = [cid for cid in manifest_ids if cid in cloud_by_id]
        total = len(in_both)
        any_change_applied = False
        store = self._get_conversation_store()

        for i, conv_id in enumerate(in_both):
            cloud_conv = cloud_by_id[conv_id]
            manifest_entry = self.manifest.conversations[conv_id]
            title_changed, labels_changed = _metadata_differs(cloud_conv, manifest_entry)

            result.checked += 1
            if not (title_changed or labels_changed):
                result.unchanged += 1
            else:
                if title_changed:
                    result.title_changed += 1
                if labels_changed:
                    result.labels_changed += 1
                if title_changed and labels_changed:
                    result.both_changed += 1

                if not dry_run:
                    try:
                        new_title = cloud_conv.get("title") if title_changed else manifest_entry.get("title")
                        new_labels = _normalize_labels(cloud_conv.get("tags")) if labels_changed else _normalize_labels(manifest_entry.get("labels"))
                        self._write_manifest_metadata(
                            conv_id,
                            title=new_title,
                            labels=new_labels,
                        )
                        any_change_applied = True
                        if store is not None:
                            try:
                                store.update_metadata(
                                    conv_id,
                                    title=new_title,
                                    labels=new_labels,
                                )
                            except Exception as e:
                                log.warning(
                                    "Failed to update DB metadata for %s: %s", conv_id, e
                                )
                                result.errors.append((conv_id, f"db: {e}"))
                    except Exception as e:
                        log.warning("Failed to update manifest metadata for %s: %s", conv_id, e)
                        result.errors.append((conv_id, str(e)))

            if on_progress:
                try:
                    on_progress(i + 1, total)
                except Exception:  # pragma: no cover - never let progress crash sync
                    pass

        if any_change_applied and not dry_run:
            self.manifest.save(self.manifest_path)
            # Commit DB writes if we opened a connection
            if store is not None and store.conn is not None:
                try:
                    store.conn.commit()
                except Exception as e:  # pragma: no cover - best effort
                    log.warning("Failed to commit DB metadata updates: %s", e)

        # Always close the DB connection we opened in _get_conversation_store.
        # We own the connection lifecycle here (the factory returns a raw
        # sqlite3.Connection — not a context manager).
        if store is not None and store.conn is not None:
            try:
                store.conn.close()
            except Exception as e:  # pragma: no cover - best effort
                log.warning("Failed to close DB metadata connection: %s", e)

        result.elapsed_seconds = _time.perf_counter() - start
        log.info(
            "Metadata refresh complete: checked=%d title_changed=%d labels_changed=%d "
            "both_changed=%d unchanged=%d new_on_cloud=%d missing_on_cloud=%d errors=%d",
            result.checked, result.title_changed, result.labels_changed, result.both_changed,
            result.unchanged, result.new_on_cloud, result.missing_on_cloud, len(result.errors),
        )
        return result

    @staticmethod
    def _fetch_cloud_listing_by_id(client: CloudClient) -> dict[str, dict]:
        """Pull the full unfiltered listing and key it by conversation id."""
        items = client.search_all_conversations(updated_since=None)
        return {item["id"]: item for item in items if "id" in item}

    def _get_conversation_store(self):
        """Open a DB connection + ConversationStore, returning None on failure.

        Errors are logged at info level — failure to open the DB does not
        abort the manifest-only refresh, since manifest writes still benefit
        the user and the DB will be reconciled on the next ``db scan``.

        Returns a ``ConversationStore`` backed by a raw ``sqlite3.Connection``.
        The caller owns the connection lifecycle and must call
        ``store.conn.close()`` when finished. We open a real connection here
        (rather than entering ``get_connection()`` as a context manager)
        because ``ConversationStore`` expects a live ``sqlite3.Connection``,
        and entering/exiting the CM around each call would also create a
        new connection per call — defeating the point of holding a store.
        """
        try:
            import sqlite3

            from ohtv.db import get_db_path
            from ohtv.db.stores import ConversationStore
        except Exception as e:  # pragma: no cover - defensive
            log.info("DB module unavailable, skipping DB metadata updates: %s", e)
            return None
        try:
            db_path = get_db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            # WAL mode mirrors get_connection() for consistent concurrency
            # behavior with the rest of the codebase.
            conn.execute("PRAGMA journal_mode = WAL")
        except Exception as e:
            log.info("Could not open DB for metadata updates: %s", e)
            return None
        return ConversationStore(conn)

    def _write_manifest_metadata(
        self,
        conv_id: str,
        *,
        title: str | None,
        labels: dict[str, str] | None,
    ) -> None:
        """Rewrite ONLY title + labels on the manifest entry.

        Preserves ``updated_at``, ``event_count``, and ``downloaded_at``
        byte-for-byte — only the two metadata fields are touched.
        """
        entry = self.manifest.conversations.get(conv_id)
        if entry is None:  # pragma: no cover - guarded by caller
            return
        entry["title"] = title
        entry["labels"] = labels

    # ------------------------------------------------------------------ #
    # End metadata-only refresh
    # ------------------------------------------------------------------ #

    def _find_conversation_dir(self, conv_id: str) -> Path | None:
        """Find conversation directory on disk, handling UUID format variations."""
        synced_dir = self.config.synced_conversations_dir
        # Try without dashes first
        conv_dir = synced_dir / conv_id
        if conv_dir.exists():
            return conv_dir
        # Try with dashes (UUID format)
        if len(conv_id) == 32:
            formatted = f"{conv_id[:8]}-{conv_id[8:12]}-{conv_id[12:16]}-{conv_id[16:20]}-{conv_id[20:]}"
            conv_dir = synced_dir / formatted
            if conv_dir.exists():
                return conv_dir
        return None

    def _count_conversations_in_dir(self, directory: Path) -> int:
        """Count conversation directories in a path."""
        if not directory.exists():
            return 0
        return sum(1 for d in directory.iterdir() if d.is_dir())

    def reset_to_n_newest(
        self,
        n: int,
        dry_run: bool = False,
        on_progress: Callable[[str, str, str], None] | None = None,
        parallel: bool = True,
        shutdown_check: Callable[[], bool] | None = None,
    ) -> SyncResult:
        """Reset local storage to only the N most recently updated conversations.
        
        This is a destructive operation that:
        1. Deletes all existing local conversation data
        2. Clears the manifest
        3. Downloads only the N most recently updated conversations from cloud
        4. Sets last_sync_at to current time
        
        Args:
            n: Number of conversations to keep
            dry_run: Show what would happen without making changes
            on_progress: Callback for progress updates
            parallel: Use parallel downloads (default True, uses 20 workers)
            shutdown_check: Optional function that returns True to request graceful shutdown
        """
        if not self.config.api_key:
            raise ValueError("API key required. Set OPENHANDS_API_KEY or OH_API_KEY environment variable.")

        log.info("Resetting to %d newest conversations (dry_run=%s, parallel=%s)", n, dry_run, parallel)

        try:
            with CloudClient(self.config.cloud_api_url, self.config.api_key) as client:
                # Fetch all conversations from cloud.
                # Note: API returns conversations sorted by updated_at descending (newest first).
                # See REFERENCE_CLOUD_API.md for sort order documentation.
                conversations = client.search_all_conversations()
                log.info("Found %d total conversations in cloud", len(conversations))
                
                # Take only first N
                conversations_to_sync = conversations[:n]
                
                if dry_run:
                    result = SyncResult()
                    for conv in conversations_to_sync:
                        if on_progress:
                            on_progress(conv["id"], conv.get("title", "")[:50], "new")
                        result.new += 1
                    result.skipped_new = len(conversations) - n if len(conversations) > n else 0
                    return result

                # Clear existing data
                synced_dir = self.config.synced_conversations_dir
                if synced_dir.exists():
                    log.info("Clearing existing synced conversations directory")
                    shutil.rmtree(synced_dir)
                synced_dir.mkdir(parents=True, exist_ok=True)
                
                # Clear manifest
                self.manifest.conversations = {}
                self.manifest.failed_ids = []
                
                # Download using the same infrastructure as regular sync
                result = SyncResult()
                result.total_to_process = len(conversations_to_sync)
                work_items = [(conv, "new") for conv in conversations_to_sync]
                
                if parallel and len(work_items) > 1:
                    self._download_parallel(client, work_items, result, on_progress, shutdown_check, pass_total_on_first=True)
                else:
                    self._download_sequential(client, work_items, result, on_progress, shutdown_check, pass_total_on_first=True)
                
                # Track how many were available but not synced
                if len(conversations) > n:
                    result.skipped_new = len(conversations) - n
                
                # Update manifest - set last_sync_at to now since we're starting fresh
                self.manifest.sync_count += 1
                if not result.has_failures:
                    self.manifest.last_sync_at = datetime.now(timezone.utc)
                self.manifest.failed_ids = result.failed_ids
                self.manifest.save(self.manifest_path)
                
                return result
                
        except httpx.HTTPStatusError as e:
            log.error("HTTP error during reset: %s %s", e.response.status_code, e.response.reason_phrase)
            if e.response.status_code in (401, 403):
                raise SyncAuthError(f"Authentication failed (HTTP {e.response.status_code}). Check your API key.")
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.error("Network error during reset: %s", e)
            raise SyncAbortedError(f"Network error: {e}")


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string."""
    if not value:
        return None
    value = value.rstrip("Z")
    if "+" in value:
        value = value.split("+")[0]
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _format_datetime(dt: datetime | None) -> str | None:
    """Format datetime to ISO 8601."""
    if not dt:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_labels(value: object) -> dict[str, str] | None:
    """Normalize a labels/tags value to ``dict[str, str]`` or ``None``.

    Empty dict ``{}`` collapses to ``None`` to match the normalization in
    ``sources/cloud.py:parse_conversation_info`` and the manifest writer in
    ``SyncManager._update_manifest_entry``. Non-dict / falsy values also
    collapse to ``None``.
    """
    if isinstance(value, dict) and len(value) > 0:
        # Cast keys/values to str defensively — API returns strings, but
        # we don't want a stray int sneaking into the DB JSON column.
        return {str(k): str(v) for k, v in value.items()}
    return None


def _metadata_differs(
    cloud_conv: dict,
    manifest_entry: dict,
) -> tuple[bool, bool]:
    """Compare cloud listing entry vs manifest entry on title+labels.

    Both fields are normalized before comparison:
    - ``title``: missing/empty strings collapse to ``None``.
    - ``labels``: empty dict ``{}`` collapses to ``None`` (same rule as
      ``parse_conversation_info``); key order is irrelevant since we
      compare dicts directly.

    Args:
        cloud_conv: Conversation dict from the cloud listing
            (``client.search_all_conversations``). Labels live under
            ``"tags"`` in the API response.
        manifest_entry: Conversation entry from the local manifest.
            Labels live under ``"labels"`` (already normalized at write
            time by ``_update_manifest_entry``).

    Returns:
        ``(title_changed, labels_changed)`` booleans.
    """
    cloud_title = cloud_conv.get("title") or None
    manifest_title = manifest_entry.get("title") or None
    title_changed = cloud_title != manifest_title

    cloud_labels = _normalize_labels(cloud_conv.get("tags"))
    manifest_labels = _normalize_labels(manifest_entry.get("labels"))
    labels_changed = cloud_labels != manifest_labels

    return title_changed, labels_changed
