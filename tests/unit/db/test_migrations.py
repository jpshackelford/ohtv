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
