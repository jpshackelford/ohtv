# Trajectory Format Comparison: Local CLI vs Cloud

This document compares the conversation trajectory formats used by the OpenHands CLI (local storage) and OpenHands Cloud (API/download).

## Executive Summary

**The formats are nearly identical.** Both use the same JSON event structure with the same fields and event types. The main differences are:

1. **File naming convention** (trivial to convert)
2. **Directory structure** (local has nested dirs, cloud is flat)
3. **Metadata file** (different schema but similar purpose)

This high compatibility enables easy interoperability and format conversion.

---

## Directory Structure

### Local CLI Format

```
~/.openhands/conversations/
└── {conversation_id}/
    ├── base_state.json          # Agent configuration and metadata
    ├── events/
    │   ├── event-00000-{uuid}.json
    │   ├── event-00001-{uuid}.json
    │   ├── event-00002-{uuid}.json
    │   └── ...
    └── observations/            # Truncated tool outputs (optional)
        └── {uuid}.txt
```

### Cloud Download Format (ZIP)

```
trajectory.zip
├── meta.json                    # Conversation metadata
├── event_000000_{uuid}.json
├── event_000001_{uuid}.json
├── event_000002_{uuid}.json
└── ...
```

### Downloaded Cloud Conversations (Recommended Location)

To avoid confusion with CLI-managed conversations, downloaded cloud trajectories should be stored in a separate directory:

```
~/.openhands/
├── conversations/              # Local CLI conversations (managed by openhands CLI)
└── cloud/
    ├── api_key.txt            # Cloud API key
    └── conversations/          # Downloaded cloud conversations (managed by ohtv)
        └── {conversation_id}/
            ├── base_state.json
            └── events/
                └── ...
```

This separation ensures:
- The OpenHands CLI doesn't see/manage downloaded conversations
- Clear distinction between locally-generated and cloud-sourced data
- Cloud-related files are grouped together

---

## File Naming

| Aspect | Local CLI | Cloud Download |
|--------|-----------|----------------|
| **Pattern** | `event-NNNNN-{uuid}.json` | `event_NNNNNN_{uuid}.json` |
| **Separator** | Dash (`-`) | Underscore (`_`) |
| **Sequence digits** | 5 | 6 |
| **Example** | `event-00042-abc123.json` | `event_000042_abc123.json` |

### Conversion

```python
import re

def cloud_to_local_filename(cloud_name: str) -> str:
    """Convert cloud filename to local format."""
    # event_000042_abc123.json -> event-00042-abc123.json
    match = re.match(r'event_(\d{6})_(.+)\.json', cloud_name)
    if match:
        seq = int(match.group(1))
        uuid = match.group(2)
        return f"event-{seq:05d}-{uuid}.json"
    return cloud_name

def local_to_cloud_filename(local_name: str) -> str:
    """Convert local filename to cloud format."""
    # event-00042-abc123.json -> event_000042_abc123.json
    match = re.match(r'event-(\d{5})-(.+)\.json', local_name)
    if match:
        seq = int(match.group(1))
        uuid = match.group(2)
        return f"event_{seq:06d}_{uuid}.json"
    return local_name
```

---

## Metadata Files

### Local: `base_state.json`

Contains full agent configuration:

```json
{
  "id": "005fc289-a6fc-4c7a-9409-d83153399c67",
  "agent": {
    "llm": {
      "model": "litellm_proxy/prod/claude-opus-4-5-20251101",
      "api_key": "**********",
      "base_url": "https://llm-proxy.app.all-hands.dev/",
      "temperature": 0.0,
      "max_input_tokens": 200000,
      "max_output_tokens": 64000,
      "native_tool_calling": true,
      "caching_prompt": true
      // ... more LLM config
    },
    "tools": [
      {"name": "terminal", "params": {}},
      {"name": "file_editor", "params": {}},
      {"name": "task_tracker", "params": {}}
      // ... more tools
    ]
  }
}
```

### Cloud: `meta.json`

Contains conversation metadata:

```json
{
  "id": "3f0346d2bcd34f06b220829a96fff1c2",
  "created_by_user_id": "adf1e6c0-51df-45bc-adc1-cb10386ef9f3",
  "sandbox_id": "7NeNnOPV9oyRPweN8xoq0h",
  "selected_repository": "owner/repo",
  "selected_branch": "main",
  "git_provider": "github",
  "title": "Conversation title",
  "trigger": "user_message",
  "pr_number": [],
  "llm_model": "litellm_proxy/prod/claude-opus-4-5-20251101",
  "metrics": {
    "model_name": "default",
    "accumulated_cost": 0.0,
    "accumulated_token_usage": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "cache_read_tokens": 0,
      "reasoning_tokens": 0
    }
  },
  "parent_conversation_id": null,
  "sub_conversation_ids": [],
  "public": null,
  "tags": {},
  "created_at": "2026-04-07T12:39:19.008368Z",
  "updated_at": "2026-04-07T12:39:19.008370Z"
}
```

### Conversion: Cloud → Local

```python
def meta_to_base_state(meta: dict) -> dict:
    """Convert cloud meta.json to local base_state.json format."""
    return {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "selected_repository": meta.get("selected_repository"),
        "selected_branch": meta.get("selected_branch"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "agent": {
            "llm": {
                "model": meta.get("llm_model", "unknown")
            },
            "tools": []  # Not available from cloud metadata
        }
    }
```

---

## Event JSON Structure

**Both formats use identical event structure.** The `kind` field determines the event type.

### Common Fields (All Events)

```json
{
  "id": "uuid-string",
  "timestamp": "2026-04-07T12:40:20.483411",
  "source": "user|agent|environment",
  "kind": "MessageEvent|ActionEvent|ObservationEvent|..."
}
```

### MessageEvent

User or agent text message.

```json
{
  "id": "da96f16f-8302-481e-8137-c14f5ee2da6a",
  "timestamp": "2026-02-24T16:49:46.899399",
  "source": "user",
  "kind": "MessageEvent",
  "llm_message": {
    "role": "user",
    "content": [
      {
        "type": "text",
        "text": "User's message content here...",
        "cache_prompt": false
      }
    ],
    "thinking_blocks": []
  },
  "activated_skills": ["github", "security"],
  "extended_content": [
    {
      "type": "text",
      "text": "<EXTRA_INFO>Skill content...</EXTRA_INFO>"
    }
  ]
}
```

**Differences:**
- Cloud adds `sender` and `critic_result` fields (usually null)

### ActionEvent

Agent tool call.

```json
{
  "id": "c88a5c69-b3b7-4d2b-9113-63b74fab47c6",
  "timestamp": "2026-02-24T16:50:11.040707",
  "source": "agent",
  "kind": "ActionEvent",
  "thought": [
    {
      "type": "text",
      "text": "Agent's thought before action..."
    }
  ],
  "thinking_blocks": [
    {
      "type": "thinking",
      "thinking": "Extended reasoning content...",
      "signature": "base64_signature"
    }
  ],
  "reasoning_content": "Reasoning summary...",
  "action": {
    "command": "view",
    "path": "/Users/user/.openhands",
    "kind": "FileEditorAction"
  },
  "tool_name": "file_editor",
  "tool_call_id": "toolu_015ZoJUAbGa3vGMVQBLSnqSt",
  "tool_call": {
    "id": "toolu_015ZoJUAbGa3vGMVQBLSnqSt",
    "name": "file_editor",
    "arguments": "{\"command\": \"view\", \"path\": \"/Users/user/.openhands\"}",
    "origin": "completion"
  },
  "llm_response_id": "chatcmpl-xxx",
  "security_risk": "LOW",
  "summary": "View .openhands directory"
}
```

**Action Types:**
- `TerminalAction` - Shell command
- `FileEditorAction` - File operations
- `MCPToolAction` - MCP tool call
- `FinishAction` - Task completion
- `ThinkAction` - Agent thinking

### ObservationEvent

Tool execution result.

```json
{
  "id": "observation-uuid",
  "timestamp": "2026-02-24T16:50:12.123456",
  "source": "environment",
  "kind": "ObservationEvent",
  "tool_name": "terminal",
  "tool_call_id": "toolu_015ZoJUAbGa3vGMVQBLSnqSt",
  "action_id": "c88a5c69-b3b7-4d2b-9113-63b74fab47c6",
  "observation": {
    "content": [
      {
        "type": "text",
        "text": "Command output here..."
      }
    ],
    "exit_code": 0,
    "kind": "TerminalObservation"
  }
}
```

**Observation Types:**
- `TerminalObservation` - Command output
- `FileEditorObservation` - File operation result
- `MCPToolObservation` - MCP tool result

### SystemPromptEvent

First event in local conversations (event-00000).

```json
{
  "id": "79ebcdfa-2181-41b8-9171-b048874403ad",
  "timestamp": "2026-02-24T16:49:46.885906",
  "source": "agent",
  "kind": "SystemPromptEvent",
  "system_prompt": {
    "type": "text",
    "text": "You are OpenHands agent, a helpful AI assistant..."
  },
  "tools": [
    {
      "description": "Execute a bash command...",
      "action_type": "TerminalAction",
      "kind": "TerminalTool",
      "title": "terminal"
    }
  ]
}
```

**Note:** In local format, this is often the first event. In cloud format, it may be a separate `SystemPromptEvent` kind.

---

## Observations Directory (Local Only)

Local format stores truncated tool outputs in a separate directory:

```
observations/
└── {uuid}.txt
```

When tool output exceeds a threshold, it's truncated in the event JSON and the full content is stored in this directory.

**Cloud format** includes full observations inline (no separate directory).

---

## Event Kind Mapping

| Kind | Source | Description |
|------|--------|-------------|
| `MessageEvent` | user/agent | Text message |
| `ActionEvent` | agent | Tool call |
| `ObservationEvent` | environment | Tool result |
| `SystemPromptEvent` | agent | System prompt + tools |
| `ConversationStateUpdateEvent` | environment | State change |
| `ConversationErrorEvent` | environment | Conversation error |
| `AgentErrorEvent` | agent | Agent-level error |
| `TokenEvent` | agent | Token usage |
| `PauseEvent` | user | User pause |
| `CondensationSummaryEvent` | agent | Context condensation |
| `HookExecutionEvent` | environment | Hook execution |

---

## Complete Conversion Example

### Cloud → Local

```python
import json
import re
import zipfile
from pathlib import Path

def convert_cloud_to_local(zip_path: Path, output_dir: Path) -> None:
    """Convert cloud trajectory zip to local CLI format."""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    events_dir = output_dir / "events"
    events_dir.mkdir(exist_ok=True)
    
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            content = zf.read(name)
            
            if name == "meta.json":
                # Convert metadata
                meta = json.loads(content)
                base_state = {
                    "id": meta.get("id"),
                    "title": meta.get("title"),
                    "selected_repository": meta.get("selected_repository"),
                    "selected_branch": meta.get("selected_branch"),
                    "created_at": meta.get("created_at"),
                    "updated_at": meta.get("updated_at"),
                    "agent": {
                        "llm": {"model": meta.get("llm_model", "unknown")},
                        "tools": []
                    }
                }
                (output_dir / "base_state.json").write_text(
                    json.dumps(base_state, indent=2)
                )
                
            elif name.startswith("event_"):
                # Convert event filename
                match = re.match(r'event_(\d{6})_(.+)\.json', name)
                if match:
                    seq = int(match.group(1))
                    uuid = match.group(2)
                    new_name = f"event-{seq:05d}-{uuid}.json"
                    (events_dir / new_name).write_bytes(content)

# Usage - store in cloud/conversations/ to avoid CLI confusion
convert_cloud_to_local(
    Path("/tmp/trajectory.zip"),
    Path("~/.openhands/cloud/conversations/abc123").expanduser()
)
```

### Local → Cloud (for upload/sharing)

```python
import json
import re
import zipfile
from pathlib import Path

def convert_local_to_cloud(conv_dir: Path, zip_path: Path) -> None:
    """Convert local CLI format to cloud trajectory zip."""
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Convert base_state.json to meta.json
        base_state_path = conv_dir / "base_state.json"
        if base_state_path.exists():
            base_state = json.loads(base_state_path.read_text())
            meta = {
                "id": base_state.get("id"),
                "title": base_state.get("title"),
                "selected_repository": base_state.get("selected_repository"),
                "selected_branch": base_state.get("selected_branch"),
                "llm_model": base_state.get("agent", {}).get("llm", {}).get("model"),
                "created_at": base_state.get("created_at"),
                "updated_at": base_state.get("updated_at")
            }
            zf.writestr("meta.json", json.dumps(meta, indent=2))
        
        # Convert event files
        events_dir = conv_dir / "events"
        for event_file in sorted(events_dir.glob("event-*.json")):
            match = re.match(r'event-(\d{5})-(.+)\.json', event_file.name)
            if match:
                seq = int(match.group(1))
                uuid = match.group(2)
                new_name = f"event_{seq:06d}_{uuid}.json"
                zf.writestr(new_name, event_file.read_bytes())

# Usage
convert_local_to_cloud(
    Path("~/.openhands/conversations/abc123").expanduser(),
    Path("/tmp/trajectory.zip")
)
```

---

## Compatibility Matrix

| Feature | Local → Cloud | Cloud → Local |
|---------|---------------|---------------|
| Event content | ✅ Full | ✅ Full |
| Event metadata | ✅ Full | ✅ Full |
| Conversation ID | ✅ | ✅ |
| Title | ✅ | ✅ |
| Repository info | ✅ | ✅ |
| LLM model | ✅ | ✅ |
| Full agent config | ❌ Not in cloud | N/A |
| Tool definitions | ❌ Not in cloud | N/A |
| Token metrics | ❌ Not in local | ✅ |
| Sandbox ID | ❌ Not in local | ✅ |

---

## Related Documentation

- [Cloud API Reference](./REFERENCE_CLOUD_API.md)
- [Design Document](./DESIGN.md)
