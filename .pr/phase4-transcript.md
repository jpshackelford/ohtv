# Phase 4: Metadata-Driven Transcript Building

## Overview

Refactor the transcript building logic in `objectives.py` to use the metadata-driven context levels from prompt frontmatter instead of hardcoded logic.

## Dependencies

- Requires Phase 1 (ContextLevel, EventFilter dataclasses)
- Requires Phase 3 (discovery and resolution functions)
- Base branch: Should be merged after Phase 1 and Phase 3 are complete

## Deliverables

### 4.1 Create `src/ohtv/analysis/transcript.py`

Extract and generalize transcript building:

```python
from ohtv.prompts.metadata import ContextLevel, EventFilter

def matches_filter(event: dict, filter: EventFilter) -> bool:
    """Check if an event matches a single filter."""
    # Check source
    if filter.source != "*" and event.get("source") != filter.source:
        return False
    
    # Check kind
    if filter.kind != "*" and event.get("kind") != filter.kind:
        return False
    
    # Check tool (only for ActionEvent)
    if filter.tool and event.get("tool_name") != filter.tool:
        return False
    
    return True

def matches_context(event: dict, context: ContextLevel) -> bool:
    """Check if event should be included at this context level.
    
    An event matches if:
    - ANY include filter matches, AND
    - NO exclude filter matches
    """
    # Check includes (OR logic)
    included = any(matches_filter(event, f) for f in context.include)
    if not included:
        return False
    
    # Check excludes
    excluded = any(matches_filter(event, f) for f in context.exclude)
    if excluded:
        return False
    
    return True

def extract_content(event: dict, max_length: int = 0) -> str:
    """Extract text content from an event with optional truncation."""
    # Reuse existing extraction logic from objectives.py
    ...
    
    if max_length > 0 and len(content) > max_length:
        content = content[:max_length] + "... [truncated]"
    
    return content

def build_transcript_from_context(
    events: list[dict], 
    context: ContextLevel
) -> list[dict]:
    """Build transcript based on context level from prompt metadata.
    
    Args:
        events: List of conversation events
        context: ContextLevel with include/exclude filters
        
    Returns:
        List of transcript items with role and text
    """
    items = []
    
    for event in events:
        if matches_context(event, context):
            content = extract_content(event, max_length=context.truncate)
            if content:
                source = event.get("source", "unknown")
                kind = event.get("kind", "unknown")
                
                # Map to transcript role
                if kind == "MessageEvent":
                    role = "user" if source == "user" else "assistant"
                elif kind == "ActionEvent":
                    role = "action"
                else:
                    role = "system"
                
                items.append({"role": role, "text": content})
    
    return items
```

### 4.2 Update `src/ohtv/analysis/objectives.py`

Refactor to use metadata-driven transcript building:

```python
from ohtv.analysis.transcript import build_transcript_from_context
from ohtv.prompts import resolve_prompt, resolve_context
from ohtv.prompts.metadata import ContextLevel

# Keep existing build_transcript() for backward compatibility
# but mark as deprecated

def build_transcript(events: list[dict], context: ContextLevel | str = "default") -> list[dict]:
    """Build a transcript based on the context level.
    
    DEPRECATED: Use build_transcript_from_context() with a ContextLevel.
    This function maintains backward compatibility with string context levels.
    """
    if isinstance(context, str):
        # Legacy mode: use hardcoded context levels
        return _legacy_build_transcript(events, context)
    else:
        # New mode: use metadata-driven context
        return build_transcript_from_context(events, context)

def _legacy_build_transcript(events: list[dict], context: str) -> list[dict]:
    """Original hardcoded transcript building logic."""
    # Move existing code here
    ...
```

Update `analyze_objectives()` to optionally accept metadata:

```python
def analyze_objectives(
    conv_dir: Path,
    context: ContextLevel | str = "default",  # Accept both
    detail: DetailLevel = "brief",
    assess: bool = False,
    model: str | None = None,
    force_refresh: bool = False,
) -> AnalysisResult:
    """Analyze objectives in a conversation.
    
    The context parameter now accepts either:
    - A string ("minimal", "default", "full") for legacy mode
    - A ContextLevel object for metadata-driven mode
    """
    ...
```

### 4.3 Unit tests

- `tests/unit/analysis/test_transcript.py`
  - Test matches_filter with various event types
  - Test matches_context with include/exclude logic
  - Test extract_content with truncation
  - Test build_transcript_from_context with sample events

## Acceptance Criteria

1. `build_transcript_from_context()` correctly filters events based on ContextLevel
2. EventFilter matching works for source, kind, and tool
3. Include/exclude logic (OR for includes, AND NOT for excludes) works correctly
4. Truncation respects `context.truncate` setting
5. Backward compatibility: existing `analyze_objectives()` calls still work
6. All unit tests pass
7. Existing tests still pass

## Files to Create/Modify

- `src/ohtv/analysis/transcript.py` - NEW: Generic transcript building
- `src/ohtv/analysis/objectives.py` - MODIFY: Use new transcript builder
- `tests/unit/analysis/__init__.py` - NEW
- `tests/unit/analysis/test_transcript.py` - NEW

## Notes

- Prioritize backward compatibility
- The legacy `build_transcript()` should continue to work identically
- New code paths should be opt-in via ContextLevel parameter
