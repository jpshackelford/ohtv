# Search & Q&A: `ohtv search`, `ohtv ask`

Semantic search over your conversation corpus, and a RAG-powered question-answerer (with optional multi-step agent mode). Requires `LLM_API_KEY` and pre-built embeddings (see [indexing.md](indexing.md) §`db embed`).

## `ohtv search` - Semantic Search

Searches conversations using embedding-based semantic search or keyword matching. Finds conversations by concept/intent rather than exact matches.

```bash
# Semantic search
ohtv search "fix authentication bugs"
ohtv search "docker deployment" -n 20

# Filter by date
ohtv search "API changes" --since 7d
ohtv search "refactoring" --since 2024-01-01

# Keyword search (exact match, uses FTS5)
ohtv search "error 404" --exact

# Set minimum similarity score
ohtv search "performance optimization" --min-score 0.5

# Output as JSON
ohtv search "testing" --format json
```

**Options:**
| Flag | Description |
|------|-------------|
| `-n, --limit N` | Number of results (default: 10) |
| `--exact` | Use keyword search instead of semantic |
| `-S, --since DATE` | Filter by date (YYYY-MM-DD or relative like `7d`, `2w`) |
| `-s, --min-score N` | Minimum similarity score 0-1 (default: 0) |
| `-F, --format` | Output format: `table`, `json` |
| `-v, --verbose` | Show debug output |

**Note:** Requires embeddings. Run `ohtv db embed` first.

---


## `ohtv ask` - Question Answering (RAG)

Ask questions about your conversations using RAG (Retrieval-Augmented Generation). Finds relevant context from your conversation history and generates a synthesized answer.

```bash
# Ask a question
ohtv ask "how did we fix the authentication bug?"

# Use more context chunks for detailed answers
ohtv ask "what changes were made to the API?" --context 10

# Show the retrieved context chunks
ohtv ask "summarize the docker deployment work" --show-context

# Use a specific model for answer generation
ohtv ask "what PRs did we create?" --model openai/gpt-4

# Lower minimum score to get more context
ohtv ask "testing strategies" --min-score 0.2

# Enable multi-turn investigation mode for deeper analysis
ohtv ask "explain the auth fix in detail" --agent

# Investigation with more steps for complex questions
ohtv ask "what went wrong with the deployment?" --agent --max-steps 10

# Debug retrieval quality (show which conversations match)
ohtv ask "api changes" --explain

# Retrieval debugging only (no LLM answer, no LLM_API_KEY needed)
ohtv ask "api changes" --explain-only

# Combine with date filters
ohtv ask "what did we work on yesterday?" --explain --since 7d
```

**Example Output:**
```
Searching for relevant context...
Generating answer...

Answer:

Based on conversation abc123 from 2 days ago, the authentication bug was
fixed by updating the JWT token validation in `src/auth/jwt.py`. The key
changes were:

1. Added expiration check before signature validation
2. Returning 401 status instead of 500 for expired tokens
3. Added unit tests for edge cases

─────────────────────────────────────────────────
Sources (2 conversations):
  • [abc12345] Fix JWT token validation
  • [def56789] Debug login flow

Search: 0.15s | Generation: 2.34s | Model: openai/gpt-4o-mini
```

**Options:**
| Flag | Description |
|------|-------------|
| `-c, --context N` | Number of context chunks to use (default: 5) |
| `-s, --min-score N` | Minimum similarity score 0-1 (default: 0.3) |
| `-m, --model MODEL` | LLM model for answer generation |
| `--show-context` | Show retrieved context chunks |
| `--explain` | Show retrieval breakdown before answer (see below) |
| `--explain-only` | Show retrieval breakdown only, skip LLM answer (no `LLM_API_KEY` needed) |
| `--agent` | Enable multi-turn investigation mode (see below) |
| `--max-steps N` | Maximum investigation steps with `--agent` (default: 5) |
| `-S, --since DATE` | Filter by date (YYYY-MM-DD or relative like `7d`, `2w`) |
| `-U, --until DATE` | Filter by date (YYYY-MM-DD) |
| `--no-temporal` | Disable automatic temporal extraction from question |
| `-v, --verbose` | Show debug output |

**Note:** Requires embeddings. Run `ohtv db embed` first.

## Retrieval Debugging (`--explain`)

The `--explain` flag shows a per-conversation breakdown of retrieved chunks before the LLM answer, helping diagnose RAG retrieval quality.

```bash
$ ohtv ask "how do embeddings work?" --explain

Query: how do embeddings work?
Retrieved 50 chunks from 19 conversations
📅 Auto-filtered: 2024-04-15 to 2024-04-22

b3af77ff (2024-04-22) "Clarify RAG implementation..."
  analysis    2 chunks   0.723-0.718
  summary     1 chunk    0.695
  content     5 chunks   0.701-0.668

76230e77 (2024-04-21) "Fix embedding functionality..."
  analysis    1 chunk    0.712
  content    22 chunks   0.698-0.667

238de50e (2024-04-21) "Draft GitHub issue for..."
  summary     1 chunk    0.682
  ...

Search time: 0.23s

Generating answer...
[Answer follows]
```

The breakdown shows:
- **Chunks grouped by conversation** - Each conversation displays its ID (truncated), date, and title
- **Embed types** - `analysis` (goal/outcomes), `summary` (user messages/refs), `content` (file contents)
- **Chunk counts** - How many chunks matched from each type
- **Score ranges** - Similarity scores (higher = better match, 0-1 scale)
- **Conversations sorted by best score** - Most relevant conversations first
- **Temporal filter info** - Shows if auto or explicit date filtering was applied

**Use `--explain-only` for retrieval-only debugging:**

```bash
# Skip LLM answer, just see retrieval (no LLM_API_KEY needed)
$ ohtv ask "api changes" --explain-only
```

This is useful for:
- **Diagnosing retrieval quality** - Are the right conversations being found?
- **Tuning chunking parameters** - Is content over-fragmented?
- **Identifying noisy conversations** - Some may flood results with low-quality matches
- **Comparing embedding types** - Which types work best for different query types?

## Investigation Mode (`--agent` / `--agent-tools`)

When an investigation flag is enabled, the answer is enhanced through a multi-turn agent loop. **Issue #161** introduced two modes that run side-by-side so we can compare them with telemetry:

| Flag             | Mode | What it does |
|------------------|------|--------------|
| `--agent`        | `cli`   | **Prompt-cookbook agent (default)**. Exposes a single `run_ohtv(argv)` tool that invokes the local `ohtv` CLI in-process. The cookbook teaches the agent which subcommands to use and when. |
| `--agent-tools`  | `tools` | **Legacy custom-tools agent (#51)**. Four bespoke Python tools (`show_conversation`, `search_conversations`, `get_refs`, `list_conversations`). |
| _(neither flag)_ | —    | Single-turn RAG; no investigation. |

`--agent` and `--agent-tools` are mutually exclusive (Click `UsageError` if both are given). `--max-steps` applies to both modes; `--max-steps 0` short-circuits to single-turn RAG even if a flag is set. A `[dim]Investigation mode: cli|tools[/dim]` banner is printed once per invocation so the active mode is visible.

### `--agent` (prompt-cookbook, #161)

Single tool: `run_ohtv(argv)`. The agent learns the CLI grammar from a [cookbook prompt](#cookbook-prompt) and invokes the local `ohtv` binary in-process — no subprocess fork, no `litellm` re-import per call.

**Allow-list** (anything else is rejected with a structured observation):

| Allowed     | Purpose |
|-------------|---------|
| `show`      | Examine a specific conversation. |
| `refs`      | List git references (PRs, issues, repos) for a conversation. |
| `search`    | Semantic / FTS search across conversations. |
| `list`      | Browse conversations by metadata. |
| `errors`    | Inspect agent/LLM error events. |
| `gen objs`  | **Cache-only**. The runner auto-injects `--cache-only` so the agent can browse cached objectives without paying for fresh LLM analyses. Cache misses yield `goal: null` in JSON output (treat as "no analysis yet", not "no goal"). |

**Blocked** (write-side commands, surfaced in rejection observations so the agent can self-correct):
`sync`, `db scan/process/embed/migrate-cache/reset`, `fetch-loc`, `gen titles`, `gen run`, `classify`, `config`.

**`gen objs --cache-only`** is a power-user-friendly first-class flag in the CLI, not a runner-only convenience: anyone can run `ohtv gen objs --cache-only -F json` to dump cached objectives without firing the LLM.

### `--agent-tools` (legacy custom tools, #51)

Available tools:
- `show_conversation` - Load and examine a specific conversation transcript
- `search_conversations` - Search for related conversations by semantic similarity
- `list_conversations` - Enumerate conversations by metadata (date / repo / PR / action / label)
- `get_refs` - Get git references (repos, PRs, issues) for a conversation

The `list_conversations` tool is the only browse primitive in this mode; the prompt-cookbook mode reaches the same data through `ohtv list -F json` and `ohtv gen objs -F json --cache-only`. The duplication is intentional — once #162 telemetry shows which mode wins on cost/quality, the loser gets retired.

### Browse vs search

Both modes encode the same heuristic: prefer **browse** (`list` / `gen objs`) for temporal or enumerative questions, **search** for conceptual ones. Vector search returns the *most-similar* matches; it cannot reliably enumerate, count, or prove absence.

- **Temporal**: _"what did we work on yesterday?"_, _"every conv from last week"_
- **Enumerative**: _"list all conversations that touched repo X"_, _"every PR we opened"_
- **Aggregative**: _"how many conversations landed merges in May?"_
- **Verifying a negative**: _"did we work on the auth refactor at all?"_

### `list_conversations` — metadata-driven enumeration (legacy `--agent-tools` only)

`list_conversations` complements `search_conversations`. Use it whenever the question is anchored to *what / when* rather than *similar to*:

- **Temporal**: _"what did we work on yesterday?"_, _"every conv from last week"_
- **Enumerative**: _"list all conversations that touched repo X"_, _"every PR we opened"_
- **Aggregative**: _"how many conversations landed merges in May?"_
- **Verifying a negative**: _"did we work on the auth refactor at all?"_

Vector search returns the *most-similar* matches; it cannot reliably enumerate, count, or prove absence. The agent will reach for `list_conversations` for those classes of questions, and for `search_conversations` when the question is about meaning ("how did we…", "explain the…").

**Filter surface** — the same shape as `ohtv gen objs` multi-conversation mode, so anything you can ask the CLI to batch over, the agent can browse:

| Filter | Notes |
|---|---|
| `since` / `until` | Accept the full `parse_date_filter` surface: ISO date (`2026-04-15`), relative (`7d`, `2w`, `1m`), or keywords (`today`, `yesterday`). |
| `day` | A specific day (`YYYY-MM-DD` or `today`) or a small integer for an N-day lookback. |
| `week` | `today` (this week) or a small integer for an N-week lookback. |
| `repo` | Full URL, `owner/repo`, or short name. |
| `pr` | PR URL, `owner/repo#N`, or `repo#N` (precise — `#1` won't match `#10`). |
| `action` | e.g. `pushed`, `open-pr`, `merged`. |
| `label` | Cloud-side labels in `key=value` form. |
| `limit` | Default 20, **hard-capped at `LIST_CONVERSATIONS_MAX_LIMIT = 50`** so the observation stays inside the prompt budget. |
| `include_sub_conversations` | **Default `False`** (roots-only, matching the post-Issue #125 CLI default — agent-delegated sub-conversations are rolled up into their root). Set to `True` to enumerate every sub. |

**Observation shape** — the agent always sees three counts so it knows whether it's looking at the full set:

- `total_matching` — ground-truth count of conversations matching the filters.
- `returned` — the capped list of summaries (≤ `limit`, ≤ 50).
- `truncated` — `True` when `total_matching > len(returned)`.

If you see the agent say _"there are 137 matches and I'm looking at the top 50"_, that's `truncated=True` doing its job. The agent will typically narrow filters (`since=3d`, a specific `repo`, etc.) and re-query rather than ask for a higher `limit`.

**Cache-only reads** — each row carries a `goal` field populated from the **cached `brief` `gen objs` analysis** for that conversation (the same variant `gen objs` multi-conv mode displays). `list_conversations` **never triggers LLM analysis** on a cache miss; instead, `goal=None` is a signal to the agent: _"call `show_conversation` on this id if you want to know what it was about."_ So the practical workflow inside investigation mode is:

1. `list_conversations` to enumerate candidates by metadata.
2. Sort/filter the rows by `goal` previews + `selected_repository` + `labels`.
3. `show_conversation` or `get_refs` on the specific ids worth drilling into.

To pre-warm the cache for a date range so `goal` is populated, run `ohtv gen objs` with matching filters (see [analysis.md](analysis.md)) before asking.

**Example with investigation:**
```bash
$ ohtv ask "what specific changes were made to fix the auth bug?" --agent

Searching for relevant context...
Generating answer...

🔍 Starting investigation mode...
[Agent examines conversation abc123...]
[Agent searches for "JWT token validation"...]

Investigation complete: 3 steps, 2 conversations examined

Answer (after investigation):

The auth bug was fixed in conversation abc123 with these specific changes:

1. In `src/auth/jwt.py` line 45: Added `if token.exp < time.time()` check
2. Changed the exception handler to return 401 instead of re-raising as 500
3. Added tests in `tests/auth/test_jwt.py` covering expired token scenarios

The fix was pushed in PR owner/repo#42.

─────────────────────────────────────────────────
Sources (2 conversations):
  • [abc12345] Fix JWT token validation
  • [def56789] Debug login flow

Search: 0.15s | Generation: 2.34s | Investigation: 8.52s | 🔍 agent
```

Investigation mode is useful for:
- Questions requiring specific code details from conversations
- Understanding the relationship between multiple conversations
- Finding which PRs or repos were involved in a fix

---

