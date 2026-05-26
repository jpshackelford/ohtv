"""Lint guard: only ``src/ohtv/progress.py`` may import from ``rich.progress``.

This prevents drift back to the pre-#91 pattern of duplicating Rich
progress-bar layouts at the call site. All other call sites must use the
shared :func:`ohtv.progress.make_progress` helper.
"""

from __future__ import annotations

from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ohtv"
ALLOW_LIST = {SRC_ROOT / "progress.py"}


def test_only_progress_module_imports_rich_progress():
    offenders: list[str] = []
    for py_path in SRC_ROOT.rglob("*.py"):
        if py_path in ALLOW_LIST:
            continue
        text = py_path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("from rich.progress import") or stripped.startswith(
                "import rich.progress"
            ):
                offenders.append(f"{py_path.relative_to(SRC_ROOT.parent)}:{lineno}: {stripped}")

    assert not offenders, (
        "Direct `rich.progress` imports outside `ohtv.progress` are forbidden. "
        "Use `ohtv.progress.make_progress(...)` instead.\nOffenders:\n  "
        + "\n  ".join(offenders)
    )
