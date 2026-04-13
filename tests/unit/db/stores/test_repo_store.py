"""Unit tests for RepoStore."""

from ohtv.db.models import Repository


class TestUpsert:
    """Tests for RepoStore.upsert()."""

    def test_inserts_new_repo(self, repo_store, db_conn):
        repo = Repository(
            id=None,
            canonical_url="https://github.com/owner/repo",
            fqn="owner/repo",
            short_name="repo",
        )
        
        repo_id = repo_store.upsert(repo)
        db_conn.commit()
        
        assert repo_id is not None
        assert repo_store.get_by_url("https://github.com/owner/repo") is not None

    def test_returns_id_of_inserted_repo(self, repo_store, db_conn):
        repo = Repository(None, "https://github.com/owner/repo", "owner/repo", "repo")
        
        repo_id = repo_store.upsert(repo)
        
        assert isinstance(repo_id, int)
        assert repo_id > 0

    def test_updates_existing_repo_by_url(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "old-name"))
        db_conn.commit()
        
        repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "new-name"))
        db_conn.commit()
        
        result = repo_store.get_by_url("https://github.com/owner/repo")
        assert result.short_name == "new-name"

    def test_returns_same_id_on_upsert_existing(self, repo_store, db_conn):
        id1 = repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "repo"))
        db_conn.commit()
        
        id2 = repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "repo"))
        
        assert id1 == id2


class TestGetByUrl:
    """Tests for RepoStore.get_by_url()."""

    def test_returns_repo_when_exists(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "repo"))
        db_conn.commit()
        
        result = repo_store.get_by_url("https://github.com/owner/repo")
        
        assert result.fqn == "owner/repo"
        assert result.short_name == "repo"

    def test_returns_none_when_not_exists(self, repo_store):
        result = repo_store.get_by_url("https://github.com/nonexistent/repo")
        
        assert result is None


class TestSearchByName:
    """Tests for RepoStore.search_by_name()."""

    def test_finds_repo_by_short_name(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/myrepo", "owner/myrepo", "myrepo"))
        db_conn.commit()
        
        results = repo_store.search_by_name("myrepo")
        
        assert len(results) == 1
        assert results[0].short_name == "myrepo"

    def test_finds_repo_by_fqn(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "repo"))
        db_conn.commit()
        
        results = repo_store.search_by_name("owner/repo")
        
        assert len(results) == 1

    def test_finds_repo_by_partial_match(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/myrepo", "owner/myrepo", "myrepo"))
        db_conn.commit()
        
        results = repo_store.search_by_name("repo")
        
        assert len(results) == 1

    def test_returns_empty_when_no_match(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/repo", "owner/repo", "repo"))
        db_conn.commit()
        
        results = repo_store.search_by_name("nonexistent")
        
        assert len(results) == 0

    def test_finds_multiple_matching_repos(self, repo_store, db_conn):
        repo_store.upsert(Repository(None, "https://github.com/owner/repo-one", "owner/repo-one", "repo-one"))
        repo_store.upsert(Repository(None, "https://github.com/owner/repo-two", "owner/repo-two", "repo-two"))
        db_conn.commit()
        
        results = repo_store.search_by_name("repo")
        
        assert len(results) == 2
