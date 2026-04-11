# Testing Guide

This document describes the testing approach, conventions, and design decisions for the ohtv project.

## Test Structure

Tests are organized to mirror the source code structure, with separate directories for unit and integration tests:

```
tests/
├── conftest.py              # Root pytest configuration (minimal)
├── fixtures/                # Shared test data and helpers
│   ├── conversations/       # Sample conversation files (JSON)
│   ├── db_states/           # Database state fixtures (YAML)
│   ├── conversations.py     # Helpers for loading conversation fixtures
│   └── database.py          # Helpers for loading database fixtures
├── unit/                    # Unit tests (fast, isolated)
│   └── db/
│       ├── stores/          # Tests for each store class
│       └── test_migrations.py
└── integration/             # Integration tests (slower, end-to-end)
    └── conftest.py          # Integration-specific fixtures
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/unit/db/stores/test_conversation_store.py

# Run specific test class or method
uv run pytest tests/unit/db/stores/test_link_store.py::TestLinkRepo::test_upgrades_link_from_read_to_write
```

## Test Fixtures

### Database Fixtures (YAML)

Database state fixtures are defined in YAML files under `tests/fixtures/db_states/`. This separates test data from test logic and makes it easy to review and modify test scenarios.

**Example: `tests/fixtures/db_states/github_refs.yaml`**
```yaml
conversations:
  - id: conv-with-github-refs
    location: /conversations/conv-with-github-refs

repositories:
  - canonical_url: https://github.com/acme/webapp
    fqn: acme/webapp
    short_name: webapp

references:
  - type: issue
    url: https://github.com/acme/webapp/issues/42
    fqn: acme/webapp#42
    display_name: webapp #42

links:
  repos:
    - conversation: conv-with-github-refs
      repo_url: https://github.com/acme/webapp
      type: write
  refs:
    - conversation: conv-with-github-refs
      ref_url: https://github.com/acme/webapp/issues/42
      type: read
```

**Loading in tests:**
```python
from fixtures.database import load_db_state, db_with_github_refs

def test_query_linked_repos():
    db = load_db_state("github_refs")  # Load by name
    # or use convenience function:
    db = db_with_github_refs()
```

### Conversation Fixtures (JSON)

Sample conversation files live in `tests/fixtures/conversations/`. Each subdirectory represents a conversation with realistic structure:

```
conversations/
└── conv-with-github-refs/
    ├── base_state.json
    └── events/
        ├── event-00000-aaa.json
        ├── event-00001-bbb.json
        └── ...
```

**Loading in tests:**
```python
from fixtures.conversations import (
    get_sample_conversation_path,
    copy_conversation_to,
    load_events,
)

def test_parse_events(tmp_path):
    # Copy to tmp_path for isolation
    conv_path = copy_conversation_to("conv-with-github-refs", tmp_path)
    events = load_events(conv_path)
```

### DatabaseBuilder (Programmatic)

For dynamic or parameterized test data, use the `DatabaseBuilder`:

```python
from fixtures.database import DatabaseBuilder
from ohtv.db.models import LinkType

def test_with_custom_data():
    db = (DatabaseBuilder()
        .with_conversation("conv-1", "/path/to/conv-1")
        .with_repo("https://github.com/owner/repo", "owner/repo", "repo")
        .with_link_repo("conv-1", "https://github.com/owner/repo", LinkType.WRITE)
        .build())
```

Prefer YAML fixtures for static test scenarios. Use the builder when you need to generate data dynamically.

## Test Principles

### One Assertion Per Test

Each test should verify one specific behavior. This makes failures easy to diagnose:

```python
# Good: focused test
def test_upsert_updates_existing_conversation_location(self, conversation_store, db_conn):
    conversation_store.upsert(Conversation(id="conv-1", location="/old/path"))
    db_conn.commit()
    
    conversation_store.upsert(Conversation(id="conv-1", location="/new/path"))
    db_conn.commit()
    
    result = conversation_store.get("conv-1")
    assert result.location == "/new/path"

# Avoid: multiple unrelated assertions
def test_conversation_crud(self, conversation_store, db_conn):
    # Too many things being tested...
```

### Test Isolation

Each test gets a fresh database (function-scoped fixtures). This is slightly slower than sharing state but ensures tests can't affect each other:

```python
@pytest.fixture
def db_conn():
    """Fresh in-memory database for each test."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    yield conn
    conn.close()
```

### Real Database, No Mocks

We use in-memory SQLite for database tests rather than mocking. This tests real behavior and is fast enough (~0.1s for 50 tests).

## Design Decisions

### Why Dataclasses Instead of Pydantic?

We use plain Python dataclasses for our models rather than Pydantic:

```python
@dataclass
class Conversation:
    id: str
    location: str
```

**Rationale:**
- Our models are simple (a few string/int fields)
- We control all data sources (our own DB, our own YAML fixtures)
- No need for complex validation or serialization
- Fewer dependencies (dataclasses are stdlib)
- Faster for simple cases

**When to reconsider:**
- If we start parsing complex JSON from external APIs
- If we need robust validation of untrusted input
- If serialization/deserialization becomes a pain point

### Why YAML for Fixtures Instead of Factory Boy?

Factory Boy (Python port of Ruby's Factory Girl/Bot) is great for generating test data programmatically. We use YAML files instead for database state fixtures because:

- **Readability**: YAML is easy to read and review in PRs
- **Static scenarios**: Our fixtures represent known states, not generated data
- **Separation of concerns**: Data is separate from loading logic
- **No magic**: What you see in the YAML is what you get

The `DatabaseBuilder` serves the role Factory Boy would for dynamic/parameterized data.

### Why In-Memory SQLite?

For database tests, we use `:memory:` SQLite databases:

- **Fast**: No disk I/O, tests run in ~0.1s
- **Isolated**: Each test gets a fresh database
- **Real**: Tests actual SQLite behavior, not mocks
- **Simple**: No cleanup needed, no test pollution

## Adding New Tests

### Adding a Database Fixture

1. Create a YAML file in `tests/fixtures/db_states/`:
   ```yaml
   # my_scenario.yaml
   conversations:
     - id: conv-1
       location: /path/to/conv-1
   # ... rest of data
   ```

2. Optionally add a convenience function in `tests/fixtures/database.py`:
   ```python
   def db_with_my_scenario() -> sqlite3.Connection:
       return load_db_state("my_scenario")
   ```

### Adding a Conversation Fixture

1. Create a directory in `tests/fixtures/conversations/`:
   ```
   my-conversation/
   ├── base_state.json
   └── events/
       └── event-00000-xxx.json
   ```

2. Use in tests:
   ```python
   conv_path = copy_conversation_to("my-conversation", tmp_path)
   ```

### Adding Unit Tests

1. Create test file mirroring source structure:
   - Source: `src/ohtv/db/stores/foo_store.py`
   - Test: `tests/unit/db/stores/test_foo_store.py`

2. Organize tests by method:
   ```python
   class TestMethodName:
       def test_behavior_one(self, relevant_fixture):
           ...
       
       def test_behavior_two(self, relevant_fixture):
           ...
   ```
