"""Issue #128 — ``ohtv ask`` / ``ohtv search`` citation root-dedup.

The render-layer dedup collapses chunks from delegated sub-conversations
to their root so users see one citation per user-intent unit. These
tests cover:

* ``_dedup_search_results_by_root`` (CLI helper): MAX-score policy,
  rank re-numbering, limit truncation, no backfill, standalone
  passthrough.
* ``_display_retrieval_breakdown``: shows both grains (chunk-level
  conv id + rolled-up root id) when chunks come from delegated subs.

Tests use an in-memory SQLite DB seeded with rows matching migration
020 (every row carries ``root_conversation_id``). The DB is wrapped in
a lightweight ``conv_store`` stand-in that only exposes ``.conn``,
which is all the helper needs.

Cross-references:
* Helper: :func:`ohtv.cli._dedup_search_results_by_root`
* AC closing checkbox: 1 root + 2 subs + 1 standalone → 2 rendered rows.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ohtv.cli import (
    _SearchResultRow,
    _dedup_search_results_by_root,
    _display_retrieval_breakdown,
)
from ohtv.db import migrate


@pytest.fixture
def db_conn():
    """In-memory DB with the full ohtv schema (incl. migration 020)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def _seed_tree(db_conn, root_id: str, sub_ids: list[str]) -> None:
    """Seed a (root, *subs) tree in ``conversations``."""
    db_conn.execute(
        "INSERT INTO conversations (id, location, source, root_conversation_id) "
        "VALUES (?, ?, 'cloud', ?)",
        (root_id, f"/tmp/{root_id}", root_id),
    )
    for sub_id in sub_ids:
        db_conn.execute(
            "INSERT INTO conversations "
            "(id, location, source, parent_conversation_id, root_conversation_id) "
            "VALUES (?, ?, 'cloud', ?, ?)",
            (sub_id, f"/tmp/{sub_id}", root_id, root_id),
        )
    db_conn.commit()


def _seed_standalone(db_conn, conv_id: str) -> None:
    """Seed a standalone (self-rooted) conversation."""
    db_conn.execute(
        "INSERT INTO conversations (id, location, source, root_conversation_id) "
        "VALUES (?, ?, 'cloud', ?)",
        (conv_id, f"/tmp/{conv_id}", conv_id),
    )
    db_conn.commit()


def _make_conv_store(db_conn):
    """Wrap a sqlite conn as a minimal conv_store surface."""
    store = MagicMock()
    store.conn = db_conn
    return store


# ---------------------------------------------------------------------------
# _dedup_search_results_by_root
# ---------------------------------------------------------------------------


class TestDedupSearchResultsByRoot:
    """The CLI search-result dedup helper. Walks pre-sorted input,
    keeps first-occurrence per root (MAX policy), rewrites
    conversation_id to root id, re-ranks, truncates to limit."""

    def test_empty_input_returns_empty(self, db_conn):
        store = _make_conv_store(db_conn)
        assert _dedup_search_results_by_root([], store, limit=10) == []

    def test_standalone_passes_through(self, db_conn):
        """Standalone conversations are returned unchanged (root == id)."""
        _seed_standalone(db_conn, "stand1")
        results = [
            _SearchResultRow(conversation_id="stand1", score=0.9, rank=1, best_match_type="analysis"),
        ]
        out = _dedup_search_results_by_root(results, _make_conv_store(db_conn), limit=10)
        assert len(out) == 1
        assert out[0].conversation_id == "stand1"
        assert out[0].rank == 1
        assert out[0].score == 0.9

    def test_subtree_collapses_to_one_row_max_score(self, db_conn):
        """1 root + 2 subs (sorted score desc) → 1 row with MAX score."""
        _seed_tree(db_conn, "rootA", ["subA1", "subA2"])
        # Input sorted by score desc.
        results = [
            _SearchResultRow(conversation_id="subA1", score=0.95, rank=1, best_match_type="analysis"),
            _SearchResultRow(conversation_id="rootA", score=0.85, rank=2, best_match_type="summary"),
            _SearchResultRow(conversation_id="subA2", score=0.72, rank=3, best_match_type="content"),
        ]
        out = _dedup_search_results_by_root(results, _make_conv_store(db_conn), limit=10)
        assert len(out) == 1
        # ID is rewritten to the root (so display shows familiar id).
        assert out[0].conversation_id == "rootA"
        # MAX score wins (first occurrence by virtue of pre-sorted input).
        assert out[0].score == 0.95
        # Source-text / best_match_type stay at max-scoring chunk's
        # values — the snippet under that chunk is what gets shown.
        assert out[0].best_match_type == "analysis"
        assert out[0].rank == 1

    def test_two_distinct_subtrees(self, db_conn):
        """5 chunks from 1 root + 2 chunks from 1 standalone → 2 rows."""
        _seed_tree(db_conn, "rootA", ["subA1", "subA2"])
        _seed_standalone(db_conn, "standB")
        results = [
            _SearchResultRow(conversation_id="rootA", score=0.95, rank=1, best_match_type="analysis"),
            _SearchResultRow(conversation_id="subA1", score=0.92, rank=2, best_match_type="summary"),
            _SearchResultRow(conversation_id="standB", score=0.88, rank=3, best_match_type="analysis"),
            _SearchResultRow(conversation_id="subA2", score=0.81, rank=4, best_match_type="content"),
            _SearchResultRow(conversation_id="rootA", score=0.78, rank=5, best_match_type="content"),
        ]
        out = _dedup_search_results_by_root(results, _make_conv_store(db_conn), limit=10)
        assert len(out) == 2
        # Order preserved: rootA first (max score 0.95), then standB.
        assert [r.conversation_id for r in out] == ["rootA", "standB"]
        # Ranks renumbered 1..N after collapse.
        assert [r.rank for r in out] == [1, 2]

    def test_no_backfill_preserves_limit(self, db_conn):
        """If dedup leaves fewer rows than ``limit``, we do NOT
        backfill — preserves the explicit AC4 contract."""
        _seed_tree(db_conn, "rootA", ["subA1", "subA2", "subA3"])
        # All 4 chunks from the same root.
        results = [
            _SearchResultRow(conversation_id=cid, score=0.9 - i * 0.05, rank=i + 1, best_match_type="analysis")
            for i, cid in enumerate(["rootA", "subA1", "subA2", "subA3"])
        ]
        out = _dedup_search_results_by_root(results, _make_conv_store(db_conn), limit=10)
        # Even though limit=10 and we had 4 input rows, dedup leaves 1.
        # No backfill from elsewhere.
        assert len(out) == 1

    def test_limit_truncates_after_dedup(self, db_conn):
        """``limit`` is applied **after** dedup, so it's a roots-cap."""
        # Three standalone trees.
        for cid in ("conv1", "conv2", "conv3"):
            _seed_standalone(db_conn, cid)
        results = [
            _SearchResultRow(conversation_id="conv1", score=0.9, rank=1, best_match_type="analysis"),
            _SearchResultRow(conversation_id="conv2", score=0.8, rank=2, best_match_type="analysis"),
            _SearchResultRow(conversation_id="conv3", score=0.7, rank=3, best_match_type="analysis"),
        ]
        out = _dedup_search_results_by_root(results, _make_conv_store(db_conn), limit=2)
        assert len(out) == 2
        assert [r.conversation_id for r in out] == ["conv1", "conv2"]

    def test_unknown_id_passes_through_unchanged(self, db_conn):
        """An id not in the DB falls back to self-root (FS-only conv)."""
        results = [
            _SearchResultRow(conversation_id="ghost1", score=0.5, rank=1, best_match_type="analysis"),
        ]
        out = _dedup_search_results_by_root(results, _make_conv_store(db_conn), limit=10)
        assert len(out) == 1
        assert out[0].conversation_id == "ghost1"


# ---------------------------------------------------------------------------
# _display_retrieval_breakdown — both grains
# ---------------------------------------------------------------------------


class TestDisplayRetrievalBreakdownBothGrains:
    """The ``--explain`` retrieval breakdown shows both the chunk-level
    ``conversation_id`` and the rolled-up ``root_conversation_id`` so
    users can audit dedup decisions."""

    def _chunk(self, conv_id: str, root_id: str, score: float = 0.8):
        m = MagicMock()
        m.conversation_id = conv_id
        m.root_conversation_id = root_id
        m.embed_type = "analysis"
        m.title = "Test"
        m.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        m.summary = None
        m.score = score
        return m

    def test_only_standalone_chunks_no_root_annotation(self, capsys):
        """When every chunk has root == id, the header doesn't include
        the ``(root: ...)`` parenthetical — keeps the breakdown clean
        for the common case."""
        chunks = [self._chunk("standabcdef", "standabcdef")]
        _display_retrieval_breakdown(
            question="q",
            chunks=chunks,
            search_time=0.1,
            temporal_applied=False,
            date_range=None,
            explicit_start=None,
            explicit_end=None,
        )
        out = capsys.readouterr().out
        assert "root:" not in out
        # The conv-grain count is shown without the rolled-up count.
        assert "Retrieved 1 chunks from 1 conversations" in out
        assert "roots" not in out

    def test_sub_chunk_shows_both_grains(self, capsys):
        """A chunk from a delegated sub shows both its own id AND the
        rolled-up root id in the per-conv header."""
        chunks = [self._chunk("sub12345678", "rootabcdef00")]
        _display_retrieval_breakdown(
            question="q",
            chunks=chunks,
            search_time=0.1,
            temporal_applied=False,
            date_range=None,
            explicit_start=None,
            explicit_end=None,
        )
        out = capsys.readouterr().out
        # Both ids appear (8-char prefixes).
        assert "sub12345" in out
        assert "rootabcd" in out
        # The "root:" parenthetical is present in the per-conv header.
        assert "root:" in out
        # Single chunk under a single sub still reports 1 conv (its
        # own id) and the summary line does NOT append "(N roots)"
        # because the conv-count and root-count happen to coincide.
        # The chunk-level "(root: ...)" annotation remains the source
        # of truth here.
        assert "Retrieved 1 chunks from 1 conversations" in out

    def test_summary_line_when_chunk_count_differs_from_root_count(self, capsys):
        """When chunks split across multiple subs but collapse to one
        root, the summary line shows ``(N roots)``."""
        chunks = [
            self._chunk("sub11111111", "rootcafe00", score=0.9),
            self._chunk("sub22222222", "rootcafe00", score=0.8),
            self._chunk("standalone1", "standalone1", score=0.7),
        ]
        _display_retrieval_breakdown(
            question="q",
            chunks=chunks,
            search_time=0.1,
            temporal_applied=False,
            date_range=None,
            explicit_start=None,
            explicit_end=None,
        )
        out = capsys.readouterr().out
        # 3 chunks across 3 distinct conv ids → 2 roots.
        assert "3 chunks from 3 conversations" in out
        assert "(2 roots)" in out
