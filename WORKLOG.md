### 2026-05-27 17:50 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `4f1e30d` | orchestrator | this cycle | running |
| `5a20c41` | testing | PR #117 — `--force -n` newest-updated fix | **NEW** running |
| `ee4d831` | expansion | Issue #112 — `cloud_listing` schema for set-diff sync | **NEW** running |

**Spawned: 2 Workers (parallel — both slots filled).** Exactly the dispatch forecast by the 17:21Z pre-commit ("If both finished cleanly → next cycle gets two newly-open slots; spawn another expansion (#112) + handle whatever PR state #107 left").

1. **Testing Worker** — `5a20c4108b18474abc84679832975c82` ([conv](https://app.all-hands.dev/conversations/5a20c4108b18474abc84679832975c82))
   - PR: [#117 — fix(sync): sort by updated_at DESC in reset_to_n_newest (#107)](https://github.com/jpshackelford/ohtv/pull/117) — ready, CI green (`pr-review` SUCCESS), 0 manual test results, 0 review threads.
   - Scope: full `pytest -x` regression baseline (expect 1695/1695), focused `TestResetToNNewest`, ruff, T-1..T-8 blackbox matrix (algorithmic correctness, sort-key choice, reverse-polarity, in-PR docs corrections, scope check, integration smoke, README scan), AC pass against #107, post `## Manual Test Results — PR #117` comment, exit.
   - Explicit DO-NOTs: no edits, no commits, no draft-flip, no approve/merge, no WORKLOG touch, no spawning.
2. **Expansion Worker** — `ee4d831acd6947de83ed8d6d0b166714` ([conv](https://app.all-hands.dev/conversations/ee4d831acd6947de83ed8d6d0b166714))
   - Issue: [#112 — Schema additions for set-diff sync](https://github.com/jpshackelford/ohtv/issues/112)
   - The other foundation half (with already-`ready` #110) that unblocks #111. Picked per the 17:21Z pre-commit's explicit next-target rule.
   - Scope: design `cloud_listing` table (or column additions to `conversations`), pick next migration number, define upsert contract, write technical-approach comment with AC + out-of-scope, coordinate with #110's harness (xfail-marked scenarios that flip when #112 lands), apply `ready` label, prepend WORKLOG entry, exit.
   - Explicit DO-NOTs: no source edits (expansion-only), no test code, no PR, no touching other issues' labels, no touching PR #117 in flight.

**Docs-update gate for PR #117 — N/A:** The decision tree's docs-worker spawn applies to PRs introducing user-facing changes (new CLI flags, new env vars, output formats). PR #117 is a behavioral bug fix to existing `--force -n` semantics: no new flag, no new env var, no new output format. `REFERENCE_CLOUD_API.md` L130 is updated **in-diff** for the false `updated_at` DESC claim. README.md is not in the diff and correctly does not need an update. Skipped to testing per "PR exists, ready, CI green, docs updated, no manual test results → Spawn testing worker."

**Worker handoff success (17:21Z → 17:25Z → 17:26Z):** Last cycle's two parallel spawns both completed in <5min wall time:
- Expansion `a907335` for #110 → finished 17:25Z; #110 has `ready` label; technical-approach comment landed at https://github.com/jpshackelford/ohtv/issues/110#issuecomment-4556930022 (FakeCloudClient shape + 16 behavioral scenarios with `xfail(strict=True)` markers per downstream issue).
- Impl `705e31a` for #107 → finished 17:26Z; PR #117 opened at HEAD `556f4b53...`, marked ready immediately after CI gate; 1695/1695 tests pass; AI bot review 🟢 "Good taste" (COMMENTED).
- The expansion→impl→testing handoff for #107 went from raw bug → expanded → priority-set → implemented → in testing in **~45 min** of wall time.

**`## INSTRUCTION:` re-check:** `grep -nE "^## INSTRUCTION:" WORKLOG.md` → 2 matches at lines 622 + 633, both inside ` ```markdown ... ``` ` fenced code blocks (the 10:46Z suggested-shapes templates). **Zero actionable.**

**Decision-tree trace:**

- **Expansion slot:** `a907335` finished (#110 expanded + `ready`). Slot OPEN. 7 issues need expansion: #108, #109, #111, #112, #113, #114, #116. → Spawn for **#112** per pre-commit (other foundation half, unblocks #111). Skipped: #108 (independent, can wait for next cycle), #109 (depends on #112's column ownership clarity), #111 (depends on #110 + #112), #113 (depends on #112), #114 (depends on #111), #116 (orthogonal cleanup, no dependency pressure).
- **PR slot:** PR #117 open, ready, CI green, AI-positive, no human comments, docs updated in-diff, no manual test. → Spawn **testing worker for #117** per "PR exists, ready, CI green, docs updated, no manual test results."

**Spawn details (both):**

- Plugin shape: `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin` (canonical, NOT included in this spawn because the orchestrate skill embedded prompts no longer pass `plugins` — workers pick up plugins from their own start-task context).
- Both `POST /api/v1/app-conversations` with correct `initial_message.content[{type, text}]` schema. Start-tasks `04c7f6a5…` + `76822bdf…` → polled `/start-tasks?ids=…&ids=…` (multi-id syntax requires repeated `ids=` params, NOT comma-separated — re-learned this cycle after a 400 on the comma form). Both `READY` in ~12s with `app_conversation_id` populated.
- Verified post-spawn: both `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`. Cloud-generated titles preserved descriptive intent (🐛 "Manual Test Gate: PR #117 Sync Reset Fix" + 🗃️ "Expand #112: cloud_listing schema for sync") — better than the typical "Conversation NNN" placeholder.

**Current State (verified 17:46–17:50Z):**

- **Open PRs:** 1 — [PR #117](https://github.com/jpshackelford/ohtv/pull/117) (ready, CI green 🟢, AI-bot positive 🟢 "Good taste", manual test in flight via `5a20c41`).
- **Ready issues (2):** #107 (now in PR #117 testing) + #110 (just expanded; impl worker would start after #112 lands its impl since #111 depends on #110+#112 — for now #110's impl is on the queue once a PR slot opens).
- **Need expansion (no `ready`, no `hold`):** #108, #109, #111, #112 (in flight via `ee4d831`), #113, #114, #116 → **7 issues** (#112 covered, 6 remain after this cycle).
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Other running OH conversations for this repo:** `4f1e30d` (this orchestrator) + the 2 new spawns. All else PAUSED/finished/missing.

**Pre-commit for next cycle (~18:20Z window):**

- **If `5a20c41` is `running`** → PR slot stays filled, log status. Testing a 3-file bug-fix PR (pytest -x + 8 blackbox tests) typically runs 10–30 min.
- **If `5a20c41` is `finished` AND a `## Manual Test Results — PR #117` PR comment exists with ✅ Ready to merge AND no blocker bugs** → spawn **merge worker** for PR #117. AI bot review is already positive; no human review round needed.
- **If `5a20c41` is `finished` AND test report shows 🟡/🔴 with bugs** → spawn **review worker** to fold in fixes; re-test on the cycle after.
- **If `5a20c41` is `finished` BUT no test comment was posted** → investigate the conversation events; may need a `## INSTRUCTION:` from human (recall the 11:48Z–15:18Z zombie-blocked stretch — different cause, similar symptom of no-comment-posted).
- **If `ee4d831` is `finished` AND #112 has `ready` label** → expansion slot opens. Next target depends on the dependency tree: #111 (the headline fix) now has both its foundations ready (#110 + #112), so once a PR slot opens, **#111 is the next impl candidate** — but it ALSO needs an impl worker on #112 first (the schema must land before #111 can build the set-diff engine against it). So next expansion target = **#113** (`--repair` four-category, depends on #112 — expansion can proceed in parallel with #112's impl since they don't share schema scope).
- **If both PR slot and impl-of-#112 land in some future cycle** → the critical path becomes: #112 impl → #111 impl (headline fix) → #113 + #114 in parallel.
- **If a new `## INSTRUCTION:` appears in WORKLOG.md (outside fenced code)** → follow it first.

**Housekeeping:** WORKLOG.md is **1678 lines** pre-this-entry, **~1730 lines** post. **Over the established 1600-line custom threshold for this repo.** Archive eligible: the 11:48Z–15:18Z 2026-05-27 "Still idling" block (~660 lines, >6h old, unrelated to in-flight work). **Deferred this cycle** to keep the action count to 2 spawns. **Pre-commit:** the next quiet cycle OR the cycle after that (if quiet doesn't arrive soon) will fire `/truncate-worklog` against that block → `WORKLOG_ARCHIVE_2026-05-27.md` (already exists — append, or write to `_2026-05-27_part2.md` if collision). The 04:21Z–17:26Z block (the productive sync-rewrite planning + #107 fix burst) stays put — recent and contextual.

**Auto-disable check:** Productive cycle (2 spawns) → consecutive-quiet counter remains 0. No auto-disable trigger.

**Lessons re-learned this cycle:**

1. **Multi-id query param syntax:** `/start-tasks?ids=X,Y` returns 400 (comma not a UUID separator). Must use `?ids=X&ids=Y` (repeated params). Same likely true for `/app-conversations?ids=…`. The openhands-api skill could call this out explicitly.
2. **The 17:21Z parallel-spawn forecast worked exactly as designed:** both slots opened on this cycle's wake-up, both filled in one orchestrator action, plugin shape canonical, no spawn retries. The "act on pre-commits when their entry conditions hold" pattern is paying down planning debt cycle-over-cycle.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---


### 2026-05-27 17:26 UTC - Implementation Worker — Issue #107 Complete

**PR opened (ready for review):** [#117 — fix(sync): sort by updated_at DESC in reset_to_n_newest](https://github.com/jpshackelford/ohtv/pull/117)

Implementation summary:
- `src/ohtv/sync.py` — added `conversations.sort(key=lambda c: c.get("updated_at") or "", reverse=True)` inside `reset_to_n_newest` after `search_all_conversations()`, before the `[:n]` slice. Items with `updated_at=None` coerce to `""` and sort to the end under `reverse=True`, so an unknown timestamp cannot displace a known-recent conversation from the keep set.
- `src/ohtv/sync.py` — replaced the misleading inline comment that claimed the API returned items in `updated_at` DESC order; new comment correctly states the API returns `created_at` DESC and explains why the client-side sort is needed.
- `REFERENCE_CLOUD_API.md` L130 — corrected the same false claim about sort order.
- `tests/unit/test_sync.py` — added `TestResetToNNewest` (4 tests) using the existing `_RecordingCloudClient` fake: regression for the dropped-recently-updated bug, `None`-sorts-last, N ≥ total, and empty-cloud no-op.

Test results: 4/4 new tests pass; full unit suite 1695/1695 pass. No new ruff findings.

**Drift from expansion plan, documented in PR body:**
1. Dropped the `created_at` fallback term from the sort key. The expansion proposed `c.get("updated_at") or c.get("created_at") or ""`, but that would let a brand-new-but-never-updated item rank as if it were recently updated — directly contradicting the "sort `None` to the END so unknown timestamps don't displace known-recent ones" constraint in the orchestration prompt. The simpler `c.get("updated_at") or ""` honors that constraint and is locked in by `test_missing_updated_at_sorts_last`.
2. Did **not** touch `src/ohtv/cli.py:329–330` (sync command docstring tightening). The orchestration prompt explicitly scoped that out.

CI: only `pr-review` is configured in `.github/workflows/`, gated on non-draft status. Marked the PR ready immediately after CI gate observation; AI review bot will run on its own. Merge is a separate worker per the workflow.

Out of scope (explicitly): cross-cutting sync rewrite (#110/#111/#112/#113/#114), sub-conversations (#108), concurrency (#109).

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---


### 2026-05-27 17:25 UTC - Issue #110 expanded

Posted technical-approach comment on [#110](https://github.com/jpshackelford/ohtv/issues/110#issuecomment-4556930022) and applied the `ready` label. #110 is the **foundation** for the sync-rewrite critical path — `#110 + #112` parallelizable; `#111` (headline set-diff fix) blocks on both.

Recommended a new `tests/unit/sync/` package (mirroring the `tests/unit/db/` precedent) with: `fakes.FakeCloudClient` (duck-typed against the 7 methods today's `CloudClient` exposes — listing/pagination/count/download/update + `__enter__/__exit__`), `builders.make_trajectory_zip` (promoted from the existing inline `_create_minimal_zip` at `test_sync.py:465`), `strategies.py` for hypothesis property tests, `conftest.py` with `fake_cloud` + `sync_manager_factory` + `seeded_local_state` fixtures, plus `test_behavioral.py` and `test_harness_smoke.py`.

**Critical design point baked in**: the existing `_RecordingCloudClient` (`test_sync.py:890`, ~25 call sites) gets folded INTO `FakeCloudClient` with the same `search_calls` / `download_calls` / `update_calls` recorder shape — no parallel-fake fragmentation, the existing `TestUpdateMetadata` suite migrates by import-swap. Until #111 lands and makes `sync()` accept `client=None`, the fixture patches `ohtv.sync.CloudClient` at the import site to inject the fake (the temporary bridge #111 retires).

Enumerated **16 behavioral scenarios** with per-test markers tied to the implementation issue that flips them: 3 pass-today (initial empty sync, ID normalization, manifest-as-canonical-metadata regression), 10 `xfail(strict=True)` flipped by #111 (gap recovery, backdated `updated_at`, visibility flip, pagination dedup, mid-listing item appearance, mid-sync crash, 2 hypothesis property tests, etc.), 3 `skip` flipped by #112/#113 (snapshot atomicity, set-diff vs `cloud_listing`, `--repair` four-category output — these would crash today because the `cloud_listing` table doesn't exist yet, hence `skip` not `xfail`). `strict=True` is the safety net against an accidental partial fix landing out-of-order in #112/#113. Out-of-scope carve-outs explicit: no `src/ohtv/` changes (those are #111/#112/#113/#114), no `cloud_listing` schema (#112), no concurrency tests (#109), no duplication of #107's `reset_to_n_newest` sort tests.

Repeated the **atomic-switch reminder** from the 16:40Z plan: no feature flag, no dual-write phase — this test suite IS the safety net for the #111 atomic switch. Scenarios discovered during #111 implementation get appended in the same PR rather than filed as follow-ups.

Conv `4f1e30d9…` (this expansion worker). Expansion only — no code changes to `src/`, no PR opened, no implementation of the harness itself (per the prompt's explicit "do not pre-implement the test harness" rule — that lands in a separate impl worker).

---

### 2026-05-27 17:21 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `4b7a792` | orchestrator | this cycle | running |
| `a907335` | expansion | Issue #110 — cloud-sync test harness (foundation) | **NEW** running |
| `705e31a` | implementation | Issue #107 — `--force -n` newest-updated fix | **NEW** running |

**Spawned: 2 Workers (parallel — both slots filled).** This is exactly the dispatch forecast by the 16:50Z pre-commit ("If `302be93` is `finished` AND ready label on #107 → spawn expansion for #110 and impl for #107 in parallel"). Both slots open as predicted; both spawns succeeded on first try.

1. **Expansion Worker** — `a9073355e2774fb788e0b4d99ee1b487` ([conv](https://app.all-hands.dev/conversations/a9073355e2774fb788e0b4d99ee1b487))
   - Issue: [#110 — cloud-sync test harness](https://github.com/jpshackelford/ohtv/issues/110)
   - Foundation for the sync-rewrite critical path. Parallelizable with #112; blocks #111.
   - Scope: post technical-approach comment (FakeCloudClient shape, test scenarios with `xfail(strict=True)` markers, files-to-create estimate), apply `ready` label, prepend WORKLOG entry, exit. **No code changes to `src/`.**
2. **Implementation Worker** — `705e31a1d37c44339d16f3d03808f737` ([conv](https://app.all-hands.dev/conversations/705e31a1d37c44339d16f3d03808f737))
   - Issue: [#107 — `--force -n` newest-updated](https://github.com/jpshackelford/ohtv/issues/107) (`priority:medium`, just assigned this cycle)
   - Scope: implement the 3-line client-side sort in `SyncManager.reset_to_n_newest`, update collateral docs at `sync.py:1142–1143` + `REFERENCE_CLOUD_API.md:130`, add `TestResetToNNewest` (4 tests) to `tests/unit/test_sync.py`, open DRAFT PR with `Fixes #107`, wait for CI green, flip to ready. Explicit "do NOT widen scope into the #110/#111/#112/#113/#114 sync rewrite chain."

**Priority assessment for #107** (run inline this cycle, single ready issue): `priority:medium` — independent of the sync-rewrite critical path, small (~3 LoC core + ~80 LoC tests), not the headline (the headline is #111 which depends on #110+#112). Bug exists in user-visible documented behavior, so worth fixing soon, but not urgent. `gh issue edit 107 --add-label priority:medium` ✓ applied.

**Current State (verified 17:17–17:21Z):**

- **Open PRs:** 0 ✓
- **Ready issues:** #107 (`ready` + `priority:medium`, now in flight via `705e31a`)
- **Need expansion (no `ready`, no `hold`):** #108, #109, #110 (in flight via `a907335`), #111, #112, #113, #114, #116 — **8 issues** (#110 covered, 7 remain after this cycle completes)
  - **New since last cycle:** #116 ("Centralize DB migration into a single 'ensure ready' entry point") filed at 16:50:56Z. Not part of the 16:40Z sync-rewrite batch; orthogonal cleanup. Will be picked up by a future expansion cycle.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker)
- **Other running OH conversations for this repo:** `4b7a792` (this orchestrator) + the two new spawns. All else PAUSED/finished.

**`## INSTRUCTION:` re-check:** `grep -nE "^## INSTRUCTION:" WORKLOG.md` — only matches are inside fenced code blocks (suggested-shapes templates from 10:46Z, now pushed deeper into history by subsequent entries). **Zero actionable.**

**Decision-tree trace:**

- **Expansion slot:** `302be93` (prior #107 expansion) confirmed PAUSED + `ready` label present on #107 → slot OPEN. 8 issues need expansion → spawn for **#110** per 16:50Z pre-commit (foundation, shortest critical path to the headline #111 fix). Skipped #108 (independent, can wait), #109 (depends on #112), #111 (depends on #110+#112), #112 (foundation but #110 picked first to maximize parallelism with the impl worker on #107), #113/#114 (depend on #111), #116 (orthogonal cleanup, no dependency pressure).
- **PR slot:** 0 open PRs + #107 ready+prioritized → spawn **impl worker for #107**. PR slot now filled.

**Spawn details (both):**

- Plugin shape: `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin` (canonical, working since 16:50Z; the 12:17Z–14:46Z zombie/plugin-500 stretch is in the rear-view mirror).
- Both `POST /api/v1/app-conversations` → start-tasks `4c33f9f4…` + `2b9f1c26…` → polled `/api/v1/app-conversations/start-tasks?ids=…` → both `READY` in ~8s with `app_conversation_id` populated.
- Verified post-spawn: both `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`.

**Pre-commit for next cycle (~17:51Z window):**

- **If `a907335` is `finished` AND #110 has `ready` label** → expansion slot opens. Next target: **#112** (other foundation half, schema additions). #112 is the only remaining foundation that unblocks #111. After #112's expansion + impl land, #111 can start.
- **If `705e31a` is `running`** → PR slot stays filled, log status. Impl typically runs 15–60 min (small fix but full PR cycle including CI wait). If `running` for >2h with no PR opened, may indicate stuck or struggling — investigate.
- **If `705e31a` opened a draft PR but CI still red** → PR slot stays filled (worker is still iterating).
- **If `705e31a` opened a ready PR + CI green + docs needed** → spawn docs worker (per workflow gate: docs before testing).
- **If `705e31a` opened a ready PR + CI green + no docs needed + no test results** → spawn testing worker. Note: #107 is purely a behavior fix in `sync.py` (no new CLI flag, no new env var, no new output format), so the docs-update gate likely doesn't fire — README only mentions `--force -n` semantics in passing if at all. Worker will assess.
- **If both finished cleanly** → next cycle gets two newly-open slots; spawn another expansion (#112) + handle whatever PR state #107 left.

**Housekeeping deferred (still):** WORKLOG.md is **1571 lines** pre-this-entry. Under the established 1600-line custom threshold for this repo (set by the 16:50Z pre-commit). Truncation deferred until: (a) a genuinely quiet cycle when there's no other work to do, OR (b) crossing 1600 lines. The 11:48Z–15:18Z 2026-05-27 "Still idling" block (~660 lines) is the obvious archive target — already >6h old and unrelated to in-flight work. Will fire on whichever trigger arrives first.

**Auto-disable check:** Productive cycle (2 spawns) → counter reset to 0. No auto-disable trigger.

**Cycle observations:**

- The expansion→impl handoff worked exactly as designed: #107 went from raw bug report (filed 16:40Z) → expanded with technical approach (16:53Z) → priority-assessed + impl-spawned (17:21Z) in **41 minutes** of wall time. The 16:40Z planning session's investment in pre-expanded issue bodies (with Problem/Solution/AC built in) paid off — the expansion worker only had to add the technical-approach comment, not do codebase archaeology from scratch.
- Both spawns succeeded with the canonical plugin shape on first try. No plugin-500 retries needed this cycle. Continued cooling of the platform issue from earlier today.
- Parallel-slot fill achieved: this is the first cycle since the 16:40Z planning batch where both slots are productively occupied (expansion #110 + impl #107). Throughput maximization in action.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 16:53 UTC - Issue #107 expanded

Posted technical-approach comment on [#107](https://github.com/jpshackelford/ohtv/issues/107) and applied the `ready` label. Recommended **Option A (fix the code)**: client-side sort by `updated_at` descending inside `SyncManager.reset_to_n_newest` (`src/ohtv/sync.py:1111`) before the `[:n]` slice. The `/api/v1/app-conversations/search` endpoint exposes no `sort` parameter, so the server cannot do the work — but `search_all_conversations()` already paginates the full set, so a 3-line `list.sort(...)` on the result is sufficient. Also flagged two collateral wrong-claim spots that share the same root cause and should ship in the same PR: the inline comment at `sync.py:1142–1143` and `REFERENCE_CLOUD_API.md:130`. Test plan adds `TestResetToNNewest` to `tests/unit/test_sync.py` reusing the existing `_RecordingCloudClient` fake (4 unit tests; behavioral cross-cutting tests deferred to #110).

Conv `302be93b60a6496c81c92a0de0cb4acb`. Expansion only — no code changes to `src/`, no PR opened.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 16:50 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `4b7a792` | orchestrator | this cycle | running |
| `302be93` | expansion | Issue #107 — `--force -n` newest-created bug | **NEW** running |

**Spawned: Expansion Worker** — `302be93b60a6496c81c92a0de0cb4acb` ([conversation](https://app.all-hands.dev/conversations/302be93b60a6496c81c92a0de0cb4acb))

State changed dramatically from the 16:18Z "All quiet" cycle. The 16:40Z sync-rewrite planning session (by @jpshackelford via an AI session) filed **8 new issues** (#107–#114) covering the cloud-sync gap-recovery rewrite, with explicit dependency graph encoded in each issue body. PR #106 merged cleanly (per 16:18Z). Auto-disable counter was at **1 of 2**; this cycle resets it to **0** because the spawn is productive.

**Current State (verified 16:46–16:50Z):**

- **Open PRs:** 0 ✓
- **Issues needing expansion (no `ready`, no `hold`):** 8 — #107, #108, #109, #110, #111, #112, #113, #114
- **Ready issues:** 0
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker)
- **Other running OH conversations for this repo:** `4b7a792` (this orchestrator) only; `3617083` (prior orchestrator) is paused/finished. All else PAUSED/finished.

**`## INSTRUCTION:` re-check:** `grep -nE "^## INSTRUCTION:" WORKLOG.md` — the only matches are inside fenced code blocks (suggested-shapes templates from earlier cycles). **Zero actionable** human instructions.

**Decision-tree trace:**

- **Expansion slot:** empty + 8 issues need expansion → **spawn expansion worker for oldest unexpanded issue** = #107.
- **PR slot:** empty + 0 open PRs + 0 ready issues → wait (nothing to implement). Slot stays idle this cycle by design — implementation can only start once the expansion chain produces at least one `ready` issue.

**Why #107 first** (not a strict "oldest" pick — see rationale):

1. **Oldest by issue number** (#107 < #108–#114) → matches the skill's default heuristic.
2. **Independent of the dependency chain** (the 16:40Z entry calls #107 + #108 "independent" of the #110→#112→#111→{#113,#114} critical path), so expansion completing here doesn't gate or get gated by the foundation pair.
3. **Smallest scope** — single-function bug (`reset_to_n_newest` in `sync.py:1011` has a docstring contradicting the cloud API's `created_at DESC` sort). Quick expansion turnaround means the `ready` queue gets its first item fast, and the expansion worker can pick up another issue on the next cycle without holding the slot long.

**Expansion worker scope (prompt highlights):**

- Clone + `uv sync`; scratch branch only — **no PR, no push** beyond the WORKLOG entry.
- Locate `reset_to_n_newest` (`sync.py:1011`) + callers + the `--force -n` CLI handler in `cli.py` + the cloud listing code in `sources/cloud.py`. Confirm the bug in code.
- **Decide Option A (fix code: sort client-side by `updated_at`) vs Option B (fix docs to say "newest created")**, with rationale.
- Post technical-approach comment on #107 with: Recommended Fix, Root Cause, Implementation Plan, Files to Modify, Test Plan, Out of Scope (carving out #108–#114).
- `gh issue edit 107 --add-label ready --repo jpshackelford/ohtv`.
- Prepend a completion entry to top of `WORKLOG.md` on `main` (the repo's newest-first convention, confirmed by reading the existing top entry from the 16:40Z planning session).
- Exit.

**Explicit DO-NOTs encoded in prompt:** no code changes to `src/`, no PR / branch push (only the WORKLOG commit goes to `main`), do not touch #108–#114 (separate future expansion tasks), no `AGENTS.md` / `README.md` edits, no spawning other conversations, no `needs-info` / `needs-split` unless genuinely blocked (the issue body looks straightforward enough that `ready` should be the outcome).

**Spawn details:**

- `POST /api/v1/app-conversations` with `initial_message.content[{type:"text", text:...}]` and `plugins:[{source:"github:jpshackelford/.openhands", repo_path:"plugins/ohtv-workflow", ref:"feat/ohtv-workflow-plugin"}]` per the openhands-api skill + the 04:21Z lesson-learned. Pre-loaded `openhands-api` skill BEFORE spawn this time (04:21Z lesson explicitly recorded; followed).
- Start task `7438fb1b…` → poll: `WORKING` → `READY` at first check, `app_conversation_id=302be93b60a6496c81c92a0de0cb4acb`. Verify: `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`, `pr_number=[]` (expansion-only, no PR pinning).

**Pre-commit for next cycle (~17:20Z window):**

- If `302be93` is `running` → log status, do nothing. Expansion of a small focused bug typically runs 5–20 min; if it's still going at 17:20Z it likely means the worker is being thorough.
- If `302be93` is `finished` AND `ohtv` has `ready` label on #107 → expansion slot opens. Next expansion target should be **#110** (test harness, foundation, blocks #111) — the dependency graph from the 16:40Z entry says #110 + #112 are the parallelizable foundation. Picking #110 next puts the headline-fix (#111) on the shortest critical path. PR slot would then have its first ready issue, so spawn an **impl worker for #107** in parallel.
- If `302be93` is `finished` BUT `ready` label NOT added → check the conversation events; may have added `needs-info` or `needs-split` instead. Address accordingly.
- If two parallel slots open (expansion + impl) → spawn both in the same cycle per the parallel-work model.
- **Housekeeping deferred again:** WORKLOG.md is now ~1490 lines (above the 1300-line pre-commit threshold from 04:21Z). On the **next** quiet cycle OR if WORKLOG.md crosses 1600 lines, run the truncate-worklog skill: archive everything older than 6 hours of productive work (the 04:21Z entry and everything below it through ~10:46Z, plus the 11:17Z–15:48Z zombie-cycle stretch). Deferring this cycle to keep the action count at 1 spawn.

**Auto-disable check:** Productive spawn this cycle → counter reset to 0. No auto-disable trigger.

**Cycle observations:**

- The 16:40Z planning session is a great precedent — pre-filing dependency-graph'd issues with design decisions baked in means downstream expansion workers can move fast (less codebase archaeology, clearer "out of scope" boundaries). Each issue body already has Problem / Solution / AC; expansion just adds the technical-approach comment + `ready` label.
- For #110 and #112 (the foundation pair), expansion can be parallelizable in principle, but the workflow only allows one expansion worker at a time. So #107 first (independent, smallest), then on the next cycle pick whichever of #110/#112 finishes its predecessor expansion first.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 16:40 UTC - Sync rewrite planning session

**Filed 8 GitHub issues covering the cloud-sync rewrite, with an explicit dependency graph encoded in each issue body via `**Depends on:**` headers (GitHub auto-links the refs).**

The sync bug surfaced earlier today (1126 cloud conversations that `ohtv sync` cannot recover under the current architecture) traces to a structural problem: the time cursor `manifest.last_sync_at` is being used as the source of truth for "what should exist locally" via the `updated_at__gte` filter on `/api/v1/app-conversations/search`. Once the cursor advances past a gap (whatever the cause — a prior partial listing, a `reset_to_n_newest` run, a one-time `--since` invocation), the gap is permanent. The cliff in the age distribution of the 1126 missing items (zero items <7 days old, hundreds from Dec 2025–May 2026) is the signature of exactly this class of bug.

Diagnosis + plan split across 8 issues, ordered tests-first. Three architectural decisions resolved during planning and baked into the issue bodies so they don't need a separate RFC.

**Issues filed** (cross-refs are real `#NNN`, not placeholders):

| # | Role | Title |
|---|---|---|
| [#107](https://github.com/jpshackelford/ohtv/issues/107) | independent bug | `--force -n` keeps "newest created", not "newest updated" as documented |
| [#108](https://github.com/jpshackelford/ohtv/issues/108) | independent feature | Sub-conversations are silently excluded from sync |
| [#109](https://github.com/jpshackelford/ohtv/issues/109) | concurrency hardening | Sync and scan can race; column ownership is undocumented |
| [#110](https://github.com/jpshackelford/ohtv/issues/110) | **foundation** | No behavioral test coverage of the cloud-sync surface |
| [#111](https://github.com/jpshackelford/ohtv/issues/111) | **headline fix** | `ohtv sync` can't recover from a gap between local store and cloud |
| [#112](https://github.com/jpshackelford/ohtv/issues/112) | **foundation** | Schema additions for set-diff sync |
| [#113](https://github.com/jpshackelford/ohtv/issues/113) | builds on #111 | `ohtv sync --repair` reports the cloud-side gap but cannot fix it |
| [#114](https://github.com/jpshackelford/ohtv/issues/114) | builds on #111 | Two sources of truth for sync state (manifest + DB) makes correctness brittle |

**Dependency graph:**

```
#107  (--force-n bug)              independent
#108  (sub-conversations)          independent

#110  (test harness)               foundation, blocks nothing directly
#112  (schema)                     foundation, blocks #111 and #109

#111  (set-diff fix)               Depends on: #110, #112
  ├── #113  (--repair)             Depends on: #111
  └── #114  (retire manifest)      Depends on: #111

#109  (concurrency)                Depends on: #112
```

**Critical path:** `#110 + #112` (parallelizable) → `#111` → `{#113, #114}` (parallelizable). `#109` joins after `#112` lands. `#107` and `#108` are independent of the chain and can be picked up any time.

**Design decisions locked into the issue bodies** (chosen during planning to avoid leaving open questions in the issues):

- **Tests-first.** `#110` lands first; subsequent implementation issues flip `skip`/`xfail(strict=True)` markers to passing as each behavior arrives. CI stays green throughout via the markers.
- **Atomic switch, no feature flag, no dual-write phase.** Under release-on-merge with ~48h wall-clock turnaround there is no meaningful soak window, so a flag would be theater. `#110`'s test suite is the safety net.
- **`cloud_listing` is a transactional snapshot.** Replaced atomically per sync run; partial listings leave the previous snapshot untouched. Prevents the original failure mode of computing set-diffs against an incomplete listing.
- **Migration backfills `cloud_updated_at` from existing `sync_manifest.json`** rather than leaving NULL. Avoids a slow first sync after upgrade where every cloud conversation would be re-refreshed.
- **Source-dependent column ownership** (encoded in `#109`): `db scan` owns filesystem columns for all rows; `ohtv sync` owns cloud-sourced metadata for `source='cloud'` rows; `db scan` owns metadata for non-cloud rows. Each column has exactly one writer per row.
- **Process-level mutex** for concurrent `ohtv sync` invocations; lockfile at `~/.ohtv/sync.lock` with PID-liveness staleness detection.
- **`--repair` reports four user-facing categories:** *New on cloud*, *Missing locally*, *Removed from cloud*, *Stale locally*. Distinction between the first two is made by comparing each item's `created_at` against the last successful reconciliation timestamp. Replaces today's misleading single number.
- **Additive-only schema migrations** so older binaries remain compatible (downgrade is non-destructive).
- **Canonical timestamp format:** ISO-8601 UTC with `Z` suffix, microsecond precision, stored as text — matches what the cloud API returns, no normalization round-trip needed on cloud-sourced values.
- **`last_sync_at` retired as a sync gate.** Survives only as a UX field ("last successful reconciliation at …"). The new algorithm never compares timestamps against this scalar.

**Probe findings that informed the plan** (throwaway probes against `https://app.all-hands.dev/api/v1/app-conversations`):

- **Sort order**: `/search` returns items sorted by `created_at DESC`, not `updated_at DESC`. This contradicts the docstring on `reset_to_n_newest` in `sync.py:1011` — that's `#107`.
- **Pagination**: cursor-based via opaque `page_id` token; terminates when `next_page_id` is null. Consistency model not documented; assume keyset-weak (items updated mid-listing may shift within the keyset and be missed). Mitigation: dedup observed IDs across pages; set-diff catches anything missed on the next run.
- **Sub-conversations**: only 2 of the 1133 missing items are subs. Not the headline cause. Filed as `#108` for cleanliness.
- **Age distribution of missing items**: 0 items <7d old; 188 7–30d; 627 30–90d; 311 >90d. The hard cliff at 7d is the signature of a one-time cursor advance, not a gradual drift. Confirms the architectural diagnosis.
- **429 / Retry-After handling**: already robust in `sources/cloud.py` via the `RateLimiter` class with global shared backoff. Not in scope for the rewrite.

**Not yet filed:** the per-issue implementation-detail follow-on comments (schema SQL, lockfile mechanics, fake-cloud-client API shape, timestamp helper, snapshot replacement query, the actual SQL for the three set-diff reconciliation queries). Per repo convention, those are comments on each issue, not body content. Deferred until an implementation worker is ready to pick up the first one.

**Next step:** when ready to start, the foundation pair `#110` (test harness) and `#112` (schema) can be worked in parallel. `#111` (the actual fix) cannot start until both are merged. The headline release that closes the bug for users is the `#111` merge.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 16:18 UTC - Orchestrator

✅ **All quiet** — board empty post-PR #106 merge. No workers spawned.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `3617083` | orchestrator | this cycle | running |
| `f06a530` | merge | PR #106 | finished ✓ (PAUSED, +3m runtime, exit 15:52:55Z — confirmed merged by @jpshackelford manually before worker reached step-7 verify, so worker exited gracefully as forecasted in 15:51Z follow-up) |

**Current State (verified 16:17–16:18Z):**

- **Open PRs:** 0 ✓ (PR #106 merged at 15:50:40Z as squash commit `d7788da4`; issue #103 auto-closed at 15:50:42Z)
- **Ready issues:** 0 (was #103, now closed via #106 merge)
- **Needs expansion:** 0
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker)
- **Recently merged (last 24h):** PR #106 (#103 hatch+docs, 15:50Z), PR #105 (#102 UsageError, 08:23Z), PR #104 (#87 manifest cache, 06:54Z), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z)
- **Other running OH conversations for this repo:** `3617083` (this orchestrator) + `f4ebb1f` ("📝 Review Recent ohtv Activity & Worklog", human-initiated review session unrelated to the orchestrator pipeline). All other recent convs PAUSED/finished.

**`## INSTRUCTION:` re-check:** `grep -nE "^## INSTRUCTION:" WORKLOG.md` returns 2 matches at lines 323 + 334 — both inside ` ```markdown ... ``` ` fenced code blocks (suggested-shapes template from 10:46Z). **Zero actionable.** Verified by inspecting lines 321–335 (code fences on 322 + 333 confirmed). The "Resume normal operations" template was effectively satisfied by @jpshackelford's manual test landing at 15:37:58Z + the resulting 15:46Z merge-worker spawn.

**Decision-tree trace:**

- Expansion slot: 0 issues need expansion → idle.
- PR slot: 0 open PRs + 0 ready issues → nothing to implement. Slot idle.
- **Action:** None. Both slots idle for legitimate reasons (board exhausted, not blocked).

**Auto-disable check:** This is the **first "All quiet" cycle** since the 11-cycle zombie-blocked stretch ended at 15:46Z with a productive merge-worker spawn (which reset the counter to 0). Counter is now **1 of 2** consecutive quiet. No auto-disable this cycle — the rule fires on the **third** consecutive quiet entry (i.e., when there would be 2+ already in WORKLOG and this would be the 3rd). **Pre-commit for next cycle:** if state is still empty AND no new ready issues land before ~16:48Z, the next entry will be the **2nd consecutive quiet** — log it normally, do NOT auto-disable yet. The auto-disable trigger arrives on the **cycle after that** (~17:18Z) if quiet persists.

**Pre-commit for next cycle (~16:48Z window):**

- If new ready issues / open PRs / new conversations have appeared → normal dispatch per decision tree.
- If still 0 open PRs + 0 ready + 0 need-expansion + 0 active workers → log 2nd consecutive "All quiet" entry, counter goes 1→2. Auto-disable holds until 3rd.
- If a new `## INSTRUCTION:` (outside fenced code) appears → follow it first.

**Housekeeping:** WORKLOG.md at 1379 lines pre-this-entry, ~1430 post. Under the 1500-line custom truncation trigger that prior cycles set for this repo. The 19:19Z–22:51Z 2026-05-26 block has been mentioned as archive-eligible across many cycles but already has a corresponding `WORKLOG_ARCHIVE_2026-05-26.md` (presumably moved earlier). On next quiet cycle, if WORKLOG.md crosses 1500 lines, I'll invoke `/truncate-worklog` to archive the 11:48Z–15:18Z 2026-05-27 "Still idling" block (~660 lines), which is now >6h old and unrelated to in-flight work. Deferred this cycle (under trigger).

**Sync note:** `OH_API_KEY="$OPENHANDS_API_KEY" ohtv sync --since 2026-05-27T12:17:35 --quiet` ran cleanly. `gh` API with `GH_TOKEN=$github_token` clean. Tools (`lxa`, `ohtv`) installed into per-run uv venv (`.venv`) — same pattern as recent cycles.

**Lesson confirmed this cycle:** The 15:51Z follow-up's forecast ("Merge worker `f06a530`… will discover the already-merged state via its step-7 verify and exit gracefully without action") played out exactly. `f06a530` ran for ~3 minutes (15:50:04→15:52:55) then paused — clean no-op race, no recovery needed. The 15:46Z spawn was correct under the decision tree at spawn time; the parallel human merge was just faster.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 15:51 UTC - Orchestrator (follow-up)

🎉 **PR #106 merged by @jpshackelford manually** at 15:50:40Z (squash commit `d7788da4`) — between my spawn (~15:47Z) and my worklog push (~15:51Z). Issue #103 auto-closed. Merge worker `f06a530` spawned 3 minutes earlier will discover the already-merged state via its step-7 verify (`gh pr view 106 --json state` → MERGED) and exit gracefully without action. The spawn was a no-op race; no recovery needed.

**Final state for next orchestrator cycle (~16:16Z):**
- Open PRs: 0 ✓
- Ready issues: 0 (was #103, now closed)
- Need expansion: 0
- On hold: #26, #90
- Board is empty → next cycle should produce a normal "All quiet" entry, starting a fresh auto-disable counter (currently 0).

_This follow-up was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 15:50 UTC - Merge Worker

**✅ PR #106 merged.** Squash commit `d7788da4a30ecdad581f43c5f55fba3aacc54b5e` on `main` at 2026-05-27T15:50:40Z. Branch `docs/chart-partial-loc-hatch-103` deleted on merge.

**Issue #103 auto-closed** at 2026-05-27T15:50:42Z via the `Closes #103` footer.

**Conventional commit shape used** (matches the pre-committed template confirmed in @jpshackelford's 15:37:58Z manual test comment):
- Subject: `feat(charts): hatch partial_loc bars + document NULL LOC convention (#103)`
- Body bullets: (a) `hatch=` kwarg on Panel 2 LOC bars when `partial_loc=True`, (b) `Patch("Partial LOC (NULL)")` legend entry, (c) AGENTS.md item #30 NULL-LOC bullet, (d) 1 new test (`test_partial_loc_bars_carry_hatch_marker`) + 1 extended regression guard (`test_bar_calls_receive_expected_pr_counts` now asserts `"hatch" not in first.kwargs` on Panel 1), (e) unit suite at 1691 passed (1690 baseline + 1 new)
- Footer: `Closes #103`

**Merge criteria** that gated this action: `state=OPEN`, `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`, AI `pr-review` check SUCCESS, head SHA `8ba972cb` matches the SHA verified in the manual test comment (T1–T9 all ✅, no blockers).

**Open observation — NOT filed as an issue.** The manual test surfaced one 🟡 cosmetic note: the `Patch("Partial LOC (NULL)")` legend entry is appended unconditionally in `plot_velocity`, regardless of whether any row actually has `partial_loc=True`. Both interpretations are defensible (always-self-documenting vs. conditional-when-relevant) and the merge-orchestrator instruction explicitly said to leave this as an open observation unless it clearly warrants a `ready`-labeled issue. It doesn't — the test comment documents it as intentional/non-blocking, and the existing AC set is silent on the question. If a future reviewer prefers the conditional-legend behavior, it's a ~3-line guard around the `Patch` append in `src/ohtv/reports/charts.py` (around lines 185–192).

**Exit.** Per orchestrator instructions: no further workers spawned, no follow-up issues filed.

---

### 2026-05-27 15:46 UTC - Orchestrator

🎉 **Unblocked! Resume condition (c) met — manual test landed at 15:37:58Z. Spawned merge worker.**

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `f06a530` | merge | PR #106 | **NEW** running ([conv](https://app.all-hands.dev/conversations/f06a5308aa414086aeb7b849eff75fa0)) |
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE (PAUSED, $0, +5h25m) — superseded by human manual test |

**State delta vs 15:18Z (cycle-11 entry):** Major break in the 11-cycle stall.
- **PR #106 now has a `## Manual Test Results` comment** by @jpshackelford at `2026-05-27T15:37:58Z` (URL: https://github.com/jpshackelford/ohtv/pull/106#issuecomment-4556089589). Verdict: ✅ **Ready to merge** — all ACs verified across 9 tests (T1–T9), 1691 unit tests pass (1690 baseline + 1 new), `import ohtv.reports.charts` confirmed lazy (no `matplotlib.*` in `sys.modules`), PNG/SVG/PDF render cleanly, AGENTS.md NULL-LOC bullet present, ruff clean. One 🟡 non-blocking cosmetic note: `Patch("Partial LOC (NULL)")` legend is added unconditionally even when no row has `partial_loc=True` — defensible either way, "merge as-is and optionally file a tiny follow-up." Test comment signed: "_This manual test was run by an AI agent (OpenHands) on behalf of @jpshackelford to recover the orchestrator from its zombie-spawn block on PR #106._"
- PR #106 head SHA still `8ba972cb` (no new commits since 09:24Z), mergeable=MERGEABLE, reviewDecision="", CI checks: pr-review SKIPPED + pr-review SUCCESS (the AI bot), no other reviews requested. **Auto-disable plan from 15:18Z entry is dropped** per its own escape clause ("If ANY of the three resume conditions DO land before 15:46Z, normal dispatch resumes…").
- Open issues unchanged: #103 (`ready`+`priority:low`, will auto-close on merge of #106), #90 (`hold`), #26 (`hold`). 0 need expansion. 0 ready-but-not-prioritized.

**`## INSTRUCTION:` re-check:** Same 2 matches at lines 250 + 261, both inside ` ```markdown ... ``` ` fenced code blocks (suggested shapes from 10:46Z). Zero actionable. Not blocking.

**Action this cycle:** Spawned **merge worker** for PR #106.
- Conv: [`f06a530`](https://app.all-hands.dev/conversations/f06a5308aa414086aeb7b849eff75fa0) (start-task `d4c9530b…` → READY in ~5s; `execution_status=running`, `sandbox_status=RUNNING`)
- Plugin: `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin`
- PR number wired: 106
- Prompt: squash-merge with the pre-committed conventional-commit shape (subject `feat(charts): hatch partial_loc bars + document NULL LOC convention (#103)`, 5 body bullets, footer `Closes #103`), `--delete-branch`, verify MERGED, post completion entry to WORKLOG, exit. Explicitly told NOT to file the cosmetic-legend follow-up unless it clearly warrants it (test comment already documented it as non-blocking / "either is defensible").

**Decision-tree trace:**
- Expansion slot: 0 issues need expansion → idle.
- PR slot: `PR exists, ready, CI green, test results valid (good rating), docs valid (AGENTS.md updated in-PR, README touchpoint N/A — chart rendering is non-CLI internals) → spawn merge worker.` ✓

**Auto-disable counter:** Reset to 0 (productive cycle — work dispatched). The 12-cycle spirit-of-rule threshold from 15:18Z is moot.

**Next cycle (~16:16Z window):** Expect merge worker to have squash-merged #106 and exited. Verify via `gh pr view 106 --json state,mergedAt` (expect MERGED), confirm #103 auto-closed, then check for any new ready issues. With #103 closed and #26/#90 on hold, the board may be empty — in which case normal "All quiet" counting resumes (this entry restarts the streak at 0).

**Sync note:** `ohtv sync --since 4h --quiet` ran cleanly (env: `OPENHANDS_API_KEY=$OH_API_KEY`). `gh` with `GH_TOKEN=$github_token` clean. Tools (`lxa`, `ohtv`) installed into a per-run uv venv (`.venv`) since system Python is non-writable for non-root — noted for future cycles, not a regression.

**Housekeeping:** WORKLOG.md at 1306 lines pre-entry, still under the 1500-line custom truncation trigger. No archive action this cycle.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 15:18 UTC - Orchestrator

> 🛑 **Still idling on PR #106 — cycle 11/N, no retry.** Pre-commit from 14:46Z holds. Resume on `## Manual Test Results` comment OR new (real, non-fenced) `## INSTRUCTION:` OR fresh non-zombie testing spawn.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE +4h57m (PAUSED, ~3µs Δ created==updated, $0, unchanged) |

**State delta vs 14:46Z:** Nothing.
- PR #106 head `8ba972cb` (no new commits since 09:24Z), 0 `## Manual Test Results` comments, only the AI bot `pr-review` SUCCESS 3m50s (LOW risk, "worth merging"), `mergeable=MERGEABLE`, `reviewDecision=""`, CI green.
- Open issues unchanged: #103 (`ready`+`priority:low`, in flight via #106), #90 (`hold`), #26 (`hold`). 0 need expansion.
- Cloud listing for `jpshackelford/ohtv` still shows all-PAUSED/$0 convs; `46367c3` `created_at == updated_at == 2026-05-27T10:21:31` (still 0 events at +4h57m). Sister zombie `35263dc` (14:07Z, PAUSED, $0, 2µs Δ) also unchanged — confirms the platform's zombie pattern is still active for ohtv-workflow plugin spawns. No fresh non-zombie testing-shaped spawn anywhere.

**`## INSTRUCTION:` re-check:** `grep -nE "^## INSTRUCTION:" WORKLOG.md` returns 2 matches at lines 217 + 228 — both inside ` ```markdown ... ``` ` fenced code blocks (the suggested-shapes template from 10:46Z, shifted from L184/L195 to L217/L228 by intervening entries but unchanged in substance). **Zero actionable human instructions.** Consistent with cycles 7–10.

**Action this cycle:** None. 11th consecutive blocked cycle. None of the three resume conditions met:
- (a) fresh non-zombie testing-shaped spawn → ✗ (listing unchanged; `35263dc` is a sister zombie, not a healthy retry)
- (b) human `## INSTRUCTION:` outside fenced code → ✗
- (c) `## Manual Test Results` comment on PR #106 → ✗ (still 0 comments)

**Auto-disable check:** N/A — blocked, not quiet. Counter stays 0. Per 14:46Z plan, the "consider auto-disable on spirit-of-rule grounds" threshold sits at **cycle 12** (~15:46Z window). This is cycle 11 — door is open, not jumping yet.

**Pre-commit for next cycle (~15:46Z window — the threshold cycle):** Unchanged from 14:46Z on the testing-worker-spawn gate. **NEW for cycle 12:** if state delta is still zero (no manual-test comment, no INSTRUCTION, no fresh healthy testing spawn) AND no human signal has landed since 10:46Z (~5h of escalation outstanding), I will write the cycle-12 entry as a one-liner AND invoke auto-disable on spirit-of-rule grounds (12 cycles of identical no-op is exactly what the auto-disable rule is meant to prevent, even though the literal "All quiet" trigger doesn't apply to "🛑 Still idling" entries). The disable POST + worklog disable-message template are already documented in the 10:46Z entry — will copy that template, log the disable, exit. If ANY of the three resume conditions DO land before 15:46Z, normal dispatch resumes and the auto-disable plan is dropped.

**Sync note:** `ohtv sync --since 4h` ran cleanly (env: `OH_API_KEY=$OPENHANDS_API_KEY`). `gh` API with `GH_TOKEN=$github_token` clean.

**Housekeeping:** WORKLOG.md was 1273 lines pre-this-entry. Still under the 1500-line custom trigger established in earlier cycles. The 2026-05-26 19:19Z–22:51Z block is archived (`WORKLOG_ARCHIVE_2026-05-26.md`, 205743 bytes). No archive action this cycle — keeping action-count at 0 per pre-commit discipline.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 14:46 UTC - Orchestrator

> 🛑 **Still idling on PR #106 — cycle 10/N, no retry.** Pre-commit from 13:19Z/13:46Z/14:16Z holds. Resume on `## Manual Test Results` comment OR new (real, non-fenced) `## INSTRUCTION:` OR fresh non-zombie testing spawn.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE +4h25m (PAUSED, 0s Δ created==updated, $0, unchanged) |

**State delta vs 14:16Z:** Nothing.
- PR #106 head `8ba972cb` (no new commits), 0 comments, `mergeable=MERGEABLE`, `reviewDecision=""` (AI bot `pr-review` SUCCESS 3m50s — only check), CI green.
- Open issues unchanged: #103 (`ready`+`priority:low`, in flight via #106), #90 (`hold`), #26 (`hold`). 0 need expansion.
- Cloud conv listing for `jpshackelford/ohtv` returns 40 convs, **all `sandbox_status=PAUSED`, all `$0`** — same set as 14:16Z. `46367c3` `created_at == updated_at == 2026-05-27T10:21:31`, confirming the zombie pattern is stable (still 0 events processed at +4h25m). No fresh testing-shaped spawn anywhere in the listing.

**`## INSTRUCTION:` re-check:** `grep -n "^## INSTRUCTION:" WORKLOG.md` returns 2 matches at lines 184 + 195 — both inside ` ```markdown ... ``` ` fenced code blocks (the suggested-shapes template from 10:46Z). **Zero actionable human instructions.** Consistent with cycles 8/9.

**Action this cycle:** None. 10th consecutive blocked cycle. None of the three resume conditions met:
- (a) fresh non-zombie testing-shaped spawn → ✗ (listing unchanged)
- (b) human `## INSTRUCTION:` outside fenced code → ✗
- (c) `## Manual Test Results` comment on PR #106 → ✗ (still 0 comments)

**Auto-disable check:** N/A — blocked, not quiet. The skill's auto-disable trigger keys on "All quiet" entries (rechecked /orchestrate skill body this cycle); these "🛑 Still idling" entries don't count, consistent with the reasoning in the 10:46Z escalation. Counter stays 0. The human-facing escalation has been outstanding for 4 hours (10:46Z → 14:46Z); if cycle 12 (~15:46Z window) is still blocked, will reconsider whether to invoke auto-disable on spirit-of-rule grounds (10+ cycles of identical no-op is exactly what the rule is meant to prevent, even if the literal trigger doesn't match).

**Pre-commit for next cycle (~15:16Z window):** Unchanged from 14:16Z. One-liner entry unless state changes. Will NOT spawn a testing worker without one of the three resume conditions. **Sliding the "consider auto-disable on spirit-of-rule grounds" threshold from cycle 12 → cycle 12** (no change) — keeping the door open but not jumping early.

**Sync note:** Skipped this cycle (state delta = 0; no need to re-sync trajectories for a one-liner cycle). `gh` API for PR/issue gate-checks runs cleanly with `GH_TOKEN=$github_token`.

**Housekeeping:** WORKLOG.md was 1240 lines pre-this-entry. Well under 1500-line trigger. The 2026-05-26 19:19Z–22:51Z block was already archived to `WORKLOG_ARCHIVE_2026-05-26.md` (verified — the file exists at 205743 bytes). No archive action needed.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 14:16 UTC - Orchestrator

> 🛑 **Still idling on PR #106 — cycle 9/N, no retry.** Pre-commit from 13:46Z holds. Resume on `## Manual Test Results` comment OR new `## INSTRUCTION:` OR fresh non-zombie testing spawn.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE +3h55m (PAUSED, 0s Δ created==updated, $0, unchanged) |

**State delta vs 13:46Z:** Nothing. PR #106 head `8ba972cb` (no new commits), 0 comments, `mergeable=MERGEABLE`, `reviewDecision=""` (AI bot review only, COMMENTED state), CI green (`pr-review` SUCCESS). Open issues: #103 (`ready`+`priority:low`, in flight via #106), #90 (`hold`), #26 (`hold`). 0 need expansion. Conv listing for `jpshackelford/ohtv` shows the same 7 PAUSED convs as 13:46Z — no new testing-shaped spawn.

**Action this cycle:** None. 9th consecutive blocked cycle. None of the three resume conditions met:
- (a) fresh non-zombie testing-shaped spawn → ✗ (no new convs in listing)
- (b) human `## INSTRUCTION:` → ✗ (only matches are inside fenced code blocks from 10:46Z)
- (c) manual-test comment on PR #106 → ✗ (still 0 comments)

**Auto-disable check:** N/A — blocked, not quiet. Counter stays 0.

**Pre-commit for next cycle (~14:46Z window):** Unchanged from 13:19Z/13:46Z. One-liner unless state changes. Will NOT spawn a testing worker without one of the three conditions above. Worklog is at ~1216 lines pre-cycle; truncation threshold (300 lines productive-age cutoff) was reset by recent productive activity, but the 19:19Z–22:51Z 2026-05-26 block is still eligible for archive — deferred again to keep cycle-action-count at 0.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 13:46 UTC - Orchestrator

> 🛑 **Still idling on PR #106 — cycle 8/N, no retry.** Pre-commit from 13:19Z holds. Resume on `## Manual Test Results` comment OR new `## INSTRUCTION:`.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE +3h25m (PAUSED, 3µs Δ, $0, unchanged) |

**State delta vs 13:19Z:** Nothing. PR #106 head `8ba972cb` (no new commits since 09:24Z), 0 `## Manual Test Results` comments, AI bot review only, mergeable=UNKNOWN. Open issues: #103 (in flight via #106, `ready`+`priority:low`), #90 (`hold`), #26 (`hold`). 0 need expansion. Zombie `46367c3` still 3µs Δ / $0 / PAUSED at +3h25m. No fresh non-zombie test spawn in conv listing.

**Action this cycle:** None. 8th consecutive blocked cycle. None of the three resume conditions met:
- (a) fresh non-zombie testing-shaped spawn elsewhere → ✗
- (b) human `## INSTRUCTION:` in WORKLOG.md → ✗ (grep → 0 actionable matches)
- (c) manual-test comment on PR #106 → ✗

**Auto-disable check:** N/A — blocked, not quiet. Counter stays 0.

**Pre-commit for next cycle (14:16Z window):** Unchanged from 13:19Z. One-liner unless state changes. Will NOT spawn a testing worker without one of the three conditions above.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 13:19 UTC - Orchestrator

> 🛑 **Still idling on PR #106 — cycle 7/N, no retry.** Pre-commit from 12:17Z holds. Resume on `## Manual Test Results` comment OR new `## INSTRUCTION:`.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE +2h58m (PAUSED, 3µs Δ, $0, unchanged) |

**State delta vs 12:17Z:** Nothing on PR #106. Head `8ba972cb` (no new commits), 0 comments, AI bot review only, no `## Manual Test Results`. Open issues: #103 (in flight via #106, `ready`+`priority:low`), #90 (hold), #26 (hold). 0 need expansion.

**Action this cycle:** None. 7th consecutive blocked cycle. Decision-tree match (testing worker for PR #106) remains suppressed by 10:46Z platform-pause pre-commit; no fresh non-zombie test spawn has appeared.

**New observation (does not change action):** developer-initiated conv `57e73b02` (LiteLLM proxy fix, 11:46Z) reached `execution_status=finished` cleanly. Confirms the platform IS producing healthy convs for **non-plugin** work in this time window. Strengthens the "ohtv-workflow plugin branch is the zombie trigger" hypothesis (3 of 4 zombies had it; only healthy productive convs today omit it or use it for non-testing work). Still requires sandbox boot logs the orchestrator can't access to confirm. The 12:17Z entry's diagnosis paths are unchanged.

**Auto-disable check:** N/A — blocked, not quiet. Counter stays 0.

**Pre-commit for next cycle (13:46Z–14:16Z window):** Same as 12:17Z. One-liner unless state changes. Will NOT spawn a testing worker without (a) a fresh non-zombie testing-shaped spawn elsewhere in the listing, OR (b) human `## INSTRUCTION:`, OR (c) the manual-test comment landing on PR #106 (which would dispatch the merge worker, not testing).

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 12:17 UTC - Orchestrator

> 🛑 **Idling on PR #106 — ping me when ready.** No retry, no auto-disable. Resume when a `## Manual Test Results` comment lands on #106 OR a `## INSTRUCTION:` appears in WORKLOG.md.

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 | ⚠️ ZOMBIE +1h56m (PAUSED, 3µs Δ, $0) |

**State (unchanged from 11:17Z):**
- PR #106 `oC green ready` 💬0, head `8ba972cb`, mergeable, AI bot review only, no manual-test comment.
- Open issues: #103 (in flight via #106), #90 (hold), #26 (hold). 0 need expansion.
- Zero new ohtv conv spawns (by anyone) since the 10:21Z zombie.

**Action this cycle:** None — 6th identical blocked cycle. Per the 11:17Z pre-commit, no retry until either a fresh non-zombie test spawn appears externally OR the human posts manual-test results OR a `## INSTRUCTION:` lands. Decision-tree match for testing worker is suppressed by the still-active platform diagnosis pause.

**Housekeeping:** WORKLOG.md truncated this cycle (1850 → 1143 lines). Archived 10 older entries to `WORKLOG_ARCHIVE_2026-05-26.md` and `WORKLOG_ARCHIVE_2026-05-27.md`. The 6h productive window now anchors at 04:21Z.

**Auto-disable check:** N/A — blocked, not quiet. Counter stays 0. (See 10:46Z entry for full rationale.)

**Next cycle:** Same one-liner unless state changes. Full diagnosis remains in the 10:46Z entry below.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 11:17 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 — hatch partial_loc + NULL docs | ⚠️ **DEAD** — PAUSED +55min, 3µs Δ, $0 |

🚨 **STILL BLOCKED — Cycle 5/N on PR #106 manual test.** No spawn this cycle (pre-committed by 10:46Z entry: "do NOT immediately re-retry without diagnosis"). No human action since the 10:46Z escalation.

**State delta vs 10:46Z (drift check):**

- **PR #106:** head SHA `8ba972cb` unchanged, 0 comments, only AI bot review (LOW risk, COMMENTED 09:29Z), CI green (`pr-review` SUCCESS). No `## Manual Test Results` comment. No new commits. mergeable=UNKNOWN.
- **`46367c3` (4th zombie):** still `PAUSED` / `execution_status=null` / `accumulated_cost=null` 55 minutes post-spawn. The microsecond delta (3µs) and zero cost confirm it never advanced beyond start-task. Pattern unchanged.
- **No new test spawns by anyone** (human or automation) in the 30 min since the 10:46Z log.
- **No new `## INSTRUCTION:`** in WORKLOG.md (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 actionable matches; the L51/L62 hits are inside the 10:46Z entry's markdown code-block examples).
- **Open issues unchanged:** #103 (`ready`+`priority:low`, in flight via #106), #90 (`hold`+`enhancement`+`priority:medium`), #26 (`hold`). 0 issues need expansion.

**Decision-tree match this cycle:**

- ✅ **Expansion slot:** idle by design (no unexpanded issues).
- ✅ **PR slot:** PR #106 sits at "ready, CI green, docs updated (PR is itself the docs update for #103), no manual test results, AI review only" → decision-tree calls for **testing worker**. Pre-commit from 10:46Z overrides: 4 prior zombies in a row → do not retry until human diagnosis. **No spawn this cycle.**
- ✅ **Auto-disable check N/A** — same reasoning as 10:46Z: this is *blocked*, not *all quiet*. Consecutive-quiet counter remains 0.

**What changed in 30 minutes:** Nothing. PR is in a holding pattern; the platform-side zombie pattern persists (no fifth retry attempted by the orchestrator, so we have no fresh probe — but `46367c3`'s continued PAUSED state at +55min is itself a strong negative signal). Human intervention is still the unblocker.

**Single action human can take to unblock (15 min of work):** clone `docs/chart-partial-loc-hatch-103`, run the test plan from the 09:53Z WORKLOG entry (9 steps), post a `## Manual Test Results` comment on PR #106. Next orchestrator will detect the comment and dispatch the merge worker.

**Pre-commit for next cycle (12:16Z–12:46Z window):**

- If a manual-test comment lands on PR #106 → dispatch **merge worker** (decision-tree: `ready, CI green, test results valid, good rating, docs valid → merge`).
- If a `## INSTRUCTION:` lands in WORKLOG.md → follow it first.
- If state is unchanged (6th identical blocked cycle) → still no retry. Consider adding a short "I'm idling on PR #106 — ping me when ready" preamble at top of next entry and dropping the per-cycle redundant detail. The 10:46Z entry already documents the diagnosis paths exhaustively; further cycles should be one-liners until something changes.
- ⚠️ **Will not spawn a testing worker on next cycle either** unless the conv-listing endpoint shows a fresh non-zombie spawn (test probe) has succeeded — which would require human or another agent to spawn it. Continuing the zombie streak doesn't help.

---

### 2026-05-27 10:46 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 — hatch partial_loc + NULL docs | ⚠️ **ZOMBIE (4th in a row)** — sandbox PAUSED, 0 activity since spawn |

🚨 **BLOCKED — Awaiting human guidance.** No worker spawned this cycle. PR #106's merge gate is stuck on the manual-test step because the platform is producing zombie spawns at a 100% rate over the last 4 attempts.

**Decision-tree match this cycle:**

- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 matches).
- ✅ **Active worker `46367c3` (spawned 10:21:31Z) is the 4th consecutive zombie** — confirmed via microsecond-delta probe on the API listing: `created_at=2026-05-27T10:21:31.042759Z`, `updated_at=2026-05-27T10:21:31.042762Z` (3-microsecond delta → no agent activity ever occurred). For comparison, the 4 most recent **healthy** productive convs all show 2+ minutes of created→updated delta:
  - `a49fc55` (impl, PR #106): 09:22:11 → 09:27:57 (+5m46s) ✓
  - `002d198` (merge, PR #105): 08:22:17 → 08:24:26 (+2m09s) ✓
  - `2a89daa` (test, PR #105): 07:51:30 → 07:56:14 (+4m44s) ✓
  - `7b39f85` (merge, PR #104): 06:51 → 06:55 (+~4m) ✓
- ✅ **PR #106 state on inspection (10:43–10:46Z):** unchanged from 10:22Z. `state=OPEN`, `isDraft=false`, `mergeable=UNKNOWN`, `reviewDecision=""`, `headRefOid=8ba972cb3e8c2bd2c8d0fe8b0eee63502e01779a` (zero drift), last commit `2026-05-27T09:24:57Z`. **No `## Manual Test Results` comment** (`gh pr view 106 --json comments` → 0 comments matching the pattern). AI bot review LOW remains the only review.
- ✅ **Match: "4th-in-a-row zombie → log and escalate, do NOT re-retry without diagnosis"** — exactly the path pre-committed by the 10:22Z cycle. No new spawn this cycle.
- ✅ **Expansion slot:** No unexpanded issues (`gh issue list --state open --json labels` → 3 open: #103 (in flight via PR #106, `ready`+`priority:low`), #26 (`hold`), #90 (`hold`+`enhancement`+`priority:medium`)). Expansion slot idle by design.
- ✅ **Auto-disable check N/A:** This is **NOT** an "All quiet" cycle — there is productive work (PR #106 testing) that is **blocked on platform issues**, not a lack of work. Consecutive-quiet counter stays at 0. (Auto-disable would be inappropriate here: it would silently park the workflow while a PR sits stuck.)

**Confirmed zombie pattern (now 4 in this orchestrator run, all blocking PR #106):**

| # | Conv ID | Spawned (UTC) | Type | Microsecond Δ created→updated | Diagnosis |
|---|---------|---------------|------|-------------------------------|-----------|
| 1 | `9928c514` | 09:16Z | (unknown — testing PR #106?) | n/a (already disappeared from listing) | MISSING sandbox, 0 cost |
| 2 | `1b1cde3d` | 09:46Z | (unknown) | n/a | MISSING sandbox, 0 cost |
| 3 | `f67d9875` | 09:51:52.832638Z → .832640Z | testing PR #106 | **2 µs** | PAUSED sandbox, exec_status=null, 0 cost |
| 4 | `46367c3` | 10:21:31.042759Z → .042762Z | testing PR #106 (retry) | **3 µs** | PAUSED sandbox, exec_status=null, 0 cost |

All four show the same fingerprint: sandbox provisioned, conv ID issued, but `updated_at` advances by single-digit microseconds past `created_at` — meaning the initial-user-message dispatch never reached the agent. This is **distinct from the 08:22Z plugin-block 500s** (which were start-task HTTP 500s BEFORE conv ID issuance — a different failure mode entirely).

**Hypotheses (orchestrator cannot validate without sandbox boot logs):**

1. **Plugin-loader bug** in the `feat/ohtv-workflow-plugin` branch causing agent-server to crash on init AFTER healthy-looking sandbox boot. The 09:53Z cycle noted the response echoed `plugins=null` — server may be silently dropping the plugin payload, but if the agent-server still attempts to load and crashes, that would match this pattern. ⚠️ **However:** the 10:22Z retry succeeded in getting a conv ID with `execution_status=idle` + `sandbox_status=RUNNING` on first poll — same observation that historically meant a healthy spawn. So either (a) initial poll is misleading and zombies look healthy for the first 30–60s, OR (b) the failure is downstream of agent init.
2. **Initial-user-msg dispatch race** in the runtime — the message payload getting lost between start-task READY and the agent's main loop. The 10:22Z entry suggested this hypothesis; nothing today contradicts it.
3. **LLM proxy / downstream timeout** — the agent does start, attempts its first LLM call, the call hangs/times out silently, the agent stalls without surfacing an error. Less likely because 0 tokens were ever recorded (would expect some prompt-tokens if the first LLM call started).
4. **Sandbox image regression** — a recent platform-side image update may have broken the bootstrap. Would explain the cliff-edge transition (07:51Z spawn worked, 09:16Z+ spawns all zombie).

**Recommended human investigation paths (in priority order):**

1. **Pull the sandbox boot logs for `46367c3`** (`46367c39cc1143a4a4d314abdd945fa6`) and `f67d9875` (`f67d9875b58d4df7999ffe09ada9c53e`) — the orchestrator has no access to these. Look for agent-server crashes, plugin-loader exceptions, or LLM proxy connection errors in the boot trace.
2. **Manually run the PR #106 test plan** locally (it's an 86-line / 3-file PR — ~15 min of human testing would unblock the merge gate and resolve the immediate blocker). Test plan is in the 09:53Z WORKLOG entry under "Testing worker scope (prompt highlights)" — 9 steps, all reproducible. If the test passes, the human can post the manual-test comment and the next orchestrator can spawn the merge worker normally.
3. **Compare sandbox image / runtime version** between `a49fc55` (last healthy spawn, 09:22Z) and `f67d9875` (first zombie, 09:51Z). The 29-minute window is the cliff.
4. **If platform issue persists** → add `## INSTRUCTION: Pause workflow pending zombie spawn diagnosis` to WORKLOG.md to silence retry attempts cleanly.

**Suggested `## INSTRUCTION:` shapes for the human:**

```markdown
## INSTRUCTION: Pause workflow — manual-test PR #106 locally and post results

The orchestrator is producing zombie testing-worker spawns at 100% rate.
Skip the testing-worker spawn step until further notice. After the manual
test comment is posted on PR #106, the orchestrator can resume normally
(merge-worker spawn is the next step in the decision tree).
```

OR

```markdown
## INSTRUCTION: Resume normal operations

Platform issue resolved (manually verified a fresh test spawn).
Continue from where you left off: spawn a testing worker for PR #106
if there are no manual test results yet.
```

**Current State (verified 10:43–10:46Z):**

- **Open PRs (1):** [PR #106](https://github.com/jpshackelford/ohtv/pull/106): `oR/oC green ready` (AI bot review LOW only, no manual tests, no issue-thread comments). Head SHA `8ba972cb` (unchanged across 3 cycles). Testing **BLOCKED by platform**, retry-worthy diagnostics: ✗ (4 zombies in a row).
- **Ready issues (1):** #103 (in flight via PR #106 — will auto-close on merge, `priority:low`).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server, awaiting external dep), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none labeled (but PR #106 is informally blocked on platform — this entry IS the surfacing of that).
- **Recently merged (last 24h):** PR #105 (#102 UsageError, 08:23Z), PR #104 (#87 manifest cache, 06:54Z), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z).

**Auto-disable risk this cycle:** **Zero.** Counter stays 0. This is a platform-blocked cycle, not a quiet cycle. The auto-disable logic explicitly keys on "All quiet" entries (no productive work to pick up), which does not match here.

**Housekeeping note:** WORKLOG.md is at **1711 lines pre-this-entry (~1820 post)**. Above the 1500-line trigger flagged by the last 3 cycles. **Deferred again this cycle** because the immediate priority is surfacing the zombie pattern in a fully self-contained entry that the human can read top-down without scrolling through truncated context. Truncation can land in the next quiet cycle once PR #106's gate is unblocked (or the human posts an instruction). The 16:00Z target proposed in the 10:22Z entry slides accordingly.

**Sync note:** `ohtv sync --since $(date -u -d '4 hours ago' +%Y-%m-%dT%H:%M:%S) --quiet` ran cleanly (`OH_API_KEY="$OPENHANDS_API_KEY"`-bridged). Tools installed via `uv venv` + `uv pip install git+...` inside the repo `.venv` (`uv pip install --system` hits `Permission denied` in this sandbox — 4th consecutive cycle with the same install pattern).

**Lessons learned this cycle:**

1. **The 10:22Z pre-commit landed exactly as forecasted.** Predicted: "If `46367c3` is idle/paused/zombie (4th in a row) → log it and consider escalating via `## INSTRUCTION:` to human; do NOT immediately re-retry without diagnosis." Reality: 4th zombie confirmed, no new spawn, escalation logged. Nine consecutive cycles of cleanly-fulfilled pre-commits.
2. **Microsecond-delta probe is a reliable zombie detector.** Healthy productive convs show 2+ minute deltas; zombies show single-digit microseconds. This is more reliable than `execution_status` or `sandbox_status` at first-poll time (both showed `idle`/`RUNNING` on the 10:22Z healthy-looking probe of `46367c3`, but the conversation never advanced past those values). **Codifying for future orchestrators:** treat any spawn with `(updated_at - created_at) < 1s` after a 20-minute wait as a confirmed zombie.
3. **Restraint is the right move at this volume of evidence.** Four consecutive zombies for the same PR means the next retry is unlikely to succeed and IS likely to add another zombie to the listing without surfacing anything new. The pre-commit's "do NOT re-retry without diagnosis" guardrail is exactly right.
4. **The auto-disable logic needs to NOT fire here.** This cycle is a "platform-blocked productive cycle", not a "quiet cycle". The skill's auto-disable trigger keys on "All quiet" entries specifically — confirmed by re-reading the skill body. No counter increment.
5. **Tiny manual-test shortcut available.** PR #106 is an 86-line, 3-file change with a fully-documented 9-step test plan (09:53Z entry). The human could unblock the gate in ~15 minutes of local work and resume the orchestrator cleanly. Calling out this option explicitly so the operational cost is visible.

**Next check (~30 min, ~11:16Z):**

- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first (this is the most likely path; the entry above is a request for one).
- If a `## Manual Test Results` comment appears on PR #106 (human posted it manually, OR a new healthy worker landed it) → spawn **merge worker**. Merge-worker pre-commit shape is already in the 10:22Z entry — re-use verbatim. Squash subject: `feat(charts): hatch partial_loc bars + document NULL LOC convention (#103)`, footer: `Closes #103`.
- If `46367c3` is still zombie AND no human instruction AND no test comment → log "platform-still-blocked, no action this cycle" and **continue restraint**. Do NOT spawn a 5th zombie. **This would be the 1st "platform-blocked" non-quiet cycle in a row** (not the same as a quiet cycle for auto-disable purposes).
- If `46367c3` retroactively comes alive (e.g., LLM proxy unblocked at runtime → the conv suddenly starts processing) AND posts a test comment → great, route as merge worker per the normal flow.
- **Pre-commit further out:** If platform issue persists for 2–3 more cycles without human intervention, the orchestrator should add a `## INSTRUCTION:` to itself nominating "I need eyes on the spawn pipeline" — but that requires deciding when "log and wait" becomes "spam the worklog with no-op entries". Soft threshold: 3 platform-blocked cycles in a row → write a single consolidated escalation summary; do not re-log per cycle.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 10:22 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `46367c3` | testing | PR #106 - hatch partial_loc + NULL docs | **NEW** (retry) |

**Spawned: Testing Worker (retry after zombie `f67d9875`)**
- PR: [#106 - hatch partial_loc bars + NULL LOC docs](https://github.com/jpshackelford/ohtv/pull/106)
- Conversation: [`46367c3`](https://app.all-hands.dev/conversations/46367c39cc1143a4a4d314abdd945fa6)
- Start task: `32a21a4156a94264b2af41d4c16335f8` → `WORKING` → conv `46367c3` ready in ~8s.
- Spawn shape: **plugins block accepted on first attempt** (no 500 this cycle — divergence from the 08:22Z cycle that needed a no-plugins fallback). `execution_status=idle`, `sandbox_status=RUNNING`, `pr_number=[106]`, `selected_branch=docs/chart-partial-loc-hatch-103` ✓.

**Why the retry was necessary:**

The 09:53Z cycle spawned testing worker `f67d9875` for PR #106 at 09:51:52Z. At 10:21Z (~30 min later) its sandbox was still `PAUSED` with `execution_status=None`, `accumulated_cost=0.0`, `prompt_tokens=0`, `completion_tokens=0`. **The conversation never actually executed.** Sandbox booted but the initial user message was never dispatched to the agent — a confirmed zombie spawn (third such pattern observed in this orchestrator run, after `1b1cde3d` at 09:46Z and `9928c514` at 09:16Z, both also MISSING/PAUSED with 0 cost). Without manual test results, PR #106's merge gate is still blocked. Retry was the right call.

**Current State (verified 10:18–10:22Z):**

- **Open PRs (1):** [PR #106](https://github.com/jpshackelford/ohtv/pull/106): `oC green ready`, AI bot review LOW ("Good taste") at 09:29Z, **no manual test results yet**. Head SHA `8ba972cb`, 3 files changed (+86/-3): `src/ohtv/reports/charts.py`, `tests/unit/reports/test_charts.py`, `AGENTS.md`. Testing in flight via `46367c3`.
- **Ready issues (1):** #103 (in flight via PR #106 — will auto-close on merge, `priority:low`).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged (last 24h):** PR #105 (#102 UsageError, 08:23Z), PR #104 (#87 manifest cache, 06:54Z), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z).

**Zombie-spawn pattern (3 confirmed this run):**

| Conv ID | Type | Spawned | Symptom |
|---------|------|---------|---------|
| `9928c514` | (unknown — testing PR #106?) | 09:16Z | MISSING sandbox, 0 cost |
| `1b1cde3d` | (unknown) | 09:46Z | MISSING sandbox, 0 cost |
| `f67d9875` | testing PR #106 | 09:51Z | PAUSED sandbox, exec_status=None, 0 cost |

All three remained sandbox-up but agent-idle: no LLM calls, no events. This is **distinct from the 08:22Z cycle's plugin-block 500s** (those were start-task errors returning HTTP 500 BEFORE the conv ID was issued; today's pattern issues a healthy-looking conv ID, sandbox boots fine, but the initial user message never reaches the agent). Hypothesis: race condition in start-task → agent-server handoff under load, OR a downstream service (LLM proxy? plugin loader?) is selectively timing out. The retry succeeded this time with the same plugin shape that prior cycles flagged as suspect — so plugin block is _not_ the cause of these particular failures. **Watch list for next cycle:** if `46367c3` also zombies, this may need a `## INSTRUCTION:` from human to dig into the sandbox boot logs.

**Pre-commit for next cycle (~10:52Z):**

- If `46367c3` is `running` or `finished` AND a `## Manual Test Results` comment exists on PR #106 with **overall PASS** verdict → spawn **merge worker**. Merge-worker prompt template (self-contained, no plugin dependency):
  1. Branch off main; checkout PR #106 (`gh pr checkout 106`).
  2. Study the full PR diff (charts.py hatch logic, test_charts.py new test + extended assertions, AGENTS.md NULL-LOC bullet).
  3. Update PR description to reflect final state (no review changes occurred, so the body should already be accurate — verify and lightly polish).
  4. Squash-merge with conventional commit:
     - Subject: `feat(charts): hatch partial_loc bars + document NULL LOC convention (#103)`
     - Body bullets: (a) Panel 2 bars now carry `hatch=///` when `VelocityRow.partial_loc=True`, (b) new `Patch("Partial LOC (NULL)")` legend entry on Panel 2, (c) regression guard added to `test_bar_calls_receive_expected_pr_counts` ensuring Panel 1 PR-count bars are NOT hatched, (d) new `test_partial_loc_bars_carry_hatch_marker` test, (e) AGENTS.md item updated with the hatch convention, (f) 1691 unit tests green.
     - Footer: `Closes #103`.
  5. `gh pr merge 106 --squash --delete-branch --subject ... --body ...`.
  6. Verify `state=MERGED` and Issue #103 auto-closed.
  7. Update WORKLOG.md on main with merge entry.
  8. Exit.

  **Explicit DO-NOTs in merge prompt:** no source edits, no fixup pushes, no README/AGENTS.md changes, no re-open, no new follow-up issues (queue is empty after this; #103 is the last ready issue and there are no follow-ups expected from this PR), no priority re-labeling, no other spawns.
- If `46367c3` is `running` and **no** test comment yet → log brief status, no action. Testing workers in this repo typically take 4–8 min; PR #106 setup includes `uv sync --extra charts` which adds ~30s for matplotlib install. Realistic completion window: 10:30–10:36Z.
- If `46367c3` is `idle`/`paused`/zombie (4th in a row) → log it and consider escalating via `## INSTRUCTION:` to human; do NOT immediately re-retry without diagnosis.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.

**Auto-disable risk this cycle:** Low (productive spawn). Counter stays 0. After #103/#106 merge, queue empties (#26 + #90 are `hold` for valid external reasons) — expect quiet-period risk in 2–3 cycles thereafter unless human adds new issues.

**Housekeeping note:** WORKLOG.md is at 1638 lines pre-this-entry (~1720 post). Above the 1500-line trigger; the **truncate-worklog** skill should run next cycle. Deferred this cycle because the immediate priority was unblocking PR #106's test gate. Recommending the 10:52Z orchestrator runs truncation first thing.

**Sync note:** `ohtv sync` skipped this cycle (orchestrator-context-only work).

**Lessons learned this cycle:**

1. **Zombie-spawn pattern is repeatable.** Three confirmed in ~75 min (09:16, 09:46, 09:51), all with sandbox up + agent idle + 0 cost. The 09:53Z orchestrator did not catch the 09:51Z zombie because at that moment the conversation was only ~2 min old and `sandbox_status` had not yet settled. **The orchestrator should NOT mark a spawn as healthy until at least one of {execution_status=running, accumulated_cost>0, prompt_tokens>0} is observed** — `idle/RUNNING` is the necessary-but-not-sufficient state.
2. **Plugin block worked on first attempt.** Confirms the 08:22Z cycle's 500s were transient, not a structural issue. The next orchestrator can continue using plugin-on-first-try, no-plugin-fallback-on-500 as the spawn pattern.
3. **WORKLOG.md needs truncation.** Crossed the 1500-line threshold mid-cycle. Holding the line for the 10:52Z cycle since `46367c3` is the critical-path concern.
4. **Pre-commits remain effective context-bridging.** Each cycle's "next cycle" section is consumed by the next orchestrator essentially verbatim — saves rederiving merge-worker prompts and decision criteria. Eight consecutive cycles with this pattern.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 09:53 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `a49fc55` | implementation | Issue #103 → PR #106 | finished ✓ |
| `f67d987` | testing | PR #106 — hatch partial_loc + NULL LOC docs | **NEW** running |

**Spawned: Testing Worker** — `f67d9875b58d4df7999ffe09ada9c53e` ([conversation](https://app.all-hands.dev/conversations/f67d9875b58d4df7999ffe09ada9c53e))

The 09:35Z impl worker `a49fc55` produced PR #106 (commit `8ba972c`, branch `docs/chart-partial-loc-hatch-103`), flipped it to ready, and the AI bot review landed with a glowing "🟢 LOW / Good taste" verdict. No manual test results comment yet — that's this spawn's job.

**Decision-tree match this cycle:**

- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 matches).
- ✅ **Active workers from prior cycle:** `002d198` (08:22Z merge worker, PR #105) and `a49fc55` (09:24Z impl worker, Issue #103) both `null` / `PAUSED|RUNNING-but-finished` per `/api/v1/app-conversations/search`. PR slot freed for the next stage.
- ✅ **PR #105 closed-loop:** state=MERGED at 08:23:19Z, Issue #102 auto-closed at 08:23:21Z. The 08:22Z cycle's pre-commit landed exactly as predicted (squash subject `chore(charts): wrap ValueError as click.UsageError ... (#102)`, branch deleted, no follow-ups).
- ✅ **PR #106 state on inspection** (~09:50–09:53Z, ~28m post-open):
  - `gh pr view 106`: `state=OPEN`, `isDraft=false`, `mergeable=MERGEABLE`, `reviewDecision=""`, `headRefOid=8ba972cb3e8c2bd2c8d0fe8b0eee63502e01779a`.
  - lxa: `oR green ready 23m 19m ago` — `oR` (opened-and-Ready, no review-bot tag in the history code; the bot review submitted via the `pull_request_reviews` API path, lxa rendered it as `R` not `C` this time — minor lxa display variance, same `COMMENTED` semantic underneath).
  - CI: `pr-review` ✅ pass (3m50s, single SUCCESS check, no SKIPPED legacy this time because the PR was flipped ready immediately rather than draft-then-ready).
  - **AI bot review (`github-actions`, 09:29:27Z):** `state=COMMENTED`, body starts "🟢 **Good taste** - Clean, elegant solution with solid test coverage." Risk LOW. No CHANGES_REQUESTED branch triggered.
  - **0 issue-thread comments, no manual test report.** Gating condition for testing worker.
- ✅ **Docs-worker skip rationale:** `gh pr diff 106 --name-only` → `AGENTS.md`, `src/ohtv/reports/charts.py`, `tests/unit/reports/test_charts.py`. README **not** modified. Per the impl worker's notes (09:35Z entry): "expansion comment confirmed no 'Reading the chart' subsection exists today; adding one is out of scope." Cross-checked README: only 2 lines mention `--chart` (a copy-pasteable example), zero chart-visual documentation. The visual convention being added (hatch + legend) is documented in **AGENTS.md item #30** (the appropriate location for internal renderer conventions) — and the impl worker already updated it. Decision-tree exclusion clause applies: "Internal refactoring (no user-facing changes)" + "Bug fixes that don't change *documented* behavior" — chart visual semantics aren't documented in README, so no README update is required. **Skipped docs worker by policy.** (Identical rationale to PR #105's 07:50Z skip — second time this orchestrator session has documented an explicit skip.)
- ✅ **Match: PR exists, ready, CI green, docs N/A, no manual test results → spawn testing worker.** Bot's glowing review does NOT substitute for manual blackbox validation per the workflow's gate; matches the same path PR #105 took at 07:50Z.
- ✅ **Expansion slot:** No unexpanded issues. `gh issue list --state open` → 3 open issues: #103 (in flight via PR #106), #26 (`hold`), #90 (`hold`). All non-hold issues are `ready` and in flight. Expansion slot idle by design.
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.

**Testing worker scope (prompt highlights):**

The prompt is deliberately thorough for an 86/3 LOC PR because the change has two subtle correctness criteria that pytest-with-mocks can't directly verify without execution: (a) the **lazy-import contract** from AGENTS.md item #30 — `import ohtv.reports.charts` must not pull matplotlib into `sys.modules`, and (b) the **legend entry presence** — the new `Patch("Partial LOC (NULL)")` must actually appear in Panel 2's rendered legend, not just be appended to a list.

1. **Unit suite (full)** — `uv run pytest tests/unit/ -q` → expect 1691 passed (1690 baseline + 1 new). Report exact count.
2. **Chart-tests focus** — all 12 must pass. Specifically the new `test_partial_loc_bars_carry_hatch_marker` AND the extended `test_bar_calls_receive_expected_pr_counts` (with the `"hatch" not in first.kwargs` regression guard for Panel 1).
3. **Lazy-import contract (AC-7)** — explicit `sys.modules` probe before/after `import ohtv.reports.charts`. Hard FAIL if matplotlib loads.
4. **Blackbox happy-path** — render a chart with all `partial_loc=False` rows (`/tmp/v106_solid.png`), verify PNG magic bytes via `file(1)`.
5. **Blackbox change-under-test** — render a chart with mixed partial/full rows (`/tmp/v106_mixed.png`), confirm no crash.
6. **Legend entry verification** — patch `Figure.savefig` to grab `axes[*].get_legend().get_texts()` before close, assert `"Partial LOC (NULL)"` in the captured texts. Hard FAIL if missing.
7. **CLI smoke test** — `uv run ohtv report velocity --chart /tmp/v106_cli.png --include-empty`. May exit cleanly with no data (sandbox DB likely empty); just verify no crash.
8. **AGENTS.md docs check** — `grep -A2 "NULL LOC bar handling" AGENTS.md` → expect the new bullet.
9. **Post structured `## Manual Test Results`** PR comment with SHA `8ba972cb`, env details, per-test PASS/FAIL, overall verdict.
10. **EXIT.** No code edits, no review-thread resolves, no merge, no WORKLOG.md touches.

**Spawn details:**
- `POST /api/v1/app-conversations` with `X-Access-Token: $OPENHANDS_API_KEY`, payload includes `selected_repository`, `selected_branch=docs/chart-partial-loc-hatch-103`, `title`, `pr_number=[106]`, `initial_user_msg` (the testing-worker prompt above), AND the `plugins` block (`[{source: github, id: jpshackelford/.openhands/plugins/ohtv-workflow, ref: feat/ohtv-workflow-plugin}]`).
- **Plugin block accepted this time** — first attempt succeeded. Start-task `34a4b7253d154f79a4e8081fc1910ae8` → `WORKING` → poll via search-by-id at +8s → `execution_status=idle`, `sandbox_status=RUNNING`, `app_conversation_id=f67d9875b58d4df7999ffe09ada9c53e`, `pr_number=[106]`. Response showed `plugins=null` in the request echo (server may have silently dropped the plugin block on accept) but **NO sandbox-boot 500** like the 08:22Z and 09:20Z attempts. Either the platform recovered, or the plugin block is now being parsed and silently ignored. Either way: the spawn succeeded, and the prompt is fully self-contained (gh + uv + git + python suffice) so plugin availability is non-critical.
- Cloud-generated title defaulted to `Conversation f67d9` (request title `[Manual Test] PR #106 - hatch partial_loc bars + NULL LOC docs` — same delayed-population pattern as prior cycles, no functional impact).

**Current State (verified 09:50–09:53Z):**

- **Open PRs (1):** [PR #106](https://github.com/jpshackelford/ohtv/pull/106): `oR green ready` 💬0 (only the bot's review, no issue-thread comments), mergeable, manual testing in flight via `f67d987`.
- **Ready issues (1):** #103 (in flight via PR #106 — will auto-close on merge).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged (last 24h):** PR #105 (#102 UsageError wrap, 08:23Z), PR #104 (#87 manifest full cache, 06:54Z), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Housekeeping note:** WORKLOG.md is at **1556 lines pre-this-entry** (~1620 post). Both the 08:22Z and 09:24Z entries flagged this trend (1500-line local norm); we're now ~120 lines over. The 09:24Z entry explicitly deferred truncation: "Next quiet-period orchestrator run should invoke `/truncate-worklog`." **Pre-committing for the next orchestrator:** if PR #106 merges before the next wake-up AND no new issues land, the next cycle's first action should be `/truncate-worklog` (archive entries older than the most-recent 6 hours of productive work, preserve the Active Workers table). The truncation work fits naturally into a quiet period because it doesn't compete with worker spawns.

**Sync note:** `ohtv sync` skipped this cycle (orchestrator-context-only work; no labeling/analysis depended on fresh sync data). Tools (`lxa`, `ohtv`) installed via `pip install --user` after `uv pip install --system` hit permission errors in this sandbox and `uv venv` wasn't pre-warmed.

**Lessons learned this cycle:**

1. **The 08:22Z pre-commit landed cleanly.** Predicted: "If `002d198` is `finished` AND PR #105 = MERGED AND Issue #102 auto-closed → PR slot empty, but **impl slot has work**: spawn **impl worker for Issue #103**." Reality: merge worker completed at 08:23Z, impl worker spawned at 09:24Z (between cycles, by the prior orchestrator), PR #106 opened at 09:25:24Z, ready at 09:35Z. Eight consecutive cycles of cleanly-fulfilled pre-commits.
2. **Plugin block: maybe transient, maybe permanent.** This cycle's spawn included the plugin block and succeeded on the first try, but the response showed `plugins=null` in the request echo. Two possible interpretations: (a) the 08:22Z + 09:20Z 500s were transient platform issues that have since resolved, OR (b) the server now silently drops/ignores the plugin block while still accepting the request, sidestepping the sandbox-boot crash. The empirical lesson stays the same: **try-with-plugins-first, fall-back-without-plugins-on-500** is a safe pattern, and **prompts should remain fully self-contained** as a hedge.
3. **lxa history-code variance: `oR` vs `oC`.** PR #105 showed `oC` (bot review tagged `COMMENTED`), but PR #106 with the same kind of bot review shows `oR` (ready, no review-tag). Could be lxa-side timing: if the bot review submits before the bot-tagging code refreshes, the history stays at `R`. Doesn't affect the decision tree — both cases match "PR exists, ready, CI green, no manual test results → spawn testing worker." But it does mean the orchestrator must always cross-check `reviewDecision` from `gh pr view` rather than trusting lxa's letter codes for the gate decision.
4. **Docs-worker skip pattern is now a documented rhythm.** Second consecutive cycle (after PR #105's 07:50Z) where docs worker was skipped with explicit reasoning in WORKLOG. The pattern that's emerging: when AGENTS.md (the internal convention doc) is updated by the impl worker AND README has no relevant subsection to update AND the change is visual/internal, skip docs worker. Codifying this as a soft rule: **"docs worker is only required when README has user-facing content to update; AGENTS.md updates by the impl worker do not trigger a separate docs worker."** Worth promoting to the orchestrate skill body if this pattern survives 2–3 more PRs.

**Next check (~30 min, ~10:23Z):**

- If `f67d987` is `running` → log brief status, no action. Testing workers typically take 5–12 min for small PRs (clone, `uv sync --extra charts`, run 8-step blackbox + 1691-test pytest, write comment, post). Likely complete before next wake-up.
- If `f67d987` is `finished` AND a `## Manual Test Results` comment exists on PR #106 with **overall PASS** verdict → spawn **merge worker**. **Pre-committing the merge-worker shape so the 10:23Z cycle doesn't re-derive:** branch is `docs/chart-partial-loc-hatch-103`, head SHA expected `8ba972cb3e8c2bd2c8d0fe8b0eee63502e01779a`, squash subject `feat(charts): hatch partial_loc bars + document NULL LOC convention (#103)`, squash body should cite (a) hatch kwarg on Panel 2 bars, (b) "Partial LOC (NULL)" legend entry, (c) AGENTS.md item #30 NULL-LOC bullet, (d) 1 new test + 1 extended test, (e) full unit suite at 1691, footer `Closes #103`. No follow-ups expected — this PR closes the dual-fix from #103.
- If `f67d987` is `finished` AND test results say **FAIL** → spawn **review worker** to fix whatever the test report flagged. Review worker should flip back to draft, fix, push, flip to ready.
- If `f67d987` is `finished` but no test comment posted → investigate the conversation events; may need `## INSTRUCTION:` from human.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Pre-commit further out:** Once PR #106 merges, the ready queue is **empty** (#26 + #90 are both `hold` for valid external reasons per multiple prior cycles). Expect the next 1–2 cycles after the merge to be quiet. **Auto-disable risk activates at that point** — if `/orchestrate` posts two consecutive "All quiet" entries in a row after the merge, the disable logic triggers (per the skill's documented behavior + automation ID `c202ca20-60d5-4f5b-9d53-3d7308c1d95b`).
- **Auto-disable risk this cycle:** Low (productive spawn). Counter stays 0.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 09:35 UTC - Implementation Worker (Issue #103)

**Status:** ✅ PR opened and flipped to ready-for-review.

- Issue: [#103 — docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars](https://github.com/jpshackelford/ohtv/issues/103) (`priority:low`)
- PR: [#106 — feat(charts): hatch partial_loc bars + document NULL LOC convention (#103)](https://github.com/jpshackelford/ohtv/pull/106) (branch `docs/chart-partial-loc-hatch-103`, opened DRAFT → flipped to ready).
- Commit: [`8ba972c`](https://github.com/jpshackelford/ohtv/commit/8ba972c) — single squashable commit covering both the chart change and the AGENTS.md note.

**Implementation (dual approach per expansion comment):**

1. **Chart change** (`src/ohtv/reports/charts.py`): both `ax_loc.bar(...)` calls in Panel 2 now take `hatch=loc_hatches` where `loc_hatches = ["///" if r.partial_loc else None for r in rows]`. Added a `matplotlib.patches.Patch` legend entry ("Partial LOC (NULL)") appended to Panel 2's legend. `Patch` import is lazy inside `plot_velocity` (preserves AGENTS.md item #30's no-load-at-import contract). Panel 1 (PR counts) intentionally un-hatched.
2. **Docs change** (`AGENTS.md` item #30): added a parallel `**NULL LOC bar handling (#103)**` bullet right after `**Words/LOC gap handling**`, cross-referencing item #28 (#81) as the authoritative table renderer.
3. **Test** (`tests/unit/reports/test_charts.py`): added `test_partial_loc_bars_carry_hatch_marker` mirroring `test_bar_calls_receive_expected_pr_counts`; extended the existing PR-counts test with `assert "hatch" not in first.kwargs` as a regression guard against over-application.

**Verification:**

- ✅ `uv run python -m pytest tests/unit/reports/test_charts.py -v` → 12 passed.
- ✅ `uv run python -m pytest tests/unit/ -q` → 1691 passed (1690 baseline + 1 new test). No regressions.
- ✅ Smoke test: `uv run ohtv report velocity --chart /tmp/v103.png --include-empty` exits cleanly (no rows in this sandbox's DB → empty-path graceful exit; pytest covers the kwargs contract).
- ✅ CI: `pr-review` workflow correctly `skipped` on draft (only workflow on this repo); no failing required checks.

**Notes for orchestrator:**

- Bot review triggered by `gh pr ready 106`. Next orchestrator wake-up should check PR #106 for review feedback or merge-ready state.
- `partial_loc=False` default on `VelocityRow` preserved → backward-compatible with all existing call sites.
- README **not** touched — expansion comment confirmed no "Reading the chart" subsection exists today; adding one is out of scope.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 09:24 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `a49fc55` | implementation | Issue #103 — docs(charts): NULL-vs-zero LOC bar | **NEW** running |

**Spawned: Implementation Worker**
- Issue: [#103 — docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars](https://github.com/jpshackelford/ohtv/issues/103) (labels: `ready`, `priority:low`)
- Conversation: [`a49fc55`](https://app.all-hands.dev/conversations/a49fc55b3a7e40e4a49ed2aa92461476) — title "📝 Document NULL-vs-zero LOC bar convention", `execution_status=running`, `sandbox_status=RUNNING`, `sandbox_id=4lusNMhjgY7SlcK26cBqrG`.
- Start task: `3dd41f11a4` → `READY` on first +10s poll, `app_conversation_id=a49fc55b3a7e40e4a49ed2aa92461476`.

**Spawn-time anomalies (resolved):**

Before this successful spawn, two prior start-tasks ERRORed at sandbox boot:
- `7ffea86b` → ERROR at 09:20:14Z, sandbox `4f39YReTGl…`, detail: `500 Internal Server Error for url '…prod-runtime.all-hands.dev/api/conversations'`.
- `444e1496` → same 500 at 09:21:01Z (sandbox `4DaSfH0tlQ…`). This was an accidental re-POST while the operator was trying to GET task status using the wrong endpoint (`GET /api/v1/app-conversations/{id}` returns the SPA HTML, not JSON); polling start-tasks must use `GET /api/v1/app-conversations/start-tasks?ids=…`.

Both ERROR tasks have no `app_conversation_id` (sandbox bootstrap failed before any conversation record was created), so they are zero-cost no-ops — no ghost conversations to clean up. **Root cause matched the 08:22Z cycle's documented fix:** the spawn payload included a non-empty `plugins` block. Removing it made the 3rd attempt (`3dd41f11a4`) succeed on the first try. Lesson reinforced: spawn payload should be `{title, selected_repository, selected_branch, initial_message}` only — no `plugins` block until the platform supports it again.

**Current State:**
- Open PRs: **none** (PR #105 merged at 08:23:19Z, auto-closed Issue #102).
- Open issues (3):
  - **#103** `ready` `priority:low` — now being implemented (this spawn).
  - **#26** `hold` — skip (waiting for human).
  - **#90** `hold` `enhancement` `priority:medium` — skip (waiting for human).
- Issues needing expansion: **0** (no unlabeled / non-`ready` / non-`hold` issues open). Expansion slot intentionally idle.
- PR slot: occupied by the impl worker for #103.

**Action Taken:**
✅ Spawned 1 worker (implementation, Issue #103). Next orchestrator wake-up should re-poll `a49fc55`; if a PR opens with user-facing changes (README likely needs bar-convention docs and/or hatch hatching), the **docs worker must run before testing** per workflow ordering.

**Housekeeping note:** WORKLOG.md is now at ~1500 lines (over the 300-line threshold). Truncation deferred to a dedicated cycle so this spawn-focused entry stays atomic and reviewable. Next quiet-period orchestrator run should invoke `/truncate-worklog`.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 08:23 UTC - Merge Worker (PR #105)

**PR merged ✅**

- PR: [#105 — chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension](https://github.com/jpshackelford/ohtv/pull/105) (state=MERGED, mergedAt=2026-05-27T08:23:19Z, branch `chore/charts-unsupported-ext-usage-error-102` deleted)
- Squash commit: [`380aa899`](https://github.com/jpshackelford/ohtv/commit/380aa8994a3872e05df4413f171a6efacb0ebf3a) — `chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension (#102)`
- Issue [#102 — chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension](https://github.com/jpshackelford/ohtv/issues/102) **closed** at 08:23:21Z (auto-closed by `Closes #102` in squash-commit footer).

**Pre-merge verification:**

- ✅ HEAD drift check: `gh pr view 105 --json headRefOid` → `2b823c79e238bed0fd04432c0500398570307729` (matched expected, no drift).
- ✅ Mergeable: `state=OPEN` / `mergeable=MERGEABLE` / `isDraft=false`.
- ✅ Diff sanity: exactly 2 lines added in `src/ohtv/cli.py` (the `except ValueError → click.UsageError` branch immediately after the sibling `except ImportError` handler) and one new 12-line test `test_cli_chart_unsupported_extension` in `tests/unit/reports/test_cli_chart.py`. No edits to `src/ohtv/reports/charts.py`, README, or AGENTS.md.
- ✅ AI bot review (07:39:08Z): COMMENTED, "🟢 Good taste - Worth merging", risk LOW.
- ✅ Manual test report (07:56:01Z, posted to PR by AI testing worker): all 8 blackbox CLI scenarios pass (unsupported `.txt`, no extension, missing matplotlib regression, all supported extensions, etc.); full unit suite 1739/1739 green (1738 baseline + 1 new test).

**Squash-merge commit body** (delivered via `--body`):

> - Add a two-line `except ValueError` branch in `src/ohtv/cli.py`'s `report velocity --chart` handler, mirroring the adjacent `ImportError → click.UsageError` pattern. Unsupported/missing extensions now exit 2 with a single-line `Error: …` instead of a Python traceback (exit 1).
> - The module-level `ValueError` contract in `plot_velocity` (`src/ohtv/reports/charts.py`) is intentionally preserved — only the CLI's reaction to that exception is polished. Other API callers and `tests/unit/reports/test_charts.py::test_unknown_extension_raises` are unaffected.
> - Add one new test `tests/unit/reports/test_cli_chart.py::test_cli_chart_unsupported_extension` verifying exit code 2, the expected error string, and the absence of `Traceback` in output.
> - Full unit suite green at 1739 tests (up from 1738); all 8 blackbox CLI scenarios pass per the manual test report comment.
>
> Closes #102

**Notes:**

- No follow-up issues filed (PR was a scope-complete 2-line polish; nothing surfaced during merge verification).
- No new priority labels applied (Issue #103 already has `priority:low` from the PR #104 merge cycle; orchestrator will pick it up next).

**Anomalies:** None. Clean merge.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 08:22 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `2a89daa` | testing | PR #105 — UsageError wrap | finished ✓ |
| `002d198` | merge | PR #105 — UsageError wrap (#102) | **NEW** running |

**Spawned: Merge Worker** — `002d1988f5884fc69dbd88a328aa9ed8` ([conversation](https://app.all-hands.dev/conversations/002d1988f5884fc69dbd88a328aa9ed8))

Testing worker `2a89daa` from the 07:50Z cycle completed cleanly. Manual test report posted at **07:56:01Z** with overall verdict **✅ PASS**:

- 8 blackbox CLI tests: all green (happy-path `.png`/`.pdf`/`.svg`, the change-under-test `.bogus` → exit 2 + clean stderr no traceback, edge cases `.PNG`/no-ext/trailing-dot all produced friendly UsageError).
- Verbatim stderr captured for `.bogus` case confirms zero `Traceback`/`ValueError:` lines.
- Unit suite: **1739 passed** (1738 baseline + 1 new test), 25.00s wall-clock.
- Both `test_cli_chart_unsupported_extension` (new) AND `test_unknown_extension_raises` (module-level contract) pass — CLI-layer wrap does not leak into `plot_velocity`'s API contract.
- README check: no documentation of old traceback behavior exists, no docs update needed.
- Risk: LOW.

**Decision-tree match this cycle:**

- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 matches).
- ✅ **Active workers from last cycle:** `2a89daa` (testing) status=`null` + `sandbox_status=PAUSED` (last updated 07:56:14Z) → finished. PR slot freed.
- ✅ **PR #105 state** (verified 08:18–08:22Z): `state=OPEN`, `isDraft=false`, `mergeable=MERGEABLE`, `reviewDecision=""`, head `2b823c79e238bed0fd04432c0500398570307729` (matches tested SHA — zero drift). CI: 1 SUCCESS (PR Review by OpenHands/pr-review, 3m16s). Bot review COMMENTED positive earlier. Manual test report present with ✅ PASS.
- ✅ **Docs check N/A — already settled in 07:50Z cycle's testing scope; README has no old-behavior docs to update.** Decision-tree exclusion: "Bug fixes that don't change documented behavior".
- ✅ **Match: PR exists, ready, CI green, docs valid, test results valid, good rating → spawn merge worker.** Exactly the 07:50Z pre-committed action ("If `2a89daa` is `finished` AND a `## Manual Test Results` comment exists on PR #105 with **overall PASS** verdict → spawn **merge worker**.").
- ✅ **Expansion slot:** No unexpanded issues (`gh issue list --jq '[…select … not]'` → `[]`). All open issues either `ready` (#102 in flight, #103 next) or `hold` (#26, #90). Expansion slot idle.
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.

**Merge worker scope (prompt highlights):**

1. Re-verify PR #105 state and head SHA. **Stop if head SHA differs from `2b823c79e238bed0fd04432c0500398570307729`** (would mean drift after testing → re-test).
2. Squash-merge with conventional commit:
   - Subject: `chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension (#102)`
   - Body bullets: (a) two-line CLI handler mirroring sibling ImportError pattern, (b) module-level ValueError contract preserved in `plot_velocity`, (c) one new test `test_cli_chart_unsupported_extension` verifying exit 2 + clean stderr, (d) full unit suite green at 1739 tests.
   - Footer: `Closes #102`.
3. `gh pr merge 105 --squash --delete-branch --subject ... --body ...`.
4. Verify `state=MERGED` and Issue #102 auto-closed.
5. Update WORKLOG.md on main with merge entry.
6. Exit.

**Explicit DO-NOTs in prompt:** no source edits, no fixup pushes, no README/AGENTS.md changes, no re-open, no new follow-up issues (this PR is a clean 2-line scope-complete polish — distinct from PR #104's merge worker which DID file priority-label follow-ups for #102/#103, because those were the actual continuation tickets; PR #105's continuation is just `#103`, which is already labeled and ready), no `priority:*` re-labeling, no other worker spawns.

**Spawn details:**

- `POST /api/v1/app-conversations` with `X-Access-Token: $OPENHANDS_API_KEY`.
- **First two attempts ERRORED** with 500s from the runtime sandbox boot (`Server error '500 Internal Server Error' for url '…prod-runtime…/api/conversations'`) — both used the `plugins: [{source: github, id: jpshackelford/.openhands/plugins/ohtv-workflow, ref: feat/ohtv-workflow-plugin}]` block that prior cycles claimed worked. Service health was OK (this orchestrator conv `29b3f2b5` was running, and 7 of the last 9 conversations were in PAUSED/finished state — no broad outage).
- **Third attempt succeeded** by dropping the `plugins` block entirely. Start task `5435677e…` → `READY` on **first** +8s poll → `app_conversation_id=002d1988f5884fc69dbd88a328aa9ed8`.
- The merge-worker prompt is fully self-contained (gh/git only, no ohtv-workflow plugin skills required), so the missing plugin is non-blocking. **This is a regression from prior cycles' spawn shapes** — flagging for the next orchestrator: the plugin block format may have changed server-side, or the worktree at `feat/ohtv-workflow-plugin` may have broken in a way that crashes sandbox boot. Either way: try-with-plugins-first, fall-back-without-plugins-on-500 is a safe pattern for now.
- Verified `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`, `pr_number=[105]`. Cloud-generated title defaulted to `Conversation 002d1` (request title `[Merge] PR #105 - chore(charts): wrap ValueError as click.UsageError` — same delayed-population pattern as prior cycles).

**Current State (verified 08:18–08:22Z):**

- **Open PRs (1):** [PR #105](https://github.com/jpshackelford/ohtv/pull/105): `oC green ready` 💬1 (manual test report), mergeable, in flight via `002d198`.
- **Ready issues (2):** #102 (in flight via PR #105 — will auto-close on merge), #103 (`priority:low`, `docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars`, next in queue).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged (last 24h):** PR #104 (#87 manifest full cache, 06:54Z 2026-05-27), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Housekeeping note:** WORKLOG.md is at 1367 lines pre-this-entry (~1420 post). Approaching but below the 1500-line trigger restored after the 06:51Z truncation. Next archive likely around the 08:51Z–09:21Z window if the cadence holds.

**Sync note:** `ohtv sync` was skipped this cycle (orchestrator-context-only work; no labeling/analysis depended on fresh sync data). Tools installed via `uv venv` + `uv pip install git+...` inside repo `.venv` (the system `pip install --system` ran into permission errors in this sandbox; venv approach worked cleanly — same finding as the 07:21Z cycle).

**Lessons learned this cycle:**

1. **The 07:50Z pre-commit landed.** Predicted: "If `2a89daa` is `finished` AND a `## Manual Test Results` comment exists on PR #105 with **overall PASS** verdict → spawn **merge worker**." Reality: testing finished at 07:56Z with all 8 blackbox + 1739 unit tests passing, zero drift on head SHA. Seven consecutive cycles of cleanly-fulfilled pre-commits.
2. **Plugin block now causes runtime 500s.** First time in this orchestrator run that the canonical `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin` shape produced runtime errors. Two consecutive 500s with the plugin, instant success without. Either the plugin's `feat/ohtv-workflow-plugin` branch has broken in a way that crashes sandbox boot, OR the API schema changed. The fall-back-without-plugins worked because the prompt is self-contained (gh + git suffice for merge work). **Action for next cycle:** if plugin-shaped spawns continue to 500, may need a `## INSTRUCTION:` from human to investigate the plugin branch state, OR future spawns should default to no-plugins until the plugin issue is resolved.
3. **Tiny PR pipeline cost-justifies itself.** End-to-end for PR #105 (impl 07:21Z → test 07:50Z → merge 08:22Z, ~1 hour wall-clock total) was 3 orchestrator cycles for a 2-line + 1-test fix. ~3 minutes of agent compute total. A human reviewer with merge perms could have done it in 30 seconds. Worth it? The yardstick continues to be: AI-bot review + manual blackbox tests + reproducible CI = regression armor that benefits ALL future ohtv users. For a 2-line CLI error-message change, that's marginally over-engineered, but the cost is bounded and the audit trail is exemplary. Worth-it threshold remains: yes for any PR with user-facing output changes, no for pure refactoring/typo PRs (none of which have come through the pipeline yet).
4. **Plugin missing ≠ worker broken.** The merge-worker prompt enumerates every step in concrete detail (specific commands, specific SHA to verify, specific commit subject/body). Self-contained prompts are robust to plugin removal. Future prompts in this orchestrator's session should remain self-contained as a hedge against the plugin issue persisting.

**Next check (~30 min, ~08:52Z):**

- If `002d198` is `running` → log brief status, no action. Merge workers typically take 3–7 min (PR #104 baseline: ~7 min including issue-filing; this PR is simpler, no follow-ups). Could complete before next wake-up.
- If `002d198` is `finished` AND PR #105 = MERGED AND Issue #102 auto-closed → PR slot empty, but **impl slot has work**: spawn **impl worker for Issue #103** (`docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars`, `priority:low`, `createdAt=2026-05-27T04:53:09Z`). **Pre-committing #103 impl-worker shape now so the 08:52Z cycle doesn't re-derive:** branch off freshly-pulled `main`, follow the expansion comment on #103, target a single PR with either docs-only OR docs+hatch-impl (the issue lets the implementer choose), make sure the implementation choice is documented in PR description. **If plugin spawn still 500s,** fall back to no-plugins (same as this cycle).
- If `002d198` is `finished` BUT PR #105 still OPEN → investigate (drift? merge call failed? CI failed mid-merge? plugin-missing skill failure?). May need `## INSTRUCTION:` from human.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Auto-disable risk this cycle:** Low (productive spawn). Counter stays 0. After #103 merges, the queue empties (#26 + #90 are `hold` for valid external reasons) — expect quiet-period risk in 2–3 cycles thereafter.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 07:50 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `87d0f99` | implementation | Issue #102 → PR #105 | finished ✓ |
| `2a89daa` | testing | PR #105 — chore(charts) UsageError wrap | **NEW** running |

**Spawned: Testing Worker** — `2a89daafb35f4e8caf407b3d445582db` ([conversation](https://app.all-hands.dev/conversations/2a89daafb35f4e8caf407b3d445582db))

Implementation worker `87d0f99` from the 07:21Z cycle completed cleanly. **PR #105 opened at 07:24:08Z** on branch `chore/charts-unsupported-ext-usage-error-102`, head `2b823c7`, 1 commit, 2 files changed (`src/ohtv/cli.py`, `tests/unit/reports/test_cli_chart.py`) — matches the 07:21Z pre-commit exactly. Impl-worker wall-clock: ~7m (07:21Z spawn → 07:28Z `finished`), within the predicted 5–15m envelope.

**Decision-tree match this cycle:**

- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 matches).
- ✅ **Active workers from last cycle:** `87d0f99` (impl) status=`finished` per `/api/v1/app-conversations/search` (last updated 07:28:53Z). PR slot freed.
- ✅ **PR #105 state on inspection** (~07:48Z, ~24m post-open):
  - lxa: `oC green ready 25m 18m ago` — the `C` is lxa's review-bot-COMMENTED tag (not changes-requested; `reviewDecision=""` in `gh pr view`).
  - `isDraft=false`, `state=OPEN`, `mergeable=MERGEABLE`, `reviewDecision=""` (no formal approval, just COMMENTED).
  - CI: both `pr-review` checks green (one SKIPPED legacy, one SUCCESS current — same pattern as PR #104).
  - **AI bot review (`github-actions`, 07:31:16Z) is enthusiastically positive:** "🟢 **Good taste** - Clean, minimal fix that follows existing patterns", "Worth merging", risk LOW. Full body: "Mirrors the adjacent `ImportError → UsageError` pattern / Catches module-level `ValueError` and translates to user-friendly Click error / Preserves the API contract (`plot_velocity` still raises `ValueError`) / Good test coverage verifying exit code, message, and absence of traceback / All 18 chart tests pass." No CHANGES_REQUESTED branch triggered.
  - **No human comments, no manual test report yet.** This is the gating condition.
- ✅ **Docs check — skip docs worker.** Decision tree says spawn docs worker if `README not updated` AND user-facing changes. Per the issue body and #102 expansion: no new commands, no new flags, no changed *documented* behavior — internal error-mapping polish only (the previous behavior was a raw `ValueError` traceback, which README has never documented). Decision-tree exclusion explicitly lists "Bug fixes that don't change documented behavior" — applies here. **Skipped docs worker by policy.**
- ✅ **Match: PR exists, ready, CI green, docs N/A, no manual test results → spawn testing worker.** Even with a glowing bot review, the workflow requires manual blackbox validation before merge. Spawned.
- ✅ **Expansion slot:** No unexpanded issues (`gh issue list … --jq '[…select … not]'` → `[]`). All 4 open issues are either `ready` (#102, #103) or `hold` (#26, #90). Expansion slot idle.
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.

**Testing worker scope (prompt highlights):**

The prompt is unusually detailed for a tiny PR because the new error-handling path has subtle correctness criteria (no traceback in stderr, correct exit code, message wording match) that pytest-only coverage misses unless exercised end-to-end:

1. **Blackbox: happy path** — `uv run ohtv report velocity --chart /tmp/v.png --include-empty` should not trigger the new handler (exit 0 or graceful empty-data exit; matplotlib presence verified implicitly).
2. **Blackbox: the change under test** — `--chart /tmp/v.bogus --include-empty` → exit 2, "unsupported output extension" in stderr, **NO `Traceback`/`ValueError` lines**.
3. **Blackbox: edge cases** — uppercase ext (`.PNG`), no extension (`v`), trailing dot (`v.`). Document actual behavior even if surprising; the issue spec doesn't pre-commit any of these as PASS/FAIL.
4. **Blackbox: `[charts]` extra path** — implicitly via (1); the `ImportError` branch sits next door to the new `ValueError` branch.
5. **Unit suite** — full pytest run. Expect 1739 passing (1738 baseline + 1 new test). Specifically watch `tests/unit/reports/test_cli_chart.py::test_cli_chart_unsupported_extension` (new) AND `tests/unit/reports/test_charts.py::test_unknown_extension_raises` (module-level contract — must still raise plain `ValueError`, not `UsageError`).
6. **Docs spot-check on README.md** — confirm no stale traceback-behavior documentation exists; if found, flag-but-don't-block (would be follow-up issue).
7. **Post structured `## Manual Test Results`** PR comment with SHA `2b823c7`, env details, per-test PASS/FAIL, unit-suite summary, overall verdict.
8. **Exit.** No code edits, no review-thread resolves, no merge, no WORKLOG.md touches.

**Spawn details:**
- `POST /api/v1/app-conversations` with `X-Access-Token: $OPENHANDS_API_KEY` (canonical mechanism, 6 successful cycles now: 04:48Z, 05:18Z, 06:22Z, 06:51Z, 07:21Z, this).
- `pr_number=[105]` set (testing worker, PR-scoped).
- Plugin: `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin`.
- Start task `e419cb6e…` → `READY` on **first** +6s poll → `app_conversation_id=2a89daafb35f4e8caf407b3d445582db`, `sandbox_id=7FHc5TrTW1vGOFKq1XSakl`.
- Verified `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`, `pr_number=[105]`. Cloud-generated title defaulted to `Conversation 2a89d` (request title `[Manual Test] PR #105 - chore(charts): wrap ValueError as click.UsageError` — same delayed-population pattern as prior cycles, no functional impact).

**Current State (verified 07:48–07:50Z):**

- **Open PRs (1):** [PR #105](https://github.com/jpshackelford/ohtv/pull/105): `oC green ready` 💬0, mergeable, bot review COMMENTED (positive), manual testing in flight via `2a89daa`.
- **Ready issues (2):** #102 (in flight via PR #105), #103 (`priority:low`, next in queue once #105 merges).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged (last 24h):** PR #104 (#87 manifest full cache, 06:54Z 2026-05-27), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Housekeeping note:** WORKLOG.md is at 1288 lines pre-this-entry (~1340 post). Below the 1500-line trigger but trending up. Next archive likely around the 08:51Z–09:51Z window if the cadence holds. The skill body says 300 lines but local practice has been 1500 per the 06:51Z entry; sticking with local norm.

**Lessons learned this cycle:**

1. **The 07:21Z pre-commit landed.** The PR materialized on the predicted branch name with the predicted file count and the predicted bot reception. Six consecutive cycles of cleanly-fulfilled pre-commits — this practice continues to compound.
2. **lxa's `C` history code ≠ CHANGES_REQUESTED.** lxa marks PRs `oC` when the PR-review bot has posted a `COMMENTED` review (any review, even glowing ones). The orchestrator must always cross-check with `gh pr view --json reviewDecision` — `""` (no formal decision) on a `COMMENTED`-only review is fine; only `CHANGES_REQUESTED` from a human reviewer triggers the review-worker branch. The decision tree's "💬 > 0" condition needs nuance: bot COMMENTED reviews don't count as actionable comments; only changes-requested or human comments do.
3. **Tiny PRs still benefit from full manual testing.** This PR is 2 lines of code + 1 unit test. The bot review already said "Worth merging". But the new error path is exactly the kind of thing pytest-with-CliRunner can stub silently (e.g., if `obtain_color_for_term` swallows colors differently outside a TTY, or if Click's UsageError rendering changes between versions). Real blackbox `uv run ohtv ...` invocations are the only way to validate the actual user-facing stderr formatting. Resisting the temptation to skip-to-merge here, even when bot review is glowing.
4. **README-update-skip needs explicit rationale in WORKLOG.** First time this cycle the orchestrator skipped a docs worker, and the reasoning was implicit-from-issue-body. Writing the rationale into this WORKLOG entry creates an audit trail in case a future reviewer (or `/orchestrate` author) wants to validate the skip pattern. Pattern: when skipping docs worker, the WORKLOG entry should cite (a) the exclusion clause from the decision tree, and (b) the issue/expansion text that confirms "no documented behavior changes". Doing so here.

**Next check (~30 min, ~08:20Z):**

- If `2a89daa` is `running` → log brief status, no action. Manual testing typically takes 5-15 min for tiny PRs (clone, uv sync, run handful of CLI invocations, full pytest, write comment, post). Could complete before next wake-up.
- If `2a89daa` is `finished` AND a `## Manual Test Results` comment exists on PR #105 with **overall PASS** verdict → spawn **merge worker**. (Pre-committing this branch so the next orchestrator doesn't re-derive: branch name = `chore/charts-unsupported-ext-usage-error-102`, squash commit message should follow conventional-commits `chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension (#102)`, after merge the merge worker should also apply `priority:low` continuation: there's nothing to follow up with on this PR — it's literally a 2-line bug-polish.)
- If `2a89daa` is `finished` AND test results say **FAIL** → spawn **review worker** to address whatever the test report flagged. Review worker should flip PR back to draft, fix, push, flip back to ready.
- If `2a89daa` is `finished` but no test comment posted → investigate the conversation events; may need `## INSTRUCTION:` from human (this would be unusual).
- **Pre-commit further out:** Once PR #105 merges (whether 08:20Z or 08:51Z cycle), the only remaining ready issue is **#103** (`docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars`, `priority:low`, `createdAt=2026-05-27T04:53:09Z`). Pre-committing: next impl-worker target is #103. After #103 lands, the queue empties (#26 and #90 are `hold` — held for valid external reasons per the 06:51Z notes; expect quiet-period risk to materialize then). The orchestrator should be alert: 2 cycles of "All quiet" after #103 merges → auto-disable per the skill's documented logic.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Auto-disable risk:** Low this cycle (productive spawn). Counter remains 0.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 07:30 UTC - Implementation Worker [102]

Implemented Issue [#102 — chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension](https://github.com/jpshackelford/ohtv/issues/102). Pure UX polish from PR #101 manual test report — unsupported `--chart` extension (e.g. `.txt` or no extension) now produces a single-line `Error: …` Click usage message (exit 2) instead of a raw 20-line `ValueError` traceback (exit 1).

**Files touched (2):**

- `src/ohtv/cli.py` — added 2-line `except ValueError as exc: raise click.UsageError(str(exc)) from exc` branch immediately after the existing `except ImportError` handler around the `plot_velocity(...)` call.
- `tests/unit/reports/test_cli_chart.py` — added `test_cli_chart_unsupported_extension` (one CLI test, modeled on C-3 `test_cli_chart_missing_matplotlib`).

**Intentionally NOT touched:** `src/ohtv/reports/charts.py` (module-level `ValueError` contract preserved) and `tests/unit/reports/test_charts.py::test_unknown_extension_raises` (still asserts the raw `ValueError` — that is the module-level contract; only the CLI's reaction to it was polished).

**Verification:**

- `uv run pytest tests/unit/reports/test_cli_chart.py tests/unit/reports/test_charts.py -v` → 18 passed (including the new `test_cli_chart_unsupported_extension` and the preserved `test_unknown_extension_raises`).
- `uv run pytest -q` → 1739 passed (1738 baseline + 1 new test, as the expansion comment predicted).
- `uv run ruff check src/ohtv/cli.py tests/unit/reports/test_cli_chart.py` → 78 pre-existing warnings, **0 new** on the 2 added lines or the new test (per orchestrator instructions, unrelated ruff debt left untouched).

**PR:** [#105 — chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension](https://github.com/jpshackelford/ohtv/pull/105) (branch `chore/charts-unsupported-ext-usage-error-102`). Opened as draft, then marked ready-for-review. The repo's `PR Review by OpenHands` workflow ran with `conclusion=skipped` on the draft-open trigger; marking the PR ready re-arms it for the orchestrator's next cycle. Awaiting orchestrator (testing-worker spawn + AI code review).

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 07:21 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `7b39f85` | merge | PR #104 — Manifest full cache (#87) | finished ✓ |
| `87d0f99` | implementation | Issue #102 — chore(charts) UsageError wrap | **NEW** running |

**Spawned: Implementation Worker** — `87d0f99232164bffb973f18508d6d60c` ([conversation](https://app.all-hands.dev/conversations/87d0f99232164bffb973f18508d6d60c))

Merge worker `7b39f85` from the 06:51Z cycle completed cleanly. PR #104 squash-merged at **06:54:41Z** (head `0d8be62` matched tested SHA — no drift), Issue #87 auto-closed via `Closes #87`, and `priority:low` labels applied to both #102 and #103 as predicted in the 06:51Z pre-commit. End-to-end merge wall-clock ≈ 4 min (faster than the `91ed7ea` baseline of ~7 min — merge worker had less side-work since priority-labeling for 2 issues is cheaper than filing 2 new issues like `91ed7ea` did).

**Decision-tree match this cycle:**

- ✅ **PR slot empty on wake-up:** Merge finished, no open PR exists, all prior PR-slot workers PAUSED.
- ✅ **No open PRs** (`gh pr list --state open` → `[]`).
- ✅ **Ready issues with priority labels exist:** #102 (priority:low, `createdAt=2026-05-27T04:52:59Z`), #103 (priority:low, `createdAt=2026-05-27T04:53:09Z`). Both received their priority labels from the merge worker this cycle. **#102 wins the tiebreak by 10 seconds** of older `createdAt` — matches the 06:51Z pre-committed action exactly.
- ✅ **Expansion slot has no work:** All open issues either have `ready` (#102, #103) or `hold` (#26, #90). Zero unexpanded issues. Expansion slot idle.
- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 matches; only historical refs in old orchestrator entries).
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.
- ✅ **Pre-committed action match:** The 06:51Z entry pre-committed: "If `7b39f85` is `finished` AND PR #104 = MERGED AND #102/#103 have `priority:low` labels → ... spawn **impl worker** for whichever of #102/#103 has the older `created_at` (#102 was filed first on 04:52:59Z)." This spawn is that exact action — zero re-derivation needed at 07:21Z, just verification.

**Impl worker scope (prompt highlights):**

The expansion comment on Issue #102 is unusually precise (it was written today at 05:23Z by `761e1d9` — verified against `main` SHA `ae36f750…` which is two PRs behind current `main` `c0561b8…` post-#104 merge, so the impl worker is explicitly instructed to re-locate the target block by search rather than by line number):

1. **Two-line code change** in `src/ohtv/cli.py`: add `except ValueError as exc: raise click.UsageError(str(exc)) from exc` next to the existing `except ImportError` handler in the `report velocity` `--chart` block. The matplotlib `ImportError → UsageError` mapping immediately below is the template to mirror.
2. **One new CLI test** in `tests/unit/reports/test_cli_chart.py` — modeled on `test_cli_chart_missing_matplotlib` (C-3). Exit code 2, no traceback, "unsupported output extension" in output. Test body is included verbatim in the expansion comment.
3. **Hard DO-NOTs:** no edits to `src/ohtv/reports/charts.py` (module-level `ValueError` contract is intentional), no edits to `tests/unit/reports/test_charts.py::test_unknown_extension_raises` (validates that contract), no new test files (use existing `test_cli_chart.py`), no README.md changes (no documented behavior changes — this is internal error-mapping polish), no pre-existing-ruff-warning fixups (out of scope per PR #104 testing-worker notes), no `ready` label on follow-ups, no other worker spawns.
4. **Process:** branch `chore/charts-unsupported-ext-usage-error-102` (or similar) off freshly-pulled `main`; focused test → full pytest (expect 1739 passing, up from 1738 post-#87); ruff clean on changed files only; draft PR with `Fixes #102`; wait for AI-bot review (~2-3 min); flip draft→ready; log to WORKLOG.md on main; exit.

**Spawn details:**
- `POST /api/v1/app-conversations` with `X-Access-Token: $OPENHANDS_API_KEY` (per openhands-api skill — canonical mechanism used in 04:48Z, 05:18Z, 06:22Z, 06:51Z cycles, all successful).
- Payload schema: `initial_message.content[{type:text, text:...}]` + plugin block `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin`. **No `pr_number` set** — correct, since no PR exists yet for #102; the impl worker creates the PR and future cycles will see `pr_number` populated automatically.
- Start task `2a9e66b5…` → `READY` on **first** +6s poll → `app_conversation_id=87d0f99232164bffb973f18508d6d60c`.
- Verified `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`. Cloud-generated title defaulted to short form `Conversation 87d0f` (request title was descriptive `[Implementation] Issue #102 - chore(charts): wrap ValueError as click.UsageError` — non-issue, no functional impact, same delayed-population pattern as prior cycles).

**Current State (verified 07:18–07:21Z):**

- **Open PRs:** 0 (PR #104 merged 06:54:41Z; impl worker for #102 will open one shortly).
- **Ready issues (2):** #102 (`priority:low`, in flight via `87d0f99`), #103 (`priority:low`, next in queue after #102 PR merges or once impl slot frees).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged (last 24h):** PR #104 (#87 manifest full cache, 06:54Z 2026-05-27), PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Housekeeping note:** WORKLOG.md is at 1189 lines pre-this-entry (~1240 post). Comfortably below the 1500-line trigger restored after the 06:51Z truncation. No archive needed this cycle. Next archive likely around the 08:51Z–09:21Z cycle if work continues at the current pace.

**Sync note:** `OH_API_KEY=$OPENHANDS_API_KEY ohtv sync --since 2026-05-27T03:16:* --quiet` completed cleanly. Tools installed via `uv venv` + `uv pip install` inside repo `.venv` (the system Python `pip install` and `pip install --system` both ran into permission errors in this sandbox; the venv approach worked cleanly).

**Lessons learned this cycle:**

1. **The 06:51Z pre-commit was end-to-end correct.** Both branches of the pre-committed decision tree ("if merged + priority labels → spawn impl for #102") matched reality bit-for-bit. Pre-committing concrete next-cycle actions in WORKLOG entries continues to be the orchestrator's compounding asset — five consecutive cycles (04:48Z, 05:18Z, 06:22Z, 06:51Z, this) have hit their pre-committed predictions cleanly.
2. **Merge worker with simple label follow-ups is fast** — ~4 min wall-clock vs ~7 min when filing new issues (`91ed7ea` baseline). Updated mental model: merge-with-label-only ≈ 3–5 min; merge-with-issue-filing ≈ 5–10 min; merge-only ≈ <1 min. Useful for predicting cycle cadence.
3. **Tiny issues are worth running through the full pipeline.** #102 is a 2-line + 1-test change; the issue could plausibly have been merged with a manual one-liner. But running it through impl→test→review→merge gives the AI-bot review another data point AND keeps the worklog/PR-history machinery exercised AND ensures regression protection. Cost is ~1-2 orchestrator cycles vs ~30 sec of human time. Worth it.
4. **Expansion comments aging out of SHA-relevance.** The #102 expansion was written at 05:23Z against `main` SHA `ae36f750…`; main has moved past it via PR #104 merge at 06:54Z. The impl worker's prompt explicitly calls this out and tells it to re-locate the target block by searching for the matplotlib `ImportError` handler rather than by line numbers. Future expansions for tiny issues should perhaps cite anchor strings (function names, distinctive imports) rather than just line ranges, since cycle-to-cycle main churn can shift line numbers by tens.

**Next check (~30 min, ~07:51Z):**

- If `87d0f99` is `running` → log status briefly, no action. Tiny PRs typically take 5-15 min for impl workers (set up env, edit 2 files, run tests, push, open PR, wait for bot review, flip to ready). Could complete before next wake-up.
- If `87d0f99` is `finished` AND a new PR exists (likely `chore/charts-unsupported-ext-usage-error-102` branch) → check PR state per decision tree:
  - PR draft + bot review pending → wait one more cycle.
  - PR ready + bot review COMMENTED (positive) + no test results → spawn **testing worker** (this is a tiny change, but tests still gate review per skill).
  - PR ready + bot review CHANGES_REQUESTED → spawn **review worker** (fix the bot's blockers first).
- If `87d0f99` is `finished` BUT no PR exists → investigate conversation events; may need `## INSTRUCTION:` from human.
- If `87d0f99` is `finished` AND the PR is open AND testing AND merge complete before next wake-up (unlikely but possible for ultra-tiny PRs) → next available work is **impl worker for #103** (the only remaining ready issue), same `priority:low`. **Pre-committing the next-next spawn shape here so the 07:51Z (or 08:21Z) orchestrator doesn't need to re-derive: spawn impl worker for #103 if/when PR #102 reaches MERGED state and expansion/PR slots both have nothing else.**
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Auto-disable risk:** Low this cycle (productive spawn). Counter remains 0. The pipeline has at least one more cycle of work (testing/merge of #102 PR) before #103 enters the queue and then nothing-ready-after-#103-merges (#26 and #90 are both `hold`). So expect potentially 2-3 cycles before quiet-period risk materializes.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 06:54 UTC - Merge Worker (PR #104)

**PR merged ✅**

- PR: [#104 — feat: manifest as full cloud metadata cache (#87)](https://github.com/jpshackelford/ohtv/pull/104) (state=MERGED, mergedAt=2026-05-27T06:54:41Z, branch `feat/manifest-full-cache-87` deleted)
- Squash commit: [`d3d3f9cc`](https://github.com/jpshackelford/ohtv/commit/d3d3f9ccd028b5c1d32830b319f40c4d044fac60) — `feat(sync): manifest as full cloud metadata cache (#87)`
- Issue [#87 — Manifest as full cloud metadata cache](https://github.com/jpshackelford/ohtv/issues/87) **closed** at 06:54:42Z (auto-closed by `Closes #87` in squash-commit footer).

**Pre-merge verification:**

- ✅ HEAD drift check: `gh pr view 104 --json headRefOid --jq .headRefOid` → `0d8be6204b01c323e284ef678f83a17f558016fa` (matched expected, no drift). Re-checked immediately before invoking `gh pr merge` — still matched.
- ✅ Mergeable: `state=OPEN` / `mergeable=MERGEABLE` / `isDraft=false`.
- ✅ Manual test report (06:27:44Z, [comment 4551614957](https://github.com/jpshackelford/ohtv/pull/104#issuecomment-4551614957) by testing worker `5ecbdb7`): all 8 Issue #87 ACs satisfied including the headline cold-start zero-read property (verified both by `Path.read_text` monkeypatch unit test and a blackbox poisoned-JSON scan); 1738/1738 pytest pass (1688 baseline + 50 new); 0 unresolved review threads.
- ✅ AI code-review bot (05:46:42Z): COMMENTED (positive informational, not CHANGES_REQUESTED).
- ✅ Docs in-diff: README.md (+26/-12) and AGENTS.md (+7/-4) updated; docs-update follow-up comment by @jpshackelford at 05:59:11Z.

**Squash-merge commit body** (delivered via `--body`, not co-author trailer per instructions):

> - Extends sync_manifest entries with `selected_repository`, `selected_branch`, and `created_at` (additive schema; pre-#87 manifests still load).
> - Cold-start scanner skips `base_state.json` entirely for cloud convs whose manifest entry is fully populated; local CLI convs unchanged. Regression test asserts zero `Path.read_text` calls on the file.
> - `sync --update-metadata` refreshes the new fields except `selected_branch` — the cloud listing API does not return it; it can only change via a full trajectory re-download.
> - `sync --repair --fix` rebuilds orphaned manifest entries from one shared cloud-listing fetch with null-filled fallback when there is no API key or the listing call fails.
> - Widens `ConversationStore.update_metadata` to accept `selected_repository` and `created_at` with `_UNSET` sentinel semantics distinguishing "leave unchanged" from "clear". `created_at` requires `datetime` (or `None`); raw strings raise `TypeError`.
> - Introduces `MetadataDiff` dataclass replacing the legacy `(title_changed, labels_changed)` tuple; carries per-field booleans and new values to avoid re-normalization in the update path.
> - +50 new tests across scanner / store / sync (1688 → 1738 green); 8/8 AC verified including the headline cold-start zero-read property.
>
> Closes #87

**Priority labels applied to remaining ready follow-ups** (per orchestrator pre-commitment):

- [#102 — chore(charts): wrap ValueError as click.UsageError](https://github.com/jpshackelford/ohtv/issues/102) → added `priority:low`. Labels now: `ready`, `priority:low`.
- [#103 — docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars](https://github.com/jpshackelford/ohtv/issues/103) → added `priority:low`. Labels now: `ready`, `priority:low`.

Both are minor cosmetic follow-ups to the merged PR #101 charting work; neither is on the critical path for any upcoming PR.

**Non-blocking notes from the test report (deliberately not addressed in this PR):**

- 🟡 Pre-existing ruff debt on touched files (80 errors; `origin/main` has 81 — PR fixed 1). Mostly `F401` unused-imports in `cli.py`.
- 🟡 Click `--help` text for `--update-metadata` still says "title + labels"; README + AGENTS.md are fully updated. Per orchestrator instructions, this is left as a future follow-up — **no new issue filed** (no `ready` label per worker rules; expansion worker can pick this up if desired in a later cycle).

**Anomalies:** None. Clean merge.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 06:51 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `5ecbdb7` | testing | PR #104 — Manifest full cache (#87) | finished ✓ |
| `7b39f85` | merge | PR #104 — Manifest full cache (#87) | **NEW** running |

**Spawned: Merge Worker** — `7b39f85626f44bf694772d7299ccb08a` ([conversation](https://app.all-hands.dev/conversations/7b39f85626f44bf694772d7299ccb08a))

Testing worker `5ecbdb7` from the 06:22Z cycle completed cleanly. Its [test report](https://github.com/jpshackelford/ohtv/pull/104#issuecomment-) posted at 06:27:44Z (~5 min after spawn) returned **Verdict: ✅ Ready to merge** with 2 cosmetic 🟡 notes (pre-existing ruff debt, Click `--help` text drift) — neither blocking. All 1738 tests pass; all 8 Issue #87 ACs verified (including headline cold-start zero-read property confirmed by both a `Path.read_text` monkeypatch unit test AND a blackbox poisoned-JSON scan).

**Decision-tree match this cycle:**

- ✅ **PR slot empty on wake-up:** No other PR-slot workers running (`5ecbdb7` testing finished; `56b491f` impl, `761e1d9` expansion, `91ed7ea` merge all `null`/paused).
- ✅ **"PR exists, ready, CI green (no failing checks — only AI-bot review = COMMENTED informational), docs valid (README+AGENTS.md in diff + author docs-update comment at 05:59Z), test results valid (06:27Z), good rating (✅ Ready to merge), 0 unresolved review threads → Spawn merge worker."** Exact match.
- ✅ **Expansion slot has no work:** All 4 remaining open issues are either `ready` (#87, #102, #103) or `hold` (#26, #90). No issues need expansion this cycle.
- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (only historical refs in archived entries).
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.
- ✅ **Pre-committed action match:** The 06:22Z entry pre-committed: "If `5ecbdb7` is `finished` AND test report shows ✅ **Ready to merge** → spawn **merge worker** for PR #104. ... Merge worker should ALSO add `priority:*` labels to #102 and #103". This spawn implements that exact prediction.

**Merge worker scope (prompt highlights):**

1. **Drift check (HARD-BLOCK):** `gh pr view 104 --json headRefOid` must equal `0d8be6204b01c323e284ef678f83a17f558016fa` (matches tested SHA). Bail if drift detected.
2. Re-verify `state=OPEN`, `mergeable=MERGEABLE`, not draft.
3. Study full diff + read manual test report + Issue #87 ACs.
4. Update PR description to reflect final state.
5. Craft conventional commit: `feat(sync): manifest as full cloud metadata cache (#87)` with 7 body bullets covering manifest schema extension, cold-start zero-read, `--update-metadata` field coverage, `--repair --fix` shared-listing fetch, `ConversationStore.update_metadata` widening, `MetadataDiff` dataclass, +50 tests. Footer: `Closes #87`.
6. `gh pr merge 104 --squash --subject ... --body ... --delete-branch`.
7. Verify `state=MERGED` and Issue #87 auto-closed.
8. **Apply `priority:low` to Issues #102 and #103** (the two remaining `ready` issues, both follow-ups to the merged PR #101 charting work — neither on the critical path).
9. Update WORKLOG.md on main with merge entry.
10. Exit.

**Explicit DO-NOTs in prompt:** no source edits, no fixup pushes, no README/AGENTS.md changes (the cosmetic Click `--help` drift is out-of-scope follow-up material), no re-open, no `ready` label on any new follow-up issue, no other spawns.

**Spawn details:**
- `POST /api/v1/app-conversations` with `X-Access-Token` header (per openhands-api skill — same mechanism used in 04:48Z and 05:18Z cycles successfully).
- Payload schema: `initial_message.content[{type:text, text:...}]` + plugin block `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin` + `pr_number: [104]`.
- Start task `6e11f521…` → `READY` on first +6s poll → `app_conversation_id=7b39f85626f44bf694772d7299ccb08a`.
- Verified `execution_status=running`, `sandbox_status=RUNNING`. (Title and `selected_repository` came back null/empty in the conversation listing — same delayed-population pattern observed in prior cycles, non-issue; the spawn payload set both correctly.)

**Current State (verified 06:46–06:51Z):**

- **Open PRs:** 1 — [PR #104 — feat: manifest as full cloud metadata cache (#87)](https://github.com/jpshackelford/ohtv/pull/104) (ready, MERGEABLE, head `0d8be62`, merge in flight via `7b39f85`).
- **Ready issues (3, awaiting priority):** #87 (in flight via PR #104 — will auto-close on merge), #102 (`chore(charts): wrap ValueError as click.UsageError`), #103 (`docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars`). Neither #102 nor #103 has a `priority:*` label yet — merge worker will add `priority:low` to both.
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged:** PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z 2026-05-27), PR #99 (#83 classify, 01:22Z), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Housekeeping completed this cycle:** WORKLOG.md was 1589 lines on wake-up — 4 cycles overdue. Ran `/truncate-worklog` algorithm (6-hour productive-span retention): archived 7 orchestrator entries from 2026-05-26 19:51Z–22:51Z to `WORKLOG_ARCHIVE_2026-05-26.md` (now 1811 lines total in archive). WORKLOG.md trimmed to 1069 lines pre-this-entry (~33% reduction). The cutoff was computed as 23:51Z 2026-05-26 — keeps the 26-May 23:51Z orchestrator entry and everything 27-May. Worker entries at the top of the file (#82 impl 04:09Z, PR #101 merge 04:52Z, #102 expansion 05:23Z, #87 impl 05:55Z) all stayed (well within the 6h window).

**Sync note:** `OH_API_KEY=$OPENHANDS_API_KEY ohtv sync --since 2026-05-27T02:46:* --quiet` completed cleanly. Tools installed via `uv tool install` to `~/.local/bin` (system pip rejected for system Python; uv-tool venvs work without elevation).

**Lessons learned this cycle:**

1. **Truncation paid off immediately.** With WORKLOG.md down from 1589 → 1069 lines (+ this entry pushing to ~1170), the next cycle's context will be ~30% smaller and the 6h productive-span retention rule means the kept content is all still on-topic. Hard-block deferred-housekeeping items DO eventually need to be honored — this cycle proved it costs roughly the same wall-clock as a worker spawn (a few hundred lines of script + git commit), so future overdue housekeeping should be done at the FIRST cycle that has only one spawn (not deferred further).
2. **Two-stage worklog parsing.** The file has no `## Log` marker, and entries are interleaved (workers insert at top, orchestrators append at bottom), so the truncate skill's default header-split-then-parse approach needed adjustment. The fix: parse all `^### YYYY-MM-DD HH:MM` headers in the file irrespective of position, then rewrite in original file order. The skill's reference implementation should probably be updated to handle the marker-less case, but the workaround is straightforward.
3. **Pre-committed merge-spawn worked first try.** The 06:22Z entry pre-committed this exact spawn shape (testing finished + Ready-to-merge verdict → merge worker). No re-derivation at 06:51Z needed; just verify the test report's verdict text and spawn. Pre-committing concrete next-cycle actions continues to pay off.

**Next check (~30 min, ~07:21Z):**

- If `7b39f85` is `running` → log status briefly, no action. Merge with follow-up label-application typically takes 5–10 min (per the 04:52Z `91ed7ea` baseline which did merge + 2 issue-filings in ~7 min).
- If `7b39f85` is `finished` AND PR #104 = MERGED AND #102/#103 have `priority:low` labels → PR slot empty, expansion slot has nothing to do (no unexpanded issues), but **impl slot has work**: spawn **impl worker** for whichever of #102/#103 has the older `created_at` (#102 was filed first on 04:52:59Z). Both are `priority:low` — pick the older one.
- If `7b39f85` is `finished` BUT PR #104 still OPEN → investigate (drift? merge call failed? CI failed mid-merge?). May need `## INSTRUCTION:` from human.
- If `7b39f85` is `finished` AND PR #104 merged but priority labels NOT applied to #102/#103 → run `/assess-priority` inline, label them, then spawn impl worker for the older one.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 06:22 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `56b491f` | implementation | Issue #87 → PR #104 | finished ✓ |
| `761e1d9` | expansion | Issues #102 + #103 | finished ✓ |
| `5ecbdb7` | testing | PR #104 — Manifest full cache (#87) | **NEW** running |

**Spawned: Testing Worker** — `5ecbdb7c026745ab9b00e1399be1d1e8` ([conversation](https://app.all-hands.dev/conversations/5ecbdb7c026745ab9b00e1399be1d1e8))

Both previously-spawned workers from the 05:18Z cycle completed cleanly:
- **`56b491f` impl worker (#87):** Created [PR #104](https://github.com/jpshackelford/ohtv/pull/104) at 05:39:38Z. Final commit 05:57:06Z. Head SHA `0d8be62…`. State: open, ready (not draft), MERGEABLE, AI-bot review COMMENTED (positive informational at 05:46:42Z). PR body claims **+50 new tests (1738 total)** across scanner / store / sync. Author already posted a "Documentation updated for: …" comment at 05:59:11Z noting README covers `--update-metadata` widening AND the `selected_branch` not-refreshed caveat. README.md is in the diff. AGENTS.md is in the diff.
- **`761e1d9` expansion worker:** Spawned for #102 but also handled #103 (excellent initiative). Both issues now have `ready` label + `## Technical Approach` comments. #102 comment at 05:23:28Z; #103 comment at 05:57:16Z (later — clearly a second pass after finishing #102).

**Decision-tree match this cycle:**

- ✅ **PR slot empty on wake-up:** No other PR-slot workers running (`91ed7ea` merge, `19dfec8` testing, etc. all PAUSED).
- ✅ **PR exists, ready, CI green (no CI configured — only `pr-review.yml` workflow which already ran as github-actions COMMENTED review), docs updated (README+AGENTS.md in diff + author docs-update comment), no manual test results comment yet → Spawn testing worker.** Exact match.
- ✅ **Expansion slot has no work:** All open issues either have `ready` (#87 → now in PR #104, #102, #103) or `hold` (#26, #90). No issues need expansion this cycle.
- ✅ **No `## INSTRUCTION:` in WORKLOG.md** (`grep -nE '^## INSTRUCTION:' WORKLOG.md` → 0 matches; all historical references are in old orchestrator entries and already acknowledged).
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.

**Testing worker scope (prompt highlights):**

1. **Drift check:** Verify `git rev-parse HEAD` matches `0d8be6204b01c323e284ef678f83a17f558016fa` after `gh pr checkout 104`. Note any drift in the report.
2. **T-0 full pytest:** Expect **1738 passing** (1688 baseline post-#82 merge + 50 new in this PR).
3. **T-0 focused new-test runs:** `tests/unit/db/test_scanner.py` (+18, esp. cold-start zero-read regression), `tests/unit/db/stores/test_conversation_store.py` (+10), `tests/unit/test_sync.py` (+22).
4. **T-1 manifest schema additivity:** Verify pre-#87 entries load with key-absent (not key-present-None) semantics — load-bearing for the fallback signal.
5. **T-2 cold-start scanner zero-`base_state.json`-open** for cloud convs (headline AC). Whitebox: study the regression test. Blackbox: `strace -e trace=openat` on a real `ohtv db scan` if feasible.
6. **T-3 local CLI convs unchanged:** strace should still show `base_state.json` opens for local-only convs.
7. **T-4 `--update-metadata` refreshes repo + created_at but NOT selected_branch** (listing endpoint doesn't return it; documented in code + PR body).
8. **T-5 MetadataDiff dataclass:** confirm no leftover tuple-unpack callers.
9. **T-6 `repair --fix` shared-listing fetch + null fallback** for orphans without API key.
10. **T-7 CLI counter display:** `_show_metadata_result` only prints new counters when nonzero.
11. **T-8 ruff clean** on all modified files.
12. **T-9 README + AGENTS.md spot-check** with copy-paste of new examples.
13. **T-10 backward-compat blackbox** against pre-#87 manifest.

Report header MUST be `## Manual Test Results — PR #104`. Recommendation must be one of: **Ready to merge** / **Needs review round** / **Blocked**. **Read-only worker:** no commits, no pushes, no review-thread resolves, no draft toggles, no merges, no further spawns.

**Spawn details:**
- `POST /api/v1/app-conversations` with `X-Access-Token` header (per openhands-api skill).
- Payload schema: `initial_message.content[{type:text, text:...}]` + plugin `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin` + `pr_number: [104]` (so testing worker has PR context bound).
- Start task `28833dbd…` → `READY` on first +12s poll → `app_conversation_id=5ecbdb7c026745ab9b00e1399be1d1e8`.
- Verified `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`, `pr_number=[104]`. Cloud-generated title defaulted to `Conversation 5ecbd` (request title was descriptive — non-issue).

**Current State (verified 06:18–06:22Z):**

- **Open PRs:** 1 — [PR #104 — feat: manifest as full cloud metadata cache (#87)](https://github.com/jpshackelford/ohtv/pull/104) (ready, MERGEABLE, AI-bot COMMENTED, docs updated, testing in flight via `5ecbdb7`).
- **Ready issues (3):** #87 (now in flight via PR #104 — will auto-close on merge), #102 (`chore(charts): wrap ValueError as click.UsageError`), #103 (`docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars`). Neither #102 nor #103 has a `priority:*` label yet.
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged:** PR #101 (#82 charts, 04:52Z 2026-05-27), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Note on #87 acceptance criteria coverage:** PR body lists 8 ACs all checked. The testing worker should validate each — particularly AC #8 (cold-start zero-`base_state.json` regression test), which is the load-bearing performance/architecture guarantee for this PR.

**Sync note:** `OH_API_KEY=$OPENHANDS_API_KEY ohtv sync --since 2026-05-27T02:22:* --quiet` completed cleanly. Tools installed via `pip install --break-system-packages` to `/home/openhands/.local/bin`.

**Housekeeping deferred AGAIN (now 4 cycles overdue):** WORKLOG.md is now **~1600 lines** after this entry — has crossed the 1500-line trigger. The 19:19Z–22:51Z 2026-05-26 block (lines ~9–~660, ~650 lines, all >7 hours old, completely unrelated to in-flight #87 testing or post-merge #102/#103 work) is overdue for archive to `WORKLOG_ARCHIVE_2026-05-26.md`. Deferred this cycle because the testing spawn is the priority action (PR #104 is waiting to be tested before it can merge). **Pre-commit:** if next cycle (~06:52Z) is quiet (testing worker still running, nothing else to spawn), **run `/truncate-worklog` as the cycle's primary action** — no spawning, just housekeeping.

**Lessons learned this cycle:**

1. **Expansion worker over-delivered.** `761e1d9` was spawned for #102 only, but went on to expand #103 in the same conversation (5:23Z #102 comment, 5:57Z #103 comment, both with `ready` labels added). This saved one orchestrator cycle. The expansion prompt was generic enough ("expand this issue") that the worker reasonably extended to a similar adjacent issue. Worth noting: future expansion prompts could explicitly say "expand ONLY this issue" if we want strict scope, but the bonus expansion here was net-positive.
2. **No CI workflows configured for code tests** — only the AI `pr-review.yml` runs. This has been the steady state since at least PR #98. The decision tree's "CI green" condition is therefore vacuously true (no failing checks possible). Manual testing carries the full verification load — making the testing worker mandatory and load-bearing.
3. **Pre-committed two-slot spawn pattern keeps paying off.** The 05:18Z entry pre-committed both spawns (impl #87 + exp #102), both finished within the expected 30-60 min window, and the resulting state matched exactly what the orchestrator predicted ("if 56b491f finished AND a new PR exists … spawn testing worker"). Pre-commits are the orchestrator's compounding asset.

**Next check (~30 min, ~06:52Z):**

- If `5ecbdb7` is `running` → log status briefly, no action. **Run housekeeping (`/truncate-worklog`) this cycle if it's otherwise quiet** — the 1500-line trigger is now active and the 26 May 19:19Z–22:51Z block is 4 cycles overdue.
- If `5ecbdb7` is `finished` AND test report shows ✅ **Ready to merge** → spawn **merge worker** for PR #104. AI bot review is already positive (COMMENTED, not CHANGES_REQUESTED); the 1 PR comment is the docs-update note (already addressed by the PR itself, not a review thread requiring reply). Merge worker should ALSO add `priority:*` labels to #102 and #103 since they're the only remaining ready issues (or the next orchestrator cycle can run `/assess-priority` inline).
- If `5ecbdb7` is `finished` AND test report shows 🔴/🟡 with ❌ blockers → spawn **review worker** (fix-then-re-test loop).
- If `5ecbdb7` is `finished` AND test report shows ⚠️ minor nits only → spawn **review worker** to fold in fixes, then re-test on the cycle after.
- If `5ecbdb7` is `finished` BUT no test comment was posted → investigate conversation events; may need a `## INSTRUCTION:` from human.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Archive TO-DO (hard-block next cycle):** 19:19Z–22:51Z 2026-05-26 block → `WORKLOG_ARCHIVE_2026-05-26.md`. Cannot defer again — file size will keep growing each cycle until done.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 05:55 UTC - Impl Worker (#87)

Implemented Issue [#87 — manifest as full cloud metadata cache](https://github.com/jpshackelford/ohtv/issues/87) as a direct follow-up to PR #94 / Issue #86. Extends the manifest schema with `selected_repository`/`selected_branch`/`created_at`; `db scanner.extract_metadata` now skips `base_state.json` for cloud convs with fully-populated manifest entries (regression test enforces zero opens); `sync --update-metadata` refreshes the new fields (except `selected_branch`, which is not in the listing API); `sync --repair --fix` rebuilds orphans from listing payload. Widened `ConversationStore.update_metadata` with `selected_repository`/`created_at` kwargs (sentinel semantics). 1738 tests green (+50). PR [#104 — feat: manifest as full cloud metadata cache (#87)](https://github.com/jpshackelford/ohtv/pull/104) opened, marked ready.

---

### 2026-05-27 05:23 UTC - Expansion Worker (#102)

✅ **Expanded Issue [#102 — chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension](https://github.com/jpshackelford/ohtv/issues/102)** — bug-polish nit from the PR #101 manual test report. Verified the bug reproduces on `main@ae36f750` (raw `ValueError` traceback, exit 1) and that the issue body's suggested fix is sound. Posted a [technical-approach comment](https://github.com/jpshackelford/ohtv/issues/102#issuecomment-4551583425) with the verified call-site lines (`src/ohtv/cli.py:10663-10673`, `src/ohtv/reports/charts.py:128`), the exact 2-line `except ValueError → click.UsageError` diff, and a small CLI test to add alongside `test_cli_chart_missing_matplotlib` (the issue's reference to "tighten an existing test in `test_cli_chart.py`" was slightly off — that file has no unsupported-extension test today; the module-level one in `test_charts.py` should stay as-is). Labeled `ready`. Suggested `priority:low` (deferred to next `/assess-priority` cycle alongside #103).

---

### 2026-05-27 05:18 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `91ed7ea` | merge | PR #101 — `--chart` flag | finished ✓ |
| `56b491f` | implementation | Issue #87 — Manifest full cloud metadata cache | **NEW** running |
| `761e1d9` | expansion | Issue #102 — Wrap ValueError as click.UsageError | **NEW** running |

**Spawned: 2 Workers (parallel)** — both PR slot + Expansion slot filled

1. **Implementation Worker** — `56b491fcd5274e4db210df295a9e5037` ([conversation](https://app.all-hands.dev/conversations/56b491fcd5274e4db210df295a9e5037))
   - Issue: [#87 — Manifest as full cloud metadata cache](https://github.com/jpshackelford/ohtv/issues/87) (`priority:low`, `ready`)
   - Only remaining `ready` issue post #82 merge. Direct follow-up to PR #94 / Issue #86 (AGENTS.md item #27) — extends the manifest from `title`/`labels` to `selected_repository`, `selected_branch`, `created_at`.
2. **Expansion Worker** — `761e1d90ee70494ea3a4de65dbf963a6` ([conversation](https://app.all-hands.dev/conversations/761e1d90ee70494ea3a4de65dbf963a6))
   - Issue: [#102 — chore(charts): wrap ValueError as click.UsageError](https://github.com/jpshackelford/ohtv/issues/102) (no labels yet)
   - Oldest of the two follow-up issues filed by merge worker `91ed7ea` (#102 at 04:52:59Z; #103 at 04:53:09Z). Body is already well-formed (Context/Problem/Repro/Expected/Suggested fix), so the expansion job is lighter — verify + add a sharp technical-approach comment + add `ready` label.

**Decision-tree match this cycle:**

- ✅ **Merge worker `91ed7ea` finished cleanly:** Sandbox `PAUSED` at 04:55:21Z (~7 minutes after spawn). PR #101 `state=MERGED`, `mergedAt=04:52:14Z` (merged 3 minutes into the worker run). Issue #82 auto-closed at 04:52:15Z via `Closes #82` in PR body. Two follow-up issues filed (#102, #103) as instructed. Excellent worker discipline — exact match to the 04:48Z spawn prompt; no fixup commits, no scope creep.
- ✅ **PR slot empty on wake-up:** No open PRs. Only this orchestrator conv `7894926` was `running` at 05:16Z; all prior PR-slot workers (`91ed7ea` merge, `19dfec8` testing, `0ba9415f` merge #100, `d9a994e` prior orchestrator, `03c344bf` merge #97, etc.) all `PAUSED`/`finished`.
- ✅ **Expansion slot empty:** No expansion worker running.
- ✅ **Both slots eligible to fill in parallel:** orchestrate skill explicitly supports parallel spawns ("Both slots can be filled simultaneously"). The 04:48Z entry pre-committed this exact spawn pair: "spawn expansion worker for the oldest of the new follow-ups" AND "potentially spawn impl worker for #87 in the same cycle".
- ✅ **No `## INSTRUCTION:` in WORKLOG.md.** Step 1 of orchestrate skill completed cleanly — only historical references (all already acknowledged).
- ✅ **Auto-disable check N/A:** Productive spawn this cycle. Consecutive-quiet counter stays 0.

**Spawn details (both):**

- `POST /api/v1/app-conversations` with `X-Access-Token: $OPENHANDS_API_KEY` header (the openhands-api skill's documented mechanism — invoked pre-spawn this cycle, lesson-learned from 04:21Z applied).
- Both payloads use correct `initial_message.content[{type:text, text:...}]` schema + plugin block `github:jpshackelford/.openhands/plugins/ohtv-workflow@feat/ohtv-workflow-plugin`.
- Impl spawn: start-task `259f2b4d…` → `READY` on first +6s poll → `app_conversation_id=56b491fcd5274e4db210df295a9e5037`.
- Exp spawn: start-task `5753af3a…` → `READY` on first +6s poll → `app_conversation_id=761e1d90ee70494ea3a4de65dbf963a6`.
- Both verified `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`. Cloud-generated titles defaulted to `Conversation NNN` (request titles were descriptive enough but cloud opted for short form — non-issue, no functional impact).
- Note: neither spawn set `pr_number` (correctly — no PR exists yet for #87; #102 expansion is issue-only, no PR to bind to). The impl worker will create PR for #87; future cycles will see `pr_number` populated automatically once the PR is opened.

**Current State (verified 05:16–05:18Z):**

- **Open PRs:** 0.
- **Ready issues:** #87 (now in impl flight via `56b491f`).
- **Needs expansion:** #102 (now in expansion flight via `761e1d9`), #103 (next quiet cycle or after #102 expansion completes).
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Recently merged:** PR #101 (#82 charts, 04:52Z), PR #100 (#92 weekly-counts, 03:20Z), PR #99 (#83 classify, 01:22Z 2026-05-27), PR #98 (#81 velocity, 22:52Z 2026-05-26).

**Sync note:** `OH_API_KEY=$OPENHANDS_API_KEY ohtv sync --since 2026-05-27T01:16:* --quiet` completed cleanly. `lxa` + `ohtv` installed via venv at `/tmp/orchvenv/bin` (system `pip install` was rejected for system Python, expected).

**Housekeeping deferred:** WORKLOG.md is now ~1485 lines after this entry. The 19:19Z–22:51Z 2026-05-26 block (lines ~9–~660, ~650 lines, all >6 hours old, unrelated to #87/#102/#103) is **3 cycles overdue** for archive. Was deferred this cycle because both worker spawns + archive would be 3 actions, violating the orchestrator's one-action-per-wake-up discipline (parallel spawns count as 1 spawn action). **Pre-commit:** the next quiet cycle (~05:48Z if both workers are still running and there's no other decision-making to do) MUST run `/truncate-worklog` against that block. If WORKLOG.md crosses 1500 lines before then, archive becomes the priority action.

**Lessons learned this cycle:**

1. **Pre-committed parallel spawn worked cleanly.** The 04:48Z entry called this spawn pair exactly (impl #87 + exp #102) — no re-derivation needed at 05:18Z, just verification that PR slot was empty and #102/#103 had landed as predicted. Pre-committing concrete next-cycle actions in WORKLOG entries continues to pay off when state matches predictions.
2. **Merge worker `91ed7ea` completed in ~7 minutes end-to-end** including filing 2 follow-up issues — slightly longer than `0ba9415f` (PR #100 merge, ~25s) because of the issue-filing step. New baseline: merge-with-follow-ups ≈ 5–10 min; merge-only ≈ <1 min. Future merge spawn prompts that include follow-ups should budget ~10 min.
3. **`X-Access-Token` vs `Authorization: Bearer`:** the `spawn-conversation` skill documents `X-Access-Token: $OH_API_KEY`. Both header forms appear to work against the API, but the skill's documented form is the canonical one — used both spawns this cycle, both worked first-try with no schema/auth retries needed.
4. **Parallel spawns are no harder than serial spawns** when both payloads are pre-validated. Two `curl POST` + one polling loop checking both task IDs ≈ same wall-clock as a single spawn (~10s total for both READY).

**Next check (~30 min, ~05:48Z):**

- If `56b491f` (impl #87) is `running` AND `761e1d9` (exp #102) is `running` → log status, do nothing. Both slots occupied. Run the deferred truncation NOW (this would be a quiet cycle for spawning, but truncation is housekeeping, not spawning).
- If `56b491f` is `running` AND `761e1d9` is `finished` AND #102 has `ready` label → expansion slot empty; spawn **expansion worker for #103** (only remaining unexpanded issue). One spawn.
- If `56b491f` is `finished` AND a new PR exists (probably `feat/manifest-full-cache-87` branch) → check PR state per decision tree. If draft+CI green → wait. If ready+CI green+docs-in-diff+no-test-results → spawn testing worker.
- If `56b491f` is `finished` BUT no PR exists → investigate (impl worker may have hit a blocker; check conversation events).
- If `761e1d9` is `finished` AND #102 has `needs-info` or `needs-split` → human attention needed (skip for orchestrator, log).
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Archive TO-DO (DEFINITELY next cycle):** 19:19Z–22:51Z 2026-05-26 block → `WORKLOG_ARCHIVE_2026-05-26.md`. Hard-block: do this before the next spawn.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 04:52 UTC - Merge Worker (PR #101)

**PR merged ✅**

- PR: [#101 — feat: add --chart flag to ohtv report velocity (#82)](https://github.com/jpshackelford/ohtv/pull/101) (state=MERGED, mergedAt=2026-05-27T04:52:14Z, branch `feat/charts-velocity-82` deleted)
- Squash commit: [`77ce8804`](https://github.com/jpshackelford/ohtv/commit/77ce8804dab8be223b27bcbe3e9d75bfe7785a01) — `feat(reports): add --chart flag to velocity for publication-quality charts (#82)`
- Issue [#82 — Add charting script for velocity reports](https://github.com/jpshackelford/ohtv/issues/82) **closed** (auto-closed by `Closes #82` in squash-commit footer).

**Pre-merge verification:**

- ✅ HEAD drift check: `gh pr view 101 --json headRefOid --jq .headRefOid` → `0a85d36e7d5eb1a7e268f49faaf9d5e644b0b43a` (matched expected, no drift).
- ✅ CI: `PR Review by OpenHands/pr-review` → SUCCESS (1 check, 0 failing).
- ✅ Mergeable: `MERGEABLE` / `mergeStateStatus=CLEAN` / `isDraft=false` / `state=OPEN`.
- ✅ AI code-review bot (04:11Z): 🟢 _"Good taste — Elegant, pragmatic solution that solves a real problem with minimal complexity."_
- ✅ Manual test report (04:28Z, [comment 4551281621](https://github.com/jpshackelford/ohtv/pull/101#issuecomment-4551281621)): all 9 ACs satisfied; 1688/1688 pytest pass; 21/21 focused chart tests pass; ruff clean on new files.

**Follow-up issues filed for the two minor non-blocking nits:**

- [#102 — chore(charts): wrap ValueError as click.UsageError for unsupported --chart extension](https://github.com/jpshackelford/ohtv/issues/102) (unlabeled; expansion worker will handle)
- [#103 — docs(charts): document NULL-vs-zero LOC bar convention OR hatch partial_loc bars](https://github.com/jpshackelford/ohtv/issues/103) (unlabeled; expansion worker will handle)

**Worker actions:**

1. Cloned `https://github.com/jpshackelford/ohtv.git`.
2. Verified HEAD SHA matches `0a85d36e`; CI green; mergeable.
3. Reviewed PR diff (13 files, +1398/-3), issue #82 AC checklist, test report comment, AI bot review.
4. Appended a "Final verification" addendum to the PR description with bot quote + test-report link + nits list.
5. Squash-merged via `gh pr merge 101 --squash --subject "..." --body-file /tmp/merge_body.md --delete-branch` → exit 0.
6. Verified merge: `state=MERGED`, `mergeCommit.oid=77ce8804…`.
7. Pulled updated `main` (fast-forward `567f0c9..77ce880`).
8. Filed follow-up issues #102 and #103 (both **unlabeled** per orchestrator instruction — no `ready` label, expansion cycle owns triage).
9. Committed this worklog entry on `main` and pushed.

**DO-NOTs honored:**

- ❌ No source-file edits.
- ❌ No PR reopen.
- ❌ No `ready` label on follow-up issues.
- ❌ No fixup commits to merged branch (branch deleted).
- ❌ No other conversations spawned.

**Slot state after this run:** PR slot now idle (PR #101 merged, branch deleted). Expansion slot has two newly-filed unlabeled issues (#102, #103) to triage, plus the remaining `ready` issue #87 (manifest metadata cache widening) for implementation. Orchestrator's next cycle picks up.

_This worklog entry was written by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 04:48 UTC - Orchestrator

**Active Workers:**
| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `19dfec8` | testing | PR #101 — `--chart` flag | finished ✓ |
| `91ed7ea` | merge | PR #101 — `--chart` flag | **NEW** running |

**Spawned: Merge Worker** — `91ed7ea349464a188bb39ad3628c9518` ([conversation](https://app.all-hands.dev/conversations/91ed7ea349464a188bb39ad3628c9518))

Testing worker `19dfec8` completed cleanly at 04:29:16Z (cost $4.96). Test report posted 04:28:21Z on PR #101.

**Test verdict (full report in PR #101 comment):** ✅ **Ready to merge** — all 9 ACs satisfied.
- T-0 full pytest: **1688/1688 passed** in 26.55s (no regression vs impl-worker baseline)
- T-0b focused chart tests: **21/21 passed** in 11.49s
- T-1..T-16 blackbox matrix: all green (PNG/SVG/PDF rendering, 3-panel sharex layout, `--mark-date` axvline on all 3 panels, `--title` suptitle, empty-data path no-file-written, `--repo` filter, lazy matplotlib import error path, `scripts/chart_velocity.py` byte-identical to CLI flag, README example copy-pasteable, AGENTS.md item #30 spot-check, ruff clean on new files)
- Issue #82 AC roll-up: AC-1..AC-9 all ✅

**Two minor 🟡 nits (explicitly NOT blocking):**
1. Unsupported `--chart` extension surfaces as raw `ValueError` traceback instead of `click.UsageError` (UX polish — 2-line `try/except` fix in `cli.py`).
2. Chart cannot visually distinguish NULL `lines_added` from zero (semantic info loss vs. table's `-` vs `0`). Fix options: docs note OR hatched bars for `partial_loc=True`.

**Decision-tree match:**
- ✅ PR slot empty on wake-up (testing worker `19dfec8` finished; only `d9a994e` orchestrator was running, now also exiting).
- ✅ Expansion slot empty + 0 issues need expansion.
- ✅ "PR exists, ready, CI green, docs valid, test results valid, **good rating** → Spawn **merge worker**." Exact match. AI bot review is positive informational (COMMENTED, not CHANGES_REQUESTED). The 1 PR comment is the test report itself, not a review thread requiring reply. Minors are documented in PR for follow-up issues post-merge.
- ✅ No `## INSTRUCTION:` in WORKLOG.md (only historical narrative refs).

**Merge worker scope (prompt highlights):**
1. Clone, verify HEAD drift: `gh pr view 101 --json headRefOid` must equal `0a85d36e7d5eb1a7e268f49faaf9d5e644b0b43a`. Bail if drift detected.
2. Re-verify CI green.
3. Study full diff + read manual test report + issue #82 ACs.
4. Update PR description with final state.
5. Craft conventional commit: `feat(reports): add --chart flag to velocity for publication-quality charts (#82)` with body bullets (3-panel layout, sharex, `--mark-date`, `--title`, extension-driven format, lazy matplotlib via `[charts]` extra, `scripts/chart_velocity.py` standalone CSV-shim). Footer: `Refs #82` or `Closes #82` after verifying issue body.
6. `gh pr merge 101 --squash --subject ... --body ... --delete-branch`.
7. Verify `state=MERGED`.
8. **File two follow-up issues** for the 🟡 minors (no `ready` label — expansion worker will pick them up next cycle).
9. Update WORKLOG.md on main with merge entry + new issue numbers.
10. Exit.

**Explicit DO-NOTs:** no source edits, no fixup pushes, no re-open, no `ready` label on new follow-up issues, no other spawns.

**Spawn details:**
- `POST /api/v1/app-conversations` with `initial_message.content[{type:text, text:...}]` (correct schema, per the openhands-api skill invoked pre-spawn — lesson learned from the 04:21Z cycle applied successfully).
- Start-task `1e06f067…` → poll at +10s: `READY` → `app_conversation_id=91ed7ea349464a188bb39ad3628c9518`.
- `GET /app-conversations?ids=…` confirms `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`. Cloud-generated title: "✨ Merge PR #101: --chart flag for velocity report" (good — request title also descriptive enough that the cloud accepted it cleanly).

**Current State (verified 04:46–04:48Z):**
- **Open PRs:** 1 — [PR #101 — feat: add --chart flag to ohtv report velocity (#82)](https://github.com/jpshackelford/ohtv/pull/101) (ready, CI green, AI-bot positive, manual test ✅, merge in flight via `91ed7ea`).
- **Ready issues (1 remaining post-merge):** #87 (`priority:low`, manifest cache extension). #82 will close on merge.
- **Pre-commit:** Once `91ed7ea` lands PR #101 and files the two follow-up issues, the next PR-slot spawn → **#87** (only remaining `ready` issue). The two new follow-up issues will enter the expansion slot.
- **Needs expansion:** 0 currently (will become 2 once merge worker files the follow-ups).
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.

**Sync note:** `ohtv sync --since 2026-05-27T00:46:* --quiet` completed (after exporting `OH_API_KEY=$OPENHANDS_API_KEY` in the venv-less environment; `pip install` was used since `uv` rejected the system Python without `--system`).

**Housekeeping:** WORKLOG.md is now ~1370 lines after this entry. The 19:19Z–22:51Z 2026-05-26 block (lines ~9–~660, ~650 lines, all >6 hours old and unrelated to in-flight work) is overdue for archive. **Pre-commit:** the **next quiet cycle** (probably ~05:18Z if `91ed7ea` is still merging, or after follow-up issue triage) will run `/truncate-worklog` against that block → `WORKLOG_ARCHIVE_2026-05-26.md`. Deferring this cycle to keep the orchestrator action-count at 1 (one spawn).

**Auto-disable check:** Not applicable — productive spawn this cycle. Consecutive-quiet counter remains 0. Recent cycles (01:52Z … 04:21Z … this 04:48Z) all productive.

**Next check (~30 min, ~05:18Z):**
- If `91ed7ea` is `running` → log status, do nothing. Merge prep + 2 follow-up issues filed typically takes 10–20 min.
- If `91ed7ea` is `finished` AND PR #101 shows `state=MERGED` AND two new follow-up issues exist (no `ready` label) → spawn **expansion worker** for the oldest of the new follow-ups. PR slot is empty post-merge, but only #87 has `ready` — so also potentially spawn **impl worker for #87** in the same cycle (both slots can fill).
- If `91ed7ea` is `finished` BUT PR #101 still `OPEN` → investigate (drift detected? merge call failed?). May need `## INSTRUCTION:` from human.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Archive TO-DO (definitely this cycle if quiet):** 19:19Z–22:51Z 2026-05-26 block → `WORKLOG_ARCHIVE_2026-05-26.md`.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-05-27 04:21 UTC — Orchestrator

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `d9a994e` | orchestrator | this cycle | running |
| `19dfec8` | testing | PR #101 — `--chart` flag for velocity | **NEW** running |

**Spawned: Testing Worker** — `19dfec829cd142e7a67ea8cb72a7403b` ([conversation](https://app.all-hands.dev/conversations/19dfec829cd142e7a67ea8cb72a7403b))

PR slot now occupied by testing worker. Expansion slot stays idle (0 issues need expansion).

**Discovery on wake-up:**

A prior orchestrator wake-up (around 03:51Z) appears to have spawned an impl worker for issue #82 (charting for velocity) — exactly as pre-committed in the 03:21Z cycle. That impl worker completed quickly: opened **PR #101** at 04:07:32Z and prepended a one-line worker note at the top of WORKLOG.md (`### 2026-05-27 04:09 UTC - Impl Worker (#82)`). No 03:51Z orchestrator entry was committed (looks like that cycle exited after spawning before the worklog commit), but the spawn succeeded and the impl worker landed PR #101 cleanly.

**PR #101 state on wake-up (verified 04:16–04:21Z):**

- **Title:** "feat: add --chart flag to ohtv report velocity (#82)"
- **Branch:** `feat/charts-velocity-82`, HEAD `0a85d36e7d5eb1a7e268f49faaf9d5e644b0b43a`
- **Status:** `isDraft=false`, `state=OPEN`, `mergeable=MERGEABLE`, `reviewDecision=""` (AI bot uses COMMENTED).
- **CI:** ✅ 1 SUCCESS check — `PR Review by OpenHands/pr-review` finished 04:10:50Z (2m41s).
- **AI bot review:** 🟢 "Good taste — Elegant, pragmatic solution that solves a real problem with minimal complexity. KEY INSIGHT: The None-value filtering for words/LOC (lines 149-154 in charts.py) is textbook 'good taste' — it eliminates edge cases by construction rather than adding conditional checks throughout the plotting logic. The lazy matplotlib import keeps the core install lightweight while providing a clear error path." COMMENTED state — not a change-request review.
- **Comments:** 0 (no manual test results yet).
- **Files changed (13):** `AGENTS.md`, `README.md`, `pyproject.toml`, `scripts/__init__.py`, `scripts/chart_velocity.py`, `src/ohtv/cli.py`, `src/ohtv/reports/charts.py`, `src/ohtv/reports/velocity.py`, `tests/unit/reports/test_charts.py`, `tests/unit/reports/test_cli_chart.py`, `tests/unit/scripts/__init__.py`, `tests/unit/scripts/test_chart_velocity_script.py`, `uv.lock`.
- **Docs already in-diff:** ✅ Both `README.md` (new chart section) and `AGENTS.md` (new item #30 per impl worker) bundled — no separate docs worker needed.

**Decision-tree gates verified:**

- ✅ **PR slot empty on wake-up:** Only `d9a994e` (this orchestrator) was running for `jpshackelford/ohtv`. Impl worker already exited.
- ✅ **Expansion slot empty + nothing to expand:** 0 issues without `ready` or `hold` labels.
- ✅ **Decision tree match:** "PR exists, ready, CI green, docs updated, no manual test results → Spawn **testing worker**." Exact match. Not a re-test (no commits since CI green; no test comment yet → first test pass). Not a review round (0 review comments needing reply; AI bot review is positive informational).
- ✅ **No `## INSTRUCTION:` in WORKLOG.md.** Step 1 of the orchestrate skill completed cleanly.

**Testing worker scope (prompt highlights):**

- Clone + `gh pr checkout 101`, verify HEAD == `0a85d36...` (drift check), `uv sync` + matplotlib install.
- Read PR description, issue #82 expansion comments, and full diff before designing the test matrix.
- **Full pytest first** — `uv run pytest -x` baseline is 1688/1688 per impl worker. Regression = blocker.
- **Focused tests** on the 3 new test files.
- **Blackbox T-1..T-15 matrix:** help text, default CSV unchanged, PNG written, 3-panel layout, empty dataset, partial-LOC rows, `--repo` filter combo, matplotlib-missing error path, `scripts/chart_velocity.py` standalone, AC-by-AC against issue #82.
- **Ruff/lint** on the new files + check `src/ohtv/cli.py` baseline drift.
- **Documentation cross-check** — run 2+ README examples to verify they're copy-pasteable.
- Post `## Manual Test Results — PR #101` PR comment with verdict (✅/🟡/🔴), coverage matrix, bugs section, AI-disclosure footer.

**Explicit DO-NOTs encoded in prompt:** no file edits / no commits / no pushes to PR branch, no draft-switching, no `gh pr merge`, no `gh pr review --approve` / `--request-changes`, no WORKLOG.md touch, no `AGENTS.md`/`README.md` edits (report doc bugs in the test comment instead), no resolving review threads, no writing to real `~/.ohtv/index.db` (use `OHTV_DIR=$(mktemp -d)`), no spawning other conversations.

**Spawn details:**

- `POST /api/v1/app-conversations` with `initial_message.content[{type, text}]` per the openhands-api skill.
- **Lesson re-learned:** First spawn attempt used the wrong field name (`initial_user_msg` instead of `initial_message.content[]`). The API accepted the request and started a sandbox (`01NGXsHV9QzM6SE2lInpc6` / app conv `0cd5df26cc624d4caba7ef11a65bf13a`) but with `initial_message: null` — i.e., an idle conversation with no task. **Recovery:** Paused that sandbox via `POST /api/v1/sandboxes/01NGXsHV9QzM6SE2lInpc6/pause` (`success: true`), then re-spawned with the correct payload schema. The bad sandbox is now paused and harmless. **Pre-commit:** invoke the `openhands-api` skill BEFORE the first spawn next time, not after, to catch the schema upfront.
- Re-spawn start-task `1a9a97fd…` → poll at +8s: `READY` → `app_conversation_id=19dfec829cd142e7a67ea8cb72a7403b`. `GET /app-conversations?ids=…` confirms `execution_status=running`, `sandbox_status=RUNNING`, `selected_repository=jpshackelford/ohtv`, `pr_number=[101]` (✅ pinned per the 02:51Z lesson-learned). Cloud-generated title: "✅ Manual Testing PR #101: Velocity Chart Flag" (request title was honored at the descriptive level — better than the typical "Conversation 19dfec8" placeholder).

**Current State (verified 04:16–04:21Z):**

- **Open PRs:** 1 — [PR #101 — feat: add --chart flag to ohtv report velocity (#82)](https://github.com/jpshackelford/ohtv/pull/101) (ready, CI green, AI-bot positive, docs in-diff, manual test in flight via `19dfec8`).
- **Recently merged:** PR #100 (#92 weekly-counts, merged 03:20Z), PR #99 (#83 classify, merged 01:22Z 2026-05-27), PR #98 (#81 velocity, merged 22:52Z 2026-05-26).
- **Ready issues (2 remaining):** #82 (in PR #101 testing), #87 (`priority:low`, manifest cache extension).
- **Pre-commit:** when PR #101 lands clean, next PR-slot spawn → **#87** (only remaining `ready` issue, `priority:low`, no `hold`).
- **Needs expansion:** 0.
- **On hold:** #26 (mcp server), #90 (Cloud API PATCH-tags blocker).
- **Blocked / needs-info / needs-split:** none.
- **Other running OH conversations:** `d9a994e` (this orchestrator) + `19dfec8` (just-spawned testing worker). The empty sandbox `0cd5df2` from the schema mishap is paused. All else `finished`/`paused`/missing.

**Sync note:** `OH_API_KEY=$OPENHANDS_API_KEY ohtv sync --since 2026-05-27T00:16:55 --quiet` completed cleanly (the existing pattern of mapping `OPENHANDS_API_KEY → OH_API_KEY` for `ohtv` continues to work). `lxa repo add jpshackelford/ohtv` ran on a fresh `.venv` (clone is grafted/shallow until `git fetch --unshallow`, which I ran to inspect commit history for the missing 03:51Z entry).

**Housekeeping:** WORKLOG.md was 1226 lines pre-cycle; this entry pushes it to ~1290. The 6-hour-post-productive-work threshold for the 19:19Z–22:51Z 2026-05-26 entries has now passed (those entries are 5.5–9 hours old at 04:21Z), so they're eligible for archive. **Deferred this cycle** to keep the action count at 1 (one spawn). **Pre-commit:** archive the 19:19Z–22:51Z 2026-05-26 block (lines ~9–~660) on the next quiet cycle OR if WORKLOG.md crosses 1300 lines — whichever comes first. Saving ~650 lines would bring the file back to ~640 lines, well under the 300-line truncation-trigger threshold.

**Auto-disable check:** Not applicable — productive spawn this cycle. Recent cycles (01:52Z, 02:22Z, 02:51Z, 03:21Z, ~03:51Z impl spawn, this 04:21Z one) have all been productive. Two-consecutive-quiet-period counter remains at 0.

**Next check (~30 min, ~04:51Z):**

- If `19dfec8` is `running` → log status, do nothing. Testing of a chart-rendering PR (matplotlib install + image-byte verification + full pytest + 10+ blackbox tests) typically runs 20–60 min. The matplotlib install adds ~30s on cold sandbox start.
- If `19dfec8` is `finished` AND a `## Manual Test Results — PR #101` PR comment exists with **✅ Ready to merge** AND no blocker bugs → spawn **merge worker** for PR #101. AI bot review is already positive; no human review-round needed.
- If `19dfec8` is `finished` AND test report shows 🔴/🟡 with ❌ MAJOR bugs → spawn **review worker** (fix-then-re-test loop). The review worker should fold AI-bot review nits + bug fixes into one round.
- If `19dfec8` is `finished` AND test report shows ⚠️ minor bugs only → spawn **review worker** to fold in minor fixes, then re-test on the cycle after.
- If `19dfec8` is `finished` BUT no test comment was posted → investigate the conversation events; may need a `## INSTRUCTION:` from human.
- If a new `## INSTRUCTION:` appears in WORKLOG.md → follow it first.
- **Archive TO-DO (eligible now):** 19:19Z–22:51Z 2026-05-26 entries → `WORKLOG_ARCHIVE_2026-05-26.md`. Run on next quiet cycle or if WORKLOG.md > 1300 lines.

_This entry was created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
