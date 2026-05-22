"""Unit tests for the sync module."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ohtv.sync import (
    MetadataRefreshResult,
    RepairResult,
    SyncManager,
    SyncManifest,
    SyncResult,
    _metadata_differs,
    _normalize_labels,
)


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


def _create_minimal_zip() -> bytes:
    """Create a minimal valid trajectory zip file."""
    import io
    import zipfile
    
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("meta.json", json.dumps({
            "id": "test123",
            "title": "Test",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }))
        zf.writestr("event_000001_abc.json", json.dumps({
            "id": "abc",
            "kind": "MessageEvent",
        }))
    return buffer.getvalue()


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
    """Tests for _metadata_differs() (cloud listing entry vs manifest entry)."""

    def test_neither_changed(self):
        cloud = {"title": "Same", "tags": {"k": "v"}}
        manifest = {"title": "Same", "labels": {"k": "v"}}
        assert _metadata_differs(cloud, manifest) == (False, False)

    def test_title_only(self):
        cloud = {"title": "New", "tags": {"k": "v"}}
        manifest = {"title": "Old", "labels": {"k": "v"}}
        assert _metadata_differs(cloud, manifest) == (True, False)

    def test_labels_only(self):
        cloud = {"title": "Same", "tags": {"k": "v2"}}
        manifest = {"title": "Same", "labels": {"k": "v"}}
        assert _metadata_differs(cloud, manifest) == (False, True)

    def test_both_changed(self):
        cloud = {"title": "New", "tags": {"k": "v2"}}
        manifest = {"title": "Old", "labels": {"k": "v"}}
        assert _metadata_differs(cloud, manifest) == (True, True)

    def test_empty_dict_labels_equals_none(self):
        """{} from API must compare equal to None from manifest (no churn)."""
        cloud = {"title": "Same", "tags": {}}
        manifest = {"title": "Same", "labels": None}
        assert _metadata_differs(cloud, manifest) == (False, False)

    def test_none_labels_equals_missing(self):
        cloud = {"title": "Same"}  # No tags key at all
        manifest = {"title": "Same", "labels": None}
        assert _metadata_differs(cloud, manifest) == (False, False)

    def test_reordered_dict_keys_equal(self):
        cloud = {"title": "Same", "tags": {"a": "1", "b": "2"}}
        manifest = {"title": "Same", "labels": {"b": "2", "a": "1"}}
        assert _metadata_differs(cloud, manifest) == (False, False)

    def test_empty_title_equals_missing(self):
        """Empty string title collapses to None for comparison."""
        cloud = {"title": "", "tags": None}
        manifest = {"title": None, "labels": None}
        assert _metadata_differs(cloud, manifest) == (False, False)

    def test_missing_manifest_title_treated_as_none(self):
        cloud = {"title": "X", "tags": None}
        manifest = {}  # No title, no labels
        assert _metadata_differs(cloud, manifest) == (True, False)


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


class _RecordingCloudClient:
    """Stub CloudClient that records every method call.

    Used by the update_metadata tests to assert that download_trajectory
    is NEVER called during a metadata refresh.
    """

    def __init__(self, listing: list[dict]):
        self._listing = listing
        self.search_calls: list = []
        self.download_calls: list = []

    def search_all_conversations(self, updated_since=None):
        self.search_calls.append(updated_since)
        return self._listing

    def download_trajectory(self, conversation_id: str) -> bytes:  # pragma: no cover
        # Recorded so tests can assert it is never invoked
        self.download_calls.append(conversation_id)
        return b""

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


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
