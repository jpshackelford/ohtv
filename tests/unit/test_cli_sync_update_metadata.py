"""CLI behavior tests for ``ohtv sync --update-metadata`` (Issue #86).

These tests focus on:
- Mutual exclusion validation for the new flag
- The auto-run gate after a normal sync (fires only when
  ``result.new + result.updated > 0`` and not in dry-run / force)
- That the explicit flag does not trigger the auto-run a second time

The underlying ``SyncManager.update_metadata()`` logic is covered in
``test_sync.py``; here we only exercise the CLI plumbing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ohtv.cli import main
from ohtv.sync import MetadataRefreshResult, SyncResult


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _empty_sync_result(new: int = 0, updated: int = 0) -> SyncResult:
    return SyncResult(new=new, updated=updated)


# =====================================================================
# Mutual exclusion
# =====================================================================


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--force"],
        ["--since", "2024-01-01"],
        ["--max-new", "10"],
        ["--repair"],
        ["--status"],
    ],
)
def test_update_metadata_rejects_conflicting_flag(
    runner: CliRunner, extra_args: list[str]
) -> None:
    """Combining --update-metadata with any of these must exit non-zero."""
    # Avoid touching the real SyncManager/config — fail fast on flag check
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr,
    ):
        mock_cfg.return_value = MagicMock(api_key="x")
        mock_mgr.return_value = MagicMock()
        result = runner.invoke(main, ["sync", "--update-metadata"] + extra_args)

    assert result.exit_code != 0
    assert "--update-metadata cannot be combined with" in result.output


def test_update_metadata_alone_does_not_error_on_flags(runner: CliRunner) -> None:
    """--update-metadata on its own must not trip the mutual-exclusion check."""
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr,
    ):
        mock_cfg.return_value = MagicMock(api_key="key")
        manager = MagicMock()
        manager.update_metadata.return_value = MetadataRefreshResult(checked=0)
        mock_mgr.return_value = manager

        result = runner.invoke(main, ["sync", "--update-metadata", "--quiet"])

    assert result.exit_code == 0
    manager.update_metadata.assert_called_once()
    # No trajectory downloads should ever happen
    assert not manager.sync.called


def test_update_metadata_errors_without_api_key(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr,
    ):
        cfg = MagicMock()
        cfg.api_key = ""  # explicit empty
        mock_cfg.return_value = cfg
        mock_mgr.return_value = MagicMock()

        result = runner.invoke(main, ["sync", "--update-metadata"])

    # Exit code from _error_no_api_key should be nonzero
    assert result.exit_code != 0


# =====================================================================
# Auto-run gate
# =====================================================================


def _patched_sync_context(*, sync_result: SyncResult, mgr: MagicMock):
    """Patch the SyncManager + the post-sync helpers used by the CLI.

    The CLI calls ``_run_sync`` (we stub at SyncManager.sync) and
    ``_run_post_sync_processing`` (stubbed out to avoid DB scans).
    """
    sync_patch = patch.object(mgr, "sync", return_value=sync_result)
    post_patch = patch("ohtv.cli._run_post_sync_processing")
    return sync_patch, post_patch


def test_auto_run_fires_when_new_conversations_synced(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
        patch("ohtv.cli._run_post_sync_processing"),
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        # First call: sync. Second call: update_metadata.
        manager.sync.return_value = _empty_sync_result(new=1, updated=0)
        manager.update_metadata.return_value = MetadataRefreshResult(checked=1)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(main, ["sync", "--quiet"])

    assert result.exit_code == 0, result.output
    manager.sync.assert_called_once()
    # Auto-run fires because result.new + result.updated > 0
    manager.update_metadata.assert_called_once()


def test_auto_run_fires_when_updated_conversations_synced(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
        patch("ohtv.cli._run_post_sync_processing"),
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        manager.sync.return_value = _empty_sync_result(new=0, updated=3)
        manager.update_metadata.return_value = MetadataRefreshResult(checked=3)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(main, ["sync", "--quiet"])

    assert result.exit_code == 0, result.output
    manager.update_metadata.assert_called_once()


def test_auto_run_skipped_when_nothing_new(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
        patch("ohtv.cli._run_post_sync_processing"),
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        manager.sync.return_value = _empty_sync_result(new=0, updated=0)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(main, ["sync", "--quiet"])

    assert result.exit_code == 0, result.output
    manager.sync.assert_called_once()
    # No auto-run: nothing new + nothing updated
    manager.update_metadata.assert_not_called()


def test_auto_run_skipped_on_dry_run(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        # Even with new conversations, dry-run must skip the metadata refresh
        manager.sync.return_value = _empty_sync_result(new=5, updated=2)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(main, ["sync", "--dry-run", "--quiet"])

    assert result.exit_code == 0, result.output
    manager.update_metadata.assert_not_called()


def test_auto_run_skipped_on_force(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
        patch("ohtv.cli._run_post_sync_processing"),
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        manager.sync.return_value = _empty_sync_result(new=5, updated=2)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(main, ["sync", "--force", "--quiet"])

    assert result.exit_code == 0, result.output
    # --force was used; auto-run must not fire
    manager.update_metadata.assert_not_called()


def test_explicit_update_metadata_does_not_call_sync(runner: CliRunner) -> None:
    """`--update-metadata` is metadata-only; never invokes a real sync."""
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        manager.update_metadata.return_value = MetadataRefreshResult(checked=2)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(main, ["sync", "--update-metadata", "--quiet"])

    assert result.exit_code == 0, result.output
    manager.sync.assert_not_called()
    manager.update_metadata.assert_called_once()


def test_explicit_update_metadata_passes_dry_run(runner: CliRunner) -> None:
    with (
        patch("ohtv.cli.Config.from_env") as mock_cfg,
        patch("ohtv.cli.SyncManager") as mock_mgr_cls,
    ):
        mock_cfg.return_value = MagicMock(api_key="k")
        manager = MagicMock()
        manager.update_metadata.return_value = MetadataRefreshResult(checked=0)
        mock_mgr_cls.return_value = manager

        result = runner.invoke(
            main, ["sync", "--update-metadata", "--dry-run", "--quiet"]
        )

    assert result.exit_code == 0, result.output
    manager.update_metadata.assert_called_once_with(dry_run=True)
