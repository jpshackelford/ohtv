"""Embedding generation for semantic search.

Uses LiteLLM for embeddings through the same proxy as the chat/gen commands.
This means the same LLM_API_KEY and LLM_BASE_URL work for both.

Environment variables:
- EMBEDDING_MODEL: Model to use (default: openai/text-embedding-3-small)
- LLM_API_KEY: API key for LiteLLM proxy
- LLM_BASE_URL: Base URL for LiteLLM proxy (optional)
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("ohtv")

DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"

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


def build_lean_transcript(events: list[dict]) -> str:
    """Build a lean transcript for embedding (user messages + finish blocks).
    
    This is the "lean index" approach from the issue:
    - User messages
    - Finish blocks (agent's final summary)
    - Thinking blocks
    
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


def embed_conversation(
    conv_dir: Path,
    model: str | None = None,
) -> EmbeddingResult | None:
    """Generate embedding for a conversation.
    
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
