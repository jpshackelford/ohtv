"""Unit tests for CLI gen run command argument parsing and validation.

These tests verify argument parsing, error messages, and basic validation
without executing actual analysis (no mocked LLM needed).
"""

import pytest
from click.testing import CliRunner

from ohtv.cli import main


@pytest.fixture
def runner():
    """Create a Click test runner with isolated environment."""
    return CliRunner()


class TestGenRunHelp:
    """Tests for gen run help output."""

    def test_help_displays(self, runner):
        """Test that help text is displayed."""
        result = runner.invoke(main, ["gen", "run", "--help"])
        assert result.exit_code == 0
        assert "Run an analysis job by ID" in result.output

    def test_help_shows_aggregate_examples(self, runner):
        """Test that help includes aggregate job examples."""
        result = runner.invoke(main, ["gen", "run", "--help"])
        assert "AGGREGATE JOBS" in result.output
        assert "reports.weekly" in result.output

    def test_help_shows_period_options(self, runner):
        """Test that help shows period iteration options."""
        result = runner.invoke(main, ["gen", "run", "--help"])
        assert "--per" in result.output
        assert "--last" in result.output
        assert "week" in result.output


class TestJobIdArgumentParsing:
    """Tests for job ID argument parsing."""

    def test_job_id_required(self, runner):
        """Test that job ID is required."""
        result = runner.invoke(main, ["gen", "run"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "Usage:" in result.output

    def test_job_id_format_validation(self, runner):
        """Test that job ID without dot shows clear error."""
        result = runner.invoke(main, ["gen", "run", "invalid"])
        assert result.exit_code != 0
        assert "family.variant" in result.output

    def test_job_id_with_dot_accepted(self, runner):
        """Test that job ID with dot format is accepted (may fail for other reasons)."""
        result = runner.invoke(main, ["gen", "run", "test.job"])
        # Should NOT fail due to format validation
        assert "family.variant" not in result.output


class TestPeriodOptions:
    """Tests for period-related option parsing."""

    def test_per_option_accepts_valid_values(self, runner):
        """Test that --per accepts week, day, month."""
        for period in ["week", "day", "month"]:
            result = runner.invoke(main, ["gen", "run", "test.job", "--per", period])
            # Should not fail due to invalid choice
            assert f"invalid choice: {period}" not in result.output.lower()

    def test_per_option_rejects_invalid_values(self, runner):
        """Test that --per rejects invalid period types."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--per", "quarter"])
        assert result.exit_code != 0
        assert "invalid choice" in result.output.lower() or "Invalid value" in result.output

    def test_last_option_accepts_integer(self, runner):
        """Test that --last accepts integer values."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--last", "4"])
        # Should not fail due to type validation
        assert "not a valid integer" not in result.output.lower()

    def test_last_option_rejects_non_integer(self, runner):
        """Test that --last rejects non-integer values."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--last", "abc"])
        assert result.exit_code != 0


class TestDateOptions:
    """Tests for date filter option parsing."""

    def test_since_option_accepted(self, runner):
        """Test that --since is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--since", "2024-01-01"])
        # Should not fail due to option not recognized
        assert "no such option" not in result.output.lower()

    def test_until_option_accepted(self, runner):
        """Test that --until is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--until", "2024-12-31"])
        # Should not fail due to option not recognized
        assert "no such option" not in result.output.lower()

    def test_week_flag_accepted(self, runner):
        """Test that --week flag is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--week"])
        # Should not fail due to option not recognized
        assert "no such option" not in result.output.lower()

    def test_day_flag_accepted(self, runner):
        """Test that --day flag is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--day"])
        # Should not fail due to option not recognized
        assert "no such option" not in result.output.lower()


class TestOutputOptions:
    """Tests for output format options."""

    def test_format_option_accepts_table(self, runner):
        """Test that --format accepts 'table'."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--format", "table"])
        assert "invalid choice: table" not in result.output.lower()

    def test_format_option_accepts_json(self, runner):
        """Test that --format accepts 'json'."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--format", "json"])
        assert "invalid choice: json" not in result.output.lower()

    def test_format_option_accepts_markdown(self, runner):
        """Test that --format accepts 'markdown'."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--format", "markdown"])
        assert "invalid choice: markdown" not in result.output.lower()

    def test_format_option_rejects_invalid(self, runner):
        """Test that --format rejects invalid values."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--format", "xml"])
        assert result.exit_code != 0

    def test_out_option_accepted(self, runner):
        """Test that --out is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--out", "/tmp/output"])
        assert "no such option" not in result.output.lower()


class TestConfirmationFlags:
    """Tests for confirmation-related flags."""

    def test_yes_flag_accepted(self, runner):
        """Test that -y/--yes flag is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "-y"])
        assert "no such option" not in result.output.lower()

        result = runner.invoke(main, ["gen", "run", "test.job", "--yes"])
        assert "no such option" not in result.output.lower()

    def test_refresh_flag_accepted(self, runner):
        """Test that --refresh flag is accepted."""
        result = runner.invoke(main, ["gen", "run", "test.job", "--refresh"])
        assert "no such option" not in result.output.lower()


class TestOptionShortcuts:
    """Tests for option shortcuts."""

    def test_s_shortcut_for_since(self, runner):
        """Test that -S is shortcut for --since."""
        result = runner.invoke(main, ["gen", "run", "test.job", "-S", "2024-01-01"])
        assert "no such option: -S" not in result.output

    def test_u_shortcut_for_until(self, runner):
        """Test that -U is shortcut for --until."""
        result = runner.invoke(main, ["gen", "run", "test.job", "-U", "2024-12-31"])
        assert "no such option: -U" not in result.output

    def test_w_shortcut_for_week(self, runner):
        """Test that -W is shortcut for --week."""
        result = runner.invoke(main, ["gen", "run", "test.job", "-W"])
        assert "no such option: -W" not in result.output

    def test_d_shortcut_for_day(self, runner):
        """Test that -D is shortcut for --day."""
        result = runner.invoke(main, ["gen", "run", "test.job", "-D"])
        assert "no such option: -D" not in result.output

    def test_f_shortcut_for_format(self, runner):
        """Test that -F is shortcut for --format."""
        result = runner.invoke(main, ["gen", "run", "test.job", "-F", "json"])
        assert "no such option: -F" not in result.output


class TestCombinedOptions:
    """Tests for combined option scenarios."""

    def test_combined_period_and_last(self, runner):
        """Test --per and --last can be combined."""
        result = runner.invoke(main, [
            "gen", "run", "test.job",
            "--per", "week",
            "--last", "4",
            "-y"
        ])
        # Should not fail due to incompatible options
        assert "cannot be used" not in result.output.lower()

    def test_combined_date_range(self, runner):
        """Test --since and --until can be combined."""
        result = runner.invoke(main, [
            "gen", "run", "test.job",
            "--since", "2024-01-01",
            "--until", "2024-03-31",
            "-y"
        ])
        # Should not fail due to incompatible options
        assert "cannot be used" not in result.output.lower()


class TestErrorMessages:
    """Tests for error message quality."""

    def test_invalid_job_shows_available_families(self, runner):
        """Test that invalid job shows available families hint."""
        result = runner.invoke(main, ["gen", "run", "nonexistent.job"])
        # Should show available families
        if "Error" in result.output:
            # Check for helpful hint
            assert "families" in result.output.lower() or "objs" in result.output

    def test_single_trajectory_job_shows_alternative(self, runner):
        """Test that single-trajectory jobs show alternative command."""
        result = runner.invoke(main, ["gen", "run", "objs.brief"])
        # Should suggest alternative command
        if "single-trajectory" in result.output.lower():
            assert "gen objs" in result.output
