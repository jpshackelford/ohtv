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
ohtv sync --repair --dry-run        # Diagnostic only — never writes
ohtv sync --repair                  # Apply non-destructive fixes (download gaps, refetch modified)
ohtv sync --repair --prune          # Also delete locally for items removed from cloud

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
| `--repair` | Check (and with `--fix`, repair) sync state via a four-bucket cloud-vs-local set diff plus the legacy ghost/orphan manifest diff. See [Repair](#repair-ohtv-sync---repair) below for the full bucket definitions, action matrix, and lock semantics. |
| `--prune` | **Only valid with `--repair` (without `--dry-run`).** Authorizes deletion of local conversations that have disappeared from the cloud listing (`removed_from_cloud` bucket). Passing `--prune` outside that combination is a hard error (Click `UsageError`, exit 2). |
| `--update-metadata` | Refresh cached cloud metadata (`title`, `labels`, `selected_repository`, `created_at`) for already-synced cloud conversations **without** re-downloading. Mutually exclusive with `--force`, `--since`, `--max-new`, `--repair`, `--status`. |
| `-p, --process` | Run all processing stages after sync |
| `-q, --quiet` | Minimal output for cron jobs |
| `--lock-timeout SECONDS` | Wait up to N seconds for `$OHTV_DIR/sync.lock` instead of failing fast. Default `0` = fail-fast. See [Writer mutex](#writer-mutex-synclock) below. |

## Writer mutex (`sync.lock`)

`ohtv sync` is a **writer** — it mutates `~/.ohtv/sync_manifest.json` and
the `conversations` / `cloud_listing` / `sync_state` tables. To prevent
two concurrent writers from clobbering each other's committed
transactions, every form of `ohtv sync` (full, `--repair`,
`--update-metadata`, `--force -n`) acquires an exclusive
`fcntl.flock` on `$OHTV_DIR/sync.lock` before doing any work, and shares
that lock with `ohtv db scan` and `ohtv gen titles`.

The default behavior is **fail-fast**: if another writer holds the lock,
`ohtv sync` exits 1 with:

```
Error: Another ohtv writer is already running (see /home/$USER/.ohtv/sync.lock).
Try again in a few seconds, or pass --lock-timeout=N to wait.
```

Pass `--lock-timeout=N` (seconds) to poll for the lock — useful when
chaining commands or scripting around a cron job that might overlap:

```bash
ohtv sync --lock-timeout=30        # wait up to 30s for the lock
ohtv sync --update-metadata --lock-timeout=10
```

`ohtv sync --status` is read-only and does **not** acquire the lock, so
it stays usable while another writer is running.

On Windows the lock is a documented no-op (`fcntl` is POSIX-only); see
the canonical contract in
[reference/database.md § Column Ownership and the `sync.lock` Writer Mutex](../reference/database.md#column-ownership-and-the-synclock-writer-mutex)
for the full rationale and column-ownership table.

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
   - `removed_from_cloud` → **no-op during normal sync** (the count is
     surfaced on `SyncResult.removed_from_cloud` and a `WARNING` log
     line is emitted, but no rows or files are deleted). Deletion is
     opt-in through `ohtv sync --repair --prune` — see
     [Repair](#repair-ohtv-sync---repair) below.
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
removes the **manifest entry** so the work list stays coherent and
emits a `WARNING`-level log line (`Removed N conversation(s) from
manifest (no longer visible in cloud listing).`). The number of items
treated this way is surfaced on `SyncResult.removed_from_cloud` so
scripts wrapping `ohtv sync` can observe it.

The DB row and on-disk trajectory are **not** deleted by normal sync.
To inspect and act on those, use [Repair](#repair-ohtv-sync---repair)
below — `ohtv sync --repair` reports `removed_from_cloud` as a
distinct bucket, and `--repair --prune` is the explicit opt-in that
deletes the DB row, the on-disk directory, and the manifest entry.

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

## Sub-conversations (Issue #108)

`ohtv sync` includes **delegated sub-conversations by default** — conversations
spawned by agent delegation / sub-agent flows whose
`parent_conversation_id` on the cloud is non-null.

The cloud listing endpoint
(`GET /api/v1/app-conversations/search`) silently defaults
`include_sub_conversations=false`. `ohtv` now forwards `true` on every
listing request so the local mirror matches what
`GET /app-conversations/count` reports and what the cloud UI shows. There
is no new CLI flag; the change is in the API client.

### What you'll see on the first sync after upgrading

If your account has accumulated delegated sub-conversations on the cloud
that previously never reached disk, your first post-upgrade `ohtv sync`
will catch them up:

- The set-diff engine (see "How the set-diff engine works" above)
  observes new ids in the cloud listing and downloads them.
- Multi-thousand-row spurious gaps that previously appeared under
  `ohtv sync --repair --check-cloud` should now close in a single run.
- Steady-state subsequent runs do zero extra downloads.

### `parent_conversation_id` on `conversations`

Each cloud conversation's row in `conversations` now carries a
`parent_conversation_id` column (migration 019):

- `NULL` for root conversations and for all local CLI conversations
  (delegation is a cloud-only concept today).
- Set to the parent's id (normalized / dashless) for sub-conversations.

The column is populated two ways, both inside `ohtv sync`:

1. The download writeback (`record_cloud_download`) carries
   `parent_conversation_id` from the listing payload into the row at
   download time.
2. The scanner pass reads from the same `cloud_listing` snapshot table
   (Issue #112) via `load_cloud_listing_parents`, so a fresh
   `ohtv db scan` over a manifest-populated dataset stays consistent
   with sync — no extra cloud round-trip needed.

The sync manifest (`~/.ohtv/sync_manifest.json`) is intentionally
**parent-agnostic** — it remains the canonical cache for cloud-side
*editable* metadata (`title`, `labels`, `selected_repository`,
`created_at`; see `--update-metadata` below), while
`parent_conversation_id` is a structural relationship stored only in
the DB. This matches the ownership shape used for `cloud_updated_at`
(migration 018) and follows the same scope decision Issue #87
established for the manifest.

Downstream features (e.g. parent-rollup reports, child enumeration)
can now query the relationship locally:

```sql
-- All sub-conversations of a given parent
SELECT id, title FROM conversations
WHERE parent_conversation_id = '<parent_id_dashless>';
```

The `idx_conversations_parent` partial index (also added by migration
019) keeps that lookup cheap.

---

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
  run `ohtv sync --repair` — and, if you want to delete them locally,
  `ohtv sync --repair --prune`). Neither is acted on automatically.
- A normal `ohtv sync` auto-runs this refresh **only when** at least one
  new or updated conversation was actually downloaded. It never fires
  on `--dry-run`, `--force`, `--repair`, or `--status`.

Output rows: the summary always shows `Title changed`, `Labels changed`,
`Both changed`, and `Unchanged`. The newer `Repository changed` and
`Created_at changed` rows are shown **only when their count is nonzero**,
keeping the steady-state output compact for the common case where only
title/labels drift.

---

## Repair (`ohtv sync --repair`)

`--repair` reconciles your local store against the cloud listing and,
optionally, applies fixes. It is the user-facing entry point for the
removed-from-cloud bookkeeping that normal sync only logs, and it is
the only command that can download an "architectural gap" — a
conversation that exists on the cloud but was never registered
locally.

Every invocation refreshes the `cloud_listing` snapshot first (so the
report reflects current cloud truth), then diffs that snapshot
against the local `conversations` table to populate **four buckets**.

### The four buckets

| Bucket | What it means | Hint shown in output |
|---|---|---|
| **New on cloud** | Conversation appeared in the cloud listing after your previous snapshot cutoff. It is genuinely new — the next normal `ohtv sync` will pick it up. | `[next sync will fetch]` |
| **Missing locally** | Present in the cloud listing, absent from your local store, and `created_at` predates the previous snapshot cutoff. This is the architectural gap that should not exist — typically the residue of an interrupted sync, an old `--since` filter, or a pre-#111 cursor that skipped pre-existing items. | `[--fix to download]` |
| **Removed from cloud** | Present locally (`source='cloud'` rows only), absent from the latest cloud listing. The cloud may have deleted them, your access may have been revoked, or you may be looking at a different tenant. Files and DB rows are preserved by default. | `[--fix --prune to delete]` |
| **Modified on cloud** | Present on both sides, but `cloud_listing.updated_at` differs from your local `cloud_updated_at`. The cloud copy has been edited since you last downloaded. | `[--fix to refetch]` |

The legacy ghost / orphan diff (`manifest` vs the synced
conversations directory on disk) is preserved alongside these four
buckets so existing tooling that relies on it keeps working.

`is_consistent` is `True` **only** when every bucket — all four
cloud-vs-local buckets *and* both legacy buckets — is empty. With
`--quiet`, this drives the exit code:

- `--repair --quiet`: exit `0` if consistent, exit `1` if any bucket
  has at least one entry.
- `--repair` (non-quiet): always exits `0` (the human-readable report
  is the signal); the non-zero exit only kicks in for hard errors
  like auth failure or lock contention.

### Action matrix: `--dry-run` vs `--fix` vs `--fix --prune`

| Invocation | `missing_locally` | `modified_on_cloud` | `removed_from_cloud` | Ghost entries | Orphaned files |
|---|---|---|---|---|---|
| `--repair --dry-run` | report | report | report | report | report |
| `--repair` (= `--repair --fix`) | **download** | **refetch** | report only | **drop from manifest** | **add to manifest** |
| `--repair --prune` (= `--repair --fix --prune`) | **download** | **refetch** | **delete DB row + on-disk dir + manifest entry** | **drop from manifest** | **add to manifest** |

Notes:

- `new_on_cloud` is never actioned by `--repair`. It is informational —
  the next normal `ohtv sync` is the right way to pick those up.
- `--prune` is **gated**. Passing `--prune` without `--repair --fix`
  (i.e. without `--repair`, or with `--repair --dry-run`, or
  bare-`--prune`) raises a Click `UsageError` and exits **2**.
- `--prune` only ever touches rows with `conversations.source =
  'cloud'`. Local-CLI conversations are filtered out at the deletion
  call site even if a future bug were to leak them into the bucket.

### Sample output

```
$ ohtv sync --repair --dry-run

           Sync State Consistency Check
  Cloud conversations          1,247
  Manifest entries             1,243
  Conversations on disk        1,243
  Last snapshot completed at   2026-05-29T05:14:02Z

✓ Ghost entries: 0
✓ Orphaned files: 0

Cloud-vs-local set diff
  New on cloud (≥ last snapshot):       2     [next sync will fetch]
  Missing locally (gap):                3     [--fix to download]
  Removed from cloud:                   1     [--fix --prune to delete]
  Modified on cloud:                    0     [--fix to refetch]

Run --repair (without --dry-run) to apply non-destructive fixes (3 + 0 = 3 items).
Add --prune to also delete 1 removed-from-cloud items.
```

Re-running with `--repair` (i.e. `--fix`) downloads the 3 missing
items; adding `--prune` additionally deletes the 1 removed item.

### Lock semantics

`--repair` interacts with the `$OHTV_DIR/sync.lock` writer mutex
(see [Writer mutex](#writer-mutex-synclock) above) **based on whether
it can write**:

| Invocation | Takes `sync.lock`? | `--lock-timeout` honored? |
|---|---|---|
| `ohtv sync --repair --dry-run` | **No** — it is a pure diagnostic. Safe to run alongside an in-flight `ohtv sync`. | n/a |
| `ohtv sync --repair` | **Yes** — it downloads and mutates the manifest / DB. | Yes; default `0` = fail-fast with `SyncLockTimeout`. |
| `ohtv sync --repair --prune` | **Yes** — it also deletes files. | Yes; default `0` = fail-fast with `SyncLockTimeout`. |

Because `--repair --dry-run` skips the lock, the listing snapshot it
refreshes can shift between two consecutive read-only invocations if
a normal sync is running concurrently. That is a documented contract,
not a bug; the rationale is in the
[#109 column-ownership table](../reference/database.md#column-ownership-and-the-synclock-writer-mutex).

### Degraded listing fallback

If the listing pass cannot complete (HTTP error mid-page, network
timeout, missing API key, a hiccup in the local snapshot table), the
in-flight snapshot is abandoned and the **previous** snapshot is
preserved intact — `--repair` will compute buckets against that
prior snapshot.

`RepairResult.listing_degraded` is set to `True` in that case, the
CLI prints a `✗ Listing degraded (HTTP failure or no API key);
previous snapshot left intact. Counts below reflect the prior
snapshot.` warning above the bucket table, and **`--fix`
short-circuits to non-destructive only**: ghost / orphan housekeeping
still runs, but no downloads are dispatched and no rows are pruned.
Re-run `--repair` once the listing is healthy to apply the deferred
fixes.

### Exit codes summary

| Condition | Exit |
|---|---|
| Consistent (non-quiet) | `0` |
| Drift detected (non-quiet) | `0` (report is the signal) |
| Consistent + `--quiet` | `0` |
| Any drift + `--quiet` | `1` |
| `--prune` without `--repair --fix` | `2` (Click `UsageError`) |
| Lock contention with `--lock-timeout=0` | `1` (`SyncLockTimeout`) |
| Auth failure (401/403) | `1` |
| Network failure during `--fix` downloads | `1` (`SyncAbortedError`) |

---
