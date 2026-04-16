"""Sync cloud conversations to local storage."""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from ohtv.config import Config, get_manifest_path
from ohtv.exporter import TrajectoryExporter, count_events
from ohtv.sources.cloud import CloudClient, RateLimitExceededError

log = logging.getLogger("ohtv")


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

    @property
    def total_synced(self) -> int:
        return self.new + self.updated

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

    @property
    def has_skipped_new(self) -> bool:
        return self.skipped_new > 0


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
    ) -> SyncResult:
        """Sync conversations from cloud.
        
        Args:
            force: Re-download all conversations (clears local before re-download)
            since: Only sync conversations updated after this date
            dry_run: Show what would sync without downloading
            max_new: Maximum number of NEW conversations to sync (no limit on updates)
            on_progress: Callback for progress updates (conv_id, title, action)
        """
        if not self.config.api_key:
            raise ValueError("API key required. Set OH_API_KEY environment variable.")

        cutoff = self._determine_cutoff(force, since)
        log.info("Starting sync (force=%s, cutoff=%s, dry_run=%s, max_new=%s)", force, cutoff, dry_run, max_new)

        try:
            with CloudClient(self.config.cloud_api_url, self.config.api_key) as client:
                conversations = client.search_all_conversations(updated_since=cutoff)
                conversations = self._add_failed_conversations(conversations)
                log.info("Found %d conversations to process", len(conversations))
                return self._process_conversations(client, conversations, force, dry_run, max_new, on_progress)
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
    ) -> SyncResult:
        """Process each conversation that needs syncing."""
        result = SyncResult()
        consecutive_failures = 0
        max_consecutive_failures = 5

        for conv in conversations:
            action = self._sync_one(client, conv, force, dry_run, max_new, on_progress, result)
            self._update_result(result, action)
            consecutive_failures = self._check_abort(action, consecutive_failures, max_consecutive_failures)

        if not dry_run:
            self._finalize_sync(result)
        return result

    def _check_abort(self, action: str, consecutive_failures: int, max_failures: int) -> int:
        """Check if we should abort due to too many consecutive failures."""
        if action == "failed":
            consecutive_failures += 1
            if consecutive_failures >= max_failures:
                log.error("Aborting after %d consecutive failures", max_failures)
                raise SyncAbortedError(f"Aborting after {max_failures} consecutive failures")
            return consecutive_failures
        return 0  # Reset on success

    def _sync_one(
        self,
        client: CloudClient,
        conv: dict,
        force: bool,
        dry_run: bool,
        max_new: int | None,
        on_progress: Callable[[str, str, str], None] | None,
        result: SyncResult,
    ) -> str:
        """Sync a single conversation. Returns action taken: 'new', 'updated', 'unchanged', 'failed', 'skipped'."""
        conv_id = conv["id"]
        cloud_updated_at = conv.get("updated_at", "")
        title = conv.get("title", "")[:50]

        planned_action = self._determine_action(conv_id, cloud_updated_at, force)

        # Check if we should skip this new conversation due to max_new limit
        if planned_action == "new" and max_new is not None and result.new >= max_new:
            if on_progress:
                on_progress(conv_id, title, "skipped")
            return "skipped"

        if planned_action == "unchanged" or dry_run:
            if on_progress:
                on_progress(conv_id, title, planned_action)
            return planned_action

        # For force mode, clean up existing directory before re-download
        if force and planned_action == "updated":
            self._cleanup_conversation_dir(conv_id)

        actual_action = self._download_and_update(
            client, conv, conv_id, cloud_updated_at, planned_action, result
        )
        if on_progress:
            on_progress(conv_id, title, actual_action)
        return actual_action

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
        self.manifest.conversations[conv_id] = {
            "title": conv.get("title"),
            "updated_at": cloud_updated_at,
            "event_count": count_events(conv_dir),
            "downloaded_at": _format_datetime(datetime.now(timezone.utc)),
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

    def reset_to_n_newest(
        self,
        n: int,
        dry_run: bool = False,
        on_progress: Callable[[str, str, str], None] | None = None,
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
        """
        if not self.config.api_key:
            raise ValueError("API key required. Set OH_API_KEY environment variable.")

        log.info("Resetting to %d newest conversations (dry_run=%s)", n, dry_run)

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
                
                # Download the N newest conversations
                result = SyncResult()
                consecutive_failures = 0
                max_consecutive_failures = 5
                
                for conv in conversations_to_sync:
                    action = self._download_and_update(
                        client, conv, conv["id"], conv.get("updated_at", ""), "new", result
                    )
                    self._update_result(result, action)
                    if on_progress:
                        on_progress(conv["id"], conv.get("title", "")[:50], action)
                    consecutive_failures = self._check_abort(action, consecutive_failures, max_consecutive_failures)
                
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
