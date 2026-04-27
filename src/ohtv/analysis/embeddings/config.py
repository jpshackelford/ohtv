"""Embedding configuration detection and wizard.

Provides auto-detection of available embedding providers and a wizard
to help users configure embedding support.

Supports:
- Cloud providers via LiteLLM (OpenAI, Mistral, etc.) using LLM_API_KEY
- Local Ollama server for free/offline embeddings
"""

import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

log = logging.getLogger("ohtv")


class EmbeddingProvider(Enum):
    """Available embedding providers."""
    OPENAI = "openai"
    OLLAMA = "ollama"
    LITELLM = "litellm"  # Generic LiteLLM with custom base URL
    NONE = "none"


@dataclass
class EmbeddingConfig:
    """Current embedding configuration."""
    provider: EmbeddingProvider
    model: str | None
    source: str  # "env", "file", "detected", "none"
    is_working: bool | None = None  # None = not tested
    error: str | None = None
    
    @property
    def is_configured(self) -> bool:
        return self.provider != EmbeddingProvider.NONE and self.model is not None


@dataclass 
class OllamaStatus:
    """Status of local Ollama server."""
    is_running: bool
    host: str
    available_models: list[str]
    error: str | None = None


# Recommended Ollama models for embeddings (in preference order)
RECOMMENDED_OLLAMA_MODELS = [
    "nomic-embed-text",  # Good quality, 768 dims, fast
    "mxbai-embed-large",  # Higher quality, 1024 dims
    "all-minilm",  # Smallest/fastest, 384 dims
    "bge-m3",  # Multilingual, 1024 dims
]


def get_ollama_host() -> str:
    """Get Ollama host URL from env or default."""
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def detect_ollama() -> OllamaStatus:
    """Detect if Ollama is running and what models are available.
    
    Returns:
        OllamaStatus with connection info and available embedding models
    """
    host = get_ollama_host()
    
    try:
        # Check if Ollama is responding
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        # Extract model names that are embedding models
        all_models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
        
        # Filter to embedding-capable models
        embedding_models = [m for m in all_models if m in RECOMMENDED_OLLAMA_MODELS]
        
        # Also check for any model with "embed" in the name
        for m in all_models:
            if "embed" in m.lower() and m not in embedding_models:
                embedding_models.append(m)
        
        return OllamaStatus(
            is_running=True,
            host=host,
            available_models=embedding_models,
            error=None,
        )
        
    except urllib.error.URLError as e:
        return OllamaStatus(
            is_running=False,
            host=host,
            available_models=[],
            error=f"Cannot connect to Ollama at {host}: {e.reason}",
        )
    except Exception as e:
        return OllamaStatus(
            is_running=False,
            host=host,
            available_models=[],
            error=str(e),
        )


def test_ollama_embedding(model: str, host: str | None = None) -> tuple[bool, str | None]:
    """Test if an Ollama model can generate embeddings.
    
    Args:
        model: Model name (without ollama/ prefix)
        host: Ollama host URL (uses default if None)
    
    Returns:
        Tuple of (success, error_message)
    """
    if host is None:
        host = get_ollama_host()
    
    test_text = "Test embedding generation"
    
    try:
        request_data = json.dumps({
            "model": model,
            "prompt": test_text,
        }).encode("utf-8")
        
        req = urllib.request.Request(
            f"{host}/api/embeddings",
            data=request_data,
            headers={"Content-Type": "application/json"},
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        
        embedding = result.get("embedding", [])
        if not embedding:
            return False, "Model returned empty embedding"
        
        return True, None
        
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        return False, f"HTTP {e.code}: {error_body or str(e)}"
    except urllib.error.URLError as e:
        return False, f"Connection failed: {e.reason}"
    except Exception as e:
        return False, str(e)


def test_litellm_embedding(model: str) -> tuple[bool, str | None]:
    """Test if a LiteLLM model can generate embeddings.
    
    Args:
        model: Full model name (e.g., "openai/text-embedding-3-small")
    
    Returns:
        Tuple of (success, error_message)
    """
    api_key = os.environ.get("LLM_API_KEY")
    api_base = os.environ.get("LLM_BASE_URL")
    
    if not api_key:
        return False, "LLM_API_KEY environment variable not set"
    
    try:
        import litellm
        litellm.suppress_debug_info = True
        
        response = litellm.embedding(
            model=model,
            input=["Test embedding generation"],
            api_key=api_key,
            api_base=api_base,
        )
        
        embedding = response.data[0]["embedding"]
        if not embedding:
            return False, "Model returned empty embedding"
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def get_current_config() -> EmbeddingConfig:
    """Get the current embedding configuration from env and config file.
    
    Checks in order:
    1. EMBEDDING_MODEL environment variable
    2. embedding_model in config file
    3. Detects from LLM_API_KEY if available
    
    Returns:
        EmbeddingConfig with current state
    """
    # Check environment variable first
    env_model = os.environ.get("EMBEDDING_MODEL")
    if env_model:
        if env_model.startswith("ollama/"):
            return EmbeddingConfig(
                provider=EmbeddingProvider.OLLAMA,
                model=env_model,
                source="env",
            )
        else:
            return EmbeddingConfig(
                provider=EmbeddingProvider.LITELLM,
                model=env_model,
                source="env",
            )
    
    # Check config file
    from ohtv.config import get_config_file_path
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    config_path = get_config_file_path()
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                file_config = tomllib.load(f)
            file_model = file_config.get("embedding_model")
            if file_model:
                if file_model.startswith("ollama/"):
                    return EmbeddingConfig(
                        provider=EmbeddingProvider.OLLAMA,
                        model=file_model,
                        source="file",
                    )
                else:
                    return EmbeddingConfig(
                        provider=EmbeddingProvider.LITELLM,
                        model=file_model,
                        source="file",
                    )
        except Exception:
            pass
    
    # Check if LLM_API_KEY is set (implies cloud embedding might work)
    if os.environ.get("LLM_API_KEY"):
        return EmbeddingConfig(
            provider=EmbeddingProvider.LITELLM,
            model="openai/text-embedding-3-small",  # Default
            source="detected",
        )
    
    return EmbeddingConfig(
        provider=EmbeddingProvider.NONE,
        model=None,
        source="none",
    )


def test_current_config() -> EmbeddingConfig:
    """Get current config and test if it works.
    
    Returns:
        EmbeddingConfig with is_working and error populated
    """
    config = get_current_config()
    
    if not config.is_configured:
        config.is_working = False
        config.error = "No embedding model configured"
        return config
    
    if config.provider == EmbeddingProvider.OLLAMA:
        # Extract model name without ollama/ prefix
        model_name = config.model.split("/", 1)[1] if "/" in config.model else config.model
        success, error = test_ollama_embedding(model_name)
        config.is_working = success
        config.error = error
    else:
        success, error = test_litellm_embedding(config.model)
        config.is_working = success
        config.error = error
    
    return config


def save_embedding_config(model: str, ollama_host: str | None = None) -> None:
    """Save embedding configuration to config file.
    
    Args:
        model: Full model name (e.g., "ollama/nomic-embed-text" or "openai/text-embedding-3-small")
        ollama_host: Optional Ollama host URL to save
    """
    from ohtv.config import get_config_file_path
    
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    config_path = get_config_file_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing config
    existing = {}
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                existing = tomllib.load(f)
        except Exception:
            pass
    
    # Update embedding config
    existing["embedding_model"] = model
    if ollama_host and ollama_host != "http://localhost:11434":
        existing["ollama_host"] = ollama_host
    
    # Write back as TOML
    lines = ["# ohtv configuration", "# See 'ohtv config --help' for available settings", ""]
    for key, value in sorted(existing.items()):
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    lines.append("")
    config_path.write_text("\n".join(lines))


def get_effective_embedding_model() -> str | None:
    """Get the effective embedding model to use.
    
    Checks env var first, then config file. Returns None if not configured.
    This is the function that should be used by embedding operations.
    """
    # Environment variable takes precedence
    env_model = os.environ.get("EMBEDDING_MODEL")
    if env_model:
        return env_model
    
    # Check config file
    from ohtv.config import get_config_file_path
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    config_path = get_config_file_path()
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                file_config = tomllib.load(f)
            return file_config.get("embedding_model")
        except Exception:
            pass
    
    return None


def is_embedding_configured() -> bool:
    """Check if embedding is configured (either via env or config file).
    
    This does NOT test if the configuration works, just if something is set.
    """
    # Check EMBEDDING_MODEL env var
    if os.environ.get("EMBEDDING_MODEL"):
        return True
    
    # Check LLM_API_KEY (implies default model can be used)
    if os.environ.get("LLM_API_KEY"):
        return True
    
    # Check config file
    model = get_effective_embedding_model()
    return model is not None
