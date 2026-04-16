# Phase 5: New CLI Command

## Overview

Create the unified `ohtv analyze` command that replaces the separate `objectives` and `summary` commands, using the extensible prompt system.

## Dependencies

- Requires all previous phases (1-4)
- Base branch: Should be merged after all previous phases are complete

## Deliverables

### 5.1 Create `ohtv analyze` command

Add to `src/ohtv/cli.py`:

```python
@cli.command()
@click.argument("family")
@click.argument("conversation_id", required=False)
@click.option("-v", "--variant", help="Prompt variant (default: family's default)")
@click.option("-c", "--context", help="Context level (number or name)")
@click.option("-m", "--model", help="Override LLM model")
@click.option("--refresh", is_flag=True, help="Force re-analysis (ignore cache)")
# Conversation filter options (same as list command)
@click.option("-D", "--today", is_flag=True, help="Today's conversations only")
@click.option("-W", "--this-week", is_flag=True, help="This week's conversations")
@click.option("-M", "--this-month", is_flag=True, help="This month's conversations")
@click.option("--repo", help="Filter by repository")
@click.option("--pr", help="Filter by PR number")
# Output options
@click.option("-q", "--quiet", is_flag=True, help="Minimal output")
@click.option("--json", "output_json", is_flag=True, help="JSON output")
def analyze(
    family: str,
    conversation_id: str | None,
    variant: str | None,
    context: str | None,
    model: str | None,
    refresh: bool,
    today: bool,
    this_week: bool,
    this_month: bool,
    repo: str | None,
    pr: str | None,
    quiet: bool,
    output_json: bool,
):
    """Analyze conversations using a prompt family.
    
    Examples:
    
      ohtv analyze objectives abc123
      ohtv analyze objectives -v detailed abc123
      ohtv analyze objectives -v brief -c 2 abc123
      ohtv analyze objectives -W
      ohtv analyze code_review --repo myrepo -D
    """
    from ohtv.prompts import resolve_prompt, resolve_context, list_families
    
    # Validate family exists
    families = list_families()
    if family not in families:
        console.print(f"[red]Unknown family: {family}[/red]")
        console.print(f"Available: {', '.join(families)}")
        raise SystemExit(1)
    
    # Resolve prompt and context
    prompt = resolve_prompt(family, variant)
    ctx = resolve_context(prompt, context)
    
    # Get conversations (single or filtered)
    if conversation_id:
        conversations = [find_conversation(conversation_id)]
    else:
        conversations = get_filtered_conversations(
            today=today, this_week=this_week, this_month=this_month,
            repo=repo, pr=pr
        )
    
    # Analyze each conversation
    for conv in conversations:
        result = analyze_with_prompt(conv, prompt, ctx, model=model, refresh=refresh)
        display_result(result, quiet=quiet, json_output=output_json)
```

### 5.2 Create generic analysis function

Add to `src/ohtv/analysis/__init__.py` or new file:

```python
from ohtv.prompts.metadata import PromptMetadata, ContextLevel
from ohtv.analysis.transcript import build_transcript_from_context

def analyze_with_prompt(
    conv_dir: Path,
    prompt: PromptMetadata,
    context: ContextLevel,
    model: str | None = None,
    refresh: bool = False,
) -> dict:
    """Analyze a conversation using a prompt.
    
    This is the generic analysis function that works with any prompt family.
    """
    # Load events
    events = load_events(conv_dir)
    
    # Build transcript using context level
    items = build_transcript_from_context(events, context)
    transcript = format_transcript(items)
    
    # Check cache (keyed by prompt.id + context.number)
    cache_key = f"prompt={prompt.id},context={context.number}"
    if not refresh:
        cached = check_cache(conv_dir, cache_key, prompt.content_hash)
        if cached:
            return cached
    
    # Call LLM
    result = call_llm(prompt.content, transcript, model=model)
    
    # Optionally validate against schema
    if prompt.output_schema:
        validate_schema(result, prompt.output_schema)
    
    # Cache and return
    save_cache(conv_dir, cache_key, result)
    return result
```

### 5.3 Update cache key format

Update `src/ohtv/analysis/cache.py`:

```python
def compute_cache_key(
    prompt_id: str,
    context_level: int,
) -> str:
    """Compute cache key for analysis results.
    
    New format: prompt=objectives.brief,context=1
    Old format: assess=False,context_level=minimal,detail_level=brief
    
    The cache manager handles both formats for backward compatibility.
    """
    return f"prompt={prompt_id},context={context_level}"
```

### 5.4 Deprecate old commands

Mark `objectives` and `summary` commands as deprecated:

```python
@cli.command(deprecated=True)
def objectives(...):
    """DEPRECATED: Use 'ohtv analyze objectives' instead."""
    console.print("[yellow]Warning: 'ohtv objectives' is deprecated. Use 'ohtv analyze objectives'.[/yellow]")
    # Forward to analyze command
    ...

@cli.command(deprecated=True)  
def summary(...):
    """DEPRECATED: Use 'ohtv analyze objectives -v brief -q' instead."""
    console.print("[yellow]Warning: 'ohtv summary' is deprecated. Use 'ohtv analyze objectives -v brief -q'.[/yellow]")
    # Forward to analyze command
    ...
```

### 5.5 Update `ohtv prompts` command

Show available families and variants:

```
$ ohtv prompts list

Prompt Families:

  objectives/
    brief (default)     Extract user goal in 1-2 sentences
      Context levels: minimal (1), default (2), full (3)
    brief_assess        Extract user goal and assess completion
      Context levels: minimal (1), default (2), full (3)
    standard            Standard analysis with outcomes
      Context levels: minimal (1), default (2), full (3)
    ...

  code_review/
    default             Analyze code changes
      Context levels: edits_only (1), with_commands (2), full (3)

Use: ohtv analyze <family> [-v variant] [-c context] <conversation_id>
```

## Acceptance Criteria

1. `ohtv analyze <family> [id]` works for all prompt families
2. `-v` selects variant, `-c` selects context level
3. All existing conversation filters work (`-D`, `-W`, `--repo`, etc.)
4. Multi-conversation analysis works with parallel processing
5. Cache key uses new format but old cache entries still work
6. `objectives` and `summary` commands show deprecation warning
7. `ohtv prompts list` shows families, variants, and context levels
8. All unit tests pass
9. Existing tests still pass

## Files to Create/Modify

- `src/ohtv/cli.py` - MODIFY: Add `analyze` command, deprecate old commands
- `src/ohtv/analysis/__init__.py` - MODIFY: Add generic analysis function
- `src/ohtv/analysis/cache.py` - MODIFY: New cache key format
- `tests/unit/cli/test_analyze.py` - NEW

## Notes

- Prioritize backward compatibility for cache
- The deprecation warnings should be helpful, not annoying
- Consider keeping old commands working for at least one release cycle
