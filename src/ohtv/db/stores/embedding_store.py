"""Data store for embeddings (semantic search)."""

import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SearchResult:
    """A single search result with score."""
    conversation_id: str
    score: float
    rank: int


@dataclass
class EmbeddingRecord:
    """An embedding record from the database."""
    conversation_id: str
    dimensions: int
    model: str
    token_count: int | None
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
        token_count: int | None = None,
    ) -> None:
        """Insert or update an embedding.
        
        Args:
            conversation_id: Conversation ID
            embedding: Embedding vector as list of floats
            model: Model name used for embedding (e.g. "openai/text-embedding-3-small")
            token_count: Number of tokens embedded
        """
        blob = struct.pack(f"<{len(embedding)}f", *embedding)
        now = datetime.now(timezone.utc).isoformat()
        
        self.conn.execute(
            """
            INSERT INTO embeddings (conversation_id, embedding, dimensions, model, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                embedding = excluded.embedding,
                dimensions = excluded.dimensions,
                model = excluded.model,
                token_count = excluded.token_count,
                created_at = excluded.created_at
            """,
            (conversation_id, blob, len(embedding), model, token_count, now),
        )

    def get(self, conversation_id: str) -> tuple[list[float], EmbeddingRecord] | None:
        """Get embedding for a conversation.
        
        Returns:
            Tuple of (embedding vector, metadata record) or None if not found
        """
        cursor = self.conn.execute(
            """
            SELECT embedding, dimensions, model, token_count, created_at
            FROM embeddings WHERE conversation_id = ?
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        blob, dims, model, token_count, created_at = row
        embedding = list(struct.unpack(f"<{dims}f", blob))
        record = EmbeddingRecord(
            conversation_id=conversation_id,
            dimensions=dims,
            model=model,
            token_count=token_count,
            created_at=datetime.fromisoformat(created_at),
        )
        return embedding, record

    def delete(self, conversation_id: str) -> bool:
        """Delete embedding for a conversation. Returns True if deleted."""
        cursor = self.conn.execute(
            "DELETE FROM embeddings WHERE conversation_id = ?",
            (conversation_id,),
        )
        return cursor.rowcount > 0

    def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """Search for similar conversations using cosine similarity.
        
        Uses numpy for efficient vector operations.
        
        Args:
            query_embedding: Query embedding vector
            limit: Maximum number of results
            min_score: Minimum similarity score (0-1)
        
        Returns:
            List of SearchResult ordered by score descending
        """
        try:
            import numpy as np
        except ImportError:
            raise RuntimeError("numpy is required for semantic search")
        
        query_dims = len(query_embedding)
        
        # Fetch all embeddings with matching dimensions
        cursor = self.conn.execute(
            "SELECT conversation_id, embedding FROM embeddings WHERE dimensions = ?",
            (query_dims,),
        )
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
        ids = []
        vectors = []
        for conv_id, blob in rows:
            ids.append(conv_id)
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
            results.append(SearchResult(
                conversation_id=ids[i],
                score=score,
                rank=rank + 1,
            ))
        
        return results

    def count(self) -> int:
        """Return count of stored embeddings."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM embeddings")
        return cursor.fetchone()[0]

    def count_by_model(self) -> dict[str, int]:
        """Return count of embeddings by model."""
        cursor = self.conn.execute(
            "SELECT model, COUNT(*) FROM embeddings GROUP BY model"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

    def list_conversation_ids(self) -> list[str]:
        """List all conversation IDs that have embeddings."""
        cursor = self.conn.execute("SELECT conversation_id FROM embeddings")
        return [row[0] for row in cursor.fetchall()]

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
