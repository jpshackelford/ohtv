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

from typing import Literal

# Client exports
from .client import (
    DEFAULT_EMBEDDING_MODEL,
    KNOWN_COSTS,
    KNOWN_DIMENSIONS,
    EmbeddingResult,
    estimate_cost,
    get_embedding,
    get_embedding_dimension,
    get_embedding_model,
)

# Text building exports
from .text_builders import (
    ConversationMetadata,
    ConversationTexts,
    TextChunk,
    build_analysis_text,
    build_content_text,
    build_conversation_texts,
    build_lean_transcript,
    build_summary_text,
)

# Chunking exports
from .chunking import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    chunk_text,
    estimate_tokens,
)

# Operations exports
from .operations import (
    EmbeddingBatch,
    EmbeddingStats,
    EmbeddingWriter,
    PendingEmbedding,
    check_embedding_status,
    check_embedding_types,
    embed_conversation,
    embed_conversation_full,
    estimate_conversation_tokens,
    generate_embeddings_only,
)

EmbedType = Literal["analysis", "summary", "content"]

__all__ = [
    # Types
    "EmbedType",
    "EmbeddingResult",
    "EmbeddingStats",
    "TextChunk",
    "ConversationTexts",
    "ConversationMetadata",
    # Constants
    "DEFAULT_EMBEDDING_MODEL",
    "KNOWN_COSTS",
    "KNOWN_DIMENSIONS",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    # Client
    "get_embedding",
    "get_embedding_model",
    "get_embedding_dimension",
    "estimate_cost",
    # Text builders
    "build_analysis_text",
    "build_summary_text",
    "build_content_text",
    "build_lean_transcript",
    "build_conversation_texts",
    # Chunking
    "chunk_text",
    "estimate_tokens",
    # Operations
    "embed_conversation",
    "embed_conversation_full",
    "generate_embeddings_only",
    "estimate_conversation_tokens",
    "check_embedding_status",
    "check_embedding_types",
    "EmbeddingBatch",
    "PendingEmbedding",
    "EmbeddingWriter",
]
