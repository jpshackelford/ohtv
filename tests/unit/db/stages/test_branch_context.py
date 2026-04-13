"""Tests for branch context processor."""

import pytest
import sqlite3

from ohtv.db.migrations import migrate
from ohtv.db.models import Conversation, LinkType, RefType
from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.branch_context import (
    process_branch_context,
    get_branch_timeline,
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
        id="test-conv-branch",
        location="/path/to/conv",
        events_mtime=1234567890.0,
        event_count=10,
        registered_at="2024-01-01T00:00:00",
    )


class TestProcessBranchContext:
    """Tests for the branch context processor."""
    
    def test_creates_branch_ref_from_push(self, db_connection, conversation):
        """Should create a branch ref when a push action has branch info."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create a GIT_PUSH action with branch info
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/add-button",
                "owner": "acme",
                "repo": "widgets",
            },
            event_id="evt-001",
        ))
        
        # Process branch context
        process_branch_context(db_connection, conversation)
        
        # Verify branch ref was created
        ref = ref_store.get_by_url("https://github.com/acme/widgets/tree/feature/add-button")
        assert ref is not None
        assert ref.ref_type == RefType.BRANCH
        assert ref.fqn == "acme/widgets:feature/add-button"
        assert ref.display_name == "widgets:feature/add-button"
        
        # Verify conversation is linked to branch
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 1
        ref_id, link_type = refs[0]
        assert ref_id == ref.id
        assert link_type == LinkType.WRITE
    
    def test_creates_multiple_branch_refs(self, db_connection, conversation):
        """Should create refs for multiple branches pushed to."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create pushes to different branches
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/button",
                "owner": "acme",
                "repo": "widgets",
            },
            event_id="evt-001",
        ))
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "feature/slider",
                "owner": "acme",
                "repo": "widgets",
            },
            event_id="evt-002",
        ))
        
        # Process branch context
        process_branch_context(db_connection, conversation)
        
        # Verify both branch refs were created
        ref1 = ref_store.get_by_url("https://github.com/acme/widgets/tree/feature/button")
        ref2 = ref_store.get_by_url("https://github.com/acme/widgets/tree/feature/slider")
        assert ref1 is not None
        assert ref2 is not None
        
        # Verify both are linked
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 2
    
    def test_deduplicates_same_branch_multiple_pushes(self, db_connection, conversation):
        """Should create only one ref when same branch is pushed multiple times."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create multiple pushes to same branch
        for i in range(3):
            action_store.insert(ConversationAction(
                id=None,
                conversation_id=conversation.id,
                action_type=ActionType.GIT_PUSH,
                target="https://github.com/acme/widgets.git",
                metadata={
                    "branch": "main",
                    "owner": "acme",
                    "repo": "widgets",
                },
                event_id=f"evt-{i:03d}",
            ))
        
        # Process branch context
        process_branch_context(db_connection, conversation)
        
        # Verify only one branch ref was created
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 1
    
    def test_ignores_push_without_full_metadata(self, db_connection, conversation):
        """Should not create ref when push is missing owner/repo/branch."""
        action_store = ActionStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Create push with missing metadata
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/widgets.git",
            metadata={
                "branch": "main",
                # Missing owner and repo
            },
            event_id="evt-001",
        ))
        
        # Process branch context
        process_branch_context(db_connection, conversation)
        
        # Verify no refs were created
        refs = link_store.get_refs_for_conversation(conversation.id)
        assert len(refs) == 0
    
    def test_handles_branches_in_different_repos(self, db_connection, conversation):
        """Should create separate refs for same branch name in different repos."""
        action_store = ActionStore(db_connection)
        ref_store = ReferenceStore(db_connection)
        link_store = LinkStore(db_connection)
        
        # Same branch name, different repos
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/frontend.git",
            metadata={
                "branch": "develop",
                "owner": "acme",
                "repo": "frontend",
            },
            event_id="evt-001",
        ))
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/backend.git",
            metadata={
                "branch": "develop",
                "owner": "acme",
                "repo": "backend",
            },
            event_id="evt-002",
        ))
        
        # Process branch context
        process_branch_context(db_connection, conversation)
        
        # Verify both branch refs were created (different repos)
        ref1 = ref_store.get_by_url("https://github.com/acme/frontend/tree/develop")
        ref2 = ref_store.get_by_url("https://github.com/acme/backend/tree/develop")
        assert ref1 is not None
        assert ref2 is not None
        assert ref1.fqn == "acme/frontend:develop"
        assert ref2.fqn == "acme/backend:develop"
    
    def test_marks_stage_complete(self, db_connection, conversation):
        """Should mark the stage as complete after processing."""
        stage_store = StageStore(db_connection)
        
        # Process (even with no actions)
        process_branch_context(db_connection, conversation)
        
        # Verify stage is marked complete
        assert not stage_store.needs_processing(
            conversation.id, "branch_context", conversation.event_count
        )


class TestGetBranchTimeline:
    """Tests for branch timeline retrieval."""
    
    def test_returns_pushes_in_order(self, db_connection, conversation):
        """Should return push events in temporal order."""
        action_store = ActionStore(db_connection)
        
        # Create pushes in specific order
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/app.git",
            metadata={"branch": "first", "owner": "acme", "repo": "app"},
            event_id="evt-001",
        ))
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/app.git",
            metadata={"branch": "second", "owner": "acme", "repo": "app"},
            event_id="evt-002",
        ))
        action_store.insert(ConversationAction(
            id=None,
            conversation_id=conversation.id,
            action_type=ActionType.GIT_PUSH,
            target="https://github.com/acme/app.git",
            metadata={"branch": "third", "owner": "acme", "repo": "app"},
            event_id="evt-003",
        ))
        
        # Get timeline
        timeline = get_branch_timeline(db_connection, conversation.id)
        
        # Verify order
        assert len(timeline) == 3
        assert timeline[0]["branch"] == "first"
        assert timeline[1]["branch"] == "second"
        assert timeline[2]["branch"] == "third"
    
    def test_returns_empty_for_no_pushes(self, db_connection, conversation):
        """Should return empty list when no pushes exist."""
        timeline = get_branch_timeline(db_connection, conversation.id)
        assert timeline == []
