"""Tests for embedding-specific env var overrides.

Embeddings can be routed to a different LiteLLM proxy / OpenAI-compatible
endpoint than chat models by setting EMBEDDING_API_KEY / EMBEDDING_BASE_URL.
When those are unset, the embedding helpers fall back to LLM_API_KEY /
LLM_BASE_URL (the historical behavior).
"""

import pytest

from ohtv.analysis.embeddings.config import (
    get_effective_embedding_api_key,
    get_effective_embedding_base_url,
    is_embedding_configured,
)


@pytest.fixture(autouse=True)
def _clear_embedding_env(monkeypatch):
    """Ensure each test starts with a clean env for the relevant vars."""
    for k in ("EMBEDDING_API_KEY", "EMBEDDING_BASE_URL", "LLM_API_KEY", "LLM_BASE_URL", "EMBEDDING_MODEL"):
        monkeypatch.delenv(k, raising=False)


class TestEffectiveEmbeddingApiKey:
    def test_returns_none_when_nothing_set(self):
        assert get_effective_embedding_api_key() is None

    def test_falls_back_to_llm_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-fallback")
        assert get_effective_embedding_api_key() == "sk-fallback"

    def test_prefers_embedding_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-fallback")
        monkeypatch.setenv("EMBEDDING_API_KEY", "sk-embed")
        assert get_effective_embedding_api_key() == "sk-embed"

    def test_embedding_only_when_no_llm(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_API_KEY", "sk-embed")
        assert get_effective_embedding_api_key() == "sk-embed"


class TestEffectiveEmbeddingBaseUrl:
    def test_returns_none_when_nothing_set(self):
        assert get_effective_embedding_base_url() is None

    def test_falls_back_to_llm_base_url(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "https://chat.example.com")
        assert get_effective_embedding_base_url() == "https://chat.example.com"

    def test_prefers_embedding_base_url(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "https://chat.example.com")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embed.example.com")
        assert get_effective_embedding_base_url() == "https://embed.example.com"


class TestIsEmbeddingConfigured:
    def test_false_when_nothing_set(self):
        assert is_embedding_configured() is False

    def test_true_when_only_embedding_api_key_set(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_API_KEY", "sk-embed")
        assert is_embedding_configured() is True

    def test_true_when_only_llm_api_key_set(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-fallback")
        assert is_embedding_configured() is True

    def test_true_when_embedding_model_env_set(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "ollama/nomic-embed-text")
        assert is_embedding_configured() is True


class TestClientUsesEffectiveCredentials:
    """get_embedding() must use EMBEDDING_* env vars when set, else LLM_*."""

    def test_get_embedding_uses_embedding_env_when_set(self, monkeypatch):
        from ohtv.analysis.embeddings import client as embed_client

        captured: dict = {}

        class _Resp:
            data = [{"embedding": [0.1, 0.2, 0.3]}]
            usage = type("U", (), {"total_tokens": 4})()

        def _fake_litellm_embedding(model, input, api_key, api_base):
            captured["model"] = model
            captured["api_key"] = api_key
            captured["api_base"] = api_base
            return _Resp()

        monkeypatch.setenv("LLM_API_KEY", "sk-chat")
        monkeypatch.setenv("LLM_BASE_URL", "https://chat.example.com")
        monkeypatch.setenv("EMBEDDING_API_KEY", "sk-embed")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embed.example.com")

        monkeypatch.setattr(embed_client.litellm, "embedding", _fake_litellm_embedding)

        result = embed_client.get_embedding("hello", model="openai/text-embedding-3-small")

        assert result.embedding == [0.1, 0.2, 0.3]
        assert captured["api_key"] == "sk-embed"
        assert captured["api_base"] == "https://embed.example.com"

    def test_get_embedding_falls_back_to_llm_env(self, monkeypatch):
        from ohtv.analysis.embeddings import client as embed_client

        captured: dict = {}

        class _Resp:
            data = [{"embedding": [0.4]}]
            usage = type("U", (), {"total_tokens": 2})()

        def _fake_litellm_embedding(model, input, api_key, api_base):
            captured["api_key"] = api_key
            captured["api_base"] = api_base
            return _Resp()

        monkeypatch.setenv("LLM_API_KEY", "sk-chat")
        monkeypatch.setenv("LLM_BASE_URL", "https://chat.example.com")

        monkeypatch.setattr(embed_client.litellm, "embedding", _fake_litellm_embedding)

        embed_client.get_embedding("hello", model="openai/text-embedding-3-small")

        assert captured["api_key"] == "sk-chat"
        assert captured["api_base"] == "https://chat.example.com"

    def test_get_embedding_raises_when_no_key(self, monkeypatch):
        from ohtv.analysis.embeddings import client as embed_client

        with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
            embed_client.get_embedding("hello", model="openai/text-embedding-3-small")
