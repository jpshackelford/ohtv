"""Tests for the conversation scanner."""

import json
import time
from pathlib import Path

import pytest

from ohtv.db.scanner import (
    ScanResult,
    count_events,
    discover_conversations,
    get_events_mtime,
    scan_conversations,
)
from ohtv.db.stores import ConversationStore


@pytest.fixture
def conversations_dir(tmp_path):
    """Create a temporary conversations directory structure."""
    # Create local conversations dir
    local_dir = tmp_path / ".openhands" / "conversations"
    local_dir.mkdir(parents=True)
    
    # Create cloud conversations dir
    cloud_dir = tmp_path / ".openhands" / "cloud" / "conversations"
    cloud_dir.mkdir(parents=True)
    
    return tmp_path


def create_conversation(base_dir: Path, conv_id: str, num_events: int = 3) -> Path:
    """Helper to create a mock conversation directory with events."""
    conv_dir = base_dir / conv_id
    events_dir = conv_dir / "events"
    events_dir.mkdir(parents=True)
    
    # Create base_state.json
    (conv_dir / "base_state.json").write_text(json.dumps({
        "conversation_id": conv_id,
        "created_at": "2024-01-01T00:00:00Z"
    }))
    
    # Create event files
    for i in range(num_events):
        event_file = events_dir / f"event-{i:05d}-abc{i}.json"
        event_file.write_text(json.dumps({
            "kind": "MessageEvent",
            "content": f"Event {i}"
        }))
    
    return conv_dir


class TestCountEvents:
    """Tests for count_events function."""
    
    def test_counts_event_files(self, tmp_path):
        """Should count files starting with 'event-'."""
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "event-00001-abc.json").write_text("{}")
        (events_dir / "event-00002-def.json").write_text("{}")
        (events_dir / "event-00003-ghi.json").write_text("{}")
        
        assert count_events(events_dir) == 3
    
    def test_ignores_non_event_files(self, tmp_path):
        """Should ignore files not starting with 'event-'."""
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        (events_dir / "event-00001-abc.json").write_text("{}")
        (events_dir / "base_state.json").write_text("{}")
        (events_dir / "metadata.json").write_text("{}")
        
        assert count_events(events_dir) == 1
    
    def test_returns_zero_for_nonexistent_dir(self, tmp_path):
        """Should return 0 if directory doesn't exist."""
        assert count_events(tmp_path / "nonexistent") == 0


class TestGetEventsMtime:
    """Tests for get_events_mtime function."""
    
    def test_returns_mtime_for_existing_dir(self, tmp_path):
        """Should return mtime for existing directory."""
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        
        mtime = get_events_mtime(events_dir)
        
        assert mtime is not None
        assert isinstance(mtime, float)
    
    def test_returns_none_for_nonexistent_dir(self, tmp_path):
        """Should return None if directory doesn't exist."""
        assert get_events_mtime(tmp_path / "nonexistent") is None


class TestDiscoverConversations:
    """Tests for discover_conversations function."""
    
    def test_discovers_conversations_with_events_dir(self, tmp_path):
        """Should find directories containing an events subdirectory."""
        conv1 = tmp_path / "conv-1"
        (conv1 / "events").mkdir(parents=True)
        
        conv2 = tmp_path / "conv-2"
        (conv2 / "events").mkdir(parents=True)
        
        discovered = discover_conversations(tmp_path, "local")
        
        assert len(discovered) == 2
        ids = [d[0] for d in discovered]
        assert "conv-1" in ids
        assert "conv-2" in ids
        # Check source is included
        assert all(d[2] == "local" for d in discovered)
    
    def test_ignores_directories_without_events(self, tmp_path):
        """Should ignore directories without events subdirectory."""
        (tmp_path / "conv-1" / "events").mkdir(parents=True)
        (tmp_path / "not-a-conv").mkdir()  # No events dir
        
        discovered = discover_conversations(tmp_path, "cloud")
        
        assert len(discovered) == 1
        assert discovered[0][0] == "conv-1"
        assert discovered[0][2] == "cloud"
    
    def test_returns_empty_for_nonexistent_dir(self, tmp_path):
        """Should return empty list for nonexistent directory."""
        discovered = discover_conversations(tmp_path / "nonexistent", "local")
        assert discovered == []


class TestScanConversations:
    """Tests for scan_conversations function."""
    
    def test_registers_new_conversations(self, db_conn, conversations_dir, monkeypatch):
        """Should register new conversations found on disk."""
        # Set up conversations
        local_dir = conversations_dir / ".openhands" / "conversations"
        create_conversation(local_dir, "conv-new-1", num_events=5)
        create_conversation(local_dir, "conv-new-2", num_events=3)
        
        # Monkeypatch get_openhands_dir to use our temp dir
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        result = scan_conversations(db_conn)
        
        assert result.new_registered == 2
        assert result.total_on_disk == 2
        
        # Verify they're in the database
        store = ConversationStore(db_conn)
        conv1 = store.get("conv-new-1")
        assert conv1 is not None
        assert conv1.event_count == 5
        
        conv2 = store.get("conv-new-2")
        assert conv2 is not None
        assert conv2.event_count == 3
    
    def test_detects_unchanged_conversations(self, db_conn, conversations_dir, monkeypatch):
        """Should skip unchanged conversations on subsequent scans."""
        local_dir = conversations_dir / ".openhands" / "conversations"
        create_conversation(local_dir, "conv-1", num_events=3)
        
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        # First scan
        result1 = scan_conversations(db_conn)
        assert result1.new_registered == 1
        
        # Second scan without changes
        result2 = scan_conversations(db_conn)
        assert result2.new_registered == 0
        assert result2.unchanged == 1
    
    def test_detects_updated_conversations(self, db_conn, conversations_dir, monkeypatch):
        """Should detect conversations with new events."""
        local_dir = conversations_dir / ".openhands" / "conversations"
        conv_dir = create_conversation(local_dir, "conv-1", num_events=3)
        
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        # First scan
        result1 = scan_conversations(db_conn)
        assert result1.new_registered == 1
        
        # Add more events and touch the directory
        time.sleep(0.01)  # Ensure mtime changes
        events_dir = conv_dir / "events"
        (events_dir / "event-00003-new.json").write_text("{}")
        
        # Second scan
        result2 = scan_conversations(db_conn)
        assert result2.updated == 1
        
        # Verify event count updated
        store = ConversationStore(db_conn)
        conv = store.get("conv-1")
        assert conv.event_count == 4
    
    def test_force_updates_all(self, db_conn, conversations_dir, monkeypatch):
        """Should update all conversations when force=True."""
        local_dir = conversations_dir / ".openhands" / "conversations"
        create_conversation(local_dir, "conv-1", num_events=3)
        
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        # First scan
        scan_conversations(db_conn)
        
        # Force scan (no changes but should still update)
        result = scan_conversations(db_conn, force=True)
        assert result.updated == 1
        assert result.unchanged == 0
    
    def test_removes_missing_when_requested(self, db_conn, conversations_dir, monkeypatch):
        """Should remove DB entries for missing conversations when remove_missing=True."""
        local_dir = conversations_dir / ".openhands" / "conversations"
        conv_dir = create_conversation(local_dir, "conv-1", num_events=3)
        
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        # First scan
        scan_conversations(db_conn)
        
        # Delete the conversation from disk
        import shutil
        shutil.rmtree(conv_dir)
        
        # Scan with remove_missing
        result = scan_conversations(db_conn, remove_missing=True)
        assert result.removed == 1
        
        # Verify it's gone from DB
        store = ConversationStore(db_conn)
        assert store.get("conv-1") is None
    
    def test_scans_both_local_and_cloud(self, db_conn, conversations_dir, monkeypatch):
        """Should discover conversations from both local and cloud directories."""
        local_dir = conversations_dir / ".openhands" / "conversations"
        cloud_dir = conversations_dir / ".openhands" / "cloud" / "conversations"
        
        create_conversation(local_dir, "local-conv", num_events=2)
        create_conversation(cloud_dir, "cloud-conv", num_events=4)
        
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        result = scan_conversations(db_conn)
        
        assert result.new_registered == 2
        assert result.total_on_disk == 2
        
        store = ConversationStore(db_conn)
        assert store.get("local-conv") is not None
        assert store.get("cloud-conv") is not None
    
    def test_calls_progress_callback(self, db_conn, conversations_dir, monkeypatch):
        """Should call progress callback for each conversation."""
        local_dir = conversations_dir / ".openhands" / "conversations"
        create_conversation(local_dir, "conv-1", num_events=2)
        create_conversation(local_dir, "conv-2", num_events=3)
        create_conversation(local_dir, "conv-3", num_events=1)
        
        monkeypatch.setattr("ohtv.db.scanner.get_openhands_dir", lambda: conversations_dir / ".openhands")
        
        # Track callback calls
        progress_calls = []
        def on_progress(current, total, conv_id):
            progress_calls.append((current, total, conv_id))
        
        scan_conversations(db_conn, on_progress=on_progress)
        
        # Should have calls for each conversation plus final completion
        assert len(progress_calls) == 4  # 3 conversations + 1 completion
        
        # First call should be index 0
        assert progress_calls[0][0] == 0
        assert progress_calls[0][1] == 3  # total
        
        # Last call should signal completion
        assert progress_calls[-1][0] == 3  # current == total
        assert progress_calls[-1][1] == 3
        assert progress_calls[-1][2] == ""  # empty conv_id on completion
