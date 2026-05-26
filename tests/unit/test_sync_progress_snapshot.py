"""Byte-identical sync progress regression guard for issue #91.

Locks in the rendered output of the canonical ``ohtv sync`` progress bar
at a fixed mid-run state. The exact bytes must remain stable so that
migrating from inline ``Progress(...)`` blocks to the shared
:func:`make_progress` helper does not visually regress.

This compares to a reconstruction of the *pre-migration* canonical
layout (the literal ``[bold blue]Syncing`` description + 9-column shape)
to verify that the helper produces byte-identical output for the same
task state.

References:
- Issue #91 audit table (sync canonical layout)
- Expansion note #4 (frozen-clock approach for snapshot stability)
"""

from __future__ import annotations

import io

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from ohtv.parallel import format_remaining
from ohtv.progress import make_progress

# Fixed task state used by both renderings.
TASK_DESC = "Syncing"
TASK_TOTAL = 200
TASK_COMPLETED = 68
TASK_ELAPSED = 24.5  # seconds since "start"
TASK_RATE = "166/min"


def _build_canonical_pre_migration_progress(console: Console) -> Progress:
    """Reconstruct the pre-migration canonical sync layout verbatim.

    This is the literal 9-column shape that the sync site used before
    issue #91, with ``TextColumn("[bold blue]Syncing")`` rather than
    ``TextColumn("[bold blue]{task.description}")``.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Syncing"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.fields[remaining]}"),
        TextColumn("[dim]│[/dim]"),
        TextColumn("[dim]ETA[/dim]"),
        TimeRemainingColumn(),
        TextColumn("[dim]{task.fields[rate]}[/dim]"),
        console=console,
        transient=True,
    )


def _capture_progress_output(progress: Progress) -> str:
    """Render the first task's columns to a no-color string."""
    task = progress.tasks[0]
    capture_console = Console(
        file=io.StringIO(),
        force_terminal=True,
        width=120,
        no_color=True,
        legacy_windows=False,
    )
    parts: list[str] = []
    for col in progress.columns:
        rendered = col.render(task)
        with capture_console.capture() as cap:
            capture_console.print(rendered, end="")
        parts.append(cap.get())
    return "".join(parts)


def _seed_task(progress: Progress) -> int:
    task_id = progress.add_task(
        TASK_DESC,
        total=TASK_TOTAL,
        completed=TASK_COMPLETED,
        remaining=format_remaining(TASK_TOTAL, TASK_COMPLETED, 0),
        rate=TASK_RATE,
    )
    task = progress.tasks[task_id]
    # Backdate start_time so elapsed is deterministic. Rich uses this
    # to compute TimeRemainingColumn.
    task.start_time = task.get_time() - TASK_ELAPSED
    return task_id


def test_sync_progress_output_is_byte_identical_to_pre_migration():
    """Layout produced by make_progress() == hand-built canonical layout."""
    console_a = Console(
        file=io.StringIO(),
        force_terminal=True,
        width=120,
        no_color=True,
        legacy_windows=False,
    )
    console_b = Console(
        file=io.StringIO(),
        force_terminal=True,
        width=120,
        no_color=True,
        legacy_windows=False,
    )

    # Reference: pre-migration canonical layout
    with _build_canonical_pre_migration_progress(console_a) as ref:
        _seed_task(ref)
        ref_output = _capture_progress_output(ref)

    # Under test: shared helper with default args
    with make_progress(console=console_b) as helper:
        _seed_task(helper)
        helper_output = _capture_progress_output(helper)

    assert helper_output == ref_output, (
        "make_progress() default layout drifted from the canonical sync layout.\n"
        f"Reference:\n  {ref_output!r}\n"
        f"Helper:\n  {helper_output!r}"
    )


def test_sync_progress_contains_documented_pieces():
    """Smoke check: the canonical layout still contains every documented piece."""
    console = Console(
        file=io.StringIO(),
        force_terminal=True,
        width=120,
        no_color=True,
        legacy_windows=False,
    )
    with make_progress(console=console) as progress:
        _seed_task(progress)
        text = _capture_progress_output(progress)

    # Documented shape: ⠸ Syncing ━━━ NN% N left │ ETA H:MM:SS N/min
    assert "Syncing" in text
    assert "34%" in text  # 68/200 = 34%
    assert "132" in text  # remaining = 200 - 68
    assert "left" in text
    assert "│" in text
    assert "ETA" in text
    assert "166/min" in text
