"""Conversation scanner for discovering and registering conversations.

Scans the filesystem for conversations and updates the database with
current state (location, mtime, event count, and metadata). Uses mtime
as a fast filter to skip unchanged conversations.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import logging

from ohtv.config import Config, get_openhands_dir, get_manifest_path
from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore
from ohtv.db.utils import generate_unique_source_names

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of a scan operation."""
    total_on_disk: int
    new_registered: int
    updated: int
    unchanged: int
    removed: int


def count_events(events_dir: Path) -> int:
    """Count event files in a conversation's events directory."""
    if not events_dir.exists():
        return 0
    return sum(1 for f in events_dir.iterdir() if f.name.startswith("event-"))


def get_events_mtime(events_dir: Path) -> float | None:
    """Get the modification time of the events directory."""
    if not events_dir.exists():
        return None
    return events_dir.stat().st_mtime


def discover_conversations(base_dir: Path, source: str) -> list[tuple[str, Path, str]]:
    """Discover conversation directories under a base path.
    
    Returns list of (conversation_id, conversation_path, source) tuples.
    Looks for directories containing an 'events' subdirectory.
    """
    conversations = []
    if not base_dir.exists():
        return conversations
    
    for entry in base_dir.iterdir():
        if entry.is_dir():
            events_dir = entry / "events"
            if events_dir.exists() and events_dir.is_dir():
                conversations.append((entry.name, entry, source))
    
    return conversations


_MISSING = object()  # sentinel: manifest key absent (vs. present-but-None)


def load_manifest_metadata() -> dict[str, dict]:
    """Load per-conversation metadata cache from the sync manifest.

    Returns:
        Dict mapping conversation ID to a per-entry dict containing the
        manifest's cached, refreshable metadata fields:

        - ``"title"``: cloud title (str or None)
        - ``"labels"``: normalized labels (dict or empty dict sentinel)
        - ``"selected_repository"``: present iff the manifest entry has
          that key. Value is the manifest value (str or None). Issue #87.
        - ``"selected_branch"``: same shape as ``selected_repository``;
          not refreshable via listing API (lives in trajectory
          ``meta.json``). Issue #87.
        - ``"created_at"``: present iff the manifest entry has that key.
          Value is the manifest value as ISO 8601 string or None.
          Issue #87.

        Issue #87 fields are only included when the underlying key
        exists in the manifest entry — this lets ``extract_metadata``
        distinguish "pre-#87 manifest (fall back to base_state.json)"
        from "post-#87 manifest with explicit None (trust the manifest)"
        without a schema migration.

    The returned ``"labels"`` value is ``{}`` (empty dict) when labels are
    absent on the manifest entry — this is the sentinel ``extract_metadata``
    uses to mean "manifest knows about this conversation, but it has no
    labels" so that label removal propagates correctly.
    """
    manifest_path = get_manifest_path()
    if not manifest_path.exists():
        return {}

    try:
        data = json.loads(manifest_path.read_text())
        conversations = data.get("conversations", {})
    except (json.JSONDecodeError, OSError):
        return {}

    metadata_map: dict[str, dict] = {}
    for conv_id, conv_data in conversations.items():
        if not isinstance(conv_data, dict):
            continue
        labels = conv_data.get("labels")
        normalized_labels = (
            labels if (labels and isinstance(labels, dict)) else {}
        )
        entry: dict = {
            "title": conv_data.get("title"),
            "labels": normalized_labels,
        }
        # Only carry Issue #87 fields when present so callers can
        # distinguish missing-key (pre-#87) from present-but-None.
        if "selected_repository" in conv_data:
            entry["selected_repository"] = conv_data.get("selected_repository")
        if "selected_branch" in conv_data:
            entry["selected_branch"] = conv_data.get("selected_branch")
        if "created_at" in conv_data:
            entry["created_at"] = conv_data.get("created_at")
        metadata_map[conv_id] = entry
    return metadata_map


def load_manifest_labels() -> dict[str, dict[str, str]]:
    """Backward-compatible wrapper that returns only the labels component.

    Prefer ``load_manifest_metadata()`` for new code so that title and
    labels are loaded in a single pass.
    """
    return {
        conv_id: meta.get("labels", {})
        for conv_id, meta in load_manifest_metadata().items()
    }


def load_cloud_listing_parents(conn: sqlite3.Connection) -> dict[str, str | None]:
    """Map normalized conversation id → ``parent_conversation_id`` from
    the ``cloud_listing`` snapshot (Issue #108).

    Returns an empty dict when:

    * The ``cloud_listing`` table does not yet exist (pre-#112 schema).
    * The snapshot is empty (no sync has run yet).
    * Any read error occurs (defensive: the scanner falls back to
      whatever the conversations table already records).

    Only rows with a non-null ``parent_conversation_id`` are returned —
    NULL "root" rows are absent from the map. Callers that need
    "explicitly root" semantics should treat absence as
    "no information" rather than "is a root".
    """
    try:
        cursor = conn.execute(
            "SELECT conversation_id, parent_conversation_id "
            "FROM cloud_listing "
            "WHERE parent_conversation_id IS NOT NULL"
        )
    except sqlite3.OperationalError:
        return {}
    return {row[0]: row[1] for row in cursor.fetchall()}


def extract_metadata(
    conv_path: Path,
    source: str,
    labels_map: dict[str, dict[str, str]] | None = None,
    manifest_map: dict[str, dict] | None = None,
    parent_map: dict[str, str | None] | None = None,
    db_overlay: "Conversation | None" = None,
) -> dict:
    """Extract metadata from a conversation directory.

    Args:
        conv_path: Path to conversation directory.
        source: Source identifier ('local' or 'cloud').
        labels_map: Legacy parameter — pre-loaded labels map keyed by
            conversation ID. Used when ``manifest_map`` is not supplied
            to preserve backward compatibility with callers that only
            need labels.
        manifest_map: Pre-loaded manifest metadata map keyed by
            conversation ID, with at minimum ``{"title": ..., "labels": ...}``
            and optionally Issue #87 fields
            ``selected_repository``, ``selected_branch``, ``created_at``.
            Phase C of #114 demotes this to a *cold-upgrade fallback*:
            consulted only when ``db_overlay`` is None or has NULL
            columns. Migration 021 backfills the gap once on upgrade.
        parent_map: Pre-loaded ``conversation_id → parent_conversation_id``
            map sourced from the ``cloud_listing`` snapshot (Issue #108).
            The scanner uses it to surface parent/child relationships in
            ``conversations.parent_conversation_id`` without re-querying
            the cloud. Manifest is intentionally parent-agnostic; this is
            the DB-only sidecar. When ``parent_map`` is ``None`` or the
            conv id is absent from it, ``parent_conversation_id`` is
            returned as ``None``.
        db_overlay: Existing :class:`Conversation` row from the DB, if
            any. Phase C of #114 promotes this to the **canonical
            overlay** for ``title`` / ``labels`` /
            ``selected_repository`` / ``created_at`` / ``selected_branch``
            on cloud convs. When all five columns are populated and the
            row's source is ``'cloud'``, the scanner skips
            ``base_state.json`` entirely — the same optimization
            previously gated on the manifest having all three #87 keys.

    Returns:
        Dict with title, created_at, updated_at, selected_repository,
        labels, parent_conversation_id, selected_branch.
    """
    timestamps_are_utc = source != "local"

    title = None
    selected_repository = None
    created_at = None
    updated_at = None
    selected_branch = None
    conv_id = conv_path.name

    # Phase C of #114: pull the existing DB row's overlay columns up
    # front. These are the canonical store for cloud convs; the
    # manifest is now only a cold-upgrade fallback.
    db_title: str | None = None
    db_selected_repository: str | None = None
    db_created_at: datetime | None = None
    db_labels: dict[str, str] | None = None
    db_selected_branch: str | None = None
    db_has_overlay = source != "local" and db_overlay is not None
    if db_has_overlay:
        db_title = db_overlay.title if isinstance(db_overlay.title, str) and db_overlay.title.strip() else None
        db_selected_repository = db_overlay.selected_repository
        db_created_at = db_overlay.created_at
        db_labels = db_overlay.labels if isinstance(db_overlay.labels, dict) and db_overlay.labels else None
        db_selected_branch = db_overlay.selected_branch

    # Title-source precedence (Issue #86, Phase C update):
    #   1. DB title (Phase C canonical for cloud convs)
    #   2. Manifest title (cold-upgrade fallback)
    #   3. base_state.json title
    #   4. First user message extraction (later fallback)
    manifest_title: str | None = None
    manifest_entry: dict | None = None
    if manifest_map is not None:
        manifest_entry = manifest_map.get(conv_id)
        if manifest_entry:
            mt = manifest_entry.get("title")
            if isinstance(mt, str) and mt.strip():
                manifest_title = mt

    # Issue #87 / Phase C of #114: cloud convs with a fully-populated
    # DB row skip ``base_state.json`` reads. "Fully populated" means
    # the DB carries non-NULL values for title, selected_repository,
    # created_at, and selected_branch. Labels are allowed to be NULL
    # because explicit-no-labels is normalized to NULL in the DB
    # (matching :class:`ConversationStore.update_metadata`).
    #
    # Cold-upgrade fallback: when the DB row hasn't been backfilled
    # yet (migration 021 still pending or never seen the conv), the
    # legacy manifest-presence gate takes over so #87 still works.
    skip_base_state_db = (
        db_has_overlay
        and isinstance(db_overlay.title, str)
        and db_overlay.title.strip() != ""
        and db_overlay.selected_repository is not None
        and db_overlay.created_at is not None
        and db_overlay.selected_branch is not None
    )
    skip_base_state_manifest = (
        source != "local"
        and manifest_entry is not None
        and "selected_repository" in manifest_entry
        and "selected_branch" in manifest_entry
        and "created_at" in manifest_entry
    )
    skip_base_state = skip_base_state_db or skip_base_state_manifest

    base_state = conv_path / "base_state.json"
    if not skip_base_state and base_state.exists():
        try:
            data = json.loads(base_state.read_text())
            title = data.get("title")
            selected_repository = data.get("selected_repository")
            created_at = _parse_datetime(data.get("created_at"), timestamps_are_utc)
            updated_at = _parse_datetime(data.get("updated_at"), timestamps_are_utc)
            bs_branch = data.get("selected_branch")
            if isinstance(bs_branch, str) and bs_branch:
                selected_branch = bs_branch
        except (json.JSONDecodeError, OSError):
            pass

    # Issue #87 / Phase C of #114: overlay editable-cloud-metadata
    # fields. DB wins for cloud convs; manifest is the cold-upgrade
    # fallback only. Local CLI convs are out of scope (base_state.json
    # remains canonical).
    if source != "local":
        if db_has_overlay:
            if db_selected_repository is not None:
                selected_repository = db_selected_repository
            if db_created_at is not None:
                created_at = db_created_at
            if db_selected_branch is not None:
                selected_branch = db_selected_branch
        # Manifest fallback applies regardless of db_has_overlay so
        # that a partially-backfilled DB row still honours the
        # manifest values it lacks. The DB values above (when
        # non-NULL) win against the manifest because they were
        # applied first.
        if manifest_entry is not None:
            if "selected_repository" in manifest_entry and selected_repository is None:
                selected_repository = manifest_entry.get("selected_repository")
            if "selected_branch" in manifest_entry and selected_branch is None:
                ms_branch = manifest_entry.get("selected_branch")
                if isinstance(ms_branch, str) and ms_branch:
                    selected_branch = ms_branch
            if "created_at" in manifest_entry and created_at is None:
                manifest_created_at = manifest_entry.get("created_at")
                if isinstance(manifest_created_at, str) and manifest_created_at:
                    parsed = _parse_datetime(manifest_created_at, assume_utc=True)
                    if parsed is not None:
                        created_at = parsed
                elif manifest_created_at is None and skip_base_state:
                    # Authoritative None from manifest — no base_state
                    # read to fall back to.
                    created_at = None

    # Title overlay (Phase C order): DB title wins, then manifest,
    # then base_state.json (already applied above), then first-user-
    # message fallback.
    if db_title:
        title = db_title
    elif manifest_title:
        title = manifest_title

    # Prefer timestamps from events for accuracy. Always reads events for
    # local-CLI convs and for cloud convs (event reads are not the
    # base_state.json open the regression test is guarding against).
    event_timestamps = _get_event_timestamps(conv_path, timestamps_are_utc)
    if event_timestamps:
        created_at = event_timestamps[0]
        updated_at = event_timestamps[1]

    # Last resort: file mtime (only sensible when base_state.json was
    # actually read; skipped path means we trust manifest + events).
    if created_at is None and not skip_base_state and base_state.exists():
        try:
            file_mtime = datetime.fromtimestamp(base_state.stat().st_mtime, tz=timezone.utc)
            created_at = file_mtime
            updated_at = file_mtime
        except OSError:
            pass

    # Get title from first user message if not present
    if not title:
        title = _get_title_from_first_user_message(conv_path)

    # Labels overlay (Phase C):
    #   1. DB labels (canonical for cloud convs)
    #   2. Manifest labels (cold-upgrade fallback)
    #   3. ``labels_map`` legacy parameter (back-compat for callers that
    #      only supplied labels)
    # Empty dict in the manifest means labels were explicitly removed
    # (store as None to match :class:`ConversationStore.update_metadata`).
    labels: dict[str, str] | None = None
    if db_has_overlay:
        labels = db_labels
    if labels is None:
        effective_labels_map: dict[str, dict[str, str]] | None = labels_map
        if manifest_map is not None and effective_labels_map is None:
            effective_labels_map = {
                cid: meta.get("labels", {}) for cid, meta in manifest_map.items()
            }
        if effective_labels_map:
            manifest_labels = effective_labels_map.get(conv_id)
            labels = manifest_labels if manifest_labels else None

    # Issue #108: parent_conversation_id is a cloud-only concept (local
    # CLI does not have delegation). Look up from the cloud_listing
    # snapshot when available; the conversations table's COALESCE-based
    # upsert preserves any value already written by ``record_cloud_download``
    # if the listing is empty for this id.
    parent_conversation_id = None
    if parent_map is not None and source != "local":
        # Conv ids in the cloud_listing table are normalized (dashless)
        # per AGENTS.md item #14; the directory name (== conv_id here)
        # may be dashed for legacy LXA convs, so we look up both forms.
        normalized = conv_id.replace("-", "")
        parent_conversation_id = parent_map.get(normalized) or parent_map.get(conv_id)

    return {
        "title": title,
        "created_at": created_at,
        "updated_at": updated_at,
        "selected_repository": selected_repository,
        "labels": labels,
        "parent_conversation_id": parent_conversation_id,
        "selected_branch": selected_branch,
    }


def _parse_datetime(value: str | None, assume_utc: bool = True) -> datetime | None:
    """Parse ISO 8601 datetime string."""
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
        local_dt = naive_dt.astimezone()
        return local_dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _get_event_timestamps(conv_path: Path, timestamps_are_utc: bool) -> tuple[datetime, datetime] | None:
    """Get first and last event timestamps."""
    events_dir = conv_path / "events"
    if not events_dir.exists():
        return None
    
    event_files = sorted(events_dir.glob("event-*.json"))
    if not event_files:
        return None
    
    first_ts = _get_event_timestamp(event_files[0], timestamps_are_utc)
    last_ts = _get_event_timestamp(event_files[-1], timestamps_are_utc)
    
    if first_ts and last_ts:
        return (first_ts, last_ts)
    return None


def _get_event_timestamp(event_file: Path, timestamps_are_utc: bool) -> datetime | None:
    """Extract timestamp from an event file."""
    try:
        data = json.loads(event_file.read_text())
        return _parse_datetime(data.get("timestamp"), timestamps_are_utc)
    except (json.JSONDecodeError, OSError):
        return None


def _get_title_from_first_user_message(conv_path: Path, max_length: int = 60) -> str | None:
    """Extract title from the first user message."""
    events_dir = conv_path / "events"
    if not events_dir.exists():
        return None
    
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
    
    return None


def _truncate_title(text: str, max_length: int) -> str:
    """Truncate text to max_length, breaking at word boundary."""
    first_line = text.split("\n")[0].strip()
    if len(first_line) <= max_length:
        return first_line
    truncated = first_line[:max_length].rsplit(" ", 1)[0]
    return truncated + "..."


def scan_conversations(
    conn: sqlite3.Connection,
    force: bool = False,
    remove_missing: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    config: Config | None = None,
) -> ScanResult:
    """Scan filesystem for conversations and update database.
    
    Args:
        conn: Database connection
        force: If True, update all conversations regardless of mtime
        remove_missing: If True, remove DB entries for conversations no longer on disk
        on_progress: Optional callback(current, total, conv_id) for progress updates
        config: Optional config for extra conversation paths (defaults to Config.from_env())
        
    Returns:
        ScanResult with counts of what changed
    """
    if config is None:
        config = Config.from_env()
    
    store = ConversationStore(conn)
    openhands_dir = get_openhands_dir()
    
    # Load title + labels from manifest (for cloud conversations). Manifest
    # title takes precedence over base_state.json (Issue #86 — keeps a cold
    # `db scan` honest after a cloud-side rename).
    manifest_map = load_manifest_metadata()

    # Load parent/child relationships from the latest cloud_listing
    # snapshot (Issue #108). Returns ``{}`` on pre-#112 schemas or when
    # no sync has populated the snapshot — extract_metadata then
    # treats parent_conversation_id as None and the COALESCE in
    # ConversationStore.upsert preserves any prior writeback.
    parent_map = load_cloud_listing_parents(conn)
    
    # Discover from both local CLI and synced cloud locations
    local_dir = openhands_dir / "conversations"
    cloud_dir = openhands_dir / "cloud" / "conversations"
    
    all_discovered = []
    all_discovered.extend(discover_conversations(local_dir, "local"))
    all_discovered.extend(discover_conversations(cloud_dir, "cloud"))
    
    # Discover from extra conversation paths
    extra_source_names = generate_unique_source_names(config.extra_conversation_paths)
    for path, source_name in zip(config.extra_conversation_paths, extra_source_names):
        if not path.exists():
            logger.warning(f"Configured path does not exist: {path}")
        elif not path.is_dir():
            logger.warning(f"Configured path is not a directory: {path}")
        else:
            all_discovered.extend(discover_conversations(path, source_name))
    
    total = len(all_discovered)
    
    # Track IDs we've seen on disk
    seen_ids = set()
    
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    
    for i, (conv_id, conv_path, source) in enumerate(all_discovered):
        if on_progress:
            on_progress(i, total, conv_id)
        
        seen_ids.add(conv_id)
        events_dir = conv_path / "events"
        
        current_mtime = get_events_mtime(events_dir)
        current_count = count_events(events_dir)
        
        existing = store.get(conv_id)
        
        if existing is None:
            # New conversation - extract metadata
            metadata = extract_metadata(
                conv_path, source,
                manifest_map=manifest_map,
                parent_map=parent_map,
                db_overlay=None,
            )
            store.upsert(Conversation(
                id=conv_id,
                location=str(conv_path),
                events_mtime=current_mtime,
                event_count=current_count,
                title=metadata["title"],
                created_at=metadata["created_at"],
                updated_at=metadata["updated_at"],
                selected_repository=metadata["selected_repository"],
                source=source,
                labels=metadata.get("labels"),
                parent_conversation_id=metadata.get("parent_conversation_id"),
                # Phase C of #114: scanner extracts selected_branch from
                # base_state.json (when present) so cold scans against a
                # pre-Phase-C corpus heal themselves on first pass. Sync
                # is the primary writer; this is the back-stop.
                selected_branch=metadata.get("selected_branch"),
            ))
            new_count += 1
        elif force or _has_changed(existing, current_mtime, current_count):
            # Changed or forced update - re-extract metadata
            metadata = extract_metadata(
                conv_path, source,
                manifest_map=manifest_map,
                parent_map=parent_map,
                # Phase C of #114: DB row is the canonical overlay for
                # cloud convs. extract_metadata trusts it over the
                # manifest for title / labels / selected_repository /
                # created_at / selected_branch.
                db_overlay=existing,
            )
            store.upsert(Conversation(
                id=conv_id,
                location=str(conv_path),
                registered_at=existing.registered_at,  # Preserve original
                events_mtime=current_mtime,
                event_count=current_count,
                title=metadata["title"],
                created_at=metadata["created_at"],
                updated_at=metadata["updated_at"],
                selected_repository=metadata["selected_repository"],
                source=source,
                labels=metadata.get("labels"),
                parent_conversation_id=metadata.get("parent_conversation_id"),
                selected_branch=metadata.get("selected_branch"),
            ))
            updated_count += 1
        else:
            unchanged_count += 1
    
    # Signal completion
    if on_progress:
        on_progress(total, total, "")
    
    # Handle missing conversations
    removed_count = 0
    if remove_missing:
        all_registered = store.list_all()
        for conv in all_registered:
            if conv.id not in seen_ids:
                store.delete(conv.id)
                removed_count += 1
    
    return ScanResult(
        total_on_disk=len(all_discovered),
        new_registered=new_count,
        updated=updated_count,
        unchanged=unchanged_count,
        removed=removed_count,
    )


def _has_changed(existing: Conversation, current_mtime: float | None, current_count: int) -> bool:
    """Check if a conversation has changed since last scan."""
    # If we don't have mtime info, assume changed
    if existing.events_mtime is None or current_mtime is None:
        return True
    
    # mtime increased means something changed
    if current_mtime > existing.events_mtime:
        return True
    
    # Event count changed (shouldn't happen without mtime change, but be safe)
    if current_count != existing.event_count:
        return True
    
    return False


def get_changed_conversations(conn: sqlite3.Connection) -> list[Conversation]:
    """Get conversations that have changed since last scan.
    
    Useful for finding conversations that need reprocessing without
    actually updating the database.
    """
    store = ConversationStore(conn)
    openhands_dir = get_openhands_dir()
    
    # Load title + labels from manifest (manifest title wins; Issue #86)
    manifest_map = load_manifest_metadata()
    # Issue #108: parent/child relationships from cloud_listing snapshot.
    parent_map = load_cloud_listing_parents(conn)
    
    local_dir = openhands_dir / "conversations"
    cloud_dir = openhands_dir / "cloud" / "conversations"
    
    changed = []
    
    all_discovered = (
        discover_conversations(local_dir, "local") +
        discover_conversations(cloud_dir, "cloud")
    )
    
    for conv_id, conv_path, source in all_discovered:
        events_dir = conv_path / "events"
        current_mtime = get_events_mtime(events_dir)
        current_count = count_events(events_dir)
        
        existing = store.get(conv_id)
        
        if existing is None or _has_changed(existing, current_mtime, current_count):
            metadata = extract_metadata(conv_path, source, manifest_map=manifest_map, parent_map=parent_map)
            changed.append(Conversation(
                id=conv_id,
                location=str(conv_path),
                events_mtime=current_mtime,
                event_count=current_count,
                title=metadata["title"],
                created_at=metadata["created_at"],
                updated_at=metadata["updated_at"],
                selected_repository=metadata["selected_repository"],
                source=source,
                labels=metadata.get("labels"),
                parent_conversation_id=metadata.get("parent_conversation_id"),
            ))
    
    return changed
