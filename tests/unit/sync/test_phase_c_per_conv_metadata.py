"""Phase C of #114: per-conv cloud metadata moves to DB columns.

Three test surfaces:

1. **Sync gate reads from DB.** After Phase C, ``_categorize_via_set_diff``
   compares the cloud listing's ``updated_at`` against
   ``conversations.cloud_updated_at`` (the DB column) rather than the
   manifest entry. A manifest entry without a matching DB row is
   still treated as a download trigger via the cold-upgrade fallback,
   but the canonical read is the DB.

2. **Download path writes editable cloud metadata to DB.** Sync's
   ``_record_cloud_download_in_db`` now writes ``title`` / ``labels`` /
   ``selected_repository`` / ``created_at`` / ``selected_branch`` to
   the DB alongside the cursor — without this, the DB would lag the
   manifest until ``db scan`` ran.

3. **``get_status`` reads from DB.** ``ohtv sync --status`` now sums
   ``conversations.event_count`` (the scanner-maintained live count)
   instead of the manifest's download-time snapshot.

4. **Migration 021 backfills.** A pre-Phase-C deployment with full
   manifest entries but NULL DB columns has those columns populated
   on first boot post-upgrade.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ohtv.db import migrate
from ohtv.db.stores import ConversationStore
from ohtv.db.models import Conversation
from ohtv.sync import SyncManager

from .builders import ConvFactory
from .fakes import FakeCloudClient, FakeConversation


_UTC = timezone.utc


# ---------------------------------------------------------------------------
# 1. Sync gate reads from DB
# ---------------------------------------------------------------------------
def test_sync_gate_compares_cloud_updated_at_against_db(
    sync_manager_factory, fake_cloud: FakeCloudClient, tmp_path: Path
):
    """If the DB cursor matches the cloud listing's updated_at, the
    conversation is treated as in-sync — even with a missing or stale
    manifest entry. This is the Phase C canonical-read contract."""
    fake_cloud.add(
        FakeConversation(
            id="a",
            title="Hello",
            created_at=datetime(2024, 1, 1, tzinfo=_UTC),
            updated_at=datetime(2024, 1, 1, tzinfo=_UTC),
        )
    )
    manager = sync_manager_factory(fake_cloud)
    result = manager.sync()
    assert result.new == 1

    # Corrupt the manifest entry (simulate a downgrade / manifest
    # truncation). The DB cursor still matches the cloud's
    # updated_at, so a second sync should be a no-op.
    manager.manifest.conversations["a"]["updated_at"] = ""
    result2 = manager.sync()
    assert result2.new == 0
    assert result2.updated == 0


def test_sync_gate_treats_stale_db_cursor_as_updated(
    sync_manager_factory, fake_cloud: FakeCloudClient, tmp_path: Path
):
    """Initial sync writes the cursor. Mutate it in the DB to simulate
    a stale local state and confirm the next sync re-downloads."""
    fake_cloud.add(
        FakeConversation(
            id="a",
            title="Hello",
            created_at=datetime(2024, 1, 1, tzinfo=_UTC),
            updated_at=datetime(2024, 1, 1, tzinfo=_UTC),
        )
    )
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE conversations SET cloud_updated_at = '1999-01-01T00:00:00Z' "
            "WHERE id = 'a'"
        )
        conn.commit()
    finally:
        conn.close()

    result = manager.sync()
    assert result.updated == 1


# ---------------------------------------------------------------------------
# 2. Download path writes editable cloud metadata to DB
# ---------------------------------------------------------------------------
def test_download_writes_editable_metadata_to_db(
    sync_manager_factory, fake_cloud: FakeCloudClient, tmp_path: Path
):
    """Right after a successful download the DB row carries title,
    labels, selected_repository, created_at, cloud_updated_at — no
    ``db scan`` required."""
    fake_cloud.add(
        FakeConversation(
            id="a",
            title="My Convo",
            created_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=_UTC),
            updated_at=datetime(2024, 6, 7, 8, 9, 10, tzinfo=_UTC),
            tags={"phase": "qa", "team": "ai"},
            selected_repository="acme/widget",
        )
    )
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT title, labels, selected_repository, created_at, "
            "       cloud_updated_at, selected_branch, source "
            "FROM conversations WHERE id = 'a'"
        ).fetchone()
    finally:
        conn.close()

    assert row["source"] == "cloud"
    assert row["title"] == "My Convo"
    assert json.loads(row["labels"]) == {"phase": "qa", "team": "ai"}
    assert row["selected_repository"] == "acme/widget"
    assert row["created_at"].startswith("2024-01-02")
    assert row["cloud_updated_at"] == "2024-06-07T08:09:10Z"
    # selected_branch lives in meta.json; the fake doesn't embed it
    # by default → NULL.
    assert row["selected_branch"] is None


def test_download_path_writes_selected_branch_when_present_in_meta(
    sync_manager_factory, fake_cloud: FakeCloudClient, tmp_path: Path
):
    """When the trajectory ZIP's meta.json carries selected_branch,
    sync mirrors it into the DB column.

    Builds the trajectory ZIP directly via :func:`make_trajectory_zip`
    so we can populate ``meta.json.selected_branch`` — which the
    ``FakeConversation`` dataclass does not yet model (its default
    lazy build only carries id/title/timestamps/repo).
    """
    from .builders import make_trajectory_zip

    conv = FakeConversation(
        id="a",
        title="Branched",
        created_at=datetime(2024, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=_UTC),
    )
    # Pre-build the trajectory with selected_branch embedded.
    conv.trajectory_zip = make_trajectory_zip(
        conv_id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        selected_branch="feature/x",
    )
    fake_cloud.add(conv)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT selected_branch FROM conversations WHERE id = 'a'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "feature/x"


# ---------------------------------------------------------------------------
# 3. get_status reads from DB
# ---------------------------------------------------------------------------
def test_get_status_uses_db_event_count(
    sync_manager_factory, fake_cloud: FakeCloudClient, tmp_path: Path
):
    """``ohtv sync --status`` sums ``conversations.event_count`` so a
    conv that grew post-sync is reflected immediately, not at the
    next download. We can't grow events post-sync in this harness
    without re-downloading, but we *can* verify the source — by
    mutating the DB's event_count and asserting the status changes
    while the manifest's snapshot stays put."""
    fake_cloud.add(FakeConversation(id="a", title="One"))
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Inflate the DB count to simulate post-sync event growth.
    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE conversations SET event_count = 99 WHERE id = 'a'"
        )
        conn.commit()
    finally:
        conn.close()

    status = manager.get_status()
    assert status["total_conversations"] == 1
    assert status["total_events"] == 99


# ---------------------------------------------------------------------------
# 4. Migration 021 backfills NULL DB columns from the manifest
# ---------------------------------------------------------------------------
def test_migration_021_backfills_metadata_from_manifest(tmp_path: Path, monkeypatch):
    """A pre-Phase-C deployment has full manifest entries but NULL DB
    columns. Migration 021 populates them on the next ``migrate()``."""
    # Build a manifest with the five Phase C fields populated for two
    # conversations.
    manifest = {
        "conversations": {
            "a" * 32: {
                "title": "Convo A",
                "labels": {"phase": "qa"},
                "selected_repository": "acme/widget",
                "selected_branch": "feature/x",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-06-07T08:09:10Z",
            },
            "b" * 32: {
                "title": "Convo B",
                "selected_branch": "main",
            },
        }
    }
    manifest_path = tmp_path / "sync_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        "ohtv.config.get_manifest_path", lambda: manifest_path
    )

    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Apply migrations 1-020 only (simulate pre-Phase-C state).
        from ohtv.db.migrations import (
            apply_migration,
            get_applied_migrations,
            get_pending_migrations,
        )
        # Bootstrap the ``_migrations`` table.
        get_applied_migrations(conn)
        for path in get_pending_migrations():
            if path.name >= "021_":
                break
            apply_migration(conn, path)
        # Seed two rows with NULL editable metadata.
        for cid in ("a" * 32, "b" * 32):
            conn.execute(
                "INSERT INTO conversations (id, location, source) "
                "VALUES (?, '/tmp/x', 'cloud')",
                (cid,),
            )
        conn.commit()

        # Now apply migration 021 (which backfills from manifest).
        migrate(conn)

        rows = {
            row["id"]: row
            for row in conn.execute(
                "SELECT id, title, labels, selected_repository, "
                "       created_at, cloud_updated_at, selected_branch "
                "FROM conversations"
            )
        }
    finally:
        conn.close()

    a = rows["a" * 32]
    assert a["title"] == "Convo A"
    assert json.loads(a["labels"]) == {"phase": "qa"}
    assert a["selected_repository"] == "acme/widget"
    assert a["created_at"] == "2024-01-01T00:00:00Z"
    assert a["cloud_updated_at"] == "2024-06-07T08:09:10Z"
    assert a["selected_branch"] == "feature/x"

    b = rows["b" * 32]
    assert b["title"] == "Convo B"
    assert b["selected_branch"] == "main"
    # No selected_repository or labels in the manifest entry.
    assert b["selected_repository"] is None
    assert b["labels"] is None


def test_migration_021_does_not_overwrite_existing_db_values(
    tmp_path: Path, monkeypatch
):
    """Idempotency / additive contract: rows where the DB already
    carries a value are never clobbered by the backfill."""
    manifest = {
        "conversations": {
            "a" * 32: {
                "title": "Manifest Title",
                "selected_repository": "manifest/repo",
            },
        }
    }
    manifest_path = tmp_path / "sync_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        "ohtv.config.get_manifest_path", lambda: manifest_path
    )

    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        from ohtv.db.migrations import (
            apply_migration,
            get_applied_migrations,
            get_pending_migrations,
        )
        get_applied_migrations(conn)
        for path in get_pending_migrations():
            if path.name >= "021_":
                break
            apply_migration(conn, path)
        # Seed a row with the DB already populated.
        conn.execute(
            "INSERT INTO conversations "
            "(id, location, source, title, selected_repository) "
            "VALUES (?, '/tmp/x', 'cloud', 'DB Title', 'db/repo')",
            ("a" * 32,),
        )
        conn.commit()

        migrate(conn)

        row = conn.execute(
            "SELECT title, selected_repository "
            "FROM conversations WHERE id = ?",
            ("a" * 32,),
        ).fetchone()
    finally:
        conn.close()

    # DB-side values win — manifest never clobbers them.
    assert row["title"] == "DB Title"
    assert row["selected_repository"] == "db/repo"


# ---------------------------------------------------------------------------
# 5. Scanner DB overlay (Phase C: prefers DB over manifest)
# ---------------------------------------------------------------------------
def test_scanner_overlay_prefers_db_over_manifest(tmp_path: Path, monkeypatch):
    """When the DB row carries a title, the scanner's overlay
    propagates it through unchanged — even when the manifest carries
    a different (stale) value."""
    from ohtv.db.scanner import extract_metadata

    conv_path = tmp_path / "conv"
    conv_path.mkdir()
    # base_state.json would be the third-priority source.
    (conv_path / "base_state.json").write_text(
        json.dumps({
            "title": "Base State Title",
            "selected_repository": "base/repo",
            "selected_branch": "main",
            "created_at": "2024-01-01T00:00:00Z",
        })
    )

    db_overlay = Conversation(
        id="abc",
        location=str(conv_path),
        title="DB Title",
        selected_repository="db/repo",
        created_at=datetime(2024, 6, 7, 8, 9, 10, tzinfo=_UTC),
        selected_branch="feature/x",
        labels={"phase": "qa"},
        source="cloud",
    )
    manifest_map = {
        "conv": {
            "title": "Manifest Title",
            "labels": {"phase": "old"},
            "selected_repository": "manifest/repo",
            "selected_branch": "manifest-branch",
            "created_at": "2023-01-01T00:00:00Z",
        }
    }
    meta = extract_metadata(
        conv_path,
        source="cloud",
        manifest_map=manifest_map,
        db_overlay=db_overlay,
    )

    # DB wins over manifest for every editable cloud metadata field.
    assert meta["title"] == "DB Title"
    assert meta["selected_repository"] == "db/repo"
    assert meta["selected_branch"] == "feature/x"
    assert meta["labels"] == {"phase": "qa"}


def test_scanner_overlay_falls_back_to_manifest_when_db_null(tmp_path: Path):
    """Cold-upgrade window: the DB row exists but some columns are
    still NULL. Manifest values fill the gap."""
    from ohtv.db.scanner import extract_metadata

    conv_path = tmp_path / "conv"
    conv_path.mkdir()
    (conv_path / "base_state.json").write_text(
        json.dumps({"title": "Base State Title"})
    )

    db_overlay = Conversation(
        id="abc",
        location=str(conv_path),
        # Title and labels in DB; selected_branch / created_at NULL.
        title="DB Title",
        labels={"phase": "qa"},
        source="cloud",
    )
    manifest_map = {
        "conv": {
            "title": "Manifest Title",
            "labels": {"phase": "old"},
            "selected_repository": "manifest/repo",
            "selected_branch": "manifest-branch",
            "created_at": "2024-01-01T00:00:00Z",
        }
    }
    meta = extract_metadata(
        conv_path,
        source="cloud",
        manifest_map=manifest_map,
        db_overlay=db_overlay,
    )

    # DB wins where it has values.
    assert meta["title"] == "DB Title"
    assert meta["labels"] == {"phase": "qa"}
    # Manifest fills the NULL gaps.
    assert meta["selected_repository"] == "manifest/repo"
    assert meta["selected_branch"] == "manifest-branch"


# ---------------------------------------------------------------------------
# 6. Manifest dual-write contract
# ---------------------------------------------------------------------------
def test_phase_c_keeps_manifest_dual_write(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    """Phase C keeps the manifest written for one release for downgrade
    safety. The manifest entry MUST still be present after a sync."""
    fake_cloud.add(
        FakeConversation(
            id="a",
            title="My Convo",
            tags={"phase": "qa"},
            selected_repository="acme/widget",
        )
    )
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    assert "a" in manager.manifest.conversations
    entry = manager.manifest.conversations["a"]
    assert entry["title"] == "My Convo"
    assert entry["selected_repository"] == "acme/widget"
    assert entry["labels"] == {"phase": "qa"}
    # selected_branch is read from base_state.json (None when the
    # fake doesn't embed it).
    assert "selected_branch" in entry
