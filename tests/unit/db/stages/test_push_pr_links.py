"""Tests for push-to-PR linking processor."""

import pytest
import sqlite3

from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation, LinkType, Reference, RefType
from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.push_pr_links import (
    process_push_pr_links,
    _get_pr_branch_key,
    _get_push_branch_key,
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


class TestGetBranchKey:
    """Tests for extracting branch keys from actions."""
    
    def test_get_pr_branch_key_with_full_metadata(self):
        """Should extract branch key from OPEN_PR with full metadata."""
        action = ConversationAction(
            id=1,
            conversation_id="conv-1",
            action_type=ActionType.OPEN_PR,
            target="https://github.com/owner/repo/pull/123",
            metadata={
                "head_branch": "feature/branch",
                "owner": "owner",
                "repo": "repo",
            },
        )
        assert _get_pr_branch_key(action) == "owner/repo:feature/branch"
    
    def test_get_pr_branch_key_missing_branch(self):
        """Should return None when head_branch is missing."""
        action = ConversationAction(
            id=1,
            conversation_id="conv-1",
            action_type=ActionType.OPEN_PR,
            target="https://github.com/owner/repo/pull/123",
            metadata={"owner": "owner", "repo": "repo"},
        )
        assert _get_pr_branch_key(action) is None
    
    def test_get_pr_branch_key_missing_owner(self):
        """Should return None when owner is missing."""
        action = ConversationAction(
            id=1,
            conversation_id="conv-1",
            action_type=ActionType.OPEN_PR,
            target="https://github.com/owner/repo/pull/123",
            metadata={"head_branch": "feature/branch", "repo": "repo"},
        )
        assert _get_pr_branch_key(action) is None
    
    def test_get_push_branch_key_with_full_metadata(self):
        """Should extract branch key from GIT_PUSH with full metadata."""
        action = ConversationAction(
            id=1,
            conversation_id="conv-1",
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={
                "branch": "feature/branch",
                "owner": "owner",
                "repo": "repo",
            },
        )
        assert _get_push_branch_key(action) == "owner/repo:feature/branch"
    
    def test_get_push_branch_key_missing_owner(self):
        """Should return None when owner is missing (conservative behavior)."""
        action = ConversationAction(
            id=1,
            conversation_id="conv-1",
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "feature/branch"},
        )
        assert _get_push_branch_key(action) is None


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


class TestTemporalLinking:
    """Tests for temporal push-to-PR linking."""
    
    def test_push_before_pr_links_backward(self, db_connection, conversation):
        """Pushes before PR creation should link via backward pass."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create PR reference
        pr_url = "https://github.com/owner/repo/pull/55"
        ref_id = ref_store.upsert(Reference(
            id=None,
            ref_type=RefType.PR,
            url=pr_url,
            fqn="owner/repo#55",
            display_name="repo #55",
        ))
        
        # Push 1 (before PR)
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "feature/new-cli", "owner": "owner", "repo": "repo"},
        ))
        
        # Push 2 (before PR)
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "feature/new-cli", "owner": "owner", "repo": "repo"},
        ))
        
        # PR created
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr_url,
            metadata={"head_branch": "feature/new-cli", "owner": "owner", "repo": "repo"},
        ))
        
        # Push 3 (after PR)
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "feature/new-cli", "owner": "owner", "repo": "repo"},
        ))
        
        process_push_pr_links(db_connection, conversation)
        
        # All pushes should link to the PR (WRITE link created)
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 1
        linked_ref_id, link_type = refs[0]
        assert linked_ref_id == ref_id
        assert link_type == LinkType.WRITE
    
    def test_branch_reuse_links_to_correct_pr(self, db_connection, conversation):
        """Multiple PRs on same branch should link pushes to correct PR temporally."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create PR references
        pr1_url = "https://github.com/owner/repo/pull/20"
        pr2_url = "https://github.com/owner/repo/pull/25"
        pr1_id = ref_store.upsert(Reference(
            id=None, ref_type=RefType.PR, url=pr1_url,
            fqn="owner/repo#20", display_name="repo #20",
        ))
        pr2_id = ref_store.upsert(Reference(
            id=None, ref_type=RefType.PR, url=pr2_url,
            fqn="owner/repo#25", display_name="repo #25",
        ))
        
        # First PR on 'develop' branch
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr1_url,
            metadata={"head_branch": "develop", "owner": "owner", "repo": "repo"},
        ))
        
        # Push to first PR
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "develop", "owner": "owner", "repo": "repo"},
        ))
        
        # Second PR on same branch (after first was merged)
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr2_url,
            metadata={"head_branch": "develop", "owner": "owner", "repo": "repo"},
        ))
        
        # Push to second PR
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "develop", "owner": "owner", "repo": "repo"},
        ))
        
        process_push_pr_links(db_connection, conversation)
        
        # Both PRs should have WRITE links (temporal linking works)
        refs = link_store.get_refs_for_conversation(conversation.id)
        ref_ids = {r[0] for r in refs}
        assert pr1_id in ref_ids, "First PR should have WRITE link"
        assert pr2_id in ref_ids, "Second PR should have WRITE link"
    
    def test_multi_branch_temporal_linking(self, db_connection, conversation):
        """Multiple branches with PRs should link correctly."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create PR references for two different branches
        pr_a_url = "https://github.com/owner/repo/pull/10"
        pr_b_url = "https://github.com/owner/repo/pull/11"
        pr_a_id = ref_store.upsert(Reference(
            id=None, ref_type=RefType.PR, url=pr_a_url,
            fqn="owner/repo#10", display_name="repo #10",
        ))
        pr_b_id = ref_store.upsert(Reference(
            id=None, ref_type=RefType.PR, url=pr_b_url,
            fqn="owner/repo#11", display_name="repo #11",
        ))
        
        # Push to branch A (before its PR)
        action_store.insert(ConversationAction(
            id=None, conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "fix/typo", "owner": "owner", "repo": "repo"},
        ))
        
        # Create PR for branch A
        action_store.insert(ConversationAction(
            id=None, conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr_a_url,
            metadata={"head_branch": "fix/typo", "owner": "owner", "repo": "repo"},
        ))
        
        # Push to branch B (before its PR)
        action_store.insert(ConversationAction(
            id=None, conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "fix/link", "owner": "owner", "repo": "repo"},
        ))
        
        # Create PR for branch B
        action_store.insert(ConversationAction(
            id=None, conversation_id=conversation.id,
            action_type=ActionType.OPEN_PR,
            target=pr_b_url,
            metadata={"head_branch": "fix/link", "owner": "owner", "repo": "repo"},
        ))
        
        process_push_pr_links(db_connection, conversation)
        
        # Both PRs should have WRITE links from their respective branches
        refs = link_store.get_refs_for_conversation(conversation.id)
        ref_ids = {r[0] for r in refs}
        assert pr_a_id in ref_ids, "PR A should have WRITE link from branch A push"
        assert pr_b_id in ref_ids, "PR B should have WRITE link from branch B push"
    
    def test_orphan_push_no_pr_no_link(self, db_connection, conversation):
        """Push without any subsequent PR should not create a link."""
        action_store = ActionStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Push to main branch (no PR)
        action_store.insert(ConversationAction(
            id=None, conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "main", "owner": "owner", "repo": "repo"},
        ))
        
        # Push to feature branch (also no PR)
        action_store.insert(ConversationAction(
            id=None, conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/owner/repo.git",
            metadata={"branch": "feature/orphan", "owner": "owner", "repo": "repo"},
        ))
        
        process_push_pr_links(db_connection, conversation)
        
        # No links should be created
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 0
