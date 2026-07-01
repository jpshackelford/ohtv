"""Tests for URL parsing utilities."""

import pytest

from ohtv_utils.extraction.refs import parse_ref_url, parse_repo_url


class TestParseRepoUrl:
    """Tests for parse_repo_url function."""

    def test_github_repo(self):
        """Parse GitHub repository URL."""
        url = "https://github.com/jpshackelford/ohtv"
        result = parse_repo_url(url)
        assert result == {
            "canonical_url": "https://github.com/jpshackelford/ohtv",
            "fqn": "jpshackelford/ohtv",
            "short_name": "ohtv",
        }

    def test_github_repo_with_trailing_slash(self):
        """Handle trailing slash in URL."""
        url = "https://github.com/owner/repo/"
        result = parse_repo_url(url)
        assert result["canonical_url"] == "https://github.com/owner/repo"

    def test_github_repo_with_git_extension(self):
        """Remove .git extension."""
        url = "https://github.com/owner/repo.git"
        result = parse_repo_url(url)
        assert result["canonical_url"] == "https://github.com/owner/repo"

    def test_gitlab_repo_simple(self):
        """Parse GitLab repository URL."""
        url = "https://gitlab.com/owner/repo"
        result = parse_repo_url(url)
        assert result == {
            "canonical_url": "https://gitlab.com/owner/repo",
            "fqn": "owner/repo",
            "short_name": "repo",
        }

    def test_gitlab_repo_nested_group(self):
        """Parse GitLab URL with nested groups."""
        url = "https://gitlab.com/group/subgroup/repo"
        result = parse_repo_url(url)
        assert result == {
            "canonical_url": "https://gitlab.com/group/subgroup/repo",
            "fqn": "group/subgroup/repo",
            "short_name": "repo",
        }

    def test_bitbucket_repo(self):
        """Parse Bitbucket repository URL."""
        url = "https://bitbucket.org/owner/repo"
        result = parse_repo_url(url)
        assert result == {
            "canonical_url": "https://bitbucket.org/owner/repo",
            "fqn": "owner/repo",
            "short_name": "repo",
        }

    def test_invalid_url(self):
        """Return None for invalid URL."""
        url = "https://example.com/not/a/repo"
        assert parse_repo_url(url) is None

    def test_empty_url(self):
        """Return None for empty URL."""
        assert parse_repo_url("") is None


class TestParseRefUrl:
    """Tests for parse_ref_url function."""

    def test_github_pr(self):
        """Parse GitHub PR URL."""
        url = "https://github.com/owner/repo/pull/123"
        result = parse_ref_url(url, "pr")
        assert result == {
            "ref_type": "pr",
            "url": url,
            "fqn": "owner/repo#123",
            "display_name": "repo #123",
        }

    def test_github_issue(self):
        """Parse GitHub issue URL."""
        url = "https://github.com/owner/repo/issues/456"
        result = parse_ref_url(url, "issue")
        assert result == {
            "ref_type": "issue",
            "url": url,
            "fqn": "owner/repo#456",
            "display_name": "repo #456",
        }

    def test_gitlab_mr(self):
        """Parse GitLab merge request URL."""
        url = "https://gitlab.com/group/repo/-/merge_requests/789"
        result = parse_ref_url(url, "pr")
        assert result == {
            "ref_type": "pr",
            "url": url,
            "fqn": "group/repo!789",
            "display_name": "repo !789",
        }

    def test_gitlab_mr_nested_group(self):
        """Parse GitLab MR with nested groups."""
        url = "https://gitlab.com/group/subgroup/repo/-/merge_requests/100"
        result = parse_ref_url(url, "pr")
        assert result == {
            "ref_type": "pr",
            "url": url,
            "fqn": "group/subgroup/repo!100",
            "display_name": "repo !100",
        }

    def test_gitlab_issue(self):
        """Parse GitLab issue URL."""
        url = "https://gitlab.com/group/repo/-/issues/321"
        result = parse_ref_url(url, "issue")
        assert result == {
            "ref_type": "issue",
            "url": url,
            "fqn": "group/repo#321",
            "display_name": "repo #321",
        }

    def test_bitbucket_pr(self):
        """Parse Bitbucket PR URL."""
        url = "https://bitbucket.org/owner/repo/pull-requests/42"
        result = parse_ref_url(url, "pr")
        assert result == {
            "ref_type": "pr",
            "url": url,
            "fqn": "owner/repo#42",
            "display_name": "repo #42",
        }

    def test_bitbucket_issue(self):
        """Parse Bitbucket issue URL."""
        url = "https://bitbucket.org/owner/repo/issues/99"
        result = parse_ref_url(url, "issue")
        assert result == {
            "ref_type": "issue",
            "url": url,
            "fqn": "owner/repo#99",
            "display_name": "repo #99",
        }

    def test_invalid_url(self):
        """Return None for invalid URL."""
        url = "https://example.com/not/a/ref"
        assert parse_ref_url(url, "pr") is None

    def test_ref_type_passed_through(self):
        """Ref type is preserved in result."""
        url = "https://github.com/owner/repo/pull/1"
        result = parse_ref_url(url, "issue")  # Type mismatch but should work
        assert result["ref_type"] == "issue"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
