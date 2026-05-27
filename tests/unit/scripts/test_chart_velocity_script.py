"""Tests for ``scripts/chart_velocity.py`` (issue #82).

The script accepts CSV via stdin or a positional file argument and
calls the same ``plot_velocity`` entry point as the CLI. We exercise
both code paths.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest


_CSV_TEXT = (
    "week,prs_merged,lines_added,lines_removed,total_loc,human_words,human_messages,words_per_loc\n"
    "2024-W10,3,200,50,150,300,12,2.00\n"
    "2024-W11,5,500,100,400,800,20,2.00\n"
    "2024-W12,1,10,10,0,20,2,\n"  # blank words_per_loc → None
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "chart_velocity.py"


@pytest.fixture(autouse=True)
def _agg_backend() -> None:
    import matplotlib

    matplotlib.use("Agg")


# ---------------------------------------------------------------------------
# S-1: CSV path argument.
# ---------------------------------------------------------------------------


def test_script_reads_csv_from_file(tmp_path: Path) -> None:
    csv_path = tmp_path / "velocity.csv"
    csv_path.write_text(_CSV_TEXT)
    out = tmp_path / "v.png"

    # Run the script via subprocess so we test the actual CLI surface,
    # not its main() return.
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), str(csv_path), "--output", str(out)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes()[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# S-2: CSV piped via stdin.
# ---------------------------------------------------------------------------


def test_script_reads_csv_from_stdin(tmp_path: Path) -> None:
    out = tmp_path / "v_stdin.svg"

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--output", str(out)],
        capture_output=True,
        text=True,
        input=_CSV_TEXT,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    head = out.read_bytes()[:200]
    assert b"<?xml" in head or b"<svg" in head


# ---------------------------------------------------------------------------
# Direct main() entry — exercise mark-date plumbing without subprocess.
# ---------------------------------------------------------------------------


def test_script_main_handles_mark_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "v.png"
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(_CSV_TEXT)

    # Insert the repo root on sys.path for the package import.
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from scripts.chart_velocity import main
        rc = main([str(csv_path), "--output", str(out), "--mark-date", "2024-03-11", "--title", "T"])
        assert rc == 0
        assert out.exists()
    finally:
        sys.path.remove(str(_REPO_ROOT))


def test_script_main_empty_csv(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Empty CSV input → exit 0, no file written, stderr hint."""
    out = tmp_path / "v.png"
    csv_path = tmp_path / "empty.csv"
    # Header-only CSV.
    csv_path.write_text(
        "week,prs_merged,lines_added,lines_removed,total_loc,"
        "human_words,human_messages,words_per_loc\n"
    )

    sys.path.insert(0, str(_REPO_ROOT))
    try:
        # We capture stderr by redirecting sys.stderr to avoid pytest's
        # capture cleverness with subprocess-free entry.
        from scripts.chart_velocity import main

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            rc = main([str(csv_path), "--output", str(out)])
        finally:
            err = sys.stderr.getvalue()
            sys.stderr = old_stderr
        assert rc == 0
        assert not out.exists()
        assert "No data" in err
    finally:
        sys.path.remove(str(_REPO_ROOT))
