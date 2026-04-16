# Task: Implement Phase 1 - Frontmatter Infrastructure

## Context

You are implementing Phase 1 of the extensible prompts feature for the ohtv project.
The full design is in `.pr/phase1-infrastructure.md`.

## Git Setup

First, ensure git is configured to push to GitHub:
```bash
git remote set-url origin https://github.com/jpshackelford/ohtv.git
git fetch origin
git checkout feature/extensible-prompts
git pull origin feature/extensible-prompts
```

## Your Task

1. Read the design document at `.pr/phase1-infrastructure.md`
2. Create a new branch: `git checkout -b feature/extensible-prompts-phase1`
3. Implement all deliverables:
   - Add pyyaml to pyproject.toml
   - Create `src/ohtv/prompts/metadata.py` with dataclasses
   - Create `src/ohtv/prompts/parser.py` with parsing functions
   - Create unit tests in `tests/unit/prompts/`
4. Run tests: `uv run python -m pytest tests/unit/prompts/ -v`
5. Commit changes with a descriptive message
6. Push to remote: `git push -u origin feature/extensible-prompts-phase1`
7. Create a PR to `feature/extensible-prompts` using `gh pr create`

## Acceptance Criteria

- pyyaml added to dependencies
- EventFilter.matches() correctly handles wildcards and tool filtering
- ContextLevel.matches() implements include/exclude logic
- parse_prompt_file() handles files with and without frontmatter
- All unit tests pass
- PR created and ready for review
