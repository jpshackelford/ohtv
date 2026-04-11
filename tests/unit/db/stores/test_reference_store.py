"""Unit tests for ReferenceStore."""

from ohtv.db.models import Reference, RefType


class TestUpsert:
    """Tests for ReferenceStore.upsert()."""

    def test_inserts_new_issue(self, reference_store, db_conn):
        ref = Reference(
            id=None,
            ref_type=RefType.ISSUE,
            url="https://github.com/owner/repo/issues/1",
            fqn="owner/repo#1",
            display_name="repo #1",
        )
        
        ref_id = reference_store.upsert(ref)
        db_conn.commit()
        
        assert ref_id is not None
        assert reference_store.get_by_url("https://github.com/owner/repo/issues/1") is not None

    def test_inserts_new_pr(self, reference_store, db_conn):
        ref = Reference(
            id=None,
            ref_type=RefType.PR,
            url="https://github.com/owner/repo/pull/2",
            fqn="owner/repo#2",
            display_name="repo #2",
        )
        
        ref_id = reference_store.upsert(ref)
        db_conn.commit()
        
        result = reference_store.get_by_url("https://github.com/owner/repo/pull/2")
        assert result.ref_type == RefType.PR

    def test_updates_existing_reference_by_url(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "old name"))
        db_conn.commit()
        
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "new name"))
        db_conn.commit()
        
        result = reference_store.get_by_url("https://github.com/o/r/issues/1")
        assert result.display_name == "new name"


class TestGetByUrl:
    """Tests for ReferenceStore.get_by_url()."""

    def test_returns_reference_when_exists(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        db_conn.commit()
        
        result = reference_store.get_by_url("https://github.com/o/r/issues/1")
        
        assert result.ref_type == RefType.ISSUE
        assert result.fqn == "o/r#1"

    def test_returns_none_when_not_exists(self, reference_store):
        result = reference_store.get_by_url("https://github.com/nonexistent/issues/1")
        
        assert result is None


class TestSearchByFqn:
    """Tests for ReferenceStore.search_by_fqn()."""

    def test_finds_references_by_fqn_pattern(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/owner/repo/issues/1", "owner/repo#1", "repo #1"))
        reference_store.upsert(Reference(None, RefType.PR, "https://github.com/owner/repo/pull/2", "owner/repo#2", "repo #2"))
        db_conn.commit()
        
        results = reference_store.search_by_fqn("owner/repo")
        
        assert len(results) == 2

    def test_filters_by_ref_type(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        reference_store.upsert(Reference(None, RefType.PR, "https://github.com/o/r/pull/2", "o/r#2", "r #2"))
        db_conn.commit()
        
        results = reference_store.search_by_fqn("o/r", ref_type=RefType.ISSUE)
        
        assert len(results) == 1
        assert results[0].ref_type == RefType.ISSUE

    def test_returns_empty_when_no_match(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        db_conn.commit()
        
        results = reference_store.search_by_fqn("nonexistent")
        
        assert len(results) == 0


class TestListByType:
    """Tests for ReferenceStore.list_by_type()."""

    def test_lists_all_issues(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/2", "o/r#2", "r #2"))
        reference_store.upsert(Reference(None, RefType.PR, "https://github.com/o/r/pull/3", "o/r#3", "r #3"))
        db_conn.commit()
        
        issues = reference_store.list_by_type(RefType.ISSUE)
        
        assert len(issues) == 2
        assert all(r.ref_type == RefType.ISSUE for r in issues)

    def test_lists_all_prs(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        reference_store.upsert(Reference(None, RefType.PR, "https://github.com/o/r/pull/2", "o/r#2", "r #2"))
        db_conn.commit()
        
        prs = reference_store.list_by_type(RefType.PR)
        
        assert len(prs) == 1
        assert prs[0].ref_type == RefType.PR

    def test_returns_empty_when_none_of_type(self, reference_store, db_conn):
        reference_store.upsert(Reference(None, RefType.ISSUE, "https://github.com/o/r/issues/1", "o/r#1", "r #1"))
        db_conn.commit()
        
        prs = reference_store.list_by_type(RefType.PR)
        
        assert len(prs) == 0
