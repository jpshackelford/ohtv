"""Aggregate analysis execution for multi-trajectory synthesis.

Implements aggregate mode jobs that synthesize cached results from multiple
conversations into a single output, optionally iterating over time periods.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader

from ohtv.analysis.periods import PeriodInfo, compute_period_state_hash
from ohtv.config import Config, get_ohtv_dir
from ohtv.prompts.metadata import PromptMetadata

log = logging.getLogger("ohtv")


@dataclass
class AggregateItem:
    """A single item in an aggregate analysis, representing one conversation's cached result."""
    conversation_id: str
    created_at: datetime | None
    title: str | None
    result: dict[str, Any]

    def to_dict(self) -> dict:
        """Convert to dict for template rendering."""
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "title": self.title,
            "result": self.result,
        }


@dataclass
class AggregateResult:
    """Result of an aggregate analysis."""
    period: PeriodInfo | None
    result: dict[str, Any]
    items_count: int
    cost: float
    from_cache: bool


def get_cache_key_for_source(
    context: str,
    detail: str,
    assess: bool,
) -> str:
    """Get the cache key used by the source job.
    
    This must match the key format used by analyze_objectives() in objectives.py.
    
    Args:
        context: Context level name (minimal, standard, full)
        detail: Detail level (brief, standard, detailed)
        assess: Whether assessment was included
        
    Returns:
        Cache key string like 'assess=False,context_level=minimal,detail_level=brief'
    """
    return f"assess={assess},context_level={context},detail_level={detail}"


def get_cached_result_for_conversation(
    conv_dir: Path,
    cache_key: str,
) -> dict | None:
    """Load a cached analysis result for a conversation.
    
    Args:
        conv_dir: Path to conversation directory
        cache_key: The cache key for the specific analysis variant
        
    Returns:
        Cached result dict, or None if not cached
    """
    # The cache is stored in objective_analysis.json with multiple analyses keyed by parameters
    cache_file = conv_dir / "objective_analysis.json"
    if not cache_file.exists():
        return None
    
    try:
        data = json.loads(cache_file.read_text())
        analyses = data.get("analyses", {})
        analysis = analyses.get(cache_key)
        if analysis is None:
            return None
        # Return the analysis dict - the caller extracts what it needs (e.g., goal)
        return analysis
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to load cached result from %s: %s", cache_file, e)
        return None


def collect_items_for_period(
    conversations: list[tuple[Path, dict]],
    period: PeriodInfo | None,
    cache_key: str,
) -> list[AggregateItem]:
    """Collect cached results for conversations within a period.
    
    Args:
        conversations: List of (conv_dir, conv_info) tuples
        period: Period to filter by, or None for all conversations
        cache_key: Cache key for the source analysis
        
    Returns:
        List of AggregateItem objects for conversations with cached results
    """
    items = []
    
    for conv_dir, conv_info in conversations:
        # Filter by period if specified
        if period is not None:
            created_at = conv_info.get("created_at")
            if created_at is None:
                continue
            # Handle both datetime and date
            if isinstance(created_at, datetime):
                conv_date = created_at.date()
            elif isinstance(created_at, date):
                conv_date = created_at
            else:
                continue
            
            if not period.contains(conv_date):
                continue
        
        # Load cached result
        cached = get_cached_result_for_conversation(conv_dir, cache_key)
        if cached is None:
            continue
        
        items.append(AggregateItem(
            conversation_id=conv_info.get("id", conv_dir.name),
            created_at=conv_info.get("created_at"),
            title=conv_info.get("title"),
            result=cached,
        ))
    
    return items


def render_aggregate_prompt(
    prompt_meta: PromptMetadata,
    items: list[AggregateItem],
    period: PeriodInfo | None,
) -> str:
    """Render an aggregate prompt template with items and period context.
    
    Args:
        prompt_meta: The aggregate prompt metadata
        items: List of cached results to synthesize
        period: Period metadata (None for non-period aggregates)
        
    Returns:
        Rendered prompt string
    """
    env = Environment(loader=BaseLoader())
    template = env.from_string(prompt_meta.content)
    
    context = {
        "items": [item.to_dict() for item in items],
        "period": period.to_dict() if period else None,
    }
    
    return template.render(**context)


def run_aggregate_llm(
    rendered_prompt: str,
    output_schema: dict | None,
    model: str | None = None,
) -> tuple[dict, float]:
    """Execute the aggregate prompt via LLM.
    
    Args:
        rendered_prompt: The fully rendered prompt string
        output_schema: JSON schema for structured output
        model: LLM model to use (None for default)
        
    Returns:
        Tuple of (result dict, cost in dollars)
    """
    import os
    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
    from openhands.sdk import LLM, Message, TextContent
    
    llm = LLM.load_from_env()
    if model:
        llm = llm.clone(model=model)
    
    # Build messages using SDK Message objects
    messages = [
        Message(
            role="user",
            content=[TextContent(type="text", text=rendered_prompt)],
        )
    ]
    
    # Request structured output if schema provided
    response_format = None
    if output_schema:
        response_format = {"type": "json_schema", "json_schema": {"schema": output_schema}}
    
    response = llm.completion(
        messages=messages,
        response_format=response_format,
    )
    
    # Extract text from response (same pattern as objectives.py)
    response_text = ""
    for content_item in response.message.content:
        if hasattr(content_item, "text"):
            response_text += content_item.text
    
    # Parse response
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        # Return raw content if not valid JSON
        result = {"raw_response": response_text}
    
    # Get cost from response metrics
    cost = 0.0
    if hasattr(response, "metrics") and response.metrics:
        cost = getattr(response.metrics, "accumulated_cost", 0.0) or 0.0
    
    return result, cost


def get_aggregate_cache_dir(config: Config) -> Path:
    """Get the cache directory for aggregate analysis results."""
    return get_ohtv_dir() / "cache" / "aggregate"


def get_aggregate_cache_file(
    config: Config,
    prompt_id: str,
    period: PeriodInfo | None,
    state_hash: str,
) -> Path:
    """Get the cache file path for an aggregate result.
    
    Args:
        config: Config object
        prompt_id: The aggregate prompt ID (e.g., "reports.weekly")
        period: Period info (None for non-period aggregates)
        state_hash: State hash for cache invalidation
        
    Returns:
        Path to cache file
    """
    cache_dir = get_aggregate_cache_dir(config)
    
    # Use period ISO as part of filename, or "all" for non-period
    period_key = period.iso if period else "all"
    
    # Sanitize prompt_id for filename
    safe_prompt_id = prompt_id.replace("/", "_").replace(".", "_")
    
    filename = f"{safe_prompt_id}_{period_key}_{state_hash}.json"
    return cache_dir / filename


def load_aggregate_cache(
    config: Config,
    prompt_id: str,
    period: PeriodInfo | None,
    state_hash: str,
) -> dict | None:
    """Load cached aggregate result if available and valid.
    
    Args:
        config: Config object
        prompt_id: The aggregate prompt ID
        period: Period info
        state_hash: Expected state hash
        
    Returns:
        Cached result dict, or None if not cached/invalid
    """
    cache_file = get_aggregate_cache_file(config, prompt_id, period, state_hash)
    
    if not cache_file.exists():
        return None
    
    try:
        data = json.loads(cache_file.read_text())
        # Verify state hash matches
        if data.get("state_hash") != state_hash:
            log.debug("Aggregate cache state hash mismatch, invalidating")
            return None
        return data.get("result")
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to load aggregate cache: %s", e)
        return None


def save_aggregate_cache(
    config: Config,
    prompt_id: str,
    period: PeriodInfo | None,
    state_hash: str,
    result: dict,
    items_count: int,
) -> None:
    """Save an aggregate result to cache.
    
    Args:
        config: Config object
        prompt_id: The aggregate prompt ID
        period: Period info
        state_hash: State hash for this result
        result: The analysis result
        items_count: Number of items aggregated
    """
    cache_file = get_aggregate_cache_file(config, prompt_id, period, state_hash)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    
    cache_data = {
        "prompt_id": prompt_id,
        "period": period.to_dict() if period else None,
        "state_hash": state_hash,
        "items_count": items_count,
        "result": result,
        "cached_at": datetime.utcnow().isoformat(),
    }
    
    cache_file.write_text(json.dumps(cache_data, indent=2))
    log.debug("Saved aggregate cache to %s", cache_file)


def run_aggregate_analysis(
    config: Config,
    prompt_meta: PromptMetadata,
    conversations: list[tuple[Path, dict]],
    period: PeriodInfo | None,
    source_cache_key: str,
    source_prompt_hash: str,
    model: str | None = None,
    force_refresh: bool = False,
) -> AggregateResult:
    """Run an aggregate analysis for a specific period (or all conversations).
    
    Args:
        config: Config object
        prompt_meta: The aggregate prompt metadata
        conversations: List of (conv_dir, conv_info) tuples
        period: Period to analyze (None for non-period aggregate)
        source_cache_key: Cache key for the source job
        source_prompt_hash: Hash of source prompt content
        model: LLM model to use
        force_refresh: Force re-analysis even if cached
        
    Returns:
        AggregateResult with analysis output
    """
    # Collect items for this period
    items = collect_items_for_period(conversations, period, source_cache_key)
    
    # Check minimum items requirement
    min_items = prompt_meta.input_config.min_items
    if len(items) < min_items:
        log.debug(
            "Period %s has %d items, below minimum %d",
            period.iso if period else "all", len(items), min_items
        )
        # Return empty result for below-minimum periods
        return AggregateResult(
            period=period,
            result={"skipped": True, "reason": f"Below minimum items ({len(items)} < {min_items})"},
            items_count=len(items),
            cost=0.0,
            from_cache=False,
        )
    
    # Compute state hash for caching
    conv_summaries = [
        {"id": info.get("id", d.name), "event_count": info.get("event_count", 0)}
        for d, info in conversations
        if period is None or (
            info.get("created_at") is not None and 
            period.contains(info["created_at"].date() if isinstance(info["created_at"], datetime) else info["created_at"])
        )
    ]
    state_hash = compute_period_state_hash(
        period if period else PeriodInfo("day", date.today(), date.today(), "all", "all"),
        conv_summaries,
        prompt_meta.content_hash,
        source_prompt_hash,
    )
    
    # Check cache
    if not force_refresh:
        cached = load_aggregate_cache(config, prompt_meta.id, period, state_hash)
        if cached is not None:
            log.debug("Using cached aggregate result for %s", period.iso if period else "all")
            return AggregateResult(
                period=period,
                result=cached,
                items_count=len(items),
                cost=0.0,
                from_cache=True,
            )
    
    # Render prompt
    rendered = render_aggregate_prompt(prompt_meta, items, period)
    
    # Run LLM
    result, cost = run_aggregate_llm(rendered, prompt_meta.output_schema, model)
    
    # Cache result (only for period-based aggregates)
    if period is not None:
        save_aggregate_cache(config, prompt_meta.id, period, state_hash, result, len(items))
    
    return AggregateResult(
        period=period,
        result=result,
        items_count=len(items),
        cost=cost,
        from_cache=False,
    )


def ensure_source_cache_populated(
    config: Config,
    conversations: list[tuple[Path, dict]],
    source_prompt_meta: PromptMetadata,
    source_cache_key: str,
    model: str | None = None,
) -> tuple[int, float]:
    """Ensure all conversations have cached results from the source job.
    
    Auto-runs the source job on any conversations without cached results.
    
    Args:
        config: Config object
        conversations: List of (conv_dir, conv_info) tuples
        source_prompt_meta: Metadata for the source prompt
        source_cache_key: Cache key for the source job
        model: LLM model to use
        
    Returns:
        Tuple of (number of new analyses run, total cost)
    """
    from ohtv.analysis import analyze_objectives
    
    uncached = []
    for conv_dir, conv_info in conversations:
        cached = get_cached_result_for_conversation(conv_dir, source_cache_key)
        if cached is None:
            uncached.append((conv_dir, conv_info))
    
    if not uncached:
        return 0, 0.0
    
    log.info("Running source job on %d uncached conversations", len(uncached))
    
    # Extract detail/assess from source variant
    variant = source_prompt_meta.variant
    assess = variant.endswith("_assess")
    detail = variant.replace("_assess", "")
    
    # Determine context from cache key
    # Cache key format: assess=False,context_level=minimal,detail_level=brief
    context = "minimal"
    for part in source_cache_key.split(","):
        if part.startswith("context_level="):
            context = part.split("=")[1]
            break
    
    total_cost = 0.0
    for conv_dir, conv_info in uncached:
        try:
            result = analyze_objectives(
                conv_dir,
                model=model,
                context=context,
                detail=detail,
                assess=assess,
            )
            total_cost += result.cost
        except Exception as e:
            log.warning("Failed to analyze %s: %s", conv_dir.name, e)
    
    return len(uncached), total_cost
