# Design: MCP Server for ohtv

This document expands on [Issue #26](https://github.com/jpshackelford/ohtv/issues/26) with a detailed design for an MCP (Model Context Protocol) server that exposes ohtv's capabilities to AI agents.

## Problem Statement

ohtv has powerful features for searching and understanding OpenHands conversation history:
- **Semantic search** across conversations using embeddings
- **RAG-based Q&A** via the `ask` command  
- **Objective analysis** extracting goals and outcomes from conversations
- **Git reference tracking** (repos, PRs, issues worked on)

Currently these are only accessible via CLI. An MCP server would let AI agents (Claude, GPT, etc.) leverage this knowledge base directly, enabling use cases like:

- "What did I work on last week?" → Agent searches ohtv and summarizes
- "Show me the conversation where we fixed the auth bug" → Agent finds and retrieves it
- "Which PRs did I touch in the last month?" → Agent queries refs data
- Context-aware coding assistance using past conversation history

## Proposed Solution

### MCP Tools

The server would expose these tools:

#### 1. `search_conversations`
Search across conversations using semantic similarity or keyword matching.

```python
@mcp.tool()
async def search_conversations(
    query: str,
    limit: int = 10,
    exact: bool = False,  # False=semantic, True=keyword (FTS5)
    min_score: float = 0.0,
    since: str | None = None,  # ISO date or relative (e.g., "7d")
) -> list[dict]:
    """Search conversations by concept or keyword.
    
    Returns list of matches with: conversation_id, title, score, created_at
    """
```

#### 2. `ask_question` 
RAG-based question answering over conversation history.

```python
@mcp.tool()
async def ask_question(
    question: str,
    context_chunks: int = 5,
    min_score: float = 0.3,
) -> dict:
    """Ask a question about your conversation history.
    
    Returns: answer (str), sources (list of conversation IDs), search_time, gen_time
    """
```

#### 3. `get_conversation`
Get details about a specific conversation.

```python
@mcp.tool()
async def get_conversation(
    conversation_id: str,
    include_messages: bool = False,
    include_actions: bool = False,
    truncate_outputs: bool = True,
) -> dict:
    """Get conversation metadata and optionally content.
    
    Returns: id, title, created_at, event_count, messages?, actions?
    """
```

#### 4. `list_conversations`
List recent or filtered conversations.

```python
@mcp.tool()
async def list_conversations(
    limit: int = 20,
    since: str | None = None,
    source: str = "all",  # "local", "cloud", "all"
) -> list[dict]:
    """List conversations with optional filtering.
    
    Returns list of: id, title, created_at, source, event_count
    """
```

#### 5. `get_refs`
Get git references (repos, PRs, issues) from conversations.

```python
@mcp.tool()
async def get_refs(
    conversation_id: str | None = None,  # None = all conversations
    ref_type: str | None = None,  # "repo", "pr", "issue", None = all
    since: str | None = None,
) -> list[dict]:
    """Get git references from conversations.
    
    Returns list of: ref_type, url, owner, repo, number?, interactions
    """
```

#### 6. `analyze_conversation`
Get or generate objective analysis for a conversation.

```python
@mcp.tool()
async def analyze_conversation(
    conversation_id: str,
    refresh: bool = False,
) -> dict:
    """Get objective analysis (goal, outcomes) for a conversation.
    
    Returns: goal, primary_outcomes, secondary_outcomes, tags
    Note: Uses cached analysis if available, generates if not.
    """
```

#### 7. `get_embedding_status`
Check embedding health and coverage.

```python
@mcp.tool()
async def get_embedding_status() -> dict:
    """Get status of embeddings for search readiness.
    
    Returns: total_conversations, embedded_conversations, 
             needs_embedding (list of IDs), last_embed_at
    """
```

### Optional Tools (Require API Keys)

These tools have side effects and require specific API keys:

#### 8. `sync_conversations` (requires `OH_API_KEY`)
```python
@mcp.tool()
async def sync_conversations(
    max_new: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Sync conversations from OpenHands Cloud.
    
    Returns: new_count, updated_count, failed_count, skipped_count
    """
```

#### 9. `embed_conversations` (requires `LLM_API_KEY`)
```python
@mcp.tool()
async def embed_conversations(
    conversation_ids: list[str] | None = None,  # None = all missing
    force: bool = False,
    estimate_only: bool = False,
) -> dict:
    """Build embeddings for semantic search.
    
    Returns: embedded_count, token_count, estimated_cost (if estimate_only)
    """
```

## Architecture

### Integration with Existing Code

The MCP server should directly import ohtv modules rather than wrapping CLI commands:

```python
from ohtv.config import Config
from ohtv.db import get_connection, migrate
from ohtv.db.stores import EmbeddingStore, ConversationStore, ReferenceStore
from ohtv.analysis.embeddings import get_embedding
from ohtv.analysis.objectives import analyze_objectives
```

This provides:
- Better performance (no subprocess overhead)
- Proper error handling
- Access to structured data (not text parsing)

### Database Access

- Read operations (search, list, get): Concurrent access is safe
- Write operations (embed, sync): Should acquire locks or be serialized
- Connection management: Pool or per-request connections

### State Management

The MCP server inherits state from:
- Environment variables: `OH_API_KEY`, `LLM_API_KEY`, `LLM_BASE_URL`, etc.
- Config file: `~/.ohtv/config.toml` (if implemented)
- Database: `~/.ohtv/conversations.db`
- Conversation data: `~/.openhands/` directories

### Transport Options

1. **STDIO** (default): For local integration with Claude Desktop, Cursor, etc.
   ```bash
   ohtv mcp serve  # Runs as stdio server
   ```

2. **HTTP/SSE**: For remote access or web integrations
   ```bash
   ohtv mcp serve --transport http --port 8765
   ```

## Data Freshness

The original issue mentions "periodically syncing and caching analysis jobs."

### Challenge
MCP servers are typically request-response; they don't have built-in background job support.

### Options

1. **Lazy approach** (recommended for MVP):
   - `search` and `ask` check for embeddings, return helpful error if missing
   - `get_embedding_status` tool lets agent check coverage
   - User/agent manually triggers `embed_conversations` when needed

2. **Auto-embed on search** (convenience):
   - If query returns no results and embeddings are missing, offer to embed
   - Could be a tool parameter: `auto_embed: bool = False`

3. **External scheduler** (production):
   - Separate cron job or systemd timer runs `ohtv sync && ohtv db embed`
   - MCP server always has fresh data

4. **Background thread** (advanced):
   - MCP server spawns background worker for sync/embed
   - Adds complexity, potential concurrency issues

## Error Handling

Tools should return structured errors:

```python
{
    "error": True,
    "error_type": "EMBEDDINGS_MISSING",  # or "AUTH_REQUIRED", "CONVERSATION_NOT_FOUND", etc.
    "message": "No embeddings found. Run 'ohtv db embed' or use embed_conversations tool.",
    "suggestion": "embed_conversations"
}
```

Common errors:
- `EMBEDDINGS_MISSING`: Search/ask without embeddings
- `AUTH_REQUIRED`: Sync without `OH_API_KEY`
- `LLM_CONFIG_MISSING`: Embed/ask without `LLM_API_KEY`
- `CONVERSATION_NOT_FOUND`: Invalid conversation ID
- `DATABASE_ERROR`: SQLite issues

## Implementation Plan

### Phase 1: Core Tools (MVP)
1. Add `mcp[cli]` dependency
2. Create `src/ohtv/mcp/` module with:
   - `server.py`: FastMCP setup and tool definitions
   - `tools.py`: Tool implementations wrapping existing code
3. Add `ohtv mcp serve` command to CLI
4. Implement: `search_conversations`, `ask_question`, `list_conversations`, `get_conversation`
5. Basic tests with MCP client

### Phase 2: Full Feature Set
1. Add: `get_refs`, `analyze_conversation`, `get_embedding_status`
2. Add: `sync_conversations`, `embed_conversations` (with auth checks)
3. HTTP transport option

### Phase 3: Polish
1. Streaming responses for `ask_question`
2. Better progress reporting for long operations
3. Configuration for default limits, models, etc.
4. Documentation for Claude Desktop / Cursor integration

## Example Usage

### Claude Desktop Configuration
```json
{
  "mcpServers": {
    "ohtv": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ohtv", "ohtv", "mcp", "serve"],
      "env": {
        "LLM_API_KEY": "your-api-key",
        "OH_API_KEY": "your-openhands-key"
      }
    }
  }
}
```

### Agent Interaction Example
```
User: "What was I working on this week?"

Agent: [calls list_conversations(since="7d")]
Agent: [calls search_conversations(query="main tasks this week", limit=5)]
Agent: "This week you worked on:
  - Authentication bug fix (abc123)
  - Docker deployment setup (def456)
  - API refactoring (ghi789)
  Would you like details on any of these?"

User: "Tell me more about the auth bug fix"

Agent: [calls get_conversation(id="abc123", include_messages=True)]
Agent: [calls analyze_conversation(id="abc123")]
Agent: "The auth bug fix conversation (abc123) involved..."
```

## Dependencies

New dependencies needed:
```toml
[project.optional-dependencies]
mcp = [
    "mcp[cli]>=1.0.0",
]
```

## Questions to Resolve

1. **Tool naming**: Should tools use underscores (`search_conversations`) or camelCase (`searchConversations`)? MCP spec allows both.

2. **Authentication**: Should the server require auth, or rely on whoever starts it having proper keys set?

3. **Rate limiting**: Should tools have built-in rate limiting for LLM calls, or rely on external?

4. **Caching**: Beyond existing analysis cache, should MCP responses be cached?

5. **Multi-user**: Is this single-user only, or should it support multiple users with separate data?

## References

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [FastMCP Python SDK](https://github.com/jlowin/fastmcp)
- [Build an MCP Server Tutorial](https://modelcontextprotocol.io/docs/develop/build-server)
