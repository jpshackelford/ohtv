"""Tests for ohtv list --with-outcomes and --enriched flags (Issue #190)."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ohtv.cli import (
    Outcome,
    _format_outcome,
    _format_outcomes_list,
    _load_outcomes_for_conversations,
    main,
)
from ohtv.sources.base import ConversationInfo


class TestOutcomeDataclass:
    """Test the Outcome dataclass."""

    def test_outcome_creation(self):
        """Test creating an Outcome object."""
        outcome = Outcome(
            type="PR",
            number=123,
            state="merged",
            repo="owner/repo",
            url="https://github.com/owner/repo/pull/123",
        )
        assert outcome.type == "PR"
        assert outcome.number == 123
        assert outcome.state == "merged"
        assert outcome.repo == "owner/repo"
        assert outcome.url == "https://github.com/owner/repo/pull/123"


class TestFormatOutcome:
    """Test _format_outcome helper function."""

    def test_format_merged_pr(self):
        """Test formatting a merged PR."""
        outcome = Outcome(
            type="PR",
            number=15234,
            state="merged",
            repo="owner/repo",
            url="https://github.com/owner/repo/pull/15234",
        )
        result = _format_outcome(outcome)
        assert result == "✓ PR #15234"

    def test_format_open_pr(self):
        """Test formatting an open PR."""
        outcome = Outcome(
            type="PR",
            number=15240,
            state="open",
            repo="owner/repo",
            url="https://github.com/owner/repo/pull/15240",
        )
        result = _format_outcome(outcome)
        assert result == "→ PR #15240"

    def test_format_closed_pr(self):
        """Test formatting a closed (unmerged) PR."""
        outcome = Outcome(
            type="PR",
            number=100,
            state="closed",
            repo="owner/repo",
            url="https://github.com/owner/repo/pull/100",
        )
        result = _format_outcome(outcome)
        assert result == "✓ PR #100"

    def test_format_open_issue(self):
        """Test formatting an open issue."""
        outcome = Outcome(
            type="Issue",
            number=15198,
            state="open",
            repo="owner/repo",
            url="https://github.com/owner/repo/issues/15198",
        )
        result = _format_outcome(outcome)
        assert result == "→ Issue #15198"

    def test_format_outcome_truncation(self):
        """Test that very long outcomes are truncated."""
        outcome = Outcome(
            type="PR",
            number=999999999,
            state="merged",
            repo="very-long-owner/very-long-repo-name",
            url="https://github.com/...",
        )
        result = _format_outcome(outcome, max_width=15)
        # The output "✓ PR #999999999" is 16 chars, should be truncated to 15
        assert len(result) <= 15
        # Due to truncation happening, it should end with ellipsis
        if len("✓ PR #999999999") > 15:
            assert result.endswith("…")


class TestFormatOutcomesList:
    """Test _format_outcomes_list helper function."""

    def test_empty_list(self):
        """Test formatting an empty outcomes list."""
        result = _format_outcomes_list([])
        assert result == "(no refs)"

    def test_single_outcome(self):
        """Test formatting a list with one outcome."""
        outcomes = [
            Outcome(
                type="PR",
                number=123,
                state="merged",
                repo="owner/repo",
                url="https://github.com/owner/repo/pull/123",
            )
        ]
        result = _format_outcomes_list(outcomes)
        assert result == "✓ PR #123"

    def test_multiple_outcomes(self):
        """Test formatting a list with multiple outcomes."""
        outcomes = [
            Outcome(
                type="PR",
                number=123,
                state="merged",
                repo="owner/repo",
                url="https://github.com/owner/repo/pull/123",
            ),
            Outcome(
                type="Issue",
                number=456,
                state="open",
                repo="owner/repo",
                url="https://github.com/owner/repo/issues/456",
            ),
        ]
        result = _format_outcomes_list(outcomes)
        assert result == "✓ PR #123, → Issue #456"

    def test_truncation_at_three(self):
        """Test that more than 3 outcomes are truncated with '+ N more'."""
        outcomes = [
            Outcome(type="PR", number=1, state="merged", repo="r/r", url="url1"),
            Outcome(type="PR", number=2, state="merged", repo="r/r", url="url2"),
            Outcome(type="PR", number=3, state="open", repo="r/r", url="url3"),
            Outcome(type="PR", number=4, state="open", repo="r/r", url="url4"),
            Outcome(type="PR", number=5, state="open", repo="r/r", url="url5"),
        ]
        result = _format_outcomes_list(outcomes)
        assert "✓ PR #1" in result
        assert "✓ PR #2" in result
        assert "→ PR #3" in result
        assert "+ 2 more" in result
        assert "PR #4" not in result
        assert "PR #5" not in result

    def test_max_width_truncation(self):
        """Test that the result is truncated if it exceeds max_width."""
        outcomes = [
            Outcome(type="PR", number=1, state="merged", repo="r/r", url="url1"),
            Outcome(type="PR", number=2, state="merged", repo="r/r", url="url2"),
        ]
        result = _format_outcomes_list(outcomes, max_width=15)
        assert len(result) <= 15
        # Should be truncated with ellipsis
        assert result.endswith("…")


class TestLoadOutcomesForConversations:
    """Test _load_outcomes_for_conversations loader function."""

    def test_empty_list(self):
        """Test loading outcomes for empty conversation list."""
        result = _load_outcomes_for_conversations([])
        assert result == {}

    @patch("ohtv.db.get_db_path")
    def test_no_database(self, mock_get_db_path):
        """Test graceful fallback when database doesn't exist."""
        mock_db_path = MagicMock()
        mock_db_path.exists.return_value = False
        mock_get_db_path.return_value = mock_db_path

        conv = ConversationInfo(
            id="abc123",
            title=None,
            created_at=None,
            updated_at=None,
            source="cloud",
        )
        result = _load_outcomes_for_conversations([conv])
        assert result == {}

    @patch("ohtv.db.get_ready_connection")
    @patch("ohtv.db.get_db_path")
    def test_load_pr_outcomes(self, mock_get_db_path, mock_get_ready_connection):
        """Test loading PR outcomes from database."""
        # Mock database path
        mock_db_path = MagicMock()
        mock_db_path.exists.return_value = True
        mock_get_db_path.return_value = mock_db_path

        # Mock database connection
        mock_conn = MagicMock()
        
        # Mock PR query results (conversation_id, pr_number, status, owner, repo_name)
        pr_rows = [
            ("abc123", 15234, "merged", "owner", "repo"),
            ("abc123", 15240, "open", "owner", "repo"),
        ]
        
        # Mock issue query results (empty)
        issue_rows = []
        
        # Set up execute to return different results for each query
        mock_conn.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=pr_rows)),
            MagicMock(fetchall=MagicMock(return_value=issue_rows)),
        ]
        
        mock_get_ready_connection.return_value.__enter__.return_value = mock_conn

        conv = ConversationInfo(
            id="abc123",
            title=None,
            created_at=None,
            updated_at=None,
            source="cloud",
        )
        result = _load_outcomes_for_conversations([conv])

        assert "abc123" in result
        assert len(result["abc123"]) == 2
        
        # Check first PR (merged)
        assert result["abc123"][0].type == "PR"
        assert result["abc123"][0].number == 15234
        assert result["abc123"][0].state == "merged"
        assert result["abc123"][0].repo == "owner/repo"
        
        # Check second PR (open)
        assert result["abc123"][1].type == "PR"
        assert result["abc123"][1].number == 15240
        assert result["abc123"][1].state == "open"

    @patch("ohtv.db.get_ready_connection")
    @patch("ohtv.db.get_db_path")
    def test_load_issue_outcomes(self, mock_get_db_path, mock_get_ready_connection):
        """Test loading issue outcomes from database."""
        # Mock database path
        mock_db_path = MagicMock()
        mock_db_path.exists.return_value = True
        mock_get_db_path.return_value = mock_db_path

        # Mock database connection
        mock_conn = MagicMock()
        
        # Mock PR query results (empty)
        pr_rows = []
        
        # Mock issue query results (conversation_id, fqn, url)
        issue_rows = [
            ("abc123", "owner/repo#15198", "https://github.com/owner/repo/issues/15198"),
        ]
        
        mock_conn.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=pr_rows)),
            MagicMock(fetchall=MagicMock(return_value=issue_rows)),
        ]
        
        mock_get_ready_connection.return_value.__enter__.return_value = mock_conn

        conv = ConversationInfo(
            id="abc123",
            title=None,
            created_at=None,
            updated_at=None,
            source="cloud",
        )
        result = _load_outcomes_for_conversations([conv])

        assert "abc123" in result
        assert len(result["abc123"]) == 1
        
        # Check issue
        assert result["abc123"][0].type == "Issue"
        assert result["abc123"][0].number == 15198
        assert result["abc123"][0].state == "open"  # Issues always show as open
        assert result["abc123"][0].repo == "owner/repo"

    @patch("ohtv.db.get_ready_connection")
    @patch("ohtv.db.get_db_path")
    def test_malformed_issue_fqn_skipped(self, mock_get_db_path, mock_get_ready_connection):
        """Test that issues with malformed FQN are skipped."""
        mock_db_path = MagicMock()
        mock_db_path.exists.return_value = True
        mock_get_db_path.return_value = mock_db_path

        mock_conn = MagicMock()
        
        # Mock issue with malformed FQN (no # or non-numeric number)
        issue_rows = [
            ("abc123", "owner/repo-no-hash", "https://github.com/..."),
            ("abc123", "owner/repo#abc", "https://github.com/..."),  # non-numeric
        ]
        
        mock_conn.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[])),  # PRs
            MagicMock(fetchall=MagicMock(return_value=issue_rows)),  # Issues
        ]
        
        mock_get_ready_connection.return_value.__enter__.return_value = mock_conn

        conv = ConversationInfo(
            id="abc123",
            title=None,
            created_at=None,
            updated_at=None,
            source="cloud",
        )
        result = _load_outcomes_for_conversations([conv])

        # Both malformed issues should be skipped
        assert result.get("abc123", []) == []

    @patch("ohtv.db.get_ready_connection")
    @patch("ohtv.db.get_db_path")
    def test_outcomes_sorted(self, mock_get_db_path, mock_get_ready_connection):
        """Test that outcomes are sorted by type (PRs first) then by number."""
        mock_db_path = MagicMock()
        mock_db_path.exists.return_value = True
        mock_get_db_path.return_value = mock_db_path

        mock_conn = MagicMock()
        
        # Return PRs and issues in mixed order
        pr_rows = [
            ("abc123", 300, "open", "owner", "repo"),
            ("abc123", 100, "merged", "owner", "repo"),
        ]
        issue_rows = [
            ("abc123", "owner/repo#50", "url"),
        ]
        
        mock_conn.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=pr_rows)),
            MagicMock(fetchall=MagicMock(return_value=issue_rows)),
        ]
        
        mock_get_ready_connection.return_value.__enter__.return_value = mock_conn

        conv = ConversationInfo(
            id="abc123",
            title=None,
            created_at=None,
            updated_at=None,
            source="cloud",
        )
        result = _load_outcomes_for_conversations([conv])

        # PRs should come first, sorted by number
        assert len(result["abc123"]) == 3
        assert result["abc123"][0].type == "PR"
        assert result["abc123"][0].number == 100
        assert result["abc123"][1].type == "PR"
        assert result["abc123"][1].number == 300
        assert result["abc123"][2].type == "Issue"
        assert result["abc123"][2].number == 50


class TestListCommandIntegration:
    """Integration tests for ohtv list command with outcomes."""

    @patch("ohtv.cli._load_outcomes_for_conversations")
    @patch("ohtv.cli._apply_conversation_filters")
    @patch("ohtv.cli.Config")
    def test_with_outcomes_flag(
        self, mock_config, mock_apply_filters, mock_load_outcomes
    ):
        """Test that --with-outcomes flag triggers outcomes loading."""
        runner = CliRunner()
        
        # Mock filter result
        mock_filter_result = MagicMock()
        mock_filter_result.conversations = []
        mock_filter_result.possible_match_ids = set()
        mock_filter_result.show_all = True
        mock_apply_filters.return_value = mock_filter_result
        
        mock_load_outcomes.return_value = {}

        runner.invoke(main, ["list", "--with-outcomes", "-A"])
        
        # Should call the outcomes loader
        assert mock_load_outcomes.called

    @patch("ohtv.cli._load_outcomes_for_conversations")
    @patch("ohtv.cli._load_engagement_for_conversations")
    @patch("ohtv.cli._apply_conversation_filters")
    @patch("ohtv.cli.Config")
    def test_enriched_flag(
        self, mock_config, mock_apply_filters, mock_load_engagement, mock_load_outcomes
    ):
        """Test that --enriched flag triggers both engagement and outcomes loading."""
        runner = CliRunner()
        
        mock_filter_result = MagicMock()
        mock_filter_result.conversations = []
        mock_filter_result.possible_match_ids = set()
        mock_filter_result.show_all = True
        mock_apply_filters.return_value = mock_filter_result
        
        mock_load_engagement.return_value = {}
        mock_load_outcomes.return_value = {}

        runner.invoke(main, ["list", "--enriched", "-A"])
        
        # Should call both loaders
        assert mock_load_engagement.called
        assert mock_load_outcomes.called

    @patch("ohtv.cli._load_outcomes_for_conversations")
    @patch("ohtv.cli._apply_conversation_filters")
    @patch("ohtv.cli.Config")
    def test_json_format_includes_outcomes(
        self, mock_config, mock_apply_filters, mock_load_outcomes
    ):
        """Test that --format json includes outcomes field."""
        from datetime import datetime, timezone

        runner = CliRunner()
        
        # Create a test conversation
        conv = ConversationInfo(
            id="abc123",
            title="Test Conv",
            created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            event_count=10,
            source="cloud",
        )
        
        mock_filter_result = MagicMock()
        mock_filter_result.conversations = [conv]
        mock_filter_result.possible_match_ids = set()
        mock_filter_result.show_all = True
        mock_apply_filters.return_value = mock_filter_result
        
        # Mock outcomes
        mock_load_outcomes.return_value = {
            "abc123": [
                Outcome(
                    type="PR",
                    number=123,
                    state="merged",
                    repo="owner/repo",
                    url="https://github.com/owner/repo/pull/123",
                )
            ]
        }

        result = runner.invoke(main, ["list", "--with-outcomes", "-F", "json", "-A"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        output_data = json.loads(result.output)
        assert len(output_data) == 1
        assert "outcomes" in output_data[0]
        assert len(output_data[0]["outcomes"]) == 1
        assert output_data[0]["outcomes"][0]["type"] == "pr"
        assert output_data[0]["outcomes"][0]["number"] == 123
        assert output_data[0]["outcomes"][0]["state"] == "merged"

    @patch("ohtv.cli._load_outcomes_for_conversations")
    @patch("ohtv.cli._apply_conversation_filters")
    @patch("ohtv.cli.Config")
    def test_csv_format_includes_outcomes(
        self, mock_config, mock_apply_filters, mock_load_outcomes
    ):
        """Test that --format csv includes outcomes column."""
        from datetime import datetime, timezone

        runner = CliRunner()
        
        conv = ConversationInfo(
            id="abc123",
            title="Test Conv",
            created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            event_count=10,
            source="cloud",
        )
        
        mock_filter_result = MagicMock()
        mock_filter_result.conversations = [conv]
        mock_filter_result.possible_match_ids = set()
        mock_filter_result.show_all = True
        mock_apply_filters.return_value = mock_filter_result
        
        mock_load_outcomes.return_value = {
            "abc123": [
                Outcome(
                    type="PR",
                    number=123,
                    state="merged",
                    repo="owner/repo",
                    url="https://github.com/owner/repo/pull/123",
                )
            ]
        }

        result = runner.invoke(main, ["list", "--with-outcomes", "-F", "csv", "-A"])
        
        assert result.exit_code == 0
        
        # Check CSV header and data
        lines = result.output.strip().split("\n")
        headers = lines[0].split(",")
        assert "outcomes" in headers
        
        # Check that outcomes column has data
        data = lines[1]
        assert "✓ PR #123" in data
