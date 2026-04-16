# Phase 3: Prompt Discovery & Loading

## Overview

Implement prompt discovery from the filesystem and integrate the new metadata-driven system with the existing codebase. This phase bridges the infrastructure (Phase 1) with the restructured content (Phase 2).

## Dependencies

- Requires Phase 1 (metadata dataclasses and parser)
- Requires Phase 2 (restructured prompt files with frontmatter)
- Base branch: Should be merged after Phase 1 and Phase 2 are complete

## Deliverables

### 3.1 Implement discovery in `src/ohtv/prompts/discovery.py`

```python
from pathlib import Path
from ohtv.prompts.metadata import PromptMetadata
from ohtv.prompts.parser import parse_prompt_file

def get_prompts_dirs() -> list[Path]:
    """Get prompt directories to search (user first, then default)."""
    # User: ~/.ohtv/prompts/
    # Default: src/ohtv/prompts/
    ...

def discover_prompts() -> dict[str, dict[str, PromptMetadata]]:
    """Discover all prompts organized by family and variant.
    
    Returns:
        Dict mapping family -> variant -> PromptMetadata
        e.g., {"objectives": {"brief": PromptMetadata(...), "detailed": ...}}
    
    Scans both user and default directories.
    User prompts override defaults with the same family/variant.
    """
    ...

def list_families() -> list[str]:
    """List all available prompt families."""
    ...

def list_variants(family: str) -> list[str]:
    """List all variants for a family."""
    ...

def resolve_prompt(family: str, variant: str | None = None) -> PromptMetadata:
    """Resolve a prompt by family and optional variant.
    
    Args:
        family: Prompt family (e.g., "objectives")
        variant: Variant name (e.g., "brief"). If None, uses default variant.
        
    Returns:
        PromptMetadata for the resolved prompt
        
    Raises:
        ValueError: If family or variant not found
    """
    ...

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
    ...
```

### 3.2 Update `src/ohtv/prompts/__init__.py`

Maintain backward compatibility while adding new discovery-based functions:

```python
# Existing functions - keep working for backward compat
from ohtv.prompts._legacy import (
    get_prompt,
    get_prompt_hash,
    init_user_prompts,
    list_prompts,
    PROMPT_NAMES,
)

# New discovery-based functions
from ohtv.prompts.discovery import (
    discover_prompts,
    list_families,
    list_variants,
    resolve_prompt,
    resolve_context,
)

# New metadata types
from ohtv.prompts.metadata import (
    EventFilter,
    ContextLevel,
    PromptMetadata,
)
```

Move existing code to `_legacy.py` to keep it working while new system is developed.

### 3.3 Update `ohtv prompts` CLI command

Update `src/ohtv/cli.py` to show family/variant structure:

```
$ ohtv prompts

Prompt Families:
  objectives/
    brief (default)     Extract user goal in 1-2 sentences
    brief_assess        Extract user goal and assess completion
    standard            Standard analysis with outcomes
    standard_assess     Standard analysis with assessment
    detailed            Full hierarchical analysis
    detailed_assess     Full hierarchical with assessment
  
  code_review/          (example - if created in Phase 2)
    default             Analyze code changes
```

### 3.4 Unit tests

- `tests/unit/prompts/test_discovery.py`
  - Test discovery from multiple directories
  - Test user override of defaults
  - Test resolve_prompt with/without variant
  - Test resolve_context by number and name
  - Test error cases (unknown family, unknown variant)

## Acceptance Criteria

1. `discover_prompts()` finds prompts in both user and default directories
2. User prompts correctly override defaults
3. `resolve_prompt()` handles default variant selection
4. `resolve_context()` handles both number and name lookups
5. Existing `get_prompt()` and `get_prompt_hash()` still work (backward compat)
6. `ohtv prompts` shows family/variant structure
7. All unit tests pass
8. Existing tests still pass

## Files to Create/Modify

- `src/ohtv/prompts/discovery.py` - NEW: Discovery functions
- `src/ohtv/prompts/_legacy.py` - NEW: Move existing code here
- `src/ohtv/prompts/__init__.py` - MODIFY: Re-export both old and new
- `src/ohtv/cli.py` - MODIFY: Update `prompts` command display
- `tests/unit/prompts/test_discovery.py` - NEW

## Notes

- Keep backward compatibility as highest priority
- The discovery system should gracefully handle prompts without frontmatter
- Cache discovered prompts to avoid repeated filesystem scans
