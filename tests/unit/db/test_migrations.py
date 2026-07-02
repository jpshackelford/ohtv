"""Unit tests for database migrations."""

import sqlite3

from ohtv.db.migrations import get_applied_migrations, get_pending_migrations, migrate


class TestMigrate:
    """Tests for the migrate() function."""

    def test_applies_migrations_to_empty_database(self):
        conn = sqlite3.connect(":memory:")
        
        applied = migrate(conn)
        
        assert len(applied) > 0
        assert "001_initial_schema.py" in applied

    def test_creates_migrations_tracking_table(self):
        conn = sqlite3.connect(":memory:")
        
        migrate(conn)
        
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_migrations'"
        )
        assert cursor.fetchone() is not None

    def test_records_applied_migrations(self):
        conn = sqlite3.connect(":memory:")
        
        migrate(conn)
        
        applied = get_applied_migrations(conn)
        assert "001_initial_schema.py" in applied

    def test_is_idempotent(self):
        conn = sqlite3.connect(":memory:")
        
        first_run = migrate(conn)
        second_run = migrate(conn)
        
        assert len(first_run) > 0
        assert len(second_run) == 0

    def test_creates_expected_tables(self):
        conn = sqlite3.connect(":memory:")
        
        migrate(conn)
        
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        
        expected = {"_migrations", "conversations", "repositories", "refs", 
                    "conversation_repos", "conversation_refs", "sqlite_sequence"}
        assert expected.issubset(tables)
    
    def test_migration_026_creates_synthesis_table(self):
        """Test that migration 026 creates conversation_synthesis table (Issue #191)."""
        conn = sqlite3.connect(":memory:")
        
        migrate(conn)
        
        # Verify table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_synthesis'"
        )
        assert cursor.fetchone() is not None
        
        # Verify table schema has expected columns
        cursor = conn.execute("PRAGMA table_info(conversation_synthesis)")
        columns = {row[1] for row in cursor.fetchall()}
        
        expected_columns = {
            "conversation_id",
            "conversation_updated_at",
            "synthesized_title",
            "synthesized_objective",
            "worklog_purpose",
            "synthesis_model",
            "synthesis_version",
            "synthesized_at",
            "tokens_used",
        }
        assert expected_columns.issubset(columns)
        
        # Verify indexes exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='conversation_synthesis'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        
        expected_indexes = {"idx_synthesis_updated", "idx_synthesis_model"}
        assert expected_indexes.issubset(indexes)


class TestGetPendingMigrations:
    """Tests for get_pending_migrations()."""

    def test_returns_migration_files(self):
        migrations = get_pending_migrations()
        
        assert len(migrations) > 0
        assert all(m.suffix == ".py" for m in migrations)

    def test_returns_migrations_in_order(self):
        migrations = get_pending_migrations()
        
        names = [m.name for m in migrations]
        assert names == sorted(names)
