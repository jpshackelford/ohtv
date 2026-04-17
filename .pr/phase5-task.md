# Task: Implement Phase 5 - Unified CLI Command

## Context

You are implementing Phase 5 of the extensible prompts feature for the ohtv project.
This is the final phase that ties together all the infrastructure built in Phases 1-4.

Phases 1-4 are complete:
- Phase 1: metadata.py, parser.py with EventFilter, ContextLevel, PromptMetadata dataclasses
- Phase 2: Prompt files with YAML frontmatter in family directories (src/ohtv/prompts/objectives/)
- Phase 3: discovery.py with discover_prompts(), resolve_prompt(), resolve_context()
- Phase 4: transcript.py with build_transcript_from_context(), extract_content()

## Git Setup

First, ensure git is configured to push to GitHub:
```bash
git remote set-url origin https://github.com/jpshackelford/ohtv.git
git fetch origin
git checkout feature/extensible-prompts
git pull origin feature/extensible-prompts
```

## Your Task

1. Create a new branch: `git checkout -b feature/extensible-prompts-phase5`

2. Create or update the unified `ohtv analyze` command in `src/ohtv/cli.py`:
   - Add new `analyze` command group
   - Subcommand: `ohtv analyze objectives <conversation_id>` - replaces current `objectives` command
   - Options:
     - `--variant/-v` to select prompt variant (brief, standard, detailed, brief_assess, etc.)
     - `--context/-c` to select context level by name or number
     - `--model/-m` for LLM model selection
     - `--no-cache` to skip cache
   - Use the new discovery system to find and load prompts
   - Use metadata-driven transcript building

3. Update the existing `objectives` command to call the new infrastructure:
   - Maintain backward compatibility with existing CLI options
   - Map old options to new system (e.g., `--assess` maps to `*_assess` variants)

4. Create comprehensive tests in `tests/unit/test_cli_analyze.py`

5. Run all tests: `uv run python -m pytest tests/unit/ -v`

6. Commit and push: 
   ```bash
   git add -A
   git commit -m "Phase 5: Add unified analyze CLI command"
   git push -u origin feature/extensible-prompts-phase5
   ```

7. Create PR: `gh pr create --base feature/extensible-prompts --title "Phase 5: Unified Analyze CLI Command"`

## Key Implementation Notes

### Using the Discovery System
```python
from ohtv.prompts.discovery import resolve_prompt, resolve_context, list_variants

# Get available variants for objectives family
variants = list_variants('objectives')  # ['brief', 'brief_assess', 'standard', ...]

# Resolve a specific prompt variant
prompt_meta = resolve_prompt('objectives', 'brief')

# Get context level from prompt metadata
context = resolve_context(prompt_meta, 1)  # or resolve_context(prompt_meta, 'minimal')
```

### Using Metadata-Driven Transcripts
```python
from ohtv.analysis.transcript import build_transcript_from_context

# Build transcript using context level filters
transcript = build_transcript_from_context(events, context_level)
```

### Mapping Old Options to New System
- `--context-level minimal` → context level 1 from prompt metadata
- `--context-level default` → context level 2 from prompt metadata  
- `--context-level full` → context level 3 from prompt metadata
- `--assess` → select `*_assess` variant
- `--detail-level brief` → select `brief` or `brief_assess` variant

## Acceptance Criteria

- `ohtv analyze objectives <id>` works with new infrastructure
- `ohtv objectives <id>` still works (backward compatibility)
- Variant selection via `--variant` option
- Context selection via `--context` option (by name or number)
- All unit tests pass
- PR created and ready for review
