"""Static chart rendering for velocity reports (issue #82).

Renders a 3-panel matplotlib figure from a list of
:class:`ohtv.reports.velocity.VelocityRow` values to a file. The
output format is inferred from the file extension (``.png`` /
``.svg`` / ``.pdf``); there is intentionally no ``--format`` flag.

``matplotlib`` is an *optional* dependency (``ohtv[charts]``). To keep
``import ohtv.reports.charts`` cheap and dependency-free for callers
that never invoke charting, matplotlib is imported lazily inside
:func:`plot_velocity`. A missing matplotlib raises ``ImportError``;
the CLI wrapper catches that and re-raises as a friendly
``click.UsageError``.

Design choices (see issue #82's technical-approach comment for the
full rationale):

* Three vertically-stacked panels sharing the ISO-week x-axis:

  1. PR counts (bar chart of ``prs_merged`` per week).
  2. LOC delta (diverging bars: +``lines_added`` above zero, the
     negation of ``lines_removed`` below zero).
  3. Words/LOC ratio (line + markers, with ``None`` ratios masked so
     the line breaks across a gap rather than raising or drawing
     through zero).

* X-ticks are the ISO week labels rotated 45° right-aligned.

* ``mark_date`` draws a single ``axvline`` on every panel at the
  x-position corresponding to that date's ISO week. Off-range dates
  are clipped to the nearest end of the range.

* The figure title is the ``title`` argument (default
  ``"Development Velocity"``).

* Saving uses ``bbox_inches="tight"``. Raster formats use DPI=300;
  vector formats ignore the DPI hint.

* No ``plt.show()`` — this module is headless-only by design.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

from ohtv.reports.velocity import VelocityRow


# Allowed output formats, derived from the file extension.
_SUPPORTED_EXTS = frozenset({".png", ".svg", ".pdf"})


def _iso_week_label_for_date(d: date) -> str:
    """Return the ``YYYY-Www`` ISO label for a calendar date."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _mark_date_x_position(rows: Sequence[VelocityRow], mark: date) -> float:
    """Compute the x-axis position for ``mark`` against the row index.

    The bars/markers are plotted against an integer x-axis
    ``range(len(rows))``. We return a float position so off-week
    marks land between bars (or at the boundary when ``mark`` falls
    outside the data range).

    Strategy:
        * Build the ISO label for ``mark`` and search for an exact
          match — if present, return its index.
        * Otherwise compare ISO labels lexicographically (they are
          zero-padded ``YYYY-Www`` strings, so lexical == temporal).
          Find the gap and return the midpoint of the surrounding
          indices.
        * Out-of-range to the left → 0; out-of-range to the right →
          ``len(rows) - 1``. The caller is responsible for any
          additional clamping if desired.
    """
    if not rows:
        return 0.0
    target = _iso_week_label_for_date(mark)
    labels = [r.week for r in rows]
    if target in labels:
        return float(labels.index(target))
    # Find insertion point against sorted ISO labels (already sorted by
    # construction in bucket_by_iso_week).
    for i, label in enumerate(labels):
        if target < label:
            if i == 0:
                return 0.0
            return float(i - 1) + 0.5
    return float(len(labels) - 1)


def plot_velocity(
    rows: Sequence[VelocityRow],
    output: Path,
    *,
    mark_date: date | None = None,
    title: str = "Development Velocity",
) -> None:
    """Render a 3-panel velocity figure to ``output``.

    Args:
        rows: Per-week :class:`VelocityRow` values, in ISO-week order.
            Totals rows (``week == "Total"``) must be filtered out by
            the caller — this function plots every row as a bar.
        output: Destination path. The suffix must be one of
            ``.png`` / ``.svg`` / ``.pdf``; any other suffix raises
            ``ValueError``.
        mark_date: Optional calendar date to highlight with a vertical
            line across every panel.
        title: Figure suptitle. Default ``"Development Velocity"``.

    Raises:
        ValueError: If ``rows`` is empty, or if ``output`` has an
            unsupported file extension.
        ImportError: If matplotlib is not installed. The CLI wrapper
            catches this and presents a friendlier hint about the
            ``[charts]`` extra.
    """
    if not rows:
        raise ValueError("no data to chart")

    suffix = output.suffix.lower()
    if suffix not in _SUPPORTED_EXTS:
        raise ValueError(
            f"unsupported output extension {suffix!r}; "
            f"expected one of {sorted(_SUPPORTED_EXTS)}"
        )

    # Lazy matplotlib import — see module docstring (AC-7).
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    weeks = [r.week for r in rows]
    x = list(range(len(rows)))

    prs_merged = [r.prs_merged for r in rows]
    lines_added = [r.lines_added or 0 for r in rows]
    # Diverging: removed lines plotted on the negative axis.
    lines_removed_neg = [-(r.lines_removed or 0) for r in rows]

    # Words/LOC ratio: mask out None so the line breaks across gaps
    # rather than connecting through a fake zero.
    ratio_x: list[int] = []
    ratio_y: list[float] = []
    for xi, row in zip(x, rows):
        if row.words_per_loc is not None:
            ratio_x.append(xi)
            ratio_y.append(row.words_per_loc)

    fig, (ax_prs, ax_loc, ax_ratio) = plt.subplots(
        3,
        1,
        figsize=(max(8, 0.6 * len(rows) + 4), 9),
        sharex=True,
    )

    # Panel 1 — PR counts.
    ax_prs.bar(x, prs_merged, color="#1f77b4")
    ax_prs.set_ylabel("PRs merged")
    ax_prs.grid(True, axis="y", linestyle=":", alpha=0.4)

    # Panel 2 — Diverging LOC bars (added above zero, removed below).
    ax_loc.bar(x, lines_added, color="#2ca02c", alpha=0.7, label="+Lines")
    ax_loc.bar(x, lines_removed_neg, color="#d62728", alpha=0.7, label="-Lines")
    ax_loc.axhline(0, color="black", linewidth=0.6)
    ax_loc.set_ylabel("Lines changed")
    ax_loc.grid(True, axis="y", linestyle=":", alpha=0.4)
    ax_loc.legend(loc="upper right", fontsize="small")

    # Panel 3 — Words/LOC ratio (line + markers, gaps for None).
    ax_ratio.plot(ratio_x, ratio_y, marker="o", color="#9467bd")
    ax_ratio.set_ylabel("Words / LOC")
    ax_ratio.set_xlabel("ISO week")
    ax_ratio.grid(True, axis="y", linestyle=":", alpha=0.4)

    # Mark-date vertical lines on every panel.
    if mark_date is not None:
        x_mark = _mark_date_x_position(rows, mark_date)
        for ax in (ax_prs, ax_loc, ax_ratio):
            ax.axvline(
                x_mark,
                color="black",
                linestyle="--",
                linewidth=1.0,
                alpha=0.7,
            )

    # Shared x-axis: ISO week labels rotated 45° right-aligned.
    ax_ratio.set_xticks(x)
    ax_ratio.set_xticklabels(weeks, rotation=45, ha="right")

    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    # Raster vs vector save knobs. matplotlib infers format from the
    # extension; we still pass it explicitly so the contract is clear.
    save_kwargs: dict = {"bbox_inches": "tight", "format": suffix.lstrip(".")}
    if suffix == ".png":
        save_kwargs["dpi"] = 300
    fig.savefig(output, **save_kwargs)
    plt.close(fig)


__all__ = ["plot_velocity"]
