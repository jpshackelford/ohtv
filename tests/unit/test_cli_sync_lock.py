"""CLI smoke tests for the ``sync.lock`` mutex (Issue #109).

These verify the three writer commands (``ohtv sync``, ``ohtv db scan``,
``ohtv gen titles``) acquire the lock through :func:`ohtv.locks.sync_lock`
and surface :class:`SyncLockTimeout` as a clean ``exit 1`` rather than an
uncaught traceback.

The lock implementation itself is covered by ``test_locks.py``; here we
only verify the CLI wiring (option present, error path clean, the
context manager actually gets called).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from ohtv.cli import main as ohtv_main
from ohtv.locks import SyncLockTimeout


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_ohtv_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``OHTV_DIR`` at a tmp tree so we don't touch ``~/.ohtv``."""
    target = tmp_path / "ohtv"
    target.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(target))
    # Some CLI paths sniff $HOME for the read-only OpenHands data dir.
    monkeypatch.setenv("HOME", str(tmp_path))
    return target


# ---------------------------------------------------------------------------
# --lock-timeout option exists on the three writer commands.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["sync", "--help"],
        ["db", "scan", "--help"],
        ["gen", "titles", "--help"],
    ],
    ids=["sync", "db_scan", "gen_titles"],
)
def test_writer_commands_advertise_lock_timeout(
    runner: CliRunner, argv: list[str]
) -> None:
    """``--lock-timeout`` shows up in ``--help`` for every writer command."""
    result = runner.invoke(ohtv_main, argv)
    assert result.exit_code == 0
    assert "--lock-timeout" in result.output
    assert "sync.lock" in result.output


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--help"],
        ["show", "--help"],
        ["refs", "--help"],
        ["errors", "--help"],
        ["search", "--help"],
        ["db", "status", "--help"],
        ["db", "embed", "--help"],
        ["report", "--help"],
        ["gen", "objs", "--help"],
    ],
    ids=[
        "list", "show", "refs", "errors", "search",
        "db_status", "db_embed", "report", "gen_objs",
    ],
)
def test_read_only_commands_do_not_advertise_lock_timeout(
    runner: CliRunner, argv: list[str]
) -> None:
    """Read-only commands MUST NOT take the lock — no --lock-timeout option.

    This is the contract from Issue #109: only writers serialize on
    ``sync.lock``. ``list``, ``show``, ``search`` etc. stay lock-free
    so a long sync never blocks a quick read.
    """
    result = runner.invoke(ohtv_main, argv)
    assert result.exit_code == 0
    assert "--lock-timeout" not in result.output


# ---------------------------------------------------------------------------
# Failure path: lock-timeout error bubbles up as exit 1 with clear message.
# ---------------------------------------------------------------------------


def _seed_minimal_db(ohtv_dir: Path) -> Path:
    """Create a migrated empty index.db so db scan can run without dying."""
    from ohtv.db.migrations import migrate

    db_path = ohtv_dir / "index.db"
    conn = sqlite3.connect(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()
    return db_path


def test_db_scan_handles_lock_timeout_cleanly(
    runner: CliRunner,
    isolated_ohtv_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the lock is held, ``db scan`` exits 1 with a readable error."""
    _seed_minimal_db(isolated_ohtv_dir)

    def _always_busy(timeout: float = 0.0, label: str = "ohtv"):
        # Match the real signature; bypass the actual fcntl path.
        from contextlib import contextmanager

        @contextmanager
        def _raiser():
            raise SyncLockTimeout(
                "Another ohtv writer is already running "
                f"(see {isolated_ohtv_dir / 'sync.lock'}). "
                "Try again in a few seconds, or pass --lock-timeout=N to wait."
            )
            yield  # unreachable but satisfies the type checker

        return _raiser()

    monkeypatch.setattr("ohtv.cli.sync_lock", _always_busy)

    result = runner.invoke(ohtv_main, ["db", "scan"])

    assert result.exit_code == 1
    # Both the message and the workaround hint must appear.
    assert "Another ohtv writer is already running" in result.output
    assert "--lock-timeout" in result.output


def test_sync_handles_lock_timeout_cleanly(
    runner: CliRunner,
    isolated_ohtv_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ohtv sync`` surfaces ``SyncLockTimeout`` as exit 1 too."""
    from contextlib import contextmanager

    @contextmanager
    def _always_busy(timeout: float = 0.0, label: str = "ohtv"):
        raise SyncLockTimeout(
            "Another ohtv writer is already running. Try --lock-timeout=N."
        )
        yield  # unreachable

    monkeypatch.setattr("ohtv.cli.sync_lock", _always_busy)
    # No API key needed — the lock raises before key check.

    result = runner.invoke(ohtv_main, ["sync"])

    assert result.exit_code == 1
    assert "Another ohtv writer is already running" in result.output


def test_sync_status_skips_the_lock(
    runner: CliRunner,
    isolated_ohtv_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ohtv sync --status`` is read-only — it MUST NOT take the lock.

    Verifies the early-return ladder still works: if the lock were taken
    around ``--status``, this test would exit 1 because the patched
    ``sync_lock`` raises. Instead we expect ``_show_status`` to run.
    """
    from contextlib import contextmanager

    sentinel = {"lock_called": False}

    @contextmanager
    def _spy_lock(timeout: float = 0.0, label: str = "ohtv"):
        sentinel["lock_called"] = True
        raise SyncLockTimeout("should not have been called")
        yield  # unreachable

    monkeypatch.setattr("ohtv.cli.sync_lock", _spy_lock)

    runner.invoke(ohtv_main, ["sync", "--status"])

    # --status path doesn't need the lock; whatever the status content,
    # the CLI must NOT have asked for the lock.
    assert sentinel["lock_called"] is False
    # We don't assert exit_code here — _show_status can succeed or fail
    # depending on whether a manifest exists; the point is the lock path
    # was never entered.


# ---------------------------------------------------------------------------
# Smoke: scan succeeds when the lock is uncontested.
# ---------------------------------------------------------------------------


def test_db_scan_runs_when_lock_uncontested(
    runner: CliRunner, isolated_ohtv_dir: Path
) -> None:
    """End-to-end: with no other holder, ``db scan`` succeeds and exits 0."""
    _seed_minimal_db(isolated_ohtv_dir)

    result = runner.invoke(ohtv_main, ["db", "scan"])

    assert result.exit_code == 0, result.output
    # The lock file is left on disk after release.
    assert (isolated_ohtv_dir / "sync.lock").exists()
