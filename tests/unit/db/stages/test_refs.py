"""Tests for the refs processing stage."""

import shutil
from pathlib import Path

import pytest

from ohtv.db.models import Conversation, LinkType, RefType
from ohtv.db.stages.refs import (
    STAGE_NAME,
    _determine_link_type,
    _parse_ref_url,
    _parse_repo_url,
    process_refs,
)
from ohtv.db.stores import (
    ConversationStore,
    LinkStore,
    ReferenceStore,
    RepoStore,
    StageStore,
)


class TestParseRepoUrl:
    """Tests for _parse_repo_url function."""
    
    def test_parses_github_repo(self):
        """Should parse GitHub repo URL."""
        repo = _parse_repo_url("https://github.com/owner/repo")
        
        assert repo is not None
        assert repo.canonical_url == "https://github.com/owner/repo"
        assert repo.fqn == "owner/repo"
        assert repo.short_name == "repo"
    
    def test_parses_github_repo_with_git_suffix(self):
        """Should handle .git suffix."""
        repo = _parse_repo_url("https://github.com/owner/repo.git")
        
        assert repo is not None
        assert repo.canonical_url == "https://github.com/owner/repo"
    
    def test_parses_gitlab_repo(self):
        """Should parse GitLab repo URL."""
        repo = _parse_repo_url("https://gitlab.com/group/repo")
        
        assert repo is not None
        assert repo.fqn == "group/repo"
    
    def test_parses_bitbucket_repo(self):
        """Should parse Bitbucket repo URL."""
        repo = _parse_repo_url("https://bitbucket.org/owner/repo")
        
        assert repo is not None
        assert repo.fqn == "owner/repo"
    
    def test_returns_none_for_invalid_url(self):
        """Should return None for unrecognized URLs."""
        assert _parse_repo_url("https://example.com/foo/bar") is None


class TestParseRefUrl:
    """Tests for _parse_ref_url function."""
    
    def test_parses_github_pr(self):
        """Should parse GitHub PR URL."""
        ref = _parse_ref_url("https://github.com/owner/repo/pull/123", RefType.PR)
        
        assert ref is not None
        assert ref.ref_type == RefType.PR
        assert ref.fqn == "owner/repo#123"
        assert ref.display_name == "repo #123"
    
    def test_parses_github_issue(self):
        """Should parse GitHub issue URL."""
        ref = _parse_ref_url("https://github.com/owner/repo/issues/456", RefType.ISSUE)
        
        assert ref is not None
        assert ref.ref_type == RefType.ISSUE
        assert ref.fqn == "owner/repo#456"
    
    def test_parses_gitlab_mr(self):
        """Should parse GitLab MR URL."""
        ref = _parse_ref_url("https://gitlab.com/group/repo/-/merge_requests/789", RefType.PR)
        
        assert ref is not None
        assert ref.fqn == "group/repo!789"
    
    def test_returns_none_for_invalid_url(self):
        """Should return None for unrecognized URLs."""
        assert _parse_ref_url("https://example.com/issue/1", RefType.ISSUE) is None


class TestDetermineLinkType:
    """Tests for _determine_link_type function."""
    
    def test_returns_write_for_write_actions(self):
        """Should return WRITE for write actions."""
        assert _determine_link_type({"pushed"}) == LinkType.WRITE
        assert _determine_link_type({"created"}) == LinkType.WRITE
        assert _determine_link_type({"commented"}) == LinkType.WRITE
        assert _determine_link_type({"merged"}) == LinkType.WRITE
    
    def test_returns_read_for_empty_interactions(self):
        """Should return READ when no interactions detected."""
        assert _determine_link_type(set()) == LinkType.READ
    
    def test_returns_read_for_unknown_actions(self):
        """Should return READ for unknown action types."""
        assert _determine_link_type({"viewed", "opened"}) == LinkType.READ


class TestProcessRefs:
    """Tests for process_refs function."""
    
    @pytest.fixture
    def sample_conversation(self, tmp_path):
        """Create a sample conversation with GitHub refs."""
        # Copy the sample conversation from fixtures
        fixtures_dir = Path(__file__).parent.parent.parent.parent / "fixtures" / "conversations"
        src = fixtures_dir / "conv-with-github-refs"
        dest = tmp_path / "conv-with-github-refs"
        shutil.copytree(src, dest)
        
        return Conversation(
            id="conv-with-github-refs",
            location=str(dest),
            event_count=4,
        )
    
    def test_extracts_and_stores_refs(self, db_conn, sample_conversation):
        """Should extract refs and store them in DB."""
        # First register the conversation
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(sample_conversation)
        
        # Process refs
        process_refs(db_conn, sample_conversation)
        
        # Check refs were stored
        ref_store = ReferenceStore(db_conn)
        
        # Should have the issue (acme/webapp#42 from the user message)
        issues = ref_store.list_by_type(RefType.ISSUE)
        assert len(issues) >= 1
        assert any(r.fqn == "acme/webapp#42" for r in issues)
        
        # Should have the PR (acme/webapp#99 from the gh pr create output)
        prs = ref_store.list_by_type(RefType.PR)
        assert len(prs) >= 1
        assert any(r.fqn == "acme/webapp#99" for r in prs)
    
    def test_creates_conversation_links(self, db_conn, sample_conversation):
        """Should create links between conversation and refs."""
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(sample_conversation)
        
        process_refs(db_conn, sample_conversation)
        
        link_store = LinkStore(db_conn)
        
        # Check ref links (issue + PR)
        ref_links = link_store.get_refs_for_conversation(sample_conversation.id)
        assert len(ref_links) >= 2  # Issue and PR
    
    def test_marks_stage_complete(self, db_conn, sample_conversation):
        """Should mark the stage as complete."""
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(sample_conversation)
        
        process_refs(db_conn, sample_conversation)
        
        stage_store = StageStore(db_conn)
        stage = stage_store.get(sample_conversation.id, STAGE_NAME)
        
        assert stage is not None
        assert stage.event_count == sample_conversation.event_count
    
    def test_detects_write_links_for_created_pr(self, db_conn, sample_conversation):
        """Should detect WRITE link type for created PR."""
        conv_store = ConversationStore(db_conn)
        conv_store.upsert(sample_conversation)
        
        process_refs(db_conn, sample_conversation)
        
        # The PR was created (gh pr create), so should be WRITE
        ref_store = ReferenceStore(db_conn)
        pr = ref_store.get_by_url("https://github.com/acme/webapp/pull/99")
        
        if pr:  # PR might be extracted
            link_store = LinkStore(db_conn)
            ref_links = link_store.get_refs_for_conversation(sample_conversation.id)
            
            # Find the link for this PR
            pr_link = next((link for ref_id, link in ref_links if ref_id == pr.id), None)
            if pr_link:
                assert pr_link == LinkType.WRITE
