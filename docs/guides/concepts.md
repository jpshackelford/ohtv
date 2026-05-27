# Concepts

A short tour of the terms and data flows you'll bump into.

## Conversations: cloud vs CLI

ohtv understands two conversation **sources**:

- **Cloud** — created in [app.all-hands.dev](https://app.all-hands.dev/),
  fetched via `ohtv sync`. Stored under `~/.ohtv/conversations/` as the
  cloud event ZIP plus a `meta.json` from the cloud manifest.
- **CLI / local** — created by `openhands-cli` on your machine. ohtv
  auto-discovers these from the standard OpenHands data directory on the
  first `ohtv db scan`.

Both end up in the same SQLite index with `source IN ('cloud', 'local')`.
The `ohtv classify` command lets you inspect or override the heuristic
classification.

## The pipeline

```
                            ┌─────────────────────────┐
                            │  ~/.ohtv/conversations/ │
                            │      (trajectories)     │
                            └──────────┬──────────────┘
       cloud convs                     │
   ─────────────────► ohtv sync ──────►│  ◄──── local convs (auto-discovered)
                                       │
                                       ▼
                            ┌─────────────────────────┐
                            │       ohtv db scan      │  register & detect changes
                            └──────────┬──────────────┘
                                       ▼
                            ┌─────────────────────────┐
                            │     ohtv db process     │  multi-stage indexing:
                            │  (refs, actions,        │  - extract repo/PR refs
                            │   contributions,        │  - classify actions
                            │   human_input, …)       │  - attribute contributions
                            └──────────┬──────────────┘  - count human input
                                       │
                                       ▼
                            ┌─────────────────────────┐
                            │      ohtv fetch-loc     │  network-bound LOC backfill
                            │  (GitHub REST API)      │  for change_refs
                            └──────────┬──────────────┘
                                       ▼
                  ┌────────────────────┴────────────────────┐
                  ▼                                         ▼
        ohtv list / refs / show               ohtv gen / ask / report
        (read-only views)                     (LLM + analytics)
```

`ohtv sync --process` runs sync + scan + process in one go, which is
what you want most of the time.

## Key data model objects

| Object | What it is |
|---|---|
| **Conversation** | One indexed agent run. Identified by a UUID/short-ID. Has a `source` (`cloud`/`local`), title, labels, created/updated timestamps, and pointers to its trajectory file. |
| **Event** | A single trajectory entry — user message, agent action, observation, finish, etc. ohtv never modifies events; it just indexes them. |
| **Action** | An indexed write-or-read operation surfaced by the `actions` stage: file edits, shell commands, git pushes, PR creates/merges, browser opens, etc. |
| **`change_ref`** | A row in `change_refs` representing one PR creation, PR merge, or **direct push** to `main`/`master` attributed to a conversation. Populated by the `contributions` stage, optionally enriched with `lines_added`/`lines_removed` by `fetch-loc`. |
| **Manifest** | `~/.ohtv/manifest.json` — the cloud-sync state cache. Stores per-conversation cloud metadata (title, labels, `selected_repository`, `created_at`, `last_sync_at`) so syncs can stay incremental and cold-start scans don't open `base_state.json` for every cloud conv. |
| **Sandbox** | A cloud-side container running an OpenHands agent. ohtv records sandbox status (`RUNNING`, `PAUSED`, `MISSING`) for sync diagnostics. |

## NULL vs zero

ohtv uses `NULL` to mean "we don't know" and `0` (or `0.0`) to mean "we
verified this value is zero". This shows up in several places:

- **LOC columns**: NULL = `fetch-loc` hasn't populated it; 0 = the PR
  genuinely changed zero lines. Rendered as `-` (table) / empty (CSV) /
  hatched bar (chart) for NULL; as `0` for zero.
- **`words_per_loc`**: NULL on weeks where either denominator is missing.
  The chart's Panel 3 renders these as gaps rather than interpolating
  through.
- **`partial_loc`**: a boolean on velocity-report rows that's `True` if
  *any* contributing row had NULL LOC. Drives the chart hatch convention
  documented in [reporting.md § Reading the chart](reporting.md#reading-the-chart).

## Where to go next

- [installation.md](installation.md) if you haven't installed yet
- [getting-started.md](getting-started.md) for a 5-minute walkthrough
- [reference/database.md](../reference/database.md) for the full schema
- [reference/glossary.md](../reference/glossary.md) for a one-line definition of every term
