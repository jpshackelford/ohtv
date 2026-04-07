# OpenHands Cloud API Reference

This document describes the OpenHands Cloud V1 API endpoints used by the trajectory viewer.

## OpenAPI Specification

The complete OpenAPI specification is available at:

```
https://app.all-hands.dev/openapi.json
```

You can use this to generate client code, explore the full API, or import into tools like Postman.

## Authentication

All API requests require authentication via the `OH_API_KEY` environment variable:

```bash
curl -s "https://app.all-hands.dev/api/v1/..." \
  -H "Authorization: Bearer $OH_API_KEY" \
  -H "Accept: application/json"
```

## Base URL

- **Production**: `https://app.all-hands.dev`
- **Custom** (via `OHTV_CLOUD_URL`): User-configurable

## API Versions

| Version | Path Prefix | Status |
|---------|-------------|--------|
| V0 (Legacy) | `/api/conversations/...` | Deprecated (removal: 2026-04-01) |
| V1 (Current) | `/api/v1/...` | **Use this** |

---

## Conversation Endpoints

### List/Search Conversations

```
GET /api/v1/app-conversations/search
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `title__contains` | string | Filter by title substring |
| `created_at__gte` | datetime | Created after (ISO 8601) |
| `created_at__lt` | datetime | Created before (ISO 8601) |
| `updated_at__gte` | datetime | Updated after (ISO 8601) |
| `updated_at__lt` | datetime | Updated before (ISO 8601) |
| `sandbox_id__eq` | string | Filter by exact sandbox ID |
| `page_id` | string | Pagination cursor (from `next_page_id`) |
| `limit` | integer | Max results per page (1-100, default: 100) |
| `include_sub_conversations` | boolean | Include sub-conversations (default: false) |

**Response:**

```json
{
  "items": [
    {
      "id": "3f0346d2bcd34f06b220829a96fff1c2",
      "title": "Conversation title",
      "created_at": "2026-04-07T12:39:19.008368Z",
      "updated_at": "2026-04-07T12:45:30.123456Z",
      "created_by_user_id": "adf1e6c0-51df-45bc-adc1-cb10386ef9f3",
      "sandbox_id": "7NeNnOPV9oyRPweN8xoq0h",
      "selected_repository": "owner/repo",
      "selected_branch": "main",
      "git_provider": "github",
      "trigger": "user_message",
      "llm_model": "litellm_proxy/prod/claude-opus-4-5-20251101",
      "parent_conversation_id": null,
      "sub_conversation_ids": [],
      "public": null,
      "tags": {},
      "metrics": {
        "model_name": "default",
        "accumulated_cost": 0.0,
        "max_budget_per_task": null,
        "accumulated_token_usage": {
          "prompt_tokens": 12500,
          "completion_tokens": 3200,
          "cache_read_tokens": 8000,
          "cache_write_tokens": 0,
          "reasoning_tokens": 1500
        }
      },
      "pr_number": []
    }
  ],
  "next_page_id": "cursor_string_or_null"
}
```

**Key Fields for Sync:**

| Field | Description | Used For |
|-------|-------------|----------|
| `id` | Conversation UUID | Unique identifier, download path |
| `title` | Conversation title | Display, manifest |
| `updated_at` | Last update timestamp | **Change detection** (critical for sync) |
| `created_at` | Creation timestamp | Display, filtering |

**Example:**

```bash
# List recent conversations
curl -s "https://app.all-hands.dev/api/v1/app-conversations/search?limit=10" \
  -H "Authorization: Bearer $OH_API_KEY"

# Search by title
curl -s "https://app.all-hands.dev/api/v1/app-conversations/search?title__contains=debug&limit=20" \
  -H "Authorization: Bearer $OH_API_KEY"

# Filter by date range
curl -s "https://app.all-hands.dev/api/v1/app-conversations/search?created_at__gte=2026-01-01T00:00:00Z&created_at__lt=2026-02-01T00:00:00Z" \
  -H "Authorization: Bearer $OH_API_KEY"

# Incremental sync: Get conversations updated since last sync (KEY FOR SYNC COMMAND)
curl -s "https://app.all-hands.dev/api/v1/app-conversations/search?updated_at__gte=2026-04-07T09:00:00Z" \
  -H "Authorization: Bearer $OH_API_KEY"
```

**Note on Sorting:** Results are returned in descending order by `updated_at` (most recently updated first).

---

### Count Conversations

```
GET /api/v1/app-conversations/count
```

**Query Parameters:** Same filters as search endpoint (excluding pagination).

**Response:** Integer count.

```bash
curl -s "https://app.all-hands.dev/api/v1/app-conversations/count" \
  -H "Authorization: Bearer $OH_API_KEY"
# Returns: 483
```

---

### Get Conversations by IDs

```
GET /api/v1/app-conversations?ids=<id1>&ids=<id2>
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `ids` | string[] | One or more conversation UUIDs |

**Response:** Array of AppConversation objects (null for missing IDs).

```bash
curl -s "https://app.all-hands.dev/api/v1/app-conversations?ids=abc123&ids=def456" \
  -H "Authorization: Bearer $OH_API_KEY"
```

---

### Download Conversation Trajectory

```
GET /api/v1/app-conversations/{conversation_id}/download
```

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | string (UUID) | Conversation ID (with or without dashes) |

**Response Headers:**

| Header | Value |
|--------|-------|
| `Content-Type` | `application/zip` |
| `Content-Disposition` | `attachment; filename="trajectory_{id}.zip"` |

**Response Body:** ZIP file containing:
- `meta.json` - Conversation metadata
- `event_NNNNNN_<uuid>.json` - Event files (one per event)

**Status Codes:**

| Code | Description |
|------|-------------|
| 200 | Success - ZIP file returned |
| 401 | Unauthorized - Invalid or missing API key |
| 404 | Not found - Conversation doesn't exist or no access |
| 422 | Validation error - Invalid conversation ID format |

**Example:**

```bash
# Download to file
curl -s "https://app.all-hands.dev/api/v1/app-conversations/abc123/download" \
  -H "Authorization: Bearer $OH_API_KEY" \
  -o trajectory.zip

# Check response headers
curl -sI "https://app.all-hands.dev/api/v1/app-conversations/abc123/download" \
  -H "Authorization: Bearer $OH_API_KEY"

# Download with progress bar (useful for large trajectories)
curl -# "https://app.all-hands.dev/api/v1/app-conversations/abc123/download" \
  -H "Authorization: Bearer $OH_API_KEY" \
  -o trajectory.zip
```

**Notes:**
- The download includes all events, even for running conversations
- Large conversations (1000+ events) may take several seconds to download
- ZIP compression significantly reduces transfer size (typically 5-10x)

---

### Update Conversation

```
PATCH /api/v1/app-conversations/{conversation_id}
```

**Request Body:**

```json
{
  "title": "New title"
}
```

---

## Event Endpoints

### List/Search Events

```
GET /api/v1/conversation/{conversation_id}/events/search
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `kind__eq` | string | Filter by event kind (see below) |
| `timestamp__gte` | datetime | Events after timestamp |
| `timestamp__lt` | datetime | Events before timestamp |
| `sort_order` | string | `TIMESTAMP` (default) or `TIMESTAMP_DESC` |
| `page_id` | string | Pagination cursor |
| `limit` | integer | Max results (1-100, default: 100) |

**Event Kinds:**

| Kind | Source | Description |
|------|--------|-------------|
| `MessageEvent` | user/agent | User or agent message |
| `ActionEvent` | agent | Tool call (action) |
| `ObservationEvent` | environment | Tool result |
| `ConversationStateUpdateEvent` | environment | State change |
| `ConversationErrorEvent` | environment | Conversation-level error |
| `AgentErrorEvent` | agent | Agent error |
| `SystemPromptEvent` | agent | System prompt |
| `TokenEvent` | agent | Token usage |
| `PauseEvent` | user | User pause request |
| `CondensationSummaryEvent` | agent | Context condensation |
| `HookExecutionEvent` | environment | Hook execution |

**Response:**

```json
{
  "items": [
    {
      "id": "event-uuid",
      "timestamp": "2026-04-07T12:40:20.483411",
      "source": "user",
      "kind": "MessageEvent",
      // ... kind-specific fields
    }
  ],
  "next_page_id": "cursor_or_null"
}
```

**Example:**

```bash
# Get all events
curl -s "https://app.all-hands.dev/api/v1/conversation/abc123/events/search?limit=100" \
  -H "Authorization: Bearer $OH_API_KEY"

# Get only ActionEvents
curl -s "https://app.all-hands.dev/api/v1/conversation/abc123/events/search?kind__eq=ActionEvent" \
  -H "Authorization: Bearer $OH_API_KEY"

# Get events in reverse order (newest first)
curl -s "https://app.all-hands.dev/api/v1/conversation/abc123/events/search?sort_order=TIMESTAMP_DESC" \
  -H "Authorization: Bearer $OH_API_KEY"
```

---

### Count Events

```
GET /api/v1/conversation/{conversation_id}/events/count
```

**Query Parameters:** Same filters as search (excluding pagination/sort).

```bash
curl -s "https://app.all-hands.dev/api/v1/conversation/abc123/events/count" \
  -H "Authorization: Bearer $OH_API_KEY"
# Returns: 162
```

---

### Get Events by IDs

```
GET /api/v1/conversation/{conversation_id}/events?id=<id1>&id=<id2>
```

**Response:** Array of Event objects (null for missing IDs).

---

## Event Structures

### MessageEvent

```json
{
  "id": "uuid",
  "timestamp": "2026-04-07T12:40:20.483411",
  "source": "user",
  "kind": "MessageEvent",
  "llm_message": {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "User's message content",
        "cache_prompt": false
      }
    ],
    "thinking_blocks": []
  },
  "activated_skills": ["skill1", "skill2"],
  "extended_content": []
}
```

### ActionEvent

```json
{
  "id": "uuid",
  "timestamp": "2026-04-07T12:40:27.002983",
  "source": "agent",
  "kind": "ActionEvent",
  "thought": [
    {
      "type": "text",
      "text": "Agent's thought process"
    }
  ],
  "thinking_blocks": [],
  "action": {
    "command": "ls -la",
    "kind": "TerminalAction"
  },
  "tool_name": "terminal",
  "tool_call_id": "toolu_01UADW6EstcKmjm5whnysKre",
  "tool_call": {
    "id": "toolu_01UADW6EstcKmjm5whnysKre",
    "name": "terminal",
    "arguments": "{\"command\": \"ls -la\"}",
    "origin": "completion"
  },
  "llm_response_id": "chatcmpl-xxx",
  "security_risk": "LOW",
  "summary": "List directory contents"
}
```

### ObservationEvent

```json
{
  "id": "uuid",
  "timestamp": "2026-04-07T12:40:28.123456",
  "source": "environment",
  "kind": "ObservationEvent",
  "tool_name": "terminal",
  "tool_call_id": "toolu_01UADW6EstcKmjm5whnysKre",
  "action_id": "action-event-uuid",
  "observation": {
    "content": [
      {
        "type": "text",
        "text": "total 48\ndrwxr-xr-x  12 user  staff   384 Apr  7 12:40 .\n..."
      }
    ],
    "exit_code": 0,
    "kind": "TerminalObservation"
  }
}
```

### ConversationErrorEvent

```json
{
  "id": "uuid",
  "timestamp": "2026-04-07T12:45:00.000000",
  "source": "environment",
  "kind": "ConversationErrorEvent",
  "code": "ERROR_TYPE",
  "detail": "Detailed error message"
}
```

---

## Pagination

All search endpoints support cursor-based pagination:

1. First request: No `page_id` parameter
2. Check response for `next_page_id`
3. If not null, use as `page_id` in next request
4. Repeat until `next_page_id` is null

```python
def fetch_all_events(conversation_id: str) -> list:
    all_events = []
    page_id = None
    
    while True:
        params = {"limit": 100}
        if page_id:
            params["page_id"] = page_id
        
        response = client.get(
            f"/api/v1/conversation/{conversation_id}/events/search",
            params=params
        )
        data = response.json()
        
        all_events.extend(data["items"])
        page_id = data.get("next_page_id")
        
        if not page_id:
            break
    
    return all_events
```

---

## Error Responses

### 401 Unauthorized

```json
{
  "detail": "Invalid or missing API key"
}
```

### 404 Not Found

```json
{
  "detail": "Conversation not found"
}
```

### 422 Validation Error

```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "ensure this value is less than or equal to 100",
      "type": "value_error.number.not_le"
    }
  ]
}
```

---

## Rate Limiting

The API may rate limit requests. Handle `429 Too Many Requests` responses by implementing exponential backoff.

**Recommended Retry Strategy:**

```python
import time
import httpx

def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Make request with exponential backoff on rate limiting."""
    max_retries = 5
    base_delay = 1.0  # seconds
    
    for attempt in range(max_retries):
        response = client.request(method, url, **kwargs)
        
        if response.status_code == 429:
            # Check for Retry-After header
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                delay = float(retry_after)
            else:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
            
            time.sleep(delay)
            continue
        
        return response
    
    raise Exception(f"Max retries exceeded for {url}")
```

---

## Sync Command API Usage

The `ohtv sync` command uses these endpoints in this order:

### 1. Check for Updates (Single Call)

```bash
# Get conversations updated since last sync
GET /api/v1/app-conversations/search?updated_at__gte={last_sync_timestamp}&limit=100
```

Returns only conversations that have changed, minimizing data transfer.

### 2. Download Changed Trajectories

For each conversation in the response:

```bash
GET /api/v1/app-conversations/{conversation_id}/download
```

### 3. (Optional) Get Total Count for Status

```bash
GET /api/v1/app-conversations/count
```

### Efficiency Analysis

| Scenario | API Calls |
|----------|-----------|
| No changes since last sync | 1 |
| 5 conversations updated | 6 (1 search + 5 downloads) |
| First sync (500 conversations) | ~6 (paginated search) + 500 downloads |

**Key optimization:** The `updated_at__gte` filter ensures we only query for changed conversations, making hourly syncs very efficient (typically 1 API call if nothing changed).

---

## Related Documentation

- [OpenHands Cloud](https://app.all-hands.dev)
- [OpenHands Documentation](https://docs.openhands.dev)
- [Trajectory Format Comparison](./REFERENCE_TRAJECTORY_FORMAT_COMPARISON.md)
