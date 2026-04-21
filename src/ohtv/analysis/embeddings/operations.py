"""High-level embedding operations for conversations."""

import logging
from dataclasses import dataclass
from pathlib import Path

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
    from ohtv.db.stores import EmbeddingStore, LinkStore, ReferenceStore
    from .client import get_embedding, get_embedding_model
    from .text_builders import build_conversation_texts

    conv_id = conv_dir.name
    store = EmbeddingStore(conn)
    stats = EmbeddingStats(conversation_id=conv_id)

    events = load_events(conv_dir)
    if not events:
        log.debug("No events in conversation %s", conv_id)
        return stats

    if analysis is None:
        analysis = load_analysis(conv_dir)

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
        except Exception:
            refs = []

    texts = build_conversation_texts(events, analysis, refs)
    
    # Early exit if no embeddable content
    if not texts.analysis_text and not texts.summary_text and not texts.content_chunks:
        log.debug("No embeddable content for %s", conv_id[:12])
        return stats
    
    # Debug: log what content exists and if embeddings exist
    log.debug(
        "Content for %s: analysis=%s, summary=%s, chunks=%d; has_existing: analysis=%s, summary=%s, content=%s",
        conv_id[:12],
        bool(texts.analysis_text),
        bool(texts.summary_text),
        len(texts.content_chunks) if texts.content_chunks else 0,
        store.has_embedding(conv_id, "analysis"),
        store.has_embedding(conv_id, "summary"),
        store.has_embedding(conv_id, "content"),
    )

    if model is None:
        model = get_embedding_model()

    if texts.analysis_text:
        if not skip_existing or not store.has_embedding(conv_id, "analysis"):
            result = get_embedding(texts.analysis_text, model=model)
            store.upsert(
                conversation_id=conv_id,
                embedding=result.embedding,
                model=result.model,
                embed_type="analysis",
                chunk_index=0,
                token_count=result.token_count,
                source_text=texts.analysis_text,
            )
            stats.analysis_tokens = result.token_count
            stats.embeddings_created += 1

    if texts.summary_text:
        if not skip_existing or not store.has_embedding(conv_id, "summary"):
            # Chunk summary text if it's too long for the model
            from .chunking import chunk_text
            summary_chunks = chunk_text(texts.summary_text)
            
            for chunk in summary_chunks:
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

    if texts.content_chunks:
        for chunk in texts.content_chunks:
            if not skip_existing or not store.has_embedding(conv_id, "content"):
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
    if not texts.analysis_text and not texts.summary_text and not texts.content_chunks:
        return 0, 0

    total_tokens = 0
    total_embeddings = 0

    if texts.analysis_text:
        total_tokens += estimate_tokens(texts.analysis_text)
        total_embeddings += 1

    if texts.summary_text:
        total_tokens += estimate_tokens(texts.summary_text)
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
