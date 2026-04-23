"""High-level embedding operations for conversations."""

import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger("ohtv")


@dataclass
class EmbeddingStats:
    """Statistics from embedding a conversation."""
    conversation_id: str
    analysis_tokens: int = 0
    summary_tokens: int = 0
    content_tokens: int = 0
    content_chunks: int = 0
    total_tokens: int = 0
    embeddings_created: int = 0


@dataclass
class PendingEmbedding:
    """An embedding ready to be written to the database."""
    conversation_id: str
    embedding: list[float]
    model: str
    embed_type: str
    chunk_index: int
    token_count: int
    source_text: str


@dataclass
class EmbeddingBatch:
    """A batch of embeddings from one conversation."""
    conversation_id: str
    embeddings: list[PendingEmbedding] = field(default_factory=list)
    fts_text: str | None = None  # For FTS indexing
    stats: EmbeddingStats | None = None
    error: str | None = None


def embed_conversation(
    conv_dir: Path,
    model: str | None = None,
):
    """Generate embedding for a conversation (legacy single-embedding).

    DEPRECATED: Use embed_conversation_full() for multi-type embeddings.

    Args:
        conv_dir: Path to conversation directory
        model: Model name (uses EMBEDDING_MODEL env var if None)

    Returns:
        EmbeddingResult or None if conversation has no content
    """
    from ohtv.analysis.cache import load_events
    from .client import get_embedding
    from .text_builders import build_lean_transcript

    events = load_events(conv_dir)
    if not events:
        log.debug("No events in conversation %s", conv_dir.name)
        return None

    transcript = build_lean_transcript(events)
    if not transcript:
        log.debug("No content in conversation %s", conv_dir.name)
        return None

    return get_embedding(transcript, model=model)


def embed_conversation_full(
    conv_dir: Path,
    conn,
    model: str | None = None,
    analysis: dict | None = None,
    refs: list[dict] | None = None,
    skip_existing: bool = True,
) -> EmbeddingStats:
    """Generate all embedding types for a conversation.

    Creates up to 3 embedding types:
    - analysis: From cached LLM analysis (if available)
    - summary: User messages + refs + file paths
    - content: File contents, chunked if large
    
    Uses contextual chunk enrichment (Anthropic's "contextual retrieval" 
    technique) to prepend date, summary, and refs to chunks before embedding.

    Args:
        conv_dir: Path to conversation directory
        conn: Database connection
        model: Model name (uses EMBEDDING_MODEL env var if None)
        analysis: Cached analysis dict (if not provided, tries to load from cache)
        refs: Git refs (if not provided, tries to load from database)
        skip_existing: Skip embedding types that already exist

    Returns:
        EmbeddingStats with counts and totals
    """
    from ohtv.analysis.cache import load_events, load_analysis
    from ohtv.db.stores import EmbeddingStore, LinkStore, ReferenceStore, ConversationStore
    from .client import get_embedding, get_embedding_model
    from .text_builders import build_conversation_texts, ConversationMetadata

    conv_id = conv_dir.name
    store = EmbeddingStore(conn)
    stats = EmbeddingStats(conversation_id=conv_id)

    events = load_events(conv_dir)
    if not events:
        log.debug("No events in conversation %s", conv_id)
        return stats

    if analysis is None:
        analysis = load_analysis(conv_dir)
    
    # Build ref FQNs list for contextual enrichment
    ref_fqns: list[str] = []
    if refs is None:
        try:
            link_store = LinkStore(conn)
            ref_store = ReferenceStore(conn)
            ref_links = link_store.get_refs_for_conversation(conv_id)
            refs = []
            for ref_id, _link_type in ref_links:
                ref = ref_store.get_by_id(ref_id)
                if ref:
                    refs.append({"ref_type": ref.ref_type.value, "url": ref.url})
                    if ref.fqn:
                        ref_fqns.append(ref.fqn)
        except Exception:
            refs = []
    else:
        # Extract FQNs from provided refs if available
        for ref in refs:
            fqn = ref.get("fqn")
            if fqn:
                ref_fqns.append(fqn)
    
    # Get conversation metadata for contextual enrichment
    metadata = None
    try:
        conv_store = ConversationStore(conn)
        conv = conv_store.get(conv_id)
        if conv:
            # Use analysis goal as summary if summary not set
            summary = conv.summary
            if not summary and analysis:
                summary = analysis.get("goal")
            
            metadata = ConversationMetadata(
                conversation_id=conv_id,
                created_at=conv.created_at,
                summary=summary,
                ref_fqns=ref_fqns,
            )
    except Exception:
        log.debug("Could not load conversation metadata for %s", conv_id)

    texts = build_conversation_texts(events, analysis, refs, metadata)

    if model is None:
        model = get_embedding_model()

    # Process analysis chunks
    for chunk in texts.analysis_chunks:
        if skip_existing and store.has_embedding(conv_id, "analysis", chunk.chunk_index):
            continue
        result = get_embedding(chunk.text, model=model)
        store.upsert(
            conversation_id=conv_id,
            embedding=result.embedding,
            model=result.model,
            embed_type="analysis",
            chunk_index=chunk.chunk_index,
            token_count=result.token_count,
            source_text=chunk.text,
        )
        stats.analysis_tokens += result.token_count
        stats.embeddings_created += 1

    # Process summary chunks
    for chunk in texts.summary_chunks:
        if skip_existing and store.has_embedding(conv_id, "summary", chunk.chunk_index):
            continue
        result = get_embedding(chunk.text, model=model)
        store.upsert(
            conversation_id=conv_id,
            embedding=result.embedding,
            model=result.model,
            embed_type="summary",
            chunk_index=chunk.chunk_index,
            token_count=result.token_count,
            source_text=chunk.text,
        )
        stats.summary_tokens += result.token_count
        stats.embeddings_created += 1

    # Process content chunks
    if texts.content_chunks:
        for chunk in texts.content_chunks:
            # Check per-chunk existence to handle interrupted runs correctly
            if skip_existing and store.has_embedding(conv_id, "content", chunk.chunk_index):
                continue
            result = get_embedding(chunk.text, model=model)
            store.upsert(
                conversation_id=conv_id,
                embedding=result.embedding,
                model=result.model,
                embed_type="content",
                chunk_index=chunk.chunk_index,
                token_count=result.token_count,
                source_text=chunk.text,
            )
            stats.content_tokens += result.token_count
            stats.content_chunks += 1
            stats.embeddings_created += 1

    stats.total_tokens = stats.analysis_tokens + stats.summary_tokens + stats.content_tokens

    return stats


def estimate_conversation_tokens(
    conv_dir: Path,
    analysis: dict | None = None,
    refs: list[dict] | None = None,
) -> tuple[int, int]:
    """Estimate token count and embedding count for a conversation.

    Args:
        conv_dir: Path to conversation directory
        analysis: Cached analysis dict (optional)
        refs: Git refs (optional)

    Returns:
        Tuple of (estimated_tokens, estimated_embeddings)
    """
    from ohtv.analysis.cache import load_events, load_analysis
    from .chunking import estimate_tokens
    from .text_builders import build_conversation_texts

    events = load_events(conv_dir)
    if not events:
        return 0, 0

    if analysis is None:
        analysis = load_analysis(conv_dir)

    texts = build_conversation_texts(events, analysis, refs)

    # Check if there's any embeddable content
    if not texts.analysis_chunks and not texts.summary_chunks and not texts.content_chunks:
        return 0, 0

    total_tokens = 0
    total_embeddings = 0

    for chunk in texts.analysis_chunks:
        total_tokens += chunk.estimated_tokens
        total_embeddings += 1

    for chunk in texts.summary_chunks:
        total_tokens += chunk.estimated_tokens
        total_embeddings += 1

    for chunk in texts.content_chunks:
        total_tokens += chunk.estimated_tokens
        total_embeddings += 1

    return total_tokens, total_embeddings


def check_embedding_status(
    conversation_ids: list[str],
    conn,
) -> dict[str, bool]:
    """Check which conversations have embeddings.

    Args:
        conversation_ids: List of conversation IDs to check
        conn: Database connection

    Returns:
        Dict mapping conversation_id -> has_embedding
    """
    from ohtv.db.stores import EmbeddingStore

    store = EmbeddingStore(conn)
    embedded = set(store.list_conversation_ids())

    return {cid: cid in embedded for cid in conversation_ids}


def check_embedding_types(
    conversation_id: str,
    conn,
) -> dict[str, bool]:
    """Check which embedding types exist for a conversation.

    Args:
        conversation_id: Conversation ID
        conn: Database connection

    Returns:
        Dict mapping embed_type -> exists
    """
    from ohtv.db.stores import EmbeddingStore

    store = EmbeddingStore(conn)
    return {
        "analysis": store.has_embedding(conversation_id, "analysis"),
        "summary": store.has_embedding(conversation_id, "summary"),
        "content": store.has_embedding(conversation_id, "content"),
    }


def generate_embeddings_only(
    conv_dir: Path,
    conn,
    model: str | None = None,
    analysis: dict | None = None,
    refs: list[dict] | None = None,
    skip_existing: bool = True,
) -> EmbeddingBatch:
    """Generate embeddings for a conversation WITHOUT writing to DB.
    
    This is designed for parallel processing - multiple threads can call
    this function to generate embeddings, then a single writer thread
    collects the results and writes them to the database.
    
    Args:
        conv_dir: Path to conversation directory
        conn: Database connection (only used to check existing embeddings)
        model: Model name (uses EMBEDDING_MODEL env var if None)
        analysis: Cached analysis dict (if not provided, tries to load from cache)
        refs: Git refs (if not provided, tries to load from database)
        skip_existing: Skip embedding types that already exist
    
    Returns:
        EmbeddingBatch containing all generated embeddings ready for DB write
    """
    from ohtv.analysis.cache import load_events, load_analysis
    from ohtv.db.stores import EmbeddingStore, LinkStore, ReferenceStore, ConversationStore
    from .client import get_embedding, get_embedding_model
    from .text_builders import build_conversation_texts, build_summary_text, ConversationMetadata

    conv_id = conv_dir.name
    batch = EmbeddingBatch(conversation_id=conv_id)
    stats = EmbeddingStats(conversation_id=conv_id)
    
    try:
        store = EmbeddingStore(conn)
        
        events = load_events(conv_dir)
        if not events:
            log.debug("No events in conversation %s", conv_id)
            batch.stats = stats
            return batch

        if analysis is None:
            analysis = load_analysis(conv_dir)
        
        # Build ref FQNs list for contextual enrichment
        ref_fqns: list[str] = []
        if refs is None:
            try:
                link_store = LinkStore(conn)
                ref_store = ReferenceStore(conn)
                ref_links = link_store.get_refs_for_conversation(conv_id)
                refs = []
                for ref_id, _link_type in ref_links:
                    ref = ref_store.get_by_id(ref_id)
                    if ref:
                        refs.append({"ref_type": ref.ref_type.value, "url": ref.url})
                        if ref.fqn:
                            ref_fqns.append(ref.fqn)
            except Exception:
                refs = []
        else:
            for ref in refs:
                fqn = ref.get("fqn")
                if fqn:
                    ref_fqns.append(fqn)
        
        # Get conversation metadata for contextual enrichment
        metadata = None
        try:
            conv_store = ConversationStore(conn)
            conv = conv_store.get(conv_id)
            if conv:
                summary = conv.summary
                if not summary and analysis:
                    summary = analysis.get("goal")
                
                metadata = ConversationMetadata(
                    conversation_id=conv_id,
                    created_at=conv.created_at,
                    summary=summary,
                    ref_fqns=ref_fqns,
                )
        except Exception:
            log.debug("Could not load conversation metadata for %s", conv_id)

        texts = build_conversation_texts(events, analysis, refs, metadata)

        if model is None:
            model = get_embedding_model()

        # Generate analysis embeddings
        for chunk in texts.analysis_chunks:
            if skip_existing and store.has_embedding(conv_id, "analysis", chunk.chunk_index):
                continue
            result = get_embedding(chunk.text, model=model)
            batch.embeddings.append(PendingEmbedding(
                conversation_id=conv_id,
                embedding=result.embedding,
                model=result.model,
                embed_type="analysis",
                chunk_index=chunk.chunk_index,
                token_count=result.token_count,
                source_text=chunk.text,
            ))
            stats.analysis_tokens += result.token_count
            stats.embeddings_created += 1

        # Generate summary embeddings
        for chunk in texts.summary_chunks:
            if skip_existing and store.has_embedding(conv_id, "summary", chunk.chunk_index):
                continue
            result = get_embedding(chunk.text, model=model)
            batch.embeddings.append(PendingEmbedding(
                conversation_id=conv_id,
                embedding=result.embedding,
                model=result.model,
                embed_type="summary",
                chunk_index=chunk.chunk_index,
                token_count=result.token_count,
                source_text=chunk.text,
            ))
            stats.summary_tokens += result.token_count
            stats.embeddings_created += 1

        # Generate content embeddings
        for chunk in texts.content_chunks:
            if skip_existing and store.has_embedding(conv_id, "content", chunk.chunk_index):
                continue
            result = get_embedding(chunk.text, model=model)
            batch.embeddings.append(PendingEmbedding(
                conversation_id=conv_id,
                embedding=result.embedding,
                model=result.model,
                embed_type="content",
                chunk_index=chunk.chunk_index,
                token_count=result.token_count,
                source_text=chunk.text,
            ))
            stats.content_tokens += result.token_count
            stats.content_chunks += 1
            stats.embeddings_created += 1

        stats.total_tokens = stats.analysis_tokens + stats.summary_tokens + stats.content_tokens
        batch.stats = stats
        
        # Generate FTS text for keyword search
        if stats.embeddings_created > 0:
            batch.fts_text = build_summary_text(events)
            
    except Exception as e:
        batch.error = str(e)
        log.debug("Error generating embeddings for %s: %s", conv_id, e)
    
    return batch


class EmbeddingWriter:
    """Thread-safe writer for batching embedding database writes.
    
    This class collects embeddings from multiple worker threads and writes
    them to the database in batches, avoiding SQLite locking issues.
    
    The writer creates its own database connection in its thread, since
    SQLite connections cannot be shared across threads.
    
    Usage:
        writer = EmbeddingWriter(batch_size=50)
        writer.start()
        
        # Worker threads submit batches
        writer.submit(batch1)
        writer.submit(batch2)
        
        # When done, stop and wait for all writes
        writer.stop()
        stats = writer.get_stats()
    """
    
    def __init__(self, batch_size: int = 50, on_batch_complete: Callable[[int], None] | None = None):
        """Initialize the writer.
        
        Args:
            batch_size: Number of conversations to batch before writing
            on_batch_complete: Callback called after each batch write with count
        """
        self._batch_size = batch_size
        self._on_batch_complete = on_batch_complete
        self._queue: queue.Queue[EmbeddingBatch | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        
        # Stats
        self._lock = threading.Lock()
        self._written = 0
        self._errors = 0
        self._total_embeddings = 0
    
    def start(self) -> None:
        """Start the writer thread."""
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()
    
    def submit(self, batch: EmbeddingBatch) -> None:
        """Submit a batch for writing."""
        self._queue.put(batch)
    
    def stop(self, timeout: float = 30.0) -> None:
        """Stop the writer and wait for pending writes.
        
        Args:
            timeout: Maximum seconds to wait for pending writes
        """
        self._stop_event.set()
        self._queue.put(None)  # Sentinel to wake up the thread
        if self._thread:
            self._thread.join(timeout=timeout)
    
    def get_stats(self) -> dict:
        """Get write statistics."""
        with self._lock:
            return {
                "written": self._written,
                "errors": self._errors,
                "total_embeddings": self._total_embeddings,
            }
    
    def _writer_loop(self) -> None:
        """Main writer loop - collects batches and writes to DB."""
        from ohtv.db.stores import EmbeddingStore
        from ohtv.db.connection import get_connection
        
        # Create connection in this thread - SQLite connections can't cross threads
        with get_connection() as conn:
            store = EmbeddingStore(conn)
            pending: list[EmbeddingBatch] = []
            
            while True:
                try:
                    # Wait for batches with timeout to allow periodic flushing
                    try:
                        batch = self._queue.get(timeout=0.5)
                    except queue.Empty:
                        batch = None
                    
                    if batch is None:
                        if self._stop_event.is_set():
                            # Flush remaining and exit
                            if pending:
                                self._write_batches(store, conn, pending)
                            break
                        continue
                    
                    if batch.error:
                        with self._lock:
                            self._errors += 1
                        continue
                    
                    pending.append(batch)
                    
                    # Write when we have enough batches
                    if len(pending) >= self._batch_size:
                        self._write_batches(store, conn, pending)
                        pending = []
                        
                except Exception as e:
                    log.error("Error in embedding writer: %s", e)
    
    def _write_batches(self, store, conn, batches: list[EmbeddingBatch]) -> None:
        """Write a list of batches to the database."""
        try:
            count = 0
            embed_count = 0
            
            for batch in batches:
                if not batch.embeddings and not batch.fts_text:
                    continue
                    
                for emb in batch.embeddings:
                    store.upsert(
                        conversation_id=emb.conversation_id,
                        embedding=emb.embedding,
                        model=emb.model,
                        embed_type=emb.embed_type,
                        chunk_index=emb.chunk_index,
                        token_count=emb.token_count,
                        source_text=emb.source_text,
                    )
                    embed_count += 1
                
                if batch.fts_text:
                    store.upsert_fts(batch.conversation_id, batch.fts_text)
                
                count += 1
            
            conn.commit()
            
            with self._lock:
                self._written += count
                self._total_embeddings += embed_count
            
            if self._on_batch_complete:
                self._on_batch_complete(count)
                
            log.debug("Wrote %d batches (%d embeddings)", count, embed_count)
            
        except Exception as e:
            log.error("Error writing embedding batches: %s", e)
            with self._lock:
                self._errors += len(batches)
