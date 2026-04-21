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

## Design Philosophy

**MCP exposes capabilities, not infrastructure.**

An agent using ohtv's MCP tools should be able to search and ask questions seamlessly - the underlying sync, embedding, and caching infrastructure should be invisible. The agent shouldn't need to manage embeddings or trigger syncs; that's implementation detail.

This means:
- **No `embed_conversations` tool** - embeddings are built automatically
- **No `sync_conversations` tool** - sync happens in the background  
- **No `get_embedding_status` tool** - the server handles data freshness internally

## Proposed Solution

### MCP Tools (User-Facing)

The server exposes these high-level tools:

#### 1. `search`
Search across conversations using semantic similarity or keyword matching.

```python
@mcp.tool()
async def search(
    query: str,
    limit: int = 10,
    exact: bool = False,  # False=semantic, True=keyword (FTS5)
    since: str | None = None,  # ISO date or relative (e.g., "7d")
) -> list[dict]:
    """Search conversations by concept or keyword.
    
    Returns list of matches with: conversation_id, title, score, created_at
    """
```

#### 2. `ask` 
RAG-based question answering over conversation history.

```python
@mcp.tool()
async def ask(
    question: str,
    context_chunks: int = 5,
) -> dict:
    """Ask a question about your conversation history.
    
    Returns: answer (str), sources (list of conversation IDs)
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
    conversation_id: str | None = None,  # None = aggregate across conversations
    ref_type: str | None = None,  # "repo", "pr", "issue", None = all
    since: str | None = None,
) -> list[dict]:
    """Get git references from conversations.
    
    Returns list of: ref_type, url, owner, repo, number?, interactions
    """
```

#### 6. `analyze`
Get or generate objective analysis for a conversation.

```python
@mcp.tool()
async def analyze(
    conversation_id: str,
) -> dict:
    """Get objective analysis (goal, outcomes) for a conversation.
    
    Returns: goal, primary_outcomes, secondary_outcomes, tags
    Note: Uses cached analysis if available, generates if not.
    """
```

### Background Scheduler

The MCP server runs a background scheduler (inspired by [OpenPaw's scheduler](https://github.com/jpshackelford/OpenPaw/blob/main/src/openpaws/scheduler.py)) to keep data fresh:

```python
@dataclass
class SchedulerConfig:
    """Background task configuration."""
    sync_interval: int = 900  # 15 minutes
    embed_after_sync: bool = True
    analysis_batch_size: int = 10  # conversations per batch
```

**Scheduled Tasks:**

1. **Sync** (every 15 min by default):
   - Calls `SyncManager.sync()` to fetch new/updated conversations from cloud
   - Only runs if `OH_API_KEY` is configured

2. **Embed** (after sync):
   - Embeds any conversations that don't have embeddings
   - Only runs if `LLM_API_KEY` is configured
   - Tracks which conversations need embedding via database

3. **Analyze** (optional, on-demand):
   - Could batch-analyze conversations without cached analysis
   - Lower priority - analysis is more expensive

**Implementation:**

```python
class MCPServer:
    def __init__(self):
        self.scheduler = Scheduler()
        self.setup_background_tasks()
    
    def setup_background_tasks(self):
        if os.environ.get("OH_API_KEY"):
            self.scheduler.add_interval_task(
                name="sync",
                interval=self.config.sync_interval,
                func=self._background_sync,
            )
    
    async def _background_sync(self):
        """Sync conversations and embed new ones."""
        result = await self.sync_manager.sync()
        if result.total_synced > 0 and os.environ.get("LLM_API_KEY"):
            await self._embed_missing()
```

### Scheduler Design

Borrowing from OpenPaw's battle-tested scheduler:

```python
@dataclass
class ScheduledTask:
    """A task with scheduling info."""
    name: str
    func: Callable
    interval: int | None = None  # seconds
    schedule: str | None = None  # cron expression
    last_run: datetime | None = None
    next_run: datetime | None = None
    status: str = "active"  # active, paused, running

class Scheduler:
    """Manages background tasks."""
    
    def __init__(self):
        self.tasks: dict[str, ScheduledTask] = {}
        self._running = False
    
    def add_interval_task(self, name: str, interval: int, func: Callable):
        """Add a task that runs every `interval` seconds."""
        task = ScheduledTask(name=name, func=func, interval=interval)
        task.next_run = datetime.now() + timedelta(seconds=interval)
        self.tasks[name] = task
    
    async def run_loop(self):
        """Main scheduler loop - runs due tasks."""
        self._running = True
        while self._running:
            for task in self.get_due_tasks():
                await self._execute_task(task)
            await asyncio.sleep(30)  # Check every 30 seconds
    
    def start(self):
        """Start the scheduler as a background task."""
        asyncio.create_task(self.run_loop())
```

## Architecture

### Integration with Existing Code

The MCP server directly imports ohtv modules:

```python
from ohtv.config import Config
from ohtv.db import get_connection, migrate
from ohtv.db.stores import EmbeddingStore, ConversationStore, ReferenceStore
from ohtv.analysis.embeddings import get_embedding, embed_conversation_full
from ohtv.analysis.objectives import analyze_objectives
from ohtv.sync import SyncManager
```

This provides:
- Better performance (no subprocess overhead)
- Proper error handling
- Access to structured data (not text parsing)

### Database Access

- Read operations (search, list, get): Concurrent access is safe
- Write operations (embed, sync): Serialized via scheduler (one task at a time)
- Connection management: Per-request connections for reads, dedicated connection for scheduler

### State Management

The MCP server inherits state from:
- Environment variables: `OH_API_KEY`, `LLM_API_KEY`, `LLM_BASE_URL`, etc.
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

## Graceful Degradation

When required services are unavailable, tools degrade gracefully:

| Scenario | Behavior |
|----------|----------|
| No embeddings yet | `search` returns empty results with message "Building search index, try again shortly" |
| No `LLM_API_KEY` | `ask` returns error "Question answering requires LLM configuration" |
| No `OH_API_KEY` | Background sync disabled; local conversations still searchable |
| Sync fails | Logged, retried on next interval; cached data still available |

## Error Handling

Tools return structured errors when needed:

```python
{
    "error": True,
    "error_type": "LLM_CONFIG_MISSING",
    "message": "Question answering requires LLM_API_KEY to be configured."
}
```

Common errors:
- `LLM_CONFIG_MISSING`: `ask` or `analyze` without `LLM_API_KEY`
- `CONVERSATION_NOT_FOUND`: Invalid conversation ID
- `DATABASE_ERROR`: SQLite issues
- `INDEXING_IN_PROGRESS`: Search index still being built

## Implementation Plan

### Phase 1: Core Server
1. Add `mcp[cli]` and `croniter` dependencies
2. Create `src/ohtv/mcp/` module:
   - `server.py`: FastMCP setup and tool definitions
   - `scheduler.py`: Background task scheduler (adapted from OpenPaw)
3. Add `ohtv mcp serve` command to CLI
4. Implement tools: `search`, `ask`, `list_conversations`, `get_conversation`
5. Implement background sync + embed

### Phase 2: Full Feature Set
1. Add: `get_refs`, `analyze`
2. HTTP transport option
3. Configurable scheduler intervals

### Phase 3: Polish
1. Streaming responses for `ask`
2. Better progress reporting
3. Documentation for Claude Desktop / Cursor integration

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
Agent: [calls search(query="main tasks this week", limit=5)]
Agent: "This week you worked on:
  - Authentication bug fix (abc123)
  - Docker deployment setup (def456)
  - API refactoring (ghi789)
  Would you like details on any of these?"

User: "Tell me more about the auth bug fix"

Agent: [calls get_conversation(id="abc123", include_messages=True)]
Agent: [calls analyze(id="abc123")]
Agent: "The auth bug fix conversation (abc123) involved..."
```

## Dependencies

New dependencies needed:
```toml
[project.optional-dependencies]
mcp = [
    "mcp[cli]>=1.0.0",
    "croniter>=2.0.0",  # For cron expression parsing (if needed)
]
```

## Configuration

Server configuration via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `OHTV_MCP_SYNC_INTERVAL` | Seconds between sync runs | 900 (15 min) |
| `OHTV_MCP_EMBED_AFTER_SYNC` | Auto-embed after sync | true |
| `LLM_API_KEY` | Required for `ask`, `analyze`, and embedding | - |
| `OH_API_KEY` | Required for cloud sync | - |

## References

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [FastMCP Python SDK](https://github.com/jlowin/fastmcp)
- [OpenPaw Scheduler](https://github.com/jpshackelford/OpenPaw/blob/main/src/openpaws/scheduler.py) - Reference implementation for background tasks
- [Build an MCP Server Tutorial](https://modelcontextprotocol.io/docs/develop/build-server)
