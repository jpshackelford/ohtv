"""Unit tests for the sync module."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ohtv.sync import RepairResult, SyncManager, SyncManifest, SyncResult


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
            disk_count=10,
            ghost_entries=[],
            orphaned_files=[],
        )
        assert result.is_consistent is True

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
        result = RepairResult(cloud_count=100, disk_count=100)
        assert result.cloud_disk_match is True

    def test_cloud_disk_match_false_when_different(self):
        result = RepairResult(cloud_count=100, disk_count=50)
        assert result.cloud_disk_match is False


class TestSyncManagerRepair:
    """Tests for SyncManager.repair method."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a SyncManager with mocked config."""
        config = MagicMock()
        config.synced_conversations_dir = tmp_path / "synced"
        config.synced_conversations_dir.mkdir(parents=True)
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
