# Database Indexing System

This document describes ohtv's SQLite-based indexing system for conversation metadata.

## Overview

ohtv uses a lightweight SQLite database to index conversations and their relationships to external references (repositories, issues, PRs). The database enables:

- **Fast discovery**: Find conversations that touched a specific repo or issue
- **Incremental processing**: Only analyze new/changed conversations
- **Multi-stage pipelines**: Run expensive operations (like LLM analysis) incrementally

**Key principle**: Conversation content stays on the filesystem. The database only stores metadata and relationships.

## Directory Structure

```
~/.openhands/                    # OpenHands data (read-only for ohtv)
  conversations/                 # Local CLI conversations
  cloud/conversations/           # Synced cloud conversations

~/.ohtv/                         # ohtv-generated data
  index.db                       # SQLite database
  logs/ohtv.log                  # Application logs
  sync_manifest.json             # Cloud sync state
```

Override with environment variables:
- `OHTV_DIR` - Base directory for ohtv data
- `OHTV_DB_PATH` - Direct path to database file

## Schema

### Core Tables

```
conversations
├── id (TEXT PRIMARY KEY)        # Conversation UUID
├── location (TEXT)              # Filesystem path
├── events_mtime (REAL)          # Last modification time of events/
├── event_count (INTEGER)        # Number of event files
└── registered_at (TEXT)         # When first indexed

repositories
├── id (INTEGER PRIMARY KEY)
├── canonical_url (TEXT UNIQUE)  # e.g., https://github.com/owner/repo
├── fqn (TEXT)                   # Fully qualified name: owner/repo
└── short_name (TEXT)            # Just the repo name

refs
├── id (INTEGER PRIMARY KEY)
├── ref_type (TEXT)              # "issue" or "pr"
├── url (TEXT UNIQUE)            # Full URL
├── fqn (TEXT)                   # owner/repo#123
└── display_name (TEXT)          # repo #123
```

### Link Tables

```
conversation_repos               # Conversation ↔ Repository links
├── conversation_id (TEXT)
├── repo_id (INTEGER)
└── link_type (TEXT)             # "read" or "write"

conversation_refs                # Conversation ↔ Issue/PR links
├── conversation_id (TEXT)
├── ref_id (INTEGER)
└── link_type (TEXT)             # "read" or "write"
```

### Actions Table

```
actions                          # Recognized actions in conversations
├── id (INTEGER PRIMARY KEY)
├── conversation_id (TEXT)       # FK to conversations
├── action_type (TEXT)           # e.g., "edit-code", "open-pr"
├── target (TEXT)                # File path, URL, etc.
├── metadata (TEXT)              # JSON for additional details
└── event_id (TEXT)              # ID of triggering event
```

### Processing State

```
conversation_stages              # Tracks processing completion
├── conversation_id (TEXT)
├── stage_name (TEXT)            # e.g., "refs", "actions"
├── event_count (INTEGER)        # Event count when processed
└── completed_at (TEXT)          # ISO timestamp
```

## Processing Pipeline

### Two-Phase Architecture

```
Phase 1: Registration (fast, O(1) per conversation)
┌─────────────────────────────────────────────────────┐
│  ohtv db scan                                       │
│  - Discovers conversations on filesystem            │
│  - Records location, mtime, event_count             │
│  - Uses mtime for fast change detection             │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
Phase 2: Processing (per-stage, incremental)
┌─────────────────────────────────────────────────────┐
│  ohtv db process <stage>                            │
│  - Runs processing logic on pending conversations   │
│  - Tracks completion in conversation_stages         │
│  - Only reprocesses when event_count increases      │
└─────────────────────────────────────────────────────┘
```

### Change Detection

The system uses a two-level change detection strategy:

1. **Fast filter (mtime)**: Compare `events/` directory modification time
   - O(1) stat call per conversation
   - Catches most unchanged conversations quickly

2. **Checkpoint (event_count)**: Count event files when mtime changes
   - Only runs if mtime differs from stored value
   - Determines if conversation actually has new content

This handles edge cases like:
- File copies that change mtime without adding events
- Backup restoration with different timestamps

### Processing Stages

Each stage is independent and tracked separately:

| Stage | Description | CLI Command |
|-------|-------------|-------------|
| `refs` | Extract repos, issues, PRs | `ohtv db process refs` |
| `actions` | Recognize actions (edits, git, PRs, etc.) | `ohtv db process actions` |
| *(future)* `objectives` | LLM-based goal extraction | `ohtv db process objectives` |

Stages can be:
- Run in any order
- Rerun with `--force` to reprocess all
- Run for specific conversation with `--conversation`

### Action Types

The `actions` stage recognizes these action types:

| Category | Action Type | Description |
|----------|-------------|-------------|
| **File Edits** | `edit-code` | Edits to code files (.py, .js, .ts, etc.) |
| | `edit-docs` | Edits to documentation (.md, .rst, etc.) |
| | `edit-other` | Edits to other file types |
| | `study-code` | Viewing code files (without editing) |
| **Git** | `git-commit` | Git commit operations |
| | `git-push` | Git push operations |
| **PRs/MRs** | `open-pr` | Creating a pull request |
| | `pr-comment` | Commenting on a PR |
| | `pr-review` | Reviewing a PR (gh command or /codereview skill) |
| | `pr-edit` | Editing PR title/description |
| | `merge-pr` | Merging PR into target branch |
| | `close-pr` | Closing PR without merging |
| | `check-ci` | Checking CI status |
| **Issues** | `open-issue` | Creating an issue |
| | `issue-comment` | Commenting on an issue |
| | `issue-edit` | Editing issue title/description |
| | `close-issue` | Closing an issue |
| **Notion** | `read-notion` | Reading Notion pages/databases |
| | `write-notion` | Creating/updating Notion pages |
| **Research** | `web-research` | Web browsing/research |

#### Extensible Recognizers

Action recognition uses a modular recognizer system in `src/ohtv/db/stages/recognizers/`:

- `file_edits.py` - EDIT_CODE, EDIT_DOCS, EDIT_OTHER, STUDY_CODE
- `git_operations.py` - GIT_COMMIT, GIT_PUSH
- `github_actions.py` - OPEN_PR, PR_*, ISSUE_*, CHECK_CI, MERGE_PR, CLOSE_*
- `notion_actions.py` - READ_NOTION, WRITE_NOTION (MCP tools and API calls)
- `research.py` - WEB_RESEARCH
- `skill_invocations.py` - PR_REVIEW (via /codereview slash commands)

To add a new recognizer:
1. Create a function `recognize_foo(event, context) -> list[ConversationAction]`
2. Register it in the `RECOGNIZERS` list in `__init__.py`

## Link Types

References are classified by interaction type:

| Link Type | Meaning | Example Actions |
|-----------|---------|-----------------|
| `read` | Referenced but not modified | Viewed issue, read PR |
| `write` | Created or modified | Pushed, commented, merged |

**Note**: `write` implies `read`. We only store one link per relationship, preferring `write` if any write action was detected.

## CLI Commands

### Batch Operations

```bash
# Register all conversations in database
ohtv db scan

# Update all, ignoring mtime optimization
ohtv db scan --force

# Remove DB entries for deleted conversations
ohtv db scan --remove-missing

# Process refs for all pending conversations
ohtv db process refs

# Reprocess all conversations
ohtv db process refs --force

# Process single conversation
ohtv db process refs --conversation <id>
```

### Automatic Indexing

The `ohtv refs` command automatically indexes when viewing:

```bash
# Auto-indexes, then displays refs
ohtv refs <conversation_id>

# Skip indexing (faster for one-off lookups)
ohtv refs <conversation_id> --no-index
```

### Database Management

```bash
# Initialize/migrate database
ohtv db init

# Show database statistics
ohtv db status
```

## Code Organization

```
src/ohtv/db/
├── __init__.py          # Public API exports
├── connection.py        # Database connection management
├── migrations.py        # Schema migration system
├── scanner.py           # Filesystem scanning logic
├── migrations/          # SQL migration files
│   ├── 001_initial.py
│   └── 002_processing_stages.py
├── models/              # Data models (dataclasses)
│   ├── conversation.py
│   ├── repository.py
│   ├── reference.py
│   ├── link.py
│   └── stage.py
├── stores/              # Data access layer
│   ├── conversation_store.py
│   ├── repo_store.py
│   ├── reference_store.py
│   ├── link_store.py
│   └── stage_store.py
└── stages/              # Processing stage implementations
    ├── __init__.py      # Stage registry
    └── refs.py          # Refs extraction stage
```

## Design Decisions

### Why SQLite?

- Zero configuration, single file
- Handles thousands of conversations easily
- ACID transactions for data integrity
- Efficient for read-heavy workloads (queries)
- Portable (database moves with the data)

### Why Not Store Content?

Conversation content (events) can be large and is already efficiently stored as JSON files. The database stores only:
- Identifiers and locations
- Relationships between entities
- Processing state

This keeps the database small and fast while avoiding data duplication.

### Why Separate Registration and Processing?

1. **Registration is cheap**: Just stat the filesystem
2. **Processing is expensive**: Parsing events, running LLM
3. **Independence**: Each stage can fail/retry independently
4. **Parallelism**: Multiple stages could run concurrently (future)

### Why Track event_count?

When a conversation grows (new events added), we need to reprocess. Tracking `event_count` at completion lets us detect this:

```
Stored: event_count=50 at completion
Current: event_count=55 on disk
→ Conversation has 5 new events, needs reprocessing
```

## Future Enhancements

- **Query commands**: `ohtv db query --repo X` to find conversations
- **More stages**: `objectives`, `summary` for LLM-based analysis
- **Bulk export**: Export relationships to CSV/JSON
- **Statistics**: Activity by repo, time-based analysis
