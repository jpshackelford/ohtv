"""CLI-side logging glue (Issue #121).

Covers ``ohtv.cli_logging.logging_options`` and
``init_logging_from_cli``: option propagation through Click context,
``--verbose`` deprecation warning, and the new
``--log-level`` / ``--log-file`` flags.
"""

from __future__ import annotations

import logging
import sys

import click
from click.testing import CliRunner

import pytest

from ohtv import cli_logging
from ohtv.cli_logging import (
    init_logging_from_cli,
    logging_options,
    reset_verbose_warning_state,
)


@pytest.fixture(autouse=True)
def _reset_state(tmp_path, monkeypatch):
    """Reset module + ohtv logger state between tests."""
    monkeypatch.setenv("OHTV_DIR", str(tmp_path))
    reset_verbose_warning_state()
    logger = logging.getLogger("ohtv")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    yield
    reset_verbose_warning_state()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _make_app(tmp_path):
    """Construct a one-command Click app that exercises the decorator."""
    @click.command()
    @logging_options
    @click.option("--verbose", "-v", is_flag=True)
    def cmd(verbose: bool):
        init_logging_from_cli(verbose=verbose)
        logger = logging.getLogger("ohtv")
        # Print the resolved file-handler level for assertion.
        levels = sorted(h.level for h in logger.handlers)
        click.echo(",".join(str(l) for l in levels))

    return cmd


class TestLoggingOptionsDecorator:
    def test_flags_appear_in_help(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, ["--help"])
        assert result.exit_code == 0
        assert "--log-level" in result.output
        assert "--log-file" in result.output
        assert "--log-stderr" in result.output

    def test_no_flags_yields_info_level(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, [])
        assert result.exit_code == 0, result.output
        # Only file handler; level=INFO=20.
        assert "20" in result.output

    def test_log_level_debug(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, ["--log-level", "DEBUG"])
        assert result.exit_code == 0, result.output
        # File handler at DEBUG=10.
        assert "10" in result.output

    def test_log_level_case_insensitive(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        # Lowercase should be accepted.
        result = runner.invoke(cmd, ["--log-level", "warning"])
        assert result.exit_code == 0, result.output
        assert "30" in result.output  # WARNING == 30

    def test_log_stderr_adds_handler(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, ["--log-stderr", "--log-level", "INFO"])
        assert result.exit_code == 0, result.output
        # Two handlers (file + stderr) both at INFO=20.
        assert result.output.strip() == "20,20"

    def test_log_file_overrides_default(self, tmp_path):
        target = tmp_path / "logs" / "custom.log"
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, ["--log-file", str(target), "--log-level", "DEBUG"])
        assert result.exit_code == 0, result.output
        logger = logging.getLogger("ohtv")
        logger.info("hi from custom log")
        for h in logger.handlers:
            h.flush()
        assert target.exists()


class TestVerboseDeprecation:
    def test_verbose_emits_one_shot_warning(self, tmp_path, capsys):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, ["--verbose"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        # CliRunner captures the stderr by default in result.stderr_bytes
        # when mix_stderr is False; we wrote with raw sys.stderr.write,
        # which Click captures via output by default.
        assert "deprecated" in result.output.lower() or "deprecated" in (
            getattr(result, "stderr", "") or ""
        ).lower()

    def test_verbose_only_warns_once_per_process(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        # First invocation prints the note.
        first = runner.invoke(cmd, ["--verbose"], catch_exceptions=False)
        # Second invocation reuses the module-level flag (test fixture
        # resets between tests; here we want to assert NO reset).
        second = runner.invoke(cmd, ["--verbose"], catch_exceptions=False)
        assert first.exit_code == 0
        assert second.exit_code == 0
        # Only the first should have the warning string.
        first_has = "deprecated" in (first.output + getattr(first, "stderr", "")).lower()
        second_has = "deprecated" in (second.output + getattr(second, "stderr", "")).lower()
        assert first_has
        assert not second_has

    def test_verbose_sets_debug_level_and_stderr(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cmd, ["--verbose"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        # Output is the comma-joined levels; expect "10,10" (file + stderr).
        levels_line = [
            ln for ln in result.output.splitlines() if all(c.isdigit() or c == "," for c in ln)
        ]
        assert levels_line, f"no levels line in {result.output!r}"
        assert "10" in levels_line[-1]

    def test_explicit_log_level_overrides_verbose(self, tmp_path):
        cmd = _make_app(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cmd, ["--verbose", "--log-level", "WARNING"], catch_exceptions=False
        )
        assert result.exit_code == 0, result.output
        # Explicit --log-level WARNING (30) wins; stderr handler also added
        # because --verbose is True.
        # Two handlers, both at WARNING=30.
        levels_line = [
            ln for ln in result.output.splitlines() if all(c.isdigit() or c == "," for c in ln)
        ]
        assert levels_line[-1] == "30,30"
