"""Tests for :mod:`ohtv.locks` (Issue #109).

The lock is a thin wrapper around ``fcntl.flock`` and is therefore
exercised primarily through subprocesses so we get genuine
cross-process contention rather than a same-process re-acquire (which
``flock`` silently allows on the same fd).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ohtv.locks import SyncLockTimeout, sync_lock


_HOLDER_SCRIPT = """
import os
import sys
import time

os.environ["OHTV_DIR"] = {ohtv_dir!r}

from ohtv.locks import sync_lock

with sync_lock(timeout=0.0, label="holder"):
    # Signal we have the lock by touching a marker file.
    open({ready_path!r}, "w").close()
    # Hold the lock until the parent removes the release marker.
    while not os.path.exists({release_path!r}):
        time.sleep(0.05)
"""


def _spawn_holder(tmp_path: Path) -> tuple[subprocess.Popen[bytes], Path, Path]:
    """Spawn a Python subprocess that grabs ``sync.lock`` and waits.

    Returns ``(process, ready_marker_path, release_marker_path)``.
    The parent should:

    1. Wait for ``ready_marker_path`` to appear.
    2. Run its assertions against the now-held lock.
    3. Touch ``release_marker_path`` to let the holder exit.
    4. ``.wait()`` on the process.
    """
    ohtv_dir = tmp_path / "ohtv"
    ohtv_dir.mkdir(exist_ok=True)
    ready = tmp_path / "ready"
    release = tmp_path / "release"

    script = _HOLDER_SCRIPT.format(
        ohtv_dir=str(ohtv_dir),
        ready_path=str(ready),
        release_path=str(release),
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(script)],
        env={**os.environ, "OHTV_DIR": str(ohtv_dir)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait up to 5 s for the holder to grab the lock.
    deadline = time.monotonic() + 5.0
    while not ready.exists():
        if proc.poll() is not None:
            _, err = proc.communicate(timeout=1)
            raise RuntimeError(
                f"Holder process exited prematurely: {err.decode()}"
            )
        if time.monotonic() >= deadline:
            proc.kill()
            raise RuntimeError("Holder process did not acquire lock in 5 s")
        time.sleep(0.05)

    return proc, ready, release


def _release_holder(
    proc: subprocess.Popen[bytes], release_path: Path
) -> None:
    """Signal the holder to exit and wait for it."""
    release_path.touch()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


@pytest.fixture
def ohtv_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point :func:`ohtv.config.get_ohtv_dir` at ``tmp_path / 'ohtv'``."""
    target = tmp_path / "ohtv"
    target.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(target))
    return target


# ---------------------------------------------------------------------------
# Basic happy-path behavior.
# ---------------------------------------------------------------------------


def test_sync_lock_acquires_when_uncontested(ohtv_dir: Path) -> None:
    """An uncontested lock acquisition yields the FD and creates the file."""
    lock_path = ohtv_dir / "sync.lock"
    assert not lock_path.exists()

    with sync_lock(timeout=0.0, label="test") as fd:
        # POSIX: fd is an integer; Windows: None.
        if sys.platform.startswith("win"):
            assert fd is None
        else:
            assert isinstance(fd, int)
        assert lock_path.exists()

    # File should remain on disk after release (it's a lock file, not a TTL).
    assert lock_path.exists()


def test_sync_lock_writes_owner_stamp(ohtv_dir: Path) -> None:
    """The lock file records ``<pid> <label>`` for diagnostic ``cat``."""
    if sys.platform.startswith("win"):
        pytest.skip("Windows lock is a no-op; no stamp is written.")

    with sync_lock(timeout=0.0, label="unit-test"):
        contents = (ohtv_dir / "sync.lock").read_text().strip()

    assert contents == f"{os.getpid()} unit-test"


def test_sync_lock_creates_ohtv_dir_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``$OHTV_DIR`` is created on demand — fresh installs have no dir yet."""
    target = tmp_path / "fresh-install"
    monkeypatch.setenv("OHTV_DIR", str(target))
    assert not target.exists()

    with sync_lock(timeout=0.0, label="fresh"):
        pass

    assert (target / "sync.lock").exists()


def test_sync_lock_not_nestable_in_same_process(ohtv_dir: Path) -> None:
    """A nested ``sync_lock`` opens a new fd → Linux ``flock`` rejects it.

    Per ``flock(2)`` on Linux: "If a process uses open(2) (or similar) to
    obtain more than one file descriptor for the same file, these file
    descriptors are treated independently by flock()." So the second
    acquire fails immediately. The production code never nests anyway;
    this regression-tests our knowledge of the mechanism.
    """
    if sys.platform.startswith("win"):
        pytest.skip("Nesting not meaningful in the Windows no-op path.")

    with sync_lock(timeout=0.0, label="outer"):
        with pytest.raises(SyncLockTimeout):
            with sync_lock(timeout=0.0, label="inner"):
                pytest.fail("Nested acquire should have failed.")


# ---------------------------------------------------------------------------
# Cross-process contention (the actual race we are guarding against).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Windows lock is a no-op (out of scope for Issue #109).",
)
def test_sync_lock_fails_fast_when_held_by_other_process(
    tmp_path: Path,
) -> None:
    """``timeout=0`` raises :class:`SyncLockTimeout` within ~1 s."""
    proc, _ready, release = _spawn_holder(tmp_path)
    try:
        # Point our own get_ohtv_dir() at the same path the holder uses.
        os.environ["OHTV_DIR"] = str(tmp_path / "ohtv")

        start = time.monotonic()
        with pytest.raises(SyncLockTimeout) as exc_info:
            with sync_lock(timeout=0.0, label="contender"):
                pytest.fail("Should not have acquired contested lock.")
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Fail-fast took {elapsed:.3f}s, expected <1s"
        # User-facing message must point at the lock file + the workaround.
        msg = str(exc_info.value)
        assert "sync.lock" in msg
        assert "--lock-timeout" in msg
    finally:
        _release_holder(proc, release)


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Windows lock is a no-op (out of scope for Issue #109).",
)
def test_sync_lock_waits_until_holder_releases(tmp_path: Path) -> None:
    """``timeout>0`` blocks until the prior holder exits, then succeeds."""
    proc, _ready, release = _spawn_holder(tmp_path)
    try:
        os.environ["OHTV_DIR"] = str(tmp_path / "ohtv")

        # Schedule the holder to release ~0.3 s from now, in a thread.
        import threading

        threading.Timer(0.3, release.touch).start()

        start = time.monotonic()
        with sync_lock(timeout=5.0, label="waiter"):
            elapsed = time.monotonic() - start

        # Should have waited at least ~0.25 s, well under the 5 s deadline.
        assert 0.2 < elapsed < 4.0, f"waited {elapsed:.3f}s"
    finally:
        # Belt and braces; release should already be touched.
        if not release.exists():
            release.touch()
        proc.wait(timeout=5)


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Windows lock is a no-op (out of scope for Issue #109).",
)
def test_sync_lock_times_out_when_holder_outlives_timeout(
    tmp_path: Path,
) -> None:
    """``timeout=0.3`` raises after polling the deadline."""
    proc, _ready, release = _spawn_holder(tmp_path)
    try:
        os.environ["OHTV_DIR"] = str(tmp_path / "ohtv")

        start = time.monotonic()
        with pytest.raises(SyncLockTimeout):
            with sync_lock(timeout=0.3, label="impatient"):
                pytest.fail("Should not have acquired contested lock.")
        elapsed = time.monotonic() - start

        # Should have honored the deadline (with a small slack for poll
        # interval + scheduling jitter).
        assert 0.25 < elapsed < 1.5, f"waited {elapsed:.3f}s"
    finally:
        _release_holder(proc, release)


# ---------------------------------------------------------------------------
# Windows platform branch.
# ---------------------------------------------------------------------------


def test_sync_lock_is_noop_on_windows(
    ohtv_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows the lock yields ``None`` and logs a warning — no flock."""
    monkeypatch.setattr("ohtv.locks._is_windows", lambda: True)

    with sync_lock(timeout=0.0, label="windows") as fd:
        assert fd is None
        # On the Windows no-op path we don't create a lock file —
        # fcntl is bypassed entirely.
        assert not (ohtv_dir / "sync.lock").exists()
