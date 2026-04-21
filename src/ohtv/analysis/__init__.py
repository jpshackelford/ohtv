"""Analysis module for extracting insights from conversations using LLM."""

from ohtv.analysis.cache import (
    AnalysisCacheManager,
    CachedAnalysis,
    compute_content_hash,
    load_events,
)
from ohtv.analysis.embeddings import (
    EmbeddingResult,
    build_lean_transcript,
    check_embedding_status,
    embed_conversation,
    estimate_cost,
    estimate_tokens,
    get_embedding,
    get_embedding_dimension,
    get_embedding_model,
)
from ohtv.analysis.objectives import (
    AnalysisResult,
    ContextLevel,
    DetailLevel,
    Objective,
    ObjectiveAnalysis,
    ObjectiveStatus,
    analyze_objectives,
    get_cached_analysis,
)

__all__ = [
    # Cache infrastructure
    "AnalysisCacheManager",
    "CachedAnalysis",
    "compute_content_hash",
    "load_events",
    # Embeddings
    "EmbeddingResult",
    "build_lean_transcript",
    "check_embedding_status",
    "embed_conversation",
    "estimate_cost",
    "estimate_tokens",
    "get_embedding",
    "get_embedding_dimension",
    "get_embedding_model",
    # Objective analysis
    "AnalysisResult",
    "ContextLevel",
    "DetailLevel",
    "Objective",
    "ObjectiveAnalysis",
    "ObjectiveStatus",
    "analyze_objectives",
    "get_cached_analysis",
]
