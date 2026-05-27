# Syncing Cloud Conversations: `ohtv sync`

Mirror cloud conversations to local disk for offline indexing, analysis, and search. Requires `OPENHANDS_API_KEY` (or `OH_API_KEY`).

## `ohtv sync` - Sync Cloud Conversations

Downloads conversations from OpenHands Cloud. Requires `OPENHANDS_API_KEY` or `OH_API_KEY` environment variable.

```bash
# Sync incrementally (only downloads changes)
ohtv sync

# Sync and run all processing stages (recommended)
ohtv sync --process

# Force re-download everything
ohtv sync --force

# Only sync conversations updated after a date
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
| `--since DATE` | Only sync conversations updated after date |
| `--dry-run` | Show what would sync without downloading |
| `-s, --status` | Show sync status |
| `--repair` | Check and fix sync state (manifest vs disk vs cloud) |
| `--update-metadata` | Refresh cached cloud metadata (`title`, `labels`, `selected_repository`, `created_at`) for already-synced cloud conversations **without** re-downloading. Mutually exclusive with `--force`, `--since`, `--max-new`, `--repair`, `--status`. |
| `-p, --process` | Run all processing stages after sync |
| `-q, --quiet` | Minimal output for cron jobs |

## Metadata refresh (`--update-metadata`)

Cloud-side edits to a conversation's title, labels, or `selected_repository`
(via the `PATCH /app-conversations/{id}` API or the cloud UI) are not picked
up by the normal incremental sync because the API may not bump `updated_at`
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

