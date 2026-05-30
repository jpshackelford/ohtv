"""Tests for Issue #128 — RAG citation root-dedup.

The render-layer citation pipeline collapses chunks from delegated
sub-conversations to their **root** so users see one citation per
user-intent unit (the unit they recognise from ``ohtv list`` and the
cloud UI), without changing the chunk-grain retrieval contract.

Coverage:

* ``_results_to_context_chunks`` populates ``root_conversation_id``
  from the DB (standalone, sub, root paths).
* ``RAGRetrievalResult.source_conversation_ids`` is a set of **roots**.
* ``_assert_root_column_present`` runtime guard fires when migration
  020 is missing.
* ``_build_context_text`` / ``_format_chunk_header`` cite the root
  and append ``(via sub: ...)`` only when the chunk's source ≠ root.
* The closing-AC regression: 1 root + 2 subs + 1 standalone →
  exactly 2 citations after dedup.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ohtv.analysis.rag import (
    ContextChunk,
    RAGAnswerer,
    RAGRetriever,
    _assert_root_column_present,
    _results_to_context_chunks,
)


def _make_pragma_rows() -> list[tuple]:
    """PRAGMA rows that satisfy the migration-020 guard."""
    return [
        (0, "id", "TEXT", 0, None, 1),
        (1, "root_conversation_id", "TEXT", 0, None, 0),
    ]


def _make_conv(
    conv_id: str,
    *,
    root_id: str | None = None,
    title: str = "Conv title",
    summary: str | None = None,
    source: str = "local",
    created_at: datetime | None = None,
) -> MagicMock:
    """Build a ``conv_store.get`` return value for one conversation."""
    m = MagicMock()
    m.title = title
    m.summary = summary
    m.source = source
    m.created_at = created_at
    # Default: standalone (root == self).
    m.root_conversation_id = root_id if root_id is not None else conv_id
    return m


def _make_chunk_result(
    conv_id: str,
    *,
    score: float = 0.8,
    embed_type: str = "analysis",
    chunk_index: int = 0,
    source_text: str = "test text",
) -> MagicMock:
    """Build a chunk-search result row (duck-typed)."""
    r = MagicMock()
    r.conversation_id = conv_id
    r.embed_type = embed_type
    r.source_text = source_text
    r.score = score
    r.chunk_index = chunk_index
    return r


# ---------------------------------------------------------------------------
# _results_to_context_chunks — root population
# ---------------------------------------------------------------------------


class TestResultsToContextChunksRootPopulation:
    """``_results_to_context_chunks`` reads ``Conversation.root_conversation_id``
    so every chunk carries a root id (== own id for standalones)."""

    def test_standalone_conv_root_equals_id(self):
        """For a conv with ``root_conversation_id = id``, the chunk
        carries the same value (no surprise re-mapping)."""
        results = [_make_chunk_result("aaa111")]
        conv_store = MagicMock()
        conv_store.get.return_value = _make_conv("aaa111")
        chunks = _results_to_context_chunks(
            results, conv_store, None, None, None, "https://example.invalid"
        )
        assert len(chunks) == 1
        assert chunks[0].conversation_id == "aaa111"
        assert chunks[0].root_conversation_id == "aaa111"

    def test_sub_conv_uses_root_from_db(self):
        """For a sub, the chunk's ``root_conversation_id`` is the
        DB-populated root, not the chunk's own conv id."""
        results = [_make_chunk_result("sub222")]
        conv_store = MagicMock()
        conv_store.get.return_value = _make_conv("sub222", root_id="root111")
        chunks = _results_to_context_chunks(
            results, conv_store, None, None, None, "https://example.invalid"
        )
        assert chunks[0].conversation_id == "sub222"
        assert chunks[0].root_conversation_id == "root111"

    def test_missing_conv_falls_back_to_self_id(self):
        """If the conv isn't in the DB (FS-only fallback), the chunk
        gets ``root_conversation_id = conversation_id`` so downstream
        dedup treats it as a standalone."""
        results = [_make_chunk_result("ghost1")]
        conv_store = MagicMock()
        conv_store.get.return_value = None
        chunks = _results_to_context_chunks(
            results, conv_store, None, None, None, "https://example.invalid"
        )
        assert chunks[0].root_conversation_id == "ghost1"

    def test_null_root_falls_back_to_self_id(self):
        """If the DB row is present but ``root_conversation_id`` is
        NULL (pre-backfill race), we self-root rather than crash."""
        results = [_make_chunk_result("orphan")]
        conv_store = MagicMock()
        # ``None`` root via direct attribute set.
        conv = MagicMock()
        conv.title = "Orphan"
        conv.summary = None
        conv.source = "local"
        conv.created_at = None
        conv.root_conversation_id = None
        conv_store.get.return_value = conv
        chunks = _results_to_context_chunks(
            results, conv_store, None, None, None, "https://example.invalid"
        )
        assert chunks[0].root_conversation_id == "orphan"


# ---------------------------------------------------------------------------
# source_conversation_ids — root grain (AC2)
# ---------------------------------------------------------------------------


class TestSourceConversationIdsAreRoots:
    """``RAGRetrievalResult.source_conversation_ids`` is the rolled-up
    set of roots, not the chunk-level conv ids."""

    @pytest.fixture
    def retriever_with_dummy_store(self):
        """Build a retriever whose ``conv_store.conn`` satisfies the
        migration-020 guard."""
        embed_store = MagicMock()
        conv_store = MagicMock()
        conv_store.conn.execute.return_value = _make_pragma_rows()
        return retriever_with_dummy_store_helper(embed_store, conv_store)

    def test_one_root_two_subs_collapses_to_one_id(self, monkeypatch):
        """1 root + 2 subs (all under same root) → 1 source id."""
        monkeypatch.setattr(
            "ohtv.analysis.embeddings.get_embedding",
            lambda q: MagicMock(embedding=[0.1] * 1536),
        )
        embed_store = MagicMock()
        conv_store = MagicMock()
        conv_store.conn.execute.return_value = _make_pragma_rows()

        # Three chunks under one root R.
        embed_store.get_context_for_rag.return_value = [
            _make_chunk_result("R", score=0.9),
            _make_chunk_result("SUB1", score=0.7),
            _make_chunk_result("SUB2", score=0.6),
        ]
        # Every conv → root R.
        def fake_get(cid):
            return _make_conv(cid, root_id="R")
        conv_store.get.side_effect = fake_get

        retriever = RAGRetriever(embed_store, conv_store, enable_temporal_filter=False)
        result = retriever.retrieve("q")

        assert result.source_conversation_ids == {"R"}
        # AC closing-checkbox: chunk-grain truth preserved.
        assert len(result.context_chunks) == 3

    def test_one_root_two_subs_plus_one_standalone(self, monkeypatch):
        """1 root + 2 subs (same root) + 1 standalone → 2 source ids."""
        monkeypatch.setattr(
            "ohtv.analysis.embeddings.get_embedding",
            lambda q: MagicMock(embedding=[0.1] * 1536),
        )
        embed_store = MagicMock()
        conv_store = MagicMock()
        conv_store.conn.execute.return_value = _make_pragma_rows()

        embed_store.get_context_for_rag.return_value = [
            _make_chunk_result("R", score=0.9),
            _make_chunk_result("SUB1", score=0.8),
            _make_chunk_result("SUB2", score=0.7),
            _make_chunk_result("Y", score=0.6),
        ]

        # Sub-tree convs root to R; standalone Y roots to itself.
        def fake_get(cid):
            if cid in ("R", "SUB1", "SUB2"):
                return _make_conv(cid, root_id="R")
            return _make_conv(cid)
        conv_store.get.side_effect = fake_get

        retriever = RAGRetriever(embed_store, conv_store, enable_temporal_filter=False)
        result = retriever.retrieve("q")

        # AC closing-checkbox: len == 2 (1 root + 1 standalone).
        assert result.source_conversation_ids == {"R", "Y"}
        # All 4 chunks survive — no pre-aggregation.
        assert len(result.context_chunks) == 4


def retriever_with_dummy_store_helper(embed_store, conv_store):
    """Sliver around ``RAGRetriever`` to keep fixtures terse."""
    return RAGRetriever(embed_store, conv_store, enable_temporal_filter=False)


# ---------------------------------------------------------------------------
# Migration-020 guard
# ---------------------------------------------------------------------------


class TestAssertRootColumnPresent:
    """``_assert_root_column_present`` fires when the column is missing,
    and stays silent when it's there."""

    def test_passes_when_column_present(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE conversations (id TEXT, root_conversation_id TEXT)"
        )
        _assert_root_column_present(conn)  # should not raise

    def test_raises_when_column_missing(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE conversations (id TEXT)")
        with pytest.raises(RuntimeError) as excinfo:
            _assert_root_column_present(conn)
        # Cite migration 020 explicitly (sibling-PR contract).
        assert "020" in str(excinfo.value)
        assert "root_conversation_id" in str(excinfo.value)

    def test_retrieve_raises_when_column_missing(self, monkeypatch):
        """Issue #128 closing AC: a connection without
        ``root_conversation_id`` raises at first retrieval — runtime,
        not at import."""
        monkeypatch.setattr(
            "ohtv.analysis.embeddings.get_embedding",
            lambda q: MagicMock(embedding=[0.1] * 1536),
        )
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE conversations (id TEXT)")
        embed_store = MagicMock()
        conv_store = MagicMock()
        conv_store.conn = conn

        retriever = RAGRetriever(embed_store, conv_store, enable_temporal_filter=False)
        # The guard fires before any DB / LLM call.
        with pytest.raises(RuntimeError, match="020"):
            retriever.retrieve("q")


# ---------------------------------------------------------------------------
# _format_chunk_header / _build_context_text — root + via-sub annotation
# ---------------------------------------------------------------------------


class TestFormatChunkHeader:
    """The LLM prompt header cites the **root** id and annotates
    ``(via sub: ...)`` when the chunk came from a delegated sub."""

    @pytest.fixture
    def answerer(self, monkeypatch):
        """Build a ``RAGAnswerer`` without exercising the LLM API key
        check (mocking ``LLM`` is overkill — we only call format helpers)."""
        # Avoid needing LLM_API_KEY.
        monkeypatch.setenv("LLM_API_KEY", "test-key-not-used")
        embed_store = MagicMock()
        conv_store = MagicMock()
        conv_store.conn.execute.return_value = _make_pragma_rows()
        return RAGAnswerer(embed_store, conv_store)

    def test_header_for_standalone_conv_omits_via_sub(self, answerer):
        chunk = ContextChunk(
            conversation_id="self123",
            root_conversation_id="self123",
            title="Standalone",
            embed_type="analysis",
            source_text="...",
            score=0.9,
        )
        header = answerer._format_chunk_header(chunk, index=1)
        assert "Conversation ID: self123" in header
        assert "via sub" not in header

    def test_header_for_sub_includes_via_sub_annotation(self, answerer):
        chunk = ContextChunk(
            conversation_id="subdeadbeef00",
            root_conversation_id="rootcafebabe11",
            title="Delegated",
            embed_type="analysis",
            source_text="...",
            score=0.85,
        )
        header = answerer._format_chunk_header(chunk, index=2)
        # Root is the canonical citation.
        assert "Conversation ID: rootcafebabe11" in header
        # Sub-grain truth is preserved in the parenthetical.
        assert "(via sub: subdeadb" in header

    def test_build_context_text_routes_through_root(self, answerer):
        """The full LLM prompt builder concatenates root-cited
        headers (so the LLM cites root ids in its answer text)."""
        chunks = [
            ContextChunk(
                conversation_id="sub00000001",
                root_conversation_id="rootABCDEF",
                title="A",
                embed_type="analysis",
                source_text="alpha",
                score=0.9,
            ),
            ContextChunk(
                conversation_id="standalone1",
                root_conversation_id="standalone1",
                title="B",
                embed_type="analysis",
                source_text="beta",
                score=0.8,
            ),
        ]
        text = answerer._build_context_text(chunks)
        # Root id appears as the canonical citation for the sub-sourced
        # chunk; via-sub annotation present.
        assert "Conversation ID: rootABCDEF" in text
        assert "(via sub: sub00000" in text
        # Standalone has no via-sub annotation.
        assert "Conversation ID: standalone1" in text
        standalone_block = text.split("[Source 2:")[-1]
        assert "via sub" not in standalone_block


# ---------------------------------------------------------------------------
# ContextChunk dataclass shape
# ---------------------------------------------------------------------------


class TestContextChunkDataclass:
    def test_root_field_required(self):
        """``root_conversation_id`` is a required field — must be
        passed explicitly to construction."""
        with pytest.raises(TypeError):
            ContextChunk(
                conversation_id="abc",  # type: ignore[call-arg]
                title="t",
                embed_type="analysis",
                source_text="s",
                score=0.5,
            )

    def test_can_construct_with_all_fields(self):
        chunk = ContextChunk(
            conversation_id="cid",
            root_conversation_id="rid",
            title="t",
            embed_type="analysis",
            source_text="s",
            score=0.5,
        )
        assert chunk.conversation_id == "cid"
        assert chunk.root_conversation_id == "rid"
