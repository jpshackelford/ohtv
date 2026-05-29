"""CLI-side logging glue (Issue #121).

Provides the ``@logging_options`` Click decorator (adds
``--log-level`` / ``--log-file`` / ``--log-stderr`` to a command without
requiring a signature change) and the ``init_logging_from_cli`` shim
called by every CLI command.

The decorator stores resolved values on the Click context under
``ctx.meta["ohtv.logging"]``; ``init_logging_from_cli`` reads them back
and forwards to :func:`ohtv.logging.setup_logging`. Commands that still
declare a per-command ``--verbose`` flag forward it through ``verbose=``
which we honour as a deprecated alias for ``--log-level DEBUG
--log-stderr`` and emit a one-shot stderr warning on first use.

This module deliberately does no logging-level work itself — it is a
parameter-conduit only.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

import click

from ohtv.logging import setup_logging

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_META_KEY = "ohtv.logging"

# Set on first verbose-deprecation warning so each ``ohtv`` invocation
# only nags once even when multiple commands are invoked in-process
# (e.g. by tests using CliRunner).
_VERBOSE_WARNING_EMITTED = False


def _record(option_name: str, value: Any) -> None:
    """Store a logging option on the active Click context."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return
    bucket = ctx.meta.setdefault(_META_KEY, {})
    bucket[option_name] = value


def _log_level_callback(ctx: click.Context, param: click.Parameter, value: str | None):
    if value is not None:
        _record("level", value)
    return value


def _log_file_callback(ctx: click.Context, param: click.Parameter, value: str | None):
    if value is not None:
        _record("log_file", value)
    return value


def _log_stderr_callback(ctx: click.Context, param: click.Parameter, value: bool):
    if value:
        _record("stderr", True)
    return value


def logging_options(func: Callable) -> Callable:
    """Click decorator that adds ``--log-level`` / ``--log-file`` /
    ``--log-stderr`` to a command without changing its signature.

    Values are stored on the Click context's ``meta`` map and picked up
    by :func:`init_logging_from_cli`. Use ``expose_value=False`` so the
    command function does not need additional kwargs.
    """
    func = click.option(
        "--log-stderr",
        is_flag=True,
        default=False,
        expose_value=False,
        callback=_log_stderr_callback,
        is_eager=True,
        help="Also send log output to stderr.",
    )(func)
    func = click.option(
        "--log-file",
        type=click.Path(dir_okay=False),
        default=None,
        expose_value=False,
        callback=_log_file_callback,
        is_eager=True,
        help=(
            "Override the default log file (~/.ohtv/logs/ohtv.log). "
            "Use '-' for stderr-only; '/dev/null' to silence file logging."
        ),
    )(func)
    func = click.option(
        "--log-level",
        type=click.Choice(_LOG_LEVELS, case_sensitive=False),
        default=None,
        expose_value=False,
        callback=_log_level_callback,
        is_eager=True,
        help=(
            "Minimum log level (default: INFO; or $OHTV_LOG_LEVEL if set)."
        ),
    )(func)
    return func


def _resolve_from_context() -> dict[str, Any]:
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return {}
    return dict(ctx.meta.get(_META_KEY, {}))


def _warn_verbose_deprecated() -> None:
    global _VERBOSE_WARNING_EMITTED
    if _VERBOSE_WARNING_EMITTED:
        return
    _VERBOSE_WARNING_EMITTED = True
    sys.stderr.write(
        "Note: --verbose is deprecated; use --log-level DEBUG --log-stderr instead.\n"
    )


def reset_verbose_warning_state() -> None:
    """Reset the one-shot deprecation flag (test hook)."""
    global _VERBOSE_WARNING_EMITTED
    _VERBOSE_WARNING_EMITTED = False


def init_logging_from_cli(verbose: bool = False) -> None:
    """Initialise the ohtv logger from Click context + ``verbose=`` shim.

    Reads ``--log-level`` / ``--log-file`` / ``--log-stderr`` recorded by
    :func:`logging_options`, applies the legacy ``--verbose`` alias when
    set, and calls :func:`ohtv.logging.setup_logging`.

    Args:
        verbose: Legacy per-command ``--verbose`` flag. When ``True``
            and ``--log-level`` was not also passed, behaves as
            ``--log-level DEBUG --log-stderr`` and emits a one-shot
            deprecation warning.
    """
    opts = _resolve_from_context()
    level = opts.get("level")
    log_file = opts.get("log_file")
    stderr = bool(opts.get("stderr", False))

    if verbose:
        if level is None:
            # Only nag when --verbose actually changes behavior. If the
            # caller already passed an explicit --log-level we treat
            # that as a signal they've moved past --verbose and skip
            # the one-shot deprecation note.
            _warn_verbose_deprecated()
            level = "DEBUG"
        stderr = True

    setup_logging(level=level, log_file=log_file, stderr=stderr)
