# Design: Extensible Prompt System

## Overview

Transform the hardcoded prompt system into a convention-based, metadata-driven architecture where:
1. Prompts are auto-discovered from the filesystem
2. Prompts declare their requirements via YAML frontmatter
3. New analysis types can be added by simply creating new prompt files
4. Context levels are defined per-prompt with custom names and event specifications

## Current State

```
src/ohtv/prompts/
├── brief.md
├── brief_assess.md
├── standard.md
├── standard_assess.md
├── detailed.md
└── detailed_assess.md
```

- `PROMPT_NAMES` hardcodes the 6 valid prompts
- `_get_prompt_name(detail, assess)` maps parameters to filenames
- `build_transcript()` hardcodes context levels (minimal/default/full)
- Cache key: `assess=False,context_level=minimal,detail_level=brief`

## Proposed Design

### Two Orthogonal Dimensions

1. **Variant** (`-v`) - Output format/structure (which prompt file to use)
2. **Context** (`-c`) - How much event data to include (defined per-prompt)

Each prompt file defines its output format AND the context levels available for it.

### Prompt File Format

Use YAML frontmatter (standard in Jekyll, Hugo, Obsidian, etc.):

```markdown
---
id: objectives.brief
description: Extract user goal in 1-2 sentences

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

In 1-2 sentences, describe the user's goal...
```

### Directory Structure

```
~/.ohtv/prompts/
├── objs/
│   ├── brief.md           # default: true
│   ├── standard.md
│   ├── detailed.md
│   ├── brief_assess.md
│   └── custom_qa.md       # user-created variant
├── code_review/
│   └── default.md
└── error_analysis/
    └── default.md
```

Prompts are organized by **family** (objectives, code_review, etc.) with **variants** within each family. Variant names are completely flexible - users can create any variants they want.

### Frontmatter Specification

```yaml
---
# Identity
id: family.variant           # Unique identifier (inferred from path if omitted)
description: Human-readable description

# Variant Configuration
default: true                # This variant is used when -v not specified

# Context Levels - what events to include in transcript
context:
  default: 1                 # Which level if -c not specified
  levels:
    1:
      name: minimal          # Human-readable name (can use -c minimal or -c 1)
      include:               # Event filters (any filter can match)
        - source: user       # user | agent | *
          kind: MessageEvent # MessageEvent | ActionEvent | ErrorEvent | *
    2:
      name: default
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
          tool: finish       # For ActionEvent only: tool_name filter
    3:
      name: full
      include:
        - source: user
          kind: MessageEvent
        - source: agent
          kind: MessageEvent
        - source: agent
          kind: ActionEvent
      exclude:               # Optional: events to skip
        - kind: ErrorEvent
      truncate: 1000         # Max chars per message (0 = no truncation)
  
# Output Schema - for validation and documentation
output:
  schema:                    # JSON Schema for expected output
    type: object
    required: [goal]
    properties:
      goal:
        type: string

# Optional: Custom handler for complex transformations
handler: ohtv.analysis.objectives:ObjectiveHandler
        
# Optional metadata
tags: [analysis, objective]  # For discovery/filtering
---
```

### CLI Interface

```bash
ohtv gen <family> [conversation_id] [-v VARIANT] [-c CONTEXT]
```

**Examples:**
```bash
# Basic usage
ohtv gen objs abc123                    # default variant, default context
ohtv gen objs -v detailed abc123        # specific variant
ohtv gen objs -v brief -c 2 abc123      # by context level number
ohtv gen objs -v brief -c full abc123   # by context level name

# Multi-conversation
ohtv gen objs -W                        # this week's conversations
ohtv gen objs -v detailed --repo foo    # filter by repo
```

**Flags:**
- `-v, --variant` - Select variant by name (default: variant marked `default: true`)
- `-c, --context` - Select context level by number or name (default: level marked in prompt)
- `-m, --model` - Override LLM model
- `--refresh` - Force re-analysis (ignore cache)
- Conversation filters: `-D`, `-W`, `-M`, `--repo`, `--pr`, etc.

### Variant System

**Flexible naming**: Variants can be named anything - `brief`, `verbose`, `qa_focused`, `with_metrics`, etc.

**Default variant**: One variant per family can be marked `default: true`. Used when `-v` not specified.

**Discovery**: If no variant is marked default, the system uses alphabetically first.

### Context Level System

Each prompt defines its own context levels with:
- **Number** (1, 2, 3...) - For quick `-c 2` access
- **Name** (minimal, default, full, or custom) - For readable `-c full` access
- **Event filters** - What events to include at this level

**Different prompts can have different context levels:**

```yaml
# objs/brief.md - standard context levels
context:
  levels:
    1: { name: minimal, include: [...] }
    2: { name: default, include: [...] }
    3: { name: full, include: [...] }

# code_review/default.md - custom context levels
context:
  levels:
    1: 
      name: edits_only
      include:
        - tool: file_editor
    2:
      name: with_commands
      include:
        - tool: file_editor
        - tool: terminal
    3:
      name: everything
      include:
        - source: agent
          kind: ActionEvent
```

### Context Filter Rules

The `include` is a list of filters. An event is included if it matches **any** filter:

```yaml
include:
  # User messages
  - source: user
    kind: MessageEvent
  
  # Agent finish actions only
  - source: agent
    kind: ActionEvent
    tool: finish
  
  # All terminal commands
  - tool: terminal    # Shorthand: implies kind: ActionEvent
```

Filter fields:
- `source`: `user` | `agent` | `*` (default: `*`)
- `kind`: `MessageEvent` | `ActionEvent` | `ErrorEvent` | `*` (default: `*`)
- `tool`: Tool name for ActionEvents (e.g., `finish`, `terminal`, `file_editor`)

The `exclude` removes events that would otherwise be included.

### Prompt Discovery

```python
@dataclass
class ContextLevel:
    number: int                  # e.g., 1, 2, 3
    name: str                    # e.g., "minimal", "full"
    include: list[EventFilter]
    exclude: list[EventFilter] = []
    truncate: int = 0            # 0 = no truncation

@dataclass 
class PromptMetadata:
    id: str                      # e.g., "objectives.brief"
    family: str                  # e.g., "objs"
    variant: str                 # e.g., "brief"
    description: str
    context_levels: dict[int, ContextLevel]  # Keyed by level number
    default_context: int         # Default context level number
    output_schema: dict | None
    tags: list[str]
    path: Path                   # Source file
    content: str                 # Prompt text (without frontmatter)
    content_hash: str            # For cache invalidation
    default: bool = False        # Is this the default variant?
    handler: str | None = None   # Optional handler class path

def discover_prompts() -> dict[str, PromptMetadata]:
    """
    Scan prompt directories and return metadata for all prompts.
    
    Search order (later overrides earlier):
    1. Package defaults: src/ohtv/prompts/
    2. User prompts: ~/.ohtv/prompts/
    
    Returns dict keyed by prompt id (e.g., "objectives.brief")
    """

def list_families() -> dict[str, list[PromptMetadata]]:
    """Return prompts grouped by family."""

def resolve_prompt(family: str, variant: str | None = None) -> PromptMetadata:
    """
    Resolve family and variant to prompt metadata.
    
    If variant is None, uses the variant marked default: true.
    """

def resolve_context(prompt: PromptMetadata, context: str | int | None) -> ContextLevel:
    """
    Resolve context specification to a ContextLevel.
    
    context can be:
    - None -> use prompt's default context level
    - int (1, 2, 3) -> level by number
    - str ("minimal", "full") -> level by name
    """
```

### Listing Prompts

```bash
$ ohtv prompts list

objectives (4 variants)
  brief          (default)      Extract user goal in 1-2 sentences
  standard                      Goal with primary/secondary outcomes
  detailed                      Full hierarchical analysis
  brief_assess                  Brief with achievement assessment

code_review (1 variant)
  default        (default)      Analyze code changes in conversation

$ ohtv prompts list objectives

objectives.brief (default variant)
  Description: Extract user goal in 1-2 sentences
  Context levels:
    1: minimal   [1 filter]  (default)
    2: default   [2 filters]
    3: full      [3 filters]
  Output schema: {goal: string}
  Handler: (none)

objectives.detailed
  Description: Full hierarchical analysis
  Context levels:
    1: minimal   [1 filter]
    2: default   [2 filters]  (default)
    3: full      [3 filters]
  Output schema: {primary_objectives: [...], summary: string}
  Handler: ohtv.analysis.objectives:ObjectiveHandler
```

The `[N filters]` count shows the number of event filters at each context level.

### Custom Handlers

For prompts that need special processing beyond simple JSON parsing, specify a handler:

```yaml
handler: ohtv.analysis.objectives:ObjectiveHandler
```

The handler is a Python class that implements:

```python
class PromptHandler:
    """Base class for custom prompt handlers."""
    
    def pre_process(self, events: list[dict], context: ContextSpec) -> list[dict]:
        """Optional: Transform events before transcript building."""
        return events
    
    def build_transcript(self, events: list[dict], context: ContextSpec) -> str:
        """Optional: Custom transcript building (default uses standard builder)."""
        return default_build_transcript(events, context)
    
    def post_process(self, response: dict) -> Any:
        """Optional: Transform LLM response into structured data."""
        return response
    
    def format_output(self, result: Any, console: Console) -> None:
        """Optional: Custom rich output formatting."""
        console.print_json(data=result)
```

**Example: ObjectiveHandler**

```python
class ObjectiveHandler(PromptHandler):
    """Handler for objectives analysis with hierarchical structure."""
    
    def post_process(self, response: dict) -> ObjectiveAnalysis:
        """Convert raw JSON to structured ObjectiveAnalysis."""
        # Parse nested objectives with status enums
        # Return pydantic model
        ...
    
    def format_output(self, result: ObjectiveAnalysis, console: Console) -> None:
        """Rich formatting with status colors and tree display."""
        ...
```

**When to use handlers:**
- Complex nested structures that benefit from pydantic validation
- Custom display formatting (trees, tables, colored status)
- Pre-processing that filters/transforms events beyond context rules
- Post-processing that enriches LLM output

**When NOT to use handlers:**
- Simple JSON output - just use `output.schema`
- Standard filtering - use `context.include/exclude`
- Most user-created prompts won't need handlers

### Transcript Builder

Replace hardcoded `build_transcript()` with metadata-driven version:

```python
def build_transcript(events: list[dict], context: ContextLevel) -> list[dict]:
    """Build transcript based on context level from prompt metadata."""
    items = []
    
    for event in events:
        if context.matches(event) and not context.excludes(event):
            content = extract_content(event, max_length=context.truncate)
            if content:
                items.append({
                    "role": event.get("source", "unknown"),
                    "kind": event.get("kind", "unknown"),
                    "text": content
                })
    
    return items
```

### Cache Key

Current: `assess=False,context_level=minimal,detail_level=brief`

New: `prompt=objectives.brief,context=1`

The cache key now includes:
- Prompt ID (family.variant)
- Context level number
- Prompt content hash (for invalidation when prompt file changes)

### Example: Creating a New Analysis Type

User wants to analyze code changes in conversations:

**1. Create prompt file:**

```bash
mkdir -p ~/.ohtv/prompts/code_review
```

**2. Write `~/.ohtv/prompts/code_review/default.md`:**

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
        - tool: file_editor
    2:
      name: with_commands
      include:
        - tool: file_editor
        - tool: terminal
    3:
      name: full
      include:
        - source: agent
          kind: ActionEvent
      truncate: 500

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
            action: {type: string, enum: [create, edit, delete]}
            summary: {type: string}
      overall_summary:
        type: string
---
Analyze the code changes made in this conversation.

For each file modified, identify:
- The file path
- Whether it was created, edited, or deleted
- A brief summary of the change

Respond with JSON:
{
  "changes": [
    {"file": "path/to/file.py", "action": "edit", "summary": "Added error handling"},
    ...
  ],
  "overall_summary": "Brief description of all changes"
}
```

**3. Use it:**

```bash
ohtv gen code_review abc123              # edits_only context (default)
ohtv gen code_review -c 2 abc123         # with_commands context
ohtv gen code_review -c full abc123      # full context by name
```

### Example: Error Pattern Analysis

```markdown
---
id: errors.patterns
description: Identify error patterns and recovery strategies
default: true

context:
  default: 1
  levels:
    1:
      name: errors_only
      include:
        - kind: ErrorEvent
    2:
      name: with_context
      include:
        - kind: ErrorEvent
        - tool: terminal
      truncate: 200

output:
  schema:
    type: object
    properties:
      errors:
        type: array
        items:
          type: object
          properties:
            type: {type: string}
            message: {type: string}
            recovered: {type: boolean}
            recovery_strategy: {type: string}
---
Analyze the errors in this conversation...
```

### Implementation Plan

#### Phase 1: Frontmatter Infrastructure
- Add `pyyaml` dependency
- Create `ContextLevel`, `EventFilter`, `PromptMetadata` dataclasses
- Implement frontmatter parsing with `parse_prompt_file()`
- Implement `ContextLevel.matches(event)` for event filtering

#### Phase 2: Prompt Discovery & Loading
- Implement `discover_prompts()` to scan directories
- Implement `resolve_prompt(family, variant)` and `resolve_context(prompt, context)`
- Restructure prompts into family directories
- Add frontmatter with context levels to all existing prompts

#### Phase 3: Metadata-Driven Transcript Building  
- Refactor `build_transcript()` to accept `ContextLevel`
- Remove hardcoded context level logic from `objectives.py`
- Test with various context level configurations

#### Phase 4: New CLI
- Create `ohtv gen <family> [conversation_id] [-v VARIANT] [-c CONTEXT]`
- Support all existing conversation filters
- Support multi-conversation parallel analysis
- Remove `objs` and `summary` commands
- Update `ohtv prompts list` to show families, variants, and context levels

#### Phase 5: Output Validation (Optional)
- Validate LLM response against `output.schema`
- Warn on schema mismatch (lenient mode)
- Could use `jsonschema` library

### Open Questions

1. **Schema validation strictness?**
   - Strict: Reject invalid responses
   - Lenient: Warn but accept
   - Recommendation: Lenient with warnings

2. **Multi-pass analysis?**
   - Some analyses might need multiple LLM calls
   - Could support `phases` in frontmatter
   - Defer to future enhancement

3. **Context level number semantics?**
   - Convention: higher numbers = more context
   - Not enforced, just a guideline for prompt authors

### Migration

1. Restructure into family directories:
   ```
   prompts/
   └── objs/
       ├── brief.md
       ├── brief_assess.md
       ├── standard.md
       ├── standard_assess.md
       ├── detailed.md
       └── detailed_assess.md
   ```
2. Add frontmatter with context levels to all prompts
3. Create new `ohtv gen` command
4. Remove `objs` and `summary` commands
5. Update cache key format to `prompt={id},context={level}`
6. Invalidate existing analysis cache (one-time migration)

### Benefits

1. **Extensibility**: New analysis types without code changes
2. **User customization**: Full control over context levels and output format
3. **Self-documenting**: Frontmatter describes what each prompt does and its context options
4. **Flexibility**: Same prompt can run with different context levels
5. **Discoverability**: `prompts list` shows all families, variants, and context levels
6. **Consistency**: Single `gen` command for all analysis types
