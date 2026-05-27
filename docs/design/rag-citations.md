# RAG Citations Enhancement

## Overview

This document describes the enhanced citation system for the `ohtv ask` command, implementing the requirements from [GitHub issue #32](https://github.com/jpshackelford/ohtv/issues/32).

## Features

1. **Contextual Chunk Enrichment**: Prepends date, summary, and refs to chunks before embedding (Anthropic's "contextual retrieval" technique)
2. **Database Schema**: Added `summary` column to `conversations` table
3. **Full cloud URLs** for source conversations (only within 14-day retention)
4. **Conversation dates and summaries** in citation output
5. **"See Also" section** with related PRs, issues, and repositories
6. **Improved LLM prompts** for better source attribution with ref disambiguation

## Architecture

### New Data Structures (rag.py)

```python
@dataclass
class RefInfo:
    """A reference (PR/issue) associated with a conversation."""
    ref_type: str  # "pr" or "issue"
    url: str
    fqn: str  # e.g., "owner/repo#123"
    display_name: str
    link_type: str  # "read" or "write"

@dataclass 
class RepoInfo:
    """A repository associated with a conversation."""
    url: str
    fqn: str  # e.g., "owner/repo"
    short_name: str
    link_type: str

@dataclass
class ConversationSource:
    """Full source information for a conversation."""
    conversation_id: str
    title: str
    summary: str | None
    source: str  # "local" or "cloud"
    cloud_url: str | None
    created_at: datetime | None
    repos: list[RepoInfo]
    prs: list[RefInfo]
    issues: list[RefInfo]
```

### Extended ContextChunk

```python
@dataclass
class ContextChunk:
    conversation_id: str
    title: str
    embed_type: str
    source_text: str
    score: float
    summary: str | None = None      # NEW
    cloud_url: str | None = None    # NEW
    created_at: datetime | None = None  # NEW
    conv_source: str = "local"      # NEW
    source: ConversationSource | None = None  # NEW
```

### Extended RAGAnswer

```python
@dataclass
class RAGAnswer:
    # ... existing fields ...
    related_repos: list[RepoInfo] | None = None   # NEW
    related_prs: list[RefInfo] | None = None      # NEW
    related_issues: list[RefInfo] | None = None   # NEW
```

## LLM Context vs User Display

**LLM receives** (for accurate citation):
- Title
- Date/age (e.g., "3 days ago")
- Summary
- Linked refs with FQN (e.g., "PR jpshackelford/ohtv#23")

**User sees** (in CLI output):
- Clickable URLs (for cloud conversations within 14-day retention)
- Full conversation IDs
- Conversation summaries
- "See Also" section with aggregated refs

## Contextual Chunk Enrichment

Based on Anthropic's [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) research (2024), chunks are enriched with contextual preambles before embedding:

```
Date: 2026-04-19
Summary: Configure MCP secrets handling
Related: PR jpshackelford/ohtv#23, Issue jpshackelford/ohtv#42
---
[actual chunk content]
```

This improves retrieval accuracy for queries that reference specific dates, PRs, or issues.

## Database Changes

Migration `009_add_summary_column.py` adds:
- `summary TEXT` column to `conversations` table

Summaries are populated via:
1. The `summaries` processing stage (extracts goal from objective analysis)
2. Automatic extraction during embedding generation (fallback to analysis goal)

## Usage

Ensure refs are indexed and summaries generated:

```bash
# Sync and run all processing including summary generation
ohtv sync -p

# Or run processing stages manually
ohtv db scan
ohtv db process refs
ohtv db process summaries

# Generate embeddings with contextual preambles
ohtv db embed

# Ask questions
ohtv ask "how did we fix the authentication bug?"
```

## Expected Output

```
$ ohtv ask "help me find the PR discussion about mcp configuration"

Answer:
In the conversation "Configure MCP secrets handling" from 3 days ago, the team 
discussed the approach for handling MCP secrets. The key decision was to use 
environment variable injection rather than storing secrets in config files...

─────────────────────────────────────────────────
Sources (2 conversations):
• [4403c7fb] Configure MCP secrets handling (2026-04-19)
  User wanted to configure MCP secrets handling for the plugin system.
  https://app.all-hands.dev/conversations/4403c7fb01ac40b0b4a6fc727314c7c2
• [a1b2c3d4] MCP security review (2026-04-17)
  Security review of MCP integration with focus on secret handling.
  https://app.all-hands.dev/conversations/a1b2c3d4e5f6789012345678901234ab

See Also:
  Pull Requests:
  • jpshackelford/ohtv #42
  Issues:
  • jpshackelford/ohtv #38
  Repositories:
  • jpshackelford/ohtv

Search: 0.15s | Generation: 2.34s | Model: openai/gpt-4o-mini
```

## Cloud URL Retention

Cloud conversations have a 14-day retention period. URLs are only displayed for conversations within this window to avoid broken links.

## Graceful Degradation

The system gracefully handles missing components:
- If ref stores are not available, citations show basic info without refs
- If summaries are not generated, the `summary` field is `None`
- If conversations are local (not cloud), no URL is displayed

## References

- [GitHub Issue #32](https://github.com/jpshackelford/ohtv/issues/32)
- [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
