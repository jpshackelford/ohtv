"""Data store for embeddings (semantic search and RAG)."""

import sqlite3
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


# Embedding types
EmbedType = Literal["analysis", "summary", "content"]


@dataclass
class SearchResult:
    """A single search result with score."""
    conversation_id: str
    score: float
    rank: int
    embed_type: str = "summary"
    chunk_index: int = 0
    source_text: str | None = None


@dataclass
class ConversationSearchResult:
    """Aggregated search result for a conversation (best match across all embeddings)."""
    conversation_id: str
    score: float
    rank: int
    best_match_type: str
    best_match_chunk: int
    source_text: str | None = None
    all_matches: list[SearchResult] = field(default_factory=list)


@dataclass
class EmbeddingRecord:
    """An embedding record from the database."""
    conversation_id: str
    embed_type: str
    chunk_index: int
    dimensions: int
    model: str
    token_count: int | None
    source_text: str | None
    created_at: datetime


class EmbeddingStore:
    """Data access for embeddings and FTS search."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(
        self,
        conversation_id: str,
        embedding: list[float],
        model: str,
        embed_type: EmbedType = "summary",
        chunk_index: int = 0,
        token_count: int | None = None,
        source_text: str | None = None,
    ) -> None:
        """Insert or update an embedding.
        
        Args:
            conversation_id: Conversation ID
            embedding: Embedding vector as list of floats
            model: Model name used for embedding
            embed_type: Type of embedding ('analysis', 'summary', 'content')
            chunk_index: Chunk index (0 for non-chunked, 0+ for content chunks)
            token_count: Number of tokens embedded
            source_text: Original text that was embedded (for RAG context)
        """
        blob = struct.pack(f"<{len(embedding)}f", *embedding)
        now = datetime.now(timezone.utc).isoformat()
        
        self.conn.execute(
            """
            INSERT INTO embeddings (
                conversation_id, embed_type, chunk_index, embedding, 
                dimensions, model, token_count, source_text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, embed_type, chunk_index) DO UPDATE SET
                embedding = excluded.embedding,
                dimensions = excluded.dimensions,
                model = excluded.model,
                token_count = excluded.token_count,
                source_text = excluded.source_text,
                created_at = excluded.created_at
            """,
            (conversation_id, embed_type, chunk_index, blob, 
             len(embedding), model, token_count, source_text, now),
        )

    def get(
        self, 
        conversation_id: str,
        embed_type: EmbedType = "summary",
        chunk_index: int = 0,
    ) -> tuple[list[float], EmbeddingRecord] | None:
        """Get a specific embedding for a conversation.
        
        Returns:
            Tuple of (embedding vector, metadata record) or None if not found
        """
        cursor = self.conn.execute(
            """
            SELECT embedding, dimensions, model, token_count, source_text, created_at
            FROM embeddings 
            WHERE conversation_id = ? AND embed_type = ? AND chunk_index = ?
            """,
            (conversation_id, embed_type, chunk_index),
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        blob, dims, model, token_count, source_text, created_at = row
        embedding = list(struct.unpack(f"<{dims}f", blob))
        record = EmbeddingRecord(
            conversation_id=conversation_id,
            embed_type=embed_type,
            chunk_index=chunk_index,
            dimensions=dims,
            model=model,
            token_count=token_count,
            source_text=source_text,
            created_at=datetime.fromisoformat(created_at),
        )
        return embedding, record

    def get_all_for_conversation(self, conversation_id: str) -> list[tuple[list[float], EmbeddingRecord]]:
        """Get all embeddings for a conversation.
        
        Returns:
            List of (embedding vector, metadata record) tuples
        """
        cursor = self.conn.execute(
            """
            SELECT embed_type, chunk_index, embedding, dimensions, model, 
                   token_count, source_text, created_at
            FROM embeddings 
            WHERE conversation_id = ?
            ORDER BY embed_type, chunk_index
            """,
            (conversation_id,),
        )
        
        results = []
        for row in cursor.fetchall():
            embed_type, chunk_index, blob, dims, model, token_count, source_text, created_at = row
            embedding = list(struct.unpack(f"<{dims}f", blob))
            record = EmbeddingRecord(
                conversation_id=conversation_id,
                embed_type=embed_type,
                chunk_index=chunk_index,
                dimensions=dims,
                model=model,
                token_count=token_count,
                source_text=source_text,
                created_at=datetime.fromisoformat(created_at),
            )
            results.append((embedding, record))
        return results

    def delete(self, conversation_id: str, embed_type: EmbedType | None = None) -> int:
        """Delete embeddings for a conversation.
        
        Args:
            conversation_id: Conversation ID
            embed_type: If provided, only delete this type. Otherwise delete all.
        
        Returns:
            Number of embeddings deleted
        """
        if embed_type:
            cursor = self.conn.execute(
                "DELETE FROM embeddings WHERE conversation_id = ? AND embed_type = ?",
                (conversation_id, embed_type),
            )
        else:
            cursor = self.conn.execute(
                "DELETE FROM embeddings WHERE conversation_id = ?",
                (conversation_id,),
            )
        return cursor.rowcount

    def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.0,
        embed_types: list[EmbedType] | None = None,
    ) -> list[SearchResult]:
        """Search for similar embeddings using cosine similarity.
        
        Returns individual embedding matches (not aggregated by conversation).
        
        Args:
            query_embedding: Query embedding vector
            limit: Maximum number of results
            min_score: Minimum similarity score (0-1)
            embed_types: Filter by embedding types (None = all types)
        
        Returns:
            List of SearchResult ordered by score descending
        """
        try:
            import numpy as np
        except ImportError:
            raise RuntimeError("numpy is required for semantic search")
        
        query_dims = len(query_embedding)
        
        # Build query with optional type filter
        if embed_types:
            placeholders = ",".join("?" * len(embed_types))
            query = f"""
                SELECT conversation_id, embed_type, chunk_index, embedding, source_text
                FROM embeddings 
                WHERE dimensions = ? AND embed_type IN ({placeholders})
            """
            params = [query_dims] + list(embed_types)
        else:
            query = """
                SELECT conversation_id, embed_type, chunk_index, embedding, source_text
                FROM embeddings WHERE dimensions = ?
            """
            params = [query_dims]
        
        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            return []
        
        # Normalize query vector
        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm
        
        # Load all vectors and compute similarities
        metadata = []  # (conv_id, embed_type, chunk_index, source_text)
        vectors = []
        for conv_id, embed_type, chunk_index, blob, source_text in rows:
            metadata.append((conv_id, embed_type, chunk_index, source_text))
            vec = np.frombuffer(blob, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vectors.append(vec / norm)
            else:
                vectors.append(vec)
        
        if not vectors:
            return []
        
        # Matrix multiply for all similarities at once
        matrix = np.vstack(vectors)
        scores = matrix @ q
        
        # Get top-k above threshold
        top_indices = np.argsort(-scores)
        results = []
        for rank, i in enumerate(top_indices):
            score = float(scores[i])
            if score < min_score:
                break
            if len(results) >= limit:
                break
            conv_id, embed_type, chunk_index, source_text = metadata[i]
            results.append(SearchResult(
                conversation_id=conv_id,
                score=score,
                rank=rank + 1,
                embed_type=embed_type,
                chunk_index=chunk_index,
                source_text=source_text,
            ))
        
        return results

    def search_conversations(
        self,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.0,
        embed_types: list[EmbedType] | None = None,
    ) -> list[ConversationSearchResult]:
        """Search for similar conversations, aggregating by best match.
        
        Each conversation appears once, ranked by its best-matching embedding.
        
        Args:
            query_embedding: Query embedding vector
            limit: Maximum number of conversations to return
            min_score: Minimum similarity score (0-1)
            embed_types: Filter by embedding types (None = all types)
        
        Returns:
            List of ConversationSearchResult ordered by score descending
        """
        # Get more raw results than limit to ensure we have enough after aggregation
        raw_results = self.search(
            query_embedding, 
            limit=limit * 5,  # Get extras for aggregation
            min_score=min_score,
            embed_types=embed_types,
        )
        
        # Aggregate by conversation - keep best match and all matches
        conv_matches: dict[str, list[SearchResult]] = {}
        for result in raw_results:
            if result.conversation_id not in conv_matches:
                conv_matches[result.conversation_id] = []
            conv_matches[result.conversation_id].append(result)
        
        # Build aggregated results
        aggregated = []
        for conv_id, matches in conv_matches.items():
            best = max(matches, key=lambda m: m.score)
            aggregated.append(ConversationSearchResult(
                conversation_id=conv_id,
                score=best.score,
                rank=0,  # Will be set below
                best_match_type=best.embed_type,
                best_match_chunk=best.chunk_index,
                source_text=best.source_text,
                all_matches=matches,
            ))
        
        # Sort by score and assign ranks
        aggregated.sort(key=lambda r: r.score, reverse=True)
        for i, result in enumerate(aggregated[:limit]):
            result.rank = i + 1
        
        return aggregated[:limit]

    def get_context_for_rag(
        self,
        query_embedding: list[float],
        max_chunks: int = 5,
        min_score: float = 0.3,
    ) -> list[SearchResult]:
        """Get relevant context chunks for RAG.
        
        Optimized for RAG: returns chunks with source_text for prompt building.
        
        Args:
            query_embedding: Query embedding vector
            max_chunks: Maximum chunks to return
            min_score: Minimum similarity score
        
        Returns:
            List of SearchResult with source_text populated
        """
        results = self.search(
            query_embedding,
            limit=max_chunks,
            min_score=min_score,
        )
        # Filter to only results with source text
        return [r for r in results if r.source_text]

    def count(self) -> int:
        """Return count of stored embeddings."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM embeddings")
        return cursor.fetchone()[0]

    def count_by_type(self) -> dict[str, int]:
        """Return count of embeddings by type."""
        cursor = self.conn.execute(
            "SELECT embed_type, COUNT(*) FROM embeddings GROUP BY embed_type"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

    def count_by_model(self) -> dict[str, int]:
        """Return count of embeddings by model."""
        cursor = self.conn.execute(
            "SELECT model, COUNT(*) FROM embeddings GROUP BY model"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

    def count_conversations(self) -> int:
        """Return count of conversations with embeddings."""
        cursor = self.conn.execute(
            "SELECT COUNT(DISTINCT conversation_id) FROM embeddings"
        )
        return cursor.fetchone()[0]

    def list_conversation_ids(self) -> list[str]:
        """List all conversation IDs that have embeddings."""
        cursor = self.conn.execute(
            "SELECT DISTINCT conversation_id FROM embeddings"
        )
        return [row[0] for row in cursor.fetchall()]

    def has_embedding(
        self, 
        conversation_id: str, 
        embed_type: EmbedType | None = None,
        chunk_index: int | None = None,
    ) -> bool:
        """Check if a conversation has embeddings.
        
        Args:
            conversation_id: Conversation ID
            embed_type: Check for specific type, or any if None
            chunk_index: Check for specific chunk, or any if None
        """
        if embed_type and chunk_index is not None:
            cursor = self.conn.execute(
                "SELECT 1 FROM embeddings WHERE conversation_id = ? AND embed_type = ? AND chunk_index = ? LIMIT 1",
                (conversation_id, embed_type, chunk_index),
            )
        elif embed_type:
            cursor = self.conn.execute(
                "SELECT 1 FROM embeddings WHERE conversation_id = ? AND embed_type = ? LIMIT 1",
                (conversation_id, embed_type),
            )
        else:
            cursor = self.conn.execute(
                "SELECT 1 FROM embeddings WHERE conversation_id = ? LIMIT 1",
                (conversation_id,),
            )
        return cursor.fetchone() is not None

    # =========================================================================
    # FTS5 methods for keyword search (--exact flag)
    # =========================================================================

    def upsert_fts(self, conversation_id: str, content: str) -> None:
        """Insert or update FTS content for a conversation.
        
        Args:
            conversation_id: Conversation ID
            content: Plain text content for full-text search
        """
        # Delete existing entry (FTS5 doesn't support ON CONFLICT)
        self.conn.execute(
            "DELETE FROM conversation_fts WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.conn.execute(
            "INSERT INTO conversation_fts (conversation_id, content) VALUES (?, ?)",
            (conversation_id, content),
        )

    def search_fts(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search conversations using FTS5 keyword matching.
        
        Args:
            query: Search query (supports FTS5 syntax)
            limit: Maximum number of results
        
        Returns:
            List of SearchResult (scores are BM25 relevance)
        """
        cursor = self.conn.execute(
            """
            SELECT conversation_id, rank
            FROM conversation_fts
            WHERE content MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        
        results = []
        for rank, (conv_id, bm25_score) in enumerate(cursor.fetchall()):
            # FTS5 rank is negative (lower = better), convert to positive score
            results.append(SearchResult(
                conversation_id=conv_id,
                score=-bm25_score,  # Make positive
                rank=rank + 1,
            ))
        return results

    def count_fts(self) -> int:
        """Return count of FTS indexed conversations."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM conversation_fts")
        return cursor.fetchone()[0]
