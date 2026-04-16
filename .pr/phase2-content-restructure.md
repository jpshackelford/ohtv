# Phase 2: Content Restructure

## Overview

Restructure existing prompt files into family directories and add YAML frontmatter with context level definitions. This is a content-only task with no Python code changes.

## Dependencies

- Base branch: `feature/extensible-prompts`
- No dependencies on Phase 1 (can run in parallel)

## Deliverables

### 2.1 Create family directory structure

Move existing prompts from flat structure to family-based:

```
src/ohtv/prompts/
├── __init__.py           # Keep existing
├── objectives/           # NEW directory
│   ├── brief.md
│   ├── brief_assess.md
│   ├── standard.md
│   ├── standard_assess.md
│   ├── detailed.md
│   └── detailed_assess.md
├── metadata.py           # (From Phase 1)
└── parser.py             # (From Phase 1)
```

### 2.2 Add frontmatter to each prompt

Each prompt file should have YAML frontmatter with context level definitions.

**Example: `objectives/brief.md`**

```markdown
---
id: objectives.brief
description: Extract user goal in 1-2 sentences
default: true

context:
  default: 1
  levels:
    1:
      name: minimal
      include:
        - source: user
          kind: MessageEvent
    2:
      name: default
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 1000

output:
  schema:
    type: object
    required: [goal]
    properties:
      goal:
        type: string
---
Analyze this conversation between a user and an AI coding assistant.

In 1-2 sentences, describe the user's goal using imperative mood (e.g., "Add pagination to search results" not "The user wants to add pagination").

Do not assess whether the goal was achieved. Just identify what they want.

Respond with JSON:
{"goal": "1-2 sentence description in imperative mood"}
```

**Example: `objectives/brief_assess.md`**

```markdown
---
id: objectives.brief_assess
description: Extract user goal and assess completion status

context:
  default: 2
  levels:
    1:
      name: minimal
      include:
        - source: user
          kind: MessageEvent
    2:
      name: default
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 1000

output:
  schema:
    type: object
    required: [goal, status]
    properties:
      goal:
        type: string
      status:
        type: string
        enum: [achieved, not_achieved, in_progress]
---
[existing prompt content here]
```

### 2.3 Context level specifications for each prompt type

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

**Default variant:** `brief` should be marked `default: true`

### 2.4 Create example prompts for new analysis types (optional)

If time permits, create example prompts demonstrating extensibility:

**`src/ohtv/prompts/code_review/default.md`** (example only, not functional yet)

```markdown
---
id: code_review.default
description: Analyze code changes made during the conversation
default: true

context:
  default: 1
  levels:
    1:
      name: edits_only
      include:
        - source: agent
          kind: ActionEvent
          tool: file_editor
    2:
      name: with_commands
      include:
        - source: agent
          kind: ActionEvent
          tool: file_editor
        - source: agent
          kind: ActionEvent
          tool: terminal
      truncate: 500
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      truncate: 300

output:
  schema:
    type: object
    required: [changes]
    properties:
      changes:
        type: array
        items:
          type: object
          properties:
            file: {type: string}
            action: {type: string}
            summary: {type: string}
---
Analyze the code changes made in this conversation.

For each file modified, identify:
- The file path
- Whether it was created, edited, or deleted
- A brief summary of the change

Respond with JSON:
{
  "changes": [
    {"file": "path/to/file.py", "action": "edit", "summary": "Added error handling"}
  ]
}
```

## Acceptance Criteria

1. All 6 existing prompts moved to `prompts/objectives/` directory
2. Each prompt has valid YAML frontmatter with:
   - `id` field matching `family.variant` pattern
   - `description` field
   - `context.levels` with at least 3 levels
   - `context.default` specifying default level
   - `output.schema` for response validation
3. `brief.md` marked as `default: true`
4. Original prompt text content preserved exactly
5. No Python code changes in this phase

## Files to Create/Modify

- `src/ohtv/prompts/objectives/` - NEW directory
- `src/ohtv/prompts/objectives/brief.md` - MOVED + frontmatter
- `src/ohtv/prompts/objectives/brief_assess.md` - MOVED + frontmatter
- `src/ohtv/prompts/objectives/standard.md` - MOVED + frontmatter
- `src/ohtv/prompts/objectives/standard_assess.md` - MOVED + frontmatter
- `src/ohtv/prompts/objectives/detailed.md` - MOVED + frontmatter
- `src/ohtv/prompts/objectives/detailed_assess.md` - MOVED + frontmatter
- (Optional) `src/ohtv/prompts/code_review/default.md` - NEW example

## Notes

- Keep the old files in place for now (Phase 3 will update the code to use new location)
- This phase can run in parallel with Phase 1 since it's content-only
- The frontmatter format should match what Phase 1's parser expects
