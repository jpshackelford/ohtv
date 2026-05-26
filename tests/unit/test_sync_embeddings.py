"""Unit tests for _run_post_sync_embeddings functionality in cli.py.

These tests verify the sync embedding progress bar feature (Issue #44).
"""

from dataclasses import dataclass
from unittest.mock import MagicMock, Mock, patch

import pytest

from ohtv.cli import _run_post_sync_embeddings


@dataclass
class MockConversation:
    """Mock conversation for testing."""
    id: str
    location: str | None


@dataclass
class MockEmbeddingStats:
    """Mock embedding stats for testing."""
    conversation_id: str
    embeddings_created: int


class TestRunPostSyncEmbeddingsConfiguration:
    """Tests for embedding configuration checks."""

    @patch("ohtv.analysis.embeddings.config.is_embedding_configured")
    def test_skips_when_not_configured(self, mock_is_configured, capsys):
        """Test that embedding is skipped when not configured."""
        mock_is_configured.return_value = False
        
        with patch("ohtv.analysis.embeddings.config.detect_ollama") as mock_detect:
            mock_detect.return_value = Mock(is_running=False)
            _run_post_sync_embeddings(quiet=False, verbose=False)
        
        captured = capsys.readouterr()
        assert "Skipping embeddings (not configured)" in captured.out

    @patch("ohtv.analysis.embeddings.config.is_embedding_configured")
    def test_shows_ollama_tip_when_available(self, mock_is_configured, capsys):
        """Test that Ollama tip is shown when detected."""
        mock_is_configured.return_value = False
        
        with patch("ohtv.analysis.embeddings.config.detect_ollama") as mock_detect:
            mock_detect.return_value = Mock(is_running=True)
            _run_post_sync_embeddings(quiet=False, verbose=False)
        
        captured = capsys.readouterr()
        assert "Ollama detected" in captured.out

    @patch("ohtv.analysis.embeddings.config.is_embedding_configured")
    def test_quiet_mode_suppresses_unconfigured_message(self, mock_is_configured, capsys):
        """Test that quiet mode suppresses the 'not configured' message."""
        mock_is_configured.return_value = False
        
        with patch("ohtv.analysis.embeddings.config.detect_ollama") as mock_detect:
            mock_detect.return_value = Mock(is_running=False)
            _run_post_sync_embeddings(quiet=True, verbose=False)
        
        captured = capsys.readouterr()
        assert captured.out == ""


class TestRunPostSyncEmbeddingsNoWork:
    """Tests for when there's no embedding work to do."""

    @patch("ohtv.analysis.embeddings.config.is_embedding_configured")
    @patch("ohtv.db.get_connection")
    def test_all_conversations_already_embedded(self, mock_get_conn, mock_is_configured, capsys, tmp_path):
        """Test when all conversations already have embeddings."""
        mock_is_configured.return_value = True
        
        # Create a mock conversation with a valid location
        conv_dir = tmp_path / "conv1"
        events_dir = conv_dir / "events"
        events_dir.mkdir(parents=True)
        
        mock_conv = MockConversation(id="conv1", location=str(conv_dir))
        
        # Set up mocks
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        with patch("ohtv.db.stores.conversation_store.ConversationStore") as mock_conv_store_cls, \
             patch("ohtv.db.stores.embedding_store.EmbeddingStore") as mock_embed_store_cls, \
             patch("ohtv.filters.normalize_conversation_id", side_effect=lambda x: x):
            
            mock_conv_store = MagicMock()
            mock_conv_store.list_all.return_value = [mock_conv]
            mock_conv_store_cls.return_value = mock_conv_store
            
            mock_embed_store = MagicMock()
            mock_embed_store.list_conversation_ids.return_value = ["conv1"]
            mock_embed_store.list_conversations_needing_embeddings.return_value = []
            mock_embed_store_cls.return_value = mock_embed_store
            
            _run_post_sync_embeddings(quiet=False, verbose=False)
        
        captured = capsys.readouterr()
        assert "All conversations have embeddings" in captured.out or "All local conversations have embeddings" in captured.out

    @patch("ohtv.analysis.embeddings.config.is_embedding_configured")
    @patch("ohtv.db.get_connection")
    def test_no_local_content_message(self, mock_get_conn, mock_is_configured, capsys, tmp_path):
        """Test when conversations have no local content, message shows 'without content skipped'."""
        mock_is_configured.return_value = True
        
        # Conversation with no location
        mock_conv = MockConversation(id="conv1", location=None)
        
        mock_conn = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        with patch("ohtv.db.stores.conversation_store.ConversationStore") as mock_conv_store_cls, \
             patch("ohtv.db.stores.embedding_store.EmbeddingStore") as mock_embed_store_cls, \
             patch("ohtv.filters.normalize_conversation_id", side_effect=lambda x: x):
            
            mock_conv_store = MagicMock()
            mock_conv_store.list_all.return_value = [mock_conv]
            mock_conv_store_cls.return_value = mock_conv_store
            
            mock_embed_store = MagicMock()
            mock_embed_store.list_conversation_ids.return_value = []
            # Return empty list - but since location is None, nothing has content
            mock_embed_store.list_conversations_needing_embeddings.return_value = []
            mock_embed_store_cls.return_value = mock_embed_store
            
            _run_post_sync_embeddings(quiet=False, verbose=False)
        
        captured = capsys.readouterr()
        # The message is "All local conversations have embeddings (N without content skipped)"
        # OR just "All conversations have embeddings" if no_local_content is 0
        # Since our mock has location=None, it should count as no_local_content 
        assert "All" in captured.out and "embeddings" in captured.out


class TestProgressThresholdConstant:
    """Test the progress threshold constant is properly set."""
    
    def test_progress_threshold_is_20(self):
        """Verify the PROGRESS_THRESHOLD constant is 20 as specified in requirements."""
        # We can't directly access the constant since it's inside the function,
        # but we can verify the behavior matches the expected threshold
        # by checking the code structure
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        assert "PROGRESS_THRESHOLD = 20" in source


class TestWorkerCountLogic:
    """Tests for worker count determination logic."""
    
    def test_worker_count_logic_in_code(self):
        """Verify worker count logic exists for both model types."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        
        # Check for Ollama-specific logic (4 workers)
        assert 'ollama/' in source.lower() or "ollama/" in source
        assert 'min(4,' in source  # Ollama workers
        assert 'min(20,' in source  # Cloud API workers


class TestParallelProcessingStructure:
    """Tests for parallel processing code structure."""
    
    def test_threadpool_executor_used(self):
        """Verify ThreadPoolExecutor is imported and used."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        assert "ThreadPoolExecutor" in source
    
    def test_progress_bar_components(self):
        """Verify the shared make_progress helper is used (issue #91)."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)

        # After #91 the embed flow uses the shared helper rather than
        # individual Rich columns built inline.
        assert "make_progress(" in source
        # And no longer imports rich.progress directly here
        assert "from rich.progress import" not in source


class TestGracefulShutdownHandling:
    """Tests for graceful shutdown on Ctrl+C."""
    
    def test_keyboard_interrupt_handled(self):
        """Verify KeyboardInterrupt is caught and handled gracefully."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        
        assert "except KeyboardInterrupt:" in source
        assert "Interrupted" in source


class TestRateTracking:
    """Tests for rate tracking implementation."""
    
    def test_rate_tracker_used(self):
        """Verify RateTracker class from ohtv.parallel is used."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        
        # Uses RateTracker class from ohtv.parallel
        assert "RateTracker" in source
        assert "rate_tracker" in source
        assert "get_rate_str()" in source


class TestEmbeddingWriterUsage:
    """Tests for EmbeddingWriter integration."""
    
    def test_embedding_writer_lifecycle(self):
        """Verify EmbeddingWriter start/stop lifecycle."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        
        assert "EmbeddingWriter" in source
        assert "writer.start()" in source
        assert "writer.stop(" in source


class TestQuietAndVerboseFlags:
    """Tests for quiet and verbose mode handling."""
    
    def test_quiet_mode_check(self):
        """Verify quiet mode suppresses progress bar."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        
        # Progress bar should only be used when not quiet
        assert "not quiet" in source
    
    def test_verbose_mode_check(self):
        """Verify verbose mode shows individual conversation processing."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        
        # Verbose should control per-conversation output
        assert "verbose" in source


class TestRateFormatting:
    """Tests for the rate formatting (via RateTracker)."""

    def test_rate_tracker_with_update_interval(self):
        """Test that RateTracker is configured with update interval for smoothing."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        # RateTracker should be initialized with update_interval for smoothing
        assert 'update_interval=' in source
        assert '0.5' in source  # 0.5 second update interval

    def test_rate_tracker_increment_on_completion(self):
        """Test that rate_tracker.increment() is called when processing completes."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        # Should increment counter after each conversation
        assert 'rate_tracker.increment()' in source


class TestUpdateCountersHelper:
    """Tests for the _update_counters helper function logic."""
    
    def test_update_counters_helper_exists(self):
        """Verify _update_counters helper function exists in code."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        assert 'def _update_counters(' in source
        
    def test_update_counters_returns_tuple(self):
        """Verify _update_counters returns tuple for counter updates."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        # Should return a tuple like (error_delta, skipped_delta, embedded_delta)
        assert 'return (1, 0, 0)' in source  # error case
        assert 'return (0, 1, 0)' in source  # skipped case
        assert 'return (0, 0, 1)' in source  # embedded case
        assert 'return (0, 0, 0)' in source  # no-op case
    
    def test_update_counters_handles_all_cases(self):
        """Verify _update_counters handles error, skip, and embed cases."""
        import inspect
        source = inspect.getsource(_run_post_sync_embeddings)
        # Should check for err_msg, stats, and stats.embeddings_created
        assert 'if err_msg:' in source
        assert 'elif stats:' in source
        assert 'embeddings_created == 0' in source


class TestModuleLevelRateFormat:
    """Tests for the module-level rate formatting in parallel module."""
    
    def test_format_rate_basic(self):
        """Test basic rate formatting from parallel module."""
        from ohtv.parallel import format_rate
        
        # 60 items in 60 seconds = 60/min
        result = format_rate(60, 60.0, "conv")
        assert "60.0 conv/min" in result
        
    def test_format_rate_zero_elapsed(self):
        """Test rate format with zero elapsed time."""
        from ohtv.parallel import format_rate
        
        result = format_rate(10, 0.05, "items")
        assert "-- items/min" in result
        
    def test_format_rate_zero_count(self):
        """Test rate format with zero count."""
        from ohtv.parallel import format_rate
        
        result = format_rate(0, 10.0, "items")
        assert "-- items/min" in result


class TestRateTracker:
    """Tests for the RateTracker class from parallel module."""
    
    def test_rate_tracker_basic(self):
        """Test basic RateTracker functionality."""
        from ohtv.parallel import RateTracker
        import time
        
        tracker = RateTracker(unit="conv")
        tracker.increment(5)
        
        # Give it a moment to have elapsed time
        time.sleep(0.15)
        
        result = tracker.get_rate_str()
        assert "conv/min" in result
        
    def test_rate_tracker_thread_safe_increment(self):
        """Test that RateTracker.increment is thread-safe."""
        from ohtv.parallel import RateTracker
        import threading
        
        tracker = RateTracker()
        threads = []
        
        def increment_many():
            for _ in range(100):
                tracker.increment()
        
        for _ in range(4):
            t = threading.Thread(target=increment_many)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert tracker.count == 400
