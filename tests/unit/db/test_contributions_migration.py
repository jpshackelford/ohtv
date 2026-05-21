"""Unit tests for contribution tracking migration (016_contributions.py).

Tests that:
- All three tables are created with correct schema
- Foreign key constraints are enforced
- Unique constraints prevent duplicates
- CHECK constraints validate data
- Migration is idempotent
"""

import sqlite3
from datetime import datetime

import pytest

from ohtv.db.migrations import migrate


@pytest.fixture
def db_with_contributions():
    """Fresh in-memory database with all migrations including contributions."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    yield conn
    conn.close()


class TestContributionsMigrationTablesCreated:
    """Tests that migration creates all required tables."""

    def test_creates_change_refs_table(self, db_with_contributions):
        """change_refs table should exist after migration."""
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='change_refs'"
        )
        assert cursor.fetchone() is not None

    def test_creates_conversation_contributions_table(self, db_with_contributions):
        """conversation_contributions table should exist after migration."""
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_contributions'"
        )
        assert cursor.fetchone() is not None

    def test_creates_conversation_human_input_table(self, db_with_contributions):
        """conversation_human_input table should exist after migration."""
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_human_input'"
        )
        assert cursor.fetchone() is not None


class TestChangeRefsSchema:
    """Tests for change_refs table schema."""

    def test_has_expected_columns(self, db_with_contributions):
        """change_refs should have all required columns."""
        cursor = db_with_contributions.execute("PRAGMA table_info(change_refs)")
        columns = {row["name"] for row in cursor.fetchall()}
        expected = {
            "id", "repo_id", "change_type", "pr_number", "commit_range",
            "branch", "status", "merged_at", "lines_added", "lines_removed",
            "files_changed", "fetched_at"
        }
        assert expected == columns

    def test_change_type_check_constraint_pr(self, db_with_contributions):
        """change_type should accept 'pr'."""
        # First create a repo to satisfy foreign key
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert with 'pr' should work
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        db_with_contributions.commit()

    def test_change_type_check_constraint_direct_push(self, db_with_contributions):
        """change_type should accept 'direct_push'."""
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "direct_push", "pending")
        )
        db_with_contributions.commit()

    def test_change_type_check_constraint_invalid(self, db_with_contributions):
        """change_type should reject invalid values."""
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
                (repo_id, "invalid_type", "pending")
            )

    def test_repo_foreign_key_constraint(self, db_with_contributions):
        """change_refs should enforce foreign key to repositories."""
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
                (99999, "pr", "pending")
            )

    def test_unique_constraint_with_pr_number(self, db_with_contributions):
        """change_refs should enforce unique (repo_id, change_type, pr_number, commit_range) for PRs."""
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # First insert should succeed - PR 42 with specific commit_range
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, pr_number, commit_range, status) VALUES (?, ?, ?, ?, ?)",
            (repo_id, "pr", 42, "abc123..def456", "pending")
        )
        db_with_contributions.commit()

        # Duplicate with same commit_range should fail
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO change_refs (repo_id, change_type, pr_number, commit_range, status) VALUES (?, ?, ?, ?, ?)",
                (repo_id, "pr", 42, "abc123..def456", "merged")
            )

    def test_unique_constraint_allows_different_prs(self, db_with_contributions):
        """change_refs should allow different PRs for same repo."""
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert PR 42
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, pr_number, commit_range, status) VALUES (?, ?, ?, ?, ?)",
            (repo_id, "pr", 42, "abc123..def456", "pending")
        )
        # Insert PR 43 - should work
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, pr_number, commit_range, status) VALUES (?, ?, ?, ?, ?)",
            (repo_id, "pr", 43, "abc123..def456", "pending")
        )
        db_with_contributions.commit()

        cursor = db_with_contributions.execute("SELECT COUNT(*) FROM change_refs WHERE repo_id = ?", (repo_id,))
        assert cursor.fetchone()[0] == 2

    def test_unique_constraint_null_handling(self, db_with_contributions):
        """change_refs unique constraint: NULLs in pr_number/commit_range are treated as distinct by SQLite."""
        # This documents SQLite's behavior: NULL values are considered distinct in unique constraints
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert with NULL pr_number and commit_range
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        # Second insert with NULLs - SQLite treats NULLs as distinct, so this works
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "merged")
        )
        db_with_contributions.commit()

        # Both inserts succeeded because NULLs are treated as distinct
        cursor = db_with_contributions.execute("SELECT COUNT(*) FROM change_refs WHERE repo_id = ?", (repo_id,))
        assert cursor.fetchone()[0] == 2

    def test_default_status(self, db_with_contributions):
        """status should default to 'pending'."""
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type) VALUES (?, ?)",
            (repo_id, "pr")
        )
        db_with_contributions.commit()

        cursor = db_with_contributions.execute(
            "SELECT status FROM change_refs WHERE repo_id = ?", (repo_id,)
        )
        assert cursor.fetchone()["status"] == "pending"


class TestConversationContributionsSchema:
    """Tests for conversation_contributions table schema."""

    def test_has_expected_columns(self, db_with_contributions):
        """conversation_contributions should have all required columns."""
        cursor = db_with_contributions.execute("PRAGMA table_info(conversation_contributions)")
        columns = {row["name"] for row in cursor.fetchall()}
        expected = {"id", "conversation_id", "change_ref_id", "contribution_type"}
        assert expected == columns

    def test_contribution_type_check_constraint_created(self, db_with_contributions):
        """contribution_type should accept 'created'."""
        # Set up required foreign key records
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "created")
        )
        db_with_contributions.commit()

    def test_contribution_type_check_constraint_pushed(self, db_with_contributions):
        """contribution_type should accept 'pushed'."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "pushed")
        )
        db_with_contributions.commit()

    def test_contribution_type_check_constraint_merged(self, db_with_contributions):
        """contribution_type should accept 'merged'."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "merged")
        )
        db_with_contributions.commit()

    def test_contribution_type_check_constraint_invalid(self, db_with_contributions):
        """contribution_type should reject invalid values."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
                ("conv123", change_ref_id, "invalid_type")
            )

    def test_conversation_foreign_key_constraint(self, db_with_contributions):
        """conversation_contributions should enforce foreign key to conversations."""
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
                ("nonexistent_conv", change_ref_id, "created")
            )

    def test_change_ref_foreign_key_constraint(self, db_with_contributions):
        """conversation_contributions should enforce foreign key to change_refs."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
                ("conv123", 99999, "created")
            )

    def test_unique_constraint(self, db_with_contributions):
        """conversation_contributions should enforce unique (conversation_id, change_ref_id, contribution_type)."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # First insert should succeed
        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "created")
        )
        db_with_contributions.commit()

        # Duplicate should fail
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            db_with_contributions.execute(
                "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
                ("conv123", change_ref_id, "created")
            )

    def test_same_conversation_different_contribution_types_allowed(self, db_with_contributions):
        """Same conversation can have different contribution types for same change_ref."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, status) VALUES (?, ?, ?)",
            (repo_id, "pr", "pending")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Multiple contribution types for same (conversation, change_ref) should work
        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "created")
        )
        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "pushed")
        )
        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv123", change_ref_id, "merged")
        )
        db_with_contributions.commit()

        cursor = db_with_contributions.execute(
            "SELECT COUNT(*) FROM conversation_contributions WHERE conversation_id = ?",
            ("conv123",)
        )
        assert cursor.fetchone()[0] == 3


class TestConversationHumanInputSchema:
    """Tests for conversation_human_input table schema."""

    def test_has_expected_columns(self, db_with_contributions):
        """conversation_human_input should have all required columns."""
        cursor = db_with_contributions.execute("PRAGMA table_info(conversation_human_input)")
        columns = {row["name"] for row in cursor.fetchall()}
        expected = {
            "conversation_id", "initial_prompt_words", "initial_prompt_source",
            "followup_word_count", "followup_message_count", "processed_at", "event_count"
        }
        assert expected == columns

    def test_conversation_id_is_primary_key(self, db_with_contributions):
        """conversation_id should be the primary key."""
        cursor = db_with_contributions.execute("PRAGMA table_info(conversation_human_input)")
        for row in cursor.fetchall():
            if row["name"] == "conversation_id":
                assert row["pk"] == 1
                break
        else:
            pytest.fail("conversation_id not found")

    def test_initial_prompt_source_check_constraint_human(self, db_with_contributions):
        """initial_prompt_source should accept 'human'."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute("""
            INSERT INTO conversation_human_input (
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count, processed_at, event_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("conv123", 100, "human", 50, 3, datetime.now().isoformat(), 10))
        db_with_contributions.commit()

    def test_initial_prompt_source_check_constraint_automation(self, db_with_contributions):
        """initial_prompt_source should accept 'automation'."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute("""
            INSERT INTO conversation_human_input (
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count, processed_at, event_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("conv123", 100, "automation", 50, 3, datetime.now().isoformat(), 10))
        db_with_contributions.commit()

    def test_initial_prompt_source_check_constraint_unknown(self, db_with_contributions):
        """initial_prompt_source should accept 'unknown'."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        db_with_contributions.execute("""
            INSERT INTO conversation_human_input (
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count, processed_at, event_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("conv123", 100, "unknown", 50, 3, datetime.now().isoformat(), 10))
        db_with_contributions.commit()

    def test_initial_prompt_source_check_constraint_invalid(self, db_with_contributions):
        """initial_prompt_source should reject invalid values."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            db_with_contributions.execute("""
                INSERT INTO conversation_human_input (
                    conversation_id, initial_prompt_words, initial_prompt_source,
                    followup_word_count, followup_message_count, processed_at, event_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("conv123", 100, "invalid_source", 50, 3, datetime.now().isoformat(), 10))

    def test_conversation_foreign_key_constraint(self, db_with_contributions):
        """conversation_human_input should enforce foreign key to conversations."""
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            db_with_contributions.execute("""
                INSERT INTO conversation_human_input (
                    conversation_id, initial_prompt_words, initial_prompt_source,
                    followup_word_count, followup_message_count, processed_at, event_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("nonexistent_conv", 100, "human", 50, 3, datetime.now().isoformat(), 10))

    def test_default_values(self, db_with_contributions):
        """Columns should have correct default values."""
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv123", "/path/to/conv")
        )
        # Insert with only required columns
        db_with_contributions.execute("""
            INSERT INTO conversation_human_input (
                conversation_id, processed_at, event_count
            ) VALUES (?, ?, ?)
        """, ("conv123", datetime.now().isoformat(), 10))
        db_with_contributions.commit()

        cursor = db_with_contributions.execute(
            "SELECT initial_prompt_words, initial_prompt_source, followup_word_count, followup_message_count FROM conversation_human_input WHERE conversation_id = ?",
            ("conv123",)
        )
        row = cursor.fetchone()
        assert row["initial_prompt_words"] == 0
        assert row["initial_prompt_source"] == "unknown"
        assert row["followup_word_count"] == 0
        assert row["followup_message_count"] == 0


class TestMigrationIdempotency:
    """Tests that migration can run multiple times safely."""

    def test_migration_is_idempotent(self):
        """Running migration multiple times should not cause errors."""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")

        # First run
        first_applied = migrate(conn)
        assert "016_contributions.py" in first_applied

        # Second run should apply no new migrations
        second_applied = migrate(conn)
        assert "016_contributions.py" not in second_applied
        assert len(second_applied) == 0

        conn.close()


class TestIndexesCreated:
    """Tests that appropriate indexes are created."""

    def test_change_refs_indexes(self, db_with_contributions):
        """change_refs should have indexes on repo_id, change_type, status."""
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='change_refs'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_change_refs_repo" in indexes
        assert "idx_change_refs_type" in indexes
        assert "idx_change_refs_status" in indexes

    def test_conversation_contributions_indexes(self, db_with_contributions):
        """conversation_contributions should have indexes on conversation_id, change_ref_id."""
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='conversation_contributions'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_conv_contributions_conv" in indexes
        assert "idx_conv_contributions_change" in indexes

    def test_conversation_human_input_indexes(self, db_with_contributions):
        """conversation_human_input should have index on initial_prompt_source."""
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='conversation_human_input'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_human_input_source" in indexes


class TestIntegrationWithExistingData:
    """Integration tests with existing data in the database."""

    def test_migration_works_with_existing_conversations(self, db_with_contributions):
        """Migration should work on database with existing conversations."""
        # Add some conversations first
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv1", "/path/to/conv1")
        )
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv2", "/path/to/conv2")
        )
        db_with_contributions.commit()

        # Migration should have already run from fixture, verify tables exist
        cursor = db_with_contributions.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='change_refs'"
        )
        assert cursor.fetchone() is not None

    def test_can_link_existing_conversations_to_changes(self, db_with_contributions):
        """Should be able to create contribution links for existing conversations."""
        # Setup: existing conversation and repo
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv_existing", "/path/to/conv")
        )
        db_with_contributions.execute(
            "INSERT INTO repositories (canonical_url, fqn, short_name) VALUES (?, ?, ?)",
            ("https://github.com/test/repo", "test/repo", "repo")
        )
        repo_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Create a change_ref
        db_with_contributions.execute(
            "INSERT INTO change_refs (repo_id, change_type, pr_number, status) VALUES (?, ?, ?, ?)",
            (repo_id, "pr", 42, "merged")
        )
        change_ref_id = db_with_contributions.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Link conversation to change
        db_with_contributions.execute(
            "INSERT INTO conversation_contributions (conversation_id, change_ref_id, contribution_type) VALUES (?, ?, ?)",
            ("conv_existing", change_ref_id, "created")
        )
        db_with_contributions.commit()

        # Verify the link exists
        cursor = db_with_contributions.execute(
            "SELECT * FROM conversation_contributions WHERE conversation_id = ?",
            ("conv_existing",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["change_ref_id"] == change_ref_id
        assert row["contribution_type"] == "created"

    def test_can_track_human_input_for_existing_conversations(self, db_with_contributions):
        """Should be able to track human input for existing conversations."""
        # Setup: existing conversation
        db_with_contributions.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv_existing", "/path/to/conv")
        )

        # Track human input
        db_with_contributions.execute("""
            INSERT INTO conversation_human_input (
                conversation_id, initial_prompt_words, initial_prompt_source,
                followup_word_count, followup_message_count, processed_at, event_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("conv_existing", 150, "human", 75, 5, datetime.now().isoformat(), 20))
        db_with_contributions.commit()

        # Verify the data
        cursor = db_with_contributions.execute(
            "SELECT * FROM conversation_human_input WHERE conversation_id = ?",
            ("conv_existing",)
        )
        row = cursor.fetchone()
        assert row["initial_prompt_words"] == 150
        assert row["initial_prompt_source"] == "human"
        assert row["followup_word_count"] == 75
        assert row["followup_message_count"] == 5
