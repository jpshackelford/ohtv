"""Embedding client for LiteLLM and Ollama API calls.

Handles configuration, API interaction, and result types.

Supports two modes:
- LiteLLM: Uses LLM_API_KEY and LLM_BASE_URL for cloud embeddings
- Ollama: Uses local Ollama server (set EMBEDDING_MODEL=ollama/nomic-embed-text)

Includes a global rate limiter that coordinates backoff across all threads
when errors are encountered.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass

import litellm

# Suppress LiteLLM info messages that spam output during batch operations
litellm.suppress_debug_info = True

log = logging.getLogger("ohtv")


class GlobalRateLimiter:
    """Thread-safe global rate limiter with exponential backoff.
    
    When any thread encounters an error (429, 500, etc.), all threads
    pause for the backoff period. This prevents thundering herd issues
    where all threads retry simultaneously.
    
    Usage:
        limiter = GlobalRateLimiter()
        
        # Before making a request
        limiter.wait_if_needed()
        
        # After an error
        limiter.record_error()
        
        # After success (optional, resets backoff)
        limiter.record_success()
    """
    
    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, max_retries: int = 5):
        self._lock = threading.Lock()
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._max_retries = max_retries
        self._consecutive_errors = 0
        self._blocked_until = 0.0  # timestamp when we can proceed
    
    def wait_if_needed(self) -> None:
        """Wait if we're in a backoff period."""
        with self._lock:
            now = time.time()
            if now < self._blocked_until:
                wait_time = self._blocked_until - now
                log.debug("Rate limiter: waiting %.1fs before next request", wait_time)
        
        # Wait outside the lock so other threads can also check
        now = time.time()
        if now < self._blocked_until:
            time.sleep(self._blocked_until - now)
    
    def record_error(self, error_code: int | None = None) -> bool:
        """Record an error and set backoff. Returns True if should retry."""
        with self._lock:
            self._consecutive_errors += 1
            
            if self._consecutive_errors > self._max_retries:
                log.warning("Rate limiter: max retries (%d) exceeded", self._max_retries)
                return False
            
            # Calculate exponential backoff with jitter
            delay = min(
                self._base_delay * (2 ** (self._consecutive_errors - 1)),
                self._max_delay
            )
            # Add some jitter (±20%) to prevent synchronized retries
            import random
            delay *= (0.8 + random.random() * 0.4)
            
            self._blocked_until = time.time() + delay
            
            log.warning(
                "Rate limiter: error %s (attempt %d/%d), backing off %.1fs",
                error_code or "unknown",
                self._consecutive_errors,
                self._max_retries,
                delay
            )
            return True
    
    def record_success(self) -> None:
        """Record a success - resets consecutive error count."""
        with self._lock:
            if self._consecutive_errors > 0:
                log.debug("Rate limiter: success after %d errors, resetting", self._consecutive_errors)
            self._consecutive_errors = 0
    
    def get_retry_count(self) -> int:
        """Get current consecutive error count."""
        with self._lock:
            return self._consecutive_errors


# Global rate limiter shared by all embedding threads
# With 10 retries and 30s max delay, we'll wait up to ~3 minutes for recovery
_rate_limiter = GlobalRateLimiter(base_delay=1.0, max_delay=30.0, max_retries=10)


def reset_rate_limiter() -> None:
    """Reset the global rate limiter state.
    
    Call this at the start of a new embedding operation to clear any
    accumulated error state from previous operations.
    """
    global _rate_limiter
    _rate_limiter = GlobalRateLimiter(base_delay=1.0, max_delay=30.0, max_retries=10)

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
    
    Uses global rate limiter to coordinate backoff across all threads
    when errors are encountered.
    
    Args:
        text: Text to embed
        model: Model name (e.g., 'ollama/nomic-embed-text')
    
    Returns:
        EmbeddingResult with embedding vector and metadata
    """
    import urllib.request
    import urllib.error
    import json
    
    # Strip 'ollama/' prefix for the API call
    ollama_model = model.split("/", 1)[1] if "/" in model else model
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    
    # nomic-embed-text has 2048 token context (from model_info)
    # BERT tokenizer averages ~4 chars/token, so ~8000 chars max
    # But we see failures at 6342 chars, so use conservative 4000 char limit
    MAX_CHARS = 4000
    original_len = len(text)
    if original_len > MAX_CHARS:
        # Truncate at word boundary to avoid cutting mid-word
        truncate_at = text.rfind(' ', 0, MAX_CHARS)
        if truncate_at > MAX_CHARS * 0.8:  # Don't lose too much content
            text = text[:truncate_at]
        else:
            text = text[:MAX_CHARS]
        log.debug("Truncated text from %d to %d chars for Ollama (2048 token limit)", original_len, len(text))
    
    text_len = len(text)
    log.debug("Getting Ollama embedding with model %s from %s (text length: %d chars)", ollama_model, ollama_url, text_len)
    
    request_data = json.dumps({
        "model": ollama_model,
        "prompt": text,
    }).encode("utf-8")
    
    last_error = None
    
    while True:
        # Wait if global rate limiter says we should back off
        _rate_limiter.wait_if_needed()
        
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
            
            # Success - reset the global rate limiter
            _rate_limiter.record_success()
            
            # Rough estimate: ~1.3 tokens per word (Ollama doesn't report token usage)
            # Precision matters less for local/free models than for paid APIs
            token_count = int(len(text.split()) * 1.3)
            
            return EmbeddingResult(
                embedding=embedding,
                token_count=token_count,
                model=model,
                dimensions=len(embedding),
            )
        except urllib.error.HTTPError as e:
            last_error = e
            # Try to read the error response body for more details
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            log.debug("Ollama HTTP %d error: %s", e.code, error_body or str(e))
            
            # Retry on 429 (rate limit) or 500-599 (server errors)
            if e.code == 429 or (500 <= e.code < 600):
                should_retry = _rate_limiter.record_error(e.code)
                if should_retry:
                    continue
            
            raise RuntimeError(
                f"Ollama connection failed: HTTP {e.code}. Body: {error_body}. "
                f"Is Ollama running? Try: ollama serve"
            ) from e
        except urllib.error.URLError as e:
            last_error = e
            # Connection errors might be transient - try backing off
            should_retry = _rate_limiter.record_error(None)
            if should_retry:
                log.debug("Ollama connection error, will retry: %s", e)
                continue
            raise RuntimeError(
                f"Ollama connection failed: {e}. "
                f"Is Ollama running? Try: ollama serve"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Ollama embedding failed: {e}") from e
    
    # Should not reach here, but just in case
    raise RuntimeError(f"Ollama embedding failed after retries: {last_error}")


def get_embedding(text: str, model: str | None = None) -> EmbeddingResult:
    """Get embedding for text using LiteLLM or Ollama.

    Uses LLM_API_KEY and LLM_BASE_URL for cloud embeddings,
    or local Ollama server for ollama/* models.
    
    Uses global rate limiter to coordinate backoff across all threads.

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

    last_error = None
    
    while True:
        # Wait if global rate limiter says we should back off
        _rate_limiter.wait_if_needed()
        
        try:
            response = litellm.embedding(
                model=model,
                input=[text],
                api_key=api_key,
                api_base=api_base,
            )
            
            # Success - reset the rate limiter
            _rate_limiter.record_success()
            
            embedding = response.data[0]["embedding"]
            token_count = response.usage.total_tokens
            dimensions = len(embedding)

            return EmbeddingResult(
                embedding=embedding,
                token_count=token_count,
                model=model,
                dimensions=dimensions,
            )
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            
            # Check for rate limit or server errors that should trigger backoff
            is_rate_limit = "429" in error_str or "rate" in error_str or "limit" in error_str
            is_server_error = "500" in error_str or "502" in error_str or "503" in error_str or "504" in error_str
            
            if is_rate_limit or is_server_error:
                error_code = 429 if is_rate_limit else 500
                should_retry = _rate_limiter.record_error(error_code)
                if should_retry:
                    log.debug("LiteLLM error, will retry: %s", e)
                    continue
            
            raise RuntimeError(f"Embedding API call failed: {e}") from e
    
    # Should not reach here
    raise RuntimeError(f"Embedding API call failed after retries: {last_error}")
