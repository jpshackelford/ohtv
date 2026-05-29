"""Migration 021: ``conversations.selected_branch`` + per-conv metadata backfill.

Issue #114 Phase C. Two coupled additions in one migration:

1. **Schema addition**: a new nullable ``selected_branch`` column on
   ``conversations``. Today this field lives only in
   ``sync_manifest.json`` (sync mirrors it from a trajectory ZIP's
   ``meta.json`` at download time — it is NOT in the cloud listing
   API). Phase C makes the DB the canonical store for *every* per-conv
   cloud metadata field, which requires giving ``selected_branch`` a
   home.

2. **One-time backfill** from ``~/.ohtv/sync_manifest.json`` into the
   DB columns that are still NULL after the existing scanner / sync
   writes. Covers the five Phase C fields the scanner's overlay
   currently sources from the manifest:

   * ``title``
   * ``labels``
   * ``selected_repository``
   * ``created_at``
   * ``cloud_updated_at`` (re-runs the same backfill migration 018
     performed for #112, but is now also additive — re-running it
     against a row that already has a value is a no-op)
   * ``selected_branch`` (the new column from step 1)

The backfill is purely additive: a column already populated by sync
(``cloud_updated_at`` from #112's ``record_cloud_download``, or one of
the four #87 columns from a previous ``db scan``) is **never**
overwritten. Pre-Phase-C deployments have all five live values in the
manifest; this migration drains them once so the scanner / sync read
paths can start trusting the DB columns immediately on first boot
after upgrade.

Phase C does not delete manifest reads/writes — that's Phase D. The
manifest is dual-written for one release for downgrade safety, and
the scanner / sync read paths keep the manifest fallback so users who
downgrade after a single Phase-C release have a sane recovery path.

Per AGENTS.md item #14 conversation IDs are stored dashless. The
manifest historically carried both forms; we normalize on read here
so the backfill matches the conversations table regardless of which
form the manifest entry uses.

Per AGENTS.md item #27 the manifest has been "the canonical cache for
cloud-side editable metadata"; this migration is the first step in
its retirement. The companion docs update lives in
``docs/reference/sync-state-ownership.md`` §3 Phase C.
"""

from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger("ohtv")


def _normalize_conversation_id(conv_id: str) -> str:
    """Strip dashes per AGENTS.md item #14.

    Migration 018 did the same; copied here to avoid an import-time
    dependency between the two migration files.
    """
    return conv_id.replace("-", "")


def _add_selected_branch_column(conn: sqlite3.Connection) -> None:
    """Add ``conversations.selected_branch`` if it's not already present.

    ``ALTER TABLE ADD COLUMN`` does not support ``IF NOT EXISTS`` in
    older SQLite versions we still support; we use a ``PRAGMA
    table_info`` probe so re-running the migration against a partially-
    applied DB is safe.
    """
    cursor = conn.execute("PRAGMA table_info(conversations)")
    existing = {row[1] for row in cursor.fetchall()}
    if "selected_branch" not in existing:
        conn.execute("ALTER TABLE conversations ADD COLUMN selected_branch TEXT")


def _load_manifest_data() -> dict | None:
    """Best-effort read of ``sync_manifest.json``.

    Returns the parsed top-level dict, or ``None`` on any of:

    * Missing manifest file (fresh install / no prior sync).
    * Malformed JSON.
    * Top-level value is not a dict (defensive against bad upgrades).
    * Cannot import ``ohtv.config`` to resolve the path (defensive
      against a Python import order quirk during the migration run).

    The backfill is purely additive, so "no manifest" simply means
    "no per-conv writes to perform here" — every column stays NULL
    and the next ``ohtv sync`` populates it via the dual-write path.
    """
    try:
        from ohtv.config import get_manifest_path
    except Exception:  # pragma: no cover - defensive
        log.warning("Migration 021: cannot import ohtv.config; skipping backfill")
        return None

    try:
        manifest_path = get_manifest_path()
    except Exception:  # pragma: no cover - defensive
        log.warning("Migration 021: cannot resolve manifest path; skipping backfill")
        return None

    if not manifest_path.exists():
        log.info(
            "Migration 021: no sync_manifest.json at %s; "
            "per-conv metadata columns left NULL (next sync fills them)",
            manifest_path,
        )
        return None

    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "Migration 021: could not read/parse %s (%s); "
            "per-conv metadata columns left NULL",
            manifest_path,
            exc,
        )
        return None

    if not isinstance(data, dict):
        log.warning(
            "Migration 021: %s is not a JSON object; skipping backfill",
            manifest_path,
        )
        return None
    return data


def _backfill_per_conv_metadata(conn: sqlite3.Connection) -> None:
    """Copy non-NULL manifest values into DB columns that are still NULL.

    Covers ``title`` / ``labels`` / ``selected_repository`` /
    ``created_at`` / ``cloud_updated_at`` / ``selected_branch``. The
    UPDATE uses ``COALESCE`` so any column already populated by sync /
    scanner is left alone — backfill is additive, never destructive.

    Read-only with respect to the manifest. Tolerant of missing keys,
    explicit NULL values, and ID-form mismatches (per AGENTS.md item
    #14 we normalize the manifest IDs on read).
    """
    data = _load_manifest_data()
    if data is None:
        return

    conversations = data.get("conversations")
    if not isinstance(conversations, dict):
        log.info(
            "Migration 021: manifest has no 'conversations' mapping; "
            "nothing to backfill"
        )
        return

    updates: list[tuple] = []
    for raw_id, entry in conversations.items():
        if not isinstance(entry, dict):
            continue
        norm_id = _normalize_conversation_id(raw_id)
        if not norm_id:
            continue

        title = entry.get("title") if isinstance(entry.get("title"), str) else None

        # ``labels`` is normalized in the manifest to dict-or-None. An
        # empty dict means "explicitly no labels" → store NULL to
        # match ``ConversationStore.update_metadata`` semantics.
        labels_val = entry.get("labels")
        if isinstance(labels_val, dict) and len(labels_val) > 0:
            labels_json: str | None = json.dumps(labels_val)
        else:
            labels_json = None

        selected_repository = (
            entry.get("selected_repository")
            if isinstance(entry.get("selected_repository"), str)
            else None
        )
        created_at = (
            entry.get("created_at")
            if isinstance(entry.get("created_at"), str)
            else None
        )
        cloud_updated_at = (
            entry.get("updated_at")
            if isinstance(entry.get("updated_at"), str)
            else None
        )
        selected_branch = (
            entry.get("selected_branch")
            if isinstance(entry.get("selected_branch"), str)
            else None
        )

        # Skip rows where the manifest carries nothing usable for any
        # of the six columns — the UPDATE would be a pure no-op.
        if not any(
            (
                title,
                labels_json,
                selected_repository,
                created_at,
                cloud_updated_at,
                selected_branch,
            )
        ):
            continue

        updates.append(
            (
                title,
                labels_json,
                selected_repository,
                created_at,
                cloud_updated_at,
                selected_branch,
                norm_id,
            )
        )

    if not updates:
        log.info(
            "Migration 021: manifest had no usable per-conv metadata; "
            "DB columns left untouched"
        )
        return

    # COALESCE preserves any value already on the row. ``UPDATE`` only
    # matches IDs already present in ``conversations`` — manifest
    # entries with no corresponding row are silently skipped.
    # Backfilling them here would race with whatever code path is
    # responsible for the row's absence (likely #113 reconciliation),
    # so we let that path heal them on its own schedule.
    conn.executemany(
        """
        UPDATE conversations
           SET title               = COALESCE(title, ?),
               labels              = COALESCE(labels, ?),
               selected_repository = COALESCE(selected_repository, ?),
               created_at          = COALESCE(created_at, ?),
               cloud_updated_at    = COALESCE(cloud_updated_at, ?),
               selected_branch     = COALESCE(selected_branch, ?)
         WHERE id = ?
        """,
        updates,
    )
    log.info(
        "Migration 021: backfilled per-conv metadata from manifest "
        "for up to %d entries (DB rows updated where ids match)",
        len(updates),
    )


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply migration 021: ``selected_branch`` column + Phase C backfill."""
    _add_selected_branch_column(conn)
    _backfill_per_conv_metadata(conn)
