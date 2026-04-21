"""Analysis module for extracting insights from conversations using LLM."""

from ohtv.analysis.cache import (
    AnalysisCacheManager,
    CachedAnalysis,
    compute_content_hash,
    load_events,
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
    # Objective analysis
    "AnalysisResult",
    "ContextLevel",
    "DetailLevel",
    "Objective",
    "ObjectiveAnalysis",
    "ObjectiveStatus",
    "analyze_objectives",
    "get_cached_analysis",
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
