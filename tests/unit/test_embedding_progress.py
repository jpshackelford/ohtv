"""Unit tests for embedding progress bar display (Issue #45).

Tests verify the progress bar format change:
- Old: "124/min (124 new)" - misleading, "new" looked like a count
- New: "190 left │ ETA 0:02:15 119/min" - clear remaining count and ETA
"""

from pathlib import Path
import pytest


def _get_db_embed_source() -> str:
    """Get the source code section for db_embed function from cli.py."""
    cli_path = Path(__file__).parent.parent.parent / "src" / "ohtv" / "cli.py"
    source = cli_path.read_text()
    
    # Find the db_embed function - starts with @db.command("embed")
    start_marker = '@db.command("embed")'
    start_idx = source.find(start_marker)
    if start_idx == -1:
        pytest.fail("Could not find @db.command('embed') in cli.py")
    
    # The next command after db_embed is @main.command() for prompts
    # Search for the next @main.command( or section comment
    search_start = start_idx + len(start_marker)
    
    # Look for the section comment or next main command
    next_section = source.find("# =====================", search_start)
    next_main_command = source.find('\n@main.command(', search_start)
    
    # Take the earliest valid marker
    candidates = [x for x in [next_section, next_main_command] if x != -1]
    if candidates:
        end_idx = min(candidates)
    else:
        # Just take a large chunk
        end_idx = start_idx + 10000
    
    return source[start_idx:end_idx]


class TestEmbedProgressBarComponents:
    """Test that progress bar has required components."""
    
    def test_has_time_remaining_column(self):
        """Verify TimeRemainingColumn is imported and used."""
        source = _get_db_embed_source()
        
        assert "TimeRemainingColumn" in source, \
            "TimeRemainingColumn should be imported for ETA display"
    
    def test_progress_bar_layout_matches_sync(self):
        """Verify progress bar layout matches sync format: remaining | ETA | rate."""
        source = _get_db_embed_source()
        
        # Should have remaining field
        assert "{task.fields[remaining]}" in source, \
            "Progress bar should display remaining count"
        
        # Should have ETA column
        assert 'TextColumn("[dim]ETA[/dim]")' in source, \
            "Progress bar should have ETA label"
        assert "TimeRemainingColumn()" in source, \
            "Progress bar should have TimeRemainingColumn for ETA display"
        
        # Should have rate field
        assert "{task.fields[rate]}" in source, \
            "Progress bar should display rate"
    
    def test_no_misleading_new_label(self):
        """Verify the misleading '(X new)' display is removed."""
        source = _get_db_embed_source()
        
        # The old format had "{new_rate:.0f} new)" - this should NOT exist
        assert 'new)"' not in source, \
            "Should not have 'new)' format string in the progress display"
        
        # The new _format_rate should only take processed and elapsed
        assert '_format_rate(processed' in source


class TestFormatRemainingFunction:
    """Test the _format_remaining function behavior in db_embed."""
    
    def test_format_remaining_exists(self):
        """Verify _format_remaining function exists in db_embed."""
        source = _get_db_embed_source()
        
        assert "def _format_remaining(" in source, \
            "_format_remaining function should be defined"
    
    def test_format_remaining_shows_countdown(self):
        """Verify _format_remaining calculates remaining = total - processed."""
        source = _get_db_embed_source()
        
        # Should calculate remaining as difference
        assert "remaining = total - processed" in source, \
            "_format_remaining should calculate remaining count"
    
    def test_format_remaining_shows_errors(self):
        """Verify _format_remaining shows error count when errors > 0."""
        source = _get_db_embed_source()
        
        # Should have conditional for errors
        assert "if errors > 0:" in source, \
            "_format_remaining should check for errors"
        assert "[red]" in source and "err" in source, \
            "_format_remaining should show errors in red"


class TestFormatRateFunction:
    """Test the _format_rate function behavior in db_embed."""
    
    def test_format_rate_simplified_signature(self):
        """Verify _format_rate has simplified signature (no new_embeds param)."""
        source = _get_db_embed_source()
        
        # Find the function definition
        # Old: def _format_rate(processed: int, new_embeds: int, elapsed: float)
        # New: def _format_rate(processed: int, elapsed: float)
        assert "def _format_rate(processed: int, elapsed: float)" in source, \
            "_format_rate should have simplified signature without new_embeds"
    
    def test_format_rate_returns_simple_rate(self):
        """Verify _format_rate returns simple rate format without 'new' suffix."""
        source = _get_db_embed_source()
        
        # Find the _format_rate function and check the return format
        func_start = source.find("def _format_rate(processed: int, elapsed: float)")
        assert func_start != -1, "_format_rate function should exist"
        
        # Get the function body - need more than 500 chars to capture the format string
        func_section = source[func_start:func_start + 800]
        
        # Should have format like f"{rate:.0f}/min" - note: escaping curly braces in the test
        assert 'f"{rate:.0f}/min"' in func_section, \
            "_format_rate should return simple rate format"
        
        # Should NOT have 'new' in the format string
        assert 'new)"' not in func_section, \
            "_format_rate should not have 'new' suffix"


class TestProgressUpdateCalls:
    """Test that progress.update calls include correct fields."""
    
    def test_progress_update_includes_remaining(self):
        """Verify progress.update calls include remaining field."""
        source = _get_db_embed_source()
        
        # Should have remaining= in progress.update calls
        assert "remaining=" in source and "_format_remaining" in source, \
            "progress.update should include remaining field"
    
    def test_progress_task_initialized_with_remaining(self):
        """Verify progress task is initialized with remaining field."""
        source = _get_db_embed_source()
        
        # add_task should have remaining in initial fields
        assert 'remaining=_format_remaining(' in source, \
            "Task should be initialized with remaining count"


class TestLayoutComment:
    """Test that code includes layout documentation comment."""
    
    def test_has_layout_comment(self):
        """Verify code has comment showing expected progress bar layout."""
        source = _get_db_embed_source()
        
        # Should have comment like: Embedding ━━━━━━━━━ 62% 190 left │ ETA 0:02:15 119/min
        assert "left" in source and "ETA" in source and "/min" in source, \
            "Code should document expected progress bar layout"


class TestFormatRateCalls:
    """Test that _format_rate is called with simplified signature."""
    
    def test_sequential_processing_format_rate_call(self):
        """Verify sequential processing uses simplified _format_rate call."""
        source = _get_db_embed_source()
        
        # Should call _format_rate(processed_count, elapsed) not _format_rate(processed_count, embedded, elapsed)
        # The old signature was: _format_rate(processed_count, embedded, elapsed)
        assert "_format_rate(processed_count, elapsed)" in source, \
            "Sequential path should use simplified _format_rate call"
    
    def test_parallel_processing_format_rate_call(self):
        """Verify parallel processing uses simplified _format_rate call."""
        source = _get_db_embed_source()
        
        # Should have rate_str = _format_rate(processed_count, elapsed)
        assert "rate_str = _format_rate(processed_count, elapsed)" in source, \
            "Parallel path should use simplified _format_rate call"
