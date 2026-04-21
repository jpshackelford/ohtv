"""Embedding generation for semantic search and RAG.

Uses LiteLLM for embeddings through the same proxy as the chat/gen commands.
This means the same LLM_API_KEY and LLM_BASE_URL work for both.

Embedding types:
- analysis: Goal + outcomes from cached LLM analysis (high signal)
- summary: User messages + refs + file paths (searchable metadata)
- content: File contents + terminal outputs, chunked (detailed content)

Environment variables:
- EMBEDDING_MODEL: Model to use (default: openai/text-embedding-3-small)
- LLM_API_KEY: API key for LiteLLM proxy
- LLM_BASE_URL: Base URL for LiteLLM proxy (optional)
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger("ohtv")

DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"

# Chunk settings
CHUNK_SIZE = 1000  # Target tokens per chunk
CHUNK_OVERLAP = 100  # Overlap between chunks

# Known model dimensions
KNOWN_DIMENSIONS: dict[str, int] = {
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
    "mistral/mistral-embed": 1024,
    "gemini/gemini-embedding-001": 768,
    "bedrock/cohere.embed-english-v3": 1024,
}

# Cost per 1M tokens for known models
KNOWN_COSTS: dict[str, float] = {
    "openai/text-embedding-3-small": 0.02,
    "openai/text-embedding-3-large": 0.13,
    "mistral/mistral-embed": 0.10,
    "gemini/gemini-embedding-001": 0.15,
    "bedrock/cohere.embed-english-v3": 0.10,
}

EmbedType = Literal["analysis", "summary", "content"]


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""
    embedding: list[float]
    token_count: int
    model: str
    dimensions: int


def get_embedding_model() -> str:
    """Get the configured embedding model."""
    return os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def get_embedding_dimension(model: str | None = None) -> int:
    """Get dimension for an embedding model.
    
    Args:
        model: Model name (uses EMBEDDING_MODEL env var if None)
    
    Returns:
        Number of dimensions for the model (1536 default if unknown)
    """
    if model is None:
        model = get_embedding_model()
    return KNOWN_DIMENSIONS.get(model, 1536)


def estimate_cost(token_count: int, model: str | None = None) -> float:
    """Estimate cost in dollars for embedding tokens.
    
    Args:
        token_count: Number of tokens to embed
        model: Model name (uses EMBEDDING_MODEL env var if None)
    
    Returns:
        Estimated cost in dollars
    """
    if model is None:
        model = get_embedding_model()
    cost_per_million = KNOWN_COSTS.get(model, 0.02)  # Default to 3-small pricing
    return (token_count / 1_000_000) * cost_per_million


def get_embedding(text: str, model: str | None = None) -> EmbeddingResult:
    """Get embedding for text using LiteLLM.
    
    Uses the same LLM_API_KEY and LLM_BASE_URL as the gen command.
    
    Args:
        text: Text to embed
        model: Model name (uses EMBEDDING_MODEL env var if None)
    
    Returns:
        EmbeddingResult with embedding vector and metadata
    
    Raises:
        RuntimeError: If LLM configuration is missing or API call fails
    """
    import litellm
    
    if model is None:
        model = get_embedding_model()
    
    api_key = os.environ.get("LLM_API_KEY")
    api_base = os.environ.get("LLM_BASE_URL")
    
    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY environment variable not set. "
            "This is required for embedding generation."
        )
    
    log.debug("Getting embedding with model %s", model)
    
    try:
        response = litellm.embedding(
            model=model,
            input=[text],
            api_key=api_key,
            api_base=api_base,
        )
    except Exception as e:
        raise RuntimeError(f"Embedding API call failed: {e}") from e
    
    embedding = response.data[0]["embedding"]
    token_count = response.usage.total_tokens
    dimensions = len(embedding)
    
    return EmbeddingResult(
        embedding=embedding,
        token_count=token_count,
        model=model,
        dimensions=dimensions,
    )


@dataclass
class TextChunk:
    """A chunk of text for embedding."""
    text: str
    chunk_index: int
    estimated_tokens: int


@dataclass
class ConversationTexts:
    """All text components for a conversation's embeddings."""
    analysis_text: str | None = None
    summary_text: str | None = None
    content_chunks: list[TextChunk] = field(default_factory=list)


# ============================================================================
# Text building functions for each embedding type
# ============================================================================

def build_analysis_text(analysis: dict) -> str | None:
    """Build text from cached LLM analysis for 'analysis' embedding.
    
    This is the highest-signal embedding - what was the conversation about?
    
    Args:
        analysis: Cached analysis dict (from gen objs)
    
    Returns:
        Formatted text or None if no meaningful analysis
    """
    if not analysis:
        return None
    
    parts = []
    
    # Goal
    goal = analysis.get("goal", "")
    if goal:
        parts.append(f"Goal: {goal}")
    
    # Primary outcomes
    primary = analysis.get("primary_outcomes", [])
    if primary:
        parts.append("Outcomes: " + "; ".join(primary))
    
    # Secondary outcomes
    secondary = analysis.get("secondary_outcomes", [])
    if secondary:
        parts.append("Additional: " + "; ".join(secondary))
    
    # Tags/categories if present
    tags = analysis.get("tags", [])
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    
    if not parts:
        return None
    
    return "\n".join(parts)


def build_summary_text(
    events: list[dict],
    refs: list[dict] | None = None,
) -> str:
    """Build summary text for 'summary' embedding.
    
    Includes user messages, refs (repos/PRs/issues), and file paths.
    This is the "searchable metadata" embedding.
    
    Args:
        events: List of conversation events
        refs: List of git refs from database (optional)
    
    Returns:
        Formatted summary text
    """
    from ohtv.analysis.transcript import extract_message_content
    
    lines = []
    file_paths: set[str] = set()
    commands: list[str] = []
    
    for event in events:
        kind = event.get("kind", "")
        source = event.get("source", "")
        
        # User messages - core intent
        if kind == "MessageEvent" and source == "user":
            content = extract_message_content(event)
            if content:
                # Truncate long user messages
                if len(content) > 1000:
                    content = content[:1000] + "..."
                lines.append(f"[USER]: {content}")
        
        # Extract file paths from file_editor actions
        elif kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            action = event.get("action", {}) or {}
            
            if tool_name == "file_editor":
                path = action.get("path", "")
                if path:
                    file_paths.add(path)
            
            # Also capture key commands (brief)
            elif tool_name == "terminal":
                cmd = action.get("command", "")
                if cmd and len(cmd) < 100:
                    # Only include short, meaningful commands
                    commands.append(cmd)
            
            # Finish message (brief)
            elif tool_name == "finish":
                message = action.get("message", "")
                if message:
                    if len(message) > 500:
                        message = message[:500] + "..."
                    lines.append(f"[FINISH]: {message}")
    
    # Add refs section
    if refs:
        ref_lines = []
        repos = set()
        prs = []
        issues = []
        
        for ref in refs:
            ref_type = ref.get("ref_type", "")
            url = ref.get("url", "")
            
            if ref_type == "repo":
                repos.add(url)
            elif ref_type == "pull_request":
                prs.append(url)
            elif ref_type == "issue":
                issues.append(url)
        
        if repos:
            ref_lines.append(f"Repositories: {', '.join(repos)}")
        if prs:
            ref_lines.append(f"PRs: {', '.join(prs)}")
        if issues:
            ref_lines.append(f"Issues: {', '.join(issues)}")
        
        if ref_lines:
            lines.append("[REFS]:\n" + "\n".join(ref_lines))
    
    # Add file paths
    if file_paths:
        # Sort and limit to most relevant
        sorted_paths = sorted(file_paths)[:20]
        lines.append(f"[FILES]: {', '.join(sorted_paths)}")
    
    # Add a few key commands
    if commands:
        unique_cmds = list(dict.fromkeys(commands))[:10]  # Dedupe, limit
        lines.append(f"[COMMANDS]: {'; '.join(unique_cmds)}")
    
    return "\n\n".join(lines)


def build_content_text(events: list[dict]) -> str:
    """Build full content text for 'content' embedding.
    
    Includes file contents, terminal outputs - the detailed content.
    This gets chunked if too long.
    
    Args:
        events: List of conversation events
    
    Returns:
        Full content text
    """
    from ohtv.analysis.transcript import extract_message_content
    
    sections = []
    
    for event in events:
        kind = event.get("kind", "")
        source = event.get("source", "")
        
        # User messages
        if kind == "MessageEvent" and source == "user":
            content = extract_message_content(event)
            if content:
                sections.append(f"[USER]: {content}")
        
        # Action events with content
        elif kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            action = event.get("action", {}) or {}
            
            if tool_name == "file_editor":
                path = action.get("path", "")
                command = action.get("command", "")
                
                # For create/str_replace, include the content
                if command == "create":
                    file_text = action.get("file_text", "")
                    if file_text and len(file_text) < 5000:
                        sections.append(f"[FILE {path}]:\n{file_text}")
                elif command == "str_replace":
                    new_str = action.get("new_str", "")
                    if new_str and len(new_str) < 3000:
                        sections.append(f"[EDIT {path}]:\n{new_str}")
            
            elif tool_name == "terminal":
                cmd = action.get("command", "")
                if cmd:
                    sections.append(f"[COMMAND]: {cmd}")
            
            elif tool_name == "finish":
                message = action.get("message", "")
                if message:
                    sections.append(f"[FINISH]: {message}")
            
            elif tool_name == "think":
                thought = action.get("thought", "")
                if thought:
                    sections.append(f"[THINKING]: {thought}")
        
        # Observation events (command output)
        elif kind == "ObservationEvent":
            content = event.get("content", "")
            if content and len(content) < 2000:
                # Truncate very long outputs
                if len(content) > 1000:
                    content = content[:1000] + "..."
                sections.append(f"[OUTPUT]: {content}")
    
    return "\n\n".join(sections)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[TextChunk]:
    """Split text into overlapping chunks.
    
    Args:
        text: Text to chunk
        chunk_size: Target tokens per chunk
        overlap: Token overlap between chunks
    
    Returns:
        List of TextChunk objects
    """
    if not text:
        return []
    
    # Estimate if we need chunking
    estimated_tokens = estimate_tokens(text)
    if estimated_tokens <= chunk_size:
        return [TextChunk(text=text, chunk_index=0, estimated_tokens=estimated_tokens)]
    
    # Split by paragraphs first to keep semantic units together
    paragraphs = text.split("\n\n")
    
    chunks = []
    current_chunk: list[str] = []
    current_tokens = 0
    chunk_index = 0
    
    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        
        # If single paragraph is too big, split by sentences
        if para_tokens > chunk_size:
            # Add current chunk first
            if current_chunk:
                chunk_text_str = "\n\n".join(current_chunk)
                chunks.append(TextChunk(
                    text=chunk_text_str,
                    chunk_index=chunk_index,
                    estimated_tokens=current_tokens,
                ))
                chunk_index += 1
                current_chunk = []
                current_tokens = 0
            
            # Split large paragraph
            sentences = para.replace(". ", ".\n").split("\n")
            for sentence in sentences:
                sent_tokens = estimate_tokens(sentence)
                if current_tokens + sent_tokens > chunk_size and current_chunk:
                    chunk_text_str = " ".join(current_chunk)
                    chunks.append(TextChunk(
                        text=chunk_text_str,
                        chunk_index=chunk_index,
                        estimated_tokens=current_tokens,
                    ))
                    chunk_index += 1
                    # Keep overlap
                    overlap_text = " ".join(current_chunk[-2:]) if len(current_chunk) > 2 else ""
                    current_chunk = [overlap_text] if overlap_text else []
                    current_tokens = estimate_tokens(overlap_text) if overlap_text else 0
                
                current_chunk.append(sentence)
                current_tokens += sent_tokens
        
        elif current_tokens + para_tokens > chunk_size and current_chunk:
            # Save current chunk
            chunk_text_str = "\n\n".join(current_chunk)
            chunks.append(TextChunk(
                text=chunk_text_str,
                chunk_index=chunk_index,
                estimated_tokens=current_tokens,
            ))
            chunk_index += 1
            
            # Start new chunk with overlap (last paragraph)
            overlap_para = current_chunk[-1] if current_chunk else ""
            current_chunk = [overlap_para, para] if overlap_para else [para]
            current_tokens = estimate_tokens(overlap_para) + para_tokens if overlap_para else para_tokens
        else:
            current_chunk.append(para)
            current_tokens += para_tokens
    
    # Don't forget the last chunk
    if current_chunk:
        chunk_text_str = "\n\n".join(current_chunk)
        chunks.append(TextChunk(
            text=chunk_text_str,
            chunk_index=chunk_index,
            estimated_tokens=current_tokens,
        ))
    
    return chunks


def build_conversation_texts(
    events: list[dict],
    analysis: dict | None = None,
    refs: list[dict] | None = None,
) -> ConversationTexts:
    """Build all text components for a conversation's embeddings.
    
    Args:
        events: List of conversation events
        analysis: Cached analysis dict (from gen objs)
        refs: List of git refs from database
    
    Returns:
        ConversationTexts with all components
    """
    # Analysis embedding (if available)
    analysis_text = build_analysis_text(analysis) if analysis else None
    
    # Summary embedding
    summary_text = build_summary_text(events, refs)
    
    # Content embedding (chunked)
    content_text = build_content_text(events)
    content_chunks = chunk_text(content_text)
    
    return ConversationTexts(
        analysis_text=analysis_text,
        summary_text=summary_text if summary_text else None,
        content_chunks=content_chunks,
    )


def build_lean_transcript(events: list[dict]) -> str:
    """Build a lean transcript for embedding (user messages + finish blocks).
    
    DEPRECATED: Use build_summary_text() or build_content_text() instead.
    Kept for backward compatibility.
    
    Args:
        events: List of conversation events
    
    Returns:
        Plain text transcript with speaker labels
    """
    from ohtv.analysis.transcript import extract_message_content
    
    lines = []
    
    for event in events:
        kind = event.get("kind", "")
        source = event.get("source", "")
        
        # User messages
        if kind == "MessageEvent" and source == "user":
            content = extract_message_content(event)
            if content:
                lines.append(f"[USER]: {content}")
        
        # Finish actions (agent's final summary)
        elif kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            if tool_name == "finish":
                action = event.get("action", {})
                message = action.get("message", "")
                if message:
                    # Truncate very long finish messages
                    if len(message) > 2000:
                        message = message[:2000] + "..."
                    lines.append(f"[FINISH]: {message}")
            
            # Thinking blocks (from think tool)
            elif tool_name == "think":
                action = event.get("action", {})
                thought = action.get("thought", "")
                if thought:
                    # Truncate very long thoughts
                    if len(thought) > 1000:
                        thought = thought[:1000] + "..."
                    lines.append(f"[THINKING]: {thought}")
    
    return "\n\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Rough estimate of token count for text.
    
    Uses 1.3 words per token as a rough estimate.
    """
    return int(len(text.split()) * 1.3)


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
) -> EmbeddingResult | None:
    """Generate embedding for a conversation (legacy single-embedding).
    
    DEPRECATED: Use embed_conversation_full() for multi-type embeddings.
    
    Args:
        conv_dir: Path to conversation directory
        model: Model name (uses EMBEDDING_MODEL env var if None)
    
    Returns:
        EmbeddingResult or None if conversation has no content
    """
    from ohtv.analysis.cache import load_events
    
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
    from ohtv.db.stores import EmbeddingStore, GitRefStore
    
    conv_id = conv_dir.name
    store = EmbeddingStore(conn)
    stats = EmbeddingStats(conversation_id=conv_id)
    
    # Load events
    events = load_events(conv_dir)
    if not events:
        log.debug("No events in conversation %s", conv_id)
        return stats
    
    # Load analysis if not provided
    if analysis is None:
        analysis = load_analysis(conv_dir)
    
    # Load refs if not provided
    if refs is None:
        try:
            ref_store = GitRefStore(conn)
            ref_rows = ref_store.list_for_conversation(conv_id)
            refs = [
                {"ref_type": r.ref_type, "url": r.url}
                for r in ref_rows
            ]
        except Exception:
            refs = []
    
    # Build all text components
    texts = build_conversation_texts(events, analysis, refs)
    
    if model is None:
        model = get_embedding_model()
    
    # Embed analysis (if available)
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
    
    # Embed summary
    if texts.summary_text:
        if not skip_existing or not store.has_embedding(conv_id, "summary"):
            result = get_embedding(texts.summary_text, model=model)
            store.upsert(
                conversation_id=conv_id,
                embedding=result.embedding,
                model=result.model,
                embed_type="summary",
                chunk_index=0,
                token_count=result.token_count,
                source_text=texts.summary_text,
            )
            stats.summary_tokens = result.token_count
            stats.embeddings_created += 1
    
    # Embed content chunks
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
    
    events = load_events(conv_dir)
    if not events:
        return 0, 0
    
    if analysis is None:
        analysis = load_analysis(conv_dir)
    
    texts = build_conversation_texts(events, analysis, refs)
    
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
