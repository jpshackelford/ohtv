"""Tests for migration 018: schema additions for set-diff sync (Issue #112).

Covers:

* Schema additions (table existence, column existence, indexes).
* Idempotency (re-running the migration is a no-op).
* Backward compatibility (a populated pre-018 DB upgrades without
  data loss; new columns are nullable; ``cloud_listing`` has no FK to
  ``conversations``).
* Backfill semantics for ``conversations.cloud_updated_at`` from
  ``~/.ohtv/sync_manifest.json`` — happy path, missing manifest,
  malformed manifest, dashed-id normalization, and the no-matching-row
  case.
* The schema is observable but **no consumer code reads or writes
  it** in this PR. The grep-based scope guarantee is covered by
  ``test_scope_guarantee_no_consumers``.

The test fixtures mirror ``test_contributions_migration.py`` —
in-memory DB with all migrations applied, plus a temp manifest path
patched via ``ohtv.config.get_manifest_path``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ohtv.db.migrations import (
    apply_migration,
    get_applied_migrations,
    get_pending_migrations,
    migrate,
)

MIGRATION_NAME = "018_set_diff_sync_schema.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_db() -> sqlite3.Connection:
    """In-memory DB with all migrations applied through 018."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_through_017() -> sqlite3.Connection:
    """In-memory DB with migrations applied through 017 only.

    Used to exercise the populated-DB upgrade path: seed pre-018
    state, then apply 018 manually.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # ``apply_migration`` writes to ``_migrations``; ensure the
    # tracking table exists first (matches ``migrate()`` flow).
    get_applied_migrations(conn)

    # Apply every migration that ships before 018.
    pending = [p for p in get_pending_migrations() if p.name < MIGRATION_NAME]
    for path in pending:
        apply_migration(conn, path)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def patch_manifest(monkeypatch, tmp_path: Path):
    """Patch ``ohtv.config.get_manifest_path`` to a temp file.

    Returns a helper that writes a dict as JSON to that path. Callers
    pass ``None`` to omit the file (simulating a fresh install).
    """
    manifest_path = tmp_path / "sync_manifest.json"

    monkeypatch.setattr(
        "ohtv.config.get_manifest_path",
        lambda: manifest_path,
    )

    def _write(data):
        if data is None:
            if manifest_path.exists():
                manifest_path.unlink()
            return
        manifest_path.write_text(json.dumps(data))

    return _write, manifest_path


# ---------------------------------------------------------------------------
# Schema additions
# ---------------------------------------------------------------------------


class TestSchemaAdditions:
    """Verify the three additive schema objects exist after 018."""

    def test_creates_cloud_listing_table(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cloud_listing'"
        ).fetchone()
        assert row is not None

    def test_creates_sync_kv_table(self, fresh_db):
        row = fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_kv'"
        ).fetchone()
        assert row is not None

    def test_adds_cloud_updated_at_column(self, fresh_db):
        cols = {
            r["name"] for r in fresh_db.execute("PRAGMA table_info(conversations)")
        }
        assert "cloud_updated_at" in cols

    def test_cloud_listing_columns(self, fresh_db):
        cols = {
            r["name"]: r for r in fresh_db.execute("PRAGMA table_info(cloud_listing)")
        }
        expected = {
            "conversation_id",
            "title",
            "created_at",
            "updated_at",
            "selected_repository",
            "selected_branch",
            "git_provider",
            "trigger",
            "parent_conversation_id",
            "tags",
            "sub_conversation_ids",
            "pr_number",
            "fetched_at",
            "snapshot_id",
        }
        assert set(cols) == expected
        # conversation_id is the primary key.
        assert cols["conversation_id"]["pk"] == 1
        # fetched_at and snapshot_id are NOT NULL.
        assert cols["fetched_at"]["notnull"] == 1
        assert cols["snapshot_id"]["notnull"] == 1
        # All cloud-payload fields nullable.
        for nullable in (
            "title",
            "created_at",
            "updated_at",
            "selected_repository",
            "selected_branch",
            "git_provider",
            "trigger",
            "parent_conversation_id",
            "tags",
            "sub_conversation_ids",
            "pr_number",
        ):
            assert cols[nullable]["notnull"] == 0, nullable

    def test_sync_kv_columns(self, fresh_db):
        cols = {r["name"]: r for r in fresh_db.execute("PRAGMA table_info(sync_kv)")}
        assert set(cols) == {"key", "value", "updated_at"}
        assert cols["key"]["pk"] == 1
        assert cols["updated_at"]["notnull"] == 1
        # value is JSON-encoded scalar/struct; nullable so callers can
        # store explicit nulls.
        assert cols["value"]["notnull"] == 0

    def test_creates_indexes(self, fresh_db):
        idx = {
            r[0]
            for r in fresh_db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_cloud_listing_updated_at" in idx
        assert "idx_cloud_listing_snapshot" in idx
        assert "idx_conversations_cloud_updated_at" in idx


# ---------------------------------------------------------------------------
# Backwards-compatibility / additive-only
# ---------------------------------------------------------------------------


class TestAdditiveOnly:
    """The migration must not break pre-018 callers."""

    def test_cloud_listing_has_no_fk_to_conversations(self, fresh_db):
        """Cloud-only rows must be representable — no FK on conversation_id."""
        fks = fresh_db.execute("PRAGMA foreign_key_list(cloud_listing)").fetchall()
        assert fks == []

        # Insert a row whose id has NO matching conversations row.
        # If a hidden FK existed this would IntegrityError.
        fresh_db.execute(
            """
            INSERT INTO cloud_listing
                (conversation_id, fetched_at, snapshot_id)
            VALUES (?, ?, ?)
            """,
            ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "2026-05-27T00:00:00Z", "snap-1"),
        )
        fresh_db.commit()
        assert (
            fresh_db.execute("SELECT COUNT(*) FROM cloud_listing").fetchone()[0] == 1
        )

    def test_cloud_updated_at_nullable(self, fresh_db):
        """Existing INSERTs against conversations must keep working."""
        fresh_db.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv1", "/tmp/conv1"),
        )
        fresh_db.commit()
        row = fresh_db.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("conv1",),
        ).fetchone()
        assert row["cloud_updated_at"] is None

    def test_sync_kv_pk_uniqueness(self, fresh_db):
        fresh_db.execute(
            "INSERT INTO sync_kv (key, value, updated_at) VALUES (?, ?, ?)",
            ("k1", '"v1"', "2026-05-27T00:00:00Z"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute(
                "INSERT INTO sync_kv (key, value, updated_at) VALUES (?, ?, ?)",
                ("k1", '"v2"', "2026-05-27T00:00:01Z"),
            )

    def test_populated_db_upgrade_preserves_data(self, db_through_017):
        """Apply 018 to a DB with pre-existing conversations rows."""
        # Seed a row using only pre-018 columns.
        db_through_017.execute(
            """
            INSERT INTO conversations
                (id, location, title, created_at, updated_at, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "abcdef1234567890abcdef1234567890",
                "/tmp/abc",
                "Pre-018 row",
                "2026-05-20T00:00:00Z",
                "2026-05-21T00:00:00Z",
                "cloud",
            ),
        )
        db_through_017.commit()

        # Apply 018.
        migration_path = next(
            p for p in get_pending_migrations() if p.name == MIGRATION_NAME
        )
        apply_migration(db_through_017, migration_path)
        db_through_017.commit()

        # Pre-018 row survived unchanged.
        row = db_through_017.execute(
            "SELECT title, created_at, updated_at, source, cloud_updated_at "
            "FROM conversations WHERE id = ?",
            ("abcdef1234567890abcdef1234567890",),
        ).fetchone()
        assert row["title"] == "Pre-018 row"
        assert row["updated_at"] == "2026-05-21T00:00:00Z"
        assert row["source"] == "cloud"
        # New column defaults to NULL (manifest absent in this fixture).
        assert row["cloud_updated_at"] is None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_migrate_records_018_once(self):
        conn = sqlite3.connect(":memory:")
        try:
            first = migrate(conn)
            assert MIGRATION_NAME in first
            second = migrate(conn)
            assert MIGRATION_NAME not in second
            assert second == []
            # Recorded exactly once.
            applied = get_applied_migrations(conn)
            assert MIGRATION_NAME in applied
        finally:
            conn.close()

    def test_re_running_upgrade_is_no_op(self, fresh_db):
        """Even if a future loader re-invokes upgrade() directly, the
        ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``
        / PRAGMA-guarded ALTER TABLE pattern must not raise."""
        # Re-invoke upgrade() directly. This simulates a tool that
        # might call the module's upgrade() function outside the
        # migrate() loop.
        from ohtv.db.migrations import MIGRATIONS_DIR
        import importlib.util

        path = MIGRATIONS_DIR / MIGRATION_NAME
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # First re-invocation.
        module.upgrade(fresh_db)
        # Second re-invocation.
        module.upgrade(fresh_db)

        # State unchanged.
        cols = {
            r["name"] for r in fresh_db.execute("PRAGMA table_info(conversations)")
        }
        assert "cloud_updated_at" in cols
        # Only one cloud_updated_at column (no duplicates).
        cloud_cols = [
            r["name"]
            for r in fresh_db.execute("PRAGMA table_info(conversations)")
            if r["name"] == "cloud_updated_at"
        ]
        assert len(cloud_cols) == 1


# ---------------------------------------------------------------------------
# Backfill semantics
# ---------------------------------------------------------------------------


class TestBackfill:
    """Backfill of ``conversations.cloud_updated_at`` from manifest."""

    def _seed_and_apply(
        self,
        db_through_017: sqlite3.Connection,
        rows: list[tuple[str, str | None]],
    ) -> sqlite3.Connection:
        """Seed conversations and apply 018. Returns the same conn."""
        for conv_id, _ in rows:
            db_through_017.execute(
                "INSERT INTO conversations (id, location) VALUES (?, ?)",
                (conv_id, f"/tmp/{conv_id}"),
            )
        db_through_017.commit()
        migration_path = next(
            p for p in get_pending_migrations() if p.name == MIGRATION_NAME
        )
        apply_migration(db_through_017, migration_path)
        db_through_017.commit()
        return db_through_017

    def test_backfill_happy_path(self, db_through_017, patch_manifest):
        write, _ = patch_manifest
        write(
            {
                "last_sync_at": "2026-05-26T12:00:00Z",
                "sync_count": 7,
                "conversations": {
                    "11111111111111111111111111111111": {
                        "title": "A",
                        "updated_at": "2026-05-20T10:00:00Z",
                        "event_count": 5,
                    },
                    "22222222222222222222222222222222": {
                        "title": "B",
                        "updated_at": "2026-05-21T11:00:00Z",
                    },
                },
                "failed_ids": [],
            }
        )
        conn = self._seed_and_apply(
            db_through_017,
            [
                ("11111111111111111111111111111111", "x"),
                ("22222222222222222222222222222222", "x"),
            ],
        )
        rows = {
            r["id"]: r["cloud_updated_at"]
            for r in conn.execute(
                "SELECT id, cloud_updated_at FROM conversations"
            )
        }
        assert rows["11111111111111111111111111111111"] == "2026-05-20T10:00:00Z"
        assert rows["22222222222222222222222222222222"] == "2026-05-21T11:00:00Z"

    def test_backfill_no_manifest_is_noop(self, db_through_017, patch_manifest):
        """Missing manifest file leaves the column NULL without raising."""
        write, _ = patch_manifest
        write(None)
        conn = self._seed_and_apply(
            db_through_017, [("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "x")]
        )
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
        ).fetchone()
        assert row["cloud_updated_at"] is None

    def test_backfill_malformed_manifest_is_noop(
        self, db_through_017, patch_manifest
    ):
        """Garbage JSON leaves the column NULL without raising."""
        _, manifest_path = patch_manifest
        manifest_path.write_text("{not-valid-json")
        conn = self._seed_and_apply(
            db_through_017, [("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "x")]
        )
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",),
        ).fetchone()
        assert row["cloud_updated_at"] is None

    def test_backfill_non_object_manifest_is_noop(
        self, db_through_017, patch_manifest
    ):
        """A JSON array at the top level is gracefully ignored."""
        _, manifest_path = patch_manifest
        manifest_path.write_text(json.dumps(["not", "an", "object"]))
        conn = self._seed_and_apply(
            db_through_017, [("cccccccccccccccccccccccccccccccc", "x")]
        )
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("cccccccccccccccccccccccccccccccc",),
        ).fetchone()
        assert row["cloud_updated_at"] is None

    def test_backfill_missing_conversations_key(
        self, db_through_017, patch_manifest
    ):
        """Manifest without 'conversations' key leaves column NULL."""
        write, _ = patch_manifest
        write({"last_sync_at": "2026-01-01T00:00:00Z", "sync_count": 1})
        conn = self._seed_and_apply(
            db_through_017, [("dddddddddddddddddddddddddddddddd", "x")]
        )
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("dddddddddddddddddddddddddddddddd",),
        ).fetchone()
        assert row["cloud_updated_at"] is None

    def test_backfill_normalizes_dashed_manifest_ids(
        self, db_through_017, patch_manifest
    ):
        """Manifest id with dashes matches dashless conversation id."""
        write, _ = patch_manifest
        dashed = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        dashless = dashed.replace("-", "")
        write(
            {
                "conversations": {
                    dashed: {"updated_at": "2026-05-22T09:00:00Z"},
                }
            }
        )
        conn = self._seed_and_apply(db_through_017, [(dashless, "x")])
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            (dashless,),
        ).fetchone()
        assert row["cloud_updated_at"] == "2026-05-22T09:00:00Z"

    def test_backfill_skips_entries_without_updated_at(
        self, db_through_017, patch_manifest
    ):
        write, _ = patch_manifest
        write(
            {
                "conversations": {
                    "ffffffffffffffffffffffffffffffff": {"title": "no updated_at"},
                    "00000000000000000000000000000001": {"updated_at": ""},
                    "00000000000000000000000000000002": {"updated_at": None},
                    "00000000000000000000000000000003": {"updated_at": 42},
                    "00000000000000000000000000000004": "not a dict",
                    "00000000000000000000000000000005": {
                        "updated_at": "2026-05-23T08:00:00Z"
                    },
                }
            }
        )
        conn = self._seed_and_apply(
            db_through_017,
            [
                ("ffffffffffffffffffffffffffffffff", "x"),
                ("00000000000000000000000000000001", "x"),
                ("00000000000000000000000000000002", "x"),
                ("00000000000000000000000000000003", "x"),
                ("00000000000000000000000000000004", "x"),
                ("00000000000000000000000000000005", "x"),
            ],
        )
        rows = {
            r["id"]: r["cloud_updated_at"]
            for r in conn.execute(
                "SELECT id, cloud_updated_at FROM conversations"
            )
        }
        # Only the well-formed entry was written.
        assert rows["00000000000000000000000000000005"] == "2026-05-23T08:00:00Z"
        for null_id in (
            "ffffffffffffffffffffffffffffffff",
            "00000000000000000000000000000001",
            "00000000000000000000000000000002",
            "00000000000000000000000000000003",
            "00000000000000000000000000000004",
        ):
            assert rows[null_id] is None, null_id

    def test_backfill_all_entries_unusable_takes_short_circuit(
        self, db_through_017, patch_manifest
    ):
        """Manifest with a 'conversations' key but no usable entries
        hits the early-return shortcut without issuing an UPDATE."""
        write, _ = patch_manifest
        write(
            {
                "conversations": {
                    "00000000000000000000000000000099": {"title": "no updated_at"},
                    "0000000000000000000000000000aaaa": {"updated_at": ""},
                }
            }
        )
        conn = self._seed_and_apply(
            db_through_017,
            [("00000000000000000000000000000099", "x")],
        )
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("00000000000000000000000000000099",),
        ).fetchone()
        assert row["cloud_updated_at"] is None

    def test_backfill_skips_empty_normalized_id(
        self, db_through_017, patch_manifest
    ):
        """An id consisting only of dashes normalizes to empty and is
        skipped rather than producing a degenerate UPDATE."""
        write, _ = patch_manifest
        write(
            {
                "conversations": {
                    # All-dashes id; normalizes to "".
                    "------------------------------------": {
                        "updated_at": "2026-05-27T00:00:00Z"
                    },
                    # A legitimate entry so the function reaches the
                    # UPDATE — and the skipped entry above is the only
                    # thing that would corrupt it.
                    "bcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbc": {
                        "updated_at": "2026-05-27T01:00:00Z"
                    },
                }
            }
        )
        conn = self._seed_and_apply(
            db_through_017,
            [("bcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbc", "x")],
        )
        row = conn.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("bcbcbcbcbcbcbcbcbcbcbcbcbcbcbcbc",),
        ).fetchone()
        assert row["cloud_updated_at"] == "2026-05-27T01:00:00Z"
        # And no row was created for the all-dashes id (would also
        # round-trip to empty string which won't match anything).
        empty_row = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE id = ?",
            ("",),
        ).fetchone()
        assert empty_row[0] == 0

    def test_backfill_no_matching_db_row(self, db_through_017, patch_manifest):
        """Manifest entries with no DB row are silently skipped."""
        write, _ = patch_manifest
        write(
            {
                "conversations": {
                    "9999999999999999999999999999dead": {
                        "updated_at": "2026-05-24T07:00:00Z"
                    }
                }
            }
        )
        # No conversations seeded — empty table.
        migration_path = next(
            p for p in get_pending_migrations() if p.name == MIGRATION_NAME
        )
        apply_migration(db_through_017, migration_path)
        db_through_017.commit()
        # Backfill did not insert any row.
        assert (
            db_through_017.execute(
                "SELECT COUNT(*) FROM conversations"
            ).fetchone()[0]
            == 0
        )

    def test_backfill_runs_only_once_via_migrate(
        self, db_through_017, patch_manifest
    ):
        """``migrate()`` invokes 018 exactly once; backfill therefore
        runs once. Re-running ``migrate()`` (the actual idempotency
        path) does not re-write."""
        write, _ = patch_manifest
        write(
            {
                "conversations": {
                    "abababababababababababababababab": {
                        "updated_at": "2026-05-25T06:00:00Z"
                    }
                }
            }
        )
        self._seed_and_apply(
            db_through_017, [("abababababababababababababababab", "x")]
        )
        # Externally clear the column to detect any re-backfill.
        db_through_017.execute(
            "UPDATE conversations SET cloud_updated_at = NULL WHERE id = ?",
            ("abababababababababababababababab",),
        )
        db_through_017.commit()
        # Re-run migrate — should be a no-op because 018 is already
        # recorded.
        applied = migrate(db_through_017)
        assert MIGRATION_NAME not in applied
        row = db_through_017.execute(
            "SELECT cloud_updated_at FROM conversations WHERE id = ?",
            ("abababababababababababababababab",),
        ).fetchone()
        # Backfill did NOT re-run, so the cleared value stays NULL.
        assert row["cloud_updated_at"] is None


# ---------------------------------------------------------------------------
# Scope guarantee
# ---------------------------------------------------------------------------


class TestScopeGuarantee:
    """Migration 018 schema is now consumed by #111.

    This class previously enforced that no production code touched
    ``cloud_listing`` / ``sync_kv`` / ``conversations.cloud_updated_at``
    until the set-diff engine landed. With Issue #111 merged the
    schema has legitimate consumers — :mod:`ohtv.db.stores.cloud_listing_store`,
    :mod:`ohtv.db.stores.sync_state_store`, the
    :meth:`ConversationStore.record_cloud_download` method, and the
    :meth:`SyncManager.sync` engine itself.

    The class is intentionally left in place (rather than deleted) as
    a marker that the scope-guarantee invariant was retired by #111.
    """

    def test_schema_is_consumed_by_issue_111(self):
        """The #112 schema now has at least one production consumer."""
        from ohtv.db.stores import CloudListingStore, SyncStateStore  # noqa: F401
