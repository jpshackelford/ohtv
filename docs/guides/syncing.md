# Syncing Cloud Conversations: `ohtv sync`

Mirror cloud conversations to local disk for offline indexing, analysis, and search. Requires `OPENHANDS_API_KEY` (or `OH_API_KEY`).

> **Behavior change (PR #133 / Issue #111): set-diff sync engine.**
> `ohtv sync` no longer uses a time-cursor (`last_sync_at`) to decide
> what to download. Every run now enumerates the **full** cloud listing
> and reconciles it against the local store via a set-diff. The first
> sync after upgrading from a pre-#111 build will close any historical
> gap between cloud and local — if your account has accumulated drift
> (conversations on cloud that never landed locally), expect a one-time
> catch-up download on the first run. Subsequent runs against a
> fully-synced cloud do zero downloads. There are no new flags and no
> new env vars; the change is purely in the engine.

## `ohtv sync` - Sync Cloud Conversations

Downloads conversations from OpenHands Cloud. Requires `OPENHANDS_API_KEY` or `OH_API_KEY` environment variable.

```bash
# Sync (full set-diff against the cloud; downloads only what's missing or stale)
ohtv sync

# Sync and run all processing stages (recommended)
ohtv sync --process

# Force re-download everything
ohtv sync --force

# Only act on conversations updated after a date (filters the work list,
# not the cloud listing — see "How --since works" below)
ohtv sync --since 2024-01-01

# Preview what would sync
ohtv sync --dry-run

# Check sync status
ohtv sync --status

# Check and repair sync state consistency
ohtv sync --repair --dry-run  # Check only
ohtv sync --repair            # Fix inconsistencies

# Refresh cached cloud metadata (title, labels, selected_repository,
# created_at) for already-synced conversations — picks up cloud-side
# renames, tag edits, or repo reassignments without re-downloading.
ohtv sync --update-metadata
ohtv sync --update-metadata --dry-run  # Preview diffs without writing

# Quiet mode (for cron jobs)
ohtv sync --quiet
```

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Re-download all conversations |
| `--since DATE` | Filter the work list to conversations updated after `DATE` (the cloud listing is always full; see below) |
| `-n, --max-new` | Maximum number of NEW conversations to sync (no limit on updates) |
| `--dry-run` | Show what would sync without downloading |
| `-s, --status` | Show sync status |
| `--repair` | Check and fix sync state (manifest vs disk vs cloud) |
| `--update-metadata` | Refresh cached cloud metadata (`title`, `labels`, `selected_repository`, `created_at`) for already-synced cloud conversations **without** re-downloading. Mutually exclusive with `--force`, `--since`, `--max-new`, `--repair`, `--status`. |
| `-p, --process` | Run all processing stages after sync |
| `-q, --quiet` | Minimal output for cron jobs |

## How the set-diff engine works

Every `ohtv sync` runs two phases:

1. **Listing pass.** Paginate the entire cloud listing into the local
   `cloud_listing` snapshot table under a fresh `snapshot_id`. Pages
   commit incrementally — if the run is interrupted (Ctrl+C, SIGTERM,
   network hiccup), the next `ohtv sync` resumes from the last
   committed page without re-fetching it. On success the snapshot is
   atomically swapped; on failure the in-flight snapshot is abandoned
   and the previous one stays usable.
2. **Set-diff dispatch.** Compare the snapshot against local
   `conversations` and dispatch:
   - `missing_locally` → **download** (this is where automatic gap
     recovery happens; no `--since` workaround needed)
   - `stale_locally` (`cloud_listing.updated_at != local
     cloud_updated_at`) → **refetch** (uses `!=`, not `>`, so a
     backdated `updated_at` on the cloud is still honored)
   - `removed_from_cloud` → **no-op** (detected but not acted on; the
     `--repair` UX from a future iteration will own pruning)
   - present + in-sync → **no-op**

Downloads commit incrementally per item. A re-run against a fully
synced cloud produces zero downloads.

### Scalability boundary

Phase 1 always paginates the full cloud listing — the architectural
inversion that makes gap recovery automatic costs an unconditional
listing round-trip. Phase 2 then streams `SELECT * FROM cloud_listing`
row-by-row through the set-diff cursor, so memory tracks one row at a
time (not the whole result set). The in-memory accumulators (work
list, "seen in cloud" set, manifest-key normalization map) scale
linearly with the catalog size and are well under 10 MB at 10k
conversations. Chunked queries would be the next mitigation if a real
catalog ever grew an order of magnitude beyond that — deferred to a
follow-up issue rather than baked in pre-emptively.

### Removed-from-cloud reconciliation

When the listing pass observes that a conversation present in the
local manifest no longer appears in the cloud listing, the engine
removes the manifest entry so the work list stays coherent and emits
a `WARNING`-level log line (`Removed N conversation(s) from manifest
(no longer visible in cloud listing).`). The full user-facing report
+ prune action is tracked under a follow-up issue (#113); the warning
is the interim signal so accidental cloud-side data loss or permission
changes do not silently shrink the manifest.

### Automatic gap recovery

The old cursor-based sync (`updated_since >= last_sync_at`) could
silently miss conversations that existed before the cursor but were
never present locally — for example after a one-time `--since`
invocation or a `reset_to_n_newest` run. Once that gap opened it stayed
open. The set-diff engine closes it on the next normal `ohtv sync`. The
historical workaround (`ohtv sync --since <very-old-date>`) is no
longer needed for this case.

### How `--since` works (post-#111)

`--since` filters the **work list**, not the cloud listing. The
listing is always full — that's the whole architectural inversion that
makes gap recovery automatic. Use `--since` when you want a normal,
already-converged store and just want to confine this run's downloads
to the last day / week / month of activity. It does NOT make the sync
"faster by skipping the listing" — the listing pass always runs in
full.

### Fresh-install behavior

`ohtv sync` runs `ensure_db_ready()` on entry, so on a fresh install
you can call `ohtv sync` directly without a prior `ohtv db scan`. The
schema (including the `cloud_listing` snapshot table from migration
018) and any one-time maintenance tasks land lazily inside the sync.

### Interruption safety

Both the listing pass and the download pipeline commit incrementally.
A `Ctrl+C` or `SIGTERM` mid-sync drains in-flight work and exits; the
next `ohtv sync` continues from the last committed snapshot page +
last committed download, with no manual recovery step.

### Status field: `last_sync_at`

`last_sync_at` (visible via `ohtv sync --status` and the manifest) is
now **informational only**. It records the timestamp of the last
successful reconciliation but is never compared against by the sync
engine. The cursor-based filter that used it as a gate is gone.

## Metadata refresh (`--update-metadata`)

Cloud-side edits to a conversation's title, labels, or `selected_repository`
(via the `PATCH /app-conversations/{id}` API or the cloud UI) are not picked
up by the normal sync because the API may not bump `updated_at`
on a metadata-only change. Run `ohtv sync --update-metadata` to refresh
the cached cloud-derived metadata fields for every already-synced
conversation without re-downloading any trajectories.

Behavior:
- Lists all cloud conversations (unfiltered by `updated_at`) and diffs
  each manifest entry's `title`, `labels`, `selected_repository`, and
  `created_at` against the cloud listing.
- Rewrites only those four fields in the manifest and the matching DB row
  where they differ; `updated_at`, `event_count`, `downloaded_at`, and
  `selected_branch` are preserved byte-for-byte.
- **`selected_branch` is cached in the manifest** by the normal sync
  path (read from the freshly-extracted `base_state.json`, which the
  exporter mirrors from the trajectory ZIP's `meta.json`), but it is
  **not refreshed by `--update-metadata`** — the cloud listing endpoint
  does not return it, so it can only change via a full trajectory
  re-download (e.g. `ohtv sync --force`).
- Never downloads trajectory ZIPs — the cost is one paged listing call.
- Does **not** advance `last_sync_at` or increment `sync_count`; this is
  an out-of-band metadata-only pass.
- Reports conversations that exist on the cloud but not locally
  (`new_on_cloud`, hint: run `ohtv sync`) and conversations in the
  manifest but absent from the cloud listing (`missing_on_cloud`, hint:
  run `ohtv sync --repair`). Neither is acted on automatically.
- A normal `ohtv sync` auto-runs this refresh **only when** at least one
  new or updated conversation was actually downloaded. It never fires
  on `--dry-run`, `--force`, `--repair`, or `--status`.

Output rows: the summary always shows `Title changed`, `Labels changed`,
`Both changed`, and `Unchanged`. The newer `Repository changed` and
`Created_at changed` rows are shown **only when their count is nonzero**,
keeping the steady-state output compact for the common case where only
title/labels drift.

---
