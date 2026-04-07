# Trajectory Viewer Design Document

## 1. Introduction

### Problem Statement

OpenHands stores conversation history as a series of JSON event files in `~/.openhands/conversations/{conversation_id}/events/`. While this format preserves complete information, it presents challenges for users who want to:

1. **Review past conversations** - Event files contain large system prompts (~70KB each), full terminal outputs, and verbose tool definitions, making it difficult to see the actual conversation flow
2. **Share conversation excerpts** - There's no way to extract just the human-readable dialogue without tool noise
3. **Debug agent behavior** - Understanding what happened requires manually parsing dozens of JSON files
4. **Create training data** - Extracting clean conversation pairs (user/agent) requires custom scripting

A typical conversation with ~160 events can be several megabytes of JSON, where the actual user/agent dialogue may be only a few kilobytes.

### Proposed Solution

Create a CLI utility called `trajectory-viewer` (or `ohtv` for short) that:

1. **Reads OpenHands conversation history** from the local `~/.openhands/conversations/` directory
2. **Filters and formats events** based on user-selectable options
3. **Outputs compact, readable summaries** in multiple formats (Markdown, JSON, plain text)

Users will be able to quickly review what happened in a conversation, extract just the dialogue, or get detailed action logs - all from a simple command line interface.

## 2. User Interface

### Global Options

```bash
# Default: looks in ~/.openhands/conversations/ (local source)
ohtv list
ohtv show <id>

# Specify alternate directory (local source only)
ohtv --dir /path/to/conversations list
ohtv -D ~/backups/openhands/conversations show <id>

# Can also use environment variable
export OHTV_CONVERSATIONS_DIR=/path/to/conversations
ohtv list
```

#### Unified Data Access

The `list` and `show` commands transparently search across both local CLI conversations and synced cloud conversations:

```bash
# Lists conversations from both sources (local + synced cloud)
ohtv list

# Show works with any conversation ID (local or cloud)
ohtv show <id>

# Sync cloud conversations to local storage (requires API key)
export OH_API_KEY=your_api_key
ohtv sync
```

**How it works:**
- `list` merges conversations from `~/.openhands/conversations/` (local) and `~/.openhands/cloud/conversations/` (synced cloud)
- `show` searches both directories for the conversation ID
- Results are sorted by timestamp regardless of source
- A "Source" column in list output indicates where each conversation came from (local vs cloud)

### Listing Conversations

```bash
# List conversations (default: newest first)
ohtv list
ohtv list --reverse              # Oldest first

# Limit and slice
ohtv list -n 10                  # Show 10 most recent
ohtv list -n 10 -k 20            # Skip 20, show next 10
ohtv list -r -n 10               # Show 10 oldest

# Output format
ohtv list --format table         # Default: tabular output
ohtv list --format json          # JSON for scripting
ohtv list --format csv           # CSV export
```

#### Example List Output (table format)

```
ID       Source  Started              Duration  Events  Title
────────────────────────────────────────────────────────────────────────────────────────────────
005fc28  cloud   2026-02-24 16:49:46    43m 26s     162  I don't understand what is happening with OpenHands...
fd2954f  cloud   2026-02-24 14:22:03    12m 15s      47  Create a branch using SDK from PR #2334...
fbcfa59  local   2026-02-23 09:15:22     8m 42s      31  Help me debug this CI failure...

Showing 3 of 483 conversations (412 cloud, 71 local)
```

Short IDs (first 7 characters) are used in table output for readability. Full IDs are shown in `show` output and JSON/CSV formats. The `show` command accepts both short and full IDs via prefix matching.

### Viewing a Conversation

```bash
# View conversation summary (default when no content flags specified)
ohtv show <conversation_id>
ohtv show <partial_id>          # Supports prefix matching

# Default output (no content flags):
# - First/last timestamps
# - Event counts by type
# - Total events

# View with specific content types
ohtv show <id> --messages        # User + agent messages only
ohtv show <id> --actions         # Include action summaries
ohtv show <id> --outputs         # Include tool call outputs
ohtv show <id> --thinking        # Include thinking blocks
ohtv show <id> --all             # Everything

# Display order and slicing
ohtv show <id> --reverse         # Show newest events first (default: oldest first)
ohtv show <id> -n 10             # Show first 10 events
ohtv show <id> -n 10 -k 20       # Show events 20-29 (skip 20, take 10)
ohtv show <id> -r -n 10          # Show last 10 events (newest first)
ohtv show <id> -r -n 10 -k 5     # Skip 5 newest, show next 10

# Pipe to less for interactive paging
ohtv show <id> -m | less

# Output format options
ohtv show <id> --format markdown  # Default
ohtv show <id> --format json
ohtv show <id> --format text

# Output to file
ohtv show <id> -o conversation.md

# Show timestamps
ohtv show <id> --timestamps

# Just show statistics
ohtv show <id> --stats           # Only show counts, no content
```

### Content Selection Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--user-messages` | `-u` | Include user's messages |
| `--agent-messages` | `-a` | Include agent's response messages |
| `--finish` | `-f` | Include finish action message |
| `--action-summaries` | `-s` | Include brief tool call summaries |
| `--action-details` | `-d` | Include full tool call details (command, args) |
| `--outputs` | `-O` | Include tool call outputs/observations |
| `--thinking` | `-t` | Include thinking/reasoning blocks |
| `--timestamps` | `-T` | Include timestamps on events |
| `--all` | `-A` | Include everything |
| `--messages` | `-m` | Shorthand for `-u -a -f` |

### Display Options (shared by `list` and `show`)

| Flag | Short | Description |
|------|-------|-------------|
| `--reverse` | `-r` | Reverse order (`list`: oldest first; `show`: newest first) |
| `--max` | `-n` | Maximum number of items to display |
| `--offset` | `-k` | Skip first N items (use with `--max` for slicing) |
| `--output` | `-o` | Write output to file |
| `--format` | `-F` | Output format (see below) |

### Show-specific Options

| Flag | Short | Description |
|------|-------|-------------|
| `--stats` | `-S` | Show only statistics (counts by type), no content |

### Output Formats

| Command | Formats | Default |
|---------|---------|---------|
| `ohtv list` | table, json, csv | table |
| `ohtv show` | markdown, json, text | markdown |

### Example Output: Default (no content flags)

```
Conversation: 005fc289a6fc4c7a9409d83153399c67
Title: I don't understand what is happening with OpenHands ACP server...

Started:  2026-02-24 16:49:46
Ended:    2026-02-24 17:33:12
Duration: 43m 26s

Event Counts:
  User messages:    10
  Agent messages:    9
  Actions:          71
  Observations:     71
  Finish:            1
  ─────────────────────
  Total:           162
```

**Note on titles:** Local trajectory data does not store explicit conversation titles. The title is derived from the first ~60 characters of the first user message, truncated at word boundaries with "..." appended.

### Example Output: With --messages flag (Markdown format)

```markdown
# Conversation: 005fc289a6fc4c7a9409d83153399c67
**Started:** 2026-02-24 16:49:46
**Ended:** 2026-02-24 17:33:12
**Duration:** 43m 26s

| Type | Count |
|------|-------|
| User messages | 10 |
| Agent messages | 9 |
| Actions | 71 |
| Observations | 71 |
| Finish | 1 |
| **Total** | **162** |

---

## User
I don't understand what is happening with OpenHands ACP server in IDEA...
[log content]

## Agent
Let me help you debug this. I'll start by examining the OpenHands configuration.

> **Action:** View .openhands directory structure for config and logs

## Agent
Based on the logs, I can see that IDEA is trying to start the OpenHands ACP server...

---

## User
Is there a way to get additional debugging output?

## Agent
Good question. Let me check the available options.

> **Action:** Check ACP command help for debug options

## Finish
I've investigated the OpenHands ACP integration with IntelliJ IDEA...
```

## 3. Technical Design

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Interface                         │
│                  (click or argparse)                     │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Conversation Loader                     │
│   - Discover conversations in ~/.openhands/conversations │
│   - Load and parse event JSON files                      │
│   - Handle truncated outputs from observations/          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Event Parser                          │
│   - Classify events by kind/source                       │
│   - Extract relevant fields based on filters             │
│   - Build structured event stream                        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Output Formatter                       │
│   - Markdown, JSON, or plain text                        │
│   - Configurable verbosity levels                        │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Data Model

#### 3.2.1 Event Types (from OpenHands)

| Kind | Source | Key Fields |
|------|--------|------------|
| `SystemPromptEvent` | agent | `system_prompt.text` (skip - too large) |
| `MessageEvent` | user | `llm_message.content[].text` |
| `MessageEvent` | agent | `llm_message.content[].text` |
| `ActionEvent` | agent | `tool_name`, `summary`, `action`, `thought`, `thinking_blocks` |
| `ObservationEvent` | environment | `observation.content`, `tool_name`, `action_id` |

#### 3.2.2 Internal Data Structures

```python
@dataclass
class GlobalConfig:
    """Global configuration, can be set via CLI flags or environment."""
    conversations_dir: Path  # Default: ~/.openhands/conversations/
    
    @classmethod
    def default(cls) -> "GlobalConfig":
        env_dir = os.environ.get("OHTV_CONVERSATIONS_DIR")
        if env_dir:
            return cls(conversations_dir=Path(env_dir))
        return cls(conversations_dir=Path.home() / ".openhands" / "conversations")


@dataclass
class ListOptions:
    """Options for the list command."""
    reverse: bool = False  # Default: newest first, reverse = oldest first
    max_items: int | None = None
    offset: int = 0
    format: str = "table"  # table, json, csv
    output_file: str | None = None


@dataclass
class ConversationMeta:
    id: str
    path: Path
    started: datetime
    ended: datetime
    event_count: int
    title: str | None  # Derived from first user message (first ~60 chars)
    
@dataclass
class EventCounts:
    user_messages: int = 0
    agent_messages: int = 0
    actions: int = 0
    observations: int = 0
    finish: int = 0
    
    @property
    def total(self) -> int:
        return (self.user_messages + self.agent_messages + 
                self.actions + self.observations + self.finish)

@dataclass
class ParsedEvent:
    id: str
    timestamp: datetime
    kind: str  # 'user_message', 'agent_message', 'action', 'observation', 'finish'
    content: str  # The main text content
    summary: str | None  # For actions
    tool_name: str | None  # For actions/observations
    thinking: str | None  # Reasoning content
    action_id: str | None  # Links observations to actions

@dataclass
class DisplayOptions:
    # Content selection
    user_messages: bool = False
    agent_messages: bool = False
    finish: bool = False
    action_summaries: bool = False
    action_details: bool = False
    outputs: bool = False
    thinking: bool = False
    
    # Display options
    timestamps: bool = False
    reverse: bool = False
    stats_only: bool = False
    max_events: int | None = None  # Limit number of events shown
    offset: int = 0  # Skip first N events (applied after reverse)
    
    # Output options
    format: str = "markdown"  # markdown, json, text
    output_file: str | None = None
    
    def has_content_flags(self) -> bool:
        """Check if any content flags were explicitly set."""
        return any([
            self.user_messages,
            self.agent_messages, 
            self.finish,
            self.action_summaries,
            self.action_details,
            self.outputs,
            self.thinking
        ])
```

### 3.3 Core Components

#### 3.3.1 Conversation Discovery

```python
def discover_conversations(config: GlobalConfig) -> list[ConversationMeta]:
    """Find all conversations in the configured directory."""
    conversations = []
    
    if not config.conversations_dir.exists():
        return conversations
    
    for conv_dir in config.conversations_dir.iterdir():
        if conv_dir.is_dir() and (conv_dir / "events").exists():
            events = list((conv_dir / "events").glob("event-*.json"))
            if events:
                # Get timestamps from first and last events
                sorted_events = sorted(events, key=lambda p: p.name)
                first_event = sorted_events[0]
                last_event = sorted_events[-1]
                
                with open(first_event) as f:
                    data = json.load(f)
                    started = datetime.fromisoformat(data["timestamp"])
                
                with open(last_event) as f:
                    data = json.load(f)
                    ended = datetime.fromisoformat(data["timestamp"])
                
                # Get title from first user message
                title = None
                for event_file in sorted_events:
                    with open(event_file) as f:
                        data = json.load(f)
                    if data.get("kind") == "MessageEvent" and data.get("source") == "user":
                        content = data.get("llm_message", {}).get("content", [])
                        if content and isinstance(content, list):
                            title = derive_title(content[0].get("text", ""))
                        break
                
                conversations.append(ConversationMeta(
                    id=conv_dir.name,
                    path=conv_dir,
                    started=started,
                    ended=ended,
                    event_count=len(events),
                    title=title
                ))
    
    # Default sort: newest first
    return sorted(conversations, key=lambda c: c.started, reverse=True)


def list_conversations(config: GlobalConfig, options: ListOptions) -> list[ConversationMeta]:
    """List conversations with filtering and slicing."""
    conversations = discover_conversations(config)
    
    # Apply reverse (default is newest first, reverse = oldest first)
    if options.reverse:
        conversations = list(reversed(conversations))
    
    # Apply offset and max slicing
    if options.offset:
        conversations = conversations[options.offset:]
    if options.max_items:
        conversations = conversations[:options.max_items]
    
    return conversations
```

#### 3.3.2 Event Loading and Parsing

```python
def load_events(conv_path: Path) -> list[ParsedEvent]:
    """Load and parse all events from a conversation."""
    events_dir = conv_path / "events"
    observations_dir = conv_path / "observations"
    
    parsed = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        with open(event_file) as f:
            data = json.load(f)
        
        parsed_event = parse_event(data, observations_dir)
        if parsed_event:
            parsed.append(parsed_event)
    
    return parsed

def parse_event(data: dict, observations_dir: Path) -> ParsedEvent | None:
    """Parse a single event into our internal format."""
    kind = data.get("kind")
    source = data.get("source")
    
    if kind == "SystemPromptEvent":
        return None  # Skip system prompts
    
    if kind == "MessageEvent":
        content = extract_message_content(data.get("llm_message", {}))
        return ParsedEvent(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            kind="user_message" if source == "user" else "agent_message",
            content=content,
            summary=None,
            tool_name=None,
            thinking=None,
            action_id=None
        )
    
    if kind == "ActionEvent":
        tool_name = data.get("tool_name")
        if tool_name == "finish":
            return ParsedEvent(
                id=data["id"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                kind="finish",
                content=data.get("action", {}).get("message", ""),
                summary=data.get("summary"),
                tool_name="finish",
                thinking=extract_thinking(data),
                action_id=None
            )
        else:
            return ParsedEvent(
                id=data["id"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                kind="action",
                content=json.dumps(data.get("action", {})),
                summary=data.get("summary"),
                tool_name=tool_name,
                thinking=extract_thinking(data),
                action_id=None
            )
    
    if kind == "ObservationEvent":
        content = extract_observation_content(data, observations_dir)
        return ParsedEvent(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            kind="observation",
            content=content,
            summary=None,
            tool_name=data.get("tool_name"),
            thinking=None,
            action_id=data.get("action_id")
        )
    
    return None
```

#### 3.3.3 Output Formatting

```python
def count_events(events: list[ParsedEvent]) -> EventCounts:
    """Count events by type."""
    counts = EventCounts()
    for event in events:
        if event.kind == "user_message":
            counts.user_messages += 1
        elif event.kind == "agent_message":
            counts.agent_messages += 1
        elif event.kind == "action":
            counts.actions += 1
        elif event.kind == "observation":
            counts.observations += 1
        elif event.kind == "finish":
            counts.finish += 1
    return counts

def format_duration(start: datetime, end: datetime) -> str:
    """Format duration between two timestamps."""
    delta = end - start
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


class MarkdownFormatter:
    def format(self, events: list[ParsedEvent], options: DisplayOptions, 
               meta: ConversationMeta) -> str:
        counts = count_events(events)
        duration = format_duration(meta.started, meta.ended)
        
        lines = [
            f"# Conversation: {meta.id}",
        ]
        if meta.title:
            lines.append(f"**Title:** {meta.title}")
        lines.extend([
            f"**Started:** {meta.started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Ended:** {meta.ended.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Duration:** {duration}",
            "",
            "| Type | Count |",
            "|------|-------|",
            f"| User messages | {counts.user_messages} |",
            f"| Agent messages | {counts.agent_messages} |",
            f"| Actions | {counts.actions} |",
            f"| Observations | {counts.observations} |",
            f"| Finish | {counts.finish} |",
            f"| **Total** | **{counts.total}** |",
            "",
        ])
        
        # If stats_only or no content flags, just return the header
        if options.stats_only or not options.has_content_flags():
            return "\n".join(lines)
        
        lines.extend(["---", ""])
        
        # Apply reverse if requested
        display_events = list(reversed(events)) if options.reverse else events
        
        # Apply offset and max_events slicing
        total_events = len(display_events)
        if options.offset:
            display_events = display_events[options.offset:]
        if options.max_events:
            display_events = display_events[:options.max_events]
        
        for event in self._filter_events(display_events, options):
            lines.extend(self._format_event(event, options))
        
        # Add note if output was sliced
        shown = len(display_events)
        if shown < total_events:
            start = options.offset
            end = start + shown
            lines.append(f"*... showing events {start}-{end-1} of {total_events} total*")
        
        return "\n".join(lines)
    
    def _format_event(self, event: ParsedEvent, options: DisplayOptions) -> list[str]:
        lines = []
        
        if options.timestamps:
            lines.append(f"*{event.timestamp.strftime('%H:%M:%S')}*")
        
        if event.kind == "user_message" and options.user_messages:
            lines.append("## User")
            lines.append(event.content)
            lines.append("")
        
        elif event.kind == "agent_message" and options.agent_messages:
            lines.append("## Agent")
            lines.append(event.content)
            lines.append("")
        
        elif event.kind == "finish" and options.finish:
            lines.append("## Finish")
            lines.append(event.content)
            lines.append("")
        
        elif event.kind == "action" and options.action_summaries:
            if event.summary:
                lines.append(f"> **Action:** {event.summary}")
                lines.append("")
            if options.action_details:
                lines.append(f"```json\n{event.content}\n```")
                lines.append("")
        
        elif event.kind == "observation" and options.outputs:
            lines.append(f"<details><summary>Output ({event.tool_name})</summary>")
            lines.append("")
            lines.append(f"```\n{event.content}\n```")
            lines.append("</details>")
            lines.append("")
        
        if event.thinking and options.thinking:
            lines.append(f"<details><summary>Thinking</summary>")
            lines.append("")
            lines.append(event.thinking)
            lines.append("</details>")
            lines.append("")
        
        return lines


class TextFormatter:
    """Plain text formatter for default output (no content flags)."""
    
    def format_stats(self, events: list[ParsedEvent], meta: ConversationMeta) -> str:
        counts = count_events(events)
        duration = format_duration(meta.started, meta.ended)
        
        title_line = f"Title: {meta.title}\n" if meta.title else ""
        
        return f"""Conversation: {meta.id}
{title_line}
Started:  {meta.started.strftime('%Y-%m-%d %H:%M:%S')}
Ended:    {meta.ended.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {duration}

Event Counts:
  User messages:  {counts.user_messages:>4}
  Agent messages: {counts.agent_messages:>4}
  Actions:        {counts.actions:>4}
  Observations:   {counts.observations:>4}
  Finish:         {counts.finish:>4}
  ─────────────────────
  Total:          {counts.total:>4}
"""


def derive_title(first_user_message: str, max_length: int = 60) -> str:
    """Derive a title from the first user message."""
    if not first_user_message:
        return None
    
    # Take only first line
    first_line = first_user_message.split('\n')[0].strip()
    
    # Truncate at max_length, but try to break at word boundary
    if len(first_line) <= max_length:
        return first_line
    
    truncated = first_line[:max_length]
    # Find last space to break at word boundary
    last_space = truncated.rfind(' ')
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    
    return truncated.rstrip() + "..."


SHORT_ID_LENGTH = 7


class TableFormatter:
    """Format conversation list as a table."""
    
    def format(self, conversations: list[ConversationMeta], 
               total_count: int, options: ListOptions) -> str:
        lines = [
            "ID       Started              Duration  Events  Title",
            "─" * 90
        ]
        
        for conv in conversations:
            short_id = conv.id[:SHORT_ID_LENGTH]
            duration = format_duration(conv.started, conv.ended)
            title = conv.title or "(no title)"
            if len(title) > 50:
                title = title[:47] + "..."
            
            lines.append(
                f"{short_id}  {conv.started.strftime('%Y-%m-%d %H:%M:%S')}  "
                f"{duration:>9}  {conv.event_count:>6}  {title}"
            )
        
        lines.append("")
        shown = len(conversations)
        if shown < total_count:
            start = options.offset
            end = start + shown
            lines.append(f"Showing {start}-{end-1} of {total_count} conversations")
        else:
            lines.append(f"Showing {shown} of {total_count} conversations")
        
        return "\n".join(lines)


class CSVFormatter:
    """Format conversation list as CSV."""
    
    def format(self, conversations: list[ConversationMeta]) -> str:
        lines = ["id,started,ended,duration_seconds,events,title"]
        
        for conv in conversations:
            duration_secs = int((conv.ended - conv.started).total_seconds())
            title = (conv.title or "").replace('"', '""')
            lines.append(
                f'{conv.id},{conv.started.isoformat()},{conv.ended.isoformat()},'
                f'{duration_secs},{conv.event_count},"{title}"'
            )
        
        return "\n".join(lines)
```

### 3.4 File Structure

```
trajectory-viewer/
├── pyproject.toml
├── README.md
├── DESIGN.md
├── src/
│   └── ohtv/
│       ├── __init__.py
│       ├── cli.py              # CLI interface (click)
│       ├── config.py           # GlobalConfig, environment handling, API key
│       ├── models.py           # Data classes (ParsedEvent, ConversationMeta, etc.)
│       ├── sources/            # Data source abstraction layer
│       │   ├── __init__.py
│       │   ├── base.py         # Abstract DataSource interface
│       │   ├── local.py        # Local filesystem source (conversation discovery, loading)
│       │   └── cloud.py        # Cloud API client (V1 API)
│       ├── parser.py           # Event parsing logic (shared by sources)
│       └── formatters/
│           ├── __init__.py
│           ├── base.py         # Base formatter class
│           ├── table.py        # Table output (for list)
│           ├── csv.py          # CSV output (for list)
│           ├── markdown.py     # Markdown output (for show)
│           ├── json.py         # JSON output (for both)
│           └── text.py         # Plain text output (for show)
└── tests/
    ├── __init__.py
    ├── test_local_source.py    # Local source tests
    ├── test_cloud_source.py    # Cloud source tests (with mocking)
    ├── test_parser.py
    └── test_formatters.py
```

## 4. Implementation Plan

### Milestone 1: Core Loading and Parsing
**Goal:** Load and parse conversation events into internal data structures

**Deliverables:**
- `src/ohtv/models.py` - Data classes
- `src/ohtv/loader.py` - Conversation discovery
- `src/ohtv/parser.py` - Event parsing
- `tests/test_loader.py` - Loader tests
- `tests/test_parser.py` - Parser tests

**Acceptance Criteria:**
- Can discover conversations in `~/.openhands/conversations/`
- Can load and parse all event types (Message, Action, Observation)
- Correctly identifies user messages, agent messages, actions, and finish events
- Handles truncated outputs from `observations/` directory

**Demo:** Python script that loads a conversation and prints event counts by type

### Milestone 2: Basic CLI with Default Output
**Goal:** Working CLI with default stats output and basic content display

**Deliverables:**
- `src/ohtv/cli.py` - CLI using click
- `src/ohtv/formatters/text.py` - Plain text formatter (for default stats)
- `src/ohtv/formatters/markdown.py` - Markdown formatter
- `pyproject.toml` - Package configuration with CLI entry point

**Acceptance Criteria:**
- `ohtv list` shows available conversations with timestamps and event counts
- `ohtv show <id>` (no flags) outputs stats summary (timestamps, counts by type, total)
- `ohtv show <id> --messages` outputs formatted conversation content
- `--reverse` flag works to show newest events first
- `--stats` flag works to show only statistics even when other flags present

**Demo:** Run `ohtv list -n 5` to see recent conversations, then `ohtv show <id>` for stats, `ohtv show <id> -m` for messages

### Milestone 3: Full Feature Set
**Goal:** Complete feature set with all formatters and options

**Deliverables:**
- `src/ohtv/formatters/json.py` - JSON output
- `src/ohtv/formatters/text.py` - Plain text output
- All filter flags implemented
- Output to file support

**Acceptance Criteria:**
- All content selection flags work as documented
- All output formats work (Markdown, JSON, text)
- `--timestamps` adds timestamps to events
- `-o filename` writes to file
- Prefix matching works for conversation IDs

**Demo:** Full usage demonstration with various flag combinations

### Milestone 4: Cloud Sync Infrastructure
**Goal:** Enable syncing cloud conversations to local storage for offline viewing

**Deliverables:**
- `src/ohtv/sources/base.py` - ConversationInfo dataclass
- `src/ohtv/sources/cloud.py` - CloudClient (API client for sync only)
- `src/ohtv/exporter.py` - TrajectoryExporter (zip → local format conversion)
- `src/ohtv/sync.py` - SyncManager with incremental sync logic
- Updated `src/ohtv/config.py` - API key handling, cloud_conversations_dir
- New `ohtv sync` command in CLI
- `sync_manifest.json` state tracking
- `tests/test_sync.py` - Sync tests

**Acceptance Criteria:**
- `ohtv sync` downloads new/updated conversations
- Uses `updated_at__gte` filter to minimize API calls
- Manifest tracks sync state across runs
- Hourly sync with no changes = 1 API call
- `--force` re-downloads everything
- `--dry-run` shows what would sync
- `--status` shows sync statistics
- `--quiet` mode for cron jobs
- Proper handling of `OH_API_KEY` environment variable
- Clear error messages for authentication failures
- Exponential backoff on rate limiting (429)

**Demo:**
```bash
export OH_API_KEY=your_key

# First sync - downloads all conversations
ohtv sync
# Output: Synced 127 conversations (127 new, 0 updated)

# Wait an hour, run again
ohtv sync
# Output: Synced 2 conversations (1 new, 1 updated)

# Check status
ohtv sync --status

# Setup hourly cron
echo "0 * * * * ohtv sync --quiet" | crontab -
```

### Milestone 4.5: Unified Data Access
**Goal:** Make `list` and `show` commands transparently search both local and synced cloud data

**Deliverables:**
- `list` merges results from both directories
- `show` searches both directories for conversation ID
- Source column in list output (local vs cloud)
- Conversation count shows breakdown by source

**Acceptance Criteria:**
- `ohtv list` shows conversations from both local and cloud sources
- `ohtv show <id>` works regardless of whether ID is local or cloud
- List output includes "Source" column indicating origin
- Summary line shows count breakdown: "Showing N of M (X cloud, Y local)"

**Demo:** 
```bash
# After running ohtv sync...
ohtv list -n 5
# Shows mixed results from both sources with Source column

ohtv show abc123 --messages
# Works whether abc123 is local or cloud
```

### Milestone 5: Polish and Distribution
**Goal:** Ready for distribution and daily use

**Deliverables:**
- README.md with usage examples (local and cloud)
- Error handling for edge cases
- Performance optimization for large conversations
- Optional: Homebrew formula or PyPI package

**Acceptance Criteria:**
- Clear error messages for invalid IDs, missing conversations
- Works with conversations of any size
- Installable via `uv tool install` or `pip install`
- Cloud pagination handles 1000+ events gracefully

## 5. Cloud Support Architecture

Cloud conversations are accessed via a **sync-first architecture**: the `sync` command downloads conversations from the cloud API to local storage, and all other commands (`list`, `show`, `refs`) read from this local cache. This provides:

- **Offline access** - View cloud conversations without internet
- **Fast response times** - No API latency for list/show operations
- **Reduced API calls** - Incremental sync minimizes bandwidth
- **Transparent access** - Users don't need to know where a conversation came from

### 5.1 Unified Data Access

The `list` and `show` commands automatically search both local and synced cloud directories:

```bash
# Sync cloud conversations (one-time or periodic)
export OH_API_KEY=your_api_key
ohtv sync

# List shows all conversations from both sources
ohtv list
# Output includes "Source" column: local or cloud

# Show works with any conversation ID
ohtv show abc123    # Works whether abc123 is local or cloud
```

**Search order:** When resolving a conversation ID, the tool searches:
1. Local CLI conversations (`~/.openhands/conversations/`)
2. Synced cloud conversations (`~/.openhands/cloud/conversations/`)

If a conversation ID exists in both locations (unlikely but possible), the local version takes precedence.

### 5.2 Cloud API Endpoints (used only by `sync`)

The `sync` command uses these V1 API endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/app-conversations/search` | Find conversations updated since last sync |
| `GET /api/v1/app-conversations/{id}/download` | Download full trajectory zip |

All other endpoints (events/search, events/count, etc.) are not needed because we read from locally synced files.

### 5.3 Cloud Event Types

Downloaded cloud events have a `kind` field that maps to our display categories:

| Cloud Event Kind | Display Category |
|------------------|------------------|
| `MessageEvent` (source=user) | User message |
| `MessageEvent` (source=agent) | Agent message |
| `ActionEvent` | Action |
| `ObservationEvent` | Observation |
| `ActionEvent` with `FinishAction` | Finish |
| `ConversationErrorEvent` | Error |
| `AgentErrorEvent` | Error |
| `SystemPromptEvent` | System (hidden by default) |
| `TokenEvent` | Token usage (hidden by default) |

### 5.4 Architecture

```
src/ohtv/
├── sources/
│   ├── __init__.py
│   ├── base.py           # ConversationInfo dataclass
│   └── cloud.py          # CloudClient (for sync only)
├── sync.py               # SyncManager - orchestrates cloud sync
├── exporter.py           # TrajectoryExporter - converts zip to local format
├── config.py             # Config with local_conversations_dir, cloud_conversations_dir
└── cli.py                # Commands: sync, list, show, refs
```

The key insight is that there is **no CloudDataSource** for list/show operations. Instead:

1. `sync` uses `CloudClient` to download trajectories to `~/.openhands/cloud/conversations/`
2. `list` merges conversations from both local and cloud directories
3. `show` searches both directories for the requested conversation ID

### 5.5 Unified Listing Implementation

The `list` command merges conversations from both sources:

```python
def list_all_conversations() -> list[ConversationInfo]:
    """List conversations from both local and cloud sources."""
    conversations = []
    
    # Local conversations (scan directory)
    for conv in discover_local_conversations():
        conv.source = "local"
        conversations.append(conv)
    
    # Cloud conversations (from manifest for speed)
    manifest = load_sync_manifest()
    for conv_id, info in manifest.conversations.items():
        conversations.append(ConversationInfo(
            id=conv_id,
            title=info.get("title"),
            updated_at=info.get("updated_at"),
            event_count=info.get("event_count"),
            source="cloud",
        ))
    
    return sorted(conversations, key=lambda c: c.updated_at, reverse=True)
```

### 5.6 Unified Show Implementation

The `show` command searches both directories:

```python
def find_conversation(conv_id: str) -> Path | None:
    """Find conversation directory by ID, searching local first then cloud."""
    # Try local first
    local_dir = config.local_conversations_dir / conv_id
    if local_dir.exists():
        return local_dir
    
    # Try cloud
    cloud_dir = config.cloud_conversations_dir / conv_id
    if cloud_dir.exists():
        return cloud_dir
    
    # Try prefix matching in both
    for base_dir in [config.local_conversations_dir, config.cloud_conversations_dir]:
        matches = [d for d in base_dir.iterdir() if d.name.startswith(conv_id)]
        if len(matches) == 1:
            return matches[0]
    
    return None
```

## 6. Format Comparison: Local vs Cloud

### Summary

**The local CLI format and cloud download format are nearly identical**, making interoperability straightforward.

### Event File Structure Comparison

| Aspect | Local CLI | Cloud Download |
|--------|-----------|----------------|
| **Location** | `~/.openhands/conversations/{id}/events/` | Flat in zip |
| **Filename pattern** | `event-00000-<uuid>.json` | `event_000000_<uuid>.json` |
| **Metadata file** | `base_state.json` | `meta.json` |
| **Observations** | Separate `observations/` dir | Inline in events |

### Event JSON Structure

Both formats use **identical event structure**:

```json
{
  "id": "uuid",
  "timestamp": "2026-04-07T12:40:20.483411",
  "source": "user|agent|environment",
  "kind": "MessageEvent|ActionEvent|ObservationEvent|...",
  // ... kind-specific fields
}
```

**MessageEvent** (identical in both):
```json
{
  "kind": "MessageEvent",
  "llm_message": {
    "role": "user",
    "content": [{"type": "text", "text": "..."}]
  }
}
```

**ActionEvent** (identical in both):
```json
{
  "kind": "ActionEvent",
  "action": {"command": "...", "kind": "TerminalAction"},
  "tool_name": "terminal",
  "tool_call_id": "toolu_...",
  "tool_call": {...}
}
```

### Metadata Differences

**Local `base_state.json`** contains:
- Full agent configuration
- LLM settings (model, API key masked, etc.)
- Tool definitions
- Session ID

**Cloud `meta.json`** contains:
- Conversation ID, title
- Repository/branch info
- Sandbox ID
- Created/updated timestamps
- Metrics (token usage, cost)

## 7. Cloud Sync

The `sync` command is the only way to access cloud conversations. It efficiently downloads all cloud conversations, only fetching new or updated trajectories.

### 7.1 Usage

```bash
# Sync all cloud conversations (incremental - only downloads changes)
ohtv sync

# Force re-download everything
ohtv sync --force

# Dry run - show what would be synced without downloading
ohtv sync --dry-run

# Show sync status (last sync time, counts)
ohtv sync --status

# Sync only conversations updated after a specific date
ohtv sync --since 2026-01-01
```

### 7.2 Efficiency Strategy

The sync is designed to minimize API calls, especially for hourly/scheduled runs:

**Key Insight:** Use the `updated_at__gte` filter to query only conversations that have changed since last sync.

```
GET /api/v1/app-conversations/search?updated_at__gte={last_sync_time}
```

**API Call Analysis:**
| Scenario | API Calls |
|----------|-----------|
| No changes since last sync | 1 (search returns empty) |
| 5 conversations updated | 1 search + 5 downloads = 6 |
| First sync (500 conversations) | ~5 paginated searches + 500 downloads |

**Hourly cron job:** Typically 1-10 API calls (1 search + few downloads)

### 7.3 Sync Manifest

Track sync state in `~/.openhands/cloud/sync_manifest.json`:

```json
{
  "last_sync_at": "2026-04-07T10:00:00Z",
  "sync_count": 42,
  "conversations": {
    "abc123def456": {
      "title": "Debug CI failure...",
      "updated_at": "2026-04-05T12:30:00Z",
      "event_count": 42,
      "downloaded_at": "2026-04-06T08:00:00Z"
    },
    "789xyz000111": {
      "title": "Implement new feature...",
      "updated_at": "2026-04-07T09:15:00Z",
      "event_count": 18,
      "downloaded_at": "2026-04-07T10:00:00Z"
    }
  }
}
```

### 7.4 Sync Algorithm

```python
def sync_conversations(force: bool = False, since: datetime = None) -> SyncResult:
    """
    Efficiently sync cloud conversations to local storage.
    
    Returns:
        SyncResult with counts of new, updated, unchanged, and failed
    """
    manifest = load_manifest()
    
    # Determine cutoff time
    if force:
        cutoff = None  # Fetch all
    elif since:
        cutoff = since
    else:
        cutoff = manifest.get("last_sync_at")
    
    # Phase 1: Query for updated conversations (single paginated request)
    # This is the key optimization - only fetches metadata for changed conversations
    params = {"limit": 100}
    if cutoff:
        params["updated_at__gte"] = cutoff
    
    updated_conversations = []
    page_id = None
    
    while True:
        if page_id:
            params["page_id"] = page_id
        
        response = client.get("/api/v1/app-conversations/search", params=params)
        data = response.json()
        updated_conversations.extend(data["items"])
        
        page_id = data.get("next_page_id")
        if not page_id:
            break
    
    # Phase 2: Download only conversations that need updating
    result = SyncResult()
    
    for conv in updated_conversations:
        conv_id = conv["id"]
        cloud_updated_at = conv["updated_at"]
        
        local_info = manifest["conversations"].get(conv_id)
        
        # Skip if we already have this version
        if local_info and local_info["updated_at"] >= cloud_updated_at and not force:
            result.unchanged += 1
            continue
        
        # Download trajectory
        try:
            download_trajectory(conv_id)
            
            # Update manifest
            manifest["conversations"][conv_id] = {
                "title": conv.get("title"),
                "updated_at": cloud_updated_at,
                "event_count": get_local_event_count(conv_id),
                "downloaded_at": datetime.utcnow().isoformat() + "Z"
            }
            
            if local_info:
                result.updated += 1
            else:
                result.new += 1
                
        except Exception as e:
            result.failed += 1
            result.errors.append((conv_id, str(e)))
    
    # Update sync timestamp
    manifest["last_sync_at"] = datetime.utcnow().isoformat() + "Z"
    manifest["sync_count"] = manifest.get("sync_count", 0) + 1
    save_manifest(manifest)
    
    return result
```

### 7.5 Sync Output

```bash
$ ohtv sync
Syncing cloud conversations...
  Checking for updates since 2026-04-07T09:00:00Z...
  Found 3 conversations to sync (2 new, 1 updated)
  
  [1/3] abc123... "Debug CI failure" (new)
  [2/3] def456... "Implement feature" (updated)
  [3/3] ghi789... "Fix bug in parser" (new)

Sync complete:
  New:       2
  Updated:   1
  Unchanged: 0
  Failed:    0
  
Next sync will check from: 2026-04-07T10:00:00Z
```

```bash
$ ohtv sync --status
Cloud Sync Status
─────────────────────────────────────────
Last sync:        2026-04-07 10:00:00 UTC
Total synced:     127 conversations
Storage used:     48.3 MB
Sync count:       42

Recent syncs:
  2026-04-07 10:00 - 3 updated
  2026-04-07 09:00 - 0 updated
  2026-04-07 08:00 - 1 updated
```

### 7.6 Cron Setup

```bash
# Sync every hour
0 * * * * /usr/local/bin/ohtv sync --quiet >> ~/.openhands/cloud/sync.log 2>&1
```

### 7.7 Storage Location

Downloaded cloud conversations are stored separately from CLI-generated conversations:

```
~/.openhands/
├── conversations/              # Local CLI conversations (managed by openhands CLI)
└── cloud/
    ├── api_key.txt            # Cloud API key (already exists)
    ├── sync_manifest.json     # Sync state tracking
    ├── sync.log               # Optional sync log
    └── conversations/          # Downloaded cloud conversations (managed by ohtv)
        ├── {conversation_id}/
        │   ├── base_state.json
        │   └── events/
        └── ...
```

This separation:
- Prevents confusion between local and downloaded conversations
- Allows the CLI to manage its own `conversations/` directory
- Groups cloud-related files together under `cloud/`

Environment variable to customize: `OHTV_CLOUD_CONVERSATIONS_DIR`

## 8. Open Questions

1. **Naming:** Is `trajectory-viewer` / `ohtv` the right name? Alternatives:
   - `oh-history` / `ohh`
   - `conv-view` / `cv`
   - `agent-log` / `al`

2. **Observation truncation:** When outputs are truncated to files in `observations/`, should we:
   - Always read the full file?
   - Offer a `--max-output-length` flag?
   - Show a summary with option to expand?

3. **Integration with OpenHands CLI:** Should this be:
   - A standalone tool?
   - A subcommand of `openhands` CLI?
   - Both (standalone that could be integrated later)?

4. **Title derivation:**
   - Currently uses first line only (already implemented in design)
   - Should we strip markdown formatting from the title?
   - Should there be a way to manually set/override titles?

5. **Additional features for future:**
   - Search across conversations?
   - Filter by date range?
   - Export to other formats (HTML, PDF)?
   - ~~Integration with OpenHands Cloud conversations?~~ (Now in scope!)
   - `ohtv tail <id>` - Follow a conversation in real-time (like `tail -f`)?

6. **Cloud-specific questions:**
   - ~~Should we cache cloud responses locally for faster repeat access?~~ (Resolved: sync-first architecture)
   - ~~How to handle pagination for very large conversations (1000+ events)?~~ (Resolved: events read from local files)
   - ~~Should we support downloading the full trajectory zip for offline viewing?~~ (Resolved: `ohtv sync`)
   - Should `sync` support the legacy V0 API for older conversations?
