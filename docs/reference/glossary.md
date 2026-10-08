# Glossary

One-line definitions for ohtv terms.

- **Action** — A row in the `actions` table representing a write (or read)
  operation surfaced from a conversation event: file edits, shell commands,
  git pushes, PR creates/merges, etc. Produced by the `actions` indexing
  stage. See [indexing § Stages](../guides/indexing.md).
- **Aggregate job** — A `gen run` prompt that operates over many
  conversations at once (e.g. weekly summary, theme discovery) rather than
  per-conversation. See [analysis.md](../guides/analysis.md).
- **Attention period** — A merged run of attended time inside one
  conversation, counted in `conversation_engagement.attention_periods`.
  Engaged time is the sum of the periods' lengths. See
  [metrics-and-attention](../guides/metrics-and-attention.md#how-engaged-minutes-work).
- **`change_ref`** — A row attributing one PR creation, PR merge, or direct
  push to a specific conversation. Populated by the `contributions` stage,
  enriched with `lines_added`/`lines_removed`/`merged_at` by `fetch-loc`.
- **CLI / local conversation** — A conversation produced by the
  `openhands-cli` tool on your machine. Stored under
  `~/.openhands/conversations/`. Has `source='local'` in the index (the
  `report weekly-counts` CSV labels it `cli` because that reads more
  naturally).
- **Cloud conversation** — A conversation produced in
  [app.all-hands.dev](https://app.all-hands.dev/). Fetched via `ohtv sync`
  and stored under `~/.openhands/cloud/conversations/`. Has `source='cloud'`
  in the index.
- **`change_refs`** — The SQLite table that stores `change_ref` rows.
  See [reference/database.md](database.md).
- **Conversation** — One indexed OpenHands agent run. Identified by UUID
  (long ID) or its first 7 hex chars (short ID).
- **`conversation_contributions`** — The link table joining conversations
  to `change_refs`, with attribution metadata (who pushed/merged when).
- **`conversation_human_input`** — Per-conversation counts of human-typed
  words and messages, produced by the `human_input` stage. Drives the
  Words/LOC ratio in velocity reports.
- **Direct push** — A commit landing on `main` / `master` via `git push`
  without an associated PR open/merge event. Detected by the
  `contributions` stage as of #79/#94; recorded as a `change_ref` row with
  `kind='push'`. Contributes to LOC accounting just like a merged PR.
- **Engaged time** (`engaged_seconds`) — Estimated time a human was
  actively watching or steering a conversation, inferred from timestamps
  around each follow-up user message. Distinct from human word counts. See
  [metrics-and-attention](../guides/metrics-and-attention.md).
- **Event** — A single trajectory entry in a conversation: user message,
  agent action, observation, finish, etc. ohtv never modifies events.
- **Fetch-LOC** — The `ohtv fetch-loc` command — a network-bound, cached,
  idempotent backfill of `lines_added`/`lines_removed` from the GitHub REST
  API into pending `change_refs` rows.
- **Fire-and-forget** — A conversation with zero or one user message.
  Stored with `engaged_seconds = 0`, not `NULL`.
- **ISO week** — A `YYYY-Www` label (e.g. `2026-W22`) computed in Python
  using `isocalendar()`. Used as the bucketing key for both
  `report velocity` and `report weekly-counts`. SQLite's `%W` is NOT
  ISO-compliant, so all bucketing happens at the Python layer.
- **Label** — A cloud-side tag attached to a conversation in the
  [app.all-hands.dev](https://app.all-hands.dev/) UI. Cached locally via
  `ohtv sync --update-metadata`. Usable as a filter on `list`, `gen`, etc.
- **Manifest** — `~/.ohtv/manifest.json`, the cloud-sync state cache.
  Stores per-conversation cloud metadata (title, labels,
  `selected_repository`, `created_at`, `last_sync_at`) so syncs stay
  incremental and cold-start scans don't need to open `base_state.json`
  for every cloud conv. Extended to full cache by PR #87/#104.
- **`partial_loc`** — A boolean on velocity-report rows that is `True` if
  *any* contributing change_ref had NULL `lines_added`. Drives the `///`
  hatch convention on Panel 2 of the velocity chart — see
  [reporting § Reading the chart](../guides/reporting.md#reading-the-chart).
- **Pipeline stage** — One of the indexing steps run by `ohtv db process`:
  `refs`, `actions`, `contributions`, `human_input`, `objs`, etc. Stages
  declare dependencies; running `all` respects them.
- **Sandbox** — A cloud-side container running an OpenHands agent.
  Has a status (`RUNNING`, `PAUSED`, `MISSING`) reported by the cloud API
  and surfaced in `ohtv sync` diagnostics and in this repo's WORKLOG.md
  zombie-pattern analysis.
- **Short ID** — The first 7 hex chars of a conversation UUID. ohtv accepts
  short IDs anywhere a conversation ID is expected, so long as the prefix
  is unambiguous.
- **Source** — One of `cloud` or `local`. The `ohtv classify` command lets
  you inspect or override the classification when the heuristic is wrong.
- **Stage** — see *Pipeline stage*.
- **`T` / `T_a`** — The two engagement constants: `T` (silence tolerance,
  default 12 min) and `T_a` (sustained-attention window, default 1 h,
  provisional). See
  [indexing § Engagement stage](../guides/indexing.md#engagement-stage).
- **Touch** — A zero-length attention period recorded when the user returns
  after longer than `T_a`. It increments `attention_periods` but adds no
  engaged time.
