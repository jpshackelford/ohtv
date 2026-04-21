"""Embedding client for LiteLLM API calls.

Handles configuration, API interaction, and result types.
"""

import logging
import os
from dataclasses import dataclass

import litellm

# Suppress LiteLLM info messages that spam output during batch operations
litellm.suppress_debug_info = True

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
    cost_per_million = KNOWN_COSTS.get(model, 0.02)
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
    if model is None:
        model = get_embedding_model()

    api_key = os.environ.get("LLM_API_KEY")
    api_base = os.environ.get("LLM_BASE_URL")

    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY environment variable not set. "
            "This is required for embedding generation."
        )

    # When using a LiteLLM proxy (api_base is set), strip the provider prefix
    # The proxy handles routing based on model name alone
    request_model = model
    if api_base and "/" in model:
        request_model = model.split("/", 1)[1]

    log.debug("Getting embedding with model %s", request_model)

    try:
        response = litellm.embedding(
            model=request_model,
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
