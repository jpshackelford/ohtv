"""Just-in-time (lazy) conversation fetcher with caching.

This module enables on-demand fetching of conversations from the cloud API,
caching them locally for future use. It reuses the same storage location
and DB schema as full sync mode for seamless interoperability.

Key features:
- Lazy loading: Only fetch what the current query needs
- Opportunistic caching: Store fetched conversations for future reuse
- Cache freshness: Historical conversations (>24h old) never expire
- Parallel downloads: Uses ThreadPoolExecutor for concurrent fetching
"""

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ohtv.config import Config
from ohtv.db import get_ready_connection
from ohtv.db.scanner import extract_metadata
from ohtv.db.stores import ConversationStore
from ohtv.exporter import TrajectoryExporter
from ohtv.sources.cloud import CloudClient

log = logging.getLogger("ohtv")

# Match sync.py's conservative parallel workers setting
DEFAULT_MAX_WORKERS = 3


@dataclass
class JITFetchResult:
    """Results of a JIT fetch operation."""
    
    requested_ids: list[str]
    already_cached: list[str]
    fetched: list[str]
    failed: list[str]
    
    @property
    def up_to_date(self) -> list[str]:
        """Conversations that were cached and fresh (no fetch needed)."""
        return self.already_cached
    
    @property
    def total_available(self) -> int:
        """Total conversations available for use (cached + fetched)."""
        return len(self.already_cached) + len(self.fetched)


class JITFetcher:
    """Just-in-time conversation fetcher with caching.
    
    Fetches conversations on-demand from the cloud API and caches them
    locally using the same storage location as full sync mode. This enables
    targeted queries without requiring a full upfront sync.
    
    Args:
        config: Configuration with cloud API URL and storage paths
        cloud_client: Cloud API client for fetching conversations
    """
    
    def __init__(self, config: Config, cloud_client: CloudClient):
        self.config = config
        self.cloud = cloud_client
        self.exporter = TrajectoryExporter(config.synced_conversations_dir)
    
    def ensure_conversations(
        self,
        *,
        conv_ids: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        force_refresh: bool = False,
        max_age_hours: int = 24,
        on_progress: Callable | None = None,
    ) -> JITFetchResult:
        """Ensure conversations are available locally.
        
        Either fetches conversations with explicit IDs or queries the cloud
        API by date range. Checks cache status and only fetches missing or
        stale conversations.
        
        Args:
            conv_ids: Explicit list of conversation IDs to fetch. If None,
                queries cloud by date range.
            since: Fetch conversations updated since this time (inclusive).
                Ignored if conv_ids is provided.
            until: Fetch conversations updated until this time (inclusive).
                Ignored if conv_ids is provided.
            force_refresh: Refetch even if cached locally.
            max_age_hours: For recent dates (≤24h old), refetch if cached
                more than N hours ago. Default: 24.
            on_progress: Optional callback(conv_id, action) for progress
                updates. Actions: "downloading", "indexing", "cached".
        
        Returns:
            JITFetchResult with lists of requested, cached, fetched, and
            failed conversation IDs.
        """
        # Step 1: Determine which conversations are needed
        if conv_ids is None:
            if since is None and until is None:
                raise ValueError("Must provide either conv_ids or date range (since/until)")
            conv_ids = self._query_cloud_for_ids(since, until)
            log.info(f"JIT: Found {len(conv_ids)} conversations matching date filter")
        else:
            log.info(f"JIT: Ensuring {len(conv_ids)} explicit conversation IDs")
        
        if not conv_ids:
            return JITFetchResult(
                requested_ids=[],
                already_cached=[],
                fetched=[],
                failed=[],
            )
        
        # Step 2: Check cache status
        cache_status = self._check_cache_status(
            conv_ids,
            max_age_hours=max_age_hours,
            force_refresh=force_refresh,
        )
        
        # Report cached conversations to progress callback
        if on_progress:
            for conv_id in cache_status["fresh"]:
                on_progress(conv_id, "cached")
        
        # Step 3: Fetch missing/stale conversations
        fetch_needed = cache_status["missing"] + cache_status["stale"]
        fetched = []
        failed = []
        
        if fetch_needed:
            log.info(f"JIT: Fetching {len(fetch_needed)} conversations ({len(cache_status['missing'])} missing, {len(cache_status['stale'])} stale)")
            fetched, failed = self._fetch_conversations(
                fetch_needed,
                on_progress=on_progress,
            )
        
        return JITFetchResult(
            requested_ids=conv_ids,
            already_cached=cache_status["fresh"],
            fetched=fetched,
            failed=failed,
        )
    
    def _query_cloud_for_ids(
        self,
        since: datetime | None,
        until: datetime | None,
    ) -> list[str]:
        """Query cloud API for conversation IDs matching date filter.
        
        Args:
            since: Lower bound for updated_at filter
            until: Upper bound for updated_at filter (client-side filter)
        
        Returns:
            List of conversation IDs matching the date filter
        """
        log.debug(f"JIT: Querying cloud for conversations (since={since}, until={until})")
        
        # Use search_all_conversations with date filter
        # Note: API only supports updated_at__gte (since), so until is client-side
        conversations = self.cloud.search_all_conversations(
            updated_since=since,
            include_sub_conversations=True,
        )
        
        # Filter by until date if provided (client-side)
        if until:
            conversations = [
                c for c in conversations
                if self._parse_updated_at(c) <= until
            ]
        
        return [c["id"] for c in conversations]
    
    def _parse_updated_at(self, conv_dict: dict) -> datetime:
        """Parse updated_at from cloud conversation dict.
        
        Args:
            conv_dict: Conversation dictionary from cloud API
        
        Returns:
            Parsed datetime (timezone-aware UTC)
        """
        updated_at_str = conv_dict.get("updated_at", "")
        if not updated_at_str:
            # Fallback to created_at if updated_at is missing
            updated_at_str = conv_dict.get("created_at", "")
        
        if not updated_at_str:
            # Last resort: use current time (will include in results)
            return datetime.now(timezone.utc)
        
        # Parse ISO format timestamp
        dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        return dt
    
    def _check_cache_status(
        self,
        conv_ids: list[str],
        max_age_hours: int,
        force_refresh: bool,
    ) -> dict[str, list[str]]:
        """Check which conversations are cached and fresh.
        
        Args:
            conv_ids: List of conversation IDs to check
            max_age_hours: Maximum age in hours for recent conversations
            force_refresh: If True, mark all as stale
        
        Returns:
            Dict with keys 'fresh', 'stale', 'missing', each containing
            a list of conversation IDs
        """
        status = {"fresh": [], "stale": [], "missing": []}
        
        if force_refresh:
            log.debug("JIT: Force refresh enabled, marking all as stale")
            status["stale"] = conv_ids
            return status
        
        # Query DB for existing conversations
        with get_ready_connection() as conn:
            store = ConversationStore(conn)
            
            for conv_id in conv_ids:
                # Normalize ID (remove dashes) per AGENTS.md item #14
                normalized_id = conv_id.replace("-", "")
                conv = store.get_by_id(normalized_id)
                
                if conv is None:
                    status["missing"].append(conv_id)
                    continue
                
                # Check if cache is fresh
                # Historical dates (>24h old): always fresh
                # Recent dates: check max_age
                if self._is_historical(conv.created_at):
                    status["fresh"].append(conv_id)
                else:
                    # Check when we last downloaded it
                    age_hours = self._get_cache_age_hours(conv)
                    if age_hours is not None and age_hours < max_age_hours:
                        status["fresh"].append(conv_id)
                    else:
                        status["stale"].append(conv_id)
        
        log.debug(f"JIT: Cache status - {len(status['fresh'])} fresh, {len(status['stale'])} stale, {len(status['missing'])} missing")
        return status
    
    def _is_historical(self, created_at: datetime | None) -> bool:
        """Check if a conversation is historical (>24h old).
        
        Args:
            created_at: Conversation creation timestamp
        
        Returns:
            True if conversation is >24h old, False otherwise
        """
        if created_at is None:
            return False
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Ensure timezone-aware comparison
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        return created_at < cutoff
    
    def _get_cache_age_hours(self, conv) -> float | None:
        """Get age of cached conversation in hours.
        
        Args:
            conv: Conversation object from DB
        
        Returns:
            Age in hours, or None if age cannot be determined
        """
        # Use cloud_updated_at if available (tracks when we last fetched)
        if hasattr(conv, "cloud_updated_at") and conv.cloud_updated_at:
            cloud_updated_at = conv.cloud_updated_at
            
            # Parse if string
            if isinstance(cloud_updated_at, str):
                cloud_updated_at = datetime.fromisoformat(cloud_updated_at)
            
            # Ensure timezone-aware
            if cloud_updated_at.tzinfo is None:
                cloud_updated_at = cloud_updated_at.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            age_seconds = (now - cloud_updated_at).total_seconds()
            return age_seconds / 3600
        
        return None
    
    def _fetch_conversations(
        self,
        conv_ids: list[str],
        on_progress: Callable | None = None,
    ) -> tuple[list[str], list[str]]:
        """Fetch conversations from cloud and index them.
        
        Uses ThreadPoolExecutor for parallel downloads, matching sync.py's
        approach with DEFAULT_MAX_WORKERS (3 concurrent downloads).
        
        Args:
            conv_ids: List of conversation IDs to fetch
            on_progress: Optional callback(conv_id, action) for progress
        
        Returns:
            Tuple of (fetched_ids, failed_ids)
        """
        fetched = []
        failed = []
        
        # Download with parallel workers
        with ThreadPoolExecutor(max_workers=DEFAULT_MAX_WORKERS) as executor:
            # Submit all tasks
            future_to_id = {
                executor.submit(
                    self._download_and_index_conversation,
                    conv_id,
                    on_progress,
                ): conv_id
                for conv_id in conv_ids
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_id):
                conv_id = future_to_id[future]
                try:
                    success = future.result()
                    if success:
                        fetched.append(conv_id)
                    else:
                        failed.append(conv_id)
                except Exception as e:
                    log.error(f"JIT: Failed to fetch {conv_id}: {e}")
                    failed.append(conv_id)
        
        return fetched, failed
    
    def _download_and_index_conversation(
        self,
        conv_id: str,
        on_progress: Callable | None = None,
    ) -> bool:
        """Download a single conversation and index it to the DB.
        
        Args:
            conv_id: Conversation ID to download
            on_progress: Optional callback(conv_id, action) for progress
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if on_progress:
                on_progress(conv_id, "downloading")
            
            # Download trajectory zip
            zip_bytes = self.cloud.download_trajectory(conv_id)
            
            # Export to local format
            conv_dir = self.exporter.export_from_zip_bytes(conv_id, zip_bytes)
            
            if on_progress:
                on_progress(conv_id, "indexing")
            
            # Record in DB
            self._index_conversation(conv_id, conv_dir)
            
            log.debug(f"JIT: Successfully fetched and indexed {conv_id}")
            return True
            
        except Exception as e:
            log.error(f"JIT: Failed to download/index {conv_id}: {e}")
            return False
    
    def _index_conversation(self, conv_id: str, conv_dir: Path) -> None:
        """Index a freshly-downloaded conversation to the DB.
        
        This records the conversation in the DB and extracts metadata using
        the scanner. Also runs minimal processing stages (refs, actions) so
        the conversation is immediately queryable.
        
        Args:
            conv_id: Conversation ID
            conv_dir: Path to conversation directory
        """
        # Load base_state.json for metadata
        base_state_path = conv_dir / "base_state.json"
        if not base_state_path.exists():
            log.warning(f"JIT: No base_state.json for {conv_id}, skipping metadata")
            return
        
        base_state = json.loads(base_state_path.read_text())
        
        # Record cloud download in DB
        with get_ready_connection() as conn:
            store = ConversationStore(conn)
            
            store.record_cloud_download(
                conversation_id=conv_id,
                location=str(conv_dir),
                cloud_updated_at=base_state.get("updated_at"),
                parent_conversation_id=base_state.get("parent_conversation_id"),
                selected_branch=base_state.get("selected_branch"),
            )
            
            # Extract metadata (title, created_at, event_count, etc.)
            # This is lightweight and runs synchronously
            extract_metadata(conn, str(conv_dir), source="cloud")
            
            # Run minimal processing stages so conversation is queryable
            # Note: Full processing (all stages) happens later via db process
            from ohtv.db.stages import STAGES
            
            # Get conversation record
            normalized_id = conv_id.replace("-", "")
            conv = store.get_by_id(normalized_id)
            
            if conv:
                # Run refs and actions stages (fast, essential for queries)
                for stage_name in ["refs", "actions"]:
                    if stage_name in STAGES:
                        try:
                            process_fn = STAGES[stage_name]
                            process_fn(conn, conv)
                            log.debug(f"JIT: Processed stage '{stage_name}' for {conv_id}")
                        except Exception as e:
                            log.warning(f"JIT: Failed to process stage '{stage_name}' for {conv_id}: {e}")
            
            conn.commit()
