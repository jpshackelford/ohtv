"""Prompt discovery and resolution.

This module discovers prompts from the filesystem and provides functions
to resolve prompts by family and variant.
"""

import logging
from functools import lru_cache
from pathlib import Path

from ohtv.config import get_ohtv_dir
from ohtv.prompts.metadata import ContextLevel, PromptMetadata
from ohtv.prompts.parser import parse_prompt_file

log = logging.getLogger("ohtv")


def get_prompts_dirs() -> list[Path]:
    """Get prompt directories to search (user first, then default).
    
    Returns:
        List of Path objects, with user directory first, then default directory.
        User directory: ~/.ohtv/prompts/
        Default directory: src/ohtv/prompts/ (bundled with package)
    """
    user_dir = get_ohtv_dir() / "prompts"
    default_dir = Path(__file__).parent
    return [user_dir, default_dir]


@lru_cache(maxsize=1)
def discover_prompts() -> dict[str, dict[str, PromptMetadata]]:
    """Discover all prompts organized by family and variant.
    
    Returns:
        Dict mapping family -> variant -> PromptMetadata
        e.g., {"objectives": {"brief": PromptMetadata(...), "detailed": ...}}
    
    Scans both user and default directories.
    User prompts override defaults with the same family/variant.
    
    Results are cached to avoid repeated filesystem scans.
    Call clear_prompt_cache() to invalidate the cache.
    """
    prompts: dict[str, dict[str, PromptMetadata]] = {}
    
    # Search directories in reverse order (default first, user last)
    # so user prompts override defaults
    for prompts_dir in reversed(get_prompts_dirs()):
        if not prompts_dir.exists():
            continue
        
        # Find all .md files in subdirectories (family directories)
        for prompt_file in prompts_dir.rglob("*.md"):
            # Skip files directly in prompts directory (old structure)
            if prompt_file.parent == prompts_dir:
                log.debug("Skipping old-structure prompt: %s", prompt_file)
                continue
            
            try:
                meta = parse_prompt_file(prompt_file)
                
                # Organize by family and variant
                if meta.family not in prompts:
                    prompts[meta.family] = {}
                
                prompts[meta.family][meta.variant] = meta
                log.debug("Discovered prompt: %s.%s from %s", 
                         meta.family, meta.variant, prompt_file)
                
            except Exception as e:
                log.warning("Failed to parse prompt %s: %s", prompt_file, e)
    
    return prompts


def clear_prompt_cache():
    """Clear the cached discovered prompts.
    
    Call this to force a re-scan of the filesystem.
    """
    discover_prompts.cache_clear()


def list_families() -> list[str]:
    """List all available prompt families.
    
    Returns:
        Sorted list of family names
    """
    prompts = discover_prompts()
    return sorted(prompts.keys())


def list_variants(family: str) -> list[str]:
    """List all variants for a family.
    
    Args:
        family: Prompt family name
        
    Returns:
        Sorted list of variant names for the family
        
    Raises:
        ValueError: If family not found
    """
    prompts = discover_prompts()
    if family not in prompts:
        raise ValueError(f"Unknown prompt family: {family}. "
                        f"Available families: {', '.join(list_families())}")
    
    return sorted(prompts[family].keys())


def resolve_prompt(family: str, variant: str | None = None) -> PromptMetadata:
    """Resolve a prompt by family and optional variant.
    
    Args:
        family: Prompt family (e.g., "objectives")
        variant: Variant name (e.g., "brief"). If None, uses default variant
                (marked with default: true in frontmatter).
        
    Returns:
        PromptMetadata for the resolved prompt
        
    Raises:
        ValueError: If family not found, variant not found, or no default variant
    """
    prompts = discover_prompts()
    
    if family not in prompts:
        raise ValueError(f"Unknown prompt family: {family}. "
                        f"Available families: {', '.join(list_families())}")
    
    family_prompts = prompts[family]
    
    # If no variant specified, find the default
    if variant is None:
        defaults = [v for v, meta in family_prompts.items() if meta.default]
        if not defaults:
            raise ValueError(f"No default variant for family '{family}'. "
                           f"Available variants: {', '.join(family_prompts.keys())}")
        if len(defaults) > 1:
            log.warning(
                "Multiple default variants for family '%s': %s. "
                "Using '%s' (first in discovery order). "
                "Mark only one variant as default: true.",
                family, defaults, defaults[0]
            )
        variant = defaults[0]
    
    if variant not in family_prompts:
        raise ValueError(f"Unknown variant '{variant}' for family '{family}'. "
                        f"Available variants: {', '.join(family_prompts.keys())}")
    
    return family_prompts[variant]


def resolve_context(prompt: PromptMetadata, context: int | str | None = None) -> ContextLevel:
    """Resolve a context level for a prompt.
    
    Args:
        prompt: The prompt metadata
        context: Context level number or name. If None, uses prompt's default.
        
    Returns:
        ContextLevel for the resolved context
        
    Raises:
        ValueError: If context level not found
    """
    if context is None:
        context = prompt.default_context
    
    return prompt.get_context_level(context)
