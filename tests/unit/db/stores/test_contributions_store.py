"""Tests for ContributionsStore."""

from __future__ import annotations

import sqlite3

import pytest

from ohtv.db.migrations import migrate
from ohtv.db.models import Repository
from ohtv.db.stores import ContributionsStore, RepoStore


@pytest.fixture
def db_conn():
    """Create an in-memory database with all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo_id(db_conn) -> int:
    """Insert a repo and return its id for use in change_refs."""
    return RepoStore(db_conn).upsert(
        Repository(
            id=None,
            canonical_url="https://github.com/acme/widgets",
            fqn="acme/widgets",
            short_name="widgets",
        )
    )


@pytest.fixture
def conversation_id(db_conn) -> str:
    """Insert a conversation row so FK constraints are satisfied."""
    conv_id = "conv-1"
    db_conn.execute(
        "INSERT INTO conversations (id, location) VALUES (?, ?)",
        (conv_id, "/tmp/conv-1"),
    )
    return conv_id


# ---------------------------------------------------------------------------
# get_or_create_pr_change_ref
# ---------------------------------------------------------------------------


class TestGetOrCreatePrChangeRef:
    def test_creates_new_pr(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 42, branch="feature/x")

        change_ref = store.get_change_ref(cr_id)
        assert change_ref is not None
        assert change_ref.repo_id == repo_id
        assert change_ref.change_type == "pr"
        assert change_ref.pr_number == 42
        assert change_ref.branch == "feature/x"
        assert change_ref.status == "pending"
        assert change_ref.commit_range is None

    def test_get_change_ref_returns_none_for_missing_id(self, db_conn):
        store = ContributionsStore(db_conn)
        assert store.get_change_ref(99999) is None

    def test_returns_existing_pr_without_duplicating(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        first = store.get_or_create_pr_change_ref(repo_id, 42, branch="feature/x")
        second = store.get_or_create_pr_change_ref(repo_id, 42, branch="ignored")
        assert first == second

        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM change_refs WHERE repo_id = ? AND pr_number = ?",
            (repo_id, 42),
        )
        assert cursor.fetchone()[0] == 1

    def test_existing_pr_branch_is_not_overwritten(self, db_conn, repo_id):
        """Calling again with a different branch must not change the stored branch.

        Branch is only set on creation - this keeps an external fetcher
        free to populate it without us clobbering on the next replay.
        """
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 7, branch="orig")
        store.get_or_create_pr_change_ref(repo_id, 7, branch="rewritten")

        change_ref = store.get_change_ref(cr_id)
        assert change_ref is not None
        assert change_ref.branch == "orig"

    def test_different_pr_numbers_create_different_rows(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        a = store.get_or_create_pr_change_ref(repo_id, 1)
        b = store.get_or_create_pr_change_ref(repo_id, 2)
        assert a != b

    def test_different_repos_with_same_pr_number_create_different_rows(
        self, db_conn, repo_id
    ):
        other_repo_id = RepoStore(db_conn).upsert(
            Repository(
                id=None,
                canonical_url="https://github.com/acme/gadgets",
                fqn="acme/gadgets",
                short_name="gadgets",
            )
        )
        store = ContributionsStore(db_conn)
        a = store.get_or_create_pr_change_ref(repo_id, 42)
        b = store.get_or_create_pr_change_ref(other_repo_id, 42)
        assert a != b


# ---------------------------------------------------------------------------
# get_or_create_direct_push_change_ref
# ---------------------------------------------------------------------------


class TestGetOrCreateDirectPushChangeRef:
    def test_creates_new_direct_push(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_direct_push_change_ref(
            repo_id, "abc123..def456", branch="main"
        )

        change_ref = store.get_change_ref(cr_id)
        assert change_ref is not None
        assert change_ref.change_type == "direct_push"
        assert change_ref.commit_range == "abc123..def456"
        assert change_ref.branch == "main"
        assert change_ref.pr_number is None
        assert change_ref.status == "pending"

    def test_returns_existing_direct_push(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        a = store.get_or_create_direct_push_change_ref(repo_id, "abc..def")
        b = store.get_or_create_direct_push_change_ref(repo_id, "abc..def")
        assert a == b

    def test_pr_and_direct_push_with_same_repo_are_independent(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        pr = store.get_or_create_pr_change_ref(repo_id, 1)
        push = store.get_or_create_direct_push_change_ref(repo_id, "aaa..bbb")
        assert pr != push

    def test_creates_with_explicit_status_merged(self, db_conn, repo_id):
        """Direct-push detection (#79) creates change_refs with status='merged'."""
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_direct_push_change_ref(
            repo_id, "abc..def", branch="main", status="merged"
        )
        change_ref = store.get_change_ref(cr_id)
        assert change_ref is not None
        assert change_ref.status == "merged"

    def test_status_preserved_across_dedup_lookup(self, db_conn, repo_id):
        """Re-calling with a different status returns the existing row unchanged."""
        store = ContributionsStore(db_conn)
        first = store.get_or_create_direct_push_change_ref(
            repo_id, "abc..def", status="merged"
        )
        second = store.get_or_create_direct_push_change_ref(
            repo_id, "abc..def", status="pending"
        )
        assert first == second
        change_ref = store.get_change_ref(first)
        assert change_ref is not None
        # First insert wins: status stays 'merged'.
        assert change_ref.status == "merged"


# ---------------------------------------------------------------------------
# record_contribution / get_*_for_*
# ---------------------------------------------------------------------------


class TestRecordContribution:
    def test_record_and_fetch_for_conversation(
        self, db_conn, repo_id, conversation_id
    ):
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 42)
        store.record_contribution(conversation_id, cr_id, "created")
        store.record_contribution(conversation_id, cr_id, "merged")

        contributions = store.get_contributions_for_conversation(conversation_id)
        types = sorted(c.contribution_type for c in contributions)
        assert types == ["created", "merged"]

    def test_duplicate_record_is_ignored(self, db_conn, repo_id, conversation_id):
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 1)
        store.record_contribution(conversation_id, cr_id, "created")
        store.record_contribution(conversation_id, cr_id, "created")  # duplicate

        contributions = store.get_contributions_for_conversation(conversation_id)
        assert len(contributions) == 1

    def test_many_to_many_multiple_conversations_one_pr(
        self, db_conn, repo_id, conversation_id
    ):
        """Two different conversations can both contribute to the same PR."""
        # Add a second conversation.
        db_conn.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv-2", "/tmp/conv-2"),
        )

        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 42)
        store.record_contribution(conversation_id, cr_id, "created")
        store.record_contribution("conv-2", cr_id, "merged")

        contributors = store.get_contributors_for_change_ref(cr_id)
        assert {c.conversation_id for c in contributors} == {
            conversation_id,
            "conv-2",
        }

        # And only one change_ref exists.
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM change_refs WHERE pr_number = 42"
        )
        assert cursor.fetchone()[0] == 1


class TestDeleteContributionsForConversation:
    def test_deletes_only_target_conversations_rows(
        self, db_conn, repo_id, conversation_id
    ):
        db_conn.execute(
            "INSERT INTO conversations (id, location) VALUES (?, ?)",
            ("conv-2", "/tmp/conv-2"),
        )

        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 1)
        store.record_contribution(conversation_id, cr_id, "created")
        store.record_contribution("conv-2", cr_id, "merged")

        deleted = store.delete_contributions_for_conversation(conversation_id)
        assert deleted == 1

        # conv-1's contributions are gone, conv-2's remain.
        assert store.get_contributions_for_conversation(conversation_id) == []
        assert len(store.get_contributions_for_conversation("conv-2")) == 1

    def test_delete_leaves_change_ref_intact(
        self, db_conn, repo_id, conversation_id
    ):
        """Deleting a conversation's contributions must NOT delete change_refs."""
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 1)
        store.record_contribution(conversation_id, cr_id, "created")

        store.delete_contributions_for_conversation(conversation_id)

        assert store.get_change_ref(cr_id) is not None


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


class TestListPrChangeRefs:
    def test_returns_only_pr_change_refs_in_pr_number_order(self, db_conn, repo_id):
        store = ContributionsStore(db_conn)
        store.get_or_create_pr_change_ref(repo_id, 5)
        store.get_or_create_pr_change_ref(repo_id, 1)
        store.get_or_create_pr_change_ref(repo_id, 3)
        # A direct push must not appear in the PR listing.
        store.get_or_create_direct_push_change_ref(repo_id, "x..y")

        listed = store.list_pr_change_refs(repo_id)
        assert [cr.pr_number for cr in listed] == [1, 3, 5]
        assert all(cr.change_type == "pr" for cr in listed)


# ---------------------------------------------------------------------------
# Schema-level constraints (defence in depth)
# ---------------------------------------------------------------------------


class TestSchemaConstraints:
    def test_unique_constraint_on_pr_per_repo(self, db_conn, repo_id):
        # Direct INSERTs to confirm the migration's unique index works as
        # we expect - our helper depends on this.
        db_conn.execute(
            "INSERT INTO change_refs (repo_id, change_type, pr_number, status) "
            "VALUES (?, 'pr', 99, 'pending')",
            (repo_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO change_refs (repo_id, change_type, pr_number, status) "
                "VALUES (?, 'pr', 99, 'pending')",
                (repo_id,),
            )

    def test_unique_constraint_on_contribution_triple(
        self, db_conn, repo_id, conversation_id
    ):
        store = ContributionsStore(db_conn)
        cr_id = store.get_or_create_pr_change_ref(repo_id, 1)
        db_conn.execute(
            "INSERT INTO conversation_contributions "
            "(conversation_id, change_ref_id, contribution_type) "
            "VALUES (?, ?, 'created')",
            (conversation_id, cr_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO conversation_contributions "
                "(conversation_id, change_ref_id, contribution_type) "
                "VALUES (?, ?, 'created')",
                (conversation_id, cr_id),
            )
