"""Unit tests for embedding progress bar display (Issue #45, updated by #91).

After issue #91 these tests verify that ``db embed`` uses the shared
:func:`ohtv.progress.make_progress` helper (with ``show_cost=True``)
rather than a hand-rolled Progress column stack.
"""

from pathlib import Path
import pytest


def _get_db_embed_source() -> str:
    """Get the source code section for db_embed function from cli.py."""
    cli_path = Path(__file__).parent.parent.parent / "src" / "ohtv" / "cli.py"
    source = cli_path.read_text()

    start_marker = '@db.command("embed")'
    start_idx = source.find(start_marker)
    if start_idx == -1:
        pytest.fail("Could not find @db.command('embed') in cli.py")

    search_start = start_idx + len(start_marker)
    next_section = source.find("# =====================", search_start)
    next_main_command = source.find('\n@main.command(', search_start)

    candidates = [x for x in [next_section, next_main_command] if x != -1]
    if candidates:
        end_idx = min(candidates)
    else:
        end_idx = start_idx + 10000

    return source[start_idx:end_idx]


class TestEmbedProgressBarComponents:
    """db embed uses the shared make_progress helper (issue #91)."""

    def test_uses_make_progress_helper(self):
        source = _get_db_embed_source()
        assert "make_progress(" in source, \
            "db embed should call ohtv.progress.make_progress() instead of building columns inline"

    def test_no_direct_rich_progress_import(self):
        source = _get_db_embed_source()
        assert "from rich.progress import" not in source, \
            "db embed must not import from rich.progress directly (issue #91 lint)"

    def test_uses_show_cost_true(self):
        """db embed already tracks cost end-to-end; it should now surface it live (issue #91)."""
        source = _get_db_embed_source()
        assert "show_cost=True" in source, \
            "db embed should pass show_cost=True to surface running spend in the bar"

    def test_progress_update_includes_cost_field(self):
        source = _get_db_embed_source()
        assert "cost=estimate_cost(actual_tokens, model)" in source \
            or "cost=cost_val" in source, \
            "progress.update calls should feed the running cost into task.fields[cost]"


class TestFormatRemainingFunction:
    """The _format_remaining helper still exists in the db embed local scope."""

    def test_format_remaining_exists(self):
        source = _get_db_embed_source()
        assert "def _format_remaining(" in source, \
            "_format_remaining function should be defined"

    def test_format_remaining_shows_countdown(self):
        source = _get_db_embed_source()
        assert "remaining = total - processed" in source, \
            "_format_remaining should calculate remaining count"

    def test_format_remaining_shows_errors(self):
        source = _get_db_embed_source()
        assert "if errors > 0:" in source, \
            "_format_remaining should check for errors"
        assert "[red]" in source and "err" in source, \
            "_format_remaining should show errors in red"


class TestFormatRateFunction:
    """The _format_rate helper still has the simplified signature."""

    def test_format_rate_simplified_signature(self):
        source = _get_db_embed_source()
        assert "def _format_rate(processed: int, elapsed: float)" in source, \
            "_format_rate should have simplified signature without new_embeds"

    def test_format_rate_returns_simple_rate(self):
        source = _get_db_embed_source()
        func_start = source.find("def _format_rate(processed: int, elapsed: float)")
        assert func_start != -1, "_format_rate function should exist"
        func_section = source[func_start:func_start + 800]
        assert 'f"{rate:.0f}/min"' in func_section, \
            "_format_rate should return simple rate format"
        assert 'new)"' not in func_section, \
            "_format_rate should not have 'new' suffix"


class TestProgressUpdateCalls:
    """progress.update calls feed the canonical task fields."""

    def test_progress_update_includes_remaining(self):
        source = _get_db_embed_source()
        assert "remaining=" in source and "_format_remaining" in source, \
            "progress.update should include remaining field"

    def test_progress_task_initialized_with_remaining(self):
        source = _get_db_embed_source()
        assert 'remaining=_format_remaining(' in source, \
            "Task should be initialized with remaining count"


class TestLayoutComment:
    def test_has_layout_comment(self):
        source = _get_db_embed_source()
        assert "left" in source and "ETA" in source and "/min" in source, \
            "Code should document expected progress bar layout"


class TestFormatRateCalls:
    """_format_rate is called with the simplified signature."""

    def test_sequential_processing_format_rate_call(self):
        source = _get_db_embed_source()
        assert "_format_rate(processed_count, elapsed)" in source, \
            "Sequential path should use simplified _format_rate call"

    def test_parallel_processing_format_rate_call(self):
        source = _get_db_embed_source()
        assert "rate_str = _format_rate(processed_count, elapsed)" in source, \
            "Parallel path should use simplified _format_rate call"
