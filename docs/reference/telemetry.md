# Telemetry — `ohtv ask` session capture

> **Status:** Schema version **1**, introduced by Issue #162.
> **Scope:** Local-only. Telemetry never leaves the machine — ohtv has
> no remote storage path. No PII redaction is performed because nothing
> is uploaded.

Every `ohtv ask` invocation writes a self-contained JSON blob under
`~/.ohtv/telemetry/sessions/` plus one summary line in
`~/.ohtv/telemetry/sessions.jsonl`. The schema is designed so a future
replay tool can re-run the same question against today's corpus
(full replay), re-run only the agent loop against a captured RAG result
(agent-loop replay), or flip the agent mode and rerun to compare
`--agent` vs `--agent-tools` head-to-head (cross-mode replay).

## On-disk layout

```
~/.ohtv/telemetry/
  sessions.jsonl                              # append-only index
  sessions/
    2026-06-04T16-23-15Z_a1b2c3d4.json        # full session blob
    2026-06-04T16-31-08Z_b2c3d4e5.json
    ...
```

Filename grammar: `{ISO8601-Z-with-hyphens}_{8-hex-uuid-prefix}.json`.
The hyphens replace the conventional colons because `:` is reserved on
Windows and some cloud sync clients (Dropbox, OneDrive) misbehave with
it. The 8-char prefix is the leading 8 hex characters of the
session's `uuid4().hex`; the **full** 32-char UUID lives inside the
file as `session_id`. Filenames are stable references; the index uses
the full UUID.

The directory is created lazily on the first successful write. Readers
must tolerate its absence.

## Configuration

| Env var                    | Default                     | Meaning                                              |
| -------------------------- | --------------------------- | ---------------------------------------------------- |
| `OHTV_TELEMETRY_ENABLED`   | `1`                         | Set to `0` to disable capture entirely.              |
| `OHTV_TELEMETRY_DIR`       | `$OHTV_DIR/telemetry/`      | Override the storage root (e.g. for tests / NAS).    |

`OHTV_TELEMETRY_ENABLED=0` short-circuits recorder creation in the
`ask` handler — no `sessions/` files are written and no `sessions.jsonl`
line is appended.

## Concurrency

- **Index** (`sessions.jsonl`): single `open(path, "a") + write()` of
  one line. Lines are ~200 bytes, well under POSIX's `PIPE_BUF`
  (4096 bytes), so concurrent writers from two processes interleave at
  line boundaries only. **No file locking.** Verified by a
  `multiprocessing.Process(2)` regression test.
- **Blobs** (`sessions/<file>.json`): each session writes to a
  `tempfile.NamedTemporaryFile` in the same directory, then
  `os.replace()`-renames into place. This is POSIX-atomic and also
  correct on Windows. A `^C` mid-write leaves a `.tmp` file behind but
  never a half-written `.json`.

## Graceful degradation

Telemetry writes are best-effort. A failure inside `recorder.finalize()`
logs a warning to `~/.ohtv/logs/ohtv.log` but **never** causes
`ohtv ask` to fail — the user has already received their answer by the
time finalization runs. The CLI handler catches all exceptions out of
`finalize()`; the recorder itself swallows in-memory accumulation
failures (`record_rag` / `record_agent`) with the same policy.

## Schema v1

```json
{
  "schema_version": 1,
  "session_id": "a1b2c3d4e5f6...32-hex...",
  "started_at": "2026-06-04T16:23:15Z",
  "ended_at":   "2026-06-04T16:23:42Z",

  "invocation": {
    "command": "ohtv ask",
    "question": "what changes were made to fix the auth bug?",
    "flags": {
      "context": 5,
      "min_score": 0.3,
      "model": null,
      "agent_mode": "cli",            // "cli" | "tools" | null
      "max_steps": 5,
      "since": null,
      "until": null,
      "no_temporal": false,
      "explain": false,
      "explain_only": false,
      "show_context": false
    }
  },

  "environment": {
    "ohtv_version": "0.27.0",
    "ohtv_git_sha": "abc1234",         // null if not in a checkout
    "python": "3.13.13",
    "platform": "linux-x86_64",
    "hostname": "...",
    "embedding_model": "openai/text-embedding-3-small",
    "embedding_dim": 1536,
    "db_schema_version": 23,            // count of applied migrations
    "corpus": {
      "total_conversations": 487,
      "total_embeddings": 12453,
      "newest_conversation_at": "2026-06-04T13:00:00Z"
    }
  },

  "rag": {
    "elapsed_seconds": 0.23,
    "search_seconds": 0.12,
    "generation_seconds": 0.11,
    "temporal_filter_applied": true,
    "date_range": ["2026-05-28T00:00:00Z", "2026-06-04T00:00:00Z"],
    "retrieved_chunks": [
      {
        "conversation_id": "abc12345...",
        "root_conversation_id": "abc12345...",
        "chunk_type": "summary",
        "score": 0.72,
        "chunk_text": "...",             // capped at 2 KB per chunk
        "chunk_text_size_bytes": 1843,
        "chunk_text_truncated": false
      }
    ],
    "initial_answer": "...",
    "source_conversation_ids": ["abc12345", "def67890"],
    "model": "openai/gpt-4o-mini",
    "tokens": { "prompt": 1234, "completion": 456 },
    "cost": 0.0023
  },

  "agent": {                              // null when no agent ran
    "mode": "cli",                        // "cli" | "tools"
    "iterations": 3,
    "finished_normally": true,
    "error": null,
    "elapsed_seconds": 14.2,
    "model": "openai/gpt-4o-mini",
    "total_cost": 0.0097,
    "total_tokens": 6543,
    "conversations_examined": ["abc12345", "def67890"],
    "final_answer": "...",
    "steps": [
      {
        "iteration": 1,
        "kind": "tool_call",              // or "think" / "finish"
        "tool_name": "run_ohtv",          // cli mode; "show_conversation" etc. in tools mode
        "arguments": { "argv": ["show", "abc12345", "-F", "json"] },
        "observation_truncated_text": "...first 8 KB...",
        "observation_size_bytes": 8432,
        "observation_truncated": true,
        "elapsed_seconds": 0.02,
        "tokens": { "prompt": 1234, "completion": 56 },  // deltas, not cumulative
        "cost": 0.0001                    // delta, not cumulative
      }
    ]
  },

  "totals": {
    "tokens": { "prompt": 5432, "completion": 1234 },
    "cost": 0.012,
    "wall_seconds": 27.4
  }
}
```

### Schema lock-ins

- **`agent: null` (not key omission).** Plain `ohtv ask` invocations
  (neither `--agent` nor `--agent-tools`) land with the top-level
  `agent` key set to `null`. `session["agent"] is None` reads cleaner
  than `"agent" in session`, and a stable key set helps JSON consumers.
- **`flags.agent_mode` mirrors `InvestigationResult.mode`** (#161). The
  enum is `"cli" | "tools" | null` — `"cli"` for `--agent` (prompt-cookbook
  mode), `"tools"` for `--agent-tools` (legacy custom-tools mode),
  `null` for plain RAG.
- **`steps[].arguments` is captured verbatim.** For cli mode that's
  `{"argv": [...]}`; for tools mode it's whatever the tool's input
  schema produced (`{"conversation_id": "..."}`, etc.). Same field,
  different shape — that's the cross-mode comparison surface.
- **Per-step `cost` and `tokens` are deltas.** The SDK exposes
  `response.metrics.accumulated_cost` (cumulative across the loop);
  the recorder subtracts a baseline so each step's record reads
  naturally. Summed deltas reconcile to `agent.total_cost`.
- **`db_schema_version` is the count of applied migrations.** That's
  the natural integer proxy for "what does this DB know about" — a
  bump means a migration landed between capture and replay.

### Truncation

Three fields are capped to keep blobs tractable; each carries paired
flags so readers can detect what was dropped:

| Field                                      | Cap      | Flag                                      |
| ------------------------------------------ | -------- | ----------------------------------------- |
| `rag.retrieved_chunks[].chunk_text`        | 2 KB     | `chunk_text_truncated` + `_size_bytes`    |
| `agent.steps[].observation_truncated_text` | 8 KB     | `observation_truncated` + `_size_bytes`   |
| `agent.final_answer`, `rag.initial_answer` | no cap   | (typically small — full LLM output)       |

### Replay-readiness contract

The schema is intentionally additive: future minor versions add fields
without removing or renaming existing ones. A future replay tool can
gate on `schema_version`. Three replay scenarios are supported:

1. **Full replay.** Read `invocation.question` + `invocation.flags`
   and re-run `ohtv ask` end-to-end against the current corpus. The
   `environment.corpus` block tells the replayer whether the corpus
   has drifted since capture.
2. **Agent-loop replay.** Feed the recorded
   `rag.retrieved_chunks` + `rag.initial_answer` to a fresh agent run
   without paying for embedding retrieval again. Useful for prompt
   iteration.
3. **Cross-mode replay.** Take a session recorded under
   `agent_mode="tools"`, flip to `agent_mode="cli"` (or vice versa),
   rerun. The rest of the invocation envelope is identical.

A 20-line `jq` pipeline is the v1 UI:

```bash
# Sessions today, sorted by cost
jq -r 'select(.started_at | startswith("2026-06-04")) |
       [.started_at, .agent_mode, .total_cost, .question]
       | @tsv' \
    ~/.ohtv/telemetry/sessions.jsonl | sort -k3 -rg
```

## Index-line shape

Each line of `sessions.jsonl` is a JSON object with this minimal
fingerprint:

```json
{
  "session_id":        "<32-char hex>",
  "started_at":        "2026-06-04T16:23:15Z",
  "ended_at":          "2026-06-04T16:23:42Z",
  "question":          "...",
  "agent_mode":        "cli",     // or "tools" / null
  "model":             "openai/gpt-4o-mini",
  "total_cost":        0.012,
  "total_tokens":      6666,
  "iterations":        3,
  "finished_normally": true,
  "blob":              "2026-06-04T16-23-15Z_a1b2c3d4.json"
}
```

The `blob` field is the filename of the full session JSON inside
`sessions/`; use it to do `cat
~/.ohtv/telemetry/sessions/$(jq -r '.blob' ...)`.

## Retention

No automatic deletion in v1. Sessions are 50–200 KB each; 1,000
sessions ≈ 100–200 MB on disk. The user controls `~/.ohtv/`. A
follow-up issue may add `ohtv telemetry prune --older-than 30d`
once disk pressure becomes real.

## See also

- AGENTS.md item #33 — `ohtv ask` dual investigation modes (#161).
- AGENTS.md item #34 — telemetry schema invariant.
- AGENTS.md item #12 — `~/.ohtv/` data-directory separation.
- `docs/guides/search-and-ask.md` §"Investigation Mode" — flag surface.
- Issue #162 — the design proposal and acceptance criteria.
