# Phase 1: Frontmatter Infrastructure

## Overview

Implement the core dataclasses and parsing infrastructure for YAML frontmatter in prompt files. This phase creates the foundation that all subsequent phases build upon.

## Dependencies

- Base branch: `feature/extensible-prompts`
- No dependencies on other phases

## Deliverables

### 1.1 Add pyyaml dependency

Add `pyyaml` to `pyproject.toml` dependencies.

### 1.2 Create dataclasses in `src/ohtv/prompts/metadata.py`

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

@dataclass
class EventFilter:
    """Filter for matching events in context level definitions."""
    source: Literal["user", "agent", "*"] = "*"
    kind: Literal["MessageEvent", "ActionEvent", "ErrorEvent", "*"] = "*"
    tool: str | None = None  # For ActionEvent filtering (e.g., "finish", "terminal")

    def matches(self, event: dict) -> bool:
        """Check if this filter matches an event."""
        # Implement matching logic:
        # - "*" matches any value
        # - tool filter only applies when kind is ActionEvent
        ...

@dataclass
class ContextLevel:
    """A context level definition from prompt frontmatter."""
    number: int                      # e.g., 1, 2, 3
    name: str                        # e.g., "minimal", "full"
    include: list[EventFilter]       # Events to include (OR logic)
    exclude: list[EventFilter] = field(default_factory=list)  # Events to exclude
    truncate: int = 0                # Max chars per message (0 = no truncation)

    def matches(self, event: dict) -> bool:
        """Check if event should be included at this context level."""
        # Match if ANY include filter matches AND NO exclude filter matches
        ...

@dataclass
class PromptMetadata:
    """Metadata parsed from prompt file frontmatter."""
    id: str                          # e.g., "objectives.brief"
    family: str                      # e.g., "objectives"
    variant: str                     # e.g., "brief"
    description: str = ""
    default: bool = False            # Is this the default variant for the family?
    context_levels: dict[int, ContextLevel] = field(default_factory=dict)
    default_context: int = 1         # Default context level number
    output_schema: dict | None = None
    handler: str | None = None       # e.g., "ohtv.analysis.objectives:ObjectiveHandler"
    tags: list[str] = field(default_factory=list)
    path: Path | None = None         # Source file path
    content: str = ""                # Prompt text (without frontmatter)
    content_hash: str = ""           # For cache invalidation

    def get_context_level(self, level: int | str) -> ContextLevel:
        """Get context level by number or name."""
        if isinstance(level, int):
            return self.context_levels[level]
        # Search by name
        for ctx in self.context_levels.values():
            if ctx.name == level:
                return ctx
        raise ValueError(f"Unknown context level: {level}")
```

### 1.3 Implement frontmatter parsing in `src/ohtv/prompts/parser.py`

```python
import hashlib
import yaml
from pathlib import Path
from ohtv.prompts.metadata import EventFilter, ContextLevel, PromptMetadata

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split content into YAML frontmatter dict and remaining content.
    
    Args:
        content: Full file content
        
    Returns:
        Tuple of (frontmatter dict, remaining content)
        Returns ({}, content) if no frontmatter present
    """
    # Frontmatter is delimited by --- at start and end
    ...

def parse_event_filter(data: dict) -> EventFilter:
    """Parse an event filter from frontmatter data."""
    ...

def parse_context_level(number: int, data: dict) -> ContextLevel:
    """Parse a context level definition from frontmatter data."""
    ...

def parse_prompt_file(path: Path) -> PromptMetadata:
    """Parse a prompt file and extract metadata from YAML frontmatter.
    
    Args:
        path: Path to the prompt .md file
        
    Returns:
        PromptMetadata with parsed frontmatter and content
        
    The frontmatter should be YAML between --- delimiters at the start of the file.
    If no frontmatter, returns metadata with defaults inferred from path.
    """
    content = path.read_text()
    frontmatter, prompt_content = parse_frontmatter(content)
    
    # Infer family/variant from path if not in frontmatter
    # e.g., prompts/objectives/brief.md -> family="objectives", variant="brief"
    ...
    
    # Parse context levels
    ...
    
    # Compute content hash
    content_hash = hashlib.sha256(prompt_content.encode()).hexdigest()[:16]
    
    return PromptMetadata(...)
```

### 1.4 Unit tests in `tests/unit/prompts/`

Create comprehensive tests:

- `tests/unit/prompts/test_metadata.py` - Test EventFilter.matches(), ContextLevel.matches()
- `tests/unit/prompts/test_parser.py` - Test frontmatter parsing, edge cases

Test cases should include:
- EventFilter matching with wildcards
- EventFilter matching with specific tool names
- ContextLevel include/exclude logic
- Frontmatter parsing with valid YAML
- Frontmatter parsing without frontmatter (backward compat)
- Path inference for family/variant
- Content hash generation

## Acceptance Criteria

1. `pyyaml` added to dependencies
2. All dataclasses defined with proper typing
3. EventFilter.matches() correctly handles wildcards and tool filtering
4. ContextLevel.matches() implements include/exclude logic
5. parse_prompt_file() handles:
   - Files with frontmatter
   - Files without frontmatter (backward compat)
   - Path-based inference of family/variant
6. All unit tests pass
7. Existing tests still pass

## Files to Create/Modify

- `pyproject.toml` - Add pyyaml
- `src/ohtv/prompts/metadata.py` - NEW: Dataclasses
- `src/ohtv/prompts/parser.py` - NEW: Parsing functions
- `tests/unit/prompts/__init__.py` - NEW
- `tests/unit/prompts/test_metadata.py` - NEW
- `tests/unit/prompts/test_parser.py` - NEW

## Notes

- Keep backward compatibility: files without frontmatter should still work
- Use the existing `PROMPT_NAMES` as reference for what prompts exist
- Content hash should only hash the prompt content, not frontmatter
