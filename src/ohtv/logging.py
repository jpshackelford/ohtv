"""Logging configuration for ohtv.

Three knobs control where and what is logged:

* ``level``     — minimum level for *all* handlers (default ``INFO``).
* ``log_file``  — destination for the rotating file handler. ``None`` keeps
                  the default (``~/.ohtv/logs/ohtv.log``). The special value
                  ``"-"`` disables file logging and forces stderr instead.
                  ``"/dev/null"`` (or ``"nul"`` on Windows) silences the file
                  handler entirely.
* ``stderr``    — if true, also add a console (stderr) handler at ``level``.

Resolution order for ``level`` is documented at ``resolve_log_level``:
CLI flag → ``OHTV_LOG_LEVEL`` env var → ``"INFO"``. Resolution for the
path follows the same order using ``OHTV_LOG_FILE``.

The rotating file handler keeps 1 MB × 3 backups and is installed exactly
once per process. The logger root level stays at ``DEBUG`` so handlers can
later be raised without losing detail.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from ohtv.config import get_ohtv_dir


_LOGGER_NAME = "ohtv"

# Special sentinels for ``log_file``:
_STDERR_ONLY_SENTINEL = "-"
# Cross-platform "null device" names users may pass on the CLI.
_NULL_DEVICE_NAMES = frozenset({"/dev/null", "nul", "NUL"})


def _get_log_dir() -> Path:
    return get_ohtv_dir() / "logs"


def _get_default_log_file() -> Path:
    return _get_log_dir() / "ohtv.log"


def get_log_file_path() -> Path:
    """Return the default log file path users should look at.

    Used in user-facing error messages (``Failed: N — see <path>``) so the
    string stays in one place.
    """
    return _get_default_log_file()


_VALID_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def resolve_log_level(
    cli_level: str | int | None,
    *,
    env: dict[str, str] | None = None,
    default: str | int = "INFO",
) -> int:
    """Resolve the effective log level.

    Resolution order: ``cli_level`` → ``OHTV_LOG_LEVEL`` env var →
    ``default``. ``str`` values are matched case-insensitively against
    ``logging`` level names; ``int`` values are returned as-is.

    Raises:
        ValueError: if a string value does not match a known level name.
    """
    env_map = env if env is not None else os.environ
    raw: str | int | None = cli_level
    if raw is None:
        raw = env_map.get("OHTV_LOG_LEVEL")
    if raw is None or raw == "":
        raw = default
    if isinstance(raw, int):
        return raw
    name = str(raw).strip().upper()
    if name not in _VALID_LEVEL_NAMES:
        raise ValueError(
            f"Invalid log level {raw!r}; expected one of "
            + ", ".join(_VALID_LEVEL_NAMES)
        )
    return getattr(logging, name)


def resolve_log_file(
    cli_path: str | Path | None,
    *,
    env: dict[str, str] | None = None,
) -> Path | str | None:
    """Resolve the effective log destination.

    Returns:
        * ``Path`` to the file handler destination, OR
        * the string ``"-"`` (stderr-only), OR
        * ``None`` to disable the file handler entirely
          (``/dev/null`` or ``nul``).

    Resolution order: ``cli_path`` → ``OHTV_LOG_FILE`` env var →
    ``~/.ohtv/logs/ohtv.log``.
    """
    env_map = env if env is not None else os.environ
    raw: str | Path | None = cli_path
    if raw is None:
        raw = env_map.get("OHTV_LOG_FILE")
    if raw is None or raw == "":
        return _get_default_log_file()
    if isinstance(raw, Path):
        return raw
    text = str(raw)
    if text == _STDERR_ONLY_SENTINEL:
        return _STDERR_ONLY_SENTINEL
    if text in _NULL_DEVICE_NAMES:
        return None
    return Path(text).expanduser()


def setup_logging(
    *,
    level: str | int | None = None,
    log_file: str | Path | None = None,
    stderr: bool = False,
    # Back-compat for legacy callers / tests that still pass the old kwarg.
    verbose: bool | None = None,
    # Allow tests / programmatic callers to override env reads.
    env: dict[str, str] | None = None,
) -> logging.Logger:
    """Configure the ``ohtv`` logger.

    Args:
        level: Log level for all handlers. Resolution order is
            ``level`` → ``OHTV_LOG_LEVEL`` → ``"INFO"``. Accepts the
            standard ``logging`` level names (case-insensitive) or an
            integer level.
        log_file: Destination for the rotating file handler. ``None``
            uses ``$OHTV_LOG_FILE`` or the default
            ``~/.ohtv/logs/ohtv.log``. ``"-"`` disables file logging
            and forces stderr instead. ``"/dev/null"`` (or ``"nul"``)
            silences file logging without enabling stderr.
        stderr: If true, *also* attach a stderr handler at ``level``.
        verbose: Deprecated alias preserved for backward compatibility.
            ``verbose=True`` is equivalent to ``level="DEBUG",
            stderr=True``. When passed, it does NOT override an
            explicit ``level``/``stderr`` argument or env var.
        env: Optional environment-variable mapping (for tests).

    Returns:
        The configured ``logging.Logger`` for ``"ohtv"``.
    """
    # Honour legacy ``verbose=True`` only if no explicit knob was passed.
    if verbose:
        if level is None:
            level = "DEBUG"
        stderr = True

    resolved_level = resolve_log_level(level, env=env)
    resolved_path = resolve_log_file(log_file, env=env)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    # Note: we deliberately leave ``propagate=True`` (the default). The
    # root logger has no handlers by default, so records flow into the
    # void unless the host process attaches its own. Setting
    # ``propagate=False`` would break ``caplog``/structured-logging
    # consumers without buying us anything.

    if resolved_path == _STDERR_ONLY_SENTINEL:
        # log_file="-" → stderr-only, no file handler.
        _ensure_stderr_handler(logger, resolved_level)
        # We override any pre-existing file handlers by raising their
        # level out of the way; we don't remove them in case the caller
        # passed log_file="-" after a prior file-handler install.
    else:
        if resolved_path is not None:
            _ensure_file_handler(logger, resolved_level, resolved_path)
        if stderr:
            _ensure_stderr_handler(logger, resolved_level)

    # Always (re-)apply the resolved level to every existing handler.
    for handler in logger.handlers:
        handler.setLevel(resolved_level)

    return logger


def _ensure_file_handler(
    logger: logging.Logger,
    level: int,
    path: Path,
) -> None:
    """Install (or reuse) a rotating file handler pointing at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            # Re-target an existing handler if the path changed.
            existing = getattr(handler, "baseFilename", None)
            try:
                same = existing is not None and Path(existing) == path
            except (OSError, ValueError):
                same = False
            if same:
                handler.setLevel(level)
                return
            # Different destination → replace it cleanly.
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001 — defensive cleanup
                pass
            break

    handler = logging.handlers.RotatingFileHandler(
        str(path),
        maxBytes=1_000_000,  # 1 MB
        backupCount=3,
    )
    handler.setLevel(level)
    handler.setFormatter(_get_formatter())
    logger.addHandler(handler)


def _ensure_stderr_handler(logger: logging.Logger, level: int) -> None:
    """Install (or reuse) a stderr console handler."""
    for handler in logger.handlers:
        if (
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.handlers.RotatingFileHandler)
            and getattr(handler, "stream", None) is sys.stderr
        ):
            handler.setLevel(level)
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(_get_formatter())
    logger.addHandler(handler)


def _get_formatter() -> logging.Formatter:
    """Standard log formatter."""
    return logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger() -> logging.Logger:
    """Return the ``ohtv`` logger."""
    return logging.getLogger(_LOGGER_NAME)
