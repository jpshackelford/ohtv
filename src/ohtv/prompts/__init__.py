"""Prompt management for ohtv.

This module provides both the legacy prompt management functions and the new
discovery-based prompt system with family/variant organization.

Legacy usage (backward compatible):
    from ohtv.prompts import get_prompt, get_prompt_hash
    
    prompt = get_prompt("brief")  # Gets the brief analysis prompt
    hash = get_prompt_hash("brief")  # Gets hash for cache invalidation

New discovery-based usage:
    from ohtv.prompts import discover_prompts, resolve_prompt, resolve_context
    
    # Discover all prompts organized by family/variant
    prompts = discover_prompts()
    
    # Resolve a specific prompt (with optional variant)
    meta = resolve_prompt("objectives", "brief")
    meta = resolve_prompt("objectives")  # Uses default variant
    
    # Resolve a context level
    ctx = resolve_context(meta, 1)  # By number
    ctx = resolve_context(meta, "minimal")  # By name
"""

# Legacy functions - for backward compatibility
from ohtv.prompts._legacy import (
    PROMPT_NAMES,
    get_default_prompts_dir,
    get_prompt,
    get_prompt_hash,
    get_user_prompts_dir,
    init_user_prompts,
    list_prompts,
)

# New discovery-based functions
from ohtv.prompts.discovery import (
    clear_prompt_cache,
    discover_prompts,
    get_prompts_dirs,
    list_families,
    list_variants,
    resolve_context,
    resolve_prompt,
)

# Metadata types
from ohtv.prompts.metadata import ContextLevel, EventFilter, PromptMetadata

# Parser functions (for advanced usage)
from ohtv.prompts.parser import parse_prompt_file

__all__ = [
    # Legacy API
    "PROMPT_NAMES",
    "get_default_prompts_dir",
    "get_prompt",
    "get_prompt_hash",
    "get_user_prompts_dir",
    "init_user_prompts",
    "list_prompts",
    # Discovery API
    "clear_prompt_cache",
    "discover_prompts",
    "get_prompts_dirs",
    "list_families",
    "list_variants",
    "resolve_context",
    "resolve_prompt",
    # Metadata types
    "ContextLevel",
    "EventFilter",
    "PromptMetadata",
    # Parser
    "parse_prompt_file",
]
