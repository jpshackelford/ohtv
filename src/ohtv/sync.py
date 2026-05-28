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
from ohtv.db.connection import get_db_path
from ohtv.db.maintenance import ensure_db_ready
from ohtv.db.stores import (
    CloudListingStore,
    ConversationStore,
    SyncStateStore,
)
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
    both_changed: int = 0  # legacy: convs where BOTH title AND labels differ
    selected_repository_changed: int = 0   # Issue #87
    created_at_changed: int = 0            # Issue #87
    convs_changed: int = 0                 # convs with >=1 field change (Issue #87)
    unchanged: int = 0
    new_on_cloud: int = 0       # In cloud listing but not in manifest (count only)
    missing_on_cloud: int = 0   # In manifest but not in cloud listing (count only)
    errors: list[tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def total_changed(self) -> int:
        """Number of manifest entries that received at least one change.

        Post-#87 this is exposed directly as ``convs_changed`` (set by the
        refresh loop). We retain the property for backward compat with
        existing callers; it returns ``convs_changed`` when populated, else
        falls back to the legacy two-field inclusion-exclusion formula.
        """
        if self.convs_changed:
            return self.convs_changed
        # Legacy formula (used by pre-#87 result objects in tests).
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
        # Thread-coordination for the parallel download path. SQLite
        # connections are not thread-safe; we buffer ``record_cloud_download``
        # writes from worker threads and flush them on the main thread
        # after the pool drains. ``None`` means "no buffering, write
        # directly" (sequential / non-pool path).
        self._db_writer_lock = threading.Lock()
        self._pending_cloud_updated_at: list[tuple[str, str, str | None]] | None = None

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
        """Sync conversations from cloud using the set-diff engine (Issue #111).

        The engine runs in two phases on every invocation:

        1. **Listing pass** — paginate the full cloud listing into the
           ``cloud_listing`` snapshot table under a fresh ``snapshot_id``.
           Pages commit incrementally so an interrupted sync can resume
           mid-listing without losing committed pages. On success the
           snapshot is atomically swapped; on any failure the in-flight
           snapshot is abandoned and the previous one stays usable.
        2. **Set-diff dispatch** — query ``cloud_listing`` against
           ``conversations`` to produce three categories:
           ``missing_locally`` (download), ``stale_locally`` (refetch),
           and ``removed_from_cloud`` (record only — #113 owns the
           prune UX).

        ``last_sync_at`` survives as a UX field only — it is *not* used
        as a sync gate. The cursor-based ``updated_since`` filter from
        the pre-#111 implementation is gone; full listing IS the gate.

        Args:
            force: Re-download every cloud conversation regardless of
                ``cloud_updated_at`` state. Treats every ``cloud_listing``
                row as ``missing_locally``.
            since: Filter applied to the WORK LIST (not the listing). The
                listing is always full per #111's architectural inversion.
                Useful when the user wants "the last week's deltas only".
            dry_run: Report what would sync without downloading.
            max_new: Maximum number of NEW conversations to sync (no
                limit on updates).
            on_progress: Callback for progress updates (conv_id, title,
                action[, total]).
            parallel: Use parallel downloads (default True).
            shutdown_check: Optional function returning True to request
                graceful shutdown between listing pages or downloads.
        """
        if not self.config.api_key:
            raise ValueError("API key required. Set OPENHANDS_API_KEY or OH_API_KEY environment variable.")

        log.info(
            "Starting set-diff sync (force=%s, since=%s, dry_run=%s, max_new=%s, parallel=%s)",
            force, since, dry_run, max_new, parallel,
        )

        # Schema-readiness gate. Runs migrations + maintenance tasks so
        # a fresh-install ``ohtv sync`` works without a prior ``db scan``.
        with get_connection_for_sync() as conn:
            ensure_db_ready(conn, show_progress=False)
            conn.commit()

        try:
            with CloudClient(self.config.cloud_api_url, self.config.api_key) as client:
                with get_connection_for_sync() as conn:
                    return self._run_set_diff_pass(
                        client,
                        conn,
                        force=force,
                        since=since,
                        dry_run=dry_run,
                        max_new=max_new,
                        on_progress=on_progress,
                        parallel=parallel,
                        shutdown_check=shutdown_check,
                    )
        except httpx.HTTPStatusError as e:
            log.error("HTTP error during sync: %s %s", e.response.status_code, e.response.reason_phrase)
            if e.response.status_code in (401, 403):
                raise SyncAuthError(f"Authentication failed (HTTP {e.response.status_code}). Check your API key.")
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            log.error("Network error during sync: %s", e)
            raise SyncAbortedError(f"Network error: {e}")

    def _run_set_diff_pass(
        self,
        client: CloudClient,
        conn,
        *,
        force: bool,
        since: datetime | None,
        dry_run: bool,
        max_new: int | None,
        on_progress: Callable[[str, str, str], None] | None,
        parallel: bool,
        shutdown_check: Callable[[], bool] | None,
    ) -> SyncResult:
        """The Issue #111 set-diff sync engine.

        See :meth:`sync` for the user-facing contract.
        """
        listing = CloudListingStore(conn)
        state = SyncStateStore(conn)

        # Phase 1: rebuild cloud_listing under a fresh snapshot.
        snapshot_id, total_listed = self._run_listing_pass(
            client, listing, conn, shutdown_check=shutdown_check
        )

        # Phase 2: persist snapshot bookkeeping in sync_kv. Read by
        # ``--status`` UX, ``--repair`` (#113), and a future freshness
        # gate. The engine itself does NOT branch on these values.
        state.set("last_snapshot_id", snapshot_id)
        state.set("last_snapshot_completed_at", _utc_now_iso())
        state.set("last_snapshot_count", total_listed)
        conn.commit()

        # Phase 3: compute the set-diff work list.
        work_items = self._categorize_via_set_diff(
            listing, conn, force=force, since=since, max_new=max_new
        )

        # Phase 4: include retry items from previous failed downloads.
        # The manifest stays the source of truth for "failed last time"
        # until #114 retires it.
        work_items = self._add_failed_conversations(work_items)
        log.info("Set-diff: %d items to process (listing=%d)", len(work_items), total_listed)

        # Phase 5: process the work list (existing pipeline).
        return self._process_work_items(
            client,
            conn,
            work_items,
            dry_run=dry_run,
            max_new=max_new,
            on_progress=on_progress,
            parallel=parallel,
            shutdown_check=shutdown_check,
        )

    def _run_listing_pass(
        self,
        client: CloudClient,
        listing: CloudListingStore,
        conn,
        *,
        shutdown_check: Callable[[], bool] | None,
    ) -> tuple[str, int]:
        """Paginate the full cloud listing into ``cloud_listing``.

        Per #111: NO ``updated_since`` filter. The listing is unconditional;
        set-diff IS the gate. Returns ``(snapshot_id, total_rows)``.

        On any exception during listing the in-flight snapshot is
        abandoned (leaving the previous snapshot intact) and the
        exception re-raises.
        """
        snapshot_id = listing.start_snapshot()
        total = 0
        page_id: str | None = None

        try:
            while True:
                if shutdown_check and shutdown_check():
                    raise SyncAbortedError("Listing interrupted by shutdown request")

                items, next_page_id = client.search_conversations(
                    # NO updated_since: the architectural inversion of #111.
                    limit=100,
                    page_id=page_id,
                )

                for row in items:
                    listing.upsert_row(snapshot_id, row)
                conn.commit()  # per-page incremental commit
                total += len(items)

                if not next_page_id:
                    break
                page_id = next_page_id

            # Atomic swap: prune rows from prior snapshots.
            listing.commit_snapshot(snapshot_id)
            conn.commit()
        except Exception:
            # Failure path: abandon only the in-flight snapshot rows so
            # any previously-committed snapshot stays intact.
            try:
                listing.abandon_snapshot(snapshot_id)
                conn.commit()
            except Exception as cleanup_exc:  # pragma: no cover
                log.warning("Failed to abandon snapshot %s: %s", snapshot_id, cleanup_exc)
            raise

        return snapshot_id, total

    def _categorize_via_set_diff(
        self,
        listing: CloudListingStore,
        conn,
        *,
        force: bool,
        since: datetime | None,
        max_new: int | None,
    ) -> list[tuple[dict, str]]:
        """Build the work list from cloud_listing vs manifest diff.

        Returns ``[(conv_dict, action), ...]`` where ``action`` is one
        of ``"new"`` (missing locally), ``"updated"`` (stale locally),
        or — implicitly — items not yielded at all (present and fresh).
        ``force`` collapses every listing row to ``"new"`` (with
        cleanup-and-redownload semantics handled by the download path).

        ``since`` filters the work list (not the listing) — items with
        ``updated_at`` older than ``since`` drop out, matching the
        ``--since`` UX after #111.

        **Source-of-truth**: the manifest (per AGENTS.md item #27 —
        "manifest stays authoritative until #114"). The conversations
        table is consulted as a *consistency check* on
        ``cloud_updated_at`` (set-diff helpers on
        :class:`CloudListingStore`), but the manifest is what the
        engine compares against and what the engine mutates.
        """
        # Pre-strip every manifest key into its dashless form for O(1)
        # set-diff comparisons. Manifest may carry either shape per
        # AGENTS.md item #14.
        manifest_norm: dict[str, str] = {
            mid.replace("-", ""): mid for mid in self.manifest.conversations
        }

        work: list[tuple[dict, str]] = []
        seen_in_cloud: set[str] = set()  # for the removed-from-cloud reconciliation below

        # Streaming SELECT — sqlite3 returns a cursor we iterate row-by-row,
        # so peak memory tracks one row at a time, not the full result set.
        # The local accumulators (``work``, ``seen_in_cloud``, ``manifest_norm``)
        # do scale with the catalog size: at ~200 bytes/row they comfortably
        # absorb the low-thousands catalogs we see today and are still well
        # under 10 MB at 10k conversations. Chunked queries are deferred to a
        # follow-up if anyone actually hits a scale wall — added in response
        # to bot-review feedback on PR #133.
        for row in conn.execute("SELECT * FROM cloud_listing"):
            cid = row["conversation_id"]
            seen_in_cloud.add(cid)
            conv = _listing_row_to_conv_dict(row)

            if force:
                # Force mode bypasses the diff: every cloud row is
                # treated as missing and downloaded.
                if _passes_since_filter(conv, since):
                    work.append((conv, "new"))
                continue

            manifest_key = manifest_norm.get(cid)
            if manifest_key is None:
                # Missing locally — download as "new".
                if _passes_since_filter(conv, since):
                    work.append((conv, "new"))
                continue

            # Present locally: compare cloud_updated_at to detect drift.
            cloud_ts = conv.get("updated_at") or ""
            manifest_entry = self.manifest.conversations.get(manifest_key) or {}
            manifest_ts = manifest_entry.get("updated_at") or ""

            if not manifest_ts or cloud_ts != manifest_ts:
                # Stale (or never recorded). Use != not > so a
                # server-side rewind also reconciles. Scenario #3.
                if _passes_since_filter(conv, since):
                    work.append((conv, "updated"))
                continue

            # Present-both-synced: no work. Issue #112's set-diff helper
            # on CloudListingStore exposes the same partition to #113
            # without us recomputing it.

        # Removed-from-cloud reconciliation: drop manifest entries
        # that disappeared from the listing. #113 will add the
        # user-facing report; #111 just keeps the manifest coherent so
        # the property tests pass (scenario #15). Emit a WARNING so
        # accidental cloud-side data loss or permission changes
        # surface in the log rather than silently shrinking the
        # manifest — bot-review feedback on this PR.
        removed_count = 0
        for normalized, manifest_key in list(manifest_norm.items()):
            if normalized in seen_in_cloud:
                continue
            del self.manifest.conversations[manifest_key]
            removed_count += 1
        if removed_count:
            log.warning(
                "Removed %d conversation(s) from manifest "
                "(no longer visible in cloud listing).",
                removed_count,
            )

        return work

    def _add_failed_conversations(
        self, work_items: list[tuple[dict, str]]
    ) -> list[tuple[dict, str]]:
        """Append retry entries for previously-failed downloads.

        Returns ``[(conv_dict, action), ...]`` with ``failed_ids`` from
        the manifest folded in as ``"new"`` items (the existing retry
        contract). Items already present in the work list are deduped.
        """
        if not self.manifest.failed_ids:
            return work_items

        existing_ids = {c["id"].replace("-", "") for c, _ in work_items}
        retry_count = 0

        for failed_id in self.manifest.failed_ids:
            normalized = failed_id.replace("-", "")
            if normalized in existing_ids:
                continue
            work_items.append((
                {
                    "id": failed_id,
                    "title": "(retry)",
                    "updated_at": "",
                },
                "new",
            ))
            retry_count += 1

        if retry_count > 0:
            log.info("Adding %d previously failed conversations for retry", retry_count)

        return work_items

    def _process_work_items(
        self,
        client: CloudClient,
        conn,
        work_items: list[tuple[dict, str]],
        *,
        dry_run: bool,
        max_new: int | None,
        on_progress: Callable[[str, str, str], None] | None,
        parallel: bool = True,
        shutdown_check: Callable[[], bool] | None = None,
    ) -> SyncResult:
        """Process the pre-categorized work list from :meth:`_categorize_via_set_diff`.

        ``work_items`` arrives as ``[(conv_dict, action), ...]`` where
        ``action`` is one of ``"new"``, ``"updated"``, or ``"unchanged"``.
        This method:

        * Applies ``max_new`` (a count-based skip on ``"new"`` items).
        * Routes ``"unchanged"`` / ``"skipped"`` / ``dry_run`` items
          straight to the result tally.
        * Forwards the remainder to the existing
          :meth:`_download_parallel` / :meth:`_download_sequential` paths
          (carrying the open DB connection so successful downloads can
          write ``conversations.cloud_updated_at``).
        """
        result = SyncResult()

        # Phase 1: Apply max_new (count-based skip).
        capped_items: list[tuple[dict, str]] = []
        new_count = 0
        for conv, action in work_items:
            if action == "new":
                if max_new is not None and new_count >= max_new:
                    capped_items.append((conv, "skipped"))
                    result.skipped_new += 1
                    continue
                new_count += 1
            capped_items.append((conv, action))

        # Total for progress display (excludes "skipped" items).
        result.total_to_process = sum(1 for _, a in capped_items if a != "skipped")

        # Phase 2: Route unchanged / skipped / dry-run straight to tally.
        first_progress_call = True
        to_download: list[tuple[dict, str]] = []
        for conv, action in capped_items:
            if action in ("unchanged", "skipped") or dry_run:
                self._update_result(result, action)
                if on_progress:
                    if first_progress_call:
                        on_progress(
                            conv["id"], conv.get("title", "")[:50],
                            action, result.total_to_process,
                        )
                        first_progress_call = False
                    else:
                        on_progress(conv["id"], conv.get("title", "")[:50], action)
            else:
                to_download.append((conv, action))

        # Phase 3: Download.
        if to_download:
            pass_total = first_progress_call
            if parallel and len(to_download) > 1:
                self._download_parallel(
                    client, to_download, result, on_progress,
                    shutdown_check, pass_total, conn=conn,
                )
            else:
                self._download_sequential(
                    client, to_download, result, on_progress,
                    shutdown_check, pass_total, conn=conn,
                )

        if not dry_run:
            self._finalize_sync(result, conn=conn)
        return result

    def _categorize_conversations(
        self,
        conversations: list[dict],
        force: bool,
        max_new: int | None,
        result: SyncResult,
    ) -> list[tuple[dict, str]]:
        """Legacy cursor-based categorizer.

        Retained for backward compatibility with existing unit tests in
        ``tests/unit/test_sync.py`` (``TestSyncManagerMaxNew``). The
        production sync path goes through
        :meth:`_categorize_via_set_diff` (Issue #111). New code should
        not call this method.
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
        conn=None,
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
                client, conv, conv_id, cloud_updated_at, planned_action, result, conn=conn,
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
        conn=None,
    ) -> None:
        """Download conversations in parallel using a thread pool.
        
        Rate limiting is handled by a shared rate limiter in the CloudClient,
        so when one worker hits a 429, all workers will pause before making
        new requests.
        """
        max_workers = min(DEFAULT_MAX_WORKERS, len(work_items))
        log.info("Starting parallel download with %d workers for %d conversations", 
                 max_workers, len(work_items))

        # Enable the cloud_updated_at write buffer for the duration of
        # this parallel pass. SQLite connections are not thread-safe;
        # workers append, the main thread flushes below.
        with self._db_writer_lock:
            self._pending_cloud_updated_at = []

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
                client, conv, conv_id, cloud_updated_at, planned_action, result, conn=conn,
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

        # Flush the cloud_updated_at writes accumulated by worker
        # threads onto the main-thread DB connection, then disable
        # buffering so subsequent (sequential) calls write directly.
        if conn is not None:
            self._flush_cloud_updated_at_writes(conn)
        with self._db_writer_lock:
            self._pending_cloud_updated_at = None

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
        conn=None,
    ) -> str:
        """Download conversation, update manifest, write conversations.cloud_updated_at.

        ``conn`` (optional) is the sync-wide DB connection. When passed,
        the method writes ``conversations.cloud_updated_at`` via
        :meth:`ConversationStore.record_cloud_download` so the next
        sync's set-diff sees this conversation as in-sync. A DB-side
        failure does NOT count as a download failure — manifest +
        on-disk export are the user-facing success criteria.
        """
        try:
            log.debug("Downloading %s", conv_id)
            zip_bytes = client.download_trajectory(conv_id)
            conv_dir = self.exporter.export_from_zip_bytes(conv_id, zip_bytes)
            self._update_manifest_entry(conv, conv_id, cloud_updated_at, conv_dir)
            if conn is not None:
                self._record_cloud_download_in_db(
                    conn, conv_id, conv_dir, cloud_updated_at
                )
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

    def _record_cloud_download_in_db(
        self,
        conn,
        conv_id: str,
        conv_dir: Path,
        cloud_updated_at: str,
    ) -> None:
        """Persist ``conversations.cloud_updated_at`` after a successful download.

        Best-effort: a DB-side failure is logged but does not bubble up
        through the download path. SQLite connections are not
        thread-safe — parallel workers handing the connection from the
        main thread will trigger ``ProgrammingError: SQLite objects
        created in a thread can only be used in that same thread.``
        We serialize all writes through a lock and pin them to a
        single thread by buffering instead: workers append to
        :attr:`_pending_cloud_updated_at` (guarded by
        :attr:`_db_writer_lock`) and the main thread flushes after the
        thread pool drains. See :meth:`_flush_cloud_updated_at_writes`.
        """
        # If we have a writer queue, defer (parallel case). Otherwise
        # write directly (sequential case).
        with self._db_writer_lock:
            if self._pending_cloud_updated_at is not None:
                self._pending_cloud_updated_at.append(
                    (conv_id, str(conv_dir), cloud_updated_at or None)
                )
                return
        try:
            store = ConversationStore(conn)
            store.record_cloud_download(
                conv_id,
                location=str(conv_dir),
                cloud_updated_at=cloud_updated_at or None,
            )
            conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "Failed to record cloud_updated_at for %s in DB: %s",
                conv_id, exc,
            )

    def _flush_cloud_updated_at_writes(self, conn) -> None:
        """Drain the queued ``record_cloud_download`` writes onto ``conn``.

        Called from the main thread after the parallel download pool
        drains. Safe to call with an empty queue (no-op).
        """
        with self._db_writer_lock:
            queued = list(self._pending_cloud_updated_at or [])
            if self._pending_cloud_updated_at is not None:
                self._pending_cloud_updated_at.clear()
        if not queued:
            return
        try:
            store = ConversationStore(conn)
            for conv_id, location, cloud_updated_at in queued:
                store.record_cloud_download(
                    conv_id,
                    location=location,
                    cloud_updated_at=cloud_updated_at,
                )
            conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "Failed to flush %d queued cloud_updated_at writes: %s",
                len(queued), exc,
            )

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
        """Update the manifest with new conversation info.

        Issue #87 extension: persist ``selected_repository``,
        ``selected_branch``, and ``created_at`` so the manifest becomes
        the complete cache of cloud-derived metadata. ``selected_branch``
        is read from the freshly-extracted ``base_state.json`` (mirrored
        from the trajectory ZIP's ``meta.json`` by the exporter) — it is
        NOT in the cloud listing payload.
        """
        # Extract labels/tags from API response (may be empty dict or None)
        tags = conv.get("tags")
        labels = tags if tags and isinstance(tags, dict) and len(tags) > 0 else None

        self.manifest.conversations[conv_id] = {
            "title": conv.get("title"),
            "updated_at": cloud_updated_at,
            "event_count": count_events(conv_dir),
            "downloaded_at": _format_datetime(datetime.now(timezone.utc)),
            "labels": labels,
            # Issue #87: full cloud metadata cache.
            "selected_repository": conv.get("selected_repository"),
            "selected_branch": _read_selected_branch(conv_dir),
            "created_at": conv.get("created_at"),
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

    def _finalize_sync(self, result: SyncResult, conn=None) -> None:
        """Update and save manifest after sync.

        Post-#111: ``last_sync_at`` is a pure UX field. The engine never
        consumes it as a gate. We dual-write it to ``sync_kv`` so #114
        can drain the manifest without a flag-day.
        """
        self.manifest.failed_ids = result.failed_ids
        self.manifest.sync_count += 1

        # Advance last_sync_at unless there are unresolved gaps (failures
        # / skipped-by-max_new). The UX value is "what was the wall-clock
        # time of the last clean reconciliation" — not consulted by the
        # set-diff engine.
        advanced = False
        if result.has_failures:
            log.warning(
                "Sync complete with %d failures. Not advancing last_sync_at. "
                "Run 'ohtv sync' again to retry failed conversations.",
                result.failed,
            )
        elif result.has_skipped_new:
            log.info(
                "Sync complete. Synced %d new, %d additional available. "
                "Not advancing last_sync_at so skipped conversations stay visible.",
                result.new, result.skipped_new,
            )
        else:
            self.manifest.last_sync_at = datetime.now(timezone.utc)
            advanced = True
            log.info("Sync complete. Total conversations: %d", len(self.manifest.conversations))

        self.manifest.save(self.manifest_path)

        # Dual-write to sync_kv (Issue #114 transition state). Engine
        # never reads from this key.
        if advanced and conn is not None:
            try:
                SyncStateStore(conn).set(
                    "last_sync_at", _format_datetime(self.manifest.last_sync_at)
                )
                conn.commit()
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Failed to mirror last_sync_at into sync_kv: %s", exc)

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

            # Issue #87: rebuild orphan manifest entries from the listing
            # API payload when possible (one fetch shared across all
            # orphans). Falls back to null-filled entries when we don't
            # have an API key or the listing query fails.
            cloud_by_id: dict[str, dict] = {}
            if result.orphaned_files and check_cloud and self.config.api_key:
                cloud_by_id = self._fetch_cloud_listing_for_repair()

            for orphan_id in result.orphaned_files:
                conv_dir = self._find_conversation_dir(orphan_id)
                if conv_dir:
                    self.manifest.conversations[orphan_id] = (
                        self._build_repaired_manifest_entry(
                            orphan_id, conv_dir, cloud_by_id
                        )
                    )
                    result.added_to_manifest += 1

            if result.removed_from_manifest > 0 or result.added_to_manifest > 0:
                self.manifest.save(self.manifest_path)
                log.info(
                    "Repair applied: removed %d ghost entries, added %d orphaned files",
                    result.removed_from_manifest, result.added_to_manifest
                )

        return result

    def _fetch_cloud_listing_for_repair(self) -> dict[str, dict]:
        """Pull the full cloud listing keyed by id, for ``repair`` to
        rebuild orphaned manifest entries from. Returns an empty dict on
        any error so ``repair`` can fall back to a null-filled entry.
        """
        try:
            with CloudClient(self.config.cloud_api_url, self.config.api_key) as client:
                items = client.search_all_conversations(updated_since=None)
                return {item["id"]: item for item in items if "id" in item}
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
            log.warning("Repair: could not fetch cloud listing for orphan rebuild: %s", e)
            return {}

    def _build_repaired_manifest_entry(
        self,
        conv_id: str,
        conv_dir: Path,
        cloud_by_id: dict[str, dict],
    ) -> dict:
        """Construct a manifest entry for an orphaned on-disk conversation.

        Uses the cloud listing payload (when available) so we don't write
        nulls for fields that the API knows about. Reads
        ``selected_branch`` from the existing ``base_state.json`` since it
        is not in the listing.

        Note: this is the ONE place ``repair`` reads ``base_state.json`` —
        it's necessary because ``selected_branch`` lives only in
        ``meta.json`` (now mirrored into ``base_state.json`` by the
        exporter) and is not in the listing API.
        """
        cloud_conv = cloud_by_id.get(conv_id) or {}
        tags = cloud_conv.get("tags")
        labels = tags if tags and isinstance(tags, dict) and len(tags) > 0 else None
        return {
            "title": cloud_conv.get("title"),
            "updated_at": cloud_conv.get("updated_at"),
            "event_count": count_events(conv_dir),
            "downloaded_at": _format_datetime(datetime.now(timezone.utc)),
            "labels": labels,
            # Issue #87: full cloud metadata cache.
            "selected_repository": cloud_conv.get("selected_repository"),
            "selected_branch": _read_selected_branch(conv_dir),
            "created_at": cloud_conv.get("created_at"),
        }

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

        try:
            for i, conv_id in enumerate(in_both):
                cloud_conv = cloud_by_id[conv_id]
                manifest_entry = self.manifest.conversations[conv_id]
                diff = _metadata_differs(cloud_conv, manifest_entry)

                result.checked += 1
                if not diff.any_changed:
                    result.unchanged += 1
                else:
                    if diff.title_changed:
                        result.title_changed += 1
                    if diff.labels_changed:
                        result.labels_changed += 1
                    if diff.title_changed and diff.labels_changed:
                        result.both_changed += 1
                    if diff.selected_repository_changed:
                        result.selected_repository_changed += 1
                    if diff.created_at_changed:
                        result.created_at_changed += 1
                    result.convs_changed += 1

                    if not dry_run:
                        if self._update_metadata_with_error_handling(
                            conv_id, diff, manifest_entry, store, result,
                        ):
                            any_change_applied = True

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
        finally:
            # Always close the DB connection we opened in _get_conversation_store.
            # We own the connection lifecycle here (the factory returns a raw
            # sqlite3.Connection — not a context manager). The try/finally
            # guards against manifest.save() raising (disk full, permission
            # denied, etc.), which would otherwise leak the connection.
            if store is not None and store.conn is not None:
                try:
                    store.conn.close()
                except Exception as e:  # pragma: no cover - best effort
                    log.warning("Failed to close DB metadata connection: %s", e)

        result.elapsed_seconds = _time.perf_counter() - start
        log.info(
            "Metadata refresh complete: checked=%d title_changed=%d labels_changed=%d "
            "both_changed=%d repo_changed=%d created_at_changed=%d "
            "convs_changed=%d unchanged=%d new_on_cloud=%d missing_on_cloud=%d "
            "errors=%d",
            result.checked, result.title_changed, result.labels_changed,
            result.both_changed, result.selected_repository_changed,
            result.created_at_changed, result.convs_changed, result.unchanged,
            result.new_on_cloud, result.missing_on_cloud, len(result.errors),
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

    def _update_metadata_with_error_handling(
        self,
        conv_id: str,
        diff: "MetadataDiff",
        manifest_entry: dict,
        store,
        result: "MetadataRefreshResult",
    ) -> bool:
        """Apply changed metadata fields to manifest and (if open) DB.

        Flattens what would otherwise be a deeply nested try/except in the
        main refresh loop. Manifest write is attempted first; if it fails,
        the DB write is skipped to preserve "manifest is source of truth"
        ordering. DB failures are recorded but never roll back the manifest
        change.

        Issue #87: ``selected_repository`` and ``created_at`` are written
        only when ``diff`` reports them changed (sentinel-vs-clear via
        ``ConversationStore.update_metadata``'s ``_UNSET`` semantics).
        ``selected_branch`` is never refreshed here — it's not in the
        listing API.

        Returns:
            True if the manifest write succeeded (caller should treat the
            row as updated, e.g. set ``any_change_applied``). False if the
            manifest write failed.
        """
        # Build "new" values for fields that changed; preserve existing
        # manifest values for fields that didn't (so the manifest entry
        # converges on the canonical cloud snapshot without churn).
        new_title = diff.new_title if diff.title_changed else manifest_entry.get("title")
        if diff.labels_changed:
            new_labels = diff.new_labels
        else:
            new_labels = _normalize_labels(manifest_entry.get("labels"))
        new_repo = (
            diff.new_selected_repository
            if diff.selected_repository_changed
            else manifest_entry.get("selected_repository")
        )
        new_created_at = (
            diff.new_created_at
            if diff.created_at_changed
            else manifest_entry.get("created_at")
        )

        try:
            self._write_manifest_metadata(
                conv_id,
                title=new_title,
                labels=new_labels,
                selected_repository=new_repo,
                created_at=new_created_at,
            )
        except Exception as e:
            log.warning("Failed to update manifest metadata for %s: %s", conv_id, e)
            result.errors.append((conv_id, str(e)))
            return False

        if store is not None:
            # Only push fields that actually changed to the DB so we don't
            # rewrite unchanged columns (sentinel-driven WHERE-IS semantics
            # in ConversationStore.update_metadata).
            db_kwargs: dict = {}
            if diff.title_changed:
                db_kwargs["title"] = new_title
            if diff.labels_changed:
                db_kwargs["labels"] = new_labels
            if diff.selected_repository_changed:
                db_kwargs["selected_repository"] = new_repo
            if diff.created_at_changed:
                # Parse the ISO 8601 string into a datetime for the DB write.
                # _parse_datetime returns None on malformed input — fall
                # through with None which the store will write as NULL.
                db_kwargs["created_at"] = _parse_datetime(new_created_at)
            if db_kwargs:
                try:
                    store.update_metadata(conv_id, **db_kwargs)
                except Exception as e:
                    log.warning("Failed to update DB metadata for %s: %s", conv_id, e)
                    result.errors.append((conv_id, f"db: {e}"))
        return True

    def _write_manifest_metadata(
        self,
        conv_id: str,
        *,
        title: str | None,
        labels: dict[str, str] | None,
        selected_repository: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Rewrite refreshable metadata fields on the manifest entry.

        Issue #86 wrote only ``title``/``labels``. Issue #87 extends to
        ``selected_repository`` and ``created_at`` so the manifest entry
        converges on the canonical cloud snapshot.

        Preserves ``updated_at``, ``event_count``, ``downloaded_at``, and
        ``selected_branch`` (which can only be refreshed via a full
        trajectory download) byte-for-byte.
        """
        entry = self.manifest.conversations.get(conv_id)
        if entry is None:  # pragma: no cover - guarded by caller
            return
        entry["title"] = title
        entry["labels"] = labels
        entry["selected_repository"] = selected_repository
        entry["created_at"] = created_at

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
                # The /search endpoint returns items in created_at DESC order and exposes
                # no `sort` parameter (see REFERENCE_CLOUD_API.md). To honor this method's
                # documented "N most recently updated" semantic, sort client-side by
                # updated_at DESC before truncating. Items with a missing/None updated_at
                # are coerced to "" so they sort to the end under reverse=True — a
                # conversation with unknown updated_at must not displace a known-recent
                # one from the keep set (issue #107).
                conversations = client.search_all_conversations()
                log.info("Found %d total conversations in cloud", len(conversations))
                conversations.sort(
                    key=lambda c: c.get("updated_at") or "",
                    reverse=True,
                )

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


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp for ``sync_kv`` bookkeeping."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redash(undashed: str) -> str:
    """Reinsert canonical UUID dashes into a 32-char hex string.

    Returns the input verbatim if it does not look like a 32-char hex.
    """
    if len(undashed) != 32 or not all(c in "0123456789abcdef" for c in undashed.lower()):
        return undashed
    return f"{undashed[0:8]}-{undashed[8:12]}-{undashed[12:16]}-{undashed[16:20]}-{undashed[20:32]}"


def _listing_row_to_conv_dict(row) -> dict:
    """Adapt a ``cloud_listing`` table row into the dict shape used by
    the download pipeline (``conv["id"]``, ``conv["title"]``, etc.).
    """
    return {
        "id": row["conversation_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "selected_repository": row["selected_repository"],
        "selected_branch": row["selected_branch"],
        "tags": _maybe_json_loads(row["tags"]),
    }


def _maybe_json_loads(value):
    """Best-effort JSON decode for stringified columns.

    The cloud listing API returns ``tags`` as a dict / None; we store
    it verbatim in :meth:`CloudListingStore.upsert_row`. SQLite
    coerces dicts/lists to TEXT silently, so this round-trip may
    receive either a real dict (in-memory store), a JSON string (after
    an INSERT round-trip), or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def _passes_since_filter(conv: dict, since: datetime | None) -> bool:
    """Return True if ``conv`` should be retained given a ``--since`` filter.

    ``since`` is interpreted as a UTC datetime; ``None`` disables the
    filter. Items whose ``updated_at`` is missing OR newer-or-equal to
    ``since`` are retained (we don't drop unknown timestamps lest a
    stale cloud row hide a fresh local sync).

    ``click.DateTime()`` hands us offset-naive datetimes; normalize them
    to UTC-aware here so the ``parsed >= since`` comparison doesn't
    raise ``TypeError`` against the tz-aware values returned by
    :func:`_parse_datetime` (T6 regression, PR #133).
    """
    if since is None:
        return True
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    updated_at = conv.get("updated_at")
    if not updated_at:
        return True
    parsed = _parse_datetime(updated_at)
    if parsed is None:
        return True
    return parsed >= since


def get_connection_for_sync():
    """Open a fresh sqlite3 connection at the configured DB path.

    Mirrors :func:`ohtv.db.connection.get_connection` but isolated so
    tests can monkeypatch ``ohtv.sync.get_db_path`` without affecting
    other call sites. The returned context manager configures the same
    pragmas as the canonical connection helper.
    """
    import sqlite3
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    return _ctx()


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


@dataclass
class MetadataDiff:
    """Per-conversation diff between cloud listing and manifest entry.

    Carries which fields changed AND the canonical new values so the
    update path doesn't have to re-normalize. Issue #87 extends
    Issue #86's two-bool tuple into a struct that also tracks
    ``selected_repository`` and ``created_at`` deltas.
    """

    title_changed: bool = False
    labels_changed: bool = False
    selected_repository_changed: bool = False
    created_at_changed: bool = False

    new_title: str | None = None
    new_labels: dict[str, str] | None = None
    new_selected_repository: str | None = None
    new_created_at: str | None = None  # ISO 8601 string from listing

    @property
    def any_changed(self) -> bool:
        return (
            self.title_changed
            or self.labels_changed
            or self.selected_repository_changed
            or self.created_at_changed
        )


def _metadata_differs(
    cloud_conv: dict,
    manifest_entry: dict,
) -> MetadataDiff:
    """Compare cloud listing entry vs manifest entry on refreshable fields.

    All fields are normalized before comparison:
    - ``title``: missing/empty strings collapse to ``None``.
    - ``labels``: empty dict ``{}`` collapses to ``None`` (same rule as
      ``parse_conversation_info``); key order is irrelevant since we
      compare dicts directly.
    - ``selected_repository``: missing/empty strings collapse to ``None``.
    - ``created_at``: compared as ISO 8601 strings (the listing API
      returns them as strings; the manifest stores them as strings).

    Args:
        cloud_conv: Conversation dict from the cloud listing
            (``client.search_all_conversations``). Labels live under
            ``"tags"`` in the API response.
        manifest_entry: Conversation entry from the local manifest.
            Labels live under ``"labels"`` (already normalized at write
            time by ``_update_manifest_entry``).

    Returns:
        ``MetadataDiff`` with per-field booleans and the new values.

    Note:
        ``selected_branch`` is NOT compared — the cloud listing API
        does not return that field (only ``meta.json`` inside the
        trajectory ZIP carries it), so it cannot be refreshed without
        a full download. Documented in Issue #87.
    """
    cloud_title = cloud_conv.get("title") or None
    manifest_title = manifest_entry.get("title") or None
    title_changed = cloud_title != manifest_title

    cloud_labels = _normalize_labels(cloud_conv.get("tags"))
    manifest_labels = _normalize_labels(manifest_entry.get("labels"))
    labels_changed = cloud_labels != manifest_labels

    cloud_repo = cloud_conv.get("selected_repository") or None
    # Pre-#87 manifests don't have the key. Treat missing as None — a
    # cloud value of None matches that and is a no-op; a cloud value of
    # a real string DOES count as a change (caller will write it,
    # populating the field on first refresh).
    manifest_repo = manifest_entry.get("selected_repository") or None
    selected_repository_changed = cloud_repo != manifest_repo

    cloud_created_at = cloud_conv.get("created_at") or None
    manifest_created_at = manifest_entry.get("created_at") or None
    created_at_changed = cloud_created_at != manifest_created_at

    return MetadataDiff(
        title_changed=title_changed,
        labels_changed=labels_changed,
        selected_repository_changed=selected_repository_changed,
        created_at_changed=created_at_changed,
        new_title=cloud_title,
        new_labels=cloud_labels,
        new_selected_repository=cloud_repo,
        new_created_at=cloud_created_at,
    )


def _read_selected_branch(conv_dir: Path) -> str | None:
    """Read ``selected_branch`` from a freshly-exported ``base_state.json``.

    The exporter writes ``base_state.json`` from the trajectory ZIP's
    ``meta.json``; ``selected_branch`` lives there but NOT in the cloud
    listing API. Returns ``None`` on any read/parse failure — manifest
    just won't carry the field for that conv, and the scanner will fall
    back to ``base_state.json`` as before.
    """
    base_state = conv_dir / "base_state.json"
    if not base_state.exists():
        return None
    try:
        data = json.loads(base_state.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    value = data.get("selected_branch")
    return value if isinstance(value, str) and value else None
