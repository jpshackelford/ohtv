"""Embedding client for LiteLLM and Ollama API calls.

Handles configuration, API interaction, and result types.

Supports two modes:
- LiteLLM: Uses LLM_API_KEY and LLM_BASE_URL for cloud embeddings
- Ollama: Uses local Ollama server (set EMBEDDING_MODEL=ollama/nomic-embed-text)
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
    # Ollama models
    "ollama/nomic-embed-text": 768,
    "ollama/mxbai-embed-large": 1024,
    "ollama/all-minilm": 384,
    "ollama/bge-m3": 1024,
}

# Cost per 1M tokens for known models (Ollama models are free/local)
KNOWN_COSTS: dict[str, float] = {
    "openai/text-embedding-3-small": 0.02,
    "openai/text-embedding-3-large": 0.13,
    "mistral/mistral-embed": 0.10,
    "gemini/gemini-embedding-001": 0.15,
    "bedrock/cohere.embed-english-v3": 0.10,
    # Ollama models are free (local)
    "ollama/nomic-embed-text": 0.0,
    "ollama/mxbai-embed-large": 0.0,
    "ollama/all-minilm": 0.0,
    "ollama/bge-m3": 0.0,
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


def _get_ollama_embedding(text: str, model: str) -> EmbeddingResult:
    """Get embedding from local Ollama server.
    
    Args:
        text: Text to embed
        model: Model name (e.g., 'ollama/nomic-embed-text')
    
    Returns:
        EmbeddingResult with embedding vector and metadata
    """
    import time
    import urllib.request
    import urllib.error
    import json
    
    # Strip 'ollama/' prefix for the API call
    ollama_model = model.split("/", 1)[1] if "/" in model else model
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    
    text_len = len(text)
    log.debug("Getting Ollama embedding with model %s from %s (text length: %d chars)", ollama_model, ollama_url, text_len)
    
    request_data = json.dumps({
        "model": ollama_model,
        "prompt": text,
    }).encode("utf-8")
    
    # Retry logic for transient Ollama errors (500s when overloaded)
    max_retries = 3
    retry_delay = 1.0  # seconds
    last_error = None
    
    for attempt in range(max_retries):
        req = urllib.request.Request(
            f"{ollama_url}/api/embeddings",
            data=request_data,
            headers={"Content-Type": "application/json"},
        )
        
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
            
            embedding = result.get("embedding", [])
            if not embedding:
                raise RuntimeError(f"Ollama returned empty embedding. Response: {result}")
            
            # Estimate token count (Ollama doesn't return this)
            token_count = int(len(text.split()) * 1.3)
            
            return EmbeddingResult(
                embedding=embedding,
                token_count=token_count,
                model=model,
                dimensions=len(embedding),
            )
        except urllib.error.HTTPError as e:
            last_error = e
            # Retry on 500 errors (Ollama overloaded)
            if e.code == 500 and attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise RuntimeError(
                f"Ollama connection failed: {e}. "
                f"Is Ollama running? Try: ollama serve"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Ollama connection failed: {e}. "
                f"Is Ollama running? Try: ollama serve"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Ollama embedding failed: {e}") from e
    
    # Should not reach here, but just in case
    raise RuntimeError(f"Ollama embedding failed after {max_retries} retries: {last_error}")


def get_embedding(text: str, model: str | None = None) -> EmbeddingResult:
    """Get embedding for text using LiteLLM or Ollama.

    Uses LLM_API_KEY and LLM_BASE_URL for cloud embeddings,
    or local Ollama server for ollama/* models.

    Args:
        text: Text to embed
        model: Model name (uses EMBEDDING_MODEL env var if None)
               Use 'ollama/nomic-embed-text' for local Ollama embeddings

    Returns:
        EmbeddingResult with embedding vector and metadata

    Raises:
        RuntimeError: If configuration is missing or API call fails
    """
    if model is None:
        model = get_embedding_model()

    # Use Ollama for ollama/* models
    if model.startswith("ollama/"):
        return _get_ollama_embedding(text, model)

    # Use LiteLLM for cloud models
    api_key = os.environ.get("LLM_API_KEY")
    api_base = os.environ.get("LLM_BASE_URL")

    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY environment variable not set. "
            "This is required for embedding generation. "
            "Or use EMBEDDING_MODEL=ollama/nomic-embed-text for local embeddings."
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
