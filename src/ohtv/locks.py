"""Process-level mutex for writers of the ``conversations`` table (Issue #109).

This module exposes a single context manager — :func:`sync_lock` — and one
exception type — :class:`SyncLockTimeout`. Together they serialize the three
writer commands that touch the metadata columns documented in the
column-ownership table at ``docs/reference/database.md``:

* ``ohtv sync`` (all forms — full, ``--repair --fix``, ``--update-metadata``,
  ``--force -n``)
* ``ohtv db scan``
* ``ohtv gen titles``

Read-only commands (``list``, ``show``, ``refs``, ``errors``, ``search``,
``ask``, ``report *``, ``db status``, ``db process *``, ``db embed``,
``gen objs``) **do not** take the lock.

Mechanism
=========

``fcntl.flock(LOCK_EX | LOCK_NB)`` on POSIX. The lock file lives at
``$OHTV_DIR/sync.lock`` (default ``~/.ohtv/sync.lock``). When the timeout is
zero (the default for interactive use) acquisition is non-blocking and fails
fast with :class:`SyncLockTimeout`. With ``timeout > 0`` the manager polls
once per 100 ms up to the deadline before giving up.

Windows note
============

``fcntl`` is POSIX-only. On Windows the manager is a no-op and logs a single
warning. This is the documented Issue #109 out-of-scope item and is tracked
for follow-up via ``msvcrt.locking``.

Why fcntl.flock instead of ``BEGIN IMMEDIATE`` or SQLite's own locking?
======================================================================

1. The race surface includes the manifest file (``sync_manifest.json``),
   which lives on the filesystem and is not under SQLite's purview.
2. ``BEGIN IMMEDIATE`` would serialize commits but does nothing about the
   in-memory ``manifest_map`` staleness — scanner reads the manifest before
   any DB transaction opens.
3. ``fcntl.flock`` works across processes without needing a connection, so
   the CLI can hold the lock from argv-parse time through teardown without
   coupling it to a particular DB handle's lifetime.

Why fail-fast (``timeout=0``) by default?
=========================================

1. ``ohtv sync`` is interactive — a stalled Rich progress bar is worse UX
   than an immediate error.
2. Scripted use (``cron``, CI) wants explicit ``--lock-timeout=N`` opt-in.
3. The lock can be held for minutes during a fresh sync; queueing without
   bound risks pile-ups.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger("ohtv")


# Poll interval when waiting for the lock (seconds). Chosen to keep latency
# under 100 ms while still being well above the kernel context-switch cost.
_POLL_INTERVAL_SECONDS = 0.1


class SyncLockTimeout(RuntimeError):
    """Raised when :func:`sync_lock` cannot acquire the lock in time.

    The default acquisition timeout is zero, so any contention against
    another holder of ``$OHTV_DIR/sync.lock`` raises this exception
    immediately. With ``timeout > 0`` the exception is raised only after
    the poll loop exhausts its deadline.
    """


def _is_windows() -> bool:
    """Return ``True`` on Windows platforms (no ``fcntl``)."""
    return sys.platform.startswith("win")


def _resolve_lock_path() -> Path:
    """Locate ``$OHTV_DIR/sync.lock`` via the existing config plumbing.

    Imported lazily so :mod:`ohtv.config` doesn't sit in the import chain
    of every module that wants the lock — particularly important for the
    test harness, where ``OHTV_DIR`` is monkeypatched per-test.
    """
    from ohtv.config import get_ohtv_dir

    return get_ohtv_dir() / "sync.lock"


@contextmanager
def sync_lock(
    timeout: float = 0.0, label: str = "ohtv"
) -> Iterator[int | None]:
    """Acquire a process-level exclusive lock on ``$OHTV_DIR/sync.lock``.

    Parameters
    ----------
    timeout
        Seconds to wait for the lock. ``0.0`` (default) means fail-fast —
        no retry, no wait. Positive values poll once per ~100 ms until the
        deadline elapses.
    label
        Short identifier written into the lock file alongside the holder's
        PID for diagnostic purposes (``cat ~/.ohtv/sync.lock`` shows
        ``<pid> <label>``). Typical values: ``"sync"``, ``"scan"``,
        ``"gen-titles"``.

    Yields
    ------
    int | None
        The lock file descriptor on POSIX, or ``None`` on Windows (where
        the lock is a documented no-op).

    Raises
    ------
    SyncLockTimeout
        If the lock could not be acquired within ``timeout`` seconds.
    """
    if _is_windows():
        # Documented limitation — see Issue #109. Best-effort: log + proceed.
        log.warning(
            "sync_lock: POSIX file locking unavailable on Windows; "
            "concurrent ohtv writers are NOT serialized on this platform."
        )
        yield None
        return

    # Import here so the module loads on Windows / under coverage without
    # fcntl present in the import path.
    import fcntl

    lock_path = _resolve_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + max(timeout, 0.0)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise
                if time.monotonic() >= deadline:
                    raise SyncLockTimeout(
                        f"Another ohtv writer is already running "
                        f"(see {lock_path}). "
                        f"Try again in a few seconds, or pass "
                        f"--lock-timeout=N to wait."
                    ) from None
                time.sleep(_POLL_INTERVAL_SECONDS)

        # Stamp PID + label for diagnostics. Best-effort; a failure here
        # must not leak the held lock back to the caller.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()} {label}\n".encode())
        except OSError:
            log.debug("sync_lock: could not write owner stamp to %s", lock_path)
        yield fd
    finally:
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        except OSError:
            # Already closed / unlocked — nothing actionable here.
            log.debug("sync_lock: release on already-closed fd")
