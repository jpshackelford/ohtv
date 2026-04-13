"""Tests for push-to-PR linking processor."""

import pytest
import sqlite3

from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation, LinkType, Reference, RefType
from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.push_pr_links import (
    process_push_pr_links,
    _build_branch_pr_map,
    _make_branch_key,
)
from ohtv.db.stores import ActionStore, LinkStore, ReferenceStore, StageStore


@pytest.fixture
def db_connection():
    """Create an in-memory database for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def conversation():
    """Create a test conversation."""
    return Conversation(
        id="test-conv-123",
        location="/path/to/conv",
        events_mtime=1234567890.0,
        event_count=10,
        registered_at="2024-01-01T00:00:00",
    )


class TestBuildBranchPRMap:
    """Tests for building branch-to-PR mapping."""
    
    def test_builds_map_from_open_pr_actions(self):
        """Should build map from OPEN_PR actions with branch info."""
        actions = [
            ConversationAction(
                id=1,
                conversation_id="conv-1",
                action_type=ActionType.OPEN_PR,
                target="https://github.com/owner/repo/pull/123",
                metadata={
                    "head_branch": "feature/branch",
                    "owner": "owner",
                    "repo": "repo",
                    "source": "github",
                },
            ),
        ]
        
        result = _build_branch_pr_map(actions)
        
        # Should only have fully qualified key (no branch-only fallback)
        assert result.get("owner/repo:feature/branch") == "https://github.com/owner/repo/pull/123"
        assert "feature/branch" not in result  # No branch-only key
    
    def test_ignores_non_open_pr_actions(self):
        """Should ignore actions that aren't OPEN_PR."""
        actions = [
            ConversationAction(
                id=1,
                conversation_id="conv-1",
                action_type=ActionType.GIT_PUSH,
                target="https://github.com/owner/repo.git",
                metadata={"branch": "main"},
            ),
        ]
        
        result = _build_branch_pr_map(actions)
        assert len(result) == 0
    
    def test_ignores_pr_without_branch_info(self):
        """Should ignore OPEN_PR actions without head_branch metadata."""
        actions = [
            ConversationAction(
                id=1,
                conversation_id="conv-1",
                action_type=ActionType.OPEN_PR,
                target="https://github.com/owner/repo/pull/123",
                metadata={"source": "github"},  # No head_branch
            ),
        ]
        
        result = _build_branch_pr_map(actions)
        assert len(result) == 0
    
    def test_handles_multiple_prs(self):
        """Should handle multiple PRs with different branches."""
        actions = [
            ConversationAction(
                id=1,
                conversation_id="conv-1",
                action_type=ActionType.OPEN_PR,
                target="https://github.com/owner/repo/pull/123",
                metadata={
                    "head_branch": "feature/a",
                    "owner": "owner",
                    "repo": "repo",
                },
            ),
            ConversationAction(
                id=2,
                conversation_id="conv-1",
                action_type=ActionType.OPEN_PR,
                target="https://github.com/owner/repo/pull/456",
                metadata={
                    "head_branch": "feature/b",
                    "owner": "owner",
                    "repo": "repo",
                },
            ),
        ]
        
        result = _build_branch_pr_map(actions)
        # Keys are fully qualified (owner/repo:branch)
        assert result.get("owner/repo:feature/a") == "https://github.com/owner/repo/pull/123"
        assert result.get("owner/repo:feature/b") == "https://github.com/owner/repo/pull/456"


class TestMakeBranchKey:
    """Tests for branch key generation."""
    
    def test_creates_full_key_with_owner_repo(self):
        """Should create full key when owner and repo provided."""
        key = _make_branch_key("owner", "repo", "feature/branch")
        assert key == "owner/repo:feature/branch"
    
    def test_returns_branch_only_when_no_owner(self):
        """Should return branch only when owner is None."""
        key = _make_branch_key(None, "repo", "feature/branch")
        assert key == "feature/branch"
    
    def test_returns_branch_only_when_no_repo(self):
        """Should return branch only when repo is None."""
        key = _make_branch_key("owner", None, "feature/branch")
        assert key == "feature/branch"


class TestProcessPushPRLinks:
    """Tests for the push-to-PR linking processor."""
    
    def test_links_push_to_pr_by_branch(self, db_connection, conversation):
        """Should link a push to a PR when branch matches."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        stage_store = StageStore(db_connection)
        
        # Create a PR reference
        pr_url = "https://github.com/owner/repo/pull/123"
        ref = Reference(
            id=None,
            ref_type=RefType.PR,
            url=pr_url,
            fqn="owner/repo#123",
            display_name="repo #123",
        )
        ref_id = ref_store.upsert(ref)
        
        # Create OPEN_PR action with branch info
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr_url,
            metadata={
                "head_branch": "feature/my-branch",
                "owner": "owner",
                "repo": "repo",
            },
        ))
        
        # Create GIT_PUSH action to same branch
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={
                "branch": "feature/my-branch",
                "owner": "owner",
                "repo": "repo",
            },
        ))
        
        # Process the links
        process_push_pr_links(db_connection, conversation)
        
        # Verify the PR is now linked with WRITE type
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 1
        linked_ref_id, link_type = refs[0]
        assert linked_ref_id == ref_id
        assert link_type == LinkType.WRITE
    
    def test_does_not_link_push_to_unrelated_pr(self, db_connection, conversation):
        """Should not link push to PR with different branch."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create a PR reference
        pr_url = "https://github.com/owner/repo/pull/123"
        ref_store.upsert(Reference(
            id=None,
            ref_type=RefType.PR,
            url=pr_url,
            fqn="owner/repo#123",
            display_name="repo #123",
        ))
        
        # Create OPEN_PR action with branch info
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr_url,
            metadata={
                "head_branch": "feature/branch-a",
                "owner": "owner",
                "repo": "repo",
            },
        ))
        
        # Create GIT_PUSH action to DIFFERENT branch
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={
                "branch": "feature/branch-b",  # Different branch
                "owner": "owner",
                "repo": "repo",
            },
        ))
        
        # Process the links
        process_push_pr_links(db_connection, conversation)
        
        # Verify no link was created
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 0
    
    def test_marks_stage_complete(self, db_connection, conversation):
        """Should mark the stage as complete after processing."""
        stage_store = StageStore(db_connection)
        
        # Process (even with no actions)
        process_push_pr_links(db_connection, conversation)
        
        # Verify stage is marked complete
        assert not stage_store.needs_processing(
            conversation.id, "push_pr_links", conversation.event_count
        )
    
    def test_does_not_link_push_without_repo_info(self, db_connection, conversation):
        """Should NOT link push when repo info is missing (conservative approach)."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create a PR reference
        pr_url = "https://github.com/owner/repo/pull/123"
        ref_store.upsert(Reference(
            id=None,
            ref_type=RefType.PR,
            url=pr_url,
            fqn="owner/repo#123",
            display_name="repo #123",
        ))
        
        # Create OPEN_PR action with branch info
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr_url,
            metadata={
                "head_branch": "my-branch",
                "owner": "owner",
                "repo": "repo",
            },
        ))
        
        # Create GIT_PUSH action to same branch but WITHOUT repo info
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={
                "branch": "my-branch",
                # No owner/repo - should NOT link to avoid cross-repo mismatches
            },
        ))
        
        # Process the links
        process_push_pr_links(db_connection, conversation)
        
        # Verify NO link was created (conservative behavior)
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 0
