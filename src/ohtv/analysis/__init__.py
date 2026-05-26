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
from ohtv.analysis.titles import (
    DEFAULT_BATCH_SIZE as TITLES_DEFAULT_BATCH_SIZE,
    MAX_TITLE_CHARS,
    TitleGenerationResult,
    description_from_analysis,
    generate_titles_batch,
    is_placeholder_title,
    parse_titles_response,
)
from ohtv.analysis.periods import (
    PeriodInfo,
    iterate_periods,
    get_last_n_periods,
    compute_period_state_hash,
)
from ohtv.analysis.aggregate import (
    AggregateItem,
    AggregateResult,
    run_aggregate_analysis,
    ensure_source_cache_populated,
    get_cache_key_for_source,
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
    # Title generation
    "MAX_TITLE_CHARS",
    "TITLES_DEFAULT_BATCH_SIZE",
    "TitleGenerationResult",
    "description_from_analysis",
    "generate_titles_batch",
    "is_placeholder_title",
    "parse_titles_response",
    # Period utilities
    "PeriodInfo",
    "iterate_periods",
    "get_last_n_periods",
    "compute_period_state_hash",
    # Aggregate analysis
    "AggregateItem",
    "AggregateResult",
    "run_aggregate_analysis",
    "ensure_source_cache_populated",
    "get_cache_key_for_source",
]
