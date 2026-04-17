# Task: Implement Phase 4 - Metadata-Driven Transcript Building

## Context

You are implementing Phase 4 of the extensible prompts feature for the ohtv project.
The full design is in `.pr/phase4-transcript.md`.

Phases 1-3 are complete:
- Phase 1: metadata.py, parser.py with EventFilter, ContextLevel dataclasses
- Phase 2: Prompt files with YAML frontmatter in family directories
- Phase 3: discovery.py with prompt discovery and resolution

## Git Setup

First, ensure git is configured to push to GitHub:
```bash
git remote set-url origin https://github.com/jpshackelford/ohtv.git
git fetch origin
git checkout feature/extensible-prompts
git pull origin feature/extensible-prompts
```

## Your Task

1. Read the design document at `.pr/phase4-transcript.md`
2. Create a new branch: `git checkout -b feature/extensible-prompts-phase4`
3. Implement all deliverables:
   - Create `src/ohtv/analysis/transcript.py` with:
     - `build_transcript(events, context_level)` - Build transcript using ContextLevel filters
     - `filter_events(events, context_level)` - Apply include/exclude filters
     - `format_event(event, truncate)` - Format single event with optional truncation
   - Update existing transcript code to use new metadata-driven approach
   - Maintain backward compatibility with existing API
   - Create unit tests in `tests/unit/analysis/test_transcript.py`
4. Run all tests: `uv run python -m pytest tests/unit/ -v`
5. Ensure existing tests still pass
6. Commit changes with a descriptive message
7. Push to remote: `git push -u origin feature/extensible-prompts-phase4`
8. Create a PR to `feature/extensible-prompts` using `gh pr create`

## Key Implementation Notes

- ContextLevel has `include` (list of EventFilter) and `exclude` (list of EventFilter)
- EventFilter matches by `source` (user/agent), `kind` (message/action/etc), `tool` (specific tool name)
- Event filtering: include if ANY include filter matches AND NO exclude filter matches
- Use `truncate` from ContextLevel metadata for output truncation
- Existing code in `src/ohtv/analysis/objectives.py` builds transcripts - refactor to use new system

## Example Filter Logic

```python
def matches_event(event, filter: EventFilter) -> bool:
    if filter.source and event.source != filter.source:
        return False
    if filter.kind and event.kind != filter.kind:
        return False
    if filter.tool and event.tool != filter.tool:
        return False
    return True

def should_include(event, context_level: ContextLevel) -> bool:
    # Must match at least one include filter
    if not any(matches_event(event, f) for f in context_level.include):
        return False
    # Must not match any exclude filter
    if any(matches_event(event, f) for f in context_level.exclude):
        return False
    return True
```

## Acceptance Criteria

- `build_transcript()` respects include/exclude filters from ContextLevel
- Truncation applied based on ContextLevel.truncate value
- Existing objectives.py analysis still works
- All unit tests pass (new and existing)
- PR created and ready for review
