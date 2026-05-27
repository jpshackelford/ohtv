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

## Investigation Mode (`--agent`)

When `--agent` is enabled, the answer is enhanced through multi-turn investigation. An AI agent can use tools to examine specific conversations in detail, search for related context, and retrieve git references (PRs, issues, repos).

**Available tools in investigation mode:**
- `show_conversation` - Load and examine a specific conversation transcript
- `search_conversations` - Search for related conversations by query
- `get_refs` - Get git references (repos, PRs, issues) for a conversation

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

