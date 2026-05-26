"""Unit tests for ohtv.progress.make_progress helper."""

from __future__ import annotations

import io
import re

from rich.console import Console
from rich.progress import (
    Progress,
    TaskProgressColumn,
    TextColumn,
)

from ohtv.parallel import format_remaining
from ohtv.progress import make_progress


# ---------- column-shape tests ----------------------------------------------


def _column_types(progress: Progress) -> list[str]:
    """Return the class names of columns in order."""
    return [type(col).__name__ for col in progress.columns]


def _text_columns(progress: Progress) -> list[str]:
    """Return the formatted text for each *pure* TextColumn, in order.

    Excludes :class:`TaskProgressColumn` because it's a TextColumn subclass
    with its own preset format.
    """
    return [
        col.text_format
        for col in progress.columns
        if isinstance(col, TextColumn) and not isinstance(col, TaskProgressColumn)
    ]


class TestMakeProgressDefaults:
    """Canonical layout = the ohtv sync default."""

    def test_default_column_order(self):
        with make_progress(console=Console(file=io.StringIO())) as progress:
            types = _column_types(progress)
            # spinner, desc(text), bar, %, "N left"(text), separator(text),
            # "ETA"(text), TimeRemaining, rate(text)
            assert types == [
                "SpinnerColumn",
                "TextColumn",
                "BarColumn",
                "TaskProgressColumn",
                "TextColumn",
                "TextColumn",
                "TextColumn",
                "TimeRemainingColumn",
                "TextColumn",
            ]

    def test_default_text_columns(self):
        with make_progress(console=Console(file=io.StringIO())) as progress:
            texts = _text_columns(progress)
            assert texts == [
                "[bold blue]{task.description}",
                "{task.fields[remaining]}",
                "[dim]│[/dim]",
                "[dim]ETA[/dim]",
                "[dim]{task.fields[rate]}[/dim]",
            ]

    def test_default_transient_true(self):
        with make_progress(console=Console(file=io.StringIO())) as progress:
            # The Live instance under the bar carries the transient flag.
            assert progress.live.transient is True


# ---------- per-flag opt-out tests ------------------------------------------


class TestMakeProgressFlags:
    """Each flag toggles exactly the column it claims to."""

    def test_show_rate_false_removes_rate_column(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
        ) as progress:
            texts = _text_columns(progress)
            assert "[dim]{task.fields[rate]}[/dim]" not in texts

    def test_show_remaining_false_removes_remaining_column(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_remaining=False,
        ) as progress:
            texts = _text_columns(progress)
            assert "{task.fields[remaining]}" not in texts

    def test_show_eta_false_removes_eta_columns(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_eta=False,
        ) as progress:
            types = _column_types(progress)
            assert "TimeRemainingColumn" not in types
            texts = _text_columns(progress)
            assert "[dim]ETA[/dim]" not in texts

    def test_show_cost_true_appends_cost_column(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_cost=True,
        ) as progress:
            texts = _text_columns(progress)
            assert "[green]$[/green]{task.fields[cost]:.4f}" in texts

    def test_show_current_true_appends_current_column(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_current=True,
        ) as progress:
            texts = _text_columns(progress)
            assert "[dim]{task.fields[current]}[/dim]" in texts

    def test_transient_false_passthrough(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            transient=False,
        ) as progress:
            assert progress.live.transient is False


# ---------- separator behavior ---------------------------------------------


class TestSeparator:
    """The visual separator '│' appears iff at least one tail column does."""

    def test_separator_present_with_eta(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
            show_cost=False,
            show_current=False,
            show_eta=True,
        ) as progress:
            assert "[dim]│[/dim]" in _text_columns(progress)

    def test_separator_present_with_rate_only(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=True,
            show_eta=False,
            show_cost=False,
            show_current=False,
        ) as progress:
            assert "[dim]│[/dim]" in _text_columns(progress)

    def test_separator_present_with_cost_only(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
            show_eta=False,
            show_cost=True,
            show_current=False,
        ) as progress:
            assert "[dim]│[/dim]" in _text_columns(progress)

    def test_separator_present_with_current_only(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
            show_eta=False,
            show_cost=False,
            show_current=True,
        ) as progress:
            assert "[dim]│[/dim]" in _text_columns(progress)

    def test_separator_absent_with_no_tail_columns(self):
        # bar-only mode: spinner + desc + bar + % + remaining, no tail
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
            show_eta=False,
            show_cost=False,
            show_current=False,
            show_remaining=True,
        ) as progress:
            assert "[dim]│[/dim]" not in _text_columns(progress)

    def test_separator_absent_with_no_columns_at_all(self):
        # remaining off, no tail = just bar + %
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
            show_eta=False,
            show_cost=False,
            show_current=False,
            show_remaining=False,
        ) as progress:
            assert "[dim]│[/dim]" not in _text_columns(progress)


# ---------- positional invariants -------------------------------------------


class TestCostColumnPosition:
    """show_cost places the $ column at the documented spot."""

    def test_cost_after_rate(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_cost=True,
        ) as progress:
            texts = _text_columns(progress)
            rate_idx = texts.index("[dim]{task.fields[rate]}[/dim]")
            cost_idx = texts.index("[green]$[/green]{task.fields[cost]:.4f}")
            assert cost_idx == rate_idx + 1

    def test_cost_without_rate(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_rate=False,
            show_cost=True,
        ) as progress:
            texts = _text_columns(progress)
            assert "[green]$[/green]{task.fields[cost]:.4f}" in texts


class TestCurrentColumnPosition:
    """show_current places the current-item column at the end of the tail."""

    def test_current_at_end(self):
        with make_progress(
            console=Console(file=io.StringIO()),
            show_current=True,
            show_cost=True,
        ) as progress:
            texts = _text_columns(progress)
            # current is the very last TextColumn
            assert texts[-1] == "[dim]{task.fields[current]}[/dim]"


# ---------- rendered output snapshot tests ----------------------------------


def _render_progress_snapshot(progress: Progress) -> str:
    """Capture the rendered output of a progress instance's bar, ANSI-stripped.

    Builds the Renderable from the column layout the same way Rich does,
    then strips ANSI escape codes so assertions can match readable text.
    """
    task = progress.tasks[0]
    columns = progress.columns
    capture_console = Console(
        file=io.StringIO(),
        force_terminal=True,
        width=120,
        no_color=True,  # plain text, no ANSI codes
        legacy_windows=False,
    )
    parts = []
    for col in columns:
        rendered = col.render(task)
        with capture_console.capture() as cap:
            capture_console.print(rendered, end="")
        parts.append(cap.get())
    return "".join(parts)


class TestRenderedSnapshots:
    """Lock-in tests for the rendered shape of a fixed task state."""

    def test_default_layout_renders_canonical_shape(self):
        # Construct a progress with a fixed time so TimeRemaining is deterministic.
        # We use start_time = -elapsed so the task appears to have been running for `elapsed` seconds.
        console = Console(
            file=io.StringIO(),
            force_terminal=True,
            width=120,
            no_color=False,
            legacy_windows=False,
        )
        # Use auto_refresh=False to avoid background thread races.
        with make_progress(console=console) as progress:
            # Pre-seed task with known state
            task_id = progress.add_task(
                "Syncing",
                total=200,
                completed=68,
                remaining=format_remaining(200, 68, 0),
                rate="166/min",
            )
            # Force a fixed elapsed time so TimeRemaining is reproducible.
            task = progress.tasks[task_id]
            task.start_time = task.get_time() - 24.5  # 24.5s elapsed
            text = _render_progress_snapshot(progress)

        # The line must contain the verb, percent, "left", separator, ETA label, and rate.
        assert "Syncing" in text
        assert "34%" in text
        assert "132" in text  # remaining
        assert "left" in text
        assert "│" in text
        assert "ETA" in text
        assert "166/min" in text

    def test_show_cost_renders_dollar_amount(self):
        console = Console(
            file=io.StringIO(),
            force_terminal=True,
            width=120,
            no_color=False,
            legacy_windows=False,
        )
        with make_progress(console=console, show_cost=True) as progress:
            task_id = progress.add_task(
                "Embedding",
                total=200,
                completed=68,
                remaining=format_remaining(200, 68, 0),
                rate="166/min",
                cost=0.0042,
            )
            task = progress.tasks[task_id]
            task.start_time = task.get_time() - 24.5
            text = _render_progress_snapshot(progress)

        assert "Embedding" in text
        assert "$0.0042" in text
        # Cost matches the documented .4f format
        assert re.search(r"\$\d+\.\d{4}", text) is not None

    def test_show_current_renders_current_item(self):
        console = Console(
            file=io.StringIO(),
            force_terminal=True,
            width=120,
            no_color=False,
            legacy_windows=False,
        )
        with make_progress(
            console=console,
            show_rate=False,
            show_remaining=False,
            show_eta=False,
            show_current=True,
        ) as progress:
            progress.add_task(
                "Scanning",
                total=100,
                completed=37,
                current="abc123def456...",
            )
            text = _render_progress_snapshot(progress)

        assert "Scanning" in text
        assert "37%" in text
        assert "abc123def456..." in text


# ---------- contract: sync canonical layout is preserved --------------------


class TestSyncCanonicalContract:
    """The sync layout is the canonical one. Default args must reproduce it."""

    def test_sync_default_columns_match_documented_layout(self):
        with make_progress(console=Console(file=io.StringIO())) as progress:
            types = _column_types(progress)

        # Documented column shape for `ohtv sync`:
        # 1. SpinnerColumn
        # 2. TextColumn (description)
        # 3. BarColumn
        # 4. TaskProgressColumn
        # 5. TextColumn (remaining)
        # 6. TextColumn (separator)
        # 7. TextColumn (ETA label)
        # 8. TimeRemainingColumn
        # 9. TextColumn (rate)
        assert types == [
            "SpinnerColumn",
            "TextColumn",
            "BarColumn",
            "TaskProgressColumn",
            "TextColumn",
            "TextColumn",
            "TextColumn",
            "TimeRemainingColumn",
            "TextColumn",
        ]


# ---------- live update simulation -----------------------------------------


class TestCostUpdatesLiveUpdate:
    """show_cost field can be updated mid-run and the new value renders."""

    def test_cost_updates_visible(self):
        console = Console(
            file=io.StringIO(),
            force_terminal=True,
            width=120,
            no_color=False,
            legacy_windows=False,
        )
        with make_progress(console=console, show_cost=True) as progress:
            task_id = progress.add_task(
                "Embedding", total=100, completed=10, remaining="90 left",
                rate="5/min", cost=0.001,
            )
            t = progress.tasks[task_id]
            t.start_time = t.get_time() - 5.0
            text1 = _render_progress_snapshot(progress)
            assert "$0.0010" in text1

            progress.update(task_id, completed=20, cost=0.0123)
            text2 = _render_progress_snapshot(progress)
            assert "$0.0123" in text2

    def test_cost_grows_monotonically(self):
        """Integration-style: feed multiple updates and verify cost ticks upward."""
        console = Console(
            file=io.StringIO(),
            force_terminal=True,
            width=120,
            no_color=False,
            legacy_windows=False,
        )
        with make_progress(console=console, show_cost=True) as progress:
            task_id = progress.add_task(
                "Embedding", total=100, completed=0,
                remaining="100 left", rate="-- /min", cost=0.0,
            )
            t = progress.tasks[task_id]
            t.start_time = t.get_time() - 5.0
            seen_costs = []
            for i, cost in enumerate([0.001, 0.005, 0.012, 0.025, 0.050]):
                progress.update(task_id, completed=(i + 1) * 20, cost=cost)
                text = _render_progress_snapshot(progress)
                m = re.search(r"\$(\d+\.\d{4})", text)
                assert m is not None
                seen_costs.append(float(m.group(1)))
            assert seen_costs == sorted(seen_costs)
            assert seen_costs[0] < seen_costs[-1]
