"""Unit tests for LinkStore."""

from ohtv.db.models import Conversation, Reference, RefType, Repository, LinkType
from ohtv.db.stores import ConversationStore, ReferenceStore, RepoStore


class TestLinkRepo:
    """Tests for LinkStore.link_repo()."""

    def test_creates_link_between_conversation_and_repo(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        db_conn.commit()
        
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        db_conn.commit()
        
        links = link_store.get_repos_for_conversation("conv-1")
        assert len(links) == 1

    def test_upgrades_link_from_read_to_write(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        db_conn.commit()
        
        link_store.link_repo("conv-1", repo_id, LinkType.WRITE)
        db_conn.commit()
        
        links = link_store.get_repos_for_conversation("conv-1")
        assert links[0][1] == LinkType.WRITE

    def test_does_not_downgrade_link_from_write_to_read(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        link_store.link_repo("conv-1", repo_id, LinkType.WRITE)
        db_conn.commit()
        
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        db_conn.commit()
        
        links = link_store.get_repos_for_conversation("conv-1")
        assert links[0][1] == LinkType.WRITE

    def test_does_not_create_duplicate_links(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        db_conn.commit()
        
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        db_conn.commit()
        
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM conversation_repos WHERE conversation_id = ?",
            ("conv-1",)
        )
        assert cursor.fetchone()[0] == 1


class TestLinkRef:
    """Tests for LinkStore.link_ref()."""

    def test_creates_link_between_conversation_and_reference(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        ref_id = ReferenceStore(db_conn).upsert(
            Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1")
        )
        db_conn.commit()
        
        link_store.link_ref("conv-1", ref_id, LinkType.READ)
        db_conn.commit()
        
        links = link_store.get_refs_for_conversation("conv-1")
        assert len(links) == 1

    def test_upgrades_link_from_read_to_write(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        ref_id = ReferenceStore(db_conn).upsert(
            Reference(None, RefType.PR, "https://github.com/o/r/pull/1", "o/r#1", "r #1")
        )
        link_store.link_ref("conv-1", ref_id, LinkType.READ)
        db_conn.commit()
        
        link_store.link_ref("conv-1", ref_id, LinkType.WRITE)
        db_conn.commit()
        
        links = link_store.get_refs_for_conversation("conv-1")
        assert links[0][1] == LinkType.WRITE

    def test_does_not_downgrade_link_from_write_to_read(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        ref_id = ReferenceStore(db_conn).upsert(
            Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1")
        )
        link_store.link_ref("conv-1", ref_id, LinkType.WRITE)
        db_conn.commit()
        
        link_store.link_ref("conv-1", ref_id, LinkType.READ)
        db_conn.commit()
        
        links = link_store.get_refs_for_conversation("conv-1")
        assert links[0][1] == LinkType.WRITE


class TestGetConversationsForRepo:
    """Tests for LinkStore.get_conversations_for_repo()."""

    def test_returns_linked_conversations(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path1"))
        ConversationStore(db_conn).upsert(Conversation("conv-2", "/path2"))
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        link_store.link_repo("conv-2", repo_id, LinkType.WRITE)
        db_conn.commit()
        
        convs = link_store.get_conversations_for_repo(repo_id)
        
        conv_ids = [c[0] for c in convs]
        assert "conv-1" in conv_ids
        assert "conv-2" in conv_ids

    def test_filters_by_link_type(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path1"))
        ConversationStore(db_conn).upsert(Conversation("conv-2", "/path2"))
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        link_store.link_repo("conv-1", repo_id, LinkType.READ)
        link_store.link_repo("conv-2", repo_id, LinkType.WRITE)
        db_conn.commit()
        
        write_convs = link_store.get_conversations_for_repo(repo_id, LinkType.WRITE)
        
        assert len(write_convs) == 1
        assert write_convs[0][0] == "conv-2"

    def test_returns_empty_when_no_links(self, link_store, db_conn):
        repo_id = RepoStore(db_conn).upsert(Repository(None, "https://github.com/o/r", "o/r", "r"))
        db_conn.commit()
        
        convs = link_store.get_conversations_for_repo(repo_id)
        
        assert len(convs) == 0


class TestGetRefsForConversation:
    """Tests for LinkStore.get_refs_for_conversation()."""

    def test_returns_all_linked_refs(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        ref_store = ReferenceStore(db_conn)
        issue_id = ref_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        pr_id = ref_store.upsert(Reference(None, RefType.PR, "https://github.com/o/r/pull/2", "o/r#2", "r #2"))
        link_store.link_ref("conv-1", issue_id, LinkType.READ)
        link_store.link_ref("conv-1", pr_id, LinkType.WRITE)
        db_conn.commit()
        
        refs = link_store.get_refs_for_conversation("conv-1")
        
        assert len(refs) == 2

    def test_filters_by_ref_type(self, link_store, db_conn):
        # Setup
        ConversationStore(db_conn).upsert(Conversation("conv-1", "/path"))
        ref_store = ReferenceStore(db_conn)
        issue_id = ref_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        pr_id = ref_store.upsert(Reference(None, RefType.PR, "https://github.com/o/r/pull/2", "o/r#2", "r #2"))
        link_store.link_ref("conv-1", issue_id, LinkType.READ)
        link_store.link_ref("conv-1", pr_id, LinkType.WRITE)
        db_conn.commit()
        
        issues = link_store.get_refs_for_conversation("conv-1", RefType.ISSUE)
        
        assert len(issues) == 1
        assert issues[0][0] == issue_id

    def test_returns_empty_when_no_links(self, link_store):
        refs = link_store.get_refs_for_conversation("nonexistent")
        
        assert len(refs) == 0
