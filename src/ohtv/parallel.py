"""Utilities for parallel processing with progress display."""

import signal
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def format_rate(count: int, elapsed_seconds: float, unit: str = "items") -> str:
    """Format processing rate as items/min.
    
    Args:
        count: Number of items processed
        elapsed_seconds: Time elapsed in seconds
        unit: Unit name for display (e.g., "items", "conv")
    
    Returns:
        Formatted rate string like "42.5 items/min" or "-- items/min" if not calculable
    """
    if elapsed_seconds < 0.1 or count == 0:
        return f"-- {unit}/min"
    rate = count / (elapsed_seconds / 60.0)
    return f"{rate:.1f} {unit}/min"


@dataclass
class ParallelResult:
    """Results from parallel processing."""
    
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)  # (id, error_message)


@dataclass
class WorkItem:
    """A unit of work for parallel processing."""
    
    id: str
    data: dict


@contextmanager
def graceful_shutdown_handler(
    console,
    shutdown_flag: list[bool],
) -> Iterator[None]:
    """Context manager for graceful shutdown handling on SIGINT/SIGTERM.
    
    Args:
        console: Rich console for printing messages
        shutdown_flag: Mutable list with single bool element, set to True on shutdown
    
    Usage:
        shutdown_flag = [False]
        with graceful_shutdown_handler(console, shutdown_flag):
            while not shutdown_flag[0]:
                # do work
    """
    def _handle_shutdown(signum, frame):
        shutdown_flag[0] = True
        console.print("\n[yellow]Shutdown requested - finishing current work...[/yellow]")
    
    old_sigint = signal.signal(signal.SIGINT, _handle_shutdown)
    old_sigterm = signal.signal(signal.SIGTERM, _handle_shutdown)
    
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)


def run_parallel(
    items: list[T],
    process_fn: Callable[[T], R],
    max_workers: int = 20,
    on_result: Callable[[T, R], None] | None = None,
    on_error: Callable[[T, Exception], None] | None = None,
    shutdown_check: Callable[[], bool] | None = None,
) -> list[tuple[T, R | None, Exception | None]]:
    """Run a function on items in parallel with a thread pool.
    
    Args:
        items: Items to process
        process_fn: Function to call on each item, returns result
        max_workers: Maximum worker threads (default 20 for API calls)
        on_result: Optional callback after each successful result
        on_error: Optional callback after each error
        shutdown_check: Optional function that returns True if shutdown requested
    
    Returns:
        List of (item, result, error) tuples. Error is None if successful.
    """
    if not items:
        return []
    
    results: list[tuple[T, R | None, Exception | None]] = []
    lock = threading.Lock()
    
    actual_workers = min(max_workers, len(items))
    
    if actual_workers == 1:
        # Sequential processing
        for item in items:
            if shutdown_check and shutdown_check():
                break
            try:
                result = process_fn(item)
                results.append((item, result, None))
                if on_result:
                    on_result(item, result)
            except Exception as e:
                results.append((item, None, e))
                if on_error:
                    on_error(item, e)
    else:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            future_to_item: dict[Future, T] = {
                executor.submit(process_fn, item): item
                for item in items
            }
            
            pending = set(future_to_item.keys())
            while pending:
                if shutdown_check and shutdown_check():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                
                # Wait with timeout to allow shutdown check
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                
                for future in done:
                    item = future_to_item[future]
                    try:
                        result = future.result()
                        with lock:
                            results.append((item, result, None))
                        if on_result:
                            on_result(item, result)
                    except Exception as e:
                        with lock:
                            results.append((item, None, e))
                        if on_error:
                            on_error(item, e)
    
    return results


class RateTracker:
    """Thread-safe rate tracker for progress display."""
    
    def __init__(self, unit: str = "items", update_interval: float = 0.5):
        """Initialize rate tracker.
        
        Args:
            unit: Unit name for display
            update_interval: Minimum seconds between rate recalculations (smooths jitter)
        """
        self.unit = unit
        self.update_interval = update_interval
        self._lock = threading.Lock()
        self._start_time = time.perf_counter()
        self._count = 0
        self._last_rate_str = ""
        self._last_rate_update = 0.0
    
    def increment(self, n: int = 1) -> None:
        """Increment the count."""
        with self._lock:
            self._count += n
    
    @property
    def count(self) -> int:
        """Get current count."""
        with self._lock:
            return self._count
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        return time.perf_counter() - self._start_time
    
    def get_rate_str(self) -> str:
        """Get current rate string, smoothed to avoid jitter."""
        elapsed = self.elapsed
        with self._lock:
            count = self._count
            
            if elapsed < 0.1 or count == 0:
                return f"-- {self.unit}/min"
            
            # Only recalculate periodically to smooth jitter
            if elapsed - self._last_rate_update < self.update_interval and self._last_rate_str:
                return self._last_rate_str
            
            self._last_rate_update = elapsed
            rate = count / (elapsed / 60.0)
            self._last_rate_str = f"{rate:.1f} {self.unit}/min"
            return self._last_rate_str
