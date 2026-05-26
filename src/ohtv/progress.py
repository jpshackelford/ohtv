"""Shared Rich Progress factory for ohtv long-running commands.

All progress bars in ohtv should be built through :func:`make_progress`
rather than instantiating :class:`rich.progress.Progress` directly.

The canonical layout (used by ``ohtv sync`` and now everywhere by
default) is::

    ⠸ Syncing ━━━━━━━━━━━ 34% 142 left │ ETA 0:00:50 166/min

Column order (left → right):

1. ``SpinnerColumn()``
2. ``TextColumn("[bold blue]{task.description}")`` — action verb /
   description. Always rendered from ``task.description`` so callers
   can update the verb mid-run (e.g. "Processing week 12 2024").
3. ``BarColumn()``
4. ``TaskProgressColumn()`` — percentage.
5. ``TextColumn("{task.fields[remaining]}")`` — "N left" string built
   by :func:`ohtv.parallel.format_remaining` (opt-out with
   ``show_remaining=False``).
6. ``TextColumn("[dim]│[/dim]")`` — visual separator. Appears iff at
   least one of the following tail columns is present.
7. ``TextColumn("[dim]ETA[/dim]")`` + ``TimeRemainingColumn()``
   (opt-out with ``show_eta=False``).
8. ``TextColumn("[dim]{task.fields[rate]}[/dim]")`` — "N/min" string
   built by :class:`ohtv.parallel.RateTracker` (opt-out with
   ``show_rate=False``).
9. ``TextColumn("[green]$[/green]{task.fields[cost]:.4f}")`` — live
   running spend, opt-in with ``show_cost=True``.
10. ``TextColumn("[dim]{task.fields[current]}[/dim]")`` — current item
    indicator (e.g. truncated conversation id), opt-in with
    ``show_current=True``. Mutually useful with ``show_eta=False``
    when the work units have no sensible rate / ETA.

Notes for callers:

* Quiet mode is the caller's responsibility — short-circuit by not
  calling :func:`make_progress` at all (use ``contextlib.nullcontext``
  if you need a uniform ``with`` block).
* ``transient=True`` is the default so completed bars are scrubbed
  after the run, matching ``ohtv sync``'s behaviour.
* For long-running commands that spend the user's money on LLM /
  embedding API calls, pass ``show_cost=True`` and feed
  ``cost=<running_total>`` into ``progress.update(task, ...)``.
"""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


def make_progress(
    *,
    console: Console,
    show_rate: bool = True,
    show_remaining: bool = True,
    show_eta: bool = True,
    show_current: bool = False,
    show_cost: bool = False,
    transient: bool = True,
) -> Progress:
    """Build a Rich :class:`Progress` instance using ohtv's canonical layout.

    The default arguments yield the canonical ``ohtv sync`` layout:
    spinner, description, bar, percentage, "N left", separator, ETA,
    and rate. Each tail-column flag controls exactly one column and
    the visual separator is rendered automatically iff at least one
    tail column is requested.

    The description column always renders ``task.description``, so
    callers should pass a descriptive verb (e.g. ``"Syncing"``,
    ``"Embedding"``, ``"Processing 2024-W12"``) via
    ``progress.add_task(description, ...)``. Callers may freely update
    the description mid-run via ``progress.update(task, description=...)``.

    Args:
        console: Rich :class:`Console` to render to.
        show_rate: Include the "N/min" rate column. Reads
            ``task.fields[rate]``.
        show_remaining: Include the "N left" counter. Reads
            ``task.fields[remaining]``.
        show_eta: Include the "ETA H:MM:SS" indicator.
        show_current: Include the current-item tail indicator. Reads
            ``task.fields[current]``.
        show_cost: Include the live "$N.NNNN" running-spend column.
            Reads ``task.fields[cost]``.
        transient: Hide the bar after completion (default ``True``).

    Returns:
        A :class:`Progress` instance, ready to use as a context manager.
    """
    columns: list = [
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ]
    if show_remaining:
        columns.append(TextColumn("{task.fields[remaining]}"))

    # Visual separator is shown only if at least one tail column follows.
    has_tail = show_eta or show_rate or show_cost or show_current
    if has_tail:
        columns.append(TextColumn("[dim]│[/dim]"))

    if show_eta:
        columns.append(TextColumn("[dim]ETA[/dim]"))
        columns.append(TimeRemainingColumn())
    if show_rate:
        columns.append(TextColumn("[dim]{task.fields[rate]}[/dim]"))
    if show_cost:
        columns.append(TextColumn("[green]$[/green]{task.fields[cost]:.4f}"))
    if show_current:
        columns.append(TextColumn("[dim]{task.fields[current]}[/dim]"))

    return Progress(*columns, console=console, transient=transient)


__all__ = ["make_progress"]
