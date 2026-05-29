"""Repair command unit tests (Issue #113).

These tests target ``SyncManager.repair`` directly via the
:func:`sync_manager_factory` fixture (the same one the behavioral
suite uses), plus a few CLI-level tests for the ``--prune`` /
``--lock-timeout`` plumbing on ``ohtv sync --repair``.

Scope split versus :mod:`tests.unit.sync.test_behavioral`:

* ``test_behavioral`` owns the cross-issue scenario suite (#110 catalog).
  #113 flips two markers there but the assertions stay generic
  ("four buckets exist").
* This module exercises the implementation details: prune validation,
  source-filter safety, lock contention, listing-degraded handling,
  the new_on_cloud / missing_locally cutoff partition, and the CLI
  rendering of the four-bucket section.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from .builders import ConvFactory
from .fakes import FakeCloudClient, FakeConversation


_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Acceptance tests for the repair() core
# ---------------------------------------------------------------------------


def test_repair_result_has_four_bucket_attributes() -> None:
    """RepairResult exposes the four parallel bucket fields + counts."""
    from ohtv.sync import RepairResult

    r = RepairResult()
    # Lists default to empty.
    assert r.new_on_cloud_ids == []
    assert r.missing_locally_ids == []
    assert r.removed_from_cloud_ids == []
    assert r.modified_on_cloud_ids == []
    # Bare-name properties return ints (count of corresponding list).
    assert r.new_on_cloud == 0
    assert r.missing_locally == 0
    assert r.removed_from_cloud == 0
    assert r.modified_on_cloud == 0


def test_repair_result_counts_track_list_length() -> None:
    """The bare-name int properties are ``len()`` of the parallel list."""
    from ohtv.sync import RepairResult

    r = RepairResult()
    r.missing_locally_ids = ["a", "b", "c"]
    r.removed_from_cloud_ids = ["x"]
    assert r.missing_locally == 3
    assert r.removed_from_cloud == 1


def test_repair_result_is_consistent_only_when_all_buckets_empty() -> None:
    """``is_consistent`` returns False when any bucket has items."""
    from ohtv.sync import RepairResult

    r = RepairResult()
    assert r.is_consistent is True
    # Each bucket independently flips is_consistent to False.
    r.missing_locally_ids = ["a"]
    assert r.is_consistent is False
    r2 = RepairResult()
    r2.removed_from_cloud_ids = ["a"]
    assert r2.is_consistent is False
    r3 = RepairResult()
    r3.modified_on_cloud_ids = ["a"]
    assert r3.is_consistent is False
    r4 = RepairResult()
    r4.new_on_cloud_ids = ["a"]
    assert r4.is_consistent is False
    # Legacy ghost/orphan still counts.
    r5 = RepairResult()
    r5.ghost_entries = ["a"]
    assert r5.is_consistent is False


def test_prune_without_fix_raises_value_error(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    """AC: ``prune=True`` without ``fix=True`` is a hard error."""
    manager = sync_manager_factory(fake_cloud)
    with pytest.raises(ValueError, match="--prune"):
        manager.repair(fix=False, prune=True)


def test_repair_fix_false_does_not_dispatch_downloads(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    """fix=False refreshes listing + reports but downloads nothing."""
    convs = conv_factory.batch(2)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()  # seeds the conversations table

    # Add a missing-locally entry on the cloud side.
    fresh = FakeConversation(
        id="missing-id",
        created_at=datetime(2020, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=_UTC),
    )
    fake_cloud.add(fresh)

    download_count_before = len(fake_cloud.download_calls)
    result = manager.repair(fix=False)
    # Diagnostic only: nothing was downloaded.
    assert len(fake_cloud.download_calls) == download_count_before
    assert result.downloaded_missing == 0
    assert result.refetched_modified == 0
    assert result.pruned_removed == 0
    # The 2020 timestamp predates the snapshot cutoff -> missing_locally.
    assert "missing-id".replace("-", "") in result.missing_locally_ids


def test_repair_fix_true_downloads_missing_and_modified(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    """fix=True dispatches downloads for missing + modified entries."""
    convs = conv_factory.batch(2)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Inject one missing-locally entry (created before cutoff so it's
    # not categorized as new_on_cloud).
    fresh = FakeConversation(
        id="missingid01",
        created_at=datetime(2020, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=_UTC),
    )
    fake_cloud.add(fresh)
    # And one modified entry — bump its updated_at.
    fake_cloud.backdate(convs[0].id, datetime(2099, 1, 1, tzinfo=_UTC))

    downloads_before = len(fake_cloud.download_calls)
    result = manager.repair(fix=True)
    # Both items got downloaded (one new, one updated).
    assert len(fake_cloud.download_calls) >= downloads_before + 2
    assert result.downloaded_missing >= 1
    assert result.refetched_modified >= 1
    assert result.pruned_removed == 0  # prune defaults to False


def test_repair_fix_true_with_prune_deletes_removed_from_cloud(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
    tmp_path,
):
    """prune=True deletes both DB rows and on-disk files for removed items."""
    convs = conv_factory.batch(2)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    target_id = convs[0].id.replace("-", "")
    target_dir = manager.config.synced_conversations_dir / target_id
    assert target_dir.exists(), "fixture seed should produce on-disk dir"

    # Remove convs[0] from the cloud side.
    fake_cloud.remove(convs[0].id)

    result = manager.repair(fix=True, prune=True)
    assert result.pruned_removed == 1
    assert target_id in [i.replace("-", "") for i in result.removed_from_cloud_ids]
    # The on-disk directory was deleted.
    assert not target_dir.exists()


def test_repair_fix_true_without_prune_records_removed_only(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
):
    """Without --prune, removed_from_cloud is reported but files survive."""
    convs = conv_factory.batch(2)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    target_id = convs[0].id.replace("-", "")
    target_dir = manager.config.synced_conversations_dir / target_id

    fake_cloud.remove(convs[0].id)
    result = manager.repair(fix=True, prune=False)
    assert result.pruned_removed == 0
    assert target_id in [i.replace("-", "") for i in result.removed_from_cloud_ids]
    # The on-disk dir is preserved.
    assert target_dir.exists()


def test_prune_never_touches_source_local_rows(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
):
    """A hypothetical CLI/local row in ``conversations`` is never pruned.

    Defends against a regression where a future schema change could
    let CLI rows leak into ``removed_from_cloud_ids``. The
    :meth:`CloudListingStore.removed_from_cloud` query already filters
    by ``source='cloud'``, but we double-check at the deletion call
    site too. This test injects a forged id directly and confirms the
    safety check at deletion time.
    """
    convs = conv_factory.batch(1)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Forge a 'local' source row by writing directly to the DB.
    from ohtv.db.stores import ConversationStore
    from ohtv.sync import get_connection_for_sync
    with get_connection_for_sync() as conn:
        store = ConversationStore(conn)
        # Manual insert to set source='local' (not exposed via
        # record_cloud_download which hard-codes 'cloud').
        conn.execute(
            "INSERT INTO conversations (id, location, source, registered_at, event_count) "
            "VALUES (?, ?, 'local', ?, 0)",
            ("localonlyrow", "/tmp/whatever", "2024-01-01T00:00:00Z"),
        )
        conn.commit()

    # Trigger prune with the forged id appearing in the bucket.
    with get_connection_for_sync() as conn:
        pruned = manager._prune_removed_from_cloud(
            conn, ["localonlyrow"],
        )
    # The local-source row was preserved (pruned count stays 0).
    assert pruned == 0
    with get_connection_for_sync() as conn:
        store = ConversationStore(conn)
        assert store.get("localonlyrow") is not None


def test_repair_fix_false_handles_listing_degraded_no_api_key(
    sync_manager_factory, fake_cloud: FakeCloudClient,
):
    """No API key -> listing_degraded, buckets stay empty."""
    manager = sync_manager_factory(fake_cloud, api_key="")
    result = manager.repair(fix=False)
    assert result.listing_degraded is True
    assert result.new_on_cloud == 0
    assert result.missing_locally == 0


def test_repair_fix_true_listing_degraded_skips_downloads(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
):
    """When the listing degrades mid-flight, downloads are not dispatched."""
    convs = conv_factory.batch(2)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    # Now wedge the listing for the repair run. Issue #112's
    # ``_run_listing_pass`` calls ``search_conversations`` with
    # ``limit=100`` — page 1 always exists, so we fail at the first
    # page to model a full mid-flight failure.
    fake_cloud.add(conv_factory.next())  # add a hypothetical missing
    fake_cloud.fail_listing_at_page(1, RuntimeError("listing crashed"))

    downloads_before = len(fake_cloud.download_calls)
    # Per the contract: a mid-listing failure aborts --fix with a
    # warning and leaves the previous snapshot intact. No downloads
    # are dispatched.
    result = manager.repair(fix=True)
    assert result.listing_degraded is True
    assert result.downloaded_missing == 0
    assert result.refetched_modified == 0
    assert len(fake_cloud.download_calls) == downloads_before


# ---------------------------------------------------------------------------
# CLI-layer tests
# ---------------------------------------------------------------------------


def test_cli_prune_without_repair_is_usage_error():
    """--prune outside --repair --fix is a Click UsageError."""
    from ohtv import cli as cli_module

    runner = CliRunner()
    result = runner.invoke(cli_module.sync, ["--prune"])
    # UsageError → exit code 2.
    assert result.exit_code == 2
    assert "--prune" in result.output


def test_cli_prune_with_dry_run_is_usage_error():
    """--prune + --repair + --dry-run is still rejected (dry-run can't prune)."""
    from ohtv import cli as cli_module

    runner = CliRunner()
    result = runner.invoke(cli_module.sync, ["--repair", "--dry-run", "--prune"])
    assert result.exit_code == 2
    assert "--prune" in result.output


def test_repair_renders_four_bucket_section(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
    capsys,
):
    """CLI _run_repair prints the four labeled bucket lines."""
    from ohtv.cli import _run_repair

    convs = conv_factory.batch(1)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    _run_repair(manager, fix=False, prune=False, quiet=False)
    captured = capsys.readouterr().out
    # Issue #113 bucket section labels.
    assert "Cloud-vs-local set diff" in captured
    assert "New on cloud" in captured
    assert "Missing locally" in captured
    assert "Removed from cloud" in captured
    assert "Modified on cloud" in captured


def test_repair_quiet_mode_exits_zero_when_consistent(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
):
    """Quiet mode -> SystemExit(0) when nothing is wrong."""
    from ohtv.cli import _run_repair

    convs = conv_factory.batch(1)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    with pytest.raises(SystemExit) as exc_info:
        _run_repair(manager, fix=False, prune=False, quiet=True)
    assert exc_info.value.code == 0


def test_repair_quiet_mode_exits_nonzero_when_drift(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory,
):
    """Quiet mode -> SystemExit(1) when buckets are non-empty."""
    from ohtv.cli import _run_repair

    convs = conv_factory.batch(1)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    # Introduce a removed-from-cloud entry.
    fake_cloud.remove(convs[0].id)

    with pytest.raises(SystemExit) as exc_info:
        _run_repair(manager, fix=False, prune=False, quiet=True)
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Lock-contention test
# ---------------------------------------------------------------------------


def test_repair_fix_true_surfaces_sync_lock_timeout(
    tmp_path, monkeypatch
):
    """Concurrent --repair --fix surfaces SyncLockTimeout per #109's contract.

    The CLI takes ``sync.lock`` before calling into the writer body.
    A second invocation while the lock is held with the default
    ``--lock-timeout=0`` fails fast with :class:`SyncLockTimeout`.
    """
    from ohtv import cli as cli_module
    from ohtv.locks import sync_lock

    # Point OHTV_DIR at a per-test tmp_path so we don't clobber the
    # user's real lock file.
    ohtv_dir = tmp_path / ".ohtv"
    ohtv_dir.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    # And give the CLI an API key so it doesn't short-circuit early.
    monkeypatch.setenv("OPENHANDS_API_KEY", "test-key")

    # Hold the lock in a background thread, then invoke the CLI.
    lock_held = threading.Event()
    release_lock = threading.Event()

    def _hold_lock():
        with sync_lock(timeout=0.0, label="test-holder"):
            lock_held.set()
            # Wait until the test signals to release.
            release_lock.wait(timeout=10)

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    try:
        assert lock_held.wait(timeout=5), "background lock holder timed out"
        runner = CliRunner()
        result = runner.invoke(
            cli_module.sync,
            ["--repair"],  # i.e. --repair --fix (no --dry-run)
        )
        assert result.exit_code == 1
        assert (
            "another ohtv writer" in result.output.lower()
            or "writer is already running" in result.output.lower()
        )
    finally:
        release_lock.set()
        holder.join(timeout=5)


def test_read_only_repair_does_not_take_sync_lock(
    tmp_path, monkeypatch
):
    """--repair --dry-run runs alongside a held sync.lock (Issue #113 contract)."""
    from ohtv import cli as cli_module
    from ohtv.locks import sync_lock

    ohtv_dir = tmp_path / ".ohtv"
    ohtv_dir.mkdir()
    monkeypatch.setenv("OHTV_DIR", str(ohtv_dir))
    monkeypatch.setenv("OPENHANDS_API_KEY", "test-key")

    lock_held = threading.Event()
    release_lock = threading.Event()

    def _hold_lock():
        with sync_lock(timeout=0.0, label="test-holder"):
            lock_held.set()
            release_lock.wait(timeout=10)

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    try:
        assert lock_held.wait(timeout=5)
        runner = CliRunner()
        result = runner.invoke(
            cli_module.sync,
            ["--repair", "--dry-run"],
        )
        # The --repair --dry-run path doesn't acquire the lock, so it
        # should not see SyncLockTimeout. It may exit non-zero for
        # other reasons (no real cloud), but the lock-contention error
        # text must not appear.
        assert "writer is already running" not in result.output.lower()
        assert "another ohtv writer" not in result.output.lower()
    finally:
        release_lock.set()
        holder.join(timeout=5)


# ---------------------------------------------------------------------------
# new_on_cloud vs missing_locally cutoff partition
# ---------------------------------------------------------------------------


def test_cutoff_partition_separates_new_from_missing(
    sync_manager_factory, fake_cloud: FakeCloudClient,
):
    """``created_at`` partitions missing-locally items into the right bucket."""
    seed = FakeConversation(
        id="seed1",
        created_at=datetime(2024, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=_UTC),
    )
    fake_cloud.add(seed)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()  # establishes the cutoff at "now"

    # 1) Item with created_at BEFORE cutoff (e.g. 2020). Missing locally
    #    (never downloaded) — should land in ``missing_locally``.
    old_missing = FakeConversation(
        id="oldmissing",
        created_at=datetime(2020, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=_UTC),
    )
    fake_cloud.add(old_missing)
    # 2) Item with created_at AFTER cutoff (year 2099). Should land in
    #    ``new_on_cloud`` (next sync will fetch).
    new_after = FakeConversation(
        id="newafter",
        created_at=datetime(2099, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2099, 1, 1, tzinfo=_UTC),
    )
    fake_cloud.add(new_after)

    result = manager.repair(fix=False)
    assert "oldmissing" in result.missing_locally_ids
    assert "newafter" in result.new_on_cloud_ids
    # And vice versa: they don't cross-pollinate.
    assert "oldmissing" not in result.new_on_cloud_ids
    assert "newafter" not in result.missing_locally_ids
