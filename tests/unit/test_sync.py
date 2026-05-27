"""Unit tests for the sync module."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ohtv.sync import (
    MetadataDiff,
    MetadataRefreshResult,
    RepairResult,
    SyncManager,
    SyncManifest,
    SyncResult,
    _metadata_differs,
    _normalize_labels,
    _read_selected_branch,
)
# Issue #110: _RecordingCloudClient (formerly inline at line 890) and
# _create_minimal_zip (formerly inline at line 465) have moved into the
# shared cloud-sync test harness. Keep the local names so the 27+ existing
# call sites stay untouched while the harness becomes the single source of
# truth for cloud-sync fakes.
from unit.sync.builders import make_trajectory_zip as _create_minimal_zip
from unit.sync.fakes import RecordingCloudClient as _RecordingCloudClient


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_has_skipped_new_true_when_skipped(self):
        result = SyncResult(skipped_new=5)
        assert result.has_skipped_new is True

    def test_has_skipped_new_false_when_zero(self):
        result = SyncResult(skipped_new=0)
        assert result.has_skipped_new is False

    def test_total_synced_includes_new_and_updated(self):
        result = SyncResult(new=3, updated=2)
        assert result.total_synced == 5

    def test_has_failures_true_when_failed(self):
        result = SyncResult(failed=1)
        assert result.has_failures is True

    def test_has_failures_false_when_zero(self):
        result = SyncResult(failed=0)
        assert result.has_failures is False


class TestSyncManifest:
    """Tests for SyncManifest dataclass."""

    def test_load_creates_empty_when_file_missing(self, tmp_path):
        path = tmp_path / "missing.json"
        manifest = SyncManifest.load(path)
        assert manifest.last_sync_at is None
        assert manifest.sync_count == 0
        assert manifest.conversations == {}
        assert manifest.failed_ids == []

    def test_load_parses_existing_file(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({
            "last_sync_at": "2024-01-01T12:00:00Z",
            "sync_count": 5,
            "conversations": {"abc123": {"title": "Test"}},
            "failed_ids": ["def456"],
        }))
        manifest = SyncManifest.load(path)
        assert manifest.last_sync_at == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert manifest.sync_count == 5
        assert manifest.conversations == {"abc123": {"title": "Test"}}
        assert manifest.failed_ids == ["def456"]

    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "manifest.json"
        manifest = SyncManifest(
            last_sync_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            sync_count=3,
            conversations={"abc": {"title": "Hello"}},
            failed_ids=["xyz"],
        )
        manifest.save(path)
        
        data = json.loads(path.read_text())
        assert data["last_sync_at"] == "2024-01-01T12:00:00Z"
        assert data["sync_count"] == 3
        assert data["conversations"] == {"abc": {"title": "Hello"}}
        assert data["failed_ids"] == ["xyz"]


class TestSyncManagerUpdateResult:
    """Tests for SyncManager._update_result method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.api_key = "test-key"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_updates_new_count(self, manager):
        result = SyncResult()
        manager._update_result(result, "new")
        assert result.new == 1

    def test_updates_updated_count(self, manager):
        result = SyncResult()
        manager._update_result(result, "updated")
        assert result.updated == 1

    def test_updates_unchanged_count(self, manager):
        result = SyncResult()
        manager._update_result(result, "unchanged")
        assert result.unchanged == 1

    def test_updates_failed_count(self, manager):
        result = SyncResult()
        manager._update_result(result, "failed")
        assert result.failed == 1

    def test_updates_skipped_count(self, manager):
        result = SyncResult()
        manager._update_result(result, "skipped")
        assert result.skipped_new == 1


class TestSyncManagerDetermineAction:
    """Tests for SyncManager._determine_action method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.api_key = "test-key"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            mgr = SyncManager(config)
            # Pre-populate manifest with a known conversation
            mgr.manifest.conversations = {
                "existing123": {
                    "title": "Existing",
                    "updated_at": "2024-01-01T12:00:00Z",
                }
            }
            return mgr

    def test_returns_new_for_unknown_conversation(self, manager):
        action = manager._determine_action("newconv456", "2024-01-02T12:00:00Z", force=False)
        assert action == "new"

    def test_returns_unchanged_for_existing_not_updated(self, manager):
        action = manager._determine_action("existing123", "2024-01-01T12:00:00Z", force=False)
        assert action == "unchanged"

    def test_returns_updated_when_cloud_is_newer(self, manager):
        action = manager._determine_action("existing123", "2024-01-02T12:00:00Z", force=False)
        assert action == "updated"

    def test_returns_updated_when_force_true(self, manager):
        action = manager._determine_action("existing123", "2024-01-01T12:00:00Z", force=True)
        assert action == "updated"


class TestSyncManagerMaxNew:
    """Tests for max_new limiting behavior."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            mgr = SyncManager(config)
            # Pre-populate manifest with one existing conversation
            mgr.manifest.conversations = {
                "existing001": {
                    "title": "Existing",
                    "updated_at": "2024-01-01T12:00:00Z",
                }
            }
            return mgr

    def test_categorize_skips_new_when_limit_reached(self, manager):
        """Test that new conversations are skipped when max_new limit is reached."""
        result = SyncResult()
        
        # 6 new conversations, but limit is 5
        conversations = [
            {"id": f"newconv{i:03d}", "updated_at": "2024-01-02T12:00:00Z", "title": f"New Conv {i}"}
            for i in range(6)
        ]
        
        work_items = manager._categorize_conversations(
            conversations=conversations,
            force=False,
            max_new=5,
            result=result,
        )
        
        # First 5 should be "new", 6th should be "skipped"
        actions = [action for _, action in work_items]
        assert actions.count("new") == 5
        assert actions.count("skipped") == 1
        assert result.skipped_new == 1

    def test_categorize_allows_new_when_under_limit(self, manager):
        """Test that new conversations are allowed when under max_new limit."""
        result = SyncResult()
        
        # 3 new conversations, limit is 5
        conversations = [
            {"id": f"newconv{i:03d}", "updated_at": "2024-01-02T12:00:00Z", "title": f"New Conv {i}"}
            for i in range(3)
        ]
        
        work_items = manager._categorize_conversations(
            conversations=conversations,
            force=False,
            max_new=5,  # Still under limit
            result=result,
        )
        
        # All 3 should be "new"
        actions = [action for _, action in work_items]
        assert all(a == "new" for a in actions)
        assert result.skipped_new == 0

    def test_categorize_allows_updates_regardless_of_limit(self, manager):
        """Test that updates are always allowed, even when max_new limit is reached."""
        result = SyncResult()
        
        # 5 new + 1 update, limit is 5
        conversations = [
            {"id": f"newconv{i:03d}", "updated_at": "2024-01-02T12:00:00Z", "title": f"New Conv {i}"}
            for i in range(5)
        ]
        # Add an update (existing001 is in manager.manifest.conversations)
        conversations.append({"id": "existing001", "updated_at": "2024-01-02T12:00:00Z", "title": "Updated"})
        
        work_items = manager._categorize_conversations(
            conversations=conversations,
            force=False,
            max_new=5,  # Limit reached for new, but updates should still work
            result=result,
        )
        
        # First 5 new + 1 update
        actions = [action for _, action in work_items]
        assert actions.count("new") == 5
        assert actions.count("updated") == 1
        assert "skipped" not in actions
        assert result.skipped_new == 0


class TestSyncManagerFinalizeSync:
    """Tests for SyncManager._finalize_sync method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.api_key = "test-key"
        
        manifest_path = tmp_path / "manifest.json"
        with patch("ohtv.sync.get_manifest_path", return_value=manifest_path):
            return SyncManager(config)

    def test_advances_cutoff_when_no_skipped(self, manager):
        """Test that last_sync_at is updated when no conversations were skipped."""
        result = SyncResult(new=3, updated=2, skipped_new=0, failed=0)
        
        manager._finalize_sync(result)
        
        assert manager.manifest.last_sync_at is not None

    def test_does_not_advance_cutoff_when_skipped(self, manager):
        """Test that last_sync_at is NOT updated when conversations were skipped."""
        result = SyncResult(new=3, skipped_new=5, failed=0)
        
        manager._finalize_sync(result)
        
        assert manager.manifest.last_sync_at is None

    def test_does_not_advance_cutoff_when_failed(self, manager):
        """Test that last_sync_at is NOT updated when there were failures."""
        result = SyncResult(new=3, failed=1)
        
        manager._finalize_sync(result)
        
        assert manager.manifest.last_sync_at is None

    def test_increments_sync_count(self, manager):
        """Test that sync_count is always incremented."""
        assert manager.manifest.sync_count == 0
        
        result = SyncResult(new=1)
        manager._finalize_sync(result)
        
        assert manager.manifest.sync_count == 1


class TestSyncManagerCleanup:
    """Tests for SyncManager._cleanup_conversation_dir method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.api_key = "test-key"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_removes_existing_directory(self, manager):
        """Test that existing conversation directory is removed."""
        conv_dir = manager.config.synced_conversations_dir / "conv123"
        conv_dir.mkdir(parents=True)
        (conv_dir / "events").mkdir()
        (conv_dir / "events" / "event-00001-abc.json").write_text("{}")
        
        manager._cleanup_conversation_dir("conv123")
        
        assert not conv_dir.exists()

    def test_handles_nonexistent_directory(self, manager):
        """Test that cleanup doesn't fail for nonexistent directory."""
        # Should not raise
        manager._cleanup_conversation_dir("nonexistent123")


class TestSyncManagerGetLocalConversationCount:
    """Tests for SyncManager.get_local_conversation_count method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.api_key = "test-key"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_returns_zero_for_empty_manifest(self, manager):
        assert manager.get_local_conversation_count() == 0

    def test_returns_count_from_manifest(self, manager):
        manager.manifest.conversations = {
            "conv1": {},
            "conv2": {},
            "conv3": {},
        }
        assert manager.get_local_conversation_count() == 3


class TestSyncManagerParallel:
    """Tests for parallel sync functionality."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.synced_conversations_dir.mkdir(parents=True)
        config.api_key = "test-key"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_download_parallel_processes_all_items(self, manager):
        """Test that parallel download processes all work items."""
        result = SyncResult()
        
        # Create work items
        work_items = [
            ({"id": f"conv{i:03d}", "updated_at": "2024-01-01T00:00:00Z", "title": f"Conv {i}"}, "new")
            for i in range(5)
        ]
        
        # Mock client
        mock_client = MagicMock()
        mock_client.download_trajectory.return_value = _create_minimal_zip()
        
        # Track progress calls
        progress_calls = []
        def track_progress(conv_id, title, action):
            progress_calls.append((conv_id, action))
        
        manager._download_parallel(
            client=mock_client,
            work_items=work_items,
            result=result,
            on_progress=track_progress,
        )
        
        # All should succeed
        assert result.new == 5
        assert result.failed == 0
        assert len(progress_calls) == 5

    def test_download_sequential_processes_all_items(self, manager):
        """Test that sequential download processes all work items."""
        result = SyncResult()
        
        work_items = [
            ({"id": f"conv{i:03d}", "updated_at": "2024-01-01T00:00:00Z", "title": f"Conv {i}"}, "new")
            for i in range(3)
        ]
        
        mock_client = MagicMock()
        mock_client.download_trajectory.return_value = _create_minimal_zip()
        
        progress_calls = []
        def track_progress(conv_id, title, action):
            progress_calls.append((conv_id, action))
        
        manager._download_sequential(
            client=mock_client,
            work_items=work_items,
            result=result,
            on_progress=track_progress,
        )
        
        assert result.new == 3
        assert len(progress_calls) == 3

    def test_shutdown_check_stops_parallel_download(self, manager):
        """Test that shutdown_check stops parallel processing."""
        result = SyncResult()
        
        # Create many work items
        work_items = [
            ({"id": f"conv{i:03d}", "updated_at": "2024-01-01T00:00:00Z", "title": f"Conv {i}"}, "new")
            for i in range(20)
        ]
        
        mock_client = MagicMock()
        mock_client.download_trajectory.return_value = _create_minimal_zip()
        
        # Shutdown after first few items
        call_count = [0]
        def shutdown_after_3():
            call_count[0] += 1
            return call_count[0] > 3
        
        manager._download_parallel(
            client=mock_client,
            work_items=work_items,
            result=result,
            on_progress=None,
            shutdown_check=shutdown_after_3,
        )
        
        # Should have processed some but not all
        assert result.new < 20


class TestRepairResult:
    """Tests for RepairResult dataclass."""

    def test_is_consistent_when_no_discrepancies(self):
        result = RepairResult(
            manifest_count=10,
            disk_counts_by_dir={"/path/to/dir": 10},
            ghost_entries=[],
            orphaned_files=[],
        )
        assert result.is_consistent is True
        assert result.disk_count == 10

    def test_is_consistent_false_when_ghosts(self):
        result = RepairResult(
            ghost_entries=["abc123"],
            orphaned_files=[],
        )
        assert result.is_consistent is False

    def test_is_consistent_false_when_orphaned(self):
        result = RepairResult(
            ghost_entries=[],
            orphaned_files=["xyz789"],
        )
        assert result.is_consistent is False

    def test_cloud_disk_match_when_equal(self):
        result = RepairResult(cloud_count=100, disk_counts_by_dir={"/path": 100})
        assert result.cloud_disk_match is True

    def test_cloud_disk_match_false_when_different(self):
        result = RepairResult(cloud_count=100, disk_counts_by_dir={"/path": 50})
        assert result.cloud_disk_match is False

    def test_disk_count_sums_multiple_directories(self):
        result = RepairResult(
            disk_counts_by_dir={
                "/path/to/synced": 50,
                "/path/to/local": 30,
                "/path/to/extra": 20,
            }
        )
        assert result.disk_count == 100

    def test_disk_count_empty_when_no_directories(self):
        result = RepairResult()
        assert result.disk_count == 0


class TestSyncManagerRepair:
    """Tests for SyncManager.repair method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.synced_conversations_dir.mkdir(parents=True)
        config.local_conversations_dir = tmp_path / "local"  # Does not exist initially
        config.extra_conversation_paths = []
        config.api_key = None  # No API key - skip cloud check
        config.cloud_api_url = "https://example.com"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_detects_consistent_state(self, manager):
        """Test that repair detects when manifest and disk are consistent."""
        # Add conversation to manifest
        manager.manifest.conversations = {
            "abc123": {"title": "Test", "event_count": 5},
        }
        
        # Create matching directory on disk
        conv_dir = manager.config.synced_conversations_dir / "abc123"
        conv_dir.mkdir()
        
        result = manager.repair(fix=False, check_cloud=False)
        
        assert result.manifest_count == 1
        assert result.disk_count == 1
        assert result.is_consistent is True
        assert len(result.ghost_entries) == 0
        assert len(result.orphaned_files) == 0

    def test_detects_ghost_entries(self, manager):
        """Test that repair detects entries in manifest but not on disk."""
        # Add conversation to manifest but NOT on disk
        manager.manifest.conversations = {
            "ghost123": {"title": "Ghost", "event_count": 5},
        }
        
        result = manager.repair(fix=False, check_cloud=False)
        
        assert result.manifest_count == 1
        assert result.disk_count == 0
        assert result.is_consistent is False
        assert "ghost123" in result.ghost_entries

    def test_detects_orphaned_files(self, manager):
        """Test that repair detects files on disk but not in manifest."""
        # Create directory on disk but NOT in manifest
        conv_dir = manager.config.synced_conversations_dir / "orphan456"
        conv_dir.mkdir()
        
        result = manager.repair(fix=False, check_cloud=False)
        
        assert result.manifest_count == 0
        assert result.disk_count == 1
        assert result.is_consistent is False
        assert "orphan456" in result.orphaned_files

    def test_normalizes_uuid_format(self, manager):
        """Test that repair handles UUID format with dashes."""
        # Add conversation to manifest without dashes (32 chars)
        manager.manifest.conversations = {
            "abc12345678901234567890123456abc": {"title": "Test"},
        }
        
        # Create directory on disk WITH dashes (UUID format: 8-4-4-4-12)
        uuid_format = "abc12345-6789-0123-4567-890123456abc"
        conv_dir = manager.config.synced_conversations_dir / uuid_format
        conv_dir.mkdir()
        
        result = manager.repair(fix=False, check_cloud=False)
        
        # Should detect the match despite format difference
        assert result.is_consistent is True

    def test_fix_removes_ghost_entries(self, manager):
        """Test that repair with fix=True removes ghost entries."""
        # Add ghost entry
        manager.manifest.conversations = {
            "ghost123": {"title": "Ghost"},
            "real456": {"title": "Real"},
        }
        
        # Only create real456 on disk
        (manager.config.synced_conversations_dir / "real456").mkdir()
        
        result = manager.repair(fix=True, check_cloud=False)
        
        assert result.removed_from_manifest == 1
        assert "ghost123" not in manager.manifest.conversations
        assert "real456" in manager.manifest.conversations

    def test_fix_adds_orphaned_files(self, manager):
        """Test that repair with fix=True adds orphaned files to manifest."""
        # Create orphaned directory with events subdirectory
        conv_dir = manager.config.synced_conversations_dir / "orphan789"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        # Add an event file (count_events looks for files starting with "event_")
        (events_dir / "event_000001_abc.json").write_text('{"id": "abc"}')
        
        result = manager.repair(fix=True, check_cloud=False)
        
        assert result.added_to_manifest == 1
        assert "orphan789" in manager.manifest.conversations
        # event_count may be 0 or 1 depending on count_events implementation
        assert "event_count" in manager.manifest.conversations["orphan789"]

    def test_fix_saves_manifest(self, manager):
        """Test that repair with fix=True saves the updated manifest."""
        # Create orphaned directory
        conv_dir = manager.config.synced_conversations_dir / "orphan000"
        conv_dir.mkdir()
        
        result = manager.repair(fix=True, check_cloud=False)
        
        # Verify manifest was saved by reloading
        reloaded = SyncManifest.load(manager.manifest_path)
        assert "orphan000" in reloaded.conversations

    def test_no_changes_when_fix_false(self, manager):
        """Test that repair with fix=False doesn't modify anything."""
        # Create orphaned directory
        conv_dir = manager.config.synced_conversations_dir / "orphan111"
        conv_dir.mkdir()
        
        result = manager.repair(fix=False, check_cloud=False)
        
        assert result.added_to_manifest == 0
        assert result.removed_from_manifest == 0
        assert "orphan111" not in manager.manifest.conversations

    def test_counts_multiple_directories(self, manager, tmp_path):
        """Test that repair counts conversations in multiple directories."""
        # Create synced conversations
        (manager.config.synced_conversations_dir / "synced1").mkdir()
        (manager.config.synced_conversations_dir / "synced2").mkdir()
        
        # Create local conversations directory
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        (local_dir / "local1").mkdir()
        (local_dir / "local2").mkdir()
        (local_dir / "local3").mkdir()
        manager.config.local_conversations_dir = local_dir
        
        # Create extra conversations directory
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        (extra_dir / "extra1").mkdir()
        manager.config.extra_conversation_paths = [extra_dir]
        
        result = manager.repair(fix=False, check_cloud=False)
        
        # Total should include all directories
        assert result.disk_count == 6
        
        # Verify breakdown
        assert len(result.disk_counts_by_dir) == 3
        assert result.disk_counts_by_dir[str(manager.config.synced_conversations_dir)] == 2
        assert result.disk_counts_by_dir[str(local_dir)] == 3
        assert result.disk_counts_by_dir[str(extra_dir)] == 1

    def test_omits_empty_directories_from_breakdown(self, manager, tmp_path):
        """Test that directories with zero conversations aren't in the breakdown."""
        # Create one synced conversation
        (manager.config.synced_conversations_dir / "synced1").mkdir()
        
        # Local directory exists but is empty
        local_dir = tmp_path / "local"
        local_dir.mkdir()
        manager.config.local_conversations_dir = local_dir
        
        result = manager.repair(fix=False, check_cloud=False)
        
        assert result.disk_count == 1
        assert len(result.disk_counts_by_dir) == 1
        assert str(local_dir) not in result.disk_counts_by_dir

    def test_handles_nonexistent_extra_paths(self, manager, tmp_path):
        """Test that repair handles extra paths that don't exist."""
        (manager.config.synced_conversations_dir / "synced1").mkdir()
        
        # Point to nonexistent directory
        manager.config.extra_conversation_paths = [tmp_path / "nonexistent"]
        
        result = manager.repair(fix=False, check_cloud=False)
        
        assert result.disk_count == 1
        assert len(result.disk_counts_by_dir) == 1


class TestSyncManagerFindConversationDir:
    """Tests for SyncManager._find_conversation_dir method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.synced_conversations_dir.mkdir(parents=True)
        config.api_key = "test-key"
        
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_finds_dir_without_dashes(self, manager):
        """Test finding directory when ID has no dashes."""
        conv_id = "abc12345678901234567890123456"
        conv_dir = manager.config.synced_conversations_dir / conv_id
        conv_dir.mkdir()
        
        result = manager._find_conversation_dir(conv_id)
        
        assert result == conv_dir

    def test_finds_dir_with_uuid_format(self, manager):
        """Test finding directory when stored with UUID dashes."""
        # 32 hex chars (standard UUID without dashes)
        conv_id = "abc12345678901234567890123456abc"
        # Standard UUID format with dashes (8-4-4-4-12)
        uuid_format = "abc12345-6789-0123-4567-890123456abc"
        
        conv_dir = manager.config.synced_conversations_dir / uuid_format
        conv_dir.mkdir()
        
        result = manager._find_conversation_dir(conv_id)
        
        assert result == conv_dir

    def test_returns_none_for_nonexistent(self, manager):
        """Test that None is returned for nonexistent directory."""
        result = manager._find_conversation_dir("nonexistent123")
        
        assert result is None


# =====================================================================
# Issue #86: ohtv sync --update-metadata
# =====================================================================


class TestNormalizeLabels:
    """Tests for the module-level _normalize_labels helper."""

    def test_none_returns_none(self):
        assert _normalize_labels(None) is None

    def test_empty_dict_returns_none(self):
        assert _normalize_labels({}) is None

    def test_non_dict_returns_none(self):
        assert _normalize_labels("not a dict") is None
        assert _normalize_labels(42) is None
        assert _normalize_labels([]) is None

    def test_dict_with_content_returned_as_is(self):
        assert _normalize_labels({"qa": "smoke"}) == {"qa": "smoke"}

    def test_coerces_non_string_values_defensively(self):
        # Int values should never come from the API, but be safe in the
        # face of mixed input.
        assert _normalize_labels({"k": 1}) == {"k": "1"}


class TestMetadataDiffers:
    """Tests for _metadata_differs() (cloud listing entry vs manifest entry).

    Issue #87 swapped the legacy ``(title_changed, labels_changed)`` tuple
    return for a ``MetadataDiff`` struct that also tracks
    ``selected_repository`` and ``created_at``. Existing tests assert on
    the booleans only.
    """

    def test_neither_changed(self):
        cloud = {"title": "Same", "tags": {"k": "v"}}
        manifest = {"title": "Same", "labels": {"k": "v"}}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (False, False)
        assert diff.any_changed is False

    def test_title_only(self):
        cloud = {"title": "New", "tags": {"k": "v"}}
        manifest = {"title": "Old", "labels": {"k": "v"}}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (True, False)

    def test_labels_only(self):
        cloud = {"title": "Same", "tags": {"k": "v2"}}
        manifest = {"title": "Same", "labels": {"k": "v"}}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (False, True)

    def test_both_changed(self):
        cloud = {"title": "New", "tags": {"k": "v2"}}
        manifest = {"title": "Old", "labels": {"k": "v"}}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (True, True)

    def test_empty_dict_labels_equals_none(self):
        """{} from API must compare equal to None from manifest (no churn)."""
        cloud = {"title": "Same", "tags": {}}
        manifest = {"title": "Same", "labels": None}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (False, False)

    def test_none_labels_equals_missing(self):
        cloud = {"title": "Same"}  # No tags key at all
        manifest = {"title": "Same", "labels": None}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (False, False)

    def test_reordered_dict_keys_equal(self):
        cloud = {"title": "Same", "tags": {"a": "1", "b": "2"}}
        manifest = {"title": "Same", "labels": {"b": "2", "a": "1"}}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (False, False)

    def test_empty_title_equals_missing(self):
        """Empty string title collapses to None for comparison."""
        cloud = {"title": "", "tags": None}
        manifest = {"title": None, "labels": None}
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (False, False)

    def test_missing_manifest_title_treated_as_none(self):
        cloud = {"title": "X", "tags": None}
        manifest = {}  # No title, no labels
        diff = _metadata_differs(cloud, manifest)
        assert (diff.title_changed, diff.labels_changed) == (True, False)


class TestMetadataRefreshResult:
    """Tests for the MetadataRefreshResult dataclass."""

    def test_total_changed_subtracts_both(self):
        # 3 title changes + 2 label changes, 1 was both -> 4 distinct touches
        r = MetadataRefreshResult(
            title_changed=3, labels_changed=2, both_changed=1
        )
        assert r.total_changed == 4

    def test_has_errors_false_when_empty(self):
        assert MetadataRefreshResult().has_errors is False

    def test_has_errors_true_when_nonempty(self):
        r = MetadataRefreshResult(errors=[("conv1", "boom")])
        assert r.has_errors is True


class TestUpdateMetadata:
    """Tests for SyncManager.update_metadata() (Issue #86)."""

    @pytest.fixture
    def manager(self, tmp_path):
        """SyncManager with a tmp manifest and mocked config."""
        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        config.synced_conversations_dir = tmp_path / "synced"
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_raises_when_no_api_key(self, tmp_path):
        config = MagicMock()
        config.api_key = ""
        config.cloud_api_url = "https://example.com"
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            manager = SyncManager(config)
        with pytest.raises(ValueError, match="API key required"):
            manager.update_metadata()

    def test_title_change_is_written_to_manifest(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Old title",
                "updated_at": "2024-01-01T00:00:00Z",
                "event_count": 5,
                "downloaded_at": "2024-01-02T00:00:00Z",
                "labels": None,
            },
        }
        client = _RecordingCloudClient(
            [{"id": "abc", "title": "Renamed", "tags": None}]
        )

        # Skip DB writes for this test - we only care about manifest behavior
        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert client.download_calls == []
        assert result.checked == 1
        assert result.title_changed == 1
        assert result.labels_changed == 0
        assert result.both_changed == 0
        assert result.unchanged == 0
        assert manager.manifest.conversations["abc"]["title"] == "Renamed"
        # Bookkeeping fields preserved byte-for-byte
        assert manager.manifest.conversations["abc"]["updated_at"] == "2024-01-01T00:00:00Z"
        assert manager.manifest.conversations["abc"]["event_count"] == 5
        assert manager.manifest.conversations["abc"]["downloaded_at"] == "2024-01-02T00:00:00Z"

    def test_labels_change_normalizes_tags_dict(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "2024-01-01T00:00:00Z",
                "event_count": 5,
                "downloaded_at": "2024-01-02T00:00:00Z",
                "labels": None,
            },
        }
        client = _RecordingCloudClient(
            [{"id": "abc", "title": "Same", "tags": {"qa": "smoke"}}]
        )

        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert client.download_calls == []
        assert result.labels_changed == 1
        assert result.title_changed == 0
        assert manager.manifest.conversations["abc"]["labels"] == {"qa": "smoke"}

    def test_both_changed_counts_correctly(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Old",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            },
        }
        client = _RecordingCloudClient(
            [{"id": "abc", "title": "New", "tags": {"k": "v"}}]
        )

        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert result.title_changed == 1
        assert result.labels_changed == 1
        assert result.both_changed == 1
        # total_changed is the dedup-by-conversation count
        assert result.total_changed == 1

    def test_unchanged_does_not_rewrite_manifest(self, manager, tmp_path):
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "2024-01-01T00:00:00Z",
                "event_count": 5,
                "downloaded_at": "2024-01-02T00:00:00Z",
                "labels": None,
            },
        }
        # Save manifest, capture mtime
        manager.manifest.save(manager.manifest_path)
        import os
        before_mtime = os.path.getmtime(manager.manifest_path)

        client = _RecordingCloudClient(
            [{"id": "abc", "title": "Same", "tags": None}]
        )
        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        # mtime should be untouched
        after_mtime = os.path.getmtime(manager.manifest_path)
        assert before_mtime == after_mtime
        assert result.unchanged == 1
        assert result.title_changed == 0

    def test_dry_run_does_not_mutate(self, manager, tmp_path):
        manager.manifest.conversations = {
            "abc": {
                "title": "Old",
                "updated_at": "2024-01-01T00:00:00Z",
                "event_count": 1,
                "downloaded_at": "2024-01-02T00:00:00Z",
                "labels": None,
            },
        }
        manager.manifest.save(manager.manifest_path)
        import os
        before_mtime = os.path.getmtime(manager.manifest_path)

        client = _RecordingCloudClient(
            [{"id": "abc", "title": "New", "tags": {"k": "v"}}]
        )
        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(dry_run=True, client=client)

        # Counters report the diff
        assert result.title_changed == 1
        assert result.labels_changed == 1
        # ... but manifest is untouched on disk
        after_mtime = os.path.getmtime(manager.manifest_path)
        assert before_mtime == after_mtime
        # ... and in memory
        assert manager.manifest.conversations["abc"]["title"] == "Old"
        assert manager.manifest.conversations["abc"]["labels"] is None

    def test_never_downloads_trajectories(self, manager):
        # Even when every conversation has a diff, download is never called.
        manager.manifest.conversations = {
            f"c{i}": {
                "title": f"old{i}",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            }
            for i in range(5)
        }
        client = _RecordingCloudClient(
            [{"id": f"c{i}", "title": f"new{i}", "tags": None} for i in range(5)]
        )

        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert client.download_calls == []
        assert result.title_changed == 5

    def test_does_not_touch_sync_bookkeeping(self, manager):
        # Capture before
        before_sync_count = manager.manifest.sync_count
        before_last_sync = manager.manifest.last_sync_at
        manager.manifest.conversations = {
            "abc": {
                "title": "old",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            },
        }
        client = _RecordingCloudClient(
            [{"id": "abc", "title": "new", "tags": None}]
        )
        with patch.object(manager, "_get_conversation_store", return_value=None):
            manager.update_metadata(client=client)

        assert manager.manifest.sync_count == before_sync_count
        assert manager.manifest.last_sync_at == before_last_sync

    def test_new_on_cloud_and_missing_on_cloud_counts(self, manager):
        manager.manifest.conversations = {
            "in_both": {
                "title": "Same",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            },
            "only_local": {
                "title": "Local only",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            },
        }
        client = _RecordingCloudClient([
            {"id": "in_both", "title": "Same", "tags": None},
            {"id": "only_cloud_a", "title": "Cloud A", "tags": None},
            {"id": "only_cloud_b", "title": "Cloud B", "tags": None},
        ])

        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert result.checked == 1   # only in_both
        assert result.new_on_cloud == 2
        assert result.missing_on_cloud == 1
        # And missing/new conversations were NOT added/removed
        assert "only_cloud_a" not in manager.manifest.conversations
        assert "only_local" in manager.manifest.conversations

    def test_calls_db_update_when_changed(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Old",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            },
        }
        store = MagicMock()
        store.conn = MagicMock()

        with patch.object(manager, "_get_conversation_store", return_value=store):
            client = _RecordingCloudClient(
                [{"id": "abc", "title": "New", "tags": {"k": "v"}}]
            )
            manager.update_metadata(client=client)

        store.update_metadata.assert_called_once_with(
            "abc", title="New", labels={"k": "v"}
        )
        # And the commit was called (any change applied)
        store.conn.commit.assert_called()

    def test_skips_db_write_on_dry_run(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Old",
                "updated_at": "x",
                "event_count": 1,
                "downloaded_at": "y",
                "labels": None,
            },
        }
        store = MagicMock()
        with patch.object(manager, "_get_conversation_store", return_value=store):
            client = _RecordingCloudClient(
                [{"id": "abc", "title": "New", "tags": None}]
            )
            manager.update_metadata(dry_run=True, client=client)

        store.update_metadata.assert_not_called()

    def test_progress_callback_invoked(self, manager):
        manager.manifest.conversations = {
            "a": {"title": "x", "updated_at": "u", "event_count": 1, "downloaded_at": "d", "labels": None},
            "b": {"title": "x", "updated_at": "u", "event_count": 1, "downloaded_at": "d", "labels": None},
        }
        client = _RecordingCloudClient([
            {"id": "a", "title": "x", "tags": None},
            {"id": "b", "title": "x", "tags": None},
        ])
        events: list[tuple[int, int]] = []
        with patch.object(manager, "_get_conversation_store", return_value=None):
            manager.update_metadata(
                client=client,
                on_progress=lambda done, total: events.append((done, total)),
            )

        assert events == [(1, 2), (2, 2)]

    def test_db_failure_recorded_but_does_not_abort(self, manager):
        manager.manifest.conversations = {
            "a": {"title": "old", "updated_at": "u", "event_count": 1, "downloaded_at": "d", "labels": None},
            "b": {"title": "old", "updated_at": "u", "event_count": 1, "downloaded_at": "d", "labels": None},
        }
        store = MagicMock()
        store.update_metadata.side_effect = RuntimeError("db broke")
        with patch.object(manager, "_get_conversation_store", return_value=store):
            client = _RecordingCloudClient([
                {"id": "a", "title": "new", "tags": None},
                {"id": "b", "title": "new", "tags": None},
            ])
            result = manager.update_metadata(client=client)

        # Both manifest writes succeeded; both DB writes failed
        assert result.title_changed == 2
        assert len(result.errors) == 2
        for _, msg in result.errors:
            assert "db:" in msg
        # Manifest got the updates regardless
        assert manager.manifest.conversations["a"]["title"] == "new"
        assert manager.manifest.conversations["b"]["title"] == "new"

    def test_no_manifest_save_when_no_changes(self, manager, tmp_path):
        """If nothing differs, the manifest file is not rewritten on disk."""
        manager.manifest.conversations = {
            "a": {"title": "x", "updated_at": "u", "event_count": 1, "downloaded_at": "d", "labels": None},
        }
        manager.manifest.save(manager.manifest_path)
        import os
        before = os.path.getmtime(manager.manifest_path)

        client = _RecordingCloudClient(
            [{"id": "a", "title": "x", "tags": None}]
        )
        with patch.object(manager, "_get_conversation_store", return_value=None):
            manager.update_metadata(client=client)

        after = os.path.getmtime(manager.manifest_path)
        assert before == after

    def test_db_connection_closed_when_manifest_save_raises(self, manager):
        """If manifest.save() raises, the DB connection must still be closed.

        Regression guard for the resource leak in update_metadata(): the
        connection opened by _get_conversation_store() is owned by this
        method (ConversationStore is not a context manager), so it must be
        released via try/finally even if manifest.save() raises OSError
        (disk full, permission denied, etc.).
        """
        manager.manifest.conversations = {
            "a": {"title": "old", "updated_at": "u", "event_count": 1, "downloaded_at": "d", "labels": None},
        }
        store = MagicMock()
        store.conn = MagicMock()  # truthy + supports .close()
        with patch.object(manager, "_get_conversation_store", return_value=store), \
             patch.object(manager.manifest, "save", side_effect=OSError("disk full")):
            client = _RecordingCloudClient(
                [{"id": "a", "title": "new", "tags": None}]
            )
            with pytest.raises(OSError, match="disk full"):
                manager.update_metadata(client=client)

        # The exception propagated, but close() must still have been invoked.
        store.conn.close.assert_called_once()


class TestWriteManifestMetadata:
    """Tests for SyncManager._write_manifest_metadata()."""

    @pytest.fixture
    def manager(self, tmp_path):
        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_preserves_bookkeeping_fields(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Old",
                "updated_at": "2024-01-01T00:00:00Z",
                "event_count": 5,
                "downloaded_at": "2024-01-02T00:00:00Z",
                "labels": None,
            },
        }
        manager._write_manifest_metadata("abc", title="New", labels={"k": "v"})

        entry = manager.manifest.conversations["abc"]
        assert entry["title"] == "New"
        assert entry["labels"] == {"k": "v"}
        assert entry["updated_at"] == "2024-01-01T00:00:00Z"
        assert entry["event_count"] == 5
        assert entry["downloaded_at"] == "2024-01-02T00:00:00Z"


class TestUpdateMetadataRealDB:
    """Real on-disk SQLite regression test for the metadata-refresh path.

    Background (Issue #93 manual-test follow-up):
        The original ``_get_conversation_store`` called ``get_connection()``
        (a ``@contextmanager``) without entering it, so the ``ConversationStore``
        was constructed with a ``_GeneratorContextManager`` in ``self.conn``.
        ``update_metadata`` then blew up with::

            AttributeError: '_GeneratorContextManager' object has no attribute 'execute'

        Every test in :class:`TestUpdateMetadata` above patches
        ``_get_conversation_store`` to return a ``Mock`` (or ``None``), which
        hid the bug entirely. This test exercises the real
        ``ConversationStore`` against a real on-disk SQLite database so the
        store/connection wiring is actually verified.
    """

    def test_real_db_row_is_updated_and_no_errors(self, tmp_path):
        """End-to-end: refresh propagates new title + labels to the DB row."""
        import sqlite3

        from ohtv.db import migrate
        from ohtv.db.models import Conversation
        from ohtv.db.stores import ConversationStore

        # Real on-disk SQLite database (NOT in-memory and NOT mocked) so we
        # exercise the same code path as production.
        db_path = tmp_path / "index.db"
        seed_conn = sqlite3.connect(db_path)
        seed_conn.row_factory = sqlite3.Row
        seed_conn.execute("PRAGMA foreign_keys = ON")
        migrate(seed_conn)

        # Seed one conversation row with the *old* title/labels.
        ConversationStore(seed_conn).upsert(
            Conversation(
                id="abc123def456",  # already normalized (no dashes)
                location=str(tmp_path / "synced" / "abc123def456"),
                event_count=5,
                title="Old title",
                labels=None,
                source="cloud",
            )
        )
        seed_conn.commit()
        seed_conn.close()

        # Build a SyncManager whose DB resolution points at our temp DB.
        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        config.synced_conversations_dir = tmp_path / "synced"

        with (
            patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"),
            patch("ohtv.db.get_db_path", return_value=db_path),
        ):
            manager = SyncManager(config)
            manager.manifest.conversations = {
                "abc123def456": {
                    "title": "Old title",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "event_count": 5,
                    "downloaded_at": "2024-01-02T00:00:00Z",
                    "labels": None,
                },
            }
            client = _RecordingCloudClient(
                [{
                    "id": "abc123def456",
                    "title": "New title",
                    "tags": {"team": "platform"},
                }]
            )

            # NOTE: deliberately NOT patching _get_conversation_store — the
            # whole point of this test is to drive the real store against a
            # real connection.
            result = manager.update_metadata(client=client)

        # The refresh must report no errors (regression: the bug produced
        # ``errors == 1`` with an AttributeError message).
        assert result.errors == [], f"expected no errors, got: {result.errors}"
        assert len(result.errors) == 0
        assert result.title_changed == 1
        assert result.labels_changed == 1
        assert result.both_changed == 1

        # And the DB row must actually reflect the cloud metadata.
        check_conn = sqlite3.connect(db_path)
        check_conn.row_factory = sqlite3.Row
        row = check_conn.execute(
            "SELECT title, labels FROM conversations WHERE id = ?",
            ("abc123def456",),
        ).fetchone()
        check_conn.close()

        assert row is not None, "seeded conversation row vanished"
        assert row["title"] == "New title"
        # labels are stored as a JSON string in the DB
        assert json.loads(row["labels"]) == {"team": "platform"}

    def test_real_db_dry_run_does_not_touch_row(self, tmp_path):
        """Dry-run must NOT write to the DB even with real store wiring."""
        import sqlite3

        from ohtv.db import migrate
        from ohtv.db.models import Conversation
        from ohtv.db.stores import ConversationStore

        db_path = tmp_path / "index.db"
        seed_conn = sqlite3.connect(db_path)
        seed_conn.row_factory = sqlite3.Row
        seed_conn.execute("PRAGMA foreign_keys = ON")
        migrate(seed_conn)
        ConversationStore(seed_conn).upsert(
            Conversation(
                id="abc123def456",
                location=str(tmp_path / "synced" / "abc123def456"),
                event_count=5,
                title="Old title",
                labels=None,
                source="cloud",
            )
        )
        seed_conn.commit()
        seed_conn.close()

        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        config.synced_conversations_dir = tmp_path / "synced"

        with (
            patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"),
            patch("ohtv.db.get_db_path", return_value=db_path),
        ):
            manager = SyncManager(config)
            manager.manifest.conversations = {
                "abc123def456": {
                    "title": "Old title",
                    "updated_at": "u",
                    "event_count": 5,
                    "downloaded_at": "d",
                    "labels": None,
                },
            }
            client = _RecordingCloudClient(
                [{"id": "abc123def456", "title": "New title", "tags": None}]
            )
            result = manager.update_metadata(dry_run=True, client=client)

        assert result.errors == []
        assert result.title_changed == 1

        # DB row untouched
        check_conn = sqlite3.connect(db_path)
        check_conn.row_factory = sqlite3.Row
        row = check_conn.execute(
            "SELECT title FROM conversations WHERE id = ?",
            ("abc123def456",),
        ).fetchone()
        check_conn.close()
        assert row["title"] == "Old title"


# =====================================================================
# Issue #87: manifest as full cloud metadata cache
# =====================================================================


class TestReadSelectedBranch:
    """Tests for the _read_selected_branch helper."""

    def test_returns_branch_from_base_state(self, tmp_path):
        (tmp_path / "base_state.json").write_text(json.dumps({
            "selected_branch": "feat/foo",
        }))
        assert _read_selected_branch(tmp_path) == "feat/foo"

    def test_returns_none_when_field_missing(self, tmp_path):
        (tmp_path / "base_state.json").write_text(json.dumps({"title": "x"}))
        assert _read_selected_branch(tmp_path) is None

    def test_returns_none_when_base_state_missing(self, tmp_path):
        # No base_state.json at all
        assert _read_selected_branch(tmp_path) is None

    def test_returns_none_when_base_state_corrupt(self, tmp_path):
        (tmp_path / "base_state.json").write_text("not JSON {{")
        assert _read_selected_branch(tmp_path) is None

    def test_returns_none_for_empty_string_branch(self, tmp_path):
        (tmp_path / "base_state.json").write_text(json.dumps({
            "selected_branch": "",
        }))
        assert _read_selected_branch(tmp_path) is None

    def test_returns_none_for_non_string_branch(self, tmp_path):
        """A bizarre type sneaks in -> we don't crash, we return None."""
        (tmp_path / "base_state.json").write_text(json.dumps({
            "selected_branch": 42,
        }))
        assert _read_selected_branch(tmp_path) is None


class TestUpdateManifestEntryIssue87:
    """Tests for SyncManager._update_manifest_entry's #87 extensions.

    The manifest entry must persist ``selected_repository`` (from the
    listing payload), ``selected_branch`` (from the freshly-exported
    ``base_state.json``), and ``created_at`` (from the listing payload).
    """

    @pytest.fixture
    def manager(self, tmp_path):
        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        config.synced_conversations_dir = tmp_path / "synced"
        config.synced_conversations_dir.mkdir(parents=True)
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def _make_conv_dir(self, root: Path, conv_id: str, branch: str | None) -> Path:
        conv_dir = root / conv_id
        (conv_dir / "events").mkdir(parents=True)
        if branch is not None:
            (conv_dir / "base_state.json").write_text(json.dumps({
                "selected_branch": branch,
            }))
        return conv_dir

    def test_writes_all_three_new_fields(self, manager):
        conv_dir = self._make_conv_dir(
            manager.config.synced_conversations_dir, "convA", "feat/foo"
        )
        manager._update_manifest_entry(
            conv={
                "id": "convA",
                "title": "Title",
                "selected_repository": "org/repo",
                "created_at": "2024-06-01T12:00:00Z",
                "tags": None,
            },
            conv_id="convA",
            cloud_updated_at="2024-06-02T00:00:00Z",
            conv_dir=conv_dir,
        )
        entry = manager.manifest.conversations["convA"]
        assert entry["selected_repository"] == "org/repo"
        assert entry["selected_branch"] == "feat/foo"
        assert entry["created_at"] == "2024-06-01T12:00:00Z"
        # Legacy fields still present.
        assert entry["title"] == "Title"
        assert entry["updated_at"] == "2024-06-02T00:00:00Z"
        assert "downloaded_at" in entry
        assert "event_count" in entry

    def test_handles_missing_base_state_branch_gracefully(self, manager):
        """No base_state.json on disk → selected_branch stored as None."""
        conv_dir = self._make_conv_dir(
            manager.config.synced_conversations_dir, "convB", branch=None
        )
        manager._update_manifest_entry(
            conv={"id": "convB", "title": "X", "selected_repository": "x/y"},
            conv_id="convB",
            cloud_updated_at="2024-06-02T00:00:00Z",
            conv_dir=conv_dir,
        )
        entry = manager.manifest.conversations["convB"]
        assert entry["selected_branch"] is None
        # Other #87 fields still populated from the listing payload.
        assert entry["selected_repository"] == "x/y"

    def test_handles_missing_listing_fields_as_none(self, manager):
        """Listing payload missing repo/created_at → manifest stores None."""
        conv_dir = self._make_conv_dir(
            manager.config.synced_conversations_dir, "convC", "main"
        )
        manager._update_manifest_entry(
            conv={"id": "convC"},  # No selected_repository, no created_at
            conv_id="convC",
            cloud_updated_at="2024-06-02T00:00:00Z",
            conv_dir=conv_dir,
        )
        entry = manager.manifest.conversations["convC"]
        assert entry["selected_repository"] is None
        assert entry["created_at"] is None
        # selected_branch still extracted from base_state.json.
        assert entry["selected_branch"] == "main"


class TestMetadataDiffersIssue87:
    """Tests for the Issue #87 extension of _metadata_differs.

    The four-field comparison: title, labels, selected_repository,
    created_at. selected_branch is explicitly NOT compared (not in
    listing API).
    """

    def test_selected_repository_changed(self):
        cloud = {"selected_repository": "new/repo"}
        manifest = {"selected_repository": "old/repo"}
        diff = _metadata_differs(cloud, manifest)
        assert diff.selected_repository_changed is True
        assert diff.new_selected_repository == "new/repo"

    def test_selected_repository_unchanged(self):
        cloud = {"selected_repository": "same/repo"}
        manifest = {"selected_repository": "same/repo"}
        diff = _metadata_differs(cloud, manifest)
        assert diff.selected_repository_changed is False

    def test_selected_repository_set_from_pre_87_manifest(self):
        """Pre-#87 manifest has no key — cloud value counts as a change."""
        cloud = {"selected_repository": "some/repo"}
        manifest = {}  # No key
        diff = _metadata_differs(cloud, manifest)
        assert diff.selected_repository_changed is True

    def test_created_at_changed(self):
        cloud = {"created_at": "2024-06-01T12:00:00Z"}
        manifest = {"created_at": "2024-01-01T00:00:00Z"}
        diff = _metadata_differs(cloud, manifest)
        assert diff.created_at_changed is True
        assert diff.new_created_at == "2024-06-01T12:00:00Z"

    def test_created_at_unchanged(self):
        cloud = {"created_at": "2024-01-01T00:00:00Z"}
        manifest = {"created_at": "2024-01-01T00:00:00Z"}
        diff = _metadata_differs(cloud, manifest)
        assert diff.created_at_changed is False

    def test_selected_branch_never_compared(self):
        """Diff struct intentionally has no selected_branch field."""
        diff = _metadata_differs({}, {"selected_branch": "main"})
        assert not hasattr(diff, "selected_branch_changed")

    def test_any_changed_true_when_only_repo_differs(self):
        cloud = {"selected_repository": "new/repo"}
        manifest = {"selected_repository": "old/repo"}
        diff = _metadata_differs(cloud, manifest)
        assert diff.any_changed is True

    def test_all_four_changed(self):
        cloud = {
            "title": "New",
            "tags": {"k": "v"},
            "selected_repository": "new/repo",
            "created_at": "2024-06-01T12:00:00Z",
        }
        manifest = {
            "title": "Old",
            "labels": None,
            "selected_repository": "old/repo",
            "created_at": "2024-01-01T00:00:00Z",
        }
        diff = _metadata_differs(cloud, manifest)
        assert diff.title_changed
        assert diff.labels_changed
        assert diff.selected_repository_changed
        assert diff.created_at_changed
        assert diff.any_changed


class TestUpdateMetadataIssue87:
    """Tests for SyncManager.update_metadata's #87 extensions."""

    @pytest.fixture
    def manager(self, tmp_path):
        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        config.synced_conversations_dir = tmp_path / "synced"
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_selected_repository_change_written_to_manifest(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "2024-01-01T00:00:00Z",
                "event_count": 5,
                "downloaded_at": "2024-01-02T00:00:00Z",
                "labels": None,
                "selected_repository": "old/repo",
                "selected_branch": "main",
                "created_at": "2024-01-01T00:00:00Z",
            },
        }
        client = _RecordingCloudClient(
            [{
                "id": "abc",
                "title": "Same",
                "tags": None,
                "selected_repository": "new/repo",
                "created_at": "2024-01-01T00:00:00Z",
            }]
        )

        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert client.download_calls == []
        assert result.selected_repository_changed == 1
        assert result.title_changed == 0
        assert result.created_at_changed == 0
        assert manager.manifest.conversations["abc"]["selected_repository"] == "new/repo"
        # selected_branch preserved byte-for-byte (not refreshable here)
        assert manager.manifest.conversations["abc"]["selected_branch"] == "main"

    def test_created_at_change_written_to_manifest(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "u",
                "event_count": 5,
                "downloaded_at": "d",
                "labels": None,
                "selected_repository": "x/y",
                "selected_branch": "main",
                "created_at": "2024-01-01T00:00:00Z",
            },
        }
        client = _RecordingCloudClient(
            [{
                "id": "abc",
                "title": "Same",
                "tags": None,
                "selected_repository": "x/y",
                "created_at": "2024-06-01T12:00:00Z",
            }]
        )

        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert result.created_at_changed == 1
        assert manager.manifest.conversations["abc"]["created_at"] == "2024-06-01T12:00:00Z"

    def test_does_not_refresh_selected_branch(self, manager):
        """Manifest's selected_branch survives metadata refresh."""
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "u",
                "event_count": 5,
                "downloaded_at": "d",
                "labels": None,
                "selected_repository": "x/y",
                "selected_branch": "feat/preserved",
                "created_at": "2024-01-01T00:00:00Z",
            },
        }
        # Cloud listing would never include selected_branch, but defensively
        # add one to confirm it's still ignored.
        client = _RecordingCloudClient(
            [{
                "id": "abc",
                "title": "Same",
                "tags": None,
                "selected_repository": "x/y",
                "selected_branch": "DIFFERENT-branch-from-listing",
                "created_at": "2024-01-01T00:00:00Z",
            }]
        )
        with patch.object(manager, "_get_conversation_store", return_value=None):
            manager.update_metadata(client=client)
        assert manager.manifest.conversations["abc"]["selected_branch"] == "feat/preserved"

    def test_convs_changed_counts_distinct_convs(self, manager):
        """A conv with title + repo both changed counts as 1 conv changed."""
        manager.manifest.conversations = {
            "abc": {
                "title": "Old",
                "updated_at": "u",
                "event_count": 1,
                "downloaded_at": "d",
                "labels": None,
                "selected_repository": "old/repo",
                "selected_branch": "main",
                "created_at": "2024-01-01T00:00:00Z",
            },
        }
        client = _RecordingCloudClient(
            [{
                "id": "abc",
                "title": "New",
                "tags": None,
                "selected_repository": "new/repo",
                "created_at": "2024-01-01T00:00:00Z",
            }]
        )
        with patch.object(manager, "_get_conversation_store", return_value=None):
            result = manager.update_metadata(client=client)

        assert result.title_changed == 1
        assert result.selected_repository_changed == 1
        assert result.convs_changed == 1
        assert result.total_changed == 1  # post-#87 uses convs_changed

    def test_db_update_called_with_new_fields(self, manager):
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "u",
                "event_count": 1,
                "downloaded_at": "d",
                "labels": None,
                "selected_repository": "old/repo",
                "selected_branch": "main",
                "created_at": "2024-01-01T00:00:00Z",
            },
        }
        store = MagicMock()
        store.conn = MagicMock()
        with patch.object(manager, "_get_conversation_store", return_value=store):
            client = _RecordingCloudClient(
                [{
                    "id": "abc",
                    "title": "Same",
                    "tags": None,
                    "selected_repository": "new/repo",
                    "created_at": "2024-06-01T12:00:00Z",
                }]
            )
            manager.update_metadata(client=client)

        # Both #87 fields propagated to the DB write.
        call_args = store.update_metadata.call_args
        assert call_args.kwargs.get("selected_repository") == "new/repo"
        # created_at must be a datetime in the DB call.
        assert isinstance(call_args.kwargs.get("created_at"), datetime)

    def test_db_update_only_includes_changed_fields(self, manager):
        """If only repo changed, title/labels/created_at must not be in the call."""
        manager.manifest.conversations = {
            "abc": {
                "title": "Same",
                "updated_at": "u",
                "event_count": 1,
                "downloaded_at": "d",
                "labels": None,
                "selected_repository": "old/repo",
                "selected_branch": "main",
                "created_at": "2024-01-01T00:00:00Z",
            },
        }
        store = MagicMock()
        store.conn = MagicMock()
        with patch.object(manager, "_get_conversation_store", return_value=store):
            client = _RecordingCloudClient(
                [{
                    "id": "abc",
                    "title": "Same",
                    "tags": None,
                    "selected_repository": "new/repo",
                    "created_at": "2024-01-01T00:00:00Z",
                }]
            )
            manager.update_metadata(client=client)

        call_args = store.update_metadata.call_args
        # Only the diff'd field should be in kwargs.
        assert "selected_repository" in call_args.kwargs
        assert "title" not in call_args.kwargs
        assert "labels" not in call_args.kwargs
        assert "created_at" not in call_args.kwargs


class TestRepairFromListingPayloadIssue87:
    """Tests for SyncManager.repair's #87 cloud-listing rebuild path.

    When fix=True picks up orphaned on-disk conversations, repair queries
    the listing API once and rebuilds manifest entries with full #87
    metadata (selected_repository, selected_branch, created_at).
    """

    @pytest.fixture
    def manager(self, tmp_path):
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.synced_conversations_dir.mkdir(parents=True)
        config.local_conversations_dir = tmp_path / "local"
        config.extra_conversation_paths = []
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_rebuilds_orphan_with_full_cloud_metadata(self, manager):
        # Build an orphaned on-disk conversation
        conv_dir = manager.config.synced_conversations_dir / "convX"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (conv_dir / "base_state.json").write_text(json.dumps({
            "selected_branch": "feat/orphan",
        }))

        # Cloud listing has the conv with all the listing-API fields
        listing_entry = {
            "id": "convX",
            "title": "Recovered title",
            "tags": {"qa": "smoke"},
            "selected_repository": "org/recovered",
            "created_at": "2024-06-01T12:00:00Z",
            "updated_at": "2024-06-02T00:00:00Z",
        }

        with patch.object(
            manager,
            "_fetch_cloud_listing_for_repair",
            return_value={"convX": listing_entry},
        ):
            result = manager.repair(fix=True, check_cloud=True)

        assert result.added_to_manifest == 1
        entry = manager.manifest.conversations["convX"]
        # Listing-derived fields
        assert entry["title"] == "Recovered title"
        assert entry["labels"] == {"qa": "smoke"}
        assert entry["selected_repository"] == "org/recovered"
        assert entry["created_at"] == "2024-06-01T12:00:00Z"
        assert entry["updated_at"] == "2024-06-02T00:00:00Z"
        # selected_branch from base_state.json on disk
        assert entry["selected_branch"] == "feat/orphan"

    def test_rebuilds_orphan_fallback_when_listing_empty(self, manager):
        """No cloud listing match -> nulls except event_count and selected_branch."""
        conv_dir = manager.config.synced_conversations_dir / "convY"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        (conv_dir / "base_state.json").write_text(json.dumps({
            "selected_branch": "fallback-branch",
        }))

        with patch.object(manager, "_fetch_cloud_listing_for_repair", return_value={}):
            result = manager.repair(fix=True, check_cloud=True)

        assert result.added_to_manifest == 1
        entry = manager.manifest.conversations["convY"]
        assert entry["title"] is None
        assert entry["updated_at"] is None
        assert entry["selected_repository"] is None
        assert entry["created_at"] is None
        assert entry["selected_branch"] == "fallback-branch"

    def test_repair_does_not_fetch_when_no_api_key(self, manager):
        """No API key -> repair falls back to null-filled entries."""
        manager.config.api_key = None
        conv_dir = manager.config.synced_conversations_dir / "convZ"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)

        with patch.object(manager, "_fetch_cloud_listing_for_repair") as fetch_mock:
            result = manager.repair(fix=True, check_cloud=True)
            fetch_mock.assert_not_called()

        assert result.added_to_manifest == 1
        entry = manager.manifest.conversations["convZ"]
        assert entry["title"] is None
        assert entry["selected_repository"] is None

    def test_repair_does_not_fetch_when_no_orphans(self, manager):
        """Empty orphan list -> no listing fetch (perf)."""
        with patch.object(manager, "_fetch_cloud_listing_for_repair") as fetch_mock:
            manager.repair(fix=True, check_cloud=True)
            fetch_mock.assert_not_called()


class TestMetadataDiffDataclass:
    """Tests for the MetadataDiff dataclass struct itself."""

    def test_default_no_changes(self):
        diff = MetadataDiff()
        assert diff.any_changed is False
        assert diff.title_changed is False
        assert diff.selected_repository_changed is False
        assert diff.created_at_changed is False

    def test_any_changed_true_when_one_field_changed(self):
        for kwarg in [
            "title_changed",
            "labels_changed",
            "selected_repository_changed",
            "created_at_changed",
        ]:
            diff = MetadataDiff(**{kwarg: True})
            assert diff.any_changed is True, f"any_changed False for {kwarg}"



class TestResetToNNewest:
    """Tests for SyncManager.reset_to_n_newest() client-side sort (Issue #107).

    The cloud /search endpoint returns items in created_at DESC order and has no
    `sort` parameter, so reset_to_n_newest must sort by updated_at DESC
    client-side to honor its documented "N most recently updated" semantic.
    """

    @pytest.fixture
    def manager(self, tmp_path):
        """SyncManager with a tmp manifest and mocked config."""
        config = MagicMock()
        config.api_key = "test-key"
        config.cloud_api_url = "https://example.com"
        config.synced_conversations_dir = tmp_path / "synced"
        with patch("ohtv.sync.get_manifest_path", return_value=tmp_path / "manifest.json"):
            return SyncManager(config)

    def test_returns_n_items_sorted_by_updated_at_desc(self, manager):
        """The N items kept must be those with the newest updated_at, even when
        that ordering disagrees with created_at (which is what the API returns)."""
        # Listing as the API would return it: created_at DESC.
        # Note: conv "B" has the oldest created_at but the newest updated_at —
        # the pre-#107 code would have dropped it; the fix must keep it.
        listing = [
            {"id": "A", "title": "A", "created_at": "2026-05-20T00:00:00Z", "updated_at": "2026-05-20T00:00:00Z"},
            {"id": "C", "title": "C", "created_at": "2026-05-15T00:00:00Z", "updated_at": "2026-05-22T00:00:00Z"},
            {"id": "D", "title": "D", "created_at": "2026-05-10T00:00:00Z", "updated_at": "2026-05-18T00:00:00Z"},
            {"id": "E", "title": "E", "created_at": "2026-05-05T00:00:00Z", "updated_at": "2026-05-12T00:00:00Z"},
            {"id": "B", "title": "B", "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-25T00:00:00Z"},
        ]
        client = _RecordingCloudClient(listing)

        progress: list[str] = []

        def on_progress(conv_id, title, status):
            progress.append(conv_id)

        with patch("ohtv.sync.CloudClient", return_value=client):
            result = manager.reset_to_n_newest(n=3, dry_run=True, on_progress=on_progress)

        # Newest-updated three are B (05-25), C (05-22), A (05-20). E and D drop.
        assert progress == ["B", "C", "A"]
        assert result.new == 3
        assert result.skipped_new == 2

    def test_missing_updated_at_sorts_last(self, manager):
        """Items with updated_at=None must sort to the END so that an unknown
        timestamp can never displace a known-recent conversation from the keep
        set — even when the item has a very recent created_at."""
        listing = [
            {"id": "A", "title": "A", "created_at": "2026-05-20T00:00:00Z", "updated_at": "2026-05-20T00:00:00Z"},
            # X has the newest created_at but updated_at=None. It must NOT
            # displace A or C, both of which have a known updated_at.
            {"id": "X", "title": "X", "created_at": "2026-05-25T00:00:00Z", "updated_at": None},
            {"id": "C", "title": "C", "created_at": "2026-05-15T00:00:00Z", "updated_at": "2026-05-22T00:00:00Z"},
        ]
        client = _RecordingCloudClient(listing)

        progress: list[str] = []

        def on_progress(conv_id, title, status):
            progress.append(conv_id)

        with patch("ohtv.sync.CloudClient", return_value=client):
            result = manager.reset_to_n_newest(n=2, dry_run=True, on_progress=on_progress)

        # C (updated 05-22) > A (updated 05-20) > X (created 05-25 fallback).
        # Two highest are C and A. X is dropped despite having the newest
        # created_at, because updated_at is the primary sort key.
        assert progress == ["C", "A"]
        assert result.new == 2
        assert result.skipped_new == 1

    def test_preserves_all_items_when_n_exceeds_total(self, manager):
        """When N >= total, every item is kept; skipped_new is 0."""
        listing = [
            {"id": "A", "title": "A", "created_at": "2026-05-20T00:00:00Z", "updated_at": "2026-05-20T00:00:00Z"},
            {"id": "B", "title": "B", "created_at": "2026-05-10T00:00:00Z", "updated_at": "2026-05-22T00:00:00Z"},
            {"id": "C", "title": "C", "created_at": "2026-05-15T00:00:00Z", "updated_at": "2026-05-18T00:00:00Z"},
        ]
        client = _RecordingCloudClient(listing)

        progress: list[str] = []

        def on_progress(conv_id, title, status):
            progress.append(conv_id)

        with patch("ohtv.sync.CloudClient", return_value=client):
            result = manager.reset_to_n_newest(n=10, dry_run=True, on_progress=on_progress)

        # All 3 kept, still sorted by updated_at DESC: B (05-22), A (05-20), C (05-18).
        assert progress == ["B", "A", "C"]
        assert result.new == 3
        assert result.skipped_new == 0

    def test_empty_cloud_is_noop(self, manager):
        """Empty cloud listing must produce a clean no-op SyncResult (no errors,
        no progress callbacks). Guards against TypeError or IndexError on []."""
        client = _RecordingCloudClient([])

        progress: list[tuple] = []

        def on_progress(conv_id, title, status):
            progress.append((conv_id, status))

        with patch("ohtv.sync.CloudClient", return_value=client):
            result = manager.reset_to_n_newest(n=5, dry_run=True, on_progress=on_progress)

        assert progress == []
        assert result.new == 0
        assert result.skipped_new == 0

