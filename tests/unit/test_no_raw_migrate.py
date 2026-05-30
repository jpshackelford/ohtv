"""Regression test: production code must not call ``migrate(conn)`` directly.

Issue #116 centralizes the migration entry point through
``ohtv.db.get_ready_connection``. Every production call site under
``src/ohtv/`` should funnel through that helper so the AGENTS.md item #25
"automatic maintenance" promise holds for every command.

This test greps ``src/ohtv/`` for ``migrate(conn)`` and fails if any new
call site lands outside the allow-list. It is the floor of the regression
prevention strategy described in the issue.

Allow-listed sites:

* ``src/ohtv/db/maintenance.py`` — the canonical wrapper itself calls
  ``migrate(conn)``.
* ``src/ohtv/cli.py`` — the ``db init`` command uses the return value of
  ``migrate(conn)`` to print the list of newly-applied migration names to
  the user. This is explicit user-facing behavior that
  ``get_ready_connection`` does not surface.
* ``src/ohtv/db/connection.py`` — the ``get_ready_connection`` docstring
  includes ``migrate(conn)`` as an *example* of the pattern callers should
  no longer write. It is comment text, not a real call.
"""

from __future__ import annotations

import re
from pathlib import Path

# Pattern matches calls of the form ``migrate(conn)`` and
# ``applied = migrate(conn)``. The negative lookbehind for ``def `` skips
# the function *definition* in ``src/ohtv/db/migrations/__init__.py``.
MIGRATE_CALL_RE = re.compile(r"(?<!def )\bmigrate\(conn\b")

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "ohtv"


def _expected_paths() -> dict[Path, str]:
    """Allow-listed call sites with the reason each is exempt."""
    return {
        SRC_ROOT
        / "db"
        / "maintenance.py": "canonical wrapper (ensure_db_ready) itself",
        SRC_ROOT
        / "db"
        / "connection.py": "docstring example for get_ready_connection",
        SRC_ROOT
        / "cli.py": "db init command surfaces applied migration list to user",
    }


def _gather_raw_migrate_call_sites() -> list[tuple[Path, int, str]]:
    """Return a list of (path, lineno, line) tuples for every raw migrate(conn) call."""
    hits: list[tuple[Path, int, str]] = []
    for py_path in SRC_ROOT.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Strip comments only for matching: we want to allow a literal
            # ``# migrate(conn)`` in commentary if a contributor ever wants to
            # document the old pattern. The regex still needs to match the
            # bare token though.
            stripped = line.split("#", 1)[0]
            if MIGRATE_CALL_RE.search(stripped):
                hits.append((py_path, lineno, line.rstrip()))
    return hits


def test_no_raw_migrate_in_production_code() -> None:
    """Production sources must not call ``migrate(conn)`` outside the allow-list.

    If you're adding a new entry point that touches the SQLite index, use
    ``ohtv.db.get_ready_connection()`` instead of opening a raw connection
    and calling ``migrate(conn)``. See AGENTS.md item #25 and issue #116
    for the rationale.
    """
    allowed = _expected_paths()
    violations: list[str] = []
    for path, lineno, line in _gather_raw_migrate_call_sites():
        if path in allowed:
            continue
        rel = path.relative_to(REPO_ROOT)
        violations.append(f"  {rel}:{lineno}: {line}")

    if violations:
        allow_list = "\n".join(
            f"  - {p.relative_to(REPO_ROOT)}: {reason}"
            for p, reason in allowed.items()
        )
        raise AssertionError(
            "Found raw migrate(conn) call(s) outside the allow-list. "
            "Use ohtv.db.get_ready_connection() instead. See issue #116.\n\n"
            "Violations:\n"
            + "\n".join(violations)
            + "\n\nAllow-listed sites:\n"
            + allow_list
        )


def test_allow_listed_files_still_call_migrate() -> None:
    """Sanity check: the allow-list itself should still be live.

    If one of the allow-listed files stops calling ``migrate(conn)``
    (because the function was moved or deleted), the allow-list entry is
    dead and should be removed. Otherwise the regression test silently
    over-allows.
    """
    raw_sites_by_path: dict[Path, int] = {}
    for path, _, _ in _gather_raw_migrate_call_sites():
        raw_sites_by_path[path] = raw_sites_by_path.get(path, 0) + 1

    for allowed_path in _expected_paths():
        assert allowed_path in raw_sites_by_path, (
            f"Allow-listed file {allowed_path.relative_to(REPO_ROOT)} no longer "
            "contains a migrate(conn) call. Remove it from the allow-list in "
            "this test."
        )
