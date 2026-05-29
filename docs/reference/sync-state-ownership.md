# Sync-state ownership and the manifest-retirement plan

This document is the reference map for sync-state ownership during the
manifest-retirement project ([#114]). It captures, for the current `main`,
**which store owns which field**, **where the manifest is still read or
written**, **where the dual-store contract leaks**, and **the phased plan**
for draining the manifest into the SQLite index.

It is intentionally narrow. It documents the current contract; it does not
change it. The four-phase plan in [section 3](#3-phased-plan) explains how
the contract evolves and which still-open issues each phase blocks on.

All `file:line` citations target current `main` (commit `67de7ede`). When a
brittle spot or call-site moves, **update the citation here in the same PR
that moves the code** — this doc is the contract.

> **Companion reading**
> - [AGENTS.md item #27](../../AGENTS.md) — narrative summary of the
>   manifest-as-canonical contract; this doc is the structured reference.
> - [docs/reference/database.md, "Column Ownership and the `sync.lock`
>   Writer Mutex"](database.md) — DB-column writer ownership per
>   `source` value (#109).
> - Companion issues: [#109], [#111], [#112], [#113], [#110]/PR #119.

---

## 1. Current ownership map (post-#86 / #87 / #109 / #111 / #112 / #113)

### 1.1 Per-conversation field ownership

For each field that lives on a conversation, this table records:

- **Manifest writer** — file:line of the code that writes the value into
  `~/.ohtv/sync_manifest.json` (via `SyncManifest.save`, sync.py:248).
- **DB writer** — file:line of the code that writes the value into
  `conversations` (or, where called out, a sidecar table).
- **Canonical** — which store the rest of the system treats as truth for
  this field today.
- **Read-overlap (scan-time)** — where the scanner consumes the manifest
  value and overlays it onto the DB at scan time.

| Field | Manifest writer | DB writer | Canonical | Read-overlap (scan-time) |
|---|---|---|---|---|
| Sync-state scalars: `last_sync_at`, `sync_count`, `failed_ids` | `sync.py:1121-1142` (`_finalize_sync`); reset path `sync.py:2095-2115` | `sync_kv` mirror only (`sync.py:1149-1157`) | manifest (`sync_kv` is a write-only mirror) | n/a |
| Per-conv cloud `updated_at` (sync gate) | `sync.py:1091` (`_update_manifest_entry`) | `conversations.cloud_updated_at` via `_record_cloud_download_in_db` (`sync.py:970-986`) | manifest (engine still compares manifest, not DB — see `sync.py:553-556`) | `_build_work_items_from_cloud_listing` (`sync.py:531-557`); legacy path `_determine_action` (`sync.py:916-924`) |
| Per-conv `downloaded_at` | `sync.py:1093`, repair `sync.py:1700` | — | manifest only | n/a |
| Per-conv `event_count` (downloaded-time snapshot) | `sync.py:1092`, repair `sync.py:1699` | — | manifest only | `--status` sums it at `sync.py:1161` |
| Per-conv `event_count` (scan-time live count) | — | `scanner.py:499-511, 516-529` (`store.upsert`) | DB | refreshed every scan via `count_events` (`scanner.py:489`) |
| Per-conv `selected_branch` | `sync.py:1097` (from `meta.json` via `_read_selected_branch`), repair `sync.py:1704` | — | manifest only (no DB column) | `scanner.py:235-241` (presence-key gate); read at `scanner.py:263-271` |
| Per-conv `title` | `sync.py:1090` (download) + `sync.py:1940-1947` (refresh path) | `scanner.py:499-511, 516-529` (overlay); `sync.py:1971` (`update_metadata`) | manifest ([#86]) | `scanner.py:221-228, 254-261` |
| Per-conv `labels` | `sync.py:1094` (download) + `sync.py:1940-1947` (refresh path) | `scanner.py:499-511, 516-529` (overlay); `sync.py:1971` (`update_metadata`) | manifest ([#86]) | `scanner.py:299-311` |
| Per-conv `selected_repository` | `sync.py:1096` (download) + `sync.py:1940-1947` (refresh path) | `scanner.py:499-511, 516-529` (overlay); `sync.py:1971` (`update_metadata`) | manifest ([#87]) | `scanner.py:235-261` |
| Per-conv `created_at` | `sync.py:1098` (download) + `sync.py:1940-1947` (refresh path) | `scanner.py:499-511, 516-529` (overlay); `sync.py:1971` (`update_metadata`) | manifest ([#87]) | `scanner.py:235-271` |
| Per-conv `parent_conversation_id` | — | `sync.py:980-986` (`record_cloud_download`); scanner overlay at `scanner.py:318-324` | DB (manifest is parent-agnostic — see AGENTS.md #31) | scanner reads from `cloud_listing` via `load_cloud_listing_parents` (`scanner.py:448-455`) |
| `id`, `location`, `registered_at`, `events_mtime` | — | `scanner.py:499-511, 516-529`; `conversation_store.py` upsert | DB | — |
| Events-derived `updated_at` (per-conv) | — | `scanner.py:499-511, 516-529` via `extract_metadata` (`scanner.py:280-282`) | DB | — |
| `source` | — | `scanner.py:499-511, 516-529` (insert-time, immutable) | DB | — |
| `summary` | — | analysis pipeline (`gen objs`) | DB | — |

> **`sync_kv` is a transitional sidecar, not an owner.** The
> `sync_kv` table introduced by migration 018 mirrors `last_sync_at` so
> [#114] Phase B can flip the canonical bit without a flag day. The engine
> never reads from it today (`sync.py:1149-1157`). It is listed under
> "Manifest writer" because that is where the dual-write happens.

### 1.2 Manifest reader call sites (the surface to drain)

These are the places that have to disappear (or switch to a DB read) before
Phase D can ship.

| Site | File:line | Purpose |
|---|---|---|
| `SyncManager.__init__` | `src/ohtv/sync.py:263-266` | Long-lived in-process manifest held for the duration of a sync run. |
| `load_manifest_metadata` | `src/ohtv/db/scanner.py:70-131` | Per-scan snapshot read; consumed by `extract_metadata`. |
| `load_manifest_labels` (legacy wrapper) | `src/ohtv/db/scanner.py:133-142` | Back-compat shim over `load_manifest_metadata`. |
| `extract_metadata` overlay | `src/ohtv/db/scanner.py:172-333` | Reads the snapshot and overlays it onto the DB write — the cold-`db scan` skip-`base_state.json` optimization from [#87]. |
| `_apply_local_title_writeback` | `src/ohtv/cli.py:9821-9922` | `gen titles --apply` post-PATCH writeback ([#89]). |
| `_preview_manifest_writeback` | `src/ohtv/cli.py:9777-9802` | `gen titles --dry-run` preview ([#89]). |
| `ohtv db status` config print | `src/ohtv/cli.py:820-827` | Existence check only; no data read. |
| `_fetch_cloud_listing_for_repair` orphan rebuild | `src/ohtv/sync.py:1335-1342` (call), `sync.py:1675-1706` (builder) | `--repair --fix` rebuilds orphan manifest entries from the listing ([#87] + [#113]). |
| `update_metadata` refresh path | `src/ohtv/sync.py:1712-1851` | `ohtv sync --update-metadata` reads `self.manifest.conversations` to diff against the cloud listing ([#86]). |
| `_build_work_items_from_cloud_listing` | `src/ohtv/sync.py:494-580` | Set-diff engine reads `self.manifest.conversations[*].updated_at` as the sync gate. **This is the one Phase B / Phase C work-list path that has to flip first.** |

The manifest's top-level scalars are read in `SyncManifest.load`
(`sync.py:234-245`) and in the failed-id retry path (`sync.py:602-619`).

---

## 2. Brittle-spot catalogue

The places where the dual-store contract leaks. Each item is also the test
case the phased plan has to keep passing. Numbers map 1:1 to the
expanded-issue comment on [#114].

1. **Scanner clobbers concurrent sync writes** (`scanner.py:448`
   `load_manifest_metadata()` + `scanner.py:499-511, 516-529` `store.upsert`).
   The manifest snapshot is read once at scan start. If sync rewrites the
   manifest 30s into the scan, `extract_metadata` keeps using the stale
   snapshot, and `store.upsert(...)` writes ALL columns from the stale view
   — clobbering whatever `update_metadata` already wrote. This is the
   exact [#109] race. **Today** the [#109] `sync.lock` mutex serializes
   sync vs scan vs `gen titles` at the *process* level, which makes the
   race much harder to hit, but the scanner's `update_metadata` call path
   does not take the lock for read-only commands and still trusts a
   snapshot.

2. **Non-atomic manifest writes** (`sync.py:248-257`,
   `SyncManifest.save`). `path.write_text(json.dumps(...))` truncates the
   file before writing. SIGTERM between truncate and write produces a JSON
   parse error on next load, which silently falls through to
   `cls(last_sync_at=None, sync_count=0, conversations={}, failed_ids=[])`
   in `SyncManifest.load` (`sync.py:234-245`) — i.e. a full reset
   masquerading as "no manifest yet." No atomic rename, no `os.fsync`, no
   checksum.

3. **Metadata-refresh path writes manifest then DB with no transaction**
   (`sync.py:1894-1976`, `_update_metadata_with_error_handling`; manifest
   write at `sync.py:1940-1947`, DB write at `sync.py:1969-1974`). If the
   manifest write succeeds and the DB write raises, the manifest reflects
   the new title and the DB doesn't. The next scan papers over this (the
   manifest overlay re-applies the title) — but only if scan runs and only
   if the manifest survived (see #2).

4. **`gen titles --apply` writeback has the same shape**
   (`cli.py:9821-9922`). Manifest update in-memory →
   `manifest.save(path)` (`cli.py:9875-9881`) →
   `ConversationStore.update_metadata` (`cli.py:9907-9912`). Same crash
   window. Same dependency on a self-healing next-scan.

5. **`event_count` is in both stores with different semantics** and the
   `--status` summary sums the wrong one. `sync.py:1161`:
   ```python
   total_events = sum(c.get("event_count", 0)
                      for c in self.manifest.conversations.values())
   ```
   That is the snapshotted-at-download-time count, not the live scanner
   count. Users hit this when a conversation grows post-sync — the figure
   is stale until the next download.

6. **`selected_branch` lives only in the manifest**
   (`sync.py:1097` write; `scanner.py:235-241, 263-271` read). It is the
   one field the cloud listing API does not return — it is mirrored from
   the trajectory ZIP's `meta.json` at download time. Today there is no DB
   column for it. Any plan to retire the manifest must add a DB column for
   `selected_branch` first.

7. **Scanner's manifest-title precedence treats explicit `None` as
   "no manifest title"** (`scanner.py:226-228`:
   `if isinstance(mt, str) and mt.strip():`).
   Manifest-as-canonical ([#86]/[#87]) says an explicit `None` should
   *clear* the title, but the scanner falls back to `base_state.json`
   instead. The `created_at` path handles this correctly at
   `scanner.py:268-271` (`elif manifest_created_at is None and
   skip_base_state:`), but `title` and `labels` do not. Latent bug; only
   triggers if a cloud-side rename clears the title to empty.

8. **`load_manifest_metadata` is called even when scanning a single
   conv** (`scanner.py:448, 583`). Read amplification scales with the
   conversation count of the *whole* manifest. Not a correctness issue
   today; will become one once we are reading from DB (Phase C) — at that
   point a single-conv overlay should be a point lookup, not a full
   snapshot rebuild.

9. **`SyncManager.__init__` holds a long-lived in-memory manifest**
   (`sync.py:263-266`). All writes during a sync run go through this
   single instance, then `manifest.save()` rewrites the file from the
   in-memory view. Two concurrent sync processes both hold a stale view;
   whoever calls `save()` last wins. The [#109] `sync.lock` mutex blocks
   concurrent *writer* processes at the file-level today; this brittle
   spot persists because the locking is process-level, not row-level —
   any future relaxation of the mutex (#109's documented Windows gap, for
   instance) re-exposes it.

10. **Repair (`sync --repair --fix`) rebuilds manifest entries from the
    listing but does not write the DB row**
    (`sync.py:1335-1342` call + `sync.py:1675-1706`
    `_build_repaired_manifest_entry`). The DB only catches up when
    `ensure_db_ready()` / `db scan` next runs. Asymmetric repair —
    manifest is healed eagerly, DB is healed lazily. The [#113] four-bucket
    reconciliation (cloud-vs-DB) closes the worst case (missing rows are
    refetched and `record_cloud_download` writes both stores), but the
    "rebuild manifest entry from listing" path is still manifest-only.

---

## 3. Phased plan

### Sequencing summary

| Phase | What | Depends on | Status |
|---|---|---|---|
| A | This document + AGENTS.md note | nothing | **This PR** |
| B | Move sync-state scalars to `sync_state` | [#111] | Bundles **inside** [#111]'s set-diff PR (now closed — see "current state" below). |
| C | Move per-conv cloud metadata cache to DB columns | [#109], [#112] | Separate PR, opens after [#109] + [#112] merge (both **closed**). |
| D | Retire manifest reads + writes | Phase C ships for one release | Final PR. |

Companion: PR #119 ([#110] test harness) is **not** a blocker for any
phase. The interaction is described in [section 4](#4-pr-119-interaction).

> **Current state of dependencies (as of `67de7ede`):**
> [#109] — closed (mutex in `src/ohtv/locks.py`).
> [#111] — closed (set-diff engine in `sync.py:494-580`).
> [#112] — closed (migration 018 added `cloud_listing`, `sync_kv`, and
> `conversations.cloud_updated_at`).
> [#113] — closed (four-bucket repair in `sync.py:1184-1366`).
> Phase B's host PR has already shipped; the sync-state scalar move it
> would have carried has therefore been split off into its own follow-up
> (see Phase B below). Phase C is now unblocked. Phase D still gates on
> Phase C shipping for one release.

### Phase A — documentation only (this PR)

- Add `docs/reference/sync-state-ownership.md` (this file) with the
  ownership map, brittle-spot catalogue, and phased plan.
- Update AGENTS.md item #27 to point at this doc.
- **No production code change.**

This phase exists so [#109]/[#111]/[#112]/[#113]'s sequel work can
reference the contract by URL instead of re-deriving it in every PR
description.

### Phase B — sync-state scalars off the manifest

- Once [#112]'s `sync_kv` k/v table exists (it does — migration 018), sync
  writes `last_sync_at`, `sync_count`, `failed_ids` to `sync_kv` rows.
- Manifest top-level is **dual-written for one release** so older
  binaries keep working.
- `ohtv sync --status` reads from `sync_kv` instead of
  `self.manifest.last_sync_at` / `self.manifest.sync_count` /
  `self.manifest.failed_ids`.
- The set-diff engine no longer consults `self.manifest.failed_ids` at
  `sync.py:602-619`; retries are sourced from `sync_kv` instead.

The set-diff PR ([#111]) already started this transition by dual-writing
`last_sync_at` to `sync_kv` (`sync.py:1149-1157`). Phase B finishes the
read side and adds `sync_count` and `failed_ids` to the dual-write.

**Why a follow-up PR instead of [#111]:** the issue body originally
bundled Phase B into [#111] because [#111] retired `last_sync_at` as the
sync gate. [#111] has shipped; the dual-write landed; the read-side flip
did not. Phase B is now a small standalone PR.

### Phase C — per-conv cloud metadata cache to DB columns

Depends on:
- [#109]'s mutex contract (closed) — without it, this is just moving the
  clobber from one column set to another.
- [#112]'s `cloud_updated_at` column (closed, migration 018) — the
  foundation for retiring `manifest.conversations[*].updated_at`.

Steps, in order:

1. Sync writes `conversations.cloud_updated_at` directly (it already does,
   via `_record_cloud_download_in_db` at `sync.py:967-986` — keep it).
2. `event_count`'s manifest snapshot is dropped; `--status` sums
   `conversations.event_count` (the scanner-maintained live count).
3. Scanner's `extract_metadata` reads `title` / `labels` /
   `selected_repository` / `created_at` from the DB columns instead of
   `load_manifest_metadata()`. The `skip_base_state` shortcut from [#87]
   stays — it just keys on DB columns being populated rather than manifest
   keys being present.
4. One-time backfill migration copies any non-NULL manifest value that
   the DB lacks. Runs once via `maintenance_tasks` (AGENTS.md item #25).
5. **Add `conversations.selected_branch` column** (migration 020-ish).
   Sync's `_update_manifest_entry` (`sync.py:1097`) and
   `_build_repaired_manifest_entry` (`sync.py:1703`) start writing it to
   the DB too. The cold-start case where the cloud listing has the conv
   but no trajectory has been downloaded yet leaves the column NULL until
   the first download fills it. This is the **only** new sync write to
   `conversations` permitted by the [#109] column-ownership table — every
   other column in Phase C is already on sync's side.
6. Fix brittle spot #7 on the DB-overlay path while we're rewriting it —
   an explicit-None DB value should clear the title, same as
   `created_at`'s handling at `scanner.py:268-271`.

**PR #119 ([#110]) interaction:** scenario #14 ("Manifest as canonical
metadata source survives sync (#87 guard)") currently asserts the
manifest contract. Phase C flips its assertion to "DB columns are
canonical metadata source". Same test, different overlay layer.
**Do not touch the scenario marker until PR #119 merges** — otherwise
Phase C has a moving target.

### Phase D — retire manifest reads + writes

Lands after Phase C has shipped for one release (gives users time to
downgrade through the dual-write window without losing data).

- Remove all manifest reader call sites listed in
  [section 1.2](#12-manifest-reader-call-sites-the-surface-to-drain).
- `SyncManager.__init__` stops calling `SyncManifest.load`.
- First-run migration: if `sync_manifest.json` exists and is newer than
  the last DB write for any conv, copy forward, then rename to
  `sync_manifest.json.legacy`.

Satisfies the original-issue-body acceptance criteria in one go:
- No code path writes `sync_manifest.json`.
- No code path reads `sync_manifest.json` (including `db scan`,
  `_apply_local_title_writeback`, `_preview_manifest_writeback`).
- `ohtv sync --status` and other commands work from the DB only.

---

## 4. PR #119 interaction

PR #119 is the test harness for [#110]. **No [#114] phase blocks on it**
and PR #119 does not block on any [#114] phase. The interlock matters
because the scenarios pin the current contract:

- **Scenario #14** ("Manifest as canonical metadata source survives sync
  ([#87] guard)") asserts the current contract — manifest wins for
  `title` / `labels` / `selected_repository` / `created_at`. Phase C will
  flip its assertion target to "DB columns win". **Do not touch the
  scenario marker until PR #119 merges**, otherwise Phase C is chasing a
  test fixture that is itself in motion.
- **Scenarios #2 / #3 / #5 / #8 / #9 / #10** (`xfail(strict=True,
  reason="#111")`) flipped to passing when [#111] landed. Phase B (the
  sync-state scalar move that did not ship inside [#111]) inherits those
  flips for free.
- **Scenarios #6 / #7 / #13** (`skip(reason="#112"/"#113")`) flipped when
  [#112]/[#113] landed. Independent of [#114].

---

## 5. Risks

- **`selected_branch` has no current DB column.** Phase C's migration must
  populate it from (a) existing manifest entries for cloud convs, and
  (b) `base_state.json` / `meta.json` for the cold-start case. There is a
  small ambiguity window where the cloud listing has the conv but no
  local trajectory ZIP has been downloaded yet — we leave
  `selected_branch` NULL until the first download fills it. This is the
  documented [#109] "scanner-only column" rule (`scanner.py:235-241,
  263-271`); Phase C must extend the column-ownership table in
  `docs/reference/database.md` to record sync's new write privilege.

- **Concurrent older + newer binaries.** Phase B dual-writes; Phase C
  dual-writes. A user who downgrades after upgrading sees a manifest that
  is a release behind the DB. Acceptable — the documented direction is
  "DB is canonical, manifest is legacy" — but worth calling out in release
  notes.

- **`extract_metadata`'s asymmetric None handling for `title` / `labels`
  vs `created_at`** (brittle spot #7) is currently latent. Phase C must
  fix it on the DB-overlay path — an explicit-None DB value should clear
  the title, same as an explicit-None manifest value *should* but doesn't
  today.

- **The `--status` event-count regression risk** (brittle spot #5) —
  Phase C's switch to summing the scanner's `event_count` produces a
  different number than today on the rare case where a conv has grown
  post-download. This is the correct number, but it is a user-visible
  change. Call out in release notes.

- **Phase D cannot ship the same release as Phase C.** Users who upgrade
  to Phase D, hit a bug, and downgrade back to a pre-Phase-C binary will
  lose any cloud-metadata writes made by Phase D's binary because the
  manifest stopped being written. The dual-write window is the
  forward-compatibility contract; collapse it only after a release.

---

## 6. Out of scope

- Backwards compatibility for **external** tools reading
  `sync_manifest.json` directly (none known; never documented as a public
  contract).
- Sub-conversation support ([#108]) — Phase C touches the conversations
  table but does not add the `parent_conversation_id` column, which
  [#108] already owns (migration 019).
- Cloud-API contract changes — none.
- New CLI surface — none, apart from removing `--repair`'s
  manifest-specific output once Phase D ships.
- Concurrency tests beyond what [#110] / PR #119 already cover.

---

[#86]: https://github.com/jpshackelford/ohtv/issues/86
[#87]: https://github.com/jpshackelford/ohtv/issues/87
[#89]: https://github.com/jpshackelford/ohtv/issues/89
[#108]: https://github.com/jpshackelford/ohtv/issues/108
[#109]: https://github.com/jpshackelford/ohtv/issues/109
[#110]: https://github.com/jpshackelford/ohtv/issues/110
[#111]: https://github.com/jpshackelford/ohtv/issues/111
[#112]: https://github.com/jpshackelford/ohtv/issues/112
[#113]: https://github.com/jpshackelford/ohtv/issues/113
[#114]: https://github.com/jpshackelford/ohtv/issues/114
