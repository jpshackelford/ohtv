"""Tests for JIT (just-in-time) conversation fetcher."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from ohtv.config import Config
from ohtv.jit import JITFetchResult, JITFetcher


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock Config with temporary paths."""
    config = Mock(spec=Config)
    config.synced_conversations_dir = tmp_path / "cloud"
    config.synced_conversations_dir.mkdir(parents=True, exist_ok=True)
    config.api_key = "test-api-key"
    config.cloud_api_url = "https://test.api"
    return config


@pytest.fixture
def mock_cloud_client():
    """Create a mock CloudClient."""
    client = Mock()
    return client


@pytest.fixture
def jit_fetcher(mock_config, mock_cloud_client):
    """Create a JITFetcher with mocked dependencies."""
    return JITFetcher(mock_config, mock_cloud_client)


def test_fetch_result_properties():
    """Test JITFetchResult computed properties."""
    result = JITFetchResult(
        requested_ids=["id1", "id2", "id3"],
        already_cached=["id1"],
        fetched=["id2"],
        failed=["id3"],
    )
    
    assert result.up_to_date == ["id1"]
    assert result.total_available == 2  # cached + fetched


def test_query_cloud_for_ids_since_only(jit_fetcher, mock_cloud_client):
    """Test querying cloud for IDs with since filter."""
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    mock_cloud_client.search_all_conversations.return_value = [
        {"id": "conv1", "updated_at": "2024-01-02T00:00:00Z"},
        {"id": "conv2", "updated_at": "2024-01-03T00:00:00Z"},
    ]
    
    ids = jit_fetcher._query_cloud_for_ids(since, None)
    
    assert ids == ["conv1", "conv2"]
    mock_cloud_client.search_all_conversations.assert_called_once_with(
        updated_since=since,
        include_sub_conversations=True,
    )


def test_query_cloud_for_ids_with_until_filter(jit_fetcher, mock_cloud_client):
    """Test client-side until filtering."""
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    until = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    
    mock_cloud_client.search_all_conversations.return_value = [
        {"id": "conv1", "updated_at": "2024-01-02T00:00:00Z"},  # Include
        {"id": "conv2", "updated_at": "2024-01-03T00:00:00Z"},  # Exclude (after until)
    ]
    
    ids = jit_fetcher._query_cloud_for_ids(since, until)
    
    assert ids == ["conv1"]


def test_parse_updated_at_iso_format(jit_fetcher):
    """Test parsing ISO format timestamp."""
    conv = {"updated_at": "2024-01-02T12:30:45Z"}
    dt = jit_fetcher._parse_updated_at(conv)
    
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 2
    assert dt.hour == 12
    assert dt.tzinfo is not None


def test_parse_updated_at_fallback_to_created_at(jit_fetcher):
    """Test fallback to created_at when updated_at missing."""
    conv = {"created_at": "2024-01-01T10:00:00Z"}
    dt = jit_fetcher._parse_updated_at(conv)
    
    assert dt.day == 1


def test_parse_updated_at_missing_both(jit_fetcher):
    """Test fallback to current time when both timestamps missing."""
    conv = {}
    dt = jit_fetcher._parse_updated_at(conv)
    
    # Should be recent (within last minute)
    now = datetime.now(timezone.utc)
    assert (now - dt).total_seconds() < 60


def test_is_historical_old_conversation(jit_fetcher):
    """Test historical detection for old conversations."""
    old_date = datetime.now(timezone.utc) - timedelta(hours=48)
    assert jit_fetcher._is_historical(old_date) is True


def test_is_historical_recent_conversation(jit_fetcher):
    """Test historical detection for recent conversations."""
    recent_date = datetime.now(timezone.utc) - timedelta(hours=12)
    assert jit_fetcher._is_historical(recent_date) is False


def test_is_historical_none(jit_fetcher):
    """Test historical detection with None timestamp."""
    assert jit_fetcher._is_historical(None) is False


def test_get_cache_age_hours(jit_fetcher):
    """Test cache age calculation."""
    conv = Mock()
    conv.cloud_updated_at = datetime.now(timezone.utc) - timedelta(hours=5)
    
    age = jit_fetcher._get_cache_age_hours(conv)
    
    assert age is not None
    assert 4.9 < age < 5.1  # Allow small variation


def test_get_cache_age_hours_missing(jit_fetcher):
    """Test cache age when cloud_updated_at is missing."""
    conv = Mock()
    conv.cloud_updated_at = None
    
    age = jit_fetcher._get_cache_age_hours(conv)
    
    assert age is None


@patch("ohtv.jit.get_ready_connection")
def test_check_cache_status_missing_conversation(mock_conn, jit_fetcher):
    """Test cache status when conversation is not in DB."""
    mock_store = Mock()
    mock_store.get.return_value = None
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn.return_value = mock_conn_instance
    
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        status = jit_fetcher._check_cache_status(["conv1"], max_age_hours=24, force_refresh=False)
    
    assert status["missing"] == ["conv1"]
    assert status["fresh"] == []
    assert status["stale"] == []


@patch("ohtv.jit.get_ready_connection")
def test_check_cache_status_fresh_historical(mock_conn, jit_fetcher):
    """Test cache status for fresh historical conversation."""
    mock_conv = Mock()
    mock_conv.created_at = datetime.now(timezone.utc) - timedelta(days=7)
    mock_conv.cloud_updated_at = datetime.now(timezone.utc) - timedelta(days=1)
    
    mock_store = Mock()
    mock_store.get.return_value = mock_conv
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn.return_value = mock_conn_instance
    
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        status = jit_fetcher._check_cache_status(["conv1"], max_age_hours=24, force_refresh=False)
    
    assert status["fresh"] == ["conv1"]
    assert status["stale"] == []
    assert status["missing"] == []


@patch("ohtv.jit.get_ready_connection")
def test_check_cache_status_stale_recent(mock_conn, jit_fetcher):
    """Test cache status for stale recent conversation."""
    mock_conv = Mock()
    mock_conv.created_at = datetime.now(timezone.utc) - timedelta(hours=6)
    mock_conv.cloud_updated_at = datetime.now(timezone.utc) - timedelta(hours=30)
    
    mock_store = Mock()
    mock_store.get.return_value = mock_conv
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn.return_value = mock_conn_instance
    
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        status = jit_fetcher._check_cache_status(["conv1"], max_age_hours=24, force_refresh=False)
    
    assert status["stale"] == ["conv1"]
    assert status["fresh"] == []


@patch("ohtv.jit.get_ready_connection")
def test_check_cache_status_force_refresh(mock_conn, jit_fetcher):
    """Test cache status with force_refresh flag."""
    status = jit_fetcher._check_cache_status(["conv1", "conv2"], max_age_hours=24, force_refresh=True)
    
    assert status["stale"] == ["conv1", "conv2"]
    assert status["fresh"] == []
    assert status["missing"] == []


@patch("ohtv.jit.get_ready_connection")
@patch("ohtv.jit.extract_metadata")
def test_index_conversation(mock_extract, mock_conn, jit_fetcher, tmp_path):
    """Test indexing a conversation to DB."""
    conv_id = "test-conv-123"
    conv_dir = tmp_path / "cloud" / conv_id
    conv_dir.mkdir(parents=True)
    
    # Create base_state.json
    base_state = {
        "id": conv_id,
        "title": "Test Conversation",
        "updated_at": "2024-01-01T00:00:00Z",
        "created_at": "2024-01-01T00:00:00Z",
    }
    (conv_dir / "base_state.json").write_text(json.dumps(base_state))
    
    # Mock DB connection and store
    mock_store = Mock()
    mock_conv = Mock()
    mock_conv.id = conv_id.replace("-", "")
    mock_store.get.return_value = mock_conv
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn_instance.commit = Mock()
    mock_conn.return_value = mock_conn_instance
    
    # Mock STAGES
    mock_refs_fn = Mock()
    mock_actions_fn = Mock()
    
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        with patch("ohtv.db.stages.STAGES", {"refs": mock_refs_fn, "actions": mock_actions_fn}):
            jit_fetcher._index_conversation(conv_id, conv_dir)
    
    # Verify store.record_cloud_download was called
    mock_store.record_cloud_download.assert_called_once()
    call_kwargs = mock_store.record_cloud_download.call_args.kwargs
    assert call_kwargs["conversation_id"] == conv_id
    assert call_kwargs["location"] == str(conv_dir)
    assert call_kwargs["cloud_updated_at"] == "2024-01-01T00:00:00Z"
    
    # Verify extract_metadata was called
    mock_extract.assert_called_once()
    
    # Verify stages were processed
    mock_refs_fn.assert_called_once_with(mock_conn_instance, mock_conv)
    mock_actions_fn.assert_called_once_with(mock_conn_instance, mock_conv)


@patch("ohtv.jit.get_ready_connection")
@patch("ohtv.jit.extract_metadata")
def test_index_conversation_missing_base_state(mock_extract, mock_conn, jit_fetcher, tmp_path):
    """Test indexing conversation with missing base_state.json."""
    conv_id = "test-conv-123"
    conv_dir = tmp_path / "cloud" / conv_id
    conv_dir.mkdir(parents=True)
    # No base_state.json created
    
    jit_fetcher._index_conversation(conv_id, conv_dir)
    
    # Should log warning and return early
    mock_extract.assert_not_called()


def test_index_conversation_integration(jit_fetcher, tmp_path):
    """Integration test: index conversation with real extract_metadata call.
    
    This test exercises the real extract_metadata function without mocking
    to ensure the function signature is correct and the integration works.
    """
    from ohtv.db import get_connection, migrate
    
    conv_id = "abc123def456"
    conv_dir = tmp_path / "cloud" / conv_id
    conv_dir.mkdir(parents=True)
    
    # Create a minimal but valid conversation directory structure
    base_state = {
        "id": conv_id,
        "title": "Integration Test Conversation",
        "updated_at": "2024-01-01T12:00:00Z",
        "created_at": "2024-01-01T10:00:00Z",
        "selected_repository": "owner/repo",
        "selected_branch": "main",
    }
    (conv_dir / "base_state.json").write_text(json.dumps(base_state))
    
    # Create events directory with a minimal event
    events_dir = conv_dir / "events"
    events_dir.mkdir()
    event = {
        "id": "1",
        "source": "user",
        "message": "Test message",
        "timestamp": "2024-01-01T10:00:00Z"
    }
    (events_dir / "1.json").write_text(json.dumps(event))
    
    # Create in-memory DB for testing
    db_path = tmp_path / "test.db"
    with get_connection(db_path) as conn:
        migrate(conn)
        
        # Patch get_ready_connection to use our test DB
        with patch("ohtv.jit.get_ready_connection") as mock_get_conn:
            mock_conn_ctx = Mock()
            mock_conn_ctx.__enter__ = Mock(return_value=conn)
            mock_conn_ctx.__exit__ = Mock(return_value=False)
            mock_get_conn.return_value = mock_conn_ctx
            
            # Mock STAGES to avoid running actual processing
            with patch("ohtv.db.stages.STAGES", {"refs": Mock(), "actions": Mock()}):
                # This should NOT raise ImportError or TypeError
                # If extract_metadata signature is wrong, this will fail
                jit_fetcher._index_conversation(conv_id, conv_dir)
        
        # Verify conversation was indexed in DB
        from ohtv.db.stores import ConversationStore
        store = ConversationStore(conn)
        conv = store.get(conv_id.replace("-", ""))
        
        assert conv is not None, "Conversation should be in DB after indexing"
        assert conv.title == "Integration Test Conversation"
        assert conv.selected_repository == "owner/repo"
        assert conv.source == "cloud"


def test_ensure_conversations_requires_ids_or_dates(jit_fetcher):
    """Test that ensure_conversations requires either conv_ids or date range."""
    with pytest.raises(ValueError, match="Must provide either conv_ids or date range"):
        jit_fetcher.ensure_conversations()


@patch("ohtv.jit.get_ready_connection")
def test_ensure_conversations_empty_result(mock_conn, jit_fetcher, mock_cloud_client):
    """Test ensure_conversations with no matching conversations."""
    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mock_cloud_client.search_all_conversations.return_value = []
    
    result = jit_fetcher.ensure_conversations(since=since)
    
    assert result.requested_ids == []
    assert result.already_cached == []
    assert result.fetched == []
    assert result.failed == []


@patch("ohtv.jit.get_ready_connection")
def test_ensure_conversations_with_explicit_ids(mock_conn, jit_fetcher):
    """Test ensure_conversations with explicit conversation IDs."""
    conv_ids = ["conv1", "conv2"]
    
    # Mock cache status check
    mock_store = Mock()
    mock_store.get.return_value = None  # All missing
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn.return_value = mock_conn_instance
    
    # Mock fetching
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        with patch.object(jit_fetcher, "_fetch_conversations", return_value=(conv_ids, [])):
            result = jit_fetcher.ensure_conversations(conv_ids=conv_ids)
    
    assert result.requested_ids == conv_ids
    assert result.fetched == conv_ids
    assert result.failed == []


@patch("ohtv.jit.get_ready_connection")
def test_ensure_conversations_all_cached(mock_conn, jit_fetcher):
    """Test ensure_conversations when all are already cached."""
    conv_ids = ["conv1", "conv2"]
    
    # Mock all conversations as fresh in cache
    mock_conv = Mock()
    mock_conv.created_at = datetime.now(timezone.utc) - timedelta(days=7)
    mock_conv.cloud_updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
    
    mock_store = Mock()
    mock_store.get.return_value = mock_conv
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn.return_value = mock_conn_instance
    
    on_progress = Mock()
    
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        result = jit_fetcher.ensure_conversations(
            conv_ids=conv_ids,
            on_progress=on_progress,
        )
    
    assert result.requested_ids == conv_ids
    assert result.already_cached == conv_ids
    assert result.fetched == []
    assert result.failed == []
    
    # Verify progress callback was called for cached conversations
    assert on_progress.call_count == 2
    on_progress.assert_any_call("conv1", "cached")
    on_progress.assert_any_call("conv2", "cached")


@patch("ohtv.jit.get_ready_connection")
@patch("ohtv.jit.extract_metadata")
def test_fetch_conversations_parallel(mock_extract, mock_conn, jit_fetcher, mock_cloud_client, tmp_path):
    """Test parallel downloading of multiple conversations."""
    conv_ids = ["conv1", "conv2", "conv3"]
    
    # Mock download_trajectory to return fake zip data
    def fake_download(conv_id):
        return b"fake-zip-data"
    
    mock_cloud_client.download_trajectory = fake_download
    
    # Mock exporter
    def fake_export(conv_id, zip_bytes):
        conv_dir = tmp_path / "cloud" / conv_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        base_state = {"id": conv_id, "updated_at": "2024-01-01T00:00:00Z"}
        (conv_dir / "base_state.json").write_text(json.dumps(base_state))
        return conv_dir
    
    jit_fetcher.exporter.export_from_zip_bytes = fake_export
    
    # Mock DB store
    mock_store = Mock()
    mock_conv = Mock()
    mock_conv.id = "test"
    mock_store.get.return_value = mock_conv
    
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn_instance.commit = Mock()
    mock_conn.return_value = mock_conn_instance
    
    # Mock STAGES
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        with patch("ohtv.db.stages.STAGES", {"refs": Mock(), "actions": Mock()}):
            fetched, failed = jit_fetcher._fetch_conversations(conv_ids)
    
    assert len(fetched) == 3
    assert len(failed) == 0
    assert set(fetched) == set(conv_ids)


@patch("ohtv.jit.get_ready_connection")
def test_fetch_conversations_with_failures(mock_conn, jit_fetcher, mock_cloud_client):
    """Test fetching with some failures."""
    conv_ids = ["conv1", "conv2"]
    
    # Mock download to fail for conv2
    def fake_download(conv_id):
        if conv_id == "conv2":
            raise Exception("Download failed")
        return b"fake-zip-data"
    
    mock_cloud_client.download_trajectory = fake_download
    
    # Mock other parts
    mock_store = Mock()
    mock_conn_instance = Mock()
    mock_conn_instance.__enter__ = Mock(return_value=mock_conn_instance)
    mock_conn_instance.__exit__ = Mock(return_value=False)
    mock_conn.return_value = mock_conn_instance
    
    with patch("ohtv.jit.ConversationStore", return_value=mock_store):
        with patch.object(jit_fetcher, "_index_conversation"):
            fetched, failed = jit_fetcher._fetch_conversations(conv_ids)
    
    assert len(failed) > 0
    assert "conv2" in failed


def test_ensure_conversations_progress_callback(jit_fetcher, mock_cloud_client):
    """Test progress callback is invoked correctly."""
    conv_ids = ["conv1"]
    on_progress = Mock()
    
    # Mock _fetch_conversations to call the callback
    def mock_fetch(ids, on_progress=None):
        if on_progress:
            for conv_id in ids:
                on_progress(conv_id, "downloading")
                on_progress(conv_id, "indexing")
        return (ids, [])
    
    with patch.object(jit_fetcher, "_query_cloud_for_ids", return_value=conv_ids):
        with patch.object(jit_fetcher, "_check_cache_status", return_value={"fresh": [], "stale": [], "missing": conv_ids}):
            with patch.object(jit_fetcher, "_fetch_conversations", side_effect=mock_fetch):
                jit_fetcher.ensure_conversations(
                    since=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    on_progress=on_progress,
                )
    
    # Progress callback should be called during fetch
    assert on_progress.called
    assert on_progress.call_count == 2  # downloading + indexing


def test_ensure_conversations_force_refresh(jit_fetcher):
    """Test force_refresh marks all as stale."""
    conv_ids = ["conv1", "conv2"]
    
    with patch.object(jit_fetcher, "_check_cache_status") as mock_check:
        mock_check.return_value = {"fresh": [], "stale": conv_ids, "missing": []}
        
        with patch.object(jit_fetcher, "_fetch_conversations", return_value=(conv_ids, [])):
            result = jit_fetcher.ensure_conversations(
                conv_ids=conv_ids,
                force_refresh=True,
            )
        
        # All should be fetched due to force_refresh
        assert result.fetched == conv_ids
        assert result.already_cached == []
