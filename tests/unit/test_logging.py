"""Tests for ``ohtv.logging`` (Issue #121)."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import pytest

from ohtv import logging as ohtv_logging
from ohtv.logging import (
    get_log_file_path,
    get_logger,
    resolve_log_file,
    resolve_log_level,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path, monkeypatch):
    """Redirect ``~/.ohtv`` to a fresh tmp dir + tear down any handlers
    we install during the test."""
    monkeypatch.setenv("OHTV_DIR", str(tmp_path))
    # Drop any handlers left behind by prior tests / imports.
    logger = logging.getLogger("ohtv")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# resolve_log_level
# ---------------------------------------------------------------------------

class TestResolveLogLevel:
    def test_default_is_info(self):
        assert resolve_log_level(None, env={}) == logging.INFO

    def test_cli_overrides_default(self):
        assert resolve_log_level("DEBUG", env={}) == logging.DEBUG

    def test_env_overrides_default(self):
        assert resolve_log_level(None, env={"OHTV_LOG_LEVEL": "WARNING"}) == logging.WARNING

    def test_cli_overrides_env(self):
        assert (
            resolve_log_level("ERROR", env={"OHTV_LOG_LEVEL": "WARNING"})
            == logging.ERROR
        )

    def test_case_insensitive(self):
        assert resolve_log_level("debug", env={}) == logging.DEBUG
        assert resolve_log_level("Info", env={}) == logging.INFO

    def test_int_passthrough(self):
        assert resolve_log_level(logging.CRITICAL, env={}) == logging.CRITICAL

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid log level"):
            resolve_log_level("LOUD", env={})

    def test_empty_env_treated_as_unset(self):
        assert resolve_log_level(None, env={"OHTV_LOG_LEVEL": ""}) == logging.INFO


# ---------------------------------------------------------------------------
# resolve_log_file
# ---------------------------------------------------------------------------

class TestResolveLogFile:
    def test_default_path(self, tmp_path):
        result = resolve_log_file(None, env={})
        assert isinstance(result, Path)
        assert result.name == "ohtv.log"
        assert result.parent.name == "logs"

    def test_cli_path(self, tmp_path):
        target = tmp_path / "custom.log"
        assert resolve_log_file(str(target), env={}) == target

    def test_env_path(self, tmp_path):
        target = tmp_path / "from-env.log"
        assert resolve_log_file(None, env={"OHTV_LOG_FILE": str(target)}) == target

    def test_cli_overrides_env(self, tmp_path):
        cli_target = tmp_path / "cli.log"
        env_target = tmp_path / "env.log"
        result = resolve_log_file(str(cli_target), env={"OHTV_LOG_FILE": str(env_target)})
        assert result == cli_target

    def test_dash_returns_stderr_sentinel(self):
        assert resolve_log_file("-", env={}) == "-"

    def test_dev_null_returns_none(self):
        assert resolve_log_file("/dev/null", env={}) is None

    def test_nul_returns_none(self):
        assert resolve_log_file("nul", env={}) is None

    def test_pathlib_input(self, tmp_path):
        target = tmp_path / "p.log"
        assert resolve_log_file(target, env={}) == target

    def test_expand_user(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = resolve_log_file("~/foo.log", env={})
        assert result == tmp_path / "foo.log"


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

def _file_handlers(logger):
    return [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]


def _stderr_handlers(logger):
    return [
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "stream", None) is sys.stderr
    ]


class TestSetupLogging:
    def test_default_installs_file_handler_only(self, tmp_path):
        logger = setup_logging(env={})
        assert len(_file_handlers(logger)) == 1
        assert len(_stderr_handlers(logger)) == 0
        # Root level stays at DEBUG; handler is at INFO.
        assert logger.level == logging.DEBUG
        assert _file_handlers(logger)[0].level == logging.INFO

    def test_explicit_level(self):
        logger = setup_logging(level="WARNING", env={})
        assert _file_handlers(logger)[0].level == logging.WARNING

    def test_env_level_picked_up(self, monkeypatch):
        monkeypatch.setenv("OHTV_LOG_LEVEL", "ERROR")
        logger = setup_logging()
        assert _file_handlers(logger)[0].level == logging.ERROR

    def test_cli_level_beats_env(self, monkeypatch):
        monkeypatch.setenv("OHTV_LOG_LEVEL", "ERROR")
        logger = setup_logging(level="DEBUG")
        assert _file_handlers(logger)[0].level == logging.DEBUG

    def test_stderr_handler_added(self):
        logger = setup_logging(stderr=True, env={})
        assert len(_stderr_handlers(logger)) == 1
        assert _stderr_handlers(logger)[0].level == logging.INFO

    def test_custom_log_file_path(self, tmp_path):
        target = tmp_path / "custom.log"
        logger = setup_logging(log_file=target, env={})
        handlers = _file_handlers(logger)
        assert len(handlers) == 1
        assert Path(handlers[0].baseFilename) == target
        # File is created on first emit.
        logger.warning("hi")
        for h in handlers:
            h.flush()
        assert target.exists()
        assert "hi" in target.read_text()

    def test_env_log_file_path(self, tmp_path, monkeypatch):
        target = tmp_path / "env-default.log"
        monkeypatch.setenv("OHTV_LOG_FILE", str(target))
        logger = setup_logging()
        handlers = _file_handlers(logger)
        assert Path(handlers[0].baseFilename) == target

    def test_dash_log_file_means_stderr_only(self):
        logger = setup_logging(log_file="-", env={})
        assert len(_file_handlers(logger)) == 0
        assert len(_stderr_handlers(logger)) == 1

    def test_dev_null_log_file_silences_file(self):
        logger = setup_logging(log_file="/dev/null", env={})
        assert len(_file_handlers(logger)) == 0
        assert len(_stderr_handlers(logger)) == 0

    def test_idempotent_install(self, tmp_path):
        logger1 = setup_logging(env={})
        logger2 = setup_logging(env={})
        assert logger1 is logger2
        assert len(_file_handlers(logger2)) == 1
        assert len(_stderr_handlers(logger2)) == 0

    def test_second_call_can_add_stderr(self):
        logger = setup_logging(env={})
        assert len(_stderr_handlers(logger)) == 0
        setup_logging(stderr=True, env={})
        assert len(_stderr_handlers(logger)) == 1

    def test_legacy_verbose_kwarg_still_works(self):
        # verbose=True is the old API; equivalent to level=DEBUG + stderr=True.
        logger = setup_logging(verbose=True, env={})
        assert len(_stderr_handlers(logger)) == 1
        assert _stderr_handlers(logger)[0].level == logging.DEBUG
        assert _file_handlers(logger)[0].level == logging.DEBUG

    def test_legacy_verbose_kwarg_does_not_override_explicit_level(self):
        logger = setup_logging(verbose=True, level="WARNING", env={})
        # Explicit level wins; stderr is still added because verbose=True forces it.
        assert _file_handlers(logger)[0].level == logging.WARNING
        assert len(_stderr_handlers(logger)) == 1

    def test_handler_level_applied_to_existing_handlers(self, tmp_path):
        logger = setup_logging(level="DEBUG", env={})
        assert _file_handlers(logger)[0].level == logging.DEBUG
        # Re-call with a higher level — handlers update in place.
        setup_logging(level="ERROR", env={})
        assert _file_handlers(logger)[0].level == logging.ERROR

    def test_log_emits_to_file(self, tmp_path):
        target = tmp_path / "out.log"
        logger = setup_logging(log_file=target, level="DEBUG", env={})
        logger.debug("hello from %s", "test")
        for h in _file_handlers(logger):
            h.flush()
        content = target.read_text()
        assert "hello from test" in content

    def test_get_log_file_path_returns_default(self, tmp_path):
        result = get_log_file_path()
        assert result == tmp_path / "logs" / "ohtv.log"

    def test_get_logger_returns_named_logger(self):
        assert get_logger() is logging.getLogger("ohtv")

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError):
            setup_logging(level="LOUD", env={})

    def test_log_file_retargeted_on_path_change(self, tmp_path):
        first = tmp_path / "first.log"
        second = tmp_path / "second.log"
        logger = setup_logging(log_file=first, env={})
        first_handlers = _file_handlers(logger)
        assert len(first_handlers) == 1
        assert Path(first_handlers[0].baseFilename) == first

        setup_logging(log_file=second, env={})
        second_handlers = _file_handlers(logger)
        assert len(second_handlers) == 1
        assert Path(second_handlers[0].baseFilename) == second
