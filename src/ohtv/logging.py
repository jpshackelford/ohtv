"""Logging configuration for ohtv."""

import logging
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".openhands" / "cloud" / "logs"
LOG_FILE = LOG_DIR / "ohtv.log"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging to file and optionally console."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("ohtv")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        _add_file_handler(logger)
        if verbose:
            _add_console_handler(logger)

    return logger


def _add_file_handler(logger: logging.Logger) -> None:
    """Add rotating file handler."""
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,  # 1MB
        backupCount=3,
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_get_formatter())
    logger.addHandler(handler)


def _add_console_handler(logger: logging.Logger) -> None:
    """Add console handler for verbose mode."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_get_formatter())
    logger.addHandler(handler)


def _get_formatter() -> logging.Formatter:
    """Get standard log formatter."""
    return logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger() -> logging.Logger:
    """Get the ohtv logger."""
    return logging.getLogger("ohtv")
