"""Unit tests for summary command analysis options."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ohtv.cli import main


class TestSummaryCommandOptions:
    """Test summary command CLI options for --detail, --context, and --assess."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def mock_basic(self):
        """Basic mocks to allow command to run."""
        with patch('ohtv.cli.Config.from_env'), \
             patch('ohtv.cli._load_all_conversations', return_value=[]):
            yield

    def test_detail_option_accepts_brief(self, runner, mock_basic):
        """Test that --detail accepts 'brief' value."""
        result = runner.invoke(main, ['summary', '--detail', 'brief'])
        assert result.exit_code == 0

    def test_detail_option_accepts_standard(self, runner, mock_basic):
        """Test that --detail accepts 'standard' value."""
        result = runner.invoke(main, ['summary', '--detail', 'standard'])
        assert result.exit_code == 0

    def test_detail_option_accepts_detailed(self, runner, mock_basic):
        """Test that --detail accepts 'detailed' value."""
        result = runner.invoke(main, ['summary', '--detail', 'detailed'])
        assert result.exit_code == 0

    def test_detail_option_rejects_invalid_value(self, runner, mock_basic):
        """Test that --detail rejects invalid values."""
        result = runner.invoke(main, ['summary', '--detail', 'invalid'])
        assert result.exit_code != 0
        assert 'invalid' in result.output.lower() or 'choice' in result.output.lower()

    def test_context_option_accepts_minimal(self, runner, mock_basic):
        """Test that --context accepts 'minimal' value."""
        result = runner.invoke(main, ['summary', '--context', 'minimal'])
        assert result.exit_code == 0

    def test_context_option_accepts_default(self, runner, mock_basic):
        """Test that --context accepts 'default' value."""
        result = runner.invoke(main, ['summary', '--context', 'default'])
        assert result.exit_code == 0

    def test_context_option_accepts_full(self, runner, mock_basic):
        """Test that --context accepts 'full' value."""
        result = runner.invoke(main, ['summary', '--context', 'full'])
        assert result.exit_code == 0

    def test_context_option_rejects_invalid_value(self, runner, mock_basic):
        """Test that --context rejects invalid values."""
        result = runner.invoke(main, ['summary', '--context', 'invalid'])
        assert result.exit_code != 0
        assert 'invalid' in result.output.lower() or 'choice' in result.output.lower()

    def test_assess_option_is_boolean_flag(self, runner, mock_basic):
        """Test that --assess is a boolean flag."""
        result = runner.invoke(main, ['summary', '--assess'])
        assert result.exit_code == 0

    def test_short_options_work(self, runner, mock_basic):
        """Test that short options -d, -c, -a work."""
        result = runner.invoke(main, ['summary', '-d', 'standard', '-c', 'full', '-a'])
        assert result.exit_code == 0

    def test_all_options_combined(self, runner, mock_basic):
        """Test all three options can be used together."""
        result = runner.invoke(main, [
            'summary',
            '--detail', 'detailed',
            '--context', 'full',
            '--assess'
        ])
        assert result.exit_code == 0
