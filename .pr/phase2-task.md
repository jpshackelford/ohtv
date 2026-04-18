# Task: Implement Phase 2 - Content Restructure

## Context

You are implementing Phase 2 of the extensible prompts feature for the ohtv project.
The full design is in `.pr/phase2-content-restructure.md`.

## Git Setup

First, ensure git is configured to push to GitHub:
```bash
git remote set-url origin https://github.com/jpshackelford/ohtv.git
git fetch origin
git checkout feature/extensible-prompts
git pull origin feature/extensible-prompts
```

## Your Task

1. Read the design document at `.pr/phase2-content-restructure.md`
2. Create a new branch: `git checkout -b feature/extensible-prompts-phase2`
3. Implement all deliverables:
   - Create `src/ohtv/prompts/objs/` directory
   - Move all 6 existing prompts into that directory
   - Add YAML frontmatter to each prompt file following the spec in the design doc
   - Optionally create `src/ohtv/prompts/code_review/default.md` as an example
4. Verify the markdown files are valid
5. Commit changes with a descriptive message
6. Push to remote: `git push -u origin feature/extensible-prompts-phase2`
7. Create a PR to `feature/extensible-prompts` using `gh pr create`

## Context Level Specifications

All objectives prompts should use these standard context levels:

| Level | Name | Events Included |
|-------|------|-----------------|
| 1 | minimal | User messages only |
| 2 | default | User messages + finish action |
| 3 | full | User + agent messages + all actions (truncated to 1000 chars) |

**Default context by variant:**
- `brief`: default=1 (minimal context sufficient for goal extraction)
- `brief_assess`: default=2 (need finish action to assess)
- `standard`: default=2
- `standard_assess`: default=2
- `detailed`: default=3 (full context for detailed analysis)
- `detailed_assess`: default=3

**Mark `brief.md` as the default variant** with `default: true` in its frontmatter.

## Acceptance Criteria

- All 6 prompts moved to `src/ohtv/prompts/objs/`
- Each prompt has valid YAML frontmatter
- Original prompt text content preserved exactly
- PR created and ready for review
