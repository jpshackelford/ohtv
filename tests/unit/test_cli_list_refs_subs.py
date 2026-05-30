"""Issue #127 regression tests for ``ohtv list`` / ``ohtv refs``
roots-only default and subtree rollup.

These tests cover the five acceptance criteria from the issue:

* T-1: 1-root + 1-sub, sub has a PR ref the root doesn't —
  ``list --pr X`` surfaces the root row, ``refs <root-id>`` includes
  the sub's ref.
* T-2: multi-sub-same-root — three subs touch three different PRs;
  each ``list --pr PR_n`` resolves to the same single root row.
* T-3: ``--include-sub-conversations`` opt-in restores per-conv
  rendering; the filter set is NOT root-expanded.
* T-4: ``refs <sub-id>`` direct query unchanged.
* T-5: pre-migration-020 invocation raises a friendly ``RuntimeError``.

Implementation notes:

* DB shape matches migration 020: ``conversations`` rows carry
  ``root_conversation_id`` (orphans = self-rooted). Tests mock the
  filesystem-touching helpers so we don't need real event JSON.
* IDs are dashless 32-char hex per AGENTS.md item #14.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from ohtv.cli import (
    _filter_by_pr,
    _resolve_refs_subtree,
    main,
)
from ohtv.db import migrate


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _fake_conv(conv_id: str, *, title: str = "Test", source: str = "cloud"):
    """Build a ConversationInfo-shaped MagicMock."""
    m = MagicMock()
    m.id = conv_id
    m.short_id = conv_id[:7]
    m.lookup_id = conv_id
    m.title = title
    m.source = source
    m.created_at = datetime.now(timezone.utc)
    m.event_count = 5
    return m


def _seed_root_with_subs(conn, root_id: str, sub_ids: list[str]) -> None:
    """Insert a (root, *subs) tree into ``conversations``."""
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, source, root_conversation_id, event_count) "
        "VALUES (?, ?, 'cloud', ?, 5)",
        (root_id, f"/tmp/{root_id}", root_id),
    )
    for sub_id in sub_ids:
        conn.execute(
            "INSERT INTO conversations "
            "(id, location, source, parent_conversation_id, "
            "root_conversation_id, event_count) "
            "VALUES (?, ?, 'cloud', ?, ?, 5)",
            (sub_id, f"/tmp/{sub_id}", root_id, root_id),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# T-1 / T-2 / T-3 — _filter_by_pr root-expands the matching id set
# ---------------------------------------------------------------------------


class TestFilterByPrRootExpansion:
    """``_filter_by_pr`` should route PR matches that resolve to a sub
    back to that sub's root row when ``include_subs=False``.

    The four ``_filter_by_*`` helpers in ``cli.py`` share the same
    lookup → ``expand_to_roots`` → reduce shape, so testing PR covers
    the common path. The dedicated ``expand_to_roots`` unit tests
    (``tests/unit/test_filters.py::TestExpandToRoots``) cover the
    lower-level mapping.
    """

    def test_t1_sub_pr_match_surfaces_root(self, monkeypatch, tmp_path):
        """T-1: sub has a PR ref the root doesn't — ``list --pr X``
        surfaces the *root* row when ``include_subs`` is False."""
        root_id = "r" + "0" * 31
        sub_id = "s" + "0" * 31

        # Real on-disk DB so ``get_connection`` (which expects
        # OHTV_DIR/index.db) can open it.
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_connection, get_db_path

        # Bootstrap the schema and seed the tree.
        with get_connection() as conn:
            migrate(conn)
            _seed_root_with_subs(conn, root_id, [sub_id])

        assert get_db_path().exists()

        # Lookup returns only the sub id (PR attribution lives on the
        # delegated worker). Conversations list contains only the root,
        # mirroring what the SELECT-layer roots-only predicate would do.
        monkeypatch.setattr(
            "ohtv.filters.get_conversation_ids_for_pr",
            lambda _f: ({sub_id}, ["owner/repo#42"]),
        )

        conversations = [_fake_conv(root_id)]
        result = _filter_by_pr(conversations, "owner/repo#42", include_subs=False)

        assert [c.id for c in result] == [root_id]

    def test_t2_three_subs_same_root_all_surface_one_row(
        self, monkeypatch, tmp_path
    ):
        """T-2: three subs of the same root each touch a different PR;
        each ``--pr PR_n`` resolves to the same single root row."""
        root_id = "r" + "1" * 31
        sub_a = "a" + "1" * 31
        sub_b = "b" + "1" * 31
        sub_c = "c" + "1" * 31

        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_connection

        with get_connection() as conn:
            migrate(conn)
            _seed_root_with_subs(conn, root_id, [sub_a, sub_b, sub_c])

        conversations = [_fake_conv(root_id)]

        # Each PR lookup returns a different sub id.
        for sub in (sub_a, sub_b, sub_c):
            monkeypatch.setattr(
                "ohtv.filters.get_conversation_ids_for_pr",
                lambda _f, s=sub: ({s}, ["owner/repo#X"]),
            )
            result = _filter_by_pr(
                conversations, "owner/repo#X", include_subs=False
            )
            assert [c.id for c in result] == [root_id], (
                f"sub {sub} should expand to root {root_id}"
            )

    def test_t3_include_subs_skips_root_expansion(self, monkeypatch, tmp_path):
        """T-3: with ``include_subs=True`` the raw lookup set is used
        verbatim — no root expansion happens. A PR attributed to a sub
        only resolves to the sub row, not the root row."""
        root_id = "r" + "2" * 31
        sub_id = "s" + "2" * 31

        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_connection

        with get_connection() as conn:
            migrate(conn)
            _seed_root_with_subs(conn, root_id, [sub_id])

        monkeypatch.setattr(
            "ohtv.filters.get_conversation_ids_for_pr",
            lambda _f: ({sub_id}, ["owner/repo#42"]),
        )

        # When include_subs=True, the conversation list contains BOTH
        # root and sub (mirroring pre-#127 SELECT behavior). With root
        # expansion OFF, only the sub matches the raw id set.
        conversations = [_fake_conv(root_id), _fake_conv(sub_id)]
        result = _filter_by_pr(conversations, "owner/repo#42", include_subs=True)

        assert [c.id for c in result] == [sub_id], (
            "include_subs=True must NOT root-expand the filter id set"
        )


# ---------------------------------------------------------------------------
# T-1 (cont'd) — refs <root-id> rolls up subtree refs
# ---------------------------------------------------------------------------


class TestRefsSubtreeRollup:
    """``ohtv refs <root-id>`` must aggregate refs across every sub in
    the delegation tree (Issue #127's AC: "refs <root-id> includes the
    sub's ref"). The actual subtree resolution is tested directly on
    ``_resolve_refs_subtree`` so we don't need to construct real event
    JSON.
    """

    def test_root_resolves_to_full_subtree(self, monkeypatch, tmp_path):
        root_id = "r" + "3" * 31
        sub_a = "a" + "3" * 31
        sub_b = "b" + "3" * 31

        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_connection

        with get_connection() as conn:
            migrate(conn)
            _seed_root_with_subs(conn, root_id, [sub_a, sub_b])

        is_root, subtree_ids = _resolve_refs_subtree(root_id)

        assert is_root is True
        # Root first, then subs in id order.
        assert subtree_ids[0] == root_id
        assert set(subtree_ids[1:]) == {sub_a, sub_b}
        assert len(subtree_ids) == 3

    # -----------------------------------------------------------------
    # T-4 — refs <sub-id> direct single-conv path is unchanged
    # -----------------------------------------------------------------

    def test_t4_sub_id_returns_single_conv_path(self, monkeypatch, tmp_path):
        """``refs <sub-id>`` must NOT cross-pollinate into the root's
        view; the user explicitly asked for that sub."""
        root_id = "r" + "4" * 31
        sub_id = "s" + "4" * 31

        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_connection

        with get_connection() as conn:
            migrate(conn)
            _seed_root_with_subs(conn, root_id, [sub_id])

        is_root, subtree_ids = _resolve_refs_subtree(sub_id)

        assert is_root is False
        assert subtree_ids == [sub_id], (
            "refs <sub-id> must preserve single-conv behavior"
        )

    def test_root_with_no_subs_behaves_as_single_conv(
        self, monkeypatch, tmp_path
    ):
        """A root with no delegated subs is the degenerate single-conv
        case — the rollup branch should NOT fire for it."""
        root_id = "r" + "5" * 31

        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_connection

        with get_connection() as conn:
            migrate(conn)
            _seed_root_with_subs(conn, root_id, [])

        is_root, subtree_ids = _resolve_refs_subtree(root_id)

        assert is_root is True
        assert subtree_ids == [root_id]


# ---------------------------------------------------------------------------
# T-5 — pre-migration-020 invocation raises friendly RuntimeError
# ---------------------------------------------------------------------------


class TestMigration020Guardrail:
    """The cluster shared a guardrail pattern (#123/#124/#125): when
    ``root_conversation_id`` is absent, callers raise a ``RuntimeError``
    with command-aware wording. Issue #127 surfaces this guard for
    ``ohtv refs <root-id>`` (the new subtree-rollup code path) and
    reuses the existing store-level guard for ``ohtv list``.
    """

    def _make_pre_020_db(self, db_path: Path) -> None:
        """Build a minimal pre-migration-020 ``conversations`` table.

        We can't simply run ``migrate(conn)`` and then drop the column
        (SQLite < 3.35 lacks DROP COLUMN), so we hand-roll the legacy
        schema with just the columns that pre-020 callers expect.
        """
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE conversations ("
            "id TEXT PRIMARY KEY, "
            "location TEXT, "
            "source TEXT, "
            "event_count INTEGER DEFAULT 0"
            ")"
        )
        conn.execute(
            "INSERT INTO conversations (id, location, source) "
            "VALUES ('legacyconv', '/tmp/legacy', 'cloud')"
        )
        conn.commit()
        conn.close()

    def test_t5_refs_resolve_subtree_raises_pre_020(
        self, monkeypatch, tmp_path
    ):
        """``_resolve_refs_subtree`` must raise the friendly
        ``RuntimeError`` when the column is absent."""
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))
        from ohtv.db import get_db_path

        # Build a pre-migration-020 DB at the path ``get_db_path``
        # returns.
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._make_pre_020_db(db_path)

        with pytest.raises(RuntimeError, match="migration 020"):
            _resolve_refs_subtree("legacyconv")

    def test_t5_list_by_date_range_raises_pre_020(self):
        """The store-level guard (landed in #125 / PR #154) must also
        fire on a pre-020 DB. Issue #127 relies on this for the
        ``ohtv list`` path."""
        from ohtv.db.stores import ConversationStore

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE conversations ("
            "id TEXT PRIMARY KEY, "
            "location TEXT, "
            "source TEXT, "
            "event_count INTEGER DEFAULT 0, "
            "created_at TEXT"
            ")"
        )
        store = ConversationStore(conn)

        with pytest.raises(RuntimeError, match="migration 020"):
            store.list_by_date_range(include_subs=False)

    def test_no_db_falls_through_gracefully(self, monkeypatch, tmp_path):
        """When the DB doesn't exist yet (fresh install), the subtree
        helper should NOT raise — it falls back to single-conv
        behavior so ``refs <id>`` still works on a fresh checkout."""
        # Empty tmp_path → no DB file
        monkeypatch.setenv("OHTV_DIR", str(tmp_path))

        is_root, subtree_ids = _resolve_refs_subtree("anyid000")

        assert is_root is True
        assert subtree_ids == ["anyid000"]


# ---------------------------------------------------------------------------
# CLI option surface — both commands accept --include-sub-conversations
# ---------------------------------------------------------------------------


class TestCliOptionSurface:
    """Smoke tests that the ``--include-sub-conversations`` flag is
    wired into both Click commands. The behavioural tests above cover
    the actual effect; this just guards against accidental removal."""

    def test_list_help_advertises_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list", "--help"])
        assert result.exit_code == 0
        assert "--include-sub-conversations" in result.output

    def test_refs_help_advertises_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["refs", "--help"])
        assert result.exit_code == 0
        assert "--include-sub-conversations" in result.output
