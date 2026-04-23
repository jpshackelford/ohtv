"""Unit tests for the parallel module."""

import threading
import time

import pytest

from ohtv.parallel import format_rate, RateTracker, run_parallel


class TestFormatRate:
    """Tests for format_rate function."""

    def test_returns_rate_for_valid_inputs(self):
        # 10 items in 60 seconds = 10/min
        result = format_rate(10, 60.0)
        assert result == "10.0 items/min"

    def test_returns_placeholder_for_zero_count(self):
        result = format_rate(0, 60.0)
        assert result == "-- items/min"

    def test_returns_placeholder_for_short_elapsed(self):
        result = format_rate(10, 0.05)
        assert result == "-- items/min"

    def test_custom_unit(self):
        result = format_rate(30, 60.0, unit="conv")
        assert result == "30.0 conv/min"

    def test_fractional_rate(self):
        # 5 items in 30 seconds = 10/min
        result = format_rate(5, 30.0)
        assert result == "10.0 items/min"


class TestRateTracker:
    """Tests for RateTracker class."""

    def test_initial_count_is_zero(self):
        tracker = RateTracker()
        assert tracker.count == 0

    def test_increment_increases_count(self):
        tracker = RateTracker()
        tracker.increment()
        assert tracker.count == 1
        tracker.increment(5)
        assert tracker.count == 6

    def test_elapsed_time_increases(self):
        tracker = RateTracker()
        time.sleep(0.1)
        assert tracker.elapsed >= 0.1

    def test_get_rate_str_returns_placeholder_initially(self):
        tracker = RateTracker()
        assert "--" in tracker.get_rate_str()

    def test_thread_safety(self):
        """Test that RateTracker is thread-safe."""
        tracker = RateTracker()
        threads = []
        
        def increment_many():
            for _ in range(100):
                tracker.increment()
        
        for _ in range(10):
            t = threading.Thread(target=increment_many)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert tracker.count == 1000


class TestRunParallel:
    """Tests for run_parallel function."""

    def test_empty_list_returns_empty(self):
        results = run_parallel([], lambda x: x)
        assert results == []

    def test_single_item_processed_sequentially(self):
        results = run_parallel([1], lambda x: x * 2)
        assert len(results) == 1
        item, result, error = results[0]
        assert item == 1
        assert result == 2
        assert error is None

    def test_multiple_items_processed(self):
        items = [1, 2, 3, 4, 5]
        results = run_parallel(items, lambda x: x * 2, max_workers=2)
        
        assert len(results) == 5
        result_values = {r[1] for r in results if r[2] is None}
        assert result_values == {2, 4, 6, 8, 10}

    def test_errors_captured(self):
        def may_fail(x):
            if x == 3:
                raise ValueError("Test error")
            return x
        
        results = run_parallel([1, 2, 3, 4], may_fail)
        
        errors = [r for r in results if r[2] is not None]
        assert len(errors) == 1
        assert errors[0][0] == 3

    def test_on_result_callback(self):
        callback_items = []
        
        def on_result(item, result):
            callback_items.append((item, result))
        
        run_parallel([1, 2], lambda x: x * 2, on_result=on_result)
        
        assert len(callback_items) == 2
        assert (1, 2) in callback_items
        assert (2, 4) in callback_items

    def test_shutdown_check_stops_processing_sequential(self):
        """Test shutdown_check with sequential processing (max_workers=1)."""
        processed = []
        call_count = [0]
        
        def process(x):
            processed.append(x)
            time.sleep(0.1)  # Simulate work
            return x
        
        def shutdown_after_2():
            call_count[0] += 1
            return call_count[0] > 2
        
        run_parallel(
            list(range(10)), 
            process, 
            max_workers=1,  # Sequential to test shutdown
            shutdown_check=shutdown_after_2
        )
        
        # Should have processed 2 or 3 items before shutdown
        assert len(processed) <= 3

    def test_shutdown_check_stops_processing_parallel(self):
        """Test shutdown_check with parallel processing (multiple workers)."""
        processed = []
        processed_lock = threading.Lock()
        shutdown_requested = [False]
        
        def process(x):
            time.sleep(0.05)  # Simulate work
            with processed_lock:
                processed.append(x)
            return x
        
        def request_shutdown_after_some():
            with processed_lock:
                # Request shutdown after some items are processed
                if len(processed) >= 2:
                    shutdown_requested[0] = True
            return shutdown_requested[0]
        
        run_parallel(
            list(range(20)), 
            process, 
            max_workers=4,  # Parallel processing
            shutdown_check=request_shutdown_after_some
        )
        
        # With 4 workers and shutdown after 2 processed, we might have up to
        # 4 in-flight + 2 already done before shutdown is detected
        # Due to timing, some extra items may complete - allow reasonable tolerance
        assert len(processed) < 20, "Should stop before all items are processed"
