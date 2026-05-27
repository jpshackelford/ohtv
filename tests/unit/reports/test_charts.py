"""Unit tests for :mod:`ohtv.reports.charts` (issue #82).

No pixel-diff snapshots. Tests assert on:

* The file being written (magic bytes / non-empty).
* The data passed to matplotlib's ``bar`` / ``plot`` / ``axvline`` —
  patched at the ``Axes`` class level so we capture every call.
* Lazy-import contract — ``import ohtv.reports.charts`` does not pull
  in matplotlib at module load.

All tests run under ``matplotlib.use("Agg")`` (the production code
calls it; the conftest in this directory ensures it's set globally
too).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from ohtv.reports.charts import plot_velocity
from ohtv.reports.velocity import VelocityRow


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _agg_backend() -> None:
    """Force the Agg backend for every chart test (headless CI)."""
    import matplotlib

    matplotlib.use("Agg")


def _rows() -> list[VelocityRow]:
    return [
        VelocityRow(
            week="2024-W10",
            prs_merged=3,
            lines_added=200,
            lines_removed=50,
            total_loc=150,
            human_words=300,
            human_messages=12,
            words_per_loc=2.0,
        ),
        VelocityRow(
            week="2024-W11",
            prs_merged=5,
            lines_added=500,
            lines_removed=100,
            total_loc=400,
            human_words=800,
            human_messages=20,
            words_per_loc=2.0,
        ),
        VelocityRow(
            week="2024-W12",
            prs_merged=1,
            lines_added=10,
            lines_removed=10,
            total_loc=0,
            human_words=20,
            human_messages=2,
            words_per_loc=None,  # zero LOC → ratio undefined
        ),
    ]


# ---------------------------------------------------------------------------
# T-1 / T-2 / T-3: extension-driven format, file is written with correct
# magic bytes.
# ---------------------------------------------------------------------------


def test_plot_velocity_writes_png(tmp_path: Path) -> None:
    out = tmp_path / "velocity.png"
    plot_velocity(_rows(), out)
    assert out.exists()
    assert out.stat().st_size > 0
    with open(out, "rb") as f:
        assert f.read(4) == b"\x89PNG"


def test_plot_velocity_writes_svg(tmp_path: Path) -> None:
    out = tmp_path / "velocity.svg"
    plot_velocity(_rows(), out)
    assert out.exists()
    head = out.read_bytes()[:200]
    assert b"<?xml" in head or b"<svg" in head


def test_plot_velocity_writes_pdf(tmp_path: Path) -> None:
    out = tmp_path / "velocity.pdf"
    plot_velocity(_rows(), out)
    assert out.exists()
    with open(out, "rb") as f:
        assert f.read(5) == b"%PDF-"


# ---------------------------------------------------------------------------
# T-4: mark_date draws axvline on every panel.
# ---------------------------------------------------------------------------


def test_mark_date_drawn_on_all_panels(tmp_path: Path) -> None:
    from matplotlib.axes import Axes

    with patch.object(Axes, "axvline", autospec=True) as axvline:
        plot_velocity(_rows(), tmp_path / "v.png", mark_date=date(2024, 3, 11))

    # 3 panels × 1 mark_date line = 3 calls.
    panel_calls = [c for c in axvline.call_args_list if c.kwargs.get("linestyle") == "--"]
    assert len(panel_calls) == 3, axvline.call_args_list


def test_mark_date_omitted_no_axvline_dashed(tmp_path: Path) -> None:
    """Without mark_date, no dashed reference line is drawn.

    Panel 2 also calls ``axhline(0, ...)`` for the diverging-bar zero
    baseline — that's a horizontal line, not vertical, and uses
    ``axhline``, so it does not show up in ``axvline`` patches.
    """
    from matplotlib.axes import Axes

    with patch.object(Axes, "axvline", autospec=True) as axvline:
        plot_velocity(_rows(), tmp_path / "v.png")

    panel_calls = [c for c in axvline.call_args_list if c.kwargs.get("linestyle") == "--"]
    assert panel_calls == []


# ---------------------------------------------------------------------------
# T-5: words_per_loc is None on at least one row → no TypeError, gap in
# the line plot.
# ---------------------------------------------------------------------------


def test_words_per_loc_skips_none(tmp_path: Path) -> None:
    from matplotlib.axes import Axes

    with patch.object(Axes, "plot", autospec=True) as plot_calls:
        plot_velocity(_rows(), tmp_path / "v.png")

    # Find the call that received the ratio line. Our module calls
    # ``ax.plot(x_list, y_list, marker="o", ...)`` exactly once.
    ratio_calls = [c for c in plot_calls.call_args_list if c.kwargs.get("marker") == "o"]
    assert len(ratio_calls) == 1, plot_calls.call_args_list
    call = ratio_calls[0]
    # call.args is (self, x, y) thanks to autospec=True.
    _self, x_data, y_data = call.args[0], call.args[1], call.args[2]
    # The third row has ratio=None → dropped from both lists.
    assert len(x_data) == 2
    assert len(y_data) == 2
    assert all(v is not None for v in y_data)


# ---------------------------------------------------------------------------
# T-6: empty rows raises ValueError.
# ---------------------------------------------------------------------------


def test_empty_rows_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no data to chart"):
        plot_velocity([], tmp_path / "v.png")


# ---------------------------------------------------------------------------
# T-7: extension drives format / unknown extension rejected.
# ---------------------------------------------------------------------------


def test_unknown_extension_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported output extension"):
        plot_velocity(_rows(), tmp_path / "velocity.jpg")


def test_extension_passed_to_savefig(tmp_path: Path) -> None:
    """The supplied ``format=`` kwarg matches the extension."""
    from matplotlib.figure import Figure

    captured: dict = {}

    real_savefig = Figure.savefig

    def fake_savefig(self, fname, **kwargs):
        captured["fname"] = str(fname)
        captured["format"] = kwargs.get("format")
        captured["bbox_inches"] = kwargs.get("bbox_inches")
        captured["dpi"] = kwargs.get("dpi")
        return real_savefig(self, fname, **kwargs)

    with patch.object(Figure, "savefig", fake_savefig):
        plot_velocity(_rows(), tmp_path / "v.png")
    assert captured["format"] == "png"
    assert captured["bbox_inches"] == "tight"
    assert captured["dpi"] == 300

    with patch.object(Figure, "savefig", fake_savefig):
        plot_velocity(_rows(), tmp_path / "v.svg")
    assert captured["format"] == "svg"
    # No DPI for vector formats.
    assert captured["dpi"] is None


# ---------------------------------------------------------------------------
# Lazy import contract (AC-7).
# ---------------------------------------------------------------------------


def test_import_charts_does_not_pull_in_matplotlib() -> None:
    """``import ohtv.reports.charts`` itself does not import matplotlib.

    We verify this by reloading the module after evicting matplotlib
    from ``sys.modules``: the reload itself must not raise even with
    a synthetic ``ImportError`` for matplotlib's loader.
    """
    import importlib

    saved = {k: sys.modules[k] for k in list(sys.modules) if k.startswith("matplotlib")}
    try:
        for k in list(saved):
            del sys.modules[k]
        # Block matplotlib at import time.
        sys.modules["matplotlib"] = None  # type: ignore[assignment]
        importlib.reload(importlib.import_module("ohtv.reports.charts"))
    finally:
        sys.modules.pop("matplotlib", None)
        sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Bar-call snapshot test (AC-9): assert the data passed to Axes.bar.
# ---------------------------------------------------------------------------


def test_bar_calls_receive_expected_pr_counts(tmp_path: Path) -> None:
    from matplotlib.axes import Axes

    with patch.object(Axes, "bar", autospec=True) as bar:
        plot_velocity(_rows(), tmp_path / "v.png")

    # First bar call is panel 1 (PR counts).
    first = bar.call_args_list[0]
    _self, x, heights = first.args[0], first.args[1], first.args[2]
    assert list(x) == [0, 1, 2]
    assert list(heights) == [3, 5, 1]

    # Panel 2 has two bar calls: lines_added and -lines_removed.
    second = bar.call_args_list[1]
    third = bar.call_args_list[2]
    assert list(second.args[2]) == [200, 500, 10]
    assert list(third.args[2]) == [-50, -100, -10]

    # Panel 1 PR-counts bar MUST NOT receive a per-row hatch kwarg
    # (hatching is reserved for the Panel 2 partial_loc indicator,
    # issue #103). A solid PR bar is the intentional default.
    assert "hatch" not in first.kwargs


def test_partial_loc_bars_carry_hatch_marker(tmp_path: Path) -> None:
    """Panel 2 LOC bars carry per-row ``hatch=`` driven by ``partial_loc``.

    Mirrors :func:`test_bar_calls_receive_expected_pr_counts` — patches
    ``Axes.bar`` and inspects the kwargs of the two Panel 2 calls (indices
    1 and 2). The Panel 1 PR-counts call (index 0) must still NOT receive
    a ``hatch=`` kwarg.

    Regression guard for issue #103.
    """
    from matplotlib.axes import Axes

    rows = [
        VelocityRow(
            week="2024-W01",
            prs_merged=2,
            lines_added=200,
            lines_removed=50,
            total_loc=150,
            human_words=300,
            human_messages=10,
            words_per_loc=2.0,
            partial_loc=False,
        ),
        VelocityRow(
            week="2024-W02",
            prs_merged=3,
            lines_added=500,
            lines_removed=100,
            total_loc=400,
            human_words=800,
            human_messages=20,
            words_per_loc=2.0,
            partial_loc=True,
        ),
        VelocityRow(
            week="2024-W03",
            prs_merged=1,
            lines_added=None,
            lines_removed=None,
            total_loc=None,
            human_words=50,
            human_messages=4,
            words_per_loc=None,
            partial_loc=True,
        ),
    ]
    with patch.object(Axes, "bar", autospec=True) as bar:
        plot_velocity(rows, tmp_path / "v.png")

    # Panel 2 bar calls are indices 1 (+lines) and 2 (-lines).
    for call in (bar.call_args_list[1], bar.call_args_list[2]):
        assert call.kwargs["hatch"] == [None, "///", "///"]

    # Negative control: Panel 1 (PR counts) must stay un-hatched.
    assert "hatch" not in bar.call_args_list[0].kwargs
