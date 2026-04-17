# Task: Implement Phase 3 - Prompt Discovery

## Context

You are implementing Phase 3 of the extensible prompts feature for the ohtv project.
The full design is in `.pr/phase3-discovery.md`.

Phase 1 (metadata.py, parser.py) and Phase 2 (prompt files with frontmatter) are complete.

## Git Setup

First, ensure git is configured to push to GitHub:
```bash
git remote set-url origin https://github.com/jpshackelford/ohtv.git
git fetch origin
git checkout feature/extensible-prompts
git pull origin feature/extensible-prompts
```

## Your Task

1. Read the design document at `.pr/phase3-discovery.md`
2. Create a new branch: `git checkout -b feature/extensible-prompts-phase3`
3. Implement all deliverables:
   - Create `src/ohtv/prompts/discovery.py` with:
     - `get_prompts_dirs()` - Get user and default prompt directories
     - `discover_prompts()` - Scan directories and return family->variant->metadata
     - `list_families()` - List all prompt families
     - `list_variants(family)` - List variants for a family
     - `resolve_prompt(family, variant)` - Get prompt metadata
     - `resolve_context(prompt, context)` - Get context level by number or name
   - Move existing code to `src/ohtv/prompts/_legacy.py` for backward compat
   - Update `src/ohtv/prompts/__init__.py` to re-export both old and new APIs
   - Update `ohtv prompts` CLI command to show family/variant structure
   - Create unit tests in `tests/unit/prompts/test_discovery.py`
4. Run all tests: `uv run python -m pytest tests/unit/prompts/ -v`
5. Ensure existing tests still pass
6. Commit changes with a descriptive message
7. Push to remote: `git push -u origin feature/extensible-prompts-phase3`
8. Create a PR to `feature/extensible-prompts` using `gh pr create`

## Key Implementation Notes

- Prompts are now in family directories: `prompts/objectives/`, `prompts/code_review/`
- User prompts in `~/.ohtv/prompts/` override defaults
- Use `parse_prompt_file()` from `parser.py` to load metadata
- Cache discovered prompts to avoid repeated filesystem scans
- Support both numbered (`-c 1`) and named (`-c minimal`) context levels

## Acceptance Criteria

- `discover_prompts()` finds prompts in family directories
- User prompts correctly override defaults
- `resolve_prompt()` handles default variant selection (marked with `default: true`)
- `resolve_context()` handles both number and name lookups
- Existing `get_prompt()` and `get_prompt_hash()` still work
- `ohtv prompts` shows new family/variant structure
- All unit tests pass
- PR created and ready for review
