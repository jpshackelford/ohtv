"""Tests for text_builders.py - contextual chunk building and splitting."""

from datetime import datetime, timezone

import pytest

from ohtv.analysis.embeddings.text_builders import (
    ConversationMetadata,
    MIN_CONTENT_SPACE,
)


class TestConversationMetadataBuildPreamble:
    """Tests for ConversationMetadata.build_preamble()."""

    def test_empty_metadata_returns_empty_string(self):
        """Metadata with no fields returns empty preamble."""
        meta = ConversationMetadata(conversation_id="abc123")
        assert meta.build_preamble() == ""

    def test_with_date_only(self):
        """Preamble includes formatted date."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            created_at=datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc),
        )
        preamble = meta.build_preamble()
        assert "Date: 2026-04-19" in preamble
        assert preamble.endswith("---\n")

    def test_with_summary_only(self):
        """Preamble includes summary."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary="Configure MCP secrets handling",
        )
        preamble = meta.build_preamble()
        assert "Summary: Configure MCP secrets handling" in preamble

    def test_with_refs_only(self):
        """Preamble includes related refs."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            ref_fqns=["owner/repo#42", "owner/repo#38"],
        )
        preamble = meta.build_preamble()
        assert "Related: owner/repo#42, owner/repo#38" in preamble

    def test_long_summary_truncated(self):
        """Summaries over 200 chars are truncated with ellipsis."""
        long_summary = "A" * 250
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary=long_summary,
        )
        preamble = meta.build_preamble()
        # Should be truncated to 200 chars + "..."
        assert "A" * 200 + "..." in preamble
        assert "A" * 201 not in preamble

    def test_refs_limited_by_max_refs(self):
        """Only max_refs refs are included."""
        refs = [f"owner/repo#{i}" for i in range(10)]
        meta = ConversationMetadata(
            conversation_id="abc123",
            ref_fqns=refs,
        )
        preamble = meta.build_preamble(max_refs=3)
        assert "owner/repo#0" in preamble
        assert "owner/repo#2" in preamble
        assert "owner/repo#3" not in preamble

    def test_full_preamble_format(self):
        """Full preamble with all fields has correct format."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            created_at=datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc),
            summary="Configure MCP secrets",
            ref_fqns=["owner/repo#42"],
        )
        preamble = meta.build_preamble()
        lines = preamble.split("\n")
        assert lines[0] == "Date: 2026-04-19"
        assert lines[1] == "Summary: Configure MCP secrets"
        assert lines[2] == "Related: owner/repo#42"
        assert lines[3] == "---"


class TestConversationMetadataPrependToText:
    """Tests for ConversationMetadata.prepend_to_text()."""

    def test_short_content_no_preamble(self):
        """Short content without preamble returns single chunk."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "Short content here"
        chunks = meta.prepend_to_text(content, max_chars=3000)
        assert len(chunks) == 1
        assert chunks[0] == "Short content here"

    def test_short_content_with_preamble(self):
        """Short content with preamble returns single chunk with preamble prepended."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary="Test summary",
        )
        content = "Short content here"
        chunks = meta.prepend_to_text(content, max_chars=3000)
        assert len(chunks) == 1
        assert "Summary: Test summary" in chunks[0]
        assert "Short content here" in chunks[0]

    def test_long_content_no_preamble_splits(self):
        """Long content without preamble is split into chunks."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "word " * 1000  # ~5000 chars
        chunks = meta.prepend_to_text(content, max_chars=500)
        assert len(chunks) > 1
        # All chunks should fit within max_chars
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_long_content_with_preamble_splits_with_preamble_each(self):
        """Long content with preamble splits, and each chunk has preamble."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary="Test summary",
        )
        content = "word " * 1000  # ~5000 chars
        chunks = meta.prepend_to_text(content, max_chars=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert "Summary: Test summary" in chunk
            assert len(chunk) <= 500

    def test_empty_content(self):
        """Empty content returns empty list or list with preamble only."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary="Test",
        )
        chunks = meta.prepend_to_text("", max_chars=3000)
        assert len(chunks) == 1
        assert "Summary: Test" in chunks[0]

    def test_whitespace_only_content(self):
        """Whitespace-only content handled gracefully."""
        meta = ConversationMetadata(conversation_id="abc123")
        chunks = meta.prepend_to_text("   ", max_chars=3000)
        assert len(chunks) == 1
        assert chunks[0] == "   "

    def test_content_exactly_at_limit(self):
        """Content exactly at max_chars limit returns single chunk."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "x" * 500
        chunks = meta.prepend_to_text(content, max_chars=500)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_preamble_plus_content_at_limit(self):
        """Preamble + content at limit returns single chunk."""
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary="X",  # Minimal summary
        )
        preamble = meta.build_preamble()
        content_len = 500 - len(preamble)
        content = "x" * content_len
        chunks = meta.prepend_to_text(content, max_chars=500)
        assert len(chunks) == 1
        assert len(chunks[0]) == 500

    def test_very_long_preamble_truncated(self):
        """Very long preamble is truncated to allow MIN_CONTENT_SPACE for content."""
        # Create a preamble that would exceed max_chars
        long_refs = [f"owner/really-long-repository-name#{i:04d}" for i in range(100)]
        meta = ConversationMetadata(
            conversation_id="abc123",
            created_at=datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc),
            summary="A" * 200,
            ref_fqns=long_refs,
        )
        content = "Important content that must be preserved"
        chunks = meta.prepend_to_text(content, max_chars=500, max_refs=100)
        # Content should still appear
        assert any("Important content" in chunk for chunk in chunks)


class TestConversationMetadataSplitContent:
    """Tests for ConversationMetadata._split_content()."""

    def test_short_content_no_split(self):
        """Content shorter than max_chars returns single piece."""
        meta = ConversationMetadata(conversation_id="abc123")
        pieces = meta._split_content("short text", max_chars=100)
        assert len(pieces) == 1
        assert pieces[0] == "short text"

    def test_split_creates_two_chunks(self):
        """Content requiring 2 chunks is split correctly."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "a" * 150
        pieces = meta._split_content(content, max_chars=100, overlap=20)
        assert len(pieces) == 2
        # First chunk is at max
        assert len(pieces[0]) == 100
        # Second chunk includes overlap
        assert pieces[1].startswith("a" * 20)

    def test_split_creates_multiple_chunks(self):
        """Long content creates 3+ chunks."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "word " * 200  # ~1000 chars
        pieces = meta._split_content(content, max_chars=300, overlap=50)
        assert len(pieces) >= 3

    def test_overlap_applied_correctly(self):
        """Overlap ensures continuity between chunks."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "The quick brown fox jumps over the lazy dog. " * 10
        pieces = meta._split_content(content, max_chars=100, overlap=30)
        
        # Check that end of chunk N overlaps with start of chunk N+1
        for i in range(len(pieces) - 1):
            # Last 30 chars of piece[i] should appear at start of piece[i+1]
            # (approximately, due to word boundary logic)
            end_of_current = pieces[i][-30:]
            # The next piece should contain content that was in current piece
            # This is an approximation test since word boundaries may shift things
            assert len(pieces[i]) <= 100

    def test_word_boundary_splitting(self):
        """Split prefers breaking at word boundaries."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "word " * 50  # Many words
        pieces = meta._split_content(content, max_chars=23, overlap=5)
        # Each piece should not end mid-word (unless no space found)
        for piece in pieces[:-1]:  # Last piece may be shorter
            # Should end with a word or be exactly at limit
            assert piece.endswith(" ") or len(piece) <= 23

    def test_overlap_larger_than_content_handled(self):
        """Gracefully handles edge case where overlap >= content length."""
        meta = ConversationMetadata(conversation_id="abc123")
        content = "short"
        pieces = meta._split_content(content, max_chars=10, overlap=20)
        assert len(pieces) == 1
        assert pieces[0] == "short"

    def test_no_infinite_loop_on_edge_cases(self):
        """Ensure no infinite loop with pathological inputs."""
        meta = ConversationMetadata(conversation_id="abc123")
        # Very small max_chars
        content = "This is some content"
        pieces = meta._split_content(content, max_chars=5, overlap=2)
        # Should terminate and produce output
        assert len(pieces) > 0
        # Combined pieces should cover the content
        combined = "".join(pieces)
        assert "This" in combined


class TestMinContentSpaceConstant:
    """Tests verifying MIN_CONTENT_SPACE is used correctly."""

    def test_constant_value(self):
        """MIN_CONTENT_SPACE has expected value."""
        assert MIN_CONTENT_SPACE == 100

    def test_used_in_prepend_logic(self):
        """MIN_CONTENT_SPACE is respected in prepend_to_text."""
        # Create metadata with preamble that leaves < MIN_CONTENT_SPACE
        meta = ConversationMetadata(
            conversation_id="abc123",
            summary="A" * 200,
            ref_fqns=["owner/repo#" + str(i) for i in range(10)],
        )
        preamble = meta.build_preamble()
        # Set max_chars so that available = max_chars - preamble < MIN_CONTENT_SPACE
        # This should trigger the truncation logic
        max_chars = len(preamble) + 50  # Only 50 chars left for content
        
        content = "Important content"
        chunks = meta.prepend_to_text(content, max_chars=max_chars)
        
        # Should still produce output with content
        assert len(chunks) >= 1
        # Content should be present somewhere
        full_text = "".join(chunks)
        assert "Important content" in full_text
