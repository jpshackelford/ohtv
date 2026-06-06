# CHANGELOG


## v0.30.1 (2026-06-06)

### Bug Fixes

- **engagement**: Cap block extension on separate T_a window (Issue #184)
  ([`697008c`](https://github.com/jpshackelford/ohtv/commit/697008c81fb5d072bdeab7edce0102a1818aee55))

The v1 engagement algorithm reused the silence-tolerance threshold `T` (12 min) as the only gate for
  crediting an attended block, which inflated long-running set-and-forget conversations by 14+ hours
  each (~50 h across 9 rows surfaced in #184). v2 introduces a separate sustained-attention window
  `T_a` as a second gate after the silence-tolerance check: when the user-to-user gap exceeds `T_a`
  the block collapses to a zero-duration touch at `U_i` (attention_periods still increments,
  engaged_seconds does not). Migration 025 adds `sustained_attention_seconds` and
  `algorithm_version` columns to `conversation_engagement`, indexes the new column, and `DELETE`s
  engagement rows from `conversation_stages` so every conversation auto-recomputes under v2 on the
  next `ohtv sync` / `ohtv db process engagement` — no `--force` required.

New CLI knob: `ohtv db process engagement --sustained-attention SECONDS` (also flows through `db
  process all`). Default is 3600 s (1 h), labelled **PROVISIONAL** — pinning the empirical value
  requires the corpus analysis described in the #184 thread (bucket user-to-user gaps by intervening
  agent-activity length). Pass `--sustained-attention 999999999` to recover pre-v2 behavior for the
  sweep workflow. `--sustained-attention 0` collapses block-extension but does not zero out
  conversations with adjacent user messages within `T` — the period-merge step still applies. This
  is documented behavior, not a bug.

Manual QA on 50 cloud conversations passed all 15 scenarios (schema, defaults, knob round-trip,
  filter parity, auto-invalidation, idempotency, display); the full unit suite passes (2681 passed,
  2 skipped, 3 xfailed). Follow-up: an ambient `OHTV_DIR` leak between `test_extra_paths.py` and
  `test_gen_objs_batch.py` causes incidental failures when pytest inherits a populated `OHTV_DIR` —
  unrelated to this PR; a tracking issue should be filed.

Closes #184.

Co-authored-by: openhands <openhands@all-hands.dev>

### Chores

- Worklog update 2026-06-06T16:18:00Z
  ([`e135966`](https://github.com/jpshackelford/ohtv/commit/e135966f2c64539b19344b85d23c5fa4200f65f4))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-06-06T17:16Z
  ([`9326a6c`](https://github.com/jpshackelford/ohtv/commit/9326a6c38bbb8a707f852bb715b772398386e896))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-06-06T17:50:20Z
  ([`576d266`](https://github.com/jpshackelford/ohtv/commit/576d266a51dcd8a21d684cce7df8da9a5c6a6693))

- Worklog update 2026-06-06T18:51:11Z
  ([`713b88f`](https://github.com/jpshackelford/ohtv/commit/713b88f66f4f6c2fc8633eb02e52d22294b6ce14))

Spawned merge worker f21e1cb for PR #185 (engagement v2 / Issue #184). All four merge gates
  satisfied: CI green, bot review APPROVED, docs updated, manual test rating green.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: 2026-06-06t18:18z - spawn testing worker for PR #185
  ([`50dd64f`](https://github.com/jpshackelford/ohtv/commit/50dd64f794a0929b7c7c98479958e7b38bcd92ec))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: 2026-06-06t18:27z - dedup tick, defer to parallel orchestrator + testing worker
  ([`099d988`](https://github.com/jpshackelford/ohtv/commit/099d98823e21d6f2cb23ce0048cdc9f10f280036))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: All quiet at 13:47Z — #184 re-held by human, both slots idle
  ([`6e0c033`](https://github.com/jpshackelford/ohtv/commit/6e0c033bde61e3c85e69bb80a45ff361b5f059e4))

- **worklog**: Archive 2026-06-04 13:50Z → 2026-06-05 04:51Z entries
  ([`621478e`](https://github.com/jpshackelford/ohtv/commit/621478e5b31758d2b7f99f3418ba982b47f35495))

Archived 47 entries (including the now-resolved 2026-06-05 01:48Z INSTRUCTION block) so the live
  WORKLOG.md stays well within the orchestrator's 10-minute per-tick budget. The auth-blocker outage
  from ~05:00Z–11:00Z masked accumulated entries that should have been archived earlier; catching up
  now.

INSTRUCTION block was resolved via option-1 exit (PR #183 squash-merged at 31c45193); full block
  preserved in this archive for audit.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Archive pre-13:25Z status entries + 17:17Z orchestrator tick
  ([`43a7902`](https://github.com/jpshackelford/ohtv/commit/43a7902462d5d786dcd0b0af8d2d48de2af803e5))

[skip ci]

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Docs worker completed for PR #185
  ([`ef2a0a9`](https://github.com/jpshackelford/ohtv/commit/ef2a0a915ca8ee9286862ac72c755da1f6640c16))

- **worklog**: Expansion worker completed #184 — engagement overcount root-caused, ready
  ([`19e8c88`](https://github.com/jpshackelford/ohtv/commit/19e8c8894e0cc8509e56459742f0dd1a750c5657))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-06T18:16:50Z — spawn docs worker for PR #185
  ([`72f3826`](https://github.com/jpshackelford/ohtv/commit/72f3826e69354c9b0232cb980eda75d49e591df8))

- **worklog**: Orchestrator quiet tick 2026-06-05T16:18:55Z
  ([`823ebfc`](https://github.com/jpshackelford/ohtv/commit/823ebfc6ba54e27a17a59b4ec67fa46239089b6e))

- **worklog**: Orchestrator quiet tick 2026-06-05T23:16Z
  ([`df18df6`](https://github.com/jpshackelford/ohtv/commit/df18df6aa5bef3690aac20f25030b12a7d7a2f7a))

- **worklog**: Orchestrator quiet tick 2026-06-05T23:47Z
  ([`870b596`](https://github.com/jpshackelford/ohtv/commit/870b59605ad2a5f2b056ca295e5c1e1b50e6288f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator quiet tick 2026-06-06T00:17Z
  ([`6a2aafb`](https://github.com/jpshackelford/ohtv/commit/6a2aafbcf0ea4aea35b5cfdc8171d6adf174d6ad))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T11:48Z — all quiet, both slots idle
  ([`aa1d6ff`](https://github.com/jpshackelford/ohtv/commit/aa1d6ff3ded80df2f7b29655ad3003a808bf1870))

- **worklog**: Orchestrator status 2026-06-05T12:17Z — all quiet (user-invoked)
  ([`30ba903`](https://github.com/jpshackelford/ohtv/commit/30ba9032f82cdc7b9ce54a52d40890b6c2ad1ec2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T12:47Z — all quiet (user-invoked)
  ([`0cf09aa`](https://github.com/jpshackelford/ohtv/commit/0cf09aabc424aaf5e2a8ab34e523251f60b38c11))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T17:50:48Z
  ([`5e6dc55`](https://github.com/jpshackelford/ohtv/commit/5e6dc55f956b06751f87246f2b838c45b28a0962))

- **worklog**: Orchestrator status 2026-06-05T18:16:48Z
  ([`1990bc7`](https://github.com/jpshackelford/ohtv/commit/1990bc7bfe912edf328c32aabe9c8af634104ab2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T18:47:00Z
  ([`f29e2f3`](https://github.com/jpshackelford/ohtv/commit/f29e2f3b9150d44ecff06ebd29cb269aa99e4698))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T19:20:00Z
  ([`a836755`](https://github.com/jpshackelford/ohtv/commit/a836755853bf17c2397ed6993d4a4115d45f87fa))

- **worklog**: Orchestrator status 2026-06-05T19:47:00Z
  ([`d867970`](https://github.com/jpshackelford/ohtv/commit/d867970038447a2890ae4f6c511c2138cc127dd7))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T20:18:00Z
  ([`89431cb`](https://github.com/jpshackelford/ohtv/commit/89431cbb67316f6285a18b578d1443c27da18aab))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T20:48:21Z
  ([`4ce008a`](https://github.com/jpshackelford/ohtv/commit/4ce008a7798ece6199252df540b81247a6466778))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator status 2026-06-05T21:17Z
  ([`fedfb16`](https://github.com/jpshackelford/ohtv/commit/fedfb16363b2fe26511e869869f3993ca18a7011))

- **worklog**: Orchestrator status 2026-06-06T15:51:09Z
  ([`3a5e95a`](https://github.com/jpshackelford/ohtv/commit/3a5e95ab09196287c12288cf1cbc235a87d0dc40))

- **worklog**: Orchestrator tick 12:18Z
  ([`f257b4c`](https://github.com/jpshackelford/ohtv/commit/f257b4cbb934e4680bb0dd89c592bb4b32007b98))

PR #185 still draft, all issues on hold. No worker spawned.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 12:46Z
  ([`d078db0`](https://github.com/jpshackelford/ohtv/commit/d078db0210b574641b2a5bc6c007bbe332113917))

- **worklog**: Orchestrator tick 13:18Z
  ([`f08bb43`](https://github.com/jpshackelford/ohtv/commit/f08bb436145e84f5bb9f4100b3e47a7f0a416c13))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-05T13:20Z — spawn expansion for #184
  ([`73ff83f`](https://github.com/jpshackelford/ohtv/commit/73ff83f59eecd1c021a24b9816cc5189975ca400))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-05T16:46Z - PR #185 still draft+green, no action
  ([`8545ad0`](https://github.com/jpshackelford/ohtv/commit/8545ad0fbd85d672b774a775b416e6c3502bd1c2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-05T21:46Z
  ([`db5c148`](https://github.com/jpshackelford/ohtv/commit/db5c148a871f24115efd358746e99442c2f55739))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T00:47Z [skip ci]
  ([`bac6574`](https://github.com/jpshackelford/ohtv/commit/bac6574ed1f9937ef41b18dcedb6a6c0c4044a83))

- **worklog**: Orchestrator tick 2026-06-06T01:17Z
  ([`3405049`](https://github.com/jpshackelford/ohtv/commit/3405049c2cf611656316a5fe18ce21db05eb9302))

- **worklog**: Orchestrator tick 2026-06-06T01:48Z - quiet, PR #185 still draft
  ([`24e04b3`](https://github.com/jpshackelford/ohtv/commit/24e04b3b286f7a087bca850ffaa212f5d3659f3c))

- **worklog**: Orchestrator tick 2026-06-06T02:17Z - quiet, PR #185 still draft
  ([`ce0e05d`](https://github.com/jpshackelford/ohtv/commit/ce0e05d81c02fcb87e8b800a44774f0103ccdabb))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T02:47Z - quiet, PR #185 still draft
  ([`2478026`](https://github.com/jpshackelford/ohtv/commit/247802617ea6c08e5ba99b33cdf3829e083ddd2f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T03:19Z
  ([`430387c`](https://github.com/jpshackelford/ohtv/commit/430387c1698208f771e9e77346d99806db714f17))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T03:48Z
  ([`d19f18c`](https://github.com/jpshackelford/ohtv/commit/d19f18ce4e8c5c2b8de0d2eee89d935e9048f1af))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T04:18:52Z
  ([`b90714a`](https://github.com/jpshackelford/ohtv/commit/b90714abbecc833164bcce08607731028019b9af))

- **worklog**: Orchestrator tick 2026-06-06T04:46Z [skip ci]
  ([`b886598`](https://github.com/jpshackelford/ohtv/commit/b886598e3a817bf308eb5815b837b01fb0f6b6c0))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T05:19Z - no action (PR #185 draft, all issues hold)
  ([`0b3f49d`](https://github.com/jpshackelford/ohtv/commit/0b3f49d20aeb4866f825f507ca803a50d77a940d))

- **worklog**: Orchestrator tick 2026-06-06T05:46Z - no action (PR #185 draft, all issues hold)
  ([`4de64c4`](https://github.com/jpshackelford/ohtv/commit/4de64c4b93fc0739becab9392b90ff8badcc0a73))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 2026-06-06T13:49Z
  ([`02eaf96`](https://github.com/jpshackelford/ohtv/commit/02eaf963586f4d6773c94da0f3dfd9af8e4b8f10))

- **worklog**: Orchestrator tick 2026-06-06T14:20Z
  ([`1d0dd4f`](https://github.com/jpshackelford/ohtv/commit/1d0dd4fc5b06f025617c98309f7128737cdacf6a))

- **worklog**: Orchestrator tick 2026-06-06T14:48Z
  ([`0459989`](https://github.com/jpshackelford/ohtv/commit/04599894f31b79cc5deb903be7da455b91c43d3e))

- **worklog**: Orchestrator tick 2026-06-06T15:16Z
  ([`0e516a5`](https://github.com/jpshackelford/ohtv/commit/0e516a5d5d4e7a77968b9b81312ac4a7e230d9f8))

- **worklog**: Orchestrator tick 2026-06-06T16:47Z
  ([`b4b4b30`](https://github.com/jpshackelford/ohtv/commit/b4b4b306242b2755d808d3dd66a43acf5fa7e0f3))

- **worklog**: Orchestrator tick 22:17Z - PR #185 still draft, both slots idle
  ([`981ddef`](https://github.com/jpshackelford/ohtv/commit/981ddefd9e36cee9b68dd1e0ca3d5d0094230ac4))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator tick 22:46Z - PR #185 still draft, both slots idle
  ([`0aeb569`](https://github.com/jpshackelford/ohtv/commit/0aeb569e4ec4e7614191bc46a64fb9dd0ee6bc6a))

- **worklog**: Tick at 14:47Z - PR #185 still draft + green, both slots idle
  ([`2eba48a`](https://github.com/jpshackelford/ohtv/commit/2eba48a286ff2e70a18589466421c3a08ef79085))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Tick at 15:16Z - PR #185 still draft + green, both slots idle
  ([`c6a1033`](https://github.com/jpshackelford/ohtv/commit/c6a10333c25e37e0a3336e54545b67698b361bd2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Tick at 15:49Z - PR #185 still draft + green, both slots idle
  ([`7dcf208`](https://github.com/jpshackelford/ohtv/commit/7dcf2084f3f57f54abf9f23c3c87b2911ea86903))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Truncate + remove resolved INSTRUCTION block
  ([`28df659`](https://github.com/jpshackelford/ohtv/commit/28df659acb1637bd9694b75d832868ef085a97ba))

Live WORKLOG.md shrunk from 2769 → 70 lines. Old entries moved to WORKLOG_ARCHIVE_2026-06-05.md
  (sibling commit). INSTRUCTION block from 01:48Z removed per its own option-1 exit path now that PR
  #183 is merged (31c45193). New 11:23Z recovery entry documents the post-auth recovery for the next
  orchestrator cycle.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Wait at 14:18Z — PR #185 (draft) addresses #184, all issues on hold
  ([`2df7d1c`](https://github.com/jpshackelford/ohtv/commit/2df7d1caa11f3462df1aba8f4db00b5b24d95f0f))

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.30.0 (2026-06-05)

### Chores

- **worklog**: Docs spot-check for PR #183
  ([`53ff4dd`](https://github.com/jpshackelford/ohtv/commit/53ff4ddeb4e3d85ee9588ed2d3608bba29d08f95))

- **worklog**: Docs worker for PR #183
  ([`93c7c97`](https://github.com/jpshackelford/ohtv/commit/93c7c97f523bbe7fdd398885bd5cecd35ef26399))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Implementation worker — PR #183 (Issue #181) opened ready for review
  ([`4c6d30c`](https://github.com/jpshackelford/ohtv/commit/4c6d30c9c8003a6738a0f261f184d41139251454))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker — PR #182 squash-merged (Issue #180 closed, ohtv-v0.29.0 released)
  ([`52facbd`](https://github.com/jpshackelford/ohtv/commit/52facbd4db84a429ac11cdcd72bd5122ce81dc5d))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-04T22:24:46Z - spawned impl worker b68bb0d for Issue #181
  ([`3bfbe3f`](https://github.com/jpshackelford/ohtv/commit/3bfbe3fb3764e3752a96f4cd5caf36d4046b7a5a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator escalation - merge worker silent-fail confirmed twice on PR #183
  ([`837e100`](https://github.com/jpshackelford/ohtv/commit/837e1002c186b1824ebac1c2503a5656d784a8df))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator housekeeping - truncate WORKLOG + INSTRUCTION-honoring cycle 04:51Z
  ([`e86a82c`](https://github.com/jpshackelford/ohtv/commit/e86a82c2c93266c0c97369677b6d99d3d39ac18e))

- Archived 13 entries (2026-06-04 07:50Z to 13:18Z) to WORKLOG_ARCHIVE_2026-06-04.md -
  Pre-truncation: 3500 lines; post-truncation: 2676 lines (before this entry) - INSTRUCTION header
  preserved - No worker spawned (INSTRUCTION blocks PR slot for #183; expansion slot empty) - 6th
  consecutive INSTRUCTION-honoring cycle; auto-disable counter remains 0

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator INSTRUCTION-honoring cycle 02:18Z - skipped PR #183 merge spawn
  ([`c8d4ccc`](https://github.com/jpshackelford/ohtv/commit/c8d4ccc561fdf3c2ab4ffc5e31d20a8743ad543c))

- **worklog**: Orchestrator INSTRUCTION-honoring cycle 02:48Z - skipped PR #183 merge spawn
  ([`12528c5`](https://github.com/jpshackelford/ohtv/commit/12528c5839593a7bc70e9510534f895fba2923f6))

- **worklog**: Orchestrator INSTRUCTION-honoring cycle 03:20Z - skipped PR #183 merge spawn (3rd
  consecutive)
  ([`9b06f10`](https://github.com/jpshackelford/ohtv/commit/9b06f101d696530cf07e40b23772231224a51370))

- **worklog**: Orchestrator INSTRUCTION-honoring cycle 03:49Z - PR #183 merge spawn skipped (4th
  consecutive)
  ([`ea1633b`](https://github.com/jpshackelford/ohtv/commit/ea1633b8d361fb596741c3cffe62ca0cc9cd75ea))

- **worklog**: Orchestrator INSTRUCTION-honoring cycle 04:17Z - PR #183 merge spawn skipped (5th
  consecutive)
  ([`e0defce`](https://github.com/jpshackelford/ohtv/commit/e0defce7eff79a10131dc8079552afd9991f3c74))

- **worklog**: Orchestrator retry merge worker for PR #183 (silent-fail recovery)
  ([`27b0737`](https://github.com/jpshackelford/ohtv/commit/27b0737c5914aea8a876d478ec8f58daee944291))

- **worklog**: Orchestrator spawn docs spot-check for PR #183
  ([`e61910c`](https://github.com/jpshackelford/ohtv/commit/e61910c8533c1022ff44802533325f06f9d43315))

- **worklog**: Orchestrator spawn merge worker for PR #183
  ([`3dd8097`](https://github.com/jpshackelford/ohtv/commit/3dd809721bae3c9a8d18ffe5eefa06d65e61e449))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing worker for PR #183
  ([`2320b91`](https://github.com/jpshackelford/ohtv/commit/2320b9134443297644f313d7747f2411923c5672))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator user-invoked cycle 11:18Z - PR #183 merge spawn skipped (7th
  consecutive)
  ([`c469310`](https://github.com/jpshackelford/ohtv/commit/c46931061de2e553ac985d72fd793e71b4465c49))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator — spawned docs worker for PR #183
  ([`3f2d807`](https://github.com/jpshackelford/ohtv/commit/3f2d807b967f546064f3cb02a48523f09b0ef998))

Spawned docs worker conv 05df98c for PR #183 (Issue #181, ohtv messages command). PR is ready + CI
  green but README/AGENTS.md not updated for the new top-level CLI verb; docs must precede testing
  per the 'Test What's Documented' principle. Two pr-review bot threads (orange pagination bug +
  yellow dedup suggestion) deferred to review worker after docs and test pass.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Review round 1 on PR #183
  ([`c0e2f30`](https://github.com/jpshackelford/ohtv/commit/c0e2f302bac18ce7d905ce038489af89957d6db2))

- **worklog**: Testing worker for PR #183
  ([`6f28750`](https://github.com/jpshackelford/ohtv/commit/6f2875079ab3a92124b47183ad37765a9b3c4af8))

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **cli**: Add ohtv messages command to list user messages across conversations
  ([#183](https://github.com/jpshackelford/ohtv/pull/183),
  [`31c4519`](https://github.com/jpshackelford/ohtv/commit/31c45193806d98ec54f6811c33fc374f25a66146))

Fixes #181.

Merged by OpenHands on behalf of @jpshackelford as part of the 2026-06-05 orchestrator recovery
  (auth-blocker followed by spawn-picker silent-failure on merge-worker slot, see INSTRUCTION block
  in WORKLOG.md filed by orchestrator cycle 35eb0aa at 2026-06-05 01:48 UTC for full context).

PR is APPROVED / MERGEABLE / CLEAN with CI green (lint + pytest).


## v0.29.0 (2026-06-04)

### Chores

- **worklog**: #180 implementation worker complete (PR #182 ready)
  ([`4badb10`](https://github.com/jpshackelford/ohtv/commit/4badb10b4aeed8775616765ff0f61f36e1560531))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Docs worker PR #182 — --event-dates README section
  ([`5a76d85`](https://github.com/jpshackelford/ohtv/commit/5a76d857ce6a625a51686e8f6f4abdf5d542d3cd))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Expansion worker 1498695 completed issue #181
  ([`2473ab4`](https://github.com/jpshackelford/ohtv/commit/2473ab45467bb3d042f17b7236c9e6501b94a912))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Expansion worker — Issue #180 ready (--event-dates flag)
  ([`b9ebf0f`](https://github.com/jpshackelford/ohtv/commit/b9ebf0fac14ce85da830691ae84f2145e2afaee8))

- **worklog**: Merge worker — PR #179 squash-merged (#173 closed, release no-op'd)
  ([`18adbd5`](https://github.com/jpshackelford/ohtv/commit/18adbd5091b6f43412ae7f00de9aa30e67d69752))

Squash-merged PR #179 (refactor: extract _process_engagement_rows helper from
  _load_engagement_for_ids) at commit fa4056d. Issue #173 auto-closed.

Release workflow ran on the merge commit and correctly did NOT bump the version or create a tag —
  the 'refactor:' conventional-commit subject is classified as non-version-bumping per the AGENTS.md
  release contract. Latest tag remains ohtv-v0.28.0.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 19:20Z — spawned expansion worker for #180
  ([`21c9c65`](https://github.com/jpshackelford/ohtv/commit/21c9c65c1ff1a6008b0b3551c150904d93aa5358))

PR slot idle (no open PR, queue drained after #173 merge); expansion slot picks up #180 (filed
  18:37Z by @jpshackelford) as the oldest unexpanded issue. #181 (filed 18:38Z) is queued behind it
  since the proposed 'ohtv messages' command depends on the --event-dates plumbing #180 introduces.

Spawned conversation: 21541ba43d344ca2bedd71dfd5719d61 (verified running, RUNNING sandbox).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-04 20:51Z — spawned testing worker for PR #182
  ([`8196548`](https://github.com/jpshackelford/ohtv/commit/819654873ace67513f18ba513ec12059b3f14bfa))

- **worklog**: Orchestrator 2026-06-04T17:48Z — spawn impl worker for #173
  ([`dfa9d0d`](https://github.com/jpshackelford/ohtv/commit/dfa9d0d622727edf10cb82ddffa33c627cbff85a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-04T18:20Z - spawned testing worker for PR #179
  ([`3924e52`](https://github.com/jpshackelford/ohtv/commit/3924e52293eba448f35b3097833ce6dd4696d9a8))

- **worklog**: Orchestrator 2026-06-04T21:46Z - spawn merge worker for PR #182
  ([`85cdbfb`](https://github.com/jpshackelford/ohtv/commit/85cdbfb0183a1eda87fcc28d96f1c8e46131dbc8))

- **worklog**: Orchestrator — review worker spawned for PR #182 (1 unresolved suggestion thread)
  ([`094ea30`](https://github.com/jpshackelford/ohtv/commit/094ea301febc3fd78b98ce7ff0c0050b2291eacc))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator — spawn impl #180 + expansion #181 (parallel)
  ([`3b862e0`](https://github.com/jpshackelford/ohtv/commit/3b862e03733ac8228192f082410c99455ca135f3))

- **worklog**: Record PR #179 (refactor: _process_engagement_rows helper, Issue #173)
  ([`13fb544`](https://github.com/jpshackelford/ohtv/commit/13fb5447cb5727a94de6cb9ca01459eb6dfd6721))

- **worklog**: Review worker — PR #182 round 1 (simplified date-filter JOIN condition)
  ([`66e3425`](https://github.com/jpshackelford/ohtv/commit/66e3425b324ad5e663acd4a92bf66ed6458b781e))

- **worklog**: Testing worker — PR #182 manual blackbox tests ✓ (READY FOR MERGE)
  ([`6d034ac`](https://github.com/jpshackelford/ohtv/commit/6d034ac43955908223ec1f8df8ec14e5f03b2dc2))

All 7 test groups pass (T1-T7); 2614 unit tests pass; AC1-AC6 verified. Report posted at
  https://github.com/jpshackelford/ohtv/pull/182#issuecomment-4626107246

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **filter**: Add --event-dates to filter by engagement timestamps
  ([`9cdbbe2`](https://github.com/jpshackelford/ohtv/commit/9cdbbe2efa734a1d28a595f9aa4d4f7a463ce5ae))

Closes #180.

Threads a default-off `--event-dates` boolean flag through `list`, `search`, `ask`, `gen objs`, `gen
  titles`, and `gen run` (explicitly excluded from `refs` — refs are intrinsically
  action-timestamped). When set, the existing `--since` / `--until` / `-D` / `-W` filters re-target
  `conversation_engagement.first_event_ts` / `last_event_ts` instead of `conversations.created_at`,
  surfacing conversations whose engagement landed in the window regardless of when they were
  originally started.

Implementation highlights: - `ConversationStore.list_by_event_date_range(*, since, until, source,
  include_subs)` is the single SQL owner of the engagement-overlap predicate (since-only /
  until-only / interval-overlap branches). - INNER JOIN semantics: conversations without a
  `conversation_engagement` row are excluded under `--event-dates` (AC5), with an empty-result hint
  in `list` pointing at `ohtv db process engagement`. - Bare `--event-dates` (no date filter) raises
  `UsageError` exit 2 via `_validate_event_dates_args`, called early in `gen titles` / `gen run` so
  their default windows don't silently satisfy the gate (AC6). - Migration 024 adds covering indexes
  `idx_conv_engagement_last_event_ts` and `idx_conv_engagement_first_event_ts` on
  `conversation_engagement` so the JOIN stays O(log N) per predicate. - `--exact --event-dates` runs
  an inline chunked post-filter against `conversation_engagement` (FTS5 has no native date
  integration); the semantic search path pushes the predicate into
  `EmbeddingStore.search_conversations(..., event_dates=True)`. - `ohtv ask` captures
  `flags.event_dates` in its session telemetry blob (#162).

22 new tests across `tests/unit/db/stores/test_conversation_store_event_dates.py` (10 — predicate
  semantics, missing-engagement exclusion, source filter, roots-only, migration 024 indexes) and
  `tests/unit/test_cli_event_dates_filter.py` (12 — round-trip behavioral test, validation
  parametrized across 4 list/gen commands, empty-result hint, search FTS post-filter exclusion,
  search bare-flag UsageError). AC1–AC7 verified; manual test report posted by testing worker
  `66a5602` confirmed READY FOR MERGE across all 7 test groups.

Co-authored-by: openhands <openhands@all-hands.dev>

### Refactoring

- Extract _process_engagement_rows helper from _load_engagement_for_ids
  ([`fa4056d`](https://github.com/jpshackelford/ohtv/commit/fa4056d92304bf739f581e750f2b43b18613026b))

Pure depth-reduction refactor of `_load_engagement_for_ids` in `src/ohtv/cli.py`. Lifts the inner
  row-coercion + back-translation block into a new private helper `_process_engagement_rows`,
  dropping the chunk-loop body to four lines and reducing nested-block depth from 5 to 3.

Behavior is unchanged:

- Same single batched `WHERE conversation_id IN (...)` SELECT per `BATCH_SIZE = 900` ids. The
  load-bearing `test_chunk_query_count` invariant (1100 ids ⇒ exactly two SELECTs across the chunk
  boundary) stays green — the helper only consumes `cur.fetchall()`, so the proxy-class connection
  wrapper still observes the same `execute(...)` call count. - Same dashless ↔ dashed id
  back-translation via `normalized_to_original` (AGENTS.md item #14). - Same never-raise contract
  (Issues #167 / #168): the outer `try` / `except Exception: return engagement_map` guard is
  untouched. - Same `engagement_map[original] = row_dict` mutation semantics (later chunk wins on
  collision — exactly as before).

Tests: 86 targeted engagement tests pass; full suite 2592 passed, 2 skipped, 3 xfailed; ruff clean.
  Manual blackbox testing posted on the PR (12/12 PASS).

Pure internal refactor — no user-facing surface change, no docs update required.

Closes #173.


## v0.28.0 (2026-06-04)

### Chores

- **worklog**: Implementation worker — PR #178 opened (ready) for #162
  ([`d6c7248`](https://github.com/jpshackelford/ohtv/commit/d6c7248e4c57dd692e54c50569fd723ff45b3775))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker — PR #177 squash-merged (#161 closed)
  ([`d7dff8f`](https://github.com/jpshackelford/ohtv/commit/d7dff8fe7bbf4d40b6980eefa6bcb54904314cbe))

- **worklog**: Merge worker — PR #178 squash-merged (#162 closed)
  ([`928d3bf`](https://github.com/jpshackelford/ohtv/commit/928d3bf609ee205c38eb27d7294fd1e0e0de006a))

Records the squash-merge of PR #178 (telemetry capture for ohtv ask sessions). Issue #162
  auto-closed via Closes #162. Expected release: ohtv-v0.28.0 (minor bump from feat: subject)
  inbound via python-semantic-release. Not waiting for the release.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 15:48Z — spawned merge worker for PR #177
  ([`3873696`](https://github.com/jpshackelford/ohtv/commit/3873696096f3a413921f46b9600bbc2ee0b4cfb2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 16:19Z — spawned implementation worker for #162
  ([`3680875`](https://github.com/jpshackelford/ohtv/commit/3680875b24cc8ecf0688d950db63e1cec268f046))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 17:20Z — spawned merge worker for PR #178
  ([`8dcaa7a`](https://github.com/jpshackelford/ohtv/commit/8dcaa7a790e2ddea56b2d3bb6e840aeca3cf25c0))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #178 manual test pass
  ([`4a25b0b`](https://github.com/jpshackelford/ohtv/commit/4a25b0b8a801142ed544a16cccd127617e13a4f9))

10 blackbox scenarios + full unit suite all green; report posted to PR #178.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Testing worker spawned for PR #178
  ([`6a5189c`](https://github.com/jpshackelford/ohtv/commit/6a5189c30e89618b0ee7db95c02074ec12d808ec))

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **telemetry**: Record ohtv ask sessions to ~/.ohtv/telemetry/
  ([`0dbd6bb`](https://github.com/jpshackelford/ohtv/commit/0dbd6bb9b82de0b73a184c526292036cef9a9a18))

Capture every `ohtv ask` invocation as a self-contained, replay-friendly JSON blob under
  `~/.ohtv/telemetry/sessions/`, with an append-only `sessions.jsonl` index alongside. Designed as
  the comparison instrument for the #161 dual-mode (`--agent` vs `--agent-tools`) split.

Highlights: - `SessionRecorder` + `StepRecorder` (context manager) in
  `src/ohtv/analysis/telemetry.py`; both investigators take an optional `recorder=` kwarg
  (pass-through, no behaviour change when `None`). - Schema v1 with explicit `agent: null` (not key
  omission) for plain `ohtv ask`; `flags.agent_mode` mirrors `InvestigationResult.mode` (`"cli"` /
  `"tools"` / `null`). Filename grammar `YYYY-MM-DDTHH-MM-SSZ_<8hex>.json` (hyphens — `:` is
  reserved on Windows / breaks Dropbox-OneDrive sync). - Env-var contracts: `OHTV_TELEMETRY_DIR`
  overrides storage root; `OHTV_TELEMETRY_ENABLED=0` disables capture (recorder is never constructed
  — zero overhead). - Per-session blobs atomic via `tempfile` + `os.replace()`; `sessions.jsonl`
  appends are single sub-`PIPE_BUF` `write()`s under `O_APPEND` — no file locking needed
  (regression-tested with `multiprocessing.Process(2)`). - Graceful degradation: telemetry-dir write
  failures are swallowed in the `ask` handler's `try/finally` with a `log.warning`; `ohtv ask` still
  completes and prints its answer. - Docs: new `docs/reference/telemetry.md` (schema, layout, replay
  contract, env-var matrix); AGENTS.md item #34.

Tests: 28 new unit tests (`tests/unit/analysis/test_telemetry.py`) + 4 new CLI integration tests
  (`tests/unit/test_cli_ask_telemetry.py`). Full suite: 2592 passed, 2 skipped, 3 xfailed. Manual
  blackbox covered 11 scenarios — all PASS.

Closes #162


## v0.27.0 (2026-06-04)

### Chores

- **worklog**: Implementation worker — PR #177 opened (issue #161)
  ([`d4aa8df`](https://github.com/jpshackelford/ohtv/commit/d4aa8dfb68448c43753be1752b34babd46401278))

- **worklog**: Merge worker — PR #175 squash-merged (#170 closed)
  ([`f06f359`](https://github.com/jpshackelford/ohtv/commit/f06f35969fa6ea2473d2dd58c50e63cc95f56dbc))

Engagement-metric family 4/4 complete. Release workflow in flight for ohtv-v0.26.0 (run
  26952816438).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 13:18Z — spawn impl worker for #161 (ohtv ask agent mode)
  ([`1e30dee`](https://github.com/jpshackelford/ohtv/commit/1e30dee1666184d0c2c51289ea435c1a28f2c20e))

- **worklog**: Orchestrator 13:51Z — PR #177 opened by impl worker, waiting on completion
  ([`333f99c`](https://github.com/jpshackelford/ohtv/commit/333f99c6339b52f61631926c75ae76654d5a9d0e))

- **worklog**: Orchestrator 14:20Z — spawned testing worker for PR #177
  ([`407df00`](https://github.com/jpshackelford/ohtv/commit/407df0047f83ab6ebb0e990ef4e18b1e72d49b3d))

- **worklog**: Orchestrator 14:50Z — spawned review worker for PR #177
  ([`a2291f3`](https://github.com/jpshackelford/ohtv/commit/a2291f3f912c74223971cd208ea53d46057c72ce))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 15:18Z — spawned re-testing worker for PR #177
  ([`39956b1`](https://github.com/jpshackelford/ohtv/commit/39956b1fc863e3b5944eb0c745e165a6e58e60d3))

- **worklog**: Orchestrator cycle 12:50Z — spawn merge worker for PR #175 + truncate worklog
  ([`bc7076a`](https://github.com/jpshackelford/ohtv/commit/bc7076abd71892b753b45fa85f70f55890f8c438))

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **ask**: Add prompt-cookbook agent mode alongside legacy tools mode
  ([`722ce44`](https://github.com/jpshackelford/ohtv/commit/722ce443c84d1f5f0941f344af55c25b758301ce))

Closes #161.

Adds a second multi-turn investigation path for `ohtv ask` that runs side-by-side with the existing
  custom-tools agent, so we can A/B compare prompt-cookbook vs bespoke-tool approaches before
  retiring either. Issue #162 will hang telemetry off the new `InvestigationResult.mode` field.

User-facing changes:

* `--agent` now selects the prompt-cookbook agent (`cli` mode) and emits a one-line stderr notice
  pointing scripted callers at `--agent-tools` if they want the original 4-tool behaviour. Stdout /
  JSON pipes are undisturbed. * `--agent-tools` preserves the legacy 4-tool custom-tools agent
  (#51). * The two flags are mutually exclusive (Click `UsageError`). * `--max-steps 0`
  short-circuits both modes to single-turn RAG. * `ohtv gen objs --cache-only` is promoted to a
  first-class CLI flag that returns cached analyses without invoking the LLM. The runner also
  auto-injects `--cache-only` on any `gen objs` invocation so the agent can never trigger fresh
  analyses. * `gen objs --cache-only -F json` now emits top-level `goal: null` on cache miss instead
  of the human-readable placeholder string, so JSON consumers get a real null to branch on.

Architecture highlights:

* New `InvestigationResult.mode: Literal["tools", "cli"]` (defaults to `"tools"` for back-compat
  with existing fixtures). Both modes return identically-shaped results, verified in
  `tests/integration/test_ask_dual_mode.py`. * `src/ohtv/analysis/ohtv_runner.py` runs `ohtv`
  in-process via Click 8.3's `CliRunner` with disjoint allow- and block-lists (enforced by unit
  test). Block-list rejections are surfaced as structured observations so the agent can self-correct
  in one turn. * `src/ohtv/analysis/investigator_cli.py` wires `InvestigationAgentCli` with the
  cookbook prompt; `COOKBOOK_EXAMPLES` is extracted from `COOKBOOK_PROMPT` for easier reuse /
  testing. The cookbook is snapshot-tested so it cannot drift from the runner allow-list. *
  `conversations_examined` is populated by both modes via observation hooks (tools) or argv ID
  extraction (cli), matching AGENTS.md #14.

Review-round follow-ups squashed into this PR:

* QA: `gen objs --cache-only -F json` cache-miss → `goal: null` fix. * DX: stderr behavioural-change
  notice for `--agent`. * Refactor: extract `COOKBOOK_EXAMPLES` from `COOKBOOK_PROMPT`. * Docs:
  `run_ohtv` docstring clarifies soft-timeout semantics (logged but not enforced; bounded by the
  upstream session iteration cap).

Tests: 2553 passed, 2 skipped, 3 xfailed (no regressions; all xfails pre-date this PR). 61 new tests
  across 6 files cover allow/block-list, cache-only injection, ID extraction, mode banner, flag
  parsing, mutual exclusion, dual-mode integration, and the cookbook snapshot.

Docs: `docs/guides/search-and-ask.md` §"Investigation Mode" updated with full user-facing reference
  for both modes; `AGENTS.md` item #33 adds architectural notes for future agents touching the
  dispatch / runner / cookbook.

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.26.0 (2026-06-04)

### Chores

- **worklog**: Docs worker — PR #175 docs landed (README + 2 guides + cli.md ref)
  ([`4077c70`](https://github.com/jpshackelford/ohtv/commit/4077c70ea7cb001ae5d8619d08b1a239c2144997))

- **worklog**: Orchestrator 2026-06-04 10:50 UTC — spawn impl worker for #170 after #174 merge
  ([`25bd77a`](https://github.com/jpshackelford/ohtv/commit/25bd77a4d12e90de4557f551ec278657eb844efa))

- **worklog**: Orchestrator 2026-06-04T12:21Z — spawned review worker for PR #175
  ([`7736ba5`](https://github.com/jpshackelford/ohtv/commit/7736ba5841c1ebe44bac2ffd1825b4673d474538))

- **worklog**: Orchestrator — spawned testing worker for PR #175
  ([`9ab54ae`](https://github.com/jpshackelford/ohtv/commit/9ab54ae32978c1c566ba420bdd8995ce318a58ef))

Conv: 325ebc8 (Manual Test, PR #175 engagement filters)

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #175 review round 1 — single thread resolved (7a067f7)
  ([`71b2942`](https://github.com/jpshackelford/ohtv/commit/71b2942df61f535e64f69012c10a32795979a76d))

- **worklog**: Record PR #175 (Issue #170 engagement filters)
  ([`2a8eab0`](https://github.com/jpshackelford/ohtv/commit/2a8eab0264e1573238f5946c20c4ad5ff593719d))

- **worklog**: Spawn docs worker for PR #175 (engagement filters)
  ([`c291836`](https://github.com/jpshackelford/ohtv/commit/c291836281860daa5b586f59e03ddac5c353053a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Testing worker — PR #175 manual blackbox (ALL PASS)
  ([`1bed76f`](https://github.com/jpshackelford/ohtv/commit/1bed76f8f5e024e6f9f3bf2bc40bb1437d8f4f76))

Co-authored-by: openhands <openhands@all-hands.dev>

### Documentation

- Add engagement threshold empirical tuning analysis
  ([#176](https://github.com/jpshackelford/ohtv/pull/176),
  [`86c3750`](https://github.com/jpshackelford/ohtv/commit/86c37508fc99d7c27889f43fa7a621828129e1d6))

This adds the findings from an empirical analysis of the engagement threshold (T) parameter
  introduced in PR #165. The analysis processed 4,791 conversations with 9,935 follow-up user
  message gaps.

Key findings: - ~70% of follow-up messages occur within 30 seconds - 96.1% occur within 12 minutes -
  Content analysis shows ~65% of 8-12 min gaps are likely inattention - The 12-minute default is
  reasonable; 10 min slightly more defensible

New files: - docs/design/engagement-threshold-analysis.md: Full findings document -
  scripts/analyze_engagement.py: Basic gap distribution analysis -
  scripts/analyze_gaps_with_content.py: Content-aware gap analysis

Related: #163, #165, #167, #168, #169, #170

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **filter**: Add engagement-level filters to `list` and `gen` subcommands
  ([`3c8c527`](https://github.com/jpshackelford/ohtv/commit/3c8c52721b4330afbc89887435d1293400fecf0f))

Adds four engagement-metric filters — `--engaged`, `--no-engaged`, `--min-engaged DURATION`,
  `--min-engagement-ratio PCT` — to `ohtv list`, `gen objs`, `gen titles`, and `gen run`. All four
  call sites share one decorator + validator, so mutex/range/parse errors exit with code 2 before
  any DB work.

The threshold flags (`--min-engaged`, `--min-engagement-ratio`) AND-compose with both `--engaged`
  and every other existing filter (`--since`, `--repo`, `--label`, `--pr`, `--action`,
  `--errors-only`, …). Missing-row semantics follow the issue truth table — only `--no-engaged`
  treats a missing `conversation_engagement` row as "include". Engagement rows are loaded via the
  existing batched `_load_engagement_for_conversations` helper (single query, chunked at 900 IDs —
  zero per-row queries).

Also exposes `ohtv.filters.parse_duration_to_seconds` (accepts `Ns`/`Nm`/`Nh`/combinations like
  `1h30m`, bare numbers = minutes, case-insensitive).

Test coverage: 2492 unit tests pass (90 new). Documentation updated across README.md,
  docs/guides/analysis.md, docs/guides/exploration.md, and docs/reference/cli.md.

Closes #170.


## v0.25.0 (2026-06-04)

### Chores

- **worklog**: Docs worker for PR #174 completed
  ([`c7aef2b`](https://github.com/jpshackelford/ohtv/commit/c7aef2b196739d2baae57284893d8359db9a41d0))

- **worklog**: Expansion worker @ 2026-06-04T08:23Z — issue #173 ready
  ([`ae22b4d`](https://github.com/jpshackelford/ohtv/commit/ae22b4d890821cfe0dc09c3176576999ab897c69))

Added Technical Approach comment to #173 (refactor: reduce nesting in _load_engagement_for_ids) and
  applied the 'ready' label. Pure issue metadata; no code changes.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Implementation worker @ 2026-06-04T08:20Z — PR #174 open for Issue #169 (engagement
  in gen objs markdown)
  ([`23fd17a`](https://github.com/jpshackelford/ohtv/commit/23fd17a94b559a8386686f086caa252471042915))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge PR #172 (issue #168) — ohtv-v0.24.0 released
  ([`5674c2c`](https://github.com/jpshackelford/ohtv/commit/5674c2cf438ee2307d3cdfc7aa4b3f45172750f6))

- **worklog**: Merge worker — PR #174 squash-merged (#169 closed)
  ([`b2182c1`](https://github.com/jpshackelford/ohtv/commit/b2182c1dc50c9495ef3bba97ca20c88b955650c7))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 09:50Z - spawn testing worker for PR #174
  ([`aff3f9f`](https://github.com/jpshackelford/ohtv/commit/aff3f9f5f89eba38dbf40c0923194095dda5c9e9))

- **worklog**: Orchestrator @ 2026-06-04T07:50Z — spawned merge worker; PR #172 was human-merged
  mid-cycle
  ([`9c92e8b`](https://github.com/jpshackelford/ohtv/commit/9c92e8b2503898ded48c606ff49227326c07a38b))

- **worklog**: Orchestrator @ 2026-06-04T08:20Z — PR #172 merged; spawned impl #169 + expansion #173
  ([`141d4b8`](https://github.com/jpshackelford/ohtv/commit/141d4b8e3f0b243178f49596b25e6b3747e99f24))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle @ 2026-06-04T08:51Z — PR #174 docs worker spawned
  ([`4779823`](https://github.com/jpshackelford/ohtv/commit/4779823ef19a6962118afc95a5c20a9065d151d7))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle @ 2026-06-04T09:23Z — PR #174 docs worker re-spawned (API
  field-name bug diagnosed)
  ([`e51a611`](https://github.com/jpshackelford/ohtv/commit/e51a611c99fa4dbfb03582f62c44a7996d7e4ab8))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Testing worker — PR #174 manual blackbox test (PASS)
  ([`96d5697`](https://github.com/jpshackelford/ohtv/commit/96d56974985b887ecf2e291bd5f106552c82b73d))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Truncate to 6h productive window, spawn merge worker for PR #174
  ([`d67c952`](https://github.com/jpshackelford/ohtv/commit/d67c95228c88bdf238cbe6c511e89d3309953f35))

- Truncated WORKLOG.md from 2464 → ~1000 lines (kept 19 entries, archived 26 across 4 dated archive
  files).

- Orchestrator 10:20Z cycle: PR #174 met merge criteria → spawned merge worker (conv 002934f).

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- Add engagement to gen objs markdown output
  ([#169](https://github.com/jpshackelford/ohtv/pull/169),
  [`f140744`](https://github.com/jpshackelford/ohtv/commit/f140744e5199f30f94d326a0dfbc19c746941a2d))

Adds an `Engaged: <duration> in N period[s] (X.X%)` sub-bullet to `ohtv gen objs --with-engagement
  -F markdown`, placed immediately below each conversation's parent bullet and above the existing
  refs / labels lines.

- New helper `_format_engaged_markdown_subbullet` mirrors the precision and grammar of
  `_format_engaged_line` but drops the `of <duration> total` suffix because the parent bullet
  already shows duration inline. Returns `None` when the engagement row is missing so the sub-bullet
  is silently omitted (no `Engaged: -`). - `_run_batch_objectives_analysis` now batch-loads
  engagement rows ONCE before format dispatch, shared by the JSON (#168) and markdown (#169) paths —
  no N+1 in either. - `-F table` and flag-off `-F markdown` outputs are byte-identical to pre-#169,
  regression-tested. - Help text on `--with-engagement` updated to document the markdown effect
  alongside JSON.

29 new unit tests in `tests/unit/test_cli_gen_objs_engagement_markdown.py`; 2353 unit tests pass.
  Manual blackbox: 15/15 scenarios pass — see PR comment for the full report.

Engagement-metric family progress: #167 ✅, #168 ✅, #169 ✅ (this); #170 is next.

Closes #169


## v0.24.0 (2026-06-04)

### Chores

- **worklog**: Orchestrator @ 2026-06-04T07:20Z — spawned testing worker for PR #172
  ([`67d1c8b`](https://github.com/jpshackelford/ohtv/commit/67d1c8b24185249caf85c4ad1dea983779c566a2))

- **worklog**: Orchestrator cycle 2026-06-04 06:21 UTC — spawn impl worker for #168
  ([`9b578ef`](https://github.com/jpshackelford/ohtv/commit/9b578ef2f3b2d08bec683e48208416a08efe578d))

- **worklog**: Orchestrator cycle — PR #172 → docs worker (5a0f995) spawned
  ([`f4542fe`](https://github.com/jpshackelford/ohtv/commit/f4542fee52d8321d34aaedfa5cd704bdae2cc2a2))

### Documentation

- **worklog**: Impl worker — Issue #168 (PR #172) draft→ready, CI green
  ([`f5dfd45`](https://github.com/jpshackelford/ohtv/commit/f5dfd457cb9c8ecb5d1a3e47a06a48b51fe57741))

### Features

- Add --with-engagement flag to gen objs JSON output
  ([`01b4e7f`](https://github.com/jpshackelford/ohtv/commit/01b4e7fd3607f9b67f9a6d88b0ec98b395cbd40f))

Adds an opt-in `--with-engagement` flag to `ohtv gen objs` that surfaces the sustained-attention
  metric across the JSON exporter, in both single-conversation (`gen objs <id> --json`) and
  multi-conversation (`gen objs -F json`) modes.

When the flag is set, the JSON payload gains five fields per conversation: `engaged_seconds`,
  `attention_periods`, `engagement_threshold_seconds`, `total_duration_seconds`, and
  `engagement_ratio`. Missing rows emit JSON `null` for every field so the schema is stable across
  rows — consumers can rely on `engagement_ratio` being either a float in `[0.0, 1.0]` rounded to 4
  decimals or `null`. Engagement rows come from the `engagement` indexing stage (`ohtv db process
  engagement`); without it all five fields render as `null`, but rows are never filtered out.

This completes the engagement-metric family for `gen objs` after PR #165 wired engagement into `ohtv
  show -F json` and PR #171 added the engagement columns to `ohtv list`. The schema and semantics
  here are deliberately identical to those two surfaces so consumers can mix and match outputs
  without translation.

The flag is JSON-only by design: passing `--with-engagement` with `-F table` or `-F markdown` is a
  silent no-op so users can leave it in their aliases and switch formats freely. Markdown engagement
  output is tracked separately in issue #169; engagement-based filtering (e.g.
  `--min-engaged-seconds`) is tracked in issue #170.

Internally, `_load_engagement_for_ids` was extracted as the ID-based sibling of
  `_load_engagement_for_conversations` (now a thin delegator). It uses the same batched-query /
  900-chunk / dashless normalization semantics that AGENTS.md item #14 codifies, so the
  single-batched-SELECT performance characteristic is preserved across both call sites. A follow-up
  to reduce nesting in `_load_engagement_for_ids` is tracked separately.

Fixes #168.

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.23.0 (2026-06-04)

### Chores

- **worklog**: Expand Issue #169 (engagement in gen objs markdown)
  ([`d17bf71`](https://github.com/jpshackelford/ohtv/commit/d17bf716d8ab9bb5a9c36523017927d672fd002c))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Expansion worker for Issue #170 (engagement filter flags)
  ([`a5d28f4`](https://github.com/jpshackelford/ohtv/commit/a5d28f47568f51e3468859d1627a82c6c11c039b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Implementation worker for Issue #167 (PR #171)
  ([`e4078b0`](https://github.com/jpshackelford/ohtv/commit/e4078b0a695e1a1d15a6ecfcebb04ceba0df5fa5))

- **worklog**: Orchestrator cycle 2026-06-04 03:51Z - docs + expansion workers
  ([`42480d4`](https://github.com/jpshackelford/ohtv/commit/42480d476aa0ef630a00b42455bd7f11ab33f97d))

- **worklog**: Orchestrator cycle 2026-06-04 04:51Z — spawn review worker for PR #171
  ([`2865f5a`](https://github.com/jpshackelford/ohtv/commit/2865f5a922de2b3b9a2f02188e17ac8ffd174b28))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn merge worker for PR #171
  ([`2865a31`](https://github.com/jpshackelford/ohtv/commit/2865a31bbe514d8a78920f2b9f37bed2acdebc63))

- **worklog**: Orchestrator spawn re-test worker for PR #171
  ([`c437c87`](https://github.com/jpshackelford/ohtv/commit/c437c87e808c9d2c287f210dbd8352bfa7f87f10))

- **worklog**: Orchestrator spawned impl #167 + expansion #169
  ([`bf492e8`](https://github.com/jpshackelford/ohtv/commit/bf492e8a98aeb54adb6bce209e637eb4a4675be1))

- **worklog**: Record merge of PR #171 (engagement columns)
  ([`02e618f`](https://github.com/jpshackelford/ohtv/commit/02e618f1781f183a2230ee0d090a64aaf9fee0a7))

_This commit was authored by an AI agent (OpenHands) on behalf of @jpshackelford._

- **worklog**: Record PR #171 review-feedback completion
  ([`4675e95`](https://github.com/jpshackelford/ohtv/commit/4675e95ecd70bf8b1a8701c377c4ed0b7d6a2a24))

- **worklog**: Testing worker spawned for PR #171 (#170 expanded, queue empty)
  ([`26f0f70`](https://github.com/jpshackelford/ohtv/commit/26f0f70dd8f652ce1b45b8cacab44b6c8875e5a4))

### Features

- Add engagement columns to ohtv list output
  ([#171](https://github.com/jpshackelford/ohtv/pull/171),
  [`fe476c7`](https://github.com/jpshackelford/ohtv/commit/fe476c776d3fda7e7deade9eb7cb9ef7a5c7b4c6))

Adds an opt-in `--with-engagement` flag to `ohtv list` that surfaces the engagement metric (added by
  PR #165 to per-conversation `ohtv show`) across many conversations in the same view. The flag is
  purely a display flag — it never filters rows out, and it composes with every existing filter /
  display flag on `ohtv list`.

What ships:

* Table view adds three columns when set: `Engaged`, `Periods`, `Eng%`. Missing rows render as dim
  `-` so conversations whose engagement stage hasn't run are still listed, never silently dropped. *
  JSON output adds five fields matching the schema PR #165 established on `ohtv show <id> -F json`:
  `engaged_seconds`, `attention_periods`, `engagement_threshold_seconds`, `total_duration_seconds`,
  plus the computed `engagement_ratio`. Missing values emit JSON `null`. * CSV output appends the
  same five columns to the existing header. Empty strings for missing values; zeros preserved as
  `0`. * `_load_engagement_for_conversations` issues a single batched `SELECT ... WHERE
  conversation_id IN (?, ?, ...)` against the `conversation_engagement` table (migration 023),
  chunked at 900 IDs per batch to stay under SQLite's default ~999 parameter ceiling. Normalizes
  dashed LocalSource ids to dashless before lookup (AGENTS.md item #14). * Shared
  `_validate_engagement_values` helper and `_engagement_csv_row` builder (DRY refactor from review
  feedback) keep the formatters and CSV emitter on a single code path for present-vs-missing rows.

Tests: 36 new in `tests/unit/test_cli_list_engagement.py` cover the formatters, the batch DB loader
  (empty input, missing DB, present/missing rows, dashed-ID normalization, 1100-row chunking), the
  JSON/CSV emitters (schema stability across rows), and the rich table column rendering
  (with/without flag, idle composition). Full suite: 2351 passed, 2 skipped, 3 xfailed.

Docs: `docs/guides/exploration.md` and `docs/reference/cli.md` updated with `--with-engagement`
  examples and the `ohtv db process all` dependency.

Fixes #167.

This commit was authored by an AI agent (OpenHands) on behalf of @jpshackelford.

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.22.0 (2026-06-04)

### Chores

- **worklog**: Expansion worker for Issue #167
  ([`1befcee`](https://github.com/jpshackelford/ohtv/commit/1befceef4eeffaaf2ee7aed3fcad797384c6622b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-04 02:51Z — merged PR #166 (list_conversations tool, ca60a11)
  ([`e1155d4`](https://github.com/jpshackelford/ohtv/commit/e1155d49860aa3245e9b1957d099ddf6daddcfab))

- **worklog**: Orchestrator 2026-06-04T00:52Z - spawn impl worker for #160
  ([`6a0ce06`](https://github.com/jpshackelford/ohtv/commit/6a0ce0627806c11898e46fc3b9b1b79c2aee8419))

PR #165 merged at 00:25:43Z (commit d8a94da3a2); ohtv 0.21.0 shipped. Issue #163 auto-closed.
  Testing worker 487b7e1 did succeed (posted Manual Test Results at 23:59:45Z PASS before clean
  exit) — prior 23:53Z orchestrator read was wrong. Spawned implementation worker 8fe6274 for Issue
  #160 (list_conversations agent tool, priority:medium).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned expansion worker for #167 [skip ci]
  ([`ae2a8ec`](https://github.com/jpshackelford/ohtv/commit/ae2a8ec5e6693e9f9c6a15a36034165a313d5cf6))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing worker for PR #166
  ([`9deaaa5`](https://github.com/jpshackelford/ohtv/commit/9deaaa55b0785052fba830eee97557fe4cd34dac))

### Documentation

- **worklog**: Orchestrator spawned docs worker for PR #166
  ([`e0bc788`](https://github.com/jpshackelford/ohtv/commit/e0bc78811c79f8c8cd805462ac1ac678b8b80e9b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned merge worker for PR #166 + expansion for #168
  ([`79c3170`](https://github.com/jpshackelford/ohtv/commit/79c31707405952e423d6aece1f8d87b9377f4ad7))

- **worklog**: Worker entry for PR #166 (Issue #160 — list_conversations agent tool)
  ([`6e09a9d`](https://github.com/jpshackelford/ohtv/commit/6e09a9d7c97825b71bbbfaac3bef23f82185ee9c))

### Features

- Add list_conversations tool to ohtv ask --agent investigator
  ([#166](https://github.com/jpshackelford/ohtv/pull/166),
  [`ca60a11`](https://github.com/jpshackelford/ohtv/commit/ca60a1116c20d51e0441e64555f000c038595b3e))

Closes #160.

Adds a fourth tool to the `InvestigationAgent` — `list_conversations` — that enumerates
  conversations by metadata (date / repo / PR / action / label) rather than by semantic similarity.
  This closes the class of temporal, enumerative, aggregative, and verify-a-negative questions that
  vector search fundamentally cannot answer well (e.g. "what did we work on yesterday?", "every conv
  that touched repo X this week", "did we work on Y at all?").

User-facing changes:

- New `list_conversations` tool on the investigator agent (`ohtv ask --agent`) with the same filter
  surface as `ohtv gen objs` multi-conv mode
  (`since`/`until`/`day`/`week`/`repo`/`pr`/`action`/`label`/`limit`/ `include_sub_conversations`).
  Reads-only from the warm `gen objs` brief cache; never triggers LLM analysis on a miss
  (`goal=None` is the signal). - `include_sub_conversations` defaults to `False` (roots-only,
  matching the post-Issue #125 CLI default). - Hard cap of `LIST_CONVERSATIONS_MAX_LIMIT = 50` on
  the result list to keep the observation inside the prompt budget; oversize requests are silently
  capped, not rejected. The `total_matching` count is always returned so the agent knows whether it
  saw the full set. - System prompt updated to steer the agent toward `list_conversations` for
  temporal / enumerative / verify-a-negative questions and toward `search_conversations` for
  similarity questions. - New docs: `docs/guides/search-and-ask.md` — full filter table, observation
  shape, cache-miss semantics, and an investigator-mode workflow example.

Tests: 2266 unit tests pass (`uv run pytest tests/unit`). Manual smoke test

on a 250-conversation cloud sync (PR #166 comment, T1-T10) all PASS: temporal cue routes to
  `list_conversations` (T2), enumerative + `repo` filter (T3), `limit` silent cap at 50 (T4),
  `include_sub_conversations` default + invariant (T5, unit-covered), cache miss → `goal=None`
  graceful (T6), verify-a-negative cue (T7), system-prompt cues present (T8), docs match
  implementation (T9), no regression in non-`--agent` commands (T10).

_This commit was created by an AI agent (OpenHands) on behalf of @jpshackelford._


## v0.21.0 (2026-06-04)

### Chores

- **worklog**: 22:20z spawned implementation worker for #163; PR #164 merged - bootstrap loop closed
  ([`18febfc`](https://github.com/jpshackelford/ohtv/commit/18febfc3cc71ad0dc0d8880c263344dcf09711db))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Auto-disable orchestrator after 3rd consecutive quiet cycle
  ([`eb47113`](https://github.com/jpshackelford/ohtv/commit/eb4711319cd3915211dfe73004f19175cc11b9bf))

3rd consecutive quiet cycle (14:18Z, 14:48Z, 15:17Z): PR #164 still draft+unchanged, expansion queue
  empty. Per /orchestrate skill, PATCHed automation c202ca20-60d5-4f5b-9d53-3d7308c1d95b to
  disabled.

Re-enable path documented in WORKLOG entry.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Docs worker entry for PR #165
  ([`fecc8a8`](https://github.com/jpshackelford/ohtv/commit/fecc8a808f96b4009511093a0cbf7c3d9e8cf343))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Expansion of #162 (telemetry capture for ohtv ask)
  ([`085f71c`](https://github.com/jpshackelford/ohtv/commit/085f71c612812e9e5675d875733f3a2f3ccf833b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Expansion worker completed issue #161 (ready)
  ([`b9dd004`](https://github.com/jpshackelford/ohtv/commit/b9dd00487720a1dfcf5f782205a52c9d6e081f8a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge complete PR #159
  ([`d8e5792`](https://github.com/jpshackelford/ohtv/commit/d8e57925339be8452a9217344bb8d15ff2c4ce4b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 14:18Z — all quiet, PR #164 still draft
  ([`480629a`](https://github.com/jpshackelford/ohtv/commit/480629a0110a06d0cd587ec95bf53c0701e70fa6))

First quiet cycle of new streak (counter 0→1). Expansion queue drained, PR slot held by draft PR
  #164.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 14:48Z — 2nd quiet cycle + truncation
  ([`60040c1`](https://github.com/jpshackelford/ohtv/commit/60040c1bc3f736a9b8607725529e82598c8235c4))

Truncated WORKLOG.md from 1752 to 418 lines (16 entries archived to WORKLOG_ARCHIVE_2026-05-30.md).
  PR #164 still draft (unchanged since 13:22Z) holds the PR slot; expansion queue is empty. Second
  consecutive quiet cycle — auto-disable precondition (QUIET_COUNT>=2) not yet met this cycle, but
  will be next cycle if PR #164 stays untouched.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-03 23:16Z — spawned testing worker e85cba5 for PR #165
  ([`1cfdaa0`](https://github.com/jpshackelford/ohtv/commit/1cfdaa02d850dfd7d44e0a2dd13a06d400fc0185))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-06-03 23:53Z — recovered from paused testing worker e85cba5 by
  spawning 487b7e1 for PR #165
  ([`ca7a820`](https://github.com/jpshackelford/ohtv/commit/ca7a820bd19433f805ec89195bb57baa50adb433))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator auto-disabled at 2026-05-30T19:18Z — 3 quiet cycles
  ([`59ad482`](https://github.com/jpshackelford/ohtv/commit/59ad48277e235e98a63f893dc702083a8e5a7307))

- **worklog**: Orchestrator cycle 2026-05-30T18:48Z — 2nd quiet cycle
  ([`30e616b`](https://github.com/jpshackelford/ohtv/commit/30e616b5b43b28197f03ce28093c3161f590bd1f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle — spawned expansion worker for #162
  ([`fa71e9e`](https://github.com/jpshackelford/ohtv/commit/fa71e9e5237d7a3a433156d57f56de6eabfe7296))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned docs worker 88315ec for PR #165
  ([`d2a82aa`](https://github.com/jpshackelford/ohtv/commit/d2a82aa5d3c24dc21e5f813926d3e3fe3d5b3203))

- **worklog**: Orchestrator spawned expansion worker for #161 at 2026-06-02T13:27Z
  ([`42da672`](https://github.com/jpshackelford/ohtv/commit/42da6727ef109c8d45bd52ba85a540cbd49ac737))

- **worklog**: Record manual triage — #163 ready, #164 opened, automation re-enabled
  ([`901fd0c`](https://github.com/jpshackelford/ohtv/commit/901fd0c3841ca8e45c2648b9de9c23725a3f0658))

Adds audit-trail entry for the human-triage session at 2026-06-02 13:22Z–13:30Z (conversation
  045be10):

- Opened PR #164 (port voice-relay's enable-orchestrator.yml to ohtv) - Manually re-enabled the OHTV
  Workflow Orchestrator (one-shot bridge) - Bumped #163 priority:medium → priority:high - Added
  'ready' label to #163, skipping expansion per expand-issue.md skill audit; recorded recommended
  defaults for the 4 open questions inline so an impl-worker can adopt without escalation

The 13:27Z orchestrator cycle prediction ('expansion target after #161 = #163') is now obsolete;
  next-up for expansion is #162. Once PR #164 clears the PR slot, #163 wins the impl slot ahead of
  #160.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn testing worker for PR #164 after re-enable
  ([`0a71e46`](https://github.com/jpshackelford/ohtv/commit/0a71e463319302841aa55884c2d8e1d98e878c64))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Truncate to 6h productive window + 18:18Z all-quiet cycle
  ([`be594af`](https://github.com/jpshackelford/ohtv/commit/be594af1604675529e0d6531c733ad5382cc43e4))

Cluster of 6 releases (v0.17.0 → v0.20.0) complete with PR #159 merge. Both slots idle; backlog has
  only hold-labelled issues (#90, #26). Auto-disable counter 0 → 1. Next quiet cycle at ~19:18Z
  would disable. Archived 8 entries (08:50Z–11:10Z) to WORKLOG_ARCHIVE_2026-05-30.md.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Worker complete — PR #165 for engaged-human-minutes
  ([#163](https://github.com/jpshackelford/ohtv/pull/163),
  [`cdb3632`](https://github.com/jpshackelford/ohtv/commit/cdb3632e650b549b299506a96420cc933079651f))

Co-authored-by: openhands <openhands@all-hands.dev>

### Continuous Integration

- Add enable-orchestrator workflow ([#164](https://github.com/jpshackelford/ohtv/pull/164),
  [`4828325`](https://github.com/jpshackelford/ohtv/commit/48283253eff0f5e4f4a89b991cc63d034a37c008))

Auto-re-enables the OHTV Workflow Orchestrator automation (`c202ca20-…`) when a new issue or PR
  opens, mirroring the same workflow in `jpshackelford/voice-relay`. Run is hardened with `set -euo
  pipefail`, `curl -sf` + explicit error traps on both API calls, and `exit 1` on unexpected
  payloads — silent-failure modes should not exist in the workflow whose job is to surface them.

Closes the gap that left the orchestrator dormant for ~66h between the 2026-05-30 19:18Z
  auto-disable and the 2026-06-02 13:22Z manual re-enable while issues #160–#163 piled up.

### Features

- Engaged-human-minutes per-conversation metric (#163)
  ([#165](https://github.com/jpshackelford/ohtv/pull/165),
  [`d8a94da`](https://github.com/jpshackelford/ohtv/commit/d8a94da3a26696823a95cc4ed38e5002cd2e2cf4))

Add a per-conversation engaged-human-minutes metric that estimates how long a human was actively
  monitoring/steering each conversation, inferred from temporal gaps around each user message. Two
  related numbers fall out of the same pass — attention_periods (distinct "human was here" windows)
  and a total_duration_seconds derived from `last_event_ts - first_event_ts`.

Algorithm (timing-only, content-blind): - For each follow-up user message Uᵢ, if the gap from the
  previous event is ≤ T (default 12 min), record an attended block. - Merge adjacent blocks with
  seam ≤ T into one attention period. - engaged_seconds = sum of merged period durations.

Changes: - Migration 023 adds `conversation_engagement` table (threshold stored per row so
  tuning-sweep variants stay distinguishable). - New `engagement` stage registered after
  `contributions`; `db process all` picks it up automatically. - `--threshold N` flag on `ohtv db
  process` (consumed only by engagement; silently ignored by other stages). - `ohtv show <id>` gains
  an `Engaged:` line in text/markdown, and JSON adds `engaged_seconds`, `attention_periods`,
  `engagement_threshold_seconds`, `total_duration_seconds`. -
  `scripts/engagement_threshold_sweep.py` for non-destructive offline tuning. - Docs landed in
  `docs/design/conversation-metrics.md`, `docs/guides/indexing.md`, and
  `docs/guides/exploration.md`.

Tests: 63 new tests (35 stage, 28 CLI display); full suite 2228 passed, 2

skipped, 3 xfailed. Manual verification on PR comment: 18/18 PASS including all documented CLI
  invocations and JSON shapes.

Fixes #163

---

_This PR was implemented, reviewed, tested, and merged by AI agents (OpenHands) on behalf of
  @jpshackelford. The merge was executed inline by the orchestrator (conv `41bc06d`) after two
  consecutive spawn attempts for a merge worker (`470ea49`, `3bb7299`) stalled with the
  sandbox=RUNNING / execution=idle / cost=null / updated_at==created_at pattern previously observed
  on `e85cba5`._


## v0.20.0 (2026-05-30)

### Chores

- **worklog**: Impl worker logged PR #159 (issue #145)
  ([`a8d9df6`](https://github.com/jpshackelford/ohtv/commit/a8d9df688a2b6830832a8c462be5c046531f10af))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T15:52:00Z - spawned merge worker for PR #158
  ([`951071d`](https://github.com/jpshackelford/ohtv/commit/951071d7a152f869343cd4e209bbd8c1c797f7d9))

- **worklog**: Orchestrator 2026-05-30T16:18Z - spawn impl worker for #145
  ([`6bf75c0`](https://github.com/jpshackelford/ohtv/commit/6bf75c02579761546b36a601bd77db18dc2d8ccb))

Spawned implementation worker conversation c1d4764b for Issue #145 (gen objs key variants on context
  promotion).

PR #158 merged, ohtv-v0.19.1 released. Both worker slots clear at cycle entry. #145 is the only
  ready+prioritized issue remaining; impl worker dispatched with full implementation guidance and AC
  mapping.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator re-spawned testing worker for PR #159 after ghost
  ([`82c3c52`](https://github.com/jpshackelford/ohtv/commit/82c3c529d4d3cf34a3cdce02f11cb7825dd61548))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned merge worker for PR #159
  ([`29fbf8b`](https://github.com/jpshackelford/ohtv/commit/29fbf8b6ababa6b525dcf3736980d11cd3ef6a88))

Sixth and final merge in the cluster pending. Corrects prior cycle's ghost misclassification of
  c9629a6 (it posted the full test report).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing worker for PR #159
  ([`48c4cdb`](https://github.com/jpshackelford/ohtv/commit/48c4cdb68cfbda0275434e485ab084edda4b1c55))

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **gen-objs**: Warm key cache variants when context auto-promotes
  ([#145](https://github.com/jpshackelford/ohtv/pull/145),
  [`b626f49`](https://github.com/jpshackelford/ohtv/commit/b626f4937f5f1b77db52a890ff8190ae48635449))

## Summary

When `analyze_objectives` auto-promotes the context level because the caller's requested level
  produced an empty transcript (the worker-conversation ladder from #149), we have already paid the
  full input-token cost for the richest transcript we'll see for that conversation. This PR uses
  that sunk cost to opportunistically generate + cache analyses for sibling prompts in the same
  family that declare `key_variant_on_promotion: true` in their frontmatter — so the next `gen objs`
  invocation at a different `(detail, assess)` combo is a free cache hit.

This is a pure cache-warming optimization: zero behavior change for callers, zero change to
  `AnalysisResult.cost`, zero CLI/flag/env-var/output surface impact. The variant set is
  **metadata-driven** (frontmatter), never hardcoded.

## Key design decisions

- **Shared helpers refactor**: `_build_framed_transcript`, `_run_single_analysis`,
  `_parse_variant_name`, and `_warm_key_variant_cache` are extracted from the inline LLM-call block
  so the primary path and the fan-out share identical input framing, JSON-parse, and
  `ObjectiveAnalysis` construction. No drift between primary and variants. - **Metadata-driven
  variant discovery**: `PromptMetadata.key_variant_on_promotion: bool = False` (opt-in, default
  off). `list_key_variants_on_promotion(family)` in `prompts/discovery.py` is the single source of
  truth for the candidate set — returns `[]` for unknown families so a missing family is a no-op,
  not an error (AC #1). - **Fan-out trigger gate**: runs only when `effective_context != context`
  (i.e. promotion happened). Normal-path conversations that succeed at their requested context level
  get zero extra calls (AC #8). - **Two-layered failure isolation** (AC #7): each variant is wrapped
  in per-variant `try/except` inside `_warm_key_variant_cache`; the entire helper call is wrapped in
  a defensive outer `try/except` inside `analyze_objectives`. A variant failure logs a `WARNING` and
  continues — the primary `AnalysisResult` is never affected. - **Cache-hit short-circuit** (AC #5):
  each variant probes `_cache_manager.load_cached(...)` first at the promoted context with matching
  `content_hash + event_count + prompt_hash`. Hits skip the LLM entirely with `$0` cost. -
  **Primary-only cost semantics** (AC #6): `AnalysisResult.cost` is the primary call's cost. Variant
  costs are aggregated into a single `INFO` summary log line: `Opportunistic key-variant fan-out: N
  generated, M cached, K failed, $X.YYYY total`. - **Alias-key parity with #129**: each variant is
  saved with `requested_key_kwargs` pointing at the originally-requested context level, mirroring
  the primary's behavior so subsequent lookups at the requested (pre-promotion) level also hit
  cache. - **One opt-in this PR**: only `src/ohtv/prompts/objs/standard_assess.md` flips
  `key_variant_on_promotion: true` (AC #2). Adding more is a one-line frontmatter change in a
  follow-up — no code change required.

## Test coverage

- **Full unit suite**: 2165 passed, 2 skipped, 3 xfailed (~38s on the test runner). - **New
  unit-test files** (40 new tests total): - `tests/unit/analysis/test_key_variant_warming.py` —
  mirrors every AC: opt-in variant set discovery, primary+variant caching after promotion,
  pre-populated variant short-circuit (no LLM call), per-variant failure isolation, primary-only
  cost accounting, no-promotion no-op regression guard. -
  `tests/unit/analysis/test_cache_alias_promoted_context.py` — updated regression for the #129
  cache-alias behavior, now accounting for the variant call on the first analyze. -
  `tests/unit/prompts/test_parser.py` — parser coverage for `key_variant_on_promotion`
  (present/absent/non-bool → `bool(...)` coercion, default `False`). - **6 blackbox manual
  scenarios** (PR comment 2026-05-30T17:23:54Z, all PASS): - A: frontmatter backward-compat (prompts
  without the field parse unchanged). - B: opportunistic warming on promotion (variant cache file
  appears after a single `gen objs` call). - C: cache-hit skip with `$0` evidence (re-running with
  pre-populated variant emits no LLM call). - D: per-variant failure isolation (AC #7) — one variant
  raising does not affect primary or other variants. - E: primary-only cost (AC #6) —
  `AnalysisResult.cost` excludes variant cost; variant cost is in the INFO log line. - F:
  no-promotion regression guard (AC #8) — normal path emits zero variant calls.

Closes #145

--- _This PR was prepared and merged by an AI agent (OpenHands) on behalf of @jpshackelford._


## v0.19.1 (2026-05-30)

### Bug Fixes

- **logging**: Suppress LiteLLM botocore pre-load warnings
  ([#148](https://github.com/jpshackelford/ohtv/pull/148),
  [`aedfc69`](https://github.com/jpshackelford/ohtv/commit/aedfc690608162b20e7f50f9fb84ce7e54a04055))

Sets `LITELLM_LOG=ERROR` via `os.environ.setdefault` at package init so the eager `litellm` import
  in commands like `ohtv ask`/`ohtv gen objs` no longer leaks `could not pre-load <provider>
  response stream shape` warnings to stderr on `ohtv --help`, `ohtv prompts list`, `ohtv db status`,
  etc.

The `setdefault` is the escape hatch: `LITELLM_LOG=WARNING ohtv ask ...` brings warnings back when
  debugging is needed.

Adds two subprocess-isolated regression tests asserting both the default `ERROR` path and the
  preserve-user-set contract.

Documents `LITELLM_LOG` as a user knob in `docs/reference/configuration.md`.

Closes #148.

_This commit message was authored by an AI agent (OpenHands) on behalf of @jpshackelford._

### Chores

- **worklog**: Note PR #158 ready for review (Issue #148)
  ([`1dbb92a`](https://github.com/jpshackelford/ohtv/commit/1dbb92a684fb842517ec85c282164db54843b869))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T14:51:24Z — spawn impl worker for #148
  ([`b33e007`](https://github.com/jpshackelford/ohtv/commit/b33e007eb98341e9a5a4babc818035914d2009d1))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing worker for PR #158
  ([`0e407b8`](https://github.com/jpshackelford/ohtv/commit/0e407b8973fc7cdfa649196da74c5d7fcf3be12e))

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.19.0 (2026-05-30)

### Chores

- **worklog**: Impl worker for #149 — PR #157 opened (ready)
  ([`b59e20d`](https://github.com/jpshackelford/ohtv/commit/b59e20d4400cca6f22e8352e3cb765f019e3e0e8))

- **worklog**: Orchestrator spawned docs spot-check for PR #157; truncated 19 entries to archive
  ([`3397e77`](https://github.com/jpshackelford/ohtv/commit/3397e777e587c6488e935d6993931ec6d1998795))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned impl worker for #149 (priority:high)
  ([`de371e0`](https://github.com/jpshackelford/ohtv/commit/de371e09068567e2af4e459d6f22c7f5f7e4fe98))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing worker for PR #157
  ([`95b57cd`](https://github.com/jpshackelford/ohtv/commit/95b57cd200ed68db337616f37751cda3b1a0183a))

- **worklog**: Orchestrator wait cycle — impl worker for #149 running
  ([`cf3d5cc`](https://github.com/jpshackelford/ohtv/commit/cf3d5ccf326be26cb1a94740354b8167c413b00b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #156 merge complete
  ([`a93e376`](https://github.com/jpshackelford/ohtv/commit/a93e376ae79cf6a4a37f20fac700d5ab30c29643))

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **gen-objs**: Expand context levels from 3 to 5
  ([#149](https://github.com/jpshackelford/ohtv/pull/149),
  [`7815fd1`](https://github.com/jpshackelford/ohtv/commit/7815fd134d92bddbeeb652d52f4e32733e51eb1d))

Replaces the legacy 3-level `minimal` / `default` / `full` context ladder in `ohtv gen objs` with a
  5-level additive ladder. Each level extends the previous one with strictly more event types,
  letting users tune the analyzer precisely against token cost vs signal quality.

| # | Name | Adds (vs previous level) | | --- | --- | --- | | 1 | `minimal` | user messages only | |
  2 | `outcome` | + `finish` action | | 3 | `dialogue` | + agent messages | | 4 | `actions` | +
  non-`finish` action summaries (with commands) | | 5 | `observations` | + truncated tool
  observations |

The auto-promotion ladder (`promote_context_level` in `analysis/objectives.py`) now steps one level
  at a time through `CONTEXT_LEVEL_ORDER`, replacing the previous two-step jump. This is the clean
  function boundary that #145 plugs into next.

Stale 3-level references in `docs/guides/analysis.md` were scrubbed in the docs follow-up commit
  (c5645c1) after the manual test pass flagged them; no re-test required (docs-only).

Closes #149.

BREAKING CHANGE: The `-c / --context` flag no longer accepts the retired aliases `default` or
  `full`. Click now rejects them with a `BadParameter` error that includes a migration hint pointing
  at the new 5-level surface (`minimal` / `outcome` / `dialogue` / `actions` / `observations`, also
  addressable as `-c 1` through `-c 5`). Migration map: `default` -> `outcome` (level 2); `full` ->
  `observations` (level 5). The `analysis_cache.cache_key` shape is unchanged but the level *values*
  are not, so all pre-#149 cached analyses become orphaned and are regenerated lazily on the next
  `ohtv gen objs` run per conversation. Embeddings with `embed_type='analysis'` carry the same
  orphaned `cache_key` and will be re-embedded on next `ohtv db embed` run. No migration script is
  shipped (per the explicit PM decision in #149).

### Breaking Changes

- **gen-objs**: The `-c / --context` flag no longer accepts the retired aliases `default` or `full`.
  Click now rejects them with a `BadParameter` error that includes a migration hint pointing at the
  new 5-level surface (`minimal` / `outcome` / `dialogue` / `actions` / `observations`, also
  addressable as `-c 1` through `-c 5`). Migration map: `default` -> `outcome` (level 2); `full` ->
  `observations` (level 5). The `analysis_cache.cache_key` shape is unchanged but the level *values*
  are not, so all pre-#149 cached analyses become orphaned and are regenerated lazily on the next
  `ohtv gen objs` run per conversation. Embeddings with `embed_type='analysis'` carry the same
  orphaned `cache_key` and will be re-embedded on next `ohtv db embed` run. No migration script is
  shipped (per the explicit PM decision in #149).


## v0.18.1 (2026-05-30)

### Bug Fixes

- **rag**: Cite root_conversation_id in ask/search results
  ([#128](https://github.com/jpshackelford/ohtv/pull/128),
  [`48e6f2a`](https://github.com/jpshackelford/ohtv/commit/48e6f2a12fb6985b21aa5c2fa432edba4242c942))

Render-layer-only dedup of `ohtv ask` / `ohtv search` citations: the retrieval pipeline still
  indexes at chunk grain (sub-conversation content is often the highest-signal evidence), but the
  citation list shown to the user collapses sub-sourced chunks to their root via the migration-020
  `root_conversation_id` column.

- `ContextChunk` carries `root_conversation_id`; standalone convs use their own id as the root -
  `RAGRetrievalResult.source_conversation_ids` and `RAGAnswer.source_conversation_ids` are sets of
  root ids - `ohtv ask` Sources table renders root id/title with a `[via sub: <hex8>]` annotation
  when the max-scoring chunk came from a sub - `ohtv search` table dedupes to one row per root with
  MAX-score aggregation; rank/score/snippet reflect the max-scoring chunk - `--explain` /
  `--explain-only` retrieval breakdowns show both grains (per-chunk conversation_id + rolled-up
  root_conversation_id) - Runtime guardrail (`_assert_root_column_present`) at the entry of
  `RAGRetriever.retrieve` / `RAGAnswerer.answer_question`; the error message cites migration 020
  explicitly - `embedding_store.search` / `search_conversations` / `get_context_for_rag` are
  intentionally unchanged — no rollup writes, the `embeddings` table is left alone (per the #122
  cluster contract)

Helper added: `map_to_roots(conn, ids: list[str]) -> dict[str, str]` in `src/ohtv/filters.py`
  (list-shaped companion to #127's set-shaped `expand_to_roots`).

No new flags. No new migration. `--include-sub-conversations` was intentionally rejected during
  issue expansion — chunk-grain visibility stays available via `--show-context` and `--explain` /
  `--explain-only`.

Closes the #122 root-conversation-aggregation cluster: - #123 weekly-counts → PR #152 → v0.16.1 -
  #124 velocity → PR #153 → v0.16.2 - #125 gen objs/titles/run → PR #154 → v0.17.0 (BREAKING) - #127
  list/refs display → PR #155 → v0.18.0 (BREAKING) - #128 RAG ask/search dedup → PR #156 → v0.18.1
  (this PR) - #126 classify policy (queued for next impl pick)

Tests: 2163 passed, 2 skipped, 3 xfailed (113 new tests this PR).

Fixes #128. PR: #156

### Chores

- **worklog**: Impl worker completed #128 (PR #156 ready for review)
  ([`de0d74e`](https://github.com/jpshackelford/ohtv/commit/de0d74ed7b3c9c5dcf26a9999db749a77b5d005f))

- **worklog**: Merge worker — PR #155 merged → ohtv-v0.18.0
  ([`267fab2`](https://github.com/jpshackelford/ohtv/commit/267fab29ce8d327c7fe6d79540c5fbc3ce6394e2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T10:48:00Z — spawned impl worker for #128
  ([`0c0dc86`](https://github.com/jpshackelford/ohtv/commit/0c0dc86d75c9bd2e32bd750aadf323cbccb55c83))

- **worklog**: Orchestrator 2026-05-30T11:18Z — spawn testing worker for PR #156
  ([`ee8c436`](https://github.com/jpshackelford/ohtv/commit/ee8c436547d776b0086080f242ae5eb8f94cda71))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle - spawn merge worker for PR #156
  ([`e3123a3`](https://github.com/jpshackelford/ohtv/commit/e3123a374e9ecd24507b4697dd93347d486280af))

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.18.0 (2026-05-30)

### Chores

- **worklog**: Impl worker opened PR #155 for #127 (list/refs root grain)
  ([`ef18d33`](https://github.com/jpshackelford/ohtv/commit/ef18d33ac08b29b81833278082fc1572dfeac59b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge PR #154 — ohtv-v0.17.0 released with BREAKING CHANGES
  ([`ed8ee97`](https://github.com/jpshackelford/ohtv/commit/ed8ee970cc8e6d0d216cc97acfe96f094c045c80))

Squash commit 4f2217dc landed on main with the BREAKING CHANGE: footer intact. Semantic-release
  produced ohtv-v0.17.0 (minor bump per major_on_zero=false) with a Breaking Changes section in the
  release notes. Closes #125 via Fixes footer.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T09:53:54Z — retry testing worker for PR #155
  ([`906a786`](https://github.com/jpshackelford/ohtv/commit/906a786753652739ad4a884a113123192d2e044f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T10:21:00Z — spawned merge worker for PR #155
  ([`670e52b`](https://github.com/jpshackelford/ohtv/commit/670e52b7f56c43512e0d48d61e3f3f6eadac32e8))

- **worklog**: Orchestrator spawn docs worker for PR #155
  ([`2ffd96b`](https://github.com/jpshackelford/ohtv/commit/2ffd96b4ddc6fee9655e40f3e8e333bcd9964485))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn testing worker for PR #155
  ([`486a6ce`](https://github.com/jpshackelford/ohtv/commit/486a6cefb8bda97c4705414810f1a45e2d7a60a7))

- **worklog**: Orchestrator spawned merge worker for PR #154 (merge raced ahead to 4f2217d)
  ([`79731ea`](https://github.com/jpshackelford/ohtv/commit/79731ea73dd9c7a1f9dac397f9f9481f7dada319))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Truncate archive + orchestrator 07:50Z spawn impl worker for #127
  ([`6ab5c96`](https://github.com/jpshackelford/ohtv/commit/6ab5c96bb797e8e1fba52984829e89464d1b98f8))

- Archived 7 entries older than 6h productive span (to WORKLOG_ARCHIVE_2026-05-29.md /
  -2026-05-30.md) - WORKLOG.md reduced from 1645 -> ~1253 lines - Spawned implementation worker
  18f797e for issue #127 (list/refs root-grain display + filter-resolution) - Next root-grain
  cluster issue post v0.17.0 release

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **list,refs**: Roots-only by default with subtree rollup (#127)
  ([#155](https://github.com/jpshackelford/ohtv/pull/155),
  [`5c0adfb`](https://github.com/jpshackelford/ohtv/commit/5c0adfb3b551dd2dd18d48107dd440b3e04a3d53))

`ohtv list` and the multi-conversation form of `ohtv refs` now show **root conversations only** by
  default, and `ohtv refs <root-id>` rolls up its entire delegation subtree (union of every sub's
  refs, deduped by URL). Filters on `list` (`--pr`, `--repo`, `--label`, `--action`) resolve through
  the new `expand_to_roots` helper so a PR touched only by a delegated sub still surfaces the
  matching root row, not the sub. The display/filter counterpart to #125's batch-mode flip on `gen
  objs / titles / run`.

Pass `--include-sub-conversations` on either command to restore the pre-#127 per-sub rendering. The
  single-conv `ohtv refs <sub-id>` and `ohtv show <id>` paths are unaffected (a sub-id is still a
  valid query target). Migration-020 (`root_conversation_id`) is enforced inline at command
  invocation on both code paths — pre-020 DBs see a friendly "run `ohtv db scan`" `RuntimeError`
  rather than a silent regression.

This is the **fourth** PR in the #122 root-grain rollout series (after #150 → weekly-counts v0.16.1,
  #153 → velocity v0.16.2, #154 → gen-family v0.17.0 ⚠ BREAKING). `major_on_zero = false` in
  `pyproject.toml` ships this as **v0.18.0** (minor) with a ⚠ BREAKING CHANGES CHANGELOG entry. Only
  #128 (RAG citation dedup) remains in the cluster.

Tests: +19 new tests (`TestExpandToRoots` ×8 in `test_filters.py`; `TestFilterByPrRootExpansion` ×3,
  `TestRefsSubtreeRollup` ×3, `TestMigration020Guardrail` ×3, `TestCliOptionSurface` ×2 in
  `test_cli_list_refs_subs.py`). Suite: 2082 passed, 2 skipped, 3 xfailed (+19 from baseline
  `ed8ee97`). Manual testing: all 8 scenarios verified end-to-end against a populated DB (220 roots
  + 42 subs across 42 trees) — `list` collapses 262→220 rows by default,
  `--include-sub-conversations` restores 262; `refs -D` reports 41 vs 42 conversations aggregated;
  `refs <root-id>` printed the subtree-rollup banner and unioned the ref set; `--pr 155` routes
  through `expand_to_roots` (3 root rows vs 6 with the flag).

Fixes #127.

BREAKING CHANGE: ohtv list and the multi-conv form of ohtv refs (-D and other filters) now exclude
  sub-conversations by default; rows represent root conversations and filters like
  --pr/--repo/--label/--action resolve through the root grain. ohtv refs <root-id> additionally
  rolls up refs from every sub under the root (union, deduped by URL). Pass
  --include-sub-conversations on either command to restore the pre-v0.18.0 behavior of rendering
  every conversation as its own row.

### Breaking Changes

- **list,refs**: Ohtv list and the multi-conv form of ohtv refs (-D and other filters) now exclude
  sub-conversations by default; rows represent root conversations and filters like
  --pr/--repo/--label/--action resolve through the root grain. ohtv refs <root-id> additionally
  rolls up refs from every sub under the root (union, deduped by URL). Pass
  --include-sub-conversations on either command to restore the pre-v0.18.0 behavior of rendering
  every conversation as its own row.


## v0.17.0 (2026-05-30)

### Chores

- **worklog**: Docs worker shipped #154 doc updates
  ([#125](https://github.com/jpshackelford/ohtv/pull/125),
  [`eb199c5`](https://github.com/jpshackelford/ohtv/commit/eb199c5acb532a6d41fb6fa68ff79b573e421742))

- **worklog**: Impl hand-off for #125 PR #154
  ([`946b447`](https://github.com/jpshackelford/ohtv/commit/946b4474973341d3b23ff0f3dfa9a816627ac794))

PR #154 opened DRAFT → marked ready at 05:12Z. CI green on draft (lint=3s pass, pytest=53s pass).
  Awaits pr-review on ready transition.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T04:50Z — spawn impl worker for #125
  ([`c2ccf82`](https://github.com/jpshackelford/ohtv/commit/c2ccf82b412b5b8ec297fb4291b8bed536edfbb5))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T05:50Z — spawned testing worker for PR #154
  ([`e2a9150`](https://github.com/jpshackelford/ohtv/commit/e2a9150cb61cfe5be3e2b8f34ce2202aefe62b72))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-30T06:50:00Z - spawn review worker for PR #154
  ([`40429a6`](https://github.com/jpshackelford/ohtv/commit/40429a641e067f200743e4c21600229e96847721))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator no-action 2026-05-30T06:19:35Z [skip ci]
  ([`3b81ebb`](https://github.com/jpshackelford/ohtv/commit/3b81ebbe8f58b19aedce9f48ea654ecb135e6716))

- **worklog**: Review worker addressed PR #154 round-1 feedback (Option A on semver, warning bump,
  annotation nit)
  ([`3ef7edb`](https://github.com/jpshackelford/ohtv/commit/3ef7edbf473e8b276b0e612f0be852c5dee8afa0))

- **worklog**: Spawn docs worker for PR #154 + truncate 18:51-21:50Z May-29
  ([`6c74ce8`](https://github.com/jpshackelford/ohtv/commit/6c74ce865fcfd0a0829a696c1965cdec1539f765))

- Spawned docs worker eec0de5 for PR #154 (--include-sub-conversations flag, README not updated,
  decision-tree row 'PR ready, CI green, README not updated'). - Surfaced pr-review
  CHANGES_REQUESTED feedback (semver breaking-change classification) for the next review worker. -
  Truncated WORKLOG.md: 1723 -> 1066 lines pre-entry. Archived 8 older productive entries from
  18:51-21:50Z May-29 to WORKLOG_ARCHIVE_2026-05-29.md (existing file, appended). Kept 19 entries
  spanning 6.3h productive window (22:50Z May 29 -> 05:12Z May 30) per skill's 6-hour rule.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Testing worker reported all-pass for PR #154
  ([#125](https://github.com/jpshackelford/ohtv/pull/125),
  [`def863f`](https://github.com/jpshackelford/ohtv/commit/def863f1c3db989e8400dc78412d5b256c696317))

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **gen**: Exclude sub-conversations from multi-conv mode by default (#125)
  ([#154](https://github.com/jpshackelford/ohtv/pull/154),
  [`4f2217d`](https://github.com/jpshackelford/ohtv/commit/4f2217dc1aa64d996a5fc67ac99d00db384aade2))

Multi-conversation `gen objs`, `gen titles`, and `gen run` now exclude agent-delegated
  sub-conversations by default and process only root conversations. Sub-conversations are agent
  work, not human intent — since #108 enabled sub-conv sync, batch analysis runs have been
  double-counting prompts and inflating LLM cost linearly with delegation depth. The DB-layer
  predicate is `id = root_conversation_id`, the same shape `report velocity` uses; migration 020's
  backfill guarantees orphan subs become their own root so the predicate covers the whole table.

Pass `--include-sub-conversations` on any of the three gen-family commands to restore the previous
  behavior of treating sub-conversations as independent units. Single-conversation `ohtv gen objs
  <id>` is unaffected (the flag is multi-only). The `list` and `refs` commands continue to show
  every row — display roll-up is #127's scope.

This is the third PR in the #122 root-grain rollout series (after #150 → weekly-counts v0.16.1 and
  #153 → velocity v0.16.2). `major_on_zero = false` in pyproject.toml ships this as v0.17.0 (minor)
  with a ⚠ BREAKING CHANGES CHANGELOG entry — see the round-1 review hand-off for the Option A
  rationale (acknowledge as breaking vs. deprecation cycle).

Tests: +24 new tests across DB layer (`TestListByDateRangeIncludeSubs`, 8 tests) and CLI layer
  (`TestBatchModeSubConversations` / `TestGenTitlesSubConversations` / `TestGenRunSubConversations`,
  16 tests combined). Suite: 2063 passed (+24 from baseline). Manual testing: all 9 scenarios
  verified by testing worker `e2f465f` (see PR comment #4581947363).

Fixes #125.

BREAKING CHANGE: ohtv gen objs/titles/run multi-conv mode now excludes sub-conversations by default.
  Use --include-sub-conversations to restore the pre-v1.0.0 behavior.

### Breaking Changes

- **gen**: Ohtv gen objs/titles/run multi-conv mode now excludes sub-conversations by default. Use
  --include-sub-conversations to restore the pre-v1.0.0 behavior.


## v0.16.2 (2026-05-30)

### Bug Fixes

- **reports**: Aggregate velocity at root grain
  ([#124](https://github.com/jpshackelford/ohtv/pull/124),
  [`c79ffde`](https://github.com/jpshackelford/ohtv/commit/c79ffde8674d3dd309357a05c1e2953125068ebc))

`ohtv report velocity` double-counted human input when an agent-delegated sub-conversation
  contributed to the same merged PR as its parent. After sub-conversation sync (#108) + migration
  020 (#122) landed, the root and the sub each carried their own `conversation_human_input` row
  through the outer join. The sub's `initial_prompt_words` was masked by the `'automation'` CASE
  branch, but `followup_word_count` and `followup_message_count` slipped through, inflating `Words`
  and `Msgs` by the sub's contribution. LOC accounting was not affected.

The pre-#124 `_VELOCITY_SQL` DISTINCT sub-select keyed on `(change_ref_id, conversation_id)`. A
  `WHERE` predicate cannot fix this — the duplication is in the join cardinality, not in the row
  set. The minimal fix substitutes the DISTINCT key from conversation grain to root grain by INNER
  JOIN-ing `conversations` into the sub-select and projecting `c.root_conversation_id` as the join
  key, so the outer LEFT JOIN to `conversation_human_input` only ever sees the root's row. Orphan
  contributions (a `conversation_contributions` row whose `conversation_id` is not in
  `conversations`) are dropped by the new INNER JOIN, matching the pre-#124 behaviour of the outer
  LEFT JOIN returning NULL → 0 words for them.

Adds a `_assert_root_column_present` guard at `fetch_raw_rows` entry that raises
  `RuntimeError("report velocity requires migration 020; run 'ohtv db scan' to apply pending
  migrations")` if migration 020 has not been applied. Mirrors the guard #123 landed for
  `weekly_counts` — silently falling back to the legacy conversation-grain SQL would just
  reintroduce the bug.

Test coverage: - 6 new regression tests in `tests/unit/reports/test_velocity.py` covering root+sub
  same-PR same-week, cross-week bucketing by `merged_at`, LOC accounting invariance, 2-deep chain
  (root → sub1 → sub2), sub-only contribution attributing to root's `chi` row, and the migration-020
  guard error. - Extends `seed_conversation` helper in `tests/unit/reports/conftest.py` with
  `parent_conversation_id` / `root_conversation_id` kwargs defaulting to self-root (mirrors #123's
  shape). - Existing 27 velocity tests pass unchanged; full reports suite (81 tests) green. - Manual
  QA: 8/8 scenarios passed (subless baseline, root+sub same week, cross-week sub-only, 2-deep chain,
  LOC accounting unchanged, migration-020 guard, chart stability, CLI surface unchanged).

Fixes #124 Closes #124

Co-authored-by: openhands <openhands@all-hands.dev>

### Chores

- **worklog**: Impl worker #124 opened PR #153 (velocity root grain)
  ([`c479ca5`](https://github.com/jpshackelford/ohtv/commit/c479ca510002eafea18a9052e7abe500c960936d))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker shipped #123 as PR #152 (ohtv-v0.16.1)
  ([`ec658d5`](https://github.com/jpshackelford/ohtv/commit/ec658d52938f78102cea65f214d55a37d9b18717))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker shipped #153 as ohtv-v0.16.2
  ([`1f7b946`](https://github.com/jpshackelford/ohtv/commit/1f7b9462db38cfae3545bd303a5ed9dc5f6e9ccd))

- **worklog**: Orchestrator 2026-05-30T04:21:10Z — spawn merge worker for PR #153
  ([`480df84`](https://github.com/jpshackelford/ohtv/commit/480df840cad44144bbd8288834fa9975fe6fa88f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn impl worker for #124 (2026-05-30T03:22:21Z)
  ([`774fac0`](https://github.com/jpshackelford/ohtv/commit/774fac075861828a57ed45b8d25beed3a6056076))

- **worklog**: Orchestrator spawned testing worker for PR #153 (velocity root grain)
  ([`0ff33a2`](https://github.com/jpshackelford/ohtv/commit/0ff33a2ee99cae52d077047aee82319ffb946efe))

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.16.1 (2026-05-30)

### Bug Fixes

- **reports**: Aggregate weekly-counts at root grain
  ([#123](https://github.com/jpshackelford/ohtv/pull/123),
  [`75eb2cb`](https://github.com/jpshackelford/ohtv/commit/75eb2cb75031c2a165122ea4cd8a7b57e4c02f04))

After sub-conversation sync (#108) and migration 020 (#122) landed, 'ohtv report weekly-counts'
  over-counted the cloud column by the agent delegation rate: each delegated sub became its own row
  in conversations and the report had no way to distinguish them from roots.

Add a single predicate to the report SQL:

AND id = root_conversation_id

Plus a column-presence guard at fetch_rows entry that raises a clear RuntimeError telling the user
  to run 'ohtv db scan' if migration 020 hasn't been applied. The root's own created_at already
  equals MIN(created_at) across its subtree (a sub cannot exist before its parent), so the direct
  predicate is the minimal, index-friendly fix — the conversations_by_root view stays the right
  surface for #124 (velocity), which DOES roll up subtree sums.

Tests: 5 new (T-A through T-E) covering single root, root+subs same week, root + sub in next week
  (sub must NOT add a row), 2-deep chain, and missing-column error path. Full unit suite: 2033
  passed.

CSV header (week,cloud,cli,total) and the cli vs DB-side local naming contract (AGENTS.md #29) are
  unchanged.

Closes #123

### Chores

- **worklog**: #116 PR #151 ready for review
  ([`a96e675`](https://github.com/jpshackelford/ohtv/commit/a96e6751c966623bf28c1e416ac1320f8c8fc761))

- **worklog**: #148 expansion ready for impl
  ([`bc574e8`](https://github.com/jpshackelford/ohtv/commit/bc574e8a19748a7d31554f2a999645c6bbe90600))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Cycle #3 broken-dispatch — escalated via issue #150
  ([`f22ac07`](https://github.com/jpshackelford/ohtv/commit/f22ac07e2351ec7eb77798c3ba9892e80dd2cb5f))

Pre-committed forecast from 22:50Z fired. Opened tracking issue documenting POST-API child spawn
  failure window (21:19Z→23:16Z, 3 confirmed-dead spawns, sandbox=PAUSED at creation). Labeled the
  tracking issue 'hold' so it doesn't enter the expansion queue.

No worker spawn this cycle (EV≈0). Next cycle checks #150 for human response before resuming normal
  dispatch.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Cycle #4 broken-dispatch — inline-review #149 ready
  ([`881923a`](https://github.com/jpshackelford/ohtv/commit/881923a3a584de0b062c832393d8fad141102e77))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Cycle 00:21Z - dispatch healed, 2 workers spawned (#145 exp, #116 impl)
  ([`eda1abe`](https://github.com/jpshackelford/ohtv/commit/eda1abeddcdecfbfeeef08b33fc2f67bbdbcc02a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Expansion worker #145 - ready for impl
  ([`5ea0437`](https://github.com/jpshackelford/ohtv/commit/5ea0437029ee67f8ccfdf4b833ce000437489d47))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Impl worker shipped #123 as PR #152
  ([`7388f73`](https://github.com/jpshackelford/ohtv/commit/7388f7346a6c3dea6758067ac5a9a801952b4379))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker shipped #116 as PR #151
  ([`0214125`](https://github.com/jpshackelford/ohtv/commit/0214125b13b6e86db372043a79be3ccaac202cb1))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator diagnostic cycle 2 — confirm broken POST-spawn dispatch, no spawn this
  cycle
  ([`8c89696`](https://github.com/jpshackelford/ohtv/commit/8c8969642a756b7f998fc757dc7531be4f3a3713))

- **worklog**: Orchestrator diagnostic — systemic spawn failure since 21:15Z
  ([`68331e5`](https://github.com/jpshackelford/ohtv/commit/68331e5d7cf5be783cc21ae64c44d4d84981ca6a))

5 consecutive worker spawns dead with execution_status=null, updated_at==created_at. Issue #145
  untouched after 2 expansion attempts. PR slot empty post-#147 merge / v0.16.0 release. Surfacing
  to @jpshackelford rather than spawning a 3rd attempt or auto-disabling.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator inline-merged PR #147 (v0.16.0), respawned expansion for #145
  ([`8cf7249`](https://github.com/jpshackelford/ohtv/commit/8cf7249fc53141ac3ac2c7bafda655506c53c23b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn merge worker for #152
  ([`9d9c700`](https://github.com/jpshackelford/ohtv/commit/9d9c7008fa179c2d5e99385bf54d6460c1861fbc))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn testing #152, archive 2026-05-29
  ([`a85e02e`](https://github.com/jpshackelford/ohtv/commit/a85e02ebc0c8325bacc003e7940e3582258701af))

Truncated WORKLOG.md from 2342 → 1148 lines (archived 19 entries to WORKLOG_ARCHIVE_2026-05-29.md),
  spawned testing worker 06ac1e1 for PR #152.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned impl worker e93754b for #123
  ([`9ca6770`](https://github.com/jpshackelford/ohtv/commit/9ca67708b5a365b155d3700c600c72de28f52f80))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing #151 + expansion #148 (2026-05-30T00:54:20Z)
  ([`e8f5666`](https://github.com/jpshackelford/ohtv/commit/e8f56667d5afc138eb69e2a9c9fa9b93c5c60904))

### Refactoring

- **db**: Centralize migration through get_ready_connection
  ([#151](https://github.com/jpshackelford/ohtv/pull/151),
  [`b93c247`](https://github.com/jpshackelford/ohtv/commit/b93c24773e7cfd1a80020d49192f3b4aa92f8f07))

Adds `ohtv.db.get_ready_connection()` as the canonical entry point for production code that touches
  the SQLite index. It composes `get_connection()` with `ensure_db_ready()` so every command —
  fresh-install or otherwise — opens a connection that has the current schema **and** has had all
  pending maintenance tasks evaluated.

This replaces 14 ad-hoc `get_connection()` + `migrate(conn)` call sites across `analysis/cache.py`,
  `conversations.py`, and `cli.py`. The two low-level primitives (`get_connection`, `migrate`,
  `ensure_db_ready`) remain public for niche callers — notably `db init`, which surfaces the list of
  newly-applied migration names that `migrate(conn)` returns.

Behavior-preserving internal refactor — no CLI surface change, no flag, command, or output format
  added or removed. The visible effect is "fewer `no such table` errors after a fresh checkout".

Key implementation notes:

- `get_ready_connection(*, show_progress=False)` lives in `db/connection.py` and is re-exported from
  `ohtv.db`. `show_progress` is plumbed through to `ensure_db_ready` so library/batch callers stay
  quiet by default and CLI sites can opt in. - Idempotency is preserved: `ensure_db_ready`
  short-circuits when no migrations or maintenance tasks are pending, so repeated calls are cheap.
  Verified by `TestIdempotency` and manual scenario #12 (two consecutive `ohtv list -A` runs — no
  `Initializing database…` line on the second). - Allow-list regression test
  (`tests/unit/test_no_raw_migrate.py`) greps `src/ohtv/` for `migrate(conn)` outside three
  documented sites: `db/maintenance.py` (the wrapper itself), `db/connection.py` (docstring
  example), and `cli.py` `db init` (uses `migrate`'s return value). A liveness check confirms each
  allow-listed file still actually contains `migrate(conn)`, so a future move/rename cannot silently
  over-allow. - Lock semantics unchanged: `get_ready_connection` does not take `sync.lock`; it
  delegates to `ensure_db_ready`, which already does the right thing per item #25 / item #27 in
  AGENTS.md.

Tests: 26 new (18 helper-contract + 6 fresh-install CLI integration + 2 allow-list regression). Full
  suite 2028 passed, 2 skipped, 3 xfailed.

Manual verification: 15 scenarios all PASS — fresh-install probes for `list`, `search`, `db scan`,
  `db process all`, `db index-cache`; idempotency; `db init` happy path and second-run no-op; CI
  green.

Documentation: AGENTS.md item #25 gains a "Single entry point (#116)" bullet pointing at the helper,
  the canonical-callers rule, and the regression test as the floor of the prevention strategy.

Closes #116


## v0.16.0 (2026-05-29)

### Chores

- **worklog**: Impl worker completion for #121 (PR #147)
  ([`e04c44f`](https://github.com/jpshackelford/ohtv/commit/e04c44f5a7847a8b9781b7c7c181dbf113b13c19))

- **worklog**: Orchestrator 2026-05-29T20:21:53Z - spawn testing worker for PR #147
  ([`676a628`](https://github.com/jpshackelford/ohtv/commit/676a628ad972f38c062f9d2b56de31e35001ec6e))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn merge worker for PR #147 and expansion for #145
  ([`667f3f7`](https://github.com/jpshackelford/ohtv/commit/667f3f7b30edcb6956b566bf3642f79ebccc791e))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn review worker for PR #147 (PASS-WITH-NOTES)
  ([`f315e88`](https://github.com/jpshackelford/ohtv/commit/f315e885d9ff6d7e5f7c21c04181725e861b8ba4))

- **worklog**: Spawn impl worker for #121 (CLI logging, priority:high)
  ([`a915a6c`](https://github.com/jpshackelford/ohtv/commit/a915a6c2bcd40259a5e2ced9c3f3de66b6d1086b))

### Features

- **cli**: Add --log-level/--log-file/--log-stderr, stop swallowing batch errors
  ([#147](https://github.com/jpshackelford/ohtv/pull/147),
  [`a8c5cec`](https://github.com/jpshackelford/ohtv/commit/a8c5cec2c7644fe4ef19bb59b40d714c36b75bfa))

Adds a shared logging-options decorator wiring `--log-level`, `--log-file`, and `--log-stderr` into
  every CLI subcommand, and refactors `setup_logging` to a kwargs-only signature with the resolution
  chain CLI → environment (`OHTV_LOG_LEVEL` / `OHTV_LOG_FILE`) → built-in default. Supports `-` for
  stderr-only and `/dev/null`/`nul` for silenced file logging; idempotent on repeated calls.

Closes the swallow-sites in the batch error paths: `_run_batch_objectives_analysis`,
  `_run_post_sync_processing`, `_run_post_sync_llm_analysis`, `_run_objectives_analysis`,
  `EmbeddingWriter._writer_loop`, `generate_embeddings_only`, and `parallel.run_parallel` now call
  `log.exception` or `log.warning` instead of silently returning sentinels. Operators can now `grep
  WARNING ~/.ohtv/logs/ohtv.log` to enumerate failures after a `--quiet` batch run.

`--verbose` / `-v` is retained on all 19 commands that previously had it and now emits a one-shot
  stderr deprecation note (suppressed when an explicit `--log-level` is also passed — see follow-up
  `fix(cli):` commit on this branch). `db init --verbose` and `report velocity --verbose` keep their
  domain-specific `--verbose` behavior orthogonal to logging.

Docs: `docs/reference/configuration.md` truth-ups `OHTV_LOG_LEVEL` (previously documented but
  unwired) and adds `OHTV_LOG_FILE`; `README.md` gets a Logs subsection.

Tests: +53 unit tests across `test_logging.py`, `test_cli_logging.py`, and
  `test_cli_batch_error_logging.py`. Full suite 2050 passed, 2 skipped, 3 xfailed.

Fixes #121.

_This PR was created by an AI agent (OpenHands) on behalf of @jpshackelford._


## v0.15.0 (2026-05-29)

### Bug Fixes

- **classify**: Label sub-conversations 'sub_agent'
  ([#126](https://github.com/jpshackelford/ohtv/pull/126),
  [`604df79`](https://github.com/jpshackelford/ohtv/commit/604df7968a1f298aece9ba48569ebf5d10dfe9a8))

Every `ohtv classify` invocation now runs a deterministic, idempotent SQL UPDATE that sets
  `initial_prompt_source='sub_agent'` on every conversation with a non-NULL
  `parent_conversation_id`, before dispatching to any mode-specific work (single override,
  `--list-unknown`, or bulk heuristic). Self-healing, pure-DB, no LLM, no new flag.

**Design pivot from initial draft.** The first draft of this PR labelled sub-conversations as
  `'automation'`. Review feedback pointed out that `'automation'` already has a specific meaning —
  "an automation run (cron / webhook) dispatched this conversation" — and conflating it with
  sub-agent delegation would silently slurp every sub into the automation-run bucket of `report
  velocity` and `report weekly-counts`, even though those are structurally different things. This
  final revision introduces a dedicated, system-managed `'sub_agent'` value that lives outside the
  operator-facing `--source` Click `Choice`. The parent's actual trigger type is always recoverable
  by walking `parent_conversation_id` up to the root, so giving subs their own label loses no
  information while preventing the double-count. `VALID_SOURCES` deliberately remains the three
  operator-facing values (`human` / `automation` / `unknown`); `SUB_AGENT_SOURCE` is exported
  separately for internal callers only.

**Schema impact.** Migration 022 (`022_classify_sub_agent.py`) widens the
  `conversation_human_input.initial_prompt_source` CHECK constraint to include `'sub_agent'` as a
  fourth allowed value, following the same recreate-table pattern as migration 017
  (`change_refs.status`). Existing data is preserved verbatim — the widening only authorizes future
  writes; no row values change at migration time. A guardrail (`_assert_parent_column_present`)
  surfaces a friendly RuntimeError if migration 019 (`parent_conversation_id`) hasn't run yet.

**Velocity-report adjustment.** `src/ohtv/reports/velocity.py` adds explicit `WHEN 'sub_agent' THEN
  0` cases to both CASE statements (words and messages). The pre-existing `ELSE 0` fallback already
  produced the correct result, but spelling it out keeps the policy visible in the SQL: subs are
  extensions of the parent, so counting them independently would double-count work already rolled up
  in the parent's totals.

**Manual verification.** Manual test report at 2026-05-29T18:28Z (PR #146 comment) covered 10
  end-to-end scenarios on a hand-seeded sandbox DB: auto-classify from `unknown`, self-heal residual
  `automation` (left over from the earlier draft), self-heal residual `human`, single-conv override
  after auto-step, root behavior unchanged across all three CLI modes, velocity `sub_agent → 0`
  contribution to a PR cluster, migration 022 CHECK constraint accepts `sub_agent` and still rejects
  garbage, Click rejects `--source sub_agent` (exit 2), idempotent second invocation, and guardrail
  message when `parent_conversation_id` is missing. All 10 scenarios PASS. `uv run pytest tests/unit
  -x -q` → 1948 passed, 2 skipped, 3 xfailed.

Fixes #126.

---

_This PR was created by an AI agent (OpenHands) on behalf of @jpshackelford._

### Chores

- Trigger CI after workflow changes
  ([`7ff0c4e`](https://github.com/jpshackelford/ohtv/commit/7ff0c4e715e19f7e51b1bb2a1ee5d4dba26657fc))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Docs worker for PR #146 (#126 classify auto-step)
  ([`087c396`](https://github.com/jpshackelford/ohtv/commit/087c396da77902afdabde1f6d1ba1c83436a01a5))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Impl worker shipped #126 as PR #146
  ([`6014230`](https://github.com/jpshackelford/ohtv/commit/60142306fd61a1af9b79d05b1e9dd04a1b47eef2))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Impl worker shipped Phase C of #114 as PR #144
  ([`cf84f99`](https://github.com/jpshackelford/ohtv/commit/cf84f998b6b8d1a532c0e32110e488eedc959134))

- **worklog**: Merge worker completed PR #143
  ([`12711ed`](https://github.com/jpshackelford/ohtv/commit/12711ed4e5be232e3f814931c16d2cd1b9a8ba25))

Records the squash-merge of PR #143 (Phase B of #114) at commit 0792f987 — manifest sync-state
  scalars now dual-written to sync_kv.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker completion for PR #138
  ([`d802aa9`](https://github.com/jpshackelford/ohtv/commit/d802aa9f28648ef886cdc7d70ce8048a34238d05))

- **worklog**: Merge worker shipped PR #144 (Phase C of #114)
  ([`a4972a4`](https://github.com/jpshackelford/ohtv/commit/a4972a4e5f769ce9f7a4d4ed017e6ea94fd5a97e))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-29T17:23:41Z — spawned impl worker for #126
  ([`aabfa1d`](https://github.com/jpshackelford/ohtv/commit/aabfa1daeecf951441feca1bcfdcef67c0ad9ad0))

Inline /assess-priority on 8 ready issues (no priority labels yet); labeled #126 priority:high,
  #116/#123/#124/#125/#127/#128 priority:medium, #121 priority:low. Spawned impl worker 434b541 for
  #126 (classify short-circuit subs). PR slot opened after PR #144 merge at 16:54Z; expansion slot
  remains idle (30th consecutive cycle).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-29T17:51Z - spawned docs worker for PR #146
  ([`3360daa`](https://github.com/jpshackelford/ohtv/commit/3360daab5a25a9b09904388afb08efc18a98490c))

- **worklog**: Orchestrator @ 2026-05-29T15:18Z - spawned impl worker for #114 Phase C
  ([`ac23810`](https://github.com/jpshackelford/ohtv/commit/ac23810f67e71463c695d894cae8906a92d4798b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator @ 2026-05-29T15:50Z - observing impl worker c6f7ba1 (29 min in, no
  spawn)
  ([`f5aad30`](https://github.com/jpshackelford/ohtv/commit/f5aad305e0b90bf158285a757ea9f57405b3e334))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle 13:18Z decision-log (PR #138 merge spawn)
  ([`2019d0d`](https://github.com/jpshackelford/ohtv/commit/2019d0d4420a26e5645fae4947f105fed811c37e))

- **worklog**: Orchestrator cycle 13:53Z (spawned impl worker for #114 Phase B)
  ([`bebe716`](https://github.com/jpshackelford/ohtv/commit/bebe71627b9494c2afa16718ac4e40d395d26690))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle — spawn merge worker for PR #146
  ([`2c08d62`](https://github.com/jpshackelford/ohtv/commit/2c08d627d5020fe08afa8c2ce1ea9a37613c5406))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator hold + PR #141 CI diagnostic 2026-05-29T12:52:49Z
  ([`4091718`](https://github.com/jpshackelford/ohtv/commit/4091718465f59f990d69561a113b97382be7ba4b))

PR #141 workflows never triggered (0 check-runs, 0 statuses). Surfaced human action items: check
  Actions tab for approval banner, repo Actions policy, or push empty commit. Released worklog
  truncation (1612 to 178 lines, archived 24 entries).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned testing worker c189fe4 for PR #143
  ([`58d6cb9`](https://github.com/jpshackelford/ohtv/commit/58d6cb92098a5fb4613cc18b2453121ee14dbb0d))

- **worklog**: Orchestrator spawned testing worker for PR #144
  ([`b3d24d3`](https://github.com/jpshackelford/ohtv/commit/b3d24d3f7c875fddf1b34bed4c5ba3ec41798ed8))

- **worklog**: Orchestrator status 2026-05-29T12:24:55Z
  ([`6d8c6b6`](https://github.com/jpshackelford/ohtv/commit/6d8c6b6521922d8be1af71b4fadc5b0f099fb118))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Phase B of #114 shipped — PR #143 ready for review
  ([`ba5ddb2`](https://github.com/jpshackelford/ohtv/commit/ba5ddb2ee9cccf1b93f5a590bc00c2421fa3b59b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn testing worker for PR #146 (sub_agent pivot)
  ([`175ca51`](https://github.com/jpshackelford/ohtv/commit/175ca513560e76b652a5803ee5af4a5cffee87ed))

Docs worker 2c12c07 finished and self-pivoted design from 'automation' to dedicated 'sub_agent' enum
  value via migration 022. Spawning initial testing worker 14762b5 to verify the pivot + original
  AC.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawned merge worker 604e570 for PR #143
  ([`bdd2336`](https://github.com/jpshackelford/ohtv/commit/bdd2336bbdd8f0d1f9f4938295d8b11ddb3986d3))

- **worklog**: Testing worker exit on PR #143 (Phase B of #114)
  ([`884e6d9`](https://github.com/jpshackelford/ohtv/commit/884e6d9d19b95b90d94263e8a3cc01c048e0f4e2))

Posted manual-test report to PR #143. All four blackbox scenarios (cold-upgrade backfill, dual-write
  parity, overlay precedence, pre-018 fallback) PASS. Unit suite 1972/1972. Recommendation:
  Excellent — ship it.

Co-authored-by: openhands <openhands@all-hands.dev>

### Continuous Integration

- Replace release-please with python-semantic-release (tag-on-push)
  ([#141](https://github.com/jpshackelford/ohtv/pull/141),
  [`58d4bdd`](https://github.com/jpshackelford/ohtv/commit/58d4bdd1cce015c40ea10b8d0b46960bac1705ac))

The original release intent was 'every PR merge ships a release.' release-please's design instead
  opens a release PR that batches commits until a human merges it. Auto-merging that PR closes the
  loop but doubles the closed-PR count over time, since every feature merge produces a companion
  'chore(main): release ohtv X.Y.Z' PR in history.

python-semantic-release achieves the same end state by tagging directly on push — no release PR, no
  intermediate human gate, no doubled PR count. The conventional-commit contract is identical (feat
  -> minor, fix/perf -> patch, breaking change -> major, everything else -> no release).

Specifically:

- Delete .github/workflows/release-please.yml, release-please-config.json,
  .release-please-manifest.json. - Add .github/workflows/release.yml running
  python-semantic-release@v9.21.0 + publish-action@v9.21.0 on push to main, gated by a concurrency
  group so back-to-back merges serialise rather than racing. - Add [tool.semantic_release] block to
  pyproject.toml configured to: * read/write __version__ in src/ohtv/__init__.py and project.version
  in pyproject.toml, * keep the existing 'ohtv-v{version}' tag prefix so the first run diffs against
  the real ohtv-v0.14.0 tag (not the initial commit), * stay pre-1.0 (major_on_zero = false) so
  feat!: bumps 0.14 -> 0.15, * carry [skip ci] on the auto-generated bump commit so it doesn't
  re-trigger the workflow, * use the exact same allowed/minor/patch tag set the previous
  release-please config used. - Update AGENTS.md 'Releases & Commit Contract' section to describe
  the new no-release-PR flow and the new concurrent-merge behaviour (separate releases per merge,
  not batched). - Update CHANGELOG.md preamble to reference python-semantic-release. - Drop the
  now-stale '# x-release-please-version' annotation from src/ohtv/__init__.py.

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- **db**: Add root_conversation_id column, view, and list_roots helper
  ([#138](https://github.com/jpshackelford/ohtv/pull/138),
  [`54cc7d1`](https://github.com/jpshackelford/ohtv/commit/54cc7d159a3425837c6796ca4e448e7bab572e27))

Foundation for the aggregate sub-conversation work (Issue #122). Builds on #108's
  `parent_conversation_id` by introducing a denormalized `root_conversation_id` column on
  `conversations` so the follow-on commands (#123–#128) can roll sub-conversations onto their root
  grain without a recursive CTE on every read.

What's in this PR:

- Migration 020 adds `conversations.root_conversation_id`, the `idx_conversations_root` index, and
  the `conversations_by_root` view that rolls display fields up from the root and spans time/event
  aggregates across the subtree (`MIN(created_at)`, `MAX(updated_at)`, `SUM(event_count)`,
  `conversation_count`, `sub_count`). - Iterative Python backfill (depth cap 8, paranoia against
  cycles); orphan subs whose parent is absent fall back to `root_conversation_id = id` so groupings
  never NULL out. - `ConversationStore` is the single owner of `root_conversation_id` — callers pass
  `parent_conversation_id` only and the store resolves the root from the effective post-COALESCE
  parent, keeping scanner re-passes idempotent with sync's earlier writeback (same ownership pattern
  as `parent_conversation_id` from #108). - New read API: `ConversationStore.list_roots(since,
  until, source, selected_repository)` returns one `RootConversation` row per tree, plus
  `count_roots` / `count_subs` / `count_trees_with_subs` helpers powering the updated `db status`
  line ("N (R roots + S subs across T trees)" when subs exist, gracefully degrading to the old shape
  on pre-020 DBs). - 36 new unit tests in `tests/unit/db/`; full suite 1907 passed.

Manual verification was performed inline by the orchestrator at 11:54 UTC after the dispatched
  testing worker silent-exited; all six blackbox categories passed against head 39d8596.

Per-command callers (#123–#128) are intentionally out of scope and will land in follow-on PRs.

Refs #122

This PR was merged by an AI agent (OpenHands) on behalf of @jpshackelford.

- **sync**: Dual-write sync state scalars to sync_kv (Phase B of #114)
  ([`0792f98`](https://github.com/jpshackelford/ohtv/commit/0792f987f5f81ce2c06674376635d52efb2ec5f8))

Phase B of #114 drains the three top-level sync-state scalars from `~/.ohtv/sync_manifest.json` into
  the `sync_kv` table provisioned by migration 018 (Phase A / PR #137):

- `sync_count` - `last_sync_at` - `failed_ids` (JSON-array row — single row, not row-per-id)

**Dual-write**: `_finalize_sync` and `reset_to_n_newest` write all three scalars to `sync_kv` after
  the manifest `save()`. Manifest stays the back-compat fallback for one release.

**Overlay reader**: `SyncManager.__init__` overlays `sync_kv` rows on top of the loaded
  `SyncManifest`. `get_status()` continues to read from `self.manifest`, which now reflects DB
  values — `ohtv sync --status` transparently picks up the canonical store. Tolerates missing
  `sync_kv` table (pre-018 DB) and any sqlite read error → manifest values survive (cold-upgrade
  fallback).

**Backfill**: New `sync_state_backfill_114` maintenance task registered against `migration_018`, run
  automatically by `ensure_db_ready`. Copies each of the three keys from manifest → `sync_kv` only
  when absent in the DB; pre-existing DB rows are never overwritten. Idempotent.

**Closes brittle-spot #2** from `docs/reference/sync-state-ownership.md` (non-atomic manifest writes
  can lose all three scalars on SIGTERM) without flipping per-conv metadata ownership — that's Phase
  C.

Phases C (additive overlay → manifest-shrinker for per-conv metadata) and D
  (manifest-deletion-final) remain open work on #114.

Refs #114

- **sync**: Make DB canonical for per-conv cloud metadata (Phase C of #114)
  ([`3302139`](https://github.com/jpshackelford/ohtv/commit/33021397baaeb9955654198385d463e424ce06ff))

Phase C of #114 drains per-conversation cloud metadata out of `~/.ohtv/sync_manifest.json` and into
  the `conversations` DB table. After this PR the DB is canonical for `title`, `labels`,
  `selected_repository`, `created_at`, `selected_branch`, and the `cloud_updated_at` sync cursor.
  The manifest is still dual-written for one release as a downgrade bridge; Phase D will retire the
  manifest writes entirely.

Key invariants enforced:

* Migration 021 adds `conversations.selected_branch TEXT` and one-time backfills any non-NULL
  manifest value into NULL DB columns via `COALESCE` — populated DB columns are never clobbered, and
  the migration is idempotent. * `SyncManager._categorize_via_set_diff` reads
  `conversations.cloud_updated_at` as canonical, with the manifest retained as a cold-upgrade
  fallback. * The cloud-download path writes `title` / `labels` / `selected_repository` /
  `created_at` / `selected_branch` to the DB at download time (via `_write_phase_c_metadata`
  wrapping `ConversationStore.update_metadata`), so `--status`, `list`, and `gen titles` see
  populated metadata without waiting for `db scan`. * The scanner's `extract_metadata` takes a
  `db_overlay` argument so a cold rescan of a populated cloud row reads the DB first; the manifest
  and `base_state.json` are consulted only when the DB column is NULL. * `SyncManager.get_status`
  sums `conversations.event_count` (closing brittle spot #5 from
  `docs/reference/sync-state-ownership.md`) — the total may shift relative to pre-#144 output
  because the manifest snapshot was stale whenever agents kept emitting events post-sync. *
  Visibility-restore correctness: dropping a manifest entry now also clears the DB cursor via
  `_clear_cloud_updated_at` so the Phase C gate stays self-consistent. * AGENTS.md item #27 updated:
  DB is canonical, sync is permitted to write `selected_branch`, `update_metadata` still does NOT
  accept it (the listing API doesn't carry it). `docs/reference/database.md` and
  `docs/reference/sync-state-ownership.md` updated to match.

Behavioral scenario #14 flipped from the #87 manifest-canonical guard to the Phase C DB-canonical
  guard (same fixture, asserts on DB columns while still verifying the manifest dual-write
  contract).

Test coverage: 10 new tests in `tests/unit/sync/test_phase_c_per_conv_metadata.py`, 1933 total unit
  tests pass, plus 6 manual blackbox scenarios (cold-upgrade backfill, backfill-additive, `--status`
  reads DB, `selected_branch` schema addition, manifest dual-write preserved, scanner DB-overlay
  precedence) all PASS — see the manual test report on the PR.

Phase A landed in #138, Phase B in #143. Phase D is blocked behind release cadence and will close
  #114 when it ships.

Refs #114

Co-authored-by: openhands <openhands@all-hands.dev>


## v0.14.0 (2026-05-29)

### Bug Fixes

- Add context_level to skip cache for proper retry at higher levels
  ([#69](https://github.com/jpshackelford/ohtv/pull/69),
  [`2807e64`](https://github.com/jpshackelford/ohtv/commit/2807e64c575297f8b3a460dd3a369f151da2bc23))

fix: add context_level to skip cache for proper retry at higher levels

The skip cache was previously keyed only by conversation_id, which meant that skipping a
  conversation at a lower context level (e.g., minimal) would prevent retry at a higher context
  level (e.g., full). This defeated the purpose of the auto-promotion fix in #59.

Changes: - Add context_level column to analysis_skips table (migration 014) - Add context_level
  parameter to is_skipped() and mark_skipped() in file cache - Add skip_context_level field to
  CacheStatus with needs_analysis_for_context() - Update CLI to use context-aware batch status
  checks - Fix event count stale data bug: update event_count even when preserving higher context
  level to prevent infinite retry loops

Context-aware invalidation logic: - Skip at minimal → allows retry at default or full - Skip at
  default → allows retry at full - Skip at full → blocks all context levels (highest includes
  everything)

Backward compatibility: - Legacy cache files without context_level treated as minimal - Migration
  adds default minimal for existing entries

Test coverage: - 14 tests for file-based cache context awareness - 12 tests for database store
  context awareness - 1116 total unit tests pass

Fixes #60

Co-authored-by: openhands <openhands@all-hands.dev>

- Auto-promote context level for worker conversations (#59)
  ([#66](https://github.com/jpshackelford/ohtv/pull/66),
  [`32498ac`](https://github.com/jpshackelford/ohtv/commit/32498ac61ee0b47f2a02f2c69fdf025c2a36fbda))

fix: auto-promote context level for worker conversations (#59)

Worker conversations (orchestrator-spawned) have no user messages but do have meaningful actions.
  Previously, batch mode defaulted to "minimal" context (user messages only), resulting in empty
  transcripts and these conversations being incorrectly marked as "no_analyzable_content" (~85% skip
  rate).

Changes: - Add `_has_action_events()` helper to detect agent ActionEvents - Add auto-promotion
  logic: minimal → default → full when transcript empty - Add 10 unit tests for helper and
  auto-promotion behavior

The fix preserves token efficiency for normal conversations (uses minimal) while correctly capturing
  worker conversations that have only actions.

Fixes #59

Co-authored-by: openhands <openhands@all-hands.dev>

- Embedding progress bar displays remaining count and ETA
  ([#55](https://github.com/jpshackelford/ohtv/pull/55),
  [`0215fb0`](https://github.com/jpshackelford/ohtv/commit/0215fb00b30c4adcc3c570977f3acf543b4f6e69))

fix: improve embedding progress bar with remaining count and ETA (#55)

Replace misleading "(X new)" rate display with clear countdown and ETA.

Before: Embedding ━━━━╺━━━ 10% 124/min (124 new)

After: Embedding ━━━━╺━━━ 10% 190 left │ ETA 0:02:15 119/min

Changes: - Add TimeRemainingColumn for ETA display (matches sync progress bar) - Add
  _format_remaining() showing countdown: "{remaining} left" - Simplify _format_rate() by removing
  misleading new_embeds parameter - Update both sequential and parallel processing paths
  consistently

Test coverage: - 13 new unit tests in tests/unit/test_embedding_progress.py - Manual tests verified:
  estimate, embed, force, search, format consistency - Full suite: 966 tests passing

Fixes #45

Co-authored-by: openhands <openhands@all-hands.dev>

- Summary command now checks cache before confirmation prompt
  ([`c6626ea`](https://github.com/jpshackelford/ohtv/commit/c6626ea7ca44b56edaa04270292c6937bdba6da3))

The summary command previously prompted for confirmation based on total conversation count, even
  when most had already been cached. Now it:

1. Pre-checks cache status for each conversation when above threshold 2. Only prompts if the number
  of NEW (uncached) analyses exceeds threshold 3. Reports the accurate count of conversations
  requiring LLM computation 4. Shows how many are already cached and will be skipped

This improves UX by avoiding unnecessary prompts when running against conversations that have
  already been analyzed.

Co-authored-by: openhands <openhands@all-hands.dev>

- Summary progress bar shows only uncached conversations
  ([`4994dab`](https://github.com/jpshackelford/ohtv/commit/4994dab2fb4808de1271d00d4d182a24da1b977b))

Previously the progress bar showed total conversations even when most were cached. Now:

1. Always compute uncached_count upfront (for both confirmation and progress) 2. Progress bar shows
  only the number needing LLM analysis 3. Skip progress bar entirely when all results are cached 4.
  Only advance progress on actual LLM calls (not cache hits)

Co-authored-by: openhands <openhands@all-hands.dev>

- Use needs_processing instead of non-existent is_complete method
  ([`2669702`](https://github.com/jpshackelford/ohtv/commit/2669702f5006b77908f30728a6f82a0e490a9f8f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **cache**: Alias auto-promoted context_level so re-runs hit the cache
  ([#129](https://github.com/jpshackelford/ohtv/pull/129),
  [`29c3b70`](https://github.com/jpshackelford/ohtv/commit/29c3b70569128d6bbbe7af90c22bfb2856a9b3ba))

Root cause: when `analyze_objectives` was called with `context_level=minimal` on a worker-style
  conversation (no user messages but with agent actions), the writer auto-promoted
  `effective_context` to `default`/`full` and persisted the cache row under that promoted key, while
  the reader (`get_cache_status_batch` and `load_cached`) looked up the cache under the
  originally-requested `minimal` key. Every `ohtv gen objs -D` re-ran the same N worker
  conversations through the LLM, billing the same calls indefinitely (#129).

Fix: `AnalysisCacheManager.save` now accepts an optional `requested_key_kwargs` and writes a SECOND
  entry (both on disk and in the `analysis_cache` table) under the requested cache_key whenever
  auto-promotion has fired, pointing at the same `analysis.model_dump()`. The stored analysis
  retains its true effective `context_level` — only the cache_key mapping is duplicated.
  `load_cached` gains two narrow tolerances for alias hits (skip the per-attribute `context_level`
  equality check and skip `content_hash` when the stored level differs from the requested one);
  `detail_level`, `assess`, and `prompt_hash` validation remain strict. `make_cache_key` and
  `get_cache_status_batch` are deliberately untouched per the issue's acceptance criteria.

Tests: 2 new regression tests in `tests/unit/analysis/test_cache_alias_promoted_context.py` verified
  to FAIL on `main` and PASS on this branch. Full pytest suite: 1795 passed, 3 skipped, 10 xfailed
  in 32.59s. 9/9 manual blackbox test plan rows PASS, including verification that `detail_level` and
  `assess` changes still trigger fresh LLM calls (strict validation preserved).

Closes #129

- **investigator**: Fix tool responses and improve investigation UX
  ([#70](https://github.com/jpshackelford/ohtv/pull/70),
  [`7eb90f3`](https://github.com/jpshackelford/ohtv/commit/7eb90f374278610cbe75520399174d388319b35b))

fix(investigator): add missing name field to tool responses and improve UX

Fix AssertionError when using `ohtv ask --agent` by adding the required `name` field to tool
  response messages. The SDK now validates that tool_call_id and name must be present together.

Bug fix: - Add name=tool_call.name to Message construction in _add_tool_response()

UX improvements: - Show preliminary RAG answer before investigation begins - Display tool progress
  with context (📖/🔍/🔗 icons) - Show agent thinking steps with 💭 indicator - Synthesize partial
  findings when hitting iteration limit - Process multiple tool calls in batch before next LLM
  iteration

Test coverage: - 24 new/updated tests for investigation mode - 8 tests for _show_tool_progress() - 4
  tests for _synthesize_partial_findings() - 2 tests for multi-tool batching - 1104 total tests
  passing

Closes: Investigation mode AssertionError

Co-authored-by: openhands <openhands@all-hands.dev>

- **investigator**: Update tool_call attribute access for SDK v1.21
  ([#68](https://github.com/jpshackelford/ohtv/pull/68),
  [`4269995`](https://github.com/jpshackelford/ohtv/commit/426999591e6187b892f0435909ad12d2a41abf01))

The OpenHands SDK MessageToolCall class has name and arguments as direct attributes, not nested
  under a function object. The SDK v1.21 flattened this structure from the raw OpenAI API format.

Changed: - tool_call.function.name → tool_call.name - tool_call.function.arguments →
  tool_call.arguments

Co-authored-by: openhands <openhands@all-hands.dev>

- **list**: Date filters imply --all (no pagination)
  ([`a6ba9cd`](https://github.com/jpshackelford/ohtv/commit/a6ba9cde5ba8abd75c5f5dfa011573f1ed9d67aa))

When using --since, --until, --day, or --week, show all matching records without requiring explicit
  --all flag.

Co-authored-by: openhands <openhands@all-hands.dev>

- **prompts**: Add refs_display to display schemas
  ([#30](https://github.com/jpshackelford/ohtv/pull/30),
  [`b3faa67`](https://github.com/jpshackelford/ohtv/commit/b3faa679f1b63fbe55de2423e0fbceb98d29bb3a))

The brief.md and standard_assess.md prompts define display schemas that were missing the
  refs_display field in their Summary columns. This caused the refs data (Repos, PRs, Issues) to be
  omitted from the table output when using 'gen objs -W' or other batch modes.

The fix adds refs_display to the Summary column's fields list in both prompts, restoring the
  behavior that was present before PR #24 introduced the display schema system.

Fixes: refs data missing from gen objs table output

Co-authored-by: openhands <openhands@all-hands.dev>

- **sync**: Sort by updated_at DESC in reset_to_n_newest
  ([#107](https://github.com/jpshackelford/ohtv/pull/107),
  [`470a8c0`](https://github.com/jpshackelford/ohtv/commit/470a8c0dc346d1b117c0b62c013064490f8afab1))

The /search endpoint returns items in created_at DESC and exposes no sort parameter, so '--force -n
  N' was keeping the N most recently *created* conversations instead of the documented N most
  recently *updated*. Adds a client-side sort by updated_at DESC before truncation; items with
  missing/None updated_at sort to the end so an unknown timestamp can't displace a known-recent
  conversation.

Also corrects the inline comment in sync.py and REFERENCE_CLOUD_API.md L130, both of which
  propagated the false 'API sorts by updated_at' claim.

Test coverage: new TestResetToNNewest class in tests/unit/test_sync.py (4 cases — regression for
  #107, missing-updated_at semantic, N>=total, empty cloud no-op). Full suite 1695 passed.

Fixes #107

### Chores

- Log expansion of #121 to WORKLOG
  ([`f84f290`](https://github.com/jpshackelford/ohtv/commit/f84f2902d15e7113b20dba19584515919d78c84a))

Co-authored-by: openhands <openhands@all-hands.dev>

- Orchestrator 2026-05-27T18:16Z — spawn merge #117 + expansion #111 + truncate worklog
  ([`48836f3`](https://github.com/jpshackelford/ohtv/commit/48836f36abf081d26e5864a57ed34d2be582ee08))

- Spawn merge worker (a391f63) for PR #117: CI green, manual test ✅, 0 threads, AI bot 🟢 - Spawn
  expansion worker (d7d93bc) for #111: keystone — #110 + #112 both ready - Archive WORKLOG lines
  590-1758 (04:21–12:17 UTC, ~1168 lines) to same-day archive - Keep recent 6h (12:17–17:55 UTC) +
  new entry on top

Co-authored-by: openhands <openhands@all-hands.dev>

- Orchestrator 21:46Z cycle + worklog truncation
  ([`3d337ea`](https://github.com/jpshackelford/ohtv/commit/3d337ead59281aec5ae22639c9d2ad4c7e53f728))

Archive 5 zombie-cycle entries (13:19-15:18 UTC) to WORKLOG_ARCHIVE_2026-05-27.md. Both worker slots
  remain intentionally idle: expansion blocked by ordering-risk policy on #114 (waiting on
  #111/#112), PR slot deferred by Hypothesis-age gate on PR #119 (~2026-06-03; today is 7 days
  early).

Co-authored-by: openhands <openhands@all-hands.dev>

- Orchestrator cycle 2026-05-27T17:22:49Z — spawned expansion #110 + impl #107 (parallel)
  ([`05fef02`](https://github.com/jpshackelford/ohtv/commit/05fef02a87ccb5f16e5460dd7289332ed1f8aed1))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog - completed impl of #91 (PR #95 ready)
  ([`c363634`](https://github.com/jpshackelford/ohtv/commit/c363634101aabf24c258785a04592feb0f9f9ce2))

- Worklog - PR #106 merged, issue #103 closed
  ([`6734e21`](https://github.com/jpshackelford/ohtv/commit/6734e21bb8db2bf5fbdacd00d822ab2825191c7f))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog - PR #94 merged (issue #79)
  ([`05a3b4a`](https://github.com/jpshackelford/ohtv/commit/05a3b4a53cdf3482bd81a41f215ee5252c3c2551))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog - spawned impl worker for #91, archived 2026-05-22 entries
  ([`218baa5`](https://github.com/jpshackelford/ohtv/commit/218baa5ce8f4944ef6953c0bf67b705b1aa03c54))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog - spawned review worker for PR #95 ([#91](https://github.com/jpshackelford/ohtv/pull/91),
  [`958b3d4`](https://github.com/jpshackelford/ohtv/commit/958b3d41f33de32f9c73285eff1ca3cf0cb923fb))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog - spawned testing worker for PR #95 ([#91](https://github.com/jpshackelford/ohtv/pull/91),
  [`c602237`](https://github.com/jpshackelford/ohtv/commit/c60223771ce966196b7d82297ede318126cf2c34))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog - sync rewrite planning, 8 issues filed (#107-#114)
  ([`df5e549`](https://github.com/jpshackelford/ohtv/commit/df5e5497cb4a40a3341f9a720e1500f4ac860629))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog 2026-05-22T05:50Z — test PR #93, expand #90
  ([`ba9b25a`](https://github.com/jpshackelford/ohtv/commit/ba9b25acaf2f4af15d0a3d81af8d034991eb3c7d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog 2026-05-26 11:19Z - spawn merge worker for PR #94, amend #89 with make_progress AC
  ([`0b45b97`](https://github.com/jpshackelford/ohtv/commit/0b45b977fcbf02583c67d590516922faa19433aa))

Acknowledges 2026-05-26 10:50 UTC user INSTRUCTION: - Spawns Merge Worker (conv 3f5aacd) for PR #94
  (closes #79). - Amends Issue #89 to bind `gen titles` progress bars to the shared
  `make_progress(...)` helper from #91, and lists #91 as a hard dependency alongside the
  (already-merged) #86.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog 2026-05-26 11:21Z - acknowledge INSTRUCTION; mitigate duplicate merge worker spawn for PR
  #94
  ([`c7b6293`](https://github.com/jpshackelford/ohtv/commit/c7b629319211024bfc901667a19393734b7711ad))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog 2026-05-27 18:51 UTC - orchestrator spawns impl #110 + exp #108
  ([`1a1cdb3`](https://github.com/jpshackelford/ohtv/commit/1a1cdb38dd465bece3704b48d1a012f8d9d33ede))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog 2026-05-27T17:53Z — spawned testing #117 + expansion #112
  ([`0751db3`](https://github.com/jpshackelford/ohtv/commit/0751db304739fe589c6e6f5f3123a6e53f34e476))

- Worklog 22:20Z — spawn expansion for #121 (CLI logging); 8 new issues #121-#128
  ([`f339d6d`](https://github.com/jpshackelford/ohtv/commit/f339d6dc10828e20b99c7ac839cac60613e8440b))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog entry for #124 expansion
  ([`430cd9f`](https://github.com/jpshackelford/ohtv/commit/430cd9f7c3596ff35c187137cd4914fe5c31b803))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog entry for Issue #86 implementation
  ([`9dec2e8`](https://github.com/jpshackelford/ohtv/commit/9dec2e8e0ac539ed96554477ac1dc85c6e38cf4e))

- Worklog entry for issue #91 expansion
  ([`b3d4ac0`](https://github.com/jpshackelford/ohtv/commit/b3d4ac0088c6026ac1a71da799ba4757f6accb7d))

- Worklog entry for PR #88 merge
  ([`bd5b781`](https://github.com/jpshackelford/ohtv/commit/bd5b781f0cd88eea8c5574ad506ad60db82aba90))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog entry for PR #93 QA fix
  ([`9ba7675`](https://github.com/jpshackelford/ohtv/commit/9ba76751006a43c320a4ab277be25454cfe6c006))

_This commit was created by an AI agent (OpenHands) on behalf of @jpshackelford._

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog entry — issue #111 expanded
  ([`842dc04`](https://github.com/jpshackelford/ohtv/commit/842dc041d49206effb489878440b0d151f47853c))

Posted technical-approach comment on issue #111 and applied 'ready' label. #111 is the headline fix
  of the sync-rewrite critical path. Comment ties #110 (test harness) + #112 (schema) into the
  set-diff engine plan.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog follow-up — PR #106 merged by human at 15:50Z
  ([`3f8b6c7`](https://github.com/jpshackelford/ohtv/commit/3f8b6c781ceaa36349b21766aab651fc42539b1c))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog instruction 2026-05-26T10:50Z — auth resolved, route #91 → #89 first
  ([`977fba9`](https://github.com/jpshackelford/ohtv/commit/977fba99002b2ec58b3e6fc2f9d6fd8291b3e408))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - expanded issue #53
  ([`282c57f`](https://github.com/jpshackelford/ohtv/commit/282c57f18f303fceb6e746e205648d55954c6dea))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - expansion worker for #102
  ([`8565ca6`](https://github.com/jpshackelford/ohtv/commit/8565ca6ed23f61b723489dcd6c912c8b5f102327))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - merged PR #55
  ([`281173b`](https://github.com/jpshackelford/ohtv/commit/281173b1f4906cd486eaec8748f9c3ffcbd7d8b3))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - PR #101 opened for #82 (chart velocity)
  ([`a940e0f`](https://github.com/jpshackelford/ohtv/commit/a940e0f4d710cb83179f87821f32ad33e44ece35))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - PR #55 for issue #45
  ([`eca9a2b`](https://github.com/jpshackelford/ohtv/commit/eca9a2b4d0fe4366008e3b9b4f8ebbdf753a9ba8))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - PR #73 implements issue #53 (conversation labels)
  ([`d49785b`](https://github.com/jpshackelford/ohtv/commit/d49785b64843df30c844bf735ab7deaf4b557e31))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - PR #73 merged
  ([`71b56f1`](https://github.com/jpshackelford/ohtv/commit/71b56f1dbfbd6936b0c4e2bd86ef9db036e8246b))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - spawn testing worker for PR #98
  ([`5235068`](https://github.com/jpshackelford/ohtv/commit/5235068c9d84d31ecf67c73f13b2f1a37a4ae7b9))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update - spawned impl worker for #53, archived old entries
  ([`2cebb0f`](https://github.com/jpshackelford/ohtv/commit/2cebb0f1de306a051b16ee7a0ddfbf4d925ac88d))

- Worklog update 2026-05-05T12:19:57Z
  ([`c1b24b8`](https://github.com/jpshackelford/ohtv/commit/c1b24b83fd27f77750b4504145574f02ffb747f7))

- Worklog update 2026-05-05T12:50:20Z
  ([`b72ae3e`](https://github.com/jpshackelford/ohtv/commit/b72ae3e033318ce634e9e710143f46c5c3b708c8))

- Worklog update 2026-05-05T13:20:26Z
  ([`4ef6c06`](https://github.com/jpshackelford/ohtv/commit/4ef6c063e232f2173d7e7b1ce560ea8ef3c68a1f))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-05T13:50:38Z
  ([`394eb70`](https://github.com/jpshackelford/ohtv/commit/394eb70be714fe003d2eb3a106351e12e07e369c))

- Worklog update 2026-05-05T14:19:14Z
  ([`f42591a`](https://github.com/jpshackelford/ohtv/commit/f42591a93c1605237deab1c0e847c4d85d6e78cd))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-05T14:50:50Z
  ([`6879ebb`](https://github.com/jpshackelford/ohtv/commit/6879ebb2e57d7d98f6bcd9c7de2dd239a2ed638a))

- Worklog update 2026-05-05T15:20:13Z
  ([`679068d`](https://github.com/jpshackelford/ohtv/commit/679068d17b3224716f2aba6a6e149b0bf11c012c))

- Worklog update 2026-05-05T15:49:23Z
  ([`b73d839`](https://github.com/jpshackelford/ohtv/commit/b73d83940c71286c0c00e38f6a58d1c1b89438f7))

- Worklog update 2026-05-05T16:19:54Z
  ([`f8839ea`](https://github.com/jpshackelford/ohtv/commit/f8839ea23b420477b549e9d222de2b99c1365c26))

- Worklog update 2026-05-05T16:50:13Z
  ([`eb96edb`](https://github.com/jpshackelford/ohtv/commit/eb96edb5f65ab25a95730189d18d039f94aa35a1))

- Worklog update 2026-05-05T17:20:36Z
  ([`47df62d`](https://github.com/jpshackelford/ohtv/commit/47df62da36091b612b01a3df05ed0dbe62da1198))

- Worklog update 2026-05-05T17:48:32Z
  ([`4015036`](https://github.com/jpshackelford/ohtv/commit/4015036f28a4c62f5ebe023487c10267d64cf9be))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-05T18:18:36Z
  ([`133e29f`](https://github.com/jpshackelford/ohtv/commit/133e29f61c8f86752cb2a852d4cd19a6e6884f3f))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-05T18:47:50Z
  ([`bab9975`](https://github.com/jpshackelford/ohtv/commit/bab997579c96ffe29a91bf2e368dfb56c95b7f98))

- Worklog update 2026-05-05T19:19:23Z
  ([`30079ed`](https://github.com/jpshackelford/ohtv/commit/30079ed2222ba49532a7e8662cddd780f806a3a9))

- Worklog update 2026-05-05T19:48:27Z
  ([`50b9f73`](https://github.com/jpshackelford/ohtv/commit/50b9f73737e1a5e42edb21a7b29defa3dd2cfed2))

- Worklog update 2026-05-05T20:18:29Z
  ([`3c4c024`](https://github.com/jpshackelford/ohtv/commit/3c4c024b5baec36037d98d4ac77108629ab9bc8a))

- Worklog update 2026-05-05T20:48:00Z
  ([`4efeeef`](https://github.com/jpshackelford/ohtv/commit/4efeeefe6291a11cf2738ae6d1d2dad1b0d8def5))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-05T21:33:12Z
  ([`d70cace`](https://github.com/jpshackelford/ohtv/commit/d70cace980f373659a0b8f2c9c7bf950efc88341))

- Worklog update 2026-05-05T21:49:37Z
  ([`34db04c`](https://github.com/jpshackelford/ohtv/commit/34db04c0e8476cfd5cae4efe49d0f1a3b239980d))

- Worklog update 2026-05-05T22:20:05Z
  ([`a53264e`](https://github.com/jpshackelford/ohtv/commit/a53264eb4ae9cb55b9045b93e333239391e3079c))

- Worklog update 2026-05-05T22:49:15Z
  ([`8937a49`](https://github.com/jpshackelford/ohtv/commit/8937a490601bd99422fa4668bd8ad34e3f84cc27))

- Worklog update 2026-05-05T23:19:38Z
  ([`931f1ca`](https://github.com/jpshackelford/ohtv/commit/931f1ca0261bf3a161e57075f98a333be854d69d))

- Worklog update 2026-05-05T23:48:46Z
  ([`eb3187a`](https://github.com/jpshackelford/ohtv/commit/eb3187aea41aaa8c7967a1616d1ed488a9575232))

- Worklog update 2026-05-06T00:20:19Z
  ([`3eb30bd`](https://github.com/jpshackelford/ohtv/commit/3eb30bd6d34a31bff148c060557785bedd42d042))

- Worklog update 2026-05-06T00:51:31Z
  ([`bfb7818`](https://github.com/jpshackelford/ohtv/commit/bfb781835895db054e14cf73fa43360e8b588be3))

- Worklog update 2026-05-06T01:20:04Z
  ([`317519a`](https://github.com/jpshackelford/ohtv/commit/317519acea3a024951e7ab660e8aa9d14b9a40aa))

- Worklog update 2026-05-06T01:50:24Z
  ([`098fb68`](https://github.com/jpshackelford/ohtv/commit/098fb6804e1b6e959da5916d9ea41b6dedcdb461))

- Worklog update 2026-05-06T02:18:32Z
  ([`a54ae78`](https://github.com/jpshackelford/ohtv/commit/a54ae7873975702cba08808bebda7c56470f663d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-06T02:47:50Z
  ([`7915084`](https://github.com/jpshackelford/ohtv/commit/79150847d7b69195274c418932eaba15bdee3dbb))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-06T03:53:12Z - auto-disabled
  ([`6a099df`](https://github.com/jpshackelford/ohtv/commit/6a099df7f15a0950728d68de91c9b3b42c4ffbfd))

- Worklog update 2026-05-06T16:02:01Z
  ([`e95a589`](https://github.com/jpshackelford/ohtv/commit/e95a58972f1ff467393c5f7af6445f75e71b956a))

- Worklog update 2026-05-06T16:19:23Z
  ([`063e635`](https://github.com/jpshackelford/ohtv/commit/063e6355d7c645d22df3349cde5204e1925d13d9))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-06T16:48:14Z
  ([`ccd1aad`](https://github.com/jpshackelford/ohtv/commit/ccd1aad0fab607098e9a9d06c2fb0c6c790a7dc9))

- Worklog update 2026-05-06T17:17:18Z
  ([`238e047`](https://github.com/jpshackelford/ohtv/commit/238e047d91896be43a50e306fd374d74f2948d08))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-06T17:48:16Z
  ([`08b38f6`](https://github.com/jpshackelford/ohtv/commit/08b38f6e1a8d09d1a0fd4e3dbe8b436529a80410))

- Worklog update 2026-05-14T13:38:43Z
  ([`5bc65fd`](https://github.com/jpshackelford/ohtv/commit/5bc65fd50ce6be7d57b5a38639989e53844176fc))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-14T13:50:43Z
  ([`457bd37`](https://github.com/jpshackelford/ohtv/commit/457bd37abb7ebc84f4428ac2a28abf0e1613a16d))

- Worklog update 2026-05-14T14:22:39Z
  ([`80ce417`](https://github.com/jpshackelford/ohtv/commit/80ce417beb1a1338ff707f5df2761144e69b0a91))

- Worklog update 2026-05-14T14:50:52Z
  ([`0cd7c10`](https://github.com/jpshackelford/ohtv/commit/0cd7c1072156b80d105fe8af00b288a680fccdd7))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-14T15:52:26Z
  ([`314f517`](https://github.com/jpshackelford/ohtv/commit/314f5177f4cbb51cf1cae3fa1c7f1e837c1b42d9))

- Worklog update 2026-05-14T16:19:41Z
  ([`795e333`](https://github.com/jpshackelford/ohtv/commit/795e333733c1fe8683b9e7d76f81da2f424a819c))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-14T16:47:24Z
  ([`b18c19d`](https://github.com/jpshackelford/ohtv/commit/b18c19d15081c18d3b6f24d64fb418707904045c))

- Worklog update 2026-05-14T17:18:01Z - auto-disabled
  ([`09ab905`](https://github.com/jpshackelford/ohtv/commit/09ab9053b89b9e65c7fe8c796a3227744d2f4a67))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-14T22:31:34Z
  ([`6612df5`](https://github.com/jpshackelford/ohtv/commit/6612df58c306e8c3b6f5748df687129bd22c97af))

- Worklog update 2026-05-14T22:48:08Z
  ([`129d954`](https://github.com/jpshackelford/ohtv/commit/129d954466ecaebb13beddebc120ead26161c9ff))

- Worklog update 2026-05-14T23:22:21Z
  ([`aacaa02`](https://github.com/jpshackelford/ohtv/commit/aacaa02db670b0bb4faaf9d0ce9e5a3271afa77e))

- Worklog update 2026-05-15T01:46:59Z
  ([`22460d0`](https://github.com/jpshackelford/ohtv/commit/22460d05c611d6e1d4b5ff8bb086a2453cd4ecb5))

- Worklog update 2026-05-15T01:50:38Z
  ([`c5a06f4`](https://github.com/jpshackelford/ohtv/commit/c5a06f47e229b59e7308cfe8c364741105917441))

- Worklog update 2026-05-15T02:21:42Z
  ([`421882d`](https://github.com/jpshackelford/ohtv/commit/421882d7e76264569151b1560afa4c193d521aa8))

- Archived 44 old entries to daily archive files - Spawned implementation worker for Issue #44
  (progress bar) - Spawned expansion worker for Issue #45 (progress bar bug) - Applied priority:high
  to #44, priority:medium to #35

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T02:51:50Z
  ([`09c9b14`](https://github.com/jpshackelford/ohtv/commit/09c9b143b458d21421e934cc13d3dc1f4d4f28ce))

- Worklog update 2026-05-15T03:19:50Z
  ([`d22196f`](https://github.com/jpshackelford/ohtv/commit/d22196f0ad2724c3d1552e97c6811305e2293d0e))

- Worklog update 2026-05-15T03:51:02Z
  ([`66b7a61`](https://github.com/jpshackelford/ohtv/commit/66b7a61fca96189050e045ffa25afcc21357f465))

- Worklog update 2026-05-15T09:19:31Z
  ([`289962d`](https://github.com/jpshackelford/ohtv/commit/289962dc7af23a255f873215194042bddbde5c01))

- Worklog update 2026-05-15T09:51:05Z
  ([`ea497a8`](https://github.com/jpshackelford/ohtv/commit/ea497a80e4784dd8ae31bc75ed5604a00c7ba76e))

- Worklog update 2026-05-15T10:19:56Z - archive old entries, spawn merge worker
  ([`b06eac1`](https://github.com/jpshackelford/ohtv/commit/b06eac1460b0c882cb860b582e82ba478025cb82))

- Archived 14 old entries spanning 2026-05-14 to 2026-05-15 - Kept 5 recent entries spanning 6+
  hours of productive work - Spawned merge worker for PR #54 (6a781cf)

- Worklog update 2026-05-15T10:49:32Z
  ([`bea5721`](https://github.com/jpshackelford/ohtv/commit/bea57210757c019e8a9dc0cbf13d8fd9e9c584e1))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T11:20:28Z
  ([`a6fb7ad`](https://github.com/jpshackelford/ohtv/commit/a6fb7ad2f39f8027368a90d36d93c80179f5ef23))

- Worklog update 2026-05-15T11:49:28Z
  ([`26c6a7a`](https://github.com/jpshackelford/ohtv/commit/26c6a7abd0ed04f8ef388615c1928c34598b371e))

- Worklog update 2026-05-15T12:18:29Z
  ([`ad55240`](https://github.com/jpshackelford/ohtv/commit/ad55240794f7574ef46b2e746066a25d64d9c6b4))

- Worklog update 2026-05-15T12:50:51Z
  ([`63df928`](https://github.com/jpshackelford/ohtv/commit/63df92880d115b61061e09933bb442d6cfe2f497))

- Spawned implementation worker for issue #52 (priority:high) - Truncated worklog from 379 to 150
  lines - Conv: 51747fb

- Worklog update 2026-05-15T13:23:21Z
  ([`7919f8e`](https://github.com/jpshackelford/ohtv/commit/7919f8e9db1420bbe4d061bf542f7ab0b5cf119c))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T14:50:43Z
  ([`d3af143`](https://github.com/jpshackelford/ohtv/commit/d3af143728db778edc2b17c28a4e0297b4a19322))

- Worklog update 2026-05-15T15:20:35Z
  ([`1efb4f0`](https://github.com/jpshackelford/ohtv/commit/1efb4f0c981599b523e8a19e3c0c48f3c4997356))

- Worklog update 2026-05-15T15:51:32Z
  ([`eaf332a`](https://github.com/jpshackelford/ohtv/commit/eaf332aa9ca2e3516205f85c820493c6e517a184))

- Worklog update 2026-05-15T16:20:23Z
  ([`0021617`](https://github.com/jpshackelford/ohtv/commit/0021617647bb6aad25c22b0bbdd5b0fc0e86b38e))

- Worklog update 2026-05-15T16:51:01Z
  ([`a373d91`](https://github.com/jpshackelford/ohtv/commit/a373d917a04daaa3dff4bdf88a7380dc59930468))

- Worklog update 2026-05-15T17:21:17Z
  ([`3d2728b`](https://github.com/jpshackelford/ohtv/commit/3d2728bca43d325989efe32d988e54d219f08ffb))

- Worklog update 2026-05-15T17:49:49Z
  ([`3303a7c`](https://github.com/jpshackelford/ohtv/commit/3303a7c07f56f1a510956dbd95b07db01e283481))

- Worklog update 2026-05-15T18:22:05Z
  ([`9029e5a`](https://github.com/jpshackelford/ohtv/commit/9029e5aebc8bff99e83b1badf09e9a8aa0ce7654))

- Worklog update 2026-05-15T18:53:33Z
  ([`833ceb0`](https://github.com/jpshackelford/ohtv/commit/833ceb0872cac94e3827dd1bd02ea9f457afcd60))

- Worklog update 2026-05-15T19:23:59Z
  ([`f4c3454`](https://github.com/jpshackelford/ohtv/commit/f4c3454e64b822bf07a920b24aec2ecba5190db2))

- Spawned re-testing worker for PR #62 (conv: 1a3446b) - Archived 9 old entries to daily archive

- Worklog update 2026-05-15T19:52:18Z
  ([`460f75c`](https://github.com/jpshackelford/ohtv/commit/460f75cf92a3af49a5fba0254a5c8a11b7510997))

- Worklog update 2026-05-15T20:50:02Z
  ([`a4f4fd1`](https://github.com/jpshackelford/ohtv/commit/a4f4fd1d2ee173ff8b9264ddf12a6309ffb0b934))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T21:21:14Z
  ([`32ab70f`](https://github.com/jpshackelford/ohtv/commit/32ab70f6575728b23d45b7e2cb83777d3aeacfc1))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T21:49:46Z
  ([`3e2220a`](https://github.com/jpshackelford/ohtv/commit/3e2220a7a8caeebdc15f2f7e0e90da99dc91cd33))

- Worklog update 2026-05-15T22:20:32Z
  ([`9cc0086`](https://github.com/jpshackelford/ohtv/commit/9cc0086ee671091c53a0f0937a604c1a29f879f8))

- Worklog update 2026-05-15T22:49:16Z
  ([`bfbea8b`](https://github.com/jpshackelford/ohtv/commit/bfbea8b3e9e6b0aaf34564447b49d8c12de01462))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T23:19:56Z
  ([`435949e`](https://github.com/jpshackelford/ohtv/commit/435949e22eb59168998b8bcb97123058cb9cd11d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-15T23:20:00Z
  ([`ef47665`](https://github.com/jpshackelford/ohtv/commit/ef47665ff17efeaf1dacdac17f3f76fb131125f6))

- Worklog update 2026-05-15T23:51:00Z
  ([`3afe18b`](https://github.com/jpshackelford/ohtv/commit/3afe18bea50337fed888c4857e068afede9a2939))

- Worklog update 2026-05-16T00:19:26Z
  ([`78b17a9`](https://github.com/jpshackelford/ohtv/commit/78b17a99fbcb731d9ecd8ddfe28f4c13e10de17a))

- Worklog update 2026-05-16T00:51:50Z
  ([`ca5c372`](https://github.com/jpshackelford/ohtv/commit/ca5c37260df20b85a3ef20ceb7ced0efa9482edc))

- Worklog update 2026-05-16T01:20:16Z
  ([`97fd779`](https://github.com/jpshackelford/ohtv/commit/97fd7795f28f8580bb5ad802591eaa201d27baa2))

- Worklog update 2026-05-16T01:52:58Z
  ([`4f0ad60`](https://github.com/jpshackelford/ohtv/commit/4f0ad608273465f98d1250d5187b142f5a3ac12b))

- Spawned merge worker for PR #66 - PR meets merge criteria: CI green, approved review, manual tests
  passed

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T02:21:33Z
  ([`123aee2`](https://github.com/jpshackelford/ohtv/commit/123aee2855b58caa343cb4ed5e603e9ac3136a50))

- Worklog update 2026-05-16T02:50:56Z
  ([`a26c953`](https://github.com/jpshackelford/ohtv/commit/a26c953e2664c2eb8ce2e5a6504153ef7e780229))

- Worklog update 2026-05-16T03:19:50Z
  ([`7cab33b`](https://github.com/jpshackelford/ohtv/commit/7cab33b55d3bc31df53e2e5dcdba2f4544f86077))

- Worklog update 2026-05-16T03:51:51Z
  ([`b1f530b`](https://github.com/jpshackelford/ohtv/commit/b1f530b66651a8090fa44293c05fec449d0d0a33))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T04:20:43Z
  ([`45de2ee`](https://github.com/jpshackelford/ohtv/commit/45de2ee46ff638d4cba051a8bbd9f7ddeb63bd5c))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T04:52:15Z
  ([`cfa4d1c`](https://github.com/jpshackelford/ohtv/commit/cfa4d1c41fec3d8b63a86abf5aa4098541c4024a))

- Worklog update 2026-05-16T05:52:22Z
  ([`9b33bac`](https://github.com/jpshackelford/ohtv/commit/9b33bacac53a4d0e5b6bdec3a96398ca481f9d5d))

- Worklog update 2026-05-16T06:21:44Z
  ([`1621f71`](https://github.com/jpshackelford/ohtv/commit/1621f7163b04687c5905985f81b768e54df1f751))

- Worklog update 2026-05-16T06:51:02Z
  ([`cce580f`](https://github.com/jpshackelford/ohtv/commit/cce580f4edd84af0e13dfd0e3fe2c2ac90c83a9a))

- Worklog update 2026-05-16T07:19:54Z
  ([`ae42bf3`](https://github.com/jpshackelford/ohtv/commit/ae42bf35781b57b6809ce34ffee64c033e903b1a))

- Worklog update 2026-05-16T07:50:43Z
  ([`7a791a3`](https://github.com/jpshackelford/ohtv/commit/7a791a3cb7ab511d35c055f67f4266e8b34a5b5e))

- Worklog update 2026-05-16T08:20:56Z
  ([`6e14b5b`](https://github.com/jpshackelford/ohtv/commit/6e14b5b69b522b50867bef0adbe61efcd325eb08))

- Worklog update 2026-05-16T08:50:40Z
  ([`f59d836`](https://github.com/jpshackelford/ohtv/commit/f59d8363c713ce648df2f36419fbb0efdbfc3df5))

- Worklog update 2026-05-16T09:22:42Z
  ([`f700f1d`](https://github.com/jpshackelford/ohtv/commit/f700f1d659189ab051e3dc87beadf38328867758))

- Worklog update 2026-05-16T09:50:17Z
  ([`973d7e0`](https://github.com/jpshackelford/ohtv/commit/973d7e08fdcf5d22687e0310701bba02669b58ce))

- Worklog update 2026-05-16T10:19:42Z
  ([`580dc85`](https://github.com/jpshackelford/ohtv/commit/580dc85baa18cdecbd092770eca017d10db46087))

- Worklog update 2026-05-16T10:48:43Z
  ([`2d10efc`](https://github.com/jpshackelford/ohtv/commit/2d10efced521eb4ef238269c38eb4f3bb4d2daa7))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T11:22:21Z
  ([`0b050e5`](https://github.com/jpshackelford/ohtv/commit/0b050e52ae326e2544d262879401b54126e94575))

- Worklog update 2026-05-16T12:21:23Z
  ([`a180047`](https://github.com/jpshackelford/ohtv/commit/a18004739a9a4a74823b87f65dc99d00fc58ec39))

- Worklog update 2026-05-16T12:49:53Z
  ([`8b0f157`](https://github.com/jpshackelford/ohtv/commit/8b0f157d682f46a58ae85b442de8acd737cf75bd))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T13:20:29Z
  ([`9817612`](https://github.com/jpshackelford/ohtv/commit/98176121ffea01fb8ca5c3133d8c10f49d6ce5c4))

- Worklog update 2026-05-16T13:50:46Z
  ([`3cb654b`](https://github.com/jpshackelford/ohtv/commit/3cb654b5008536682ec2018b1d44419aa8fef393))

- Worklog update 2026-05-16T14:20:10Z
  ([`6c58e46`](https://github.com/jpshackelford/ohtv/commit/6c58e46921d5aba9a4a61c5318cba1f1ea73e084))

- Worklog update 2026-05-16T14:50:15Z
  ([`b2156c6`](https://github.com/jpshackelford/ohtv/commit/b2156c6240f7762cb5fe8f157c5dfad04211929b))

- Worklog update 2026-05-16T15:19:17Z
  ([`90805b9`](https://github.com/jpshackelford/ohtv/commit/90805b90fc218bbcc767e5fc5c300683fa865b03))

- Worklog update 2026-05-16T15:49:42Z
  ([`d390c06`](https://github.com/jpshackelford/ohtv/commit/d390c06d62e8ccaa9b77e2583d3b9d3d6055ca64))

- Worklog update 2026-05-16T16:20:05Z
  ([`73afbe2`](https://github.com/jpshackelford/ohtv/commit/73afbe230c27a4bcc215e1decaa69ff0428212e4))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T16:50:30Z
  ([`77f392c`](https://github.com/jpshackelford/ohtv/commit/77f392c6f19009688fb01a01d35435cb7421b054))

- Worklog update 2026-05-16T17:22:11Z
  ([`c3d0dc2`](https://github.com/jpshackelford/ohtv/commit/c3d0dc2ada738cd26c0fb90c0716ca0f86d7cb83))

- Worklog update 2026-05-16T17:50:17Z
  ([`d9932e6`](https://github.com/jpshackelford/ohtv/commit/d9932e6e4a543829ea373bbb438e08b1128ae5e4))

- Worklog update 2026-05-16T18:20:48Z - spawned review worker for PR #36
  ([`24f9fbe`](https://github.com/jpshackelford/ohtv/commit/24f9fbee76e1baa7f381fb2e23ed685a3aa37f99))

- Truncated worklog from 999 to ~600 lines - Archived 10 entries to WORKLOG_ARCHIVE_2026-05-16.md -
  Spawned review worker de0692f to address 5 unresolved threads

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T18:50:28Z
  ([`ee2f312`](https://github.com/jpshackelford/ohtv/commit/ee2f3129242fba47d4047256dd87d1fa6bffe700))

- Worklog update 2026-05-16T19:21:33Z
  ([`c5f93d0`](https://github.com/jpshackelford/ohtv/commit/c5f93d0666db950ffef289a6cd9ce93b98b34334))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T19:49:24Z
  ([`a2f4d54`](https://github.com/jpshackelford/ohtv/commit/a2f4d54310c8750e5840ff3a9d01a29bd2900409))

- Worklog update 2026-05-16T20:22:28Z
  ([`0c0b428`](https://github.com/jpshackelford/ohtv/commit/0c0b42814ae515202b6162f6cb3469083dd59fd4))

- Worklog update 2026-05-16T20:49:34Z
  ([`3a1e8dd`](https://github.com/jpshackelford/ohtv/commit/3a1e8dd62d68cf61b0fd3c71b0d9aeec1df0e2bd))

- Worklog update 2026-05-16T21:21:06Z
  ([`5e5bc63`](https://github.com/jpshackelford/ohtv/commit/5e5bc637bce50d012bf1ee22d8ddbd3d19353e6a))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T21:48:47Z
  ([`84b147c`](https://github.com/jpshackelford/ohtv/commit/84b147c5c9328a84d4da28414103d371e3b13aa8))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-16T22:18:21Z
  ([`056a13b`](https://github.com/jpshackelford/ohtv/commit/056a13bbda93dbdc944edb87f772917088011281))

Auto-disabled orchestrator after 3 consecutive quiet periods.

- Worklog update 2026-05-21T17:59:59Z
  ([`e3902d7`](https://github.com/jpshackelford/ohtv/commit/e3902d7febc8761a297805c85822604111036193))

- Truncated worklog (23 entries archived) - Spawned implementation worker for Issue #76

- Worklog update 2026-05-21T18:20:41Z
  ([`823ec8c`](https://github.com/jpshackelford/ohtv/commit/823ec8c2a2584c9b6b2d573f69ed7cd4f242a3da))

- Worklog update 2026-05-21T18:49:17Z
  ([`6aa2f4b`](https://github.com/jpshackelford/ohtv/commit/6aa2f4be9cc03925b4df7406a78d79248b8b84ea))

- Worklog update 2026-05-21T19:21:02Z
  ([`406986b`](https://github.com/jpshackelford/ohtv/commit/406986bafde69f9e3129a0de24e7bf1bb008cfa3))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T19:50:04Z
  ([`ecbb1c2`](https://github.com/jpshackelford/ohtv/commit/ecbb1c2b1e754db7e32a9fcfa9911a3d4abf654c))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T20:22:02Z
  ([`8d9a2e7`](https://github.com/jpshackelford/ohtv/commit/8d9a2e7a7a70656a71c92cc2036c1f4cc9f4e196))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T20:53:57Z - spawned docs worker for PR #85
  ([`a550f02`](https://github.com/jpshackelford/ohtv/commit/a550f0248d1f698ed166d988050b7d6a518eea47))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T21:23:03Z
  ([`8238993`](https://github.com/jpshackelford/ohtv/commit/8238993f0b8f590bb1923d2224eae0dae5174099))

Orchestrator wake-up: - Docs worker d05423f finished (commit 49f2dc9 on PR #85) - Spawned testing
  worker c98452a for PR #85 manual blackbox tests

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T21:51:17Z - respawn testing worker for PR #85
  ([`fe0cfc7`](https://github.com/jpshackelford/ohtv/commit/fe0cfc766537e2ccad416c8e3106cb06f06792f6))

- Worklog update 2026-05-21T22:21:25Z
  ([`f473ee9`](https://github.com/jpshackelford/ohtv/commit/f473ee9de81a4eb589444d1dfc6afe27a2efcdf3))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T22:53:06Z
  ([`4413eb5`](https://github.com/jpshackelford/ohtv/commit/4413eb5938000b3510bdaf73d65636af3717143c))

- Spawn re-testing worker 0872233 for PR #85 - Worker 104623d (review) completed: fix commit 318ea0a
  + invariant test

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T23:20Z - spawn review worker for PR #85
  ([`c308059`](https://github.com/jpshackelford/ohtv/commit/c3080599489573e420179296aabc6a27f1f79a76))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-21T23:55:29Z
  ([`f8e3f06`](https://github.com/jpshackelford/ohtv/commit/f8e3f06a79b6e4c987ff057fd8b00e609ef6c947))

Expanded issue #80 (Add GitHub API LOC fetching command) — labeled ready + priority:medium.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T00:21:00Z
  ([`ca9d5ac`](https://github.com/jpshackelford/ohtv/commit/ca9d5ac6dbbe4137597963c59a619ca6880a38c7))

Orchestrator wake-up: PR slot empty + expansion slot empty. Spawned implementation worker for #78
  (PR contribution detection) and expansion worker for #81 (velocity report) in parallel.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T01:22:37Z
  ([`bcf74e2`](https://github.com/jpshackelford/ohtv/commit/bcf74e25c153712fe27f682402a3d09c3fd9c319))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T01:52:24Z
  ([`d902383`](https://github.com/jpshackelford/ohtv/commit/d9023832b5dd77c677e88abcc125862c2a8917f2))

Orchestrator cycle 01:51 UTC: respawned testing worker for PR #88 (c9da90a) and expansion worker for
  issue #83 (f583779) after prior cycle's workers both produced 0 events. Both new workers verified
  running.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T02:24:13Z
  ([`d4a0a67`](https://github.com/jpshackelford/ohtv/commit/d4a0a677f24e12c3502366b7a11187403c5b0e82))

Spawned review worker for PR #88 and expansion worker for Issue #86.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T02:28Z
  ([`6dff4f1`](https://github.com/jpshackelford/ohtv/commit/6dff4f13f9e42345b077973bc5df3e6ed6439805))

Records review-round on PR #88: resolved both unresolved review threads (platform-detection bug fix
  in _upsert_repo_for; orphan_push_branches list -> set), 1325/1325 tests passing.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T02:56:28Z
  ([`e4434f9`](https://github.com/jpshackelford/ohtv/commit/e4434f91abdc8e284633844d4241a91fdcd77638))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T03:23:04Z
  ([`77f9f7a`](https://github.com/jpshackelford/ohtv/commit/77f9f7a0124c681939d402896f9a4baa7c5aa50e))

- Spawned re-testing worker 8136b8e for PR #88 (post-review code changes) - Spawned expansion worker
  09349b2 for Issue #89 (gen titles) - Archived 254 older lines into WORKLOG_ARCHIVE_2026-05-21.md

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T03:53:56Z
  ([`85d59ae`](https://github.com/jpshackelford/ohtv/commit/85d59ae9d8a22d7e50e241e627e25a5ff3bedcbe))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T06:52:59Z
  ([`78e9b0a`](https://github.com/jpshackelford/ohtv/commit/78e9b0af315a3c8715669b76e392f96bce2218fd))

Spawned 2 workers for the next cycle: - review/fix worker 0e15793 for PR #93 (fix DB write bug found
  in manual test) - expansion worker 3ecb17d for issue #92 (weekly conversion counts CSV)

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T07:20:00Z
  ([`22dc07c`](https://github.com/jpshackelford/ohtv/commit/22dc07c0acf160473341138a4383095568076b6b))

Orchestrator cycle: spawned re-test worker b6dac75 for PR #93 after fix commit 9af9013 lands.
  Expansion slot idle (full backlog ready).

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T07:52Z
  ([`75759b3`](https://github.com/jpshackelford/ohtv/commit/75759b360dca2d5f42ad0a972bea54af51ba083a))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T08:21Z
  ([`e327e80`](https://github.com/jpshackelford/ohtv/commit/e327e802716226ec575012d2e708ec2d35dacaff))

Cycle: spawned re-test worker 2b07b04 for PR #93 at HEAD f02208e. Prior review worker 83019b4
  finished cleanly — accepted thread 1 (extract helper), declined thread 2 (CloudClient reuse) with
  reasoning. 1 new advisory thread seq86ECw5x from github-actions deferred to next review cycle.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T08:52:24Z - spawn review worker for PR #93 round 3
  ([`6261206`](https://github.com/jpshackelford/ohtv/commit/626120655b509a8331c37becf0b08497e9a85185))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T09:18:00Z - spawn re-test worker for PR #93 (round 3 try/finally fix)
  ([`7445aac`](https://github.com/jpshackelford/ohtv/commit/7445aacaf3a4f13b55e71da1c3a957c091b88267))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T10:20:00Z - recovery comment + spawn merge worker for PR #93
  ([`5baa418`](https://github.com/jpshackelford/ohtv/commit/5baa418736bededa81d2683caebc3d1832e8118b))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T10:51Z
  ([`dec5c59`](https://github.com/jpshackelford/ohtv/commit/dec5c59cc8ec14af3033aa93066d9f67abd2f5f8))

- PR #93 merged by human at 10:22Z (squash 89a1352, closes #86) - Spawned implementation worker
  94ff387 for issue #79 (direct push detection) - Committed prior cycle's partial WORKLOG truncation
  (created 22-May archive)

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T10:55Z - PR #94 ready (Issue #79)
  ([`b956253`](https://github.com/jpshackelford/ohtv/commit/b9562533f9a50f59c8efcb5abe2cdc98633079fe))

- Worklog update 2026-05-22T11:21Z + archive #86/#93 saga
  ([`ac65b23`](https://github.com/jpshackelford/ohtv/commit/ac65b23d9b6a0078a805b26063bcb9fea23a78a7))

Spawned manual test worker c217e8d for PR #94 (direct push detection, fixes #79). Archived the
  00:51-10:51 #86/#93 saga (~1000 lines) to WORKLOG_ARCHIVE_2026-05-22.md now that PR #93 is merged.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-22T11:50Z — PR #94 tests 🟢, merge blocked by Cloud API 401
  ([`9dd8c7e`](https://github.com/jpshackelford/ohtv/commit/9dd8c7ec9fadca52e8ed39176e97c67ca477dd3f))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T13:24:34Z - re-spawn #91 impl worker after a119ddf stalled
  ([`0b3563c`](https://github.com/jpshackelford/ohtv/commit/0b3563c58244279d368060d658da733f8308bb04))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T15:22:11Z — spawn merge worker for PR #95
  ([`7ed4f12`](https://github.com/jpshackelford/ohtv/commit/7ed4f1273492b985782aed9f58b34f372de7e4b9))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T15:51:59Z
  ([`e8a46f7`](https://github.com/jpshackelford/ohtv/commit/e8a46f7ba3c5ff24c1fbfca5a6f9e0c0877496ca))

Orchestrator cycle 2026-05-26 15:50 UTC - PR #95 merged (closing #91); spawned implementation worker
  5106f489 for issue #89 (gen titles).

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T16:23:15Z - spawn docs worker for PR #96
  ([`f001ad4`](https://github.com/jpshackelford/ohtv/commit/f001ad4439e7e0406d3feed7189f451075822f3d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T16:52:58Z - spawn testing worker for PR #96
  ([`cf90c41`](https://github.com/jpshackelford/ohtv/commit/cf90c4117f469ac624c8f0d7bb4b243b81434940))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T17:30:06Z - spawn review worker for PR #96 + archive batch
  ([`237f59a`](https://github.com/jpshackelford/ohtv/commit/237f59a8cf6c1eb463dcead4275734b68ae8b698))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T17:49:00Z
  ([`9b10c1f`](https://github.com/jpshackelford/ohtv/commit/9b10c1f138519b561ab027e1740acf0ccaa21388))

Orchestrator: spawned re-testing worker 8750de99 for PR #96 after review worker e009b928 pushed two
  fix commits (6969e959, 5b1f33a2) addressing both manual-test blockers.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T18:22:50Z — spawned merge worker for PR #96
  ([`b63863a`](https://github.com/jpshackelford/ohtv/commit/b63863a1e0caafa5a13a52081a48700262985288))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T19:53:21Z
  ([`a241000`](https://github.com/jpshackelford/ohtv/commit/a241000627590fa7d6792ca8ee28e8e3ab0ad9ba))

Orchestrator cycle 19:51Z: spawned testing worker ebc3363 for PR #97 (ohtv fetch-loc). Docs worker
  007863ee finished; docs commit 79b2c6d2 landed; "Documentation Updated" PR comment present; no
  manual test results yet. Next gate per workflow sequence is testing.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T22:51Z - spawn merge worker for PR #98
  ([`05adff5`](https://github.com/jpshackelford/ohtv/commit/05adff5cabc816418466a1405b88ae6e4897965c))

Spawned merge worker (conv 235b7713) for PR #98 (feat: report velocity). Manual test verdict was
  Ready to review with all 19 acceptance criteria covered, 1617/0/0 unit tests passing, and 0
  unresolved review threads. Two nits flagged as non-blocking spec philosophy disagreements; worker
  instructed to acknowledge in squash commit body rather than change code.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-26T23:51Z - spawn testing worker for PR #99
  ([`6c6a319`](https://github.com/jpshackelford/ohtv/commit/6c6a319fc78c5c0372a735cf51ca9216e4936d20))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T00:23Z - spawn review worker for PR #99
  ([`e78ec56`](https://github.com/jpshackelford/ohtv/commit/e78ec5677fa218a5d77a93f458c8f28b86699093))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T00:51Z
  ([`0243a86`](https://github.com/jpshackelford/ohtv/commit/0243a869cec066608379014251c41d4cd745db3f))

Spawned re-testing worker 06abb078 for PR #99 after review worker 4e867f21 fixed B-1 (short-ID
  prefix), B-2 (no-such-conv error), and B-3 (3 docstring encoding nits) in commit 65df4259.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T01:21Z
  ([`c9133c4`](https://github.com/jpshackelford/ohtv/commit/c9133c4ea4f63e9c8a20702e8793d6c5f6f3aa21))

Spawned merge worker for PR #99 after re-test PASS verdict.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T01:52Z
  ([`898b244`](https://github.com/jpshackelford/ohtv/commit/898b244573f437f96eaaecdb9c3ded733ae738ae))

Spawned implementation worker (d2b32674) for issue #90 (ohtv label batch command, priority:medium).
  Prior cycle's merge worker (66d0620) landed PR #99 cleanly at 01:22:30Z (commit ae38940). PR slot
  now re-occupied by impl worker; expansion slot remains idle.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T02:22Z
  ([`621ee18`](https://github.com/jpshackelford/ohtv/commit/621ee182e5c47b2933d1c1faa3ef2696156b67a3))

- Archive 488 lines from WORKLOG.md (2026-05-26 16:21-19:58Z PR #96/#97 entries) to
  WORKLOG_ARCHIVE_2026-05-26.md. - Record orchestrator cycle: hold applied to #90 (Cloud API
  silently drops PATCH tags); impl worker spawned for #92 (report weekly-counts CSV).

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T02:51Z
  ([`3e009e3`](https://github.com/jpshackelford/ohtv/commit/3e009e3a33815bec88c546d52a8b8151b2064967))

Orchestrator cycle: spawned testing worker fc9bde66 for PR #100 (ohtv report weekly-counts, issue
  #92). Impl worker 14ac006e finished cleanly with docs bundled in. AI bot review positive. Next
  gate is manual testing.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T03:21Z
  ([`ab2e79d`](https://github.com/jpshackelford/ohtv/commit/ab2e79d02229c17c7ab5f3fe7f44eec8fb4d1923))

- Worklog update 2026-05-27T04:21Z - spawn testing worker for PR #101
  ([`567f0c9`](https://github.com/jpshackelford/ohtv/commit/567f0c9f22a3f53092e7d8be5e5ba40aa360f442))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T04:48Z - spawn merge worker for PR #101
  ([`edf27bb`](https://github.com/jpshackelford/ohtv/commit/edf27bb5fef5fe1e276d207bc4070f75fe6ce954))

- Worklog update 2026-05-27T06:23:30Z — spawn testing worker for PR #104
  ([`93d5355`](https://github.com/jpshackelford/ohtv/commit/93d5355d164742d0d46ae3c89403569e14ec3c9e))

- Worklog update 2026-05-27T08:22Z - spawn merge worker for PR #105
  ([`f33f0c6`](https://github.com/jpshackelford/ohtv/commit/f33f0c64eae956efbb0efade38aea2fe75cf0e41))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T09:24:00Z
  ([`37108a2`](https://github.com/jpshackelford/ohtv/commit/37108a24595384b7aed47444718637e914b41788))

Orchestrator cycle: spawned impl worker (conv a49fc55) for Issue #103 after two sandbox-boot ERRORs
  (root cause: plugins block in payload, matching 08:22Z lessons learned).

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T10:22Z - testing worker retry for PR #106
  ([`d39dcd9`](https://github.com/jpshackelford/ohtv/commit/d39dcd9022337ac00e5ec6d75af6ddd50a4d4544))

- Worklog update 2026-05-27T10:46Z - PR #106 testing blocked by 4th zombie spawn
  ([`f26a9fc`](https://github.com/jpshackelford/ohtv/commit/f26a9fc6152ceb12d55e1372fb512079e49965eb))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T11:17Z - PR #106 still blocked, no spawn
  ([`ac26a22`](https://github.com/jpshackelford/ohtv/commit/ac26a2219c4253e98c2836859cc31ce6fdd8b34c))

- Worklog update 2026-05-27T12:17Z + truncate (1850→1169 lines)
  ([`102ba2e`](https://github.com/jpshackelford/ohtv/commit/102ba2e3bee9df29c100e382ac9b42d04bb2cfeb))

PR #106 still blocked on manual-test — 6th identical idle cycle, no retry per 11:17Z pre-commit.
  Archived 10 older entries to keep 6h productive window.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T13:19Z
  ([`d043f4e`](https://github.com/jpshackelford/ohtv/commit/d043f4e78da7098a935b2de870793ab00dd6d4de))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T13:46Z
  ([`5363b00`](https://github.com/jpshackelford/ohtv/commit/5363b00421697ac98e7a0d5717d5e64a341f2939))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T14:16Z
  ([`7658853`](https://github.com/jpshackelford/ohtv/commit/7658853defd5b3431e6257983b513793bbc89545))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T14:46Z
  ([`d64f30a`](https://github.com/jpshackelford/ohtv/commit/d64f30a9d61ab2c5b7e6a2198489e6a94e019658))

Cycle 10/N — still idling on PR #106, no spawn.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T15:21:33Z
  ([`581a788`](https://github.com/jpshackelford/ohtv/commit/581a7883b8c21bd561d40033252201e96935e20c))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T15:46Z — spawned merge worker for PR #106
  ([`ee2ac76`](https://github.com/jpshackelford/ohtv/commit/ee2ac76033e0c6d9c5aaf3437f6ce47a93b32535))

Resume condition (c) met: manual test results landed on PR #106 at 15:37:58Z with verdict 'Ready to
  merge'. Spawned merge worker f06a530 to squash-merge PR #106 (Closes #103). Auto-disable plan from
  cycle-11 entry is dropped per its own escape clause.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T16:20:26Z - all quiet (1/3 toward auto-disable)
  ([`6470cfd`](https://github.com/jpshackelford/ohtv/commit/6470cfd009247bd57fb6d830f7cbe73aba7054c1))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T16:50Z — spawn expansion #107
  ([`82de175`](https://github.com/jpshackelford/ohtv/commit/82de1756fa94d239eed43189fcb594659c364ce6))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T19:22Z - testing #119 + expansion #109 dispatched
  ([`1196675`](https://github.com/jpshackelford/ohtv/commit/1196675364093c3911a2aa109a67869a39f30c30))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T20:53:11Z
  ([`e5686fe`](https://github.com/jpshackelford/ohtv/commit/e5686fee9ed2730760bf3b190ed386c8da78cc4a))

Orchestrator 20:51Z cycle: confirmed #113 expansion landed (bfafacb finished 20:27Z, ready label
  applied, expansion comment + WORKLOG entry posted). Expansion slot reopened, spawned worker
  6c47d56f for #116 (centralize DB migration entry point). PR slot still deferred on PR #119
  hypothesis-age gate. PR #120 remains human-driven, out of orchestrator scope.

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-27T20:56:11Z
  ([`2ff8aba`](https://github.com/jpshackelford/ohtv/commit/2ff8abaf23031bbe4366c562f0f4951bc14a70a1))

- Worklog update 2026-05-27T21:17:00Z
  ([`f9d4f62`](https://github.com/jpshackelford/ohtv/commit/f9d4f620272d558c100ab1cec993f448d649606f))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-28T11:52:00Z
  ([`7c5f342`](https://github.com/jpshackelford/ohtv/commit/7c5f342f32eb17fefc4ca9ce71874d72590381fd))

- Acknowledge ## INSTRUCTION: at line 21 (filed 22:45 UTC) - Spawn expansion worker for #124 (conv
  4f3fbb8)

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update 2026-05-28T12:18Z - spawn expansion for #125
  ([`4cab4cd`](https://github.com/jpshackelford/ohtv/commit/4cab4cdd29ed464b6185495e3862a0eaa44dfbfd))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update — #89 implemented, PR #96 opened
  ([`83424dc`](https://github.com/jpshackelford/ohtv/commit/83424dc9c2e23365c1e3c95b2923c9cbdb5cc298))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update — issue #107 expanded
  ([`3086d8c`](https://github.com/jpshackelford/ohtv/commit/3086d8cde1e166f4d8b025aa1cfbf3061c9da3d0))

- Worklog update — issue #110 expanded
  ([`d2dd488`](https://github.com/jpshackelford/ohtv/commit/d2dd48868da40d6aa7d0618ac8bcf2598d927baf))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update — PR #101 merged
  ([`ae36f75`](https://github.com/jpshackelford/ohtv/commit/ae36f7502d83a03afbc249db76b8abc8702b777d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update — PR #104 opened for #87
  ([`122ed1a`](https://github.com/jpshackelford/ohtv/commit/122ed1a5b09c1de2c99155192cf8e491a46c2213))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update — PR #88 final review thread declined and resolved
  ([`0ad1ff8`](https://github.com/jpshackelford/ohtv/commit/0ad1ff8d4c8734b4a30e36679405dd70b3ef7a05))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update — spawned impl #87 + expansion #102 (parallel)
  ([`c40d5a2`](https://github.com/jpshackelford/ohtv/commit/c40d5a2379dbcf420bfdcef44cd1eae203d834f9))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog — #108 expanded
  ([`0c7379e`](https://github.com/jpshackelford/ohtv/commit/0c7379e8d16fceb144c14a7638f68881790a4f19))

- Worklog — #109 expanded (column ownership + sync.lock contract)
  ([`9c74fcb`](https://github.com/jpshackelford/ohtv/commit/9c74fcb79598572ebca11ef8e4ae09a7de38c535))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog — #112 expanded
  ([`ac37159`](https://github.com/jpshackelford/ohtv/commit/ac371598afed49cd57c56a53212c79385423b994))

- Worklog — #113 expanded (sync --repair four-category UX)
  ([`d94cfb6`](https://github.com/jpshackelford/ohtv/commit/d94cfb68d8414b8aed158758aaf626d5061df857))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog — orchestrator cycle 19:54Z (spawn #113 expansion, defer PR #119, +priority:medium #109)
  ([`75560e4`](https://github.com/jpshackelford/ohtv/commit/75560e40d53db3aaa88c247e5b5257c4f722b2a8))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog — orchestrator cycle 20:22Z (dead-spawn recovery for 703586d, respawn #113 expansion as
  bfafacb, document corrected spawn payload + verification lesson)
  ([`f5fc84f`](https://github.com/jpshackelford/ohtv/commit/f5fc84fdffbb3dd231669f50e865971db3ba709d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog — PR #117 merged (issue #107 closed)
  ([`7c55978`](https://github.com/jpshackelford/ohtv/commit/7c55978d8ee0fb99665827419876630101ea38b2))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog — re-spawned merge worker for PR #94 after botched race-detection
  ([`ffb99ed`](https://github.com/jpshackelford/ohtv/commit/ffb99ed94becc54e7fc8f1eca2848ad5f767469e))

The 11:21Z cycle aborted the only real merge worker (6b3c4c9) believing it was a duplicate of
  3f5aacd, but 3f5aacd does not exist as a real conversation. PR #94 had been sitting unmerged for
  ~30 min. This cycle re-spawns the merge worker (5a0e1a1) and documents the lesson learned about
  distinguishing the POST job-id from the conversation-id.

Co-authored-by: openhands <openhands@all-hands.dev>

- **charts**: Wrap ValueError as click.UsageError for unsupported --chart extension
  ([#102](https://github.com/jpshackelford/ohtv/pull/102),
  [`380aa89`](https://github.com/jpshackelford/ohtv/commit/380aa8994a3872e05df4413f171a6efacb0ebf3a))

- Add a two-line `except ValueError` branch in `src/ohtv/cli.py`'s `report velocity --chart`
  handler, mirroring the adjacent `ImportError → click.UsageError` pattern. Unsupported/missing
  extensions now exit 2 with a single-line `Error: …` instead of a Python traceback (exit 1). - The
  module-level `ValueError` contract in `plot_velocity` (`src/ohtv/reports/charts.py`) is
  intentionally preserved — only the CLI's reaction to that exception is polished. Other API callers
  and `tests/unit/reports/test_charts.py::test_unknown_extension_raises` are unaffected. - Add one
  new test `tests/unit/reports/test_cli_chart.py::test_cli_chart_unsupported_extension` verifying
  exit code 2, the expected error string, and the absence of `Traceback` in output. - Full unit
  suite green at 1739 tests (up from 1738); all 8 blackbox CLI scenarios pass per the manual test
  report comment.

Closes #102

- **main**: Release ohtv 0.14.0 ([#139](https://github.com/jpshackelford/ohtv/pull/139),
  [`46efb57`](https://github.com/jpshackelford/ohtv/commit/46efb57c66742cb0fe01d84707eda775d7c67a0e))

Co-authored-by: github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>

- **worklog**: #107 implementation complete — PR #117 ready for review
  ([`809007f`](https://github.com/jpshackelford/ohtv/commit/809007f8cfadba8f94e566484f6faccc395e5929))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: #114 expanded — manifest/DB dual-store framing + phased plan
  ([`c790246`](https://github.com/jpshackelford/ohtv/commit/c790246095f1c61a9e7266e7f618b268e772c893))

- **worklog**: #125 expanded — gen objs/titles/run roots-only default
  ([`df477a7`](https://github.com/jpshackelford/ohtv/commit/df477a714e7eeb43b461cd5b3c7eeee996eef39a))

Adds `include_subs` flag threaded through `_apply_conversation_filters` → `get_conversations` →
  `list_by_date_range`. Single fix point catches all three gen commands (confirmed via code
  archaeology of cli.py lines 8334, 9093, 9900). Help text + regression test (1 root + 2 subs → 1
  LLM call) + cache-key invariance + pre-#108 cache-fallout policy codified in AC. Blocked-by #122
  (column) which is blocked-by #108.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: #126 expanded — classify auto-step for sub-conversations
  ([`e61d7b8`](https://github.com/jpshackelford/ohtv/commit/e61d7b88783636eb3daf8f57498cdb9b4eec5d68))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: #127 expanded — list/refs sub-conv display surface
  ([`ba7d92c`](https://github.com/jpshackelford/ohtv/commit/ba7d92c255e26864592b1eaaeefbc00506ca9a63))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: #128 expanded — RAG ask/search citation dedup to root grain
  ([`57bbd43`](https://github.com/jpshackelford/ohtv/commit/57bbd43d1ab45aebc957b6e9b27a0ffd8a1ebe39))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: #129 fix landed in PR #131 (draft → ready, CI green)
  ([`df9f5f1`](https://github.com/jpshackelford/ohtv/commit/df9f5f1154a5b4925c3c167898b4e8aa8d2f6ce1))

- **worklog**: All quiet, #111 impl in flight at 2026-05-28T19:20:00Z
  ([`4c2da9e`](https://github.com/jpshackelford/ohtv/commit/4c2da9e082b4ffc7ea80e4dc4ecb0182038ecb12))

- **worklog**: Dispatch impl worker for #111 at 2026-05-28T18:50:28Z
  ([`330be6e`](https://github.com/jpshackelford/ohtv/commit/330be6efadee5c99eb01de21b5374fdeac4f230f))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Dispatch review worker 7d09f3e for PR #137 + archive 8 entries
  ([`3455e10`](https://github.com/jpshackelford/ohtv/commit/3455e108c39ac3b00feb8eccb46a47df9645d15b))

- Spawned review worker for PR #137 (5 minor doc-accuracy fixes from testing worker 5888078's audit;
  all confined to docs/reference/sync-state-ownership.md). - Decision-tree row: PR exists, ready, CI
  green, test results valid, 💬 > 0 → review worker (verdict ⚠️ Minor doc fixes needed). -
  Housekeeping: ran truncate-worklog skill (10th deferred cycle). Archived 8 oldest entries (1390 →
  932 lines pre-this-entry) into WORKLOG_ARCHIVE_2026-05-{28,29}.md per the 6h-productive-span rule.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Dispatch testing worker for PR #137 (#114 Phase A docs audit)
  ([`b2af563`](https://github.com/jpshackelford/ohtv/commit/b2af563274b0d52d649a6826c56a683723bfb78f))

Spawn testing worker 5888078 to verify the sync-state-ownership doc accuracy.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Docs landed for PR #97 / #80
  ([`ce55d20`](https://github.com/jpshackelford/ohtv/commit/ce55d20a9a08898abf46e04d2a95e3ee5dff47d5))

- **worklog**: Docs update for PR #133 set-diff engine
  ([`eeb9532`](https://github.com/jpshackelford/ohtv/commit/eeb953254a53d4ec3fc530a0a448c98dca6c55f9))

- **worklog**: Impl worker #109 — PR #135 opened, CI green, ready
  ([`d40ab31`](https://github.com/jpshackelford/ohtv/commit/d40ab31286455a292c6acc873f7035f9c2f498a6))

- **worklog**: Impl worker #112 complete — migration 018 PR #132 open
  ([`fa9044e`](https://github.com/jpshackelford/ohtv/commit/fa9044e3812b43aa9fdac8c8bdac85ac22be10d2))

- **worklog**: Inline escalation for PR #138 — testing worker 8824962 silent-exit
  ([`73c0054`](https://github.com/jpshackelford/ohtv/commit/73c00542ff2ef20a5e4ad3f287609f821fa3dc3a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Manual test results for PR #97 (fetch-loc)
  ([`2e0e4c7`](https://github.com/jpshackelford/ohtv/commit/2e0e4c79391cce40b5c7634bc268a85cc76eb016))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge PR #133 — set-diff sync engine
  ([#111](https://github.com/jpshackelford/ohtv/pull/111),
  [`b519694`](https://github.com/jpshackelford/ohtv/commit/b51969469e2f549818da5012073cdd3574cc3b35))

Merge commit 92a2805b9ffe04282e5e08dd7a19aa42793a5d31. Issue #111 auto-closed as COMPLETED. Squash
  subject: feat(sync): recover from cloud/local gap via set-diff engine (#111).

- **worklog**: Merge worker 2026-05-27 06:54Z — PR #104 squash-merged d3d3f9cc, Issue #87 closed;
  priority:low applied to #102/#103
  ([`c0561b8`](https://github.com/jpshackelford/ohtv/commit/c0561b8870551a7ebd20a35bb5f6a6cdff7d862f))

- **worklog**: Merge worker dispatched for PR #133 (2026-05-28T23:21:28Z)
  ([`a056fce`](https://github.com/jpshackelford/ohtv/commit/a056fceabe6da963f1e81352a3ace758f31ab62c))

Re-test round 2 verdict APPROVE (LGTM). Spawned merge worker 1204021 to squash-merge PR #133
  (feat(sync): recover from cloud/local gap via set-diff engine (#111)). Verified non-ghost via
  accumulated_cost=$0.98 within 20s of READY.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Merge worker — PR #119 merged
  ([`bda34e9`](https://github.com/jpshackelford/ohtv/commit/bda34e9c2d611146a779cc984b2a00ad1bef6a9b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 01:55Z - merge of #134 confirmed, release-please root cause diagnosed,
  worklog truncated
  ([`ab61bd7`](https://github.com/jpshackelford/ohtv/commit/ab61bd77c0a9b3f46fbacbb178b306c748879ee9))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 03:23Z — docs worker spawned for PR #135
  ([#109](https://github.com/jpshackelford/ohtv/pull/109),
  [`4ee8fc5`](https://github.com/jpshackelford/ohtv/commit/4ee8fc575a9ca903120ea480ea8f2457f6b02898))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 03:52Z — testing worker spawned for PR #135
  ([#109](https://github.com/jpshackelford/ohtv/pull/109),
  [`8b2d2ff`](https://github.com/jpshackelford/ohtv/commit/8b2d2ff98a9fc572aa164b15837b33de40526552))

- **worklog**: Orchestrator 04:20Z — merge worker spawned for PR #135
  ([#109](https://github.com/jpshackelford/ohtv/pull/109),
  [`54ae2ee`](https://github.com/jpshackelford/ohtv/commit/54ae2ee1881d20b5ee2f627e20967e6b83c6b361))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 07:20Z — spawned d770c82 for #114 Phase A
  ([`c7e0029`](https://github.com/jpshackelford/ohtv/commit/c7e0029440d8dfd1272655d6f12c9f9fcbe8d26a))

- **worklog**: Orchestrator 18:50Z — spawn impl #80; archive 11:52Z–13:55Z chain
  ([`1904539`](https://github.com/jpshackelford/ohtv/commit/19045395fb34d4c25c6b0e7df3f7e3131e29eb08))

Spawned implementation worker 6a10472a for issue #80 (ohtv fetch-loc / GitHub API LOC backfill). PR
  slot was empty post-PR #96 merge; #80 selected as highest-priority unblocked ready issue
  (priority:medium, unblocks #81).

Housekeeping: archived 195 lines (11:52Z–13:55Z PR #94 merge + PR #95 impl chain, both fully landed
  >5h ago) from WORKLOG.md to WORKLOG_ARCHIVE_2026-05-26.md to bring the live worklog back under
  control (832 → 724 lines after new entry).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 19:19Z — spawned docs worker for PR #97
  ([`6f39357`](https://github.com/jpshackelford/ohtv/commit/6f39357c818b03f8f094792c6fea46be4ab374ee))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-22T00:52Z - spawn docs/exp workers; truncate
  ([`6122762`](https://github.com/jpshackelford/ohtv/commit/6122762b50aba99a2937642cd236288990742952))

- Spawn docs worker for PR #88 (conv d5736ad) - Spawn expansion worker for #82 charting (conv
  8fdca91) - Truncate-worklog: archived 5 entries (1 to archive-05-16, 4 to new archive-05-21)

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-27 06:51Z — spawn merge worker 7b39f85 for PR #104; archive 7
  entries from 19:51Z–22:51Z 2026-05-26
  ([`c11e985`](https://github.com/jpshackelford/ohtv/commit/c11e985b7d21c573cdd756c0ceada28df439bc06))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-27 07:21Z — spawn impl worker 87d0f99 for #102 (priority:low)
  ([`f7fd398`](https://github.com/jpshackelford/ohtv/commit/f7fd398827855f38404febde1973420e1a56bed5))

PR #104 merged 06:54Z (Issue #87 closed, priority:low applied to #102/#103). PR slot empty, ready
  issues with priority exist, expansion slot has no work. Spawned impl worker for #102 (older by 10s
  vs #103) — matches 06:51Z pre-commit exactly. Pre-committed next-next: impl for #103 once #102 PR
  reaches MERGED.

- **worklog**: Orchestrator 2026-05-27 09:53 UTC - spawn testing worker for PR #106
  ([`58ef38c`](https://github.com/jpshackelford/ohtv/commit/58ef38c287f37eb74856f7ccd458abf3e89ec329))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-28 21:48Z — review round 2 for PR #133 (T6 fix)
  ([`5fc6973`](https://github.com/jpshackelford/ohtv/commit/5fc697344e0a5af2fb1c32391f96b42e99ceeda4))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-28 22:22Z — review-r2 retry for PR #133 after
  silent-spawn-failure
  ([`73743f6`](https://github.com/jpshackelford/ohtv/commit/73743f664c68a7593e80862c1cb510c11d4c1c1d))

- **worklog**: Orchestrator 2026-05-28T14:21Z — spawn merge worker for PR #119 + expansion worker
  for #128
  ([`cd4a91a`](https://github.com/jpshackelford/ohtv/commit/cd4a91a0c2e079631629061ab804c9d9f21b8f2c))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-28T17:50Z — spawn testing worker for PR #132 + archive
  ([`68e47d6`](https://github.com/jpshackelford/ohtv/commit/68e47d68bbe500e508f40cb4ed44f85711d1c80a))

- Truncated WORKLOG.md from 1764 → 81 lines (kept 17 productive entries, ≥6h span) - Archived 29
  entries to WORKLOG_ARCHIVE_2026-05-27.md - Dispatched testing worker conv `033acff` for PR #132
  (schema-only, CI green)

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator 2026-05-28T18:21Z — spawn merge worker for PR #132
  ([`2dcd602`](https://github.com/jpshackelford/ohtv/commit/2dcd602aed570ad7fe222b633df48cc14ecae7f3))

- **worklog**: Orchestrator 2026-05-29T02:49:18Z — spawn impl worker 5c18b8d for #109
  ([`9f1259e`](https://github.com/jpshackelford/ohtv/commit/9f1259e642151a2a99b0cb02b543ebf759aec174))

- **worklog**: Orchestrator 2026-05-29T05:50Z — spawn testing worker for PR #136 + truncate
  ([`8ad5393`](https://github.com/jpshackelford/ohtv/commit/8ad539336bafe1d2d0c9e4a197f4fb1be48e0ede))

- **worklog**: Orchestrator 2026-05-29T06:20Z — spawn review worker for PR #136 thread on
  sync.py:1297
  ([`d0b7d48`](https://github.com/jpshackelford/ohtv/commit/d0b7d480cd63f4369c2edf36a1e3a07e5dac2b1a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator @ 13:22Z — spawn #127 expansion (sub-conv list/refs cluster)
  ([`0867009`](https://github.com/jpshackelford/ohtv/commit/0867009c21c05b9832868cb6fd64677490e18e21))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator cycle 2026-05-28T22:50Z
  ([`ba3a2ad`](https://github.com/jpshackelford/ohtv/commit/ba3a2ad22785980fb8c5dced8a549b97f094f784))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator dispatch impl worker for #113 (sync --repair four-category UX)
  ([`84190b8`](https://github.com/jpshackelford/ohtv/commit/84190b86a9e2d995c11eabc240a5c1b0570236de))

- **worklog**: Orchestrator dispatch merge worker for PR #136 at 06:52Z
  ([`64424b8`](https://github.com/jpshackelford/ohtv/commit/64424b889b0f5ad98e96932054b57c0484bbe74b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator dispatched docs worker for PR #134
  ([`7112d6d`](https://github.com/jpshackelford/ohtv/commit/7112d6d7e0504b95b75d539b6ca4c2644e2fbfbe))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator dispatched impl worker c72b79a for #108 (2026-05-28T23:50Z)
  ([`5f85aa0`](https://github.com/jpshackelford/ohtv/commit/5f85aa0a926371815018c70706c4068ac33bcf60))

PR #133 merged at 23:21:52Z (merge commit 92a2805, issue #111 closed). Merge worker 1204021 finished
  cleanly. PR slot reopened.

Spawned implementation worker c72b79a for issue #108 (sub-conversations silently excluded from sync)
  — canonical pick: lower-numbered of the two priority:medium ready issues. Foundation issue
  blocking #122-#128.

Non-ghost verification PASS at 23:52:15Z. Three consecutive clean spawns since the 22:22Z
  silent-spawn-failure recovery.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator dispatched impl worker for #112
  ([`e9c6cb2`](https://github.com/jpshackelford/ohtv/commit/e9c6cb2dfa0eef7e974436c814a073ad89c058ec))

Spawned implementation worker (conv 2f041bf) for Issue #112 — Schema additions for set-diff sync
  (priority:medium). PR slot was open after PR #131 merged at 16:50Z. Dependency-ordered tie-break
  vs #108/#109/#111.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator dispatched review worker for PR #133 (blocker pr_number bug)
  ([`88f3dff`](https://github.com/jpshackelford/ohtv/commit/88f3dffa6a4379a43d5a2a3dc21518a2f1002173))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator dispatched testing worker for PR #131
  ([`17ec61e`](https://github.com/jpshackelford/ohtv/commit/17ec61e0a02f58b0bb630c7d0cace88b4d456c24))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator escape-hatch closes PR #138 docs gate
  ([`024b464`](https://github.com/jpshackelford/ohtv/commit/024b464f7541077f30b8d6a6e4d9c5f1af787182))

Two consecutive docs workers no-op'd on PR #138. Invoked the inline escape-hatch authorized by the
  10:20Z forecast: pushed docs(indexing): show root/sub split in db status example (commit 39d8596)
  directly on the PR branch and posted a 'Documentation updated' comment matching the docs-gate
  regex.

Next cycle should dispatch the manual-test worker once CI re-greens on the new commit.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator follow-up — PR #119 merged manually at 14:24Z (no-op race)
  ([`b059cdb`](https://github.com/jpshackelford/ohtv/commit/b059cdb5be307bef7cd80356a98db110af3f3aa3))

- **worklog**: Orchestrator post-merge audit — PR #137 shipped, reopened #114 (auto-close incident)
  ([`a6f9025`](https://github.com/jpshackelford/ohtv/commit/a6f902527f33eedd25e8904f2275aface79c4454))

- **worklog**: Orchestrator review-fix worker addressed 5 minor items on PR #137
  ([`0b3a867`](https://github.com/jpshackelford/ohtv/commit/0b3a86741f8cb1f910f8a789ba29f2c824438b22))

Single-commit doc-only review-round response. All edits confined to
  docs/reference/sync-state-ownership.md in 3fd3789; AGENTS.md untouched per Phase C deferral rule.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawn #126 expansion (9fd1509)
  ([`21fc998`](https://github.com/jpshackelford/ohtv/commit/21fc99807e095603c8c41b9cb62c3a5c79720a0b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Orchestrator spawned merge worker for PR #137
  ([`2b576fd`](https://github.com/jpshackelford/ohtv/commit/2b576fdd0fe7031a4f274cfe36a45c6156aeffcb))

- **worklog**: Orchestrator spawned merge worker for PR #85 and expansion worker for #80
  ([`6ff8cee`](https://github.com/jpshackelford/ohtv/commit/6ff8cee82daeed5dd0411d8265b53e2642a15a11))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #119 review-feedback round addressed (head 3cfad65)
  ([`932ac66`](https://github.com/jpshackelford/ohtv/commit/932ac660bb7641b5a4cf2063733847e4808553e7))

Review worker cycle on PR #119: extracted `_filter_by_updated_since` helper (c06de5c), added
  AGENTS.md harness note (3cfad65), updated PR description with structural-split rationale, replied
  to + resolved both review threads (dedup nit + supply-chain waiver citing the `## INSTRUCTION:`
  block).

Full suite green at 1779 passed / 3 skipped / 10 xfailed. CI green on head SHA at ready-flip:
  3cfad657a6f9f42beaceabc06547bf7de4e5024c.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #133 re-test after review round 1
  ([`dade9e3`](https://github.com/jpshackelford/ohtv/commit/dade9e3d6d63cc56a5c95730c5e6f061027abfbf))

T1 (the prior pr_number blocker) verified fixed against live cloud. T2-T5 + T7-T8 all pass on first
  un-blocked attempt. New T6 bug surfaced: ohtv sync --since DATE crashes with TypeError due to
  offset-naive (Click) vs offset-aware (UTC) datetime comparison in _passes_since_filter; introduced
  in commit 92b1896 (original PR commit), not by either fix commit. Verdict: needs work, single
  blocker. Test report at PR #133 issuecomment-4568560756.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #133 review feedback addressed
  ([#111](https://github.com/jpshackelford/ohtv/pull/111),
  [`f3869e4`](https://github.com/jpshackelford/ohtv/commit/f3869e429f48fd5f49629eb03fb715cccb98f445))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #134 merged — squash 211d9ba, release-please dispatched
  ([`20481c3`](https://github.com/jpshackelford/ohtv/commit/20481c3e398d5aa2a41b8884f1f8095e2d3aecc9))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #134 opened for #108 (sub-conversations)
  ([`c5fd063`](https://github.com/jpshackelford/ohtv/commit/c5fd063f1d94f939fe2a4f947c3439e8a3f9fd61))

PR #134 (feat/include-sub-conversations-108) is open as ready-for-review; CI green: lint pass 3s,
  pytest pass 47s, pr-review skipping.

Three-step plan from the technical-approach comment landed: include_sub_conversations default-on
  across CloudClient, migration 019_parent_conversation_id (additive column + index), and
  sync+scanner writeback. Test delta 1805 -> 1824 passing (+19), no new xfails.

All five acceptance criteria from #108 satisfied. Issue will close on PR merge via the 'Fixes #108'
  footer.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #135 merged — squash 4799ad0, release-please still blocked on workflow-permissions
  ([`43faf37`](https://github.com/jpshackelford/ohtv/commit/43faf3746c52ca55458e5027136865f6e7064b2b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #136 merged — squash 764410d, repair four-bucket reconciliation (#113) shipped
  ([`67de7ed`](https://github.com/jpshackelford/ohtv/commit/67de7ede2f99cfbf5ec8640d4283f10ca2a93d35))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #137 merged — sync-state ownership doc shipped
  ([`30056ff`](https://github.com/jpshackelford/ohtv/commit/30056ffb5238a8f4e7de49d7fd3746059dd617a6))

- PR #137 squashed to main at 95c99eb with subject 'docs(sync): add sync-state ownership map and
  phased retirement plan (#114)'. - Phase A deliverable for #114 shipped: 401-line
  ownership/retirement reference doc + AGENTS.md item #27 pointer. - Phases B/C/D remain open — #114
  deliberately NOT closed by the squash body. - Branch feat/sync-state-ownership-doc-114 deleted
  from origin.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Pr #137 opened — sync-state ownership doc (#114 Phase A)
  ([`18d36db`](https://github.com/jpshackelford/ohtv/commit/18d36db5c55cd3ee28453a1ca21c9146b99fb4db))

- **worklog**: Re-spawn docs worker for PR #138 (prior worker no-op)
  ([`c3c73e2`](https://github.com/jpshackelford/ohtv/commit/c3c73e271a9dc8ccc9d2cb360a947e294bfeb87a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Re-testing worker dispatched for PR #133 (post-blocker-fix)
  ([`0a588d0`](https://github.com/jpshackelford/ohtv/commit/0a588d0c0344a7773e667dc8896a7c2833e9f186))

- **worklog**: Record #111 set-diff sync engine landing (PR #133)
  ([`d3d0dde`](https://github.com/jpshackelford/ohtv/commit/d3d0dde5c192f224d06b5ebcf2af364b4989777c))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record docs worker dispatch for PR #133
  ([`916457a`](https://github.com/jpshackelford/ohtv/commit/916457a9f75fd70a58de80a75a19eb5a702b1462))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record expansion of issue #81 (velocity report)
  ([`6deafb5`](https://github.com/jpshackelford/ohtv/commit/6deafb5ba596a3c4e8e3b6c30b8d991f64a3d45c))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #131 merge
  ([`2882f25`](https://github.com/jpshackelford/ohtv/commit/2882f25b682a8e924989fbd3e6c844a9429d7f03))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #132 merge
  ([`d7243df`](https://github.com/jpshackelford/ohtv/commit/d7243df8d6326a294260ac4d38936e61f777f6ac))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #136 for issue #113
  ([`7d540a1`](https://github.com/jpshackelford/ohtv/commit/7d540a1cf6b8b2b428b0d9c06f08b7c0fdad1241))

- **worklog**: Record PR #84 merge (contribution tracking schema)
  ([`c55135f`](https://github.com/jpshackelford/ohtv/commit/c55135feb84f85fe4210f1532ed690bc527476a0))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #85 merge and Issue #83 unblock
  ([`6fd115e`](https://github.com/jpshackelford/ohtv/commit/6fd115e9fbcb09c6ec2f077adf382fcdbdd15252))

PR #85 (feat: add human_input counting stage) merged at 23:52:59Z as 38d5032. The
  initial_prompt_source preservation contract is now established and pinned by an integration test,
  unblocking Issue #83 (conversation classification command) for expansion in the next orchestrator
  cycle.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #85 opened for issue #77
  ([`afbad04`](https://github.com/jpshackelford/ohtv/commit/afbad04ae18ed517adb31894da547362e0997cec))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #85 review thread resolution
  ([`193a352`](https://github.com/jpshackelford/ohtv/commit/193a3525408354e16298e215fe2ef697bf9af444))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #96 merge / #89 close
  ([`908b606`](https://github.com/jpshackelford/ohtv/commit/908b606537e954e219104c2df8669e7e449e21da))

PR #96 squash-merged at 2026-05-26T18:22:34Z as bc1052e7. Issue #89 auto-closed via Closes #89.
  Final test count: 1529 passed.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #97 open / #80 in-flight
  ([`70d7d8b`](https://github.com/jpshackelford/ohtv/commit/70d7d8b92993167a82e0a578bd738fa69201de1a))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn docs worker for PR #138 (root_conversation_id foundation)
  ([`c52abc0`](https://github.com/jpshackelford/ohtv/commit/c52abc08fbf93325965fee6620b5fc171e52dedd))

- **worklog**: Spawn ERROR — github provider auth expired, surfacing to human
  ([`c89a8e2`](https://github.com/jpshackelford/ohtv/commit/c89a8e2474c1de6a35f83cf2980ecf64d9cafd4c))

- **worklog**: Spawn impl worker for #122 (sub-conversation root aggregation foundation)
  ([`b993a25`](https://github.com/jpshackelford/ohtv/commit/b993a25bb8e1a4952841397c1271e026292850e5))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn implementation worker for issue #81 (velocity report)
  ([`175ec56`](https://github.com/jpshackelford/ohtv/commit/175ec568a635015c67b8d89269a09a9eb9b5b380))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn merge worker for PR #97 (all gates clear, re-test pass)
  ([`05dee8f`](https://github.com/jpshackelford/ohtv/commit/05dee8f0f4782fbb22f4b7b078da129edc4e0f63))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn re-testing worker for PR #97 after refactor
  ([`ae48e79`](https://github.com/jpshackelford/ohtv/commit/ae48e7911bd1c8d770b6f06f3ebd7157a729de7b))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn review worker for PR #97 + archive PR #95 chain
  ([`9cedd8c`](https://github.com/jpshackelford/ohtv/commit/9cedd8c9b88b0b78c65fb2d8ec88e14a9c55a494))

- Spawned [Review] worker e6daad01 for PR #97 to address pr-review bot feedback (Evidence section in
  description + nesting refactor in src/ohtv/fetch_loc.py lines 450-502). - Archived PR #95
  orchestrator chain (14:19Z, 14:46Z, 15:21Z entries) to WORKLOG_ARCHIVE_2026-05-26.md per the prior
  cycle's deferred plan. - WORKLOG.md: 915 -> 809 lines.

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Spawn testing worker for PR #133
  ([`691269a`](https://github.com/jpshackelford/ohtv/commit/691269ad56660a4ffb986dae44f49a7dad20bc9c))

- **worklog**: Spawn testing worker for PR #134 (2026-05-29T01:22:59Z)
  ([`b009b16`](https://github.com/jpshackelford/ohtv/commit/b009b16b937b7129dbee06e335087430bfefab74))

- **worklog**: Spawn testing worker for PR #138
  ([`46367e0`](https://github.com/jpshackelford/ohtv/commit/46367e0cd91c187c8b0534af272796e97cd8acde))

Co-authored-by: openhands <openhands@all-hands.dev>

### Continuous Integration

- Bootstrap release automation (release-please + tests + PR-title lint)
  ([#120](https://github.com/jpshackelford/ohtv/pull/120),
  [`d3787ba`](https://github.com/jpshackelford/ohtv/commit/d3787badea8538e3d0f7ddfabdf507f7056bba3e))

Wires up automated semantic versioning for the project:

- .github/workflows/tests.yml: pytest on every PR and push to main -
  .github/workflows/release-please.yml: opens a persistent release PR; merging it tags vX.Y.Z and
  creates the GitHub Release - .github/workflows/pr-title.yml: enforces conventional-commit PR
  titles so squash-merge subjects are parseable by release-please - release-please-config.json +
  .release-please-manifest.json: pinned to 0.13.0; chore/docs/refactor/test/build/ci/style are
  hidden so worklog pushes never bump the version or pollute the changelog - CHANGELOG.md:
  hand-curated rollup of all 62 PRs merged since 0.1.0 (2026-04-13 → 2026-05-27), grouped by feature
  area - pyproject.toml + src/ohtv/__init__.py: bumped to 0.13.0 - AGENTS.md: documents the
  commit/release contract for future agents

PyPI publish is intentionally NOT configured.

Closes: bootstrap-release-automation

Co-authored-by: openhands <openhands@all-hands.dev>

### Documentation

- Add conversation metrics design and implementation plan
  ([`a2a9d2f`](https://github.com/jpshackelford/ohtv/commit/a2a9d2fbc4351b2b14311368cada5a8be05776a1))

- Add DESIGN_CONVERSATION_METRICS.md with full architecture - Add ISSUES_CONVERSATION_METRICS.md
  with detailed implementation issues - Update WORKLOG.md with planning session notes

Research goal: Track impact of agent orchestration on development velocity by measuring PRs merged,
  LOC, and human input (words/messages) per week.

Issues filed: #76-#83

Co-authored-by: openhands <openhands@all-hands.dev>

- Add date filtering options to list command documentation
  ([`5aaa14e`](https://github.com/jpshackelford/ohtv/commit/5aaa14eb2b5e6438721d2ef94e21a8a611c06481))

Add documentation for --since, --until, --day, and --week options as well as --verbose flag.

Co-authored-by: openhands <openhands@all-hands.dev>

- Add expansion notes for issue #60 (skip cache context level)
  ([`0d306ba`](https://github.com/jpshackelford/ohtv/commit/0d306ba2d71bc34de31f20e53b33bc8e6838e8b9))

Co-authored-by: openhands <openhands@all-hands.dev>

- Add PR #74 completion entry to WORKLOG
  ([`0adb24b`](https://github.com/jpshackelford/ohtv/commit/0adb24b51fb8f9c41e9e56d874dce048f5e16c7b))

Issue #58 - Action summaries not used in transcript building

Co-authored-by: openhands <openhands@all-hands.dev>

- Add worklog entry for #51 implementation
  ([`6fdd824`](https://github.com/jpshackelford/ohtv/commit/6fdd8242be0c53cb42367cde14545705c31747a8))

Co-authored-by: openhands <openhands@all-hands.dev>

- Add worklog entry for issue #58 expansion
  ([`fb86b29`](https://github.com/jpshackelford/ohtv/commit/fb86b293498c87a783f48e348f4cc53c538a28f6))

Expanded issue #58 - Action summaries not used in transcript building. Issue ready for
  implementation with technical details.

Co-authored-by: openhands <openhands@all-hands.dev>

- Add WORKLOG entry for PR #69 (issue #60)
  ([`948bb76`](https://github.com/jpshackelford/ohtv/commit/948bb76e6c4673b14bac598e47796b9c9de351e6))

Co-authored-by: openhands <openhands@all-hands.dev>

- Comprehensive usage documentation for README
  ([`3d898f7`](https://github.com/jpshackelford/ohtv/commit/3d898f755e0f183a499e94c18e2fa6fa1cf27648))

- Add Quick Start section for immediate onboarding - Document all commands: list, show, refs, sync -
  Include examples for common use cases - Add tables for all CLI flags and options - Document
  shorthand flags and their equivalents - Remove internal architecture details (keep user-facing
  info only) - Retain logging info useful to end users

Co-authored-by: openhands <openhands@all-hands.dev>

- Expand issue #35 - Add --explain flag to ask command for RAG retrieval debugging
  ([`8de7395`](https://github.com/jpshackelford/ohtv/commit/8de73952f90852b7dd0324f32ee21dac0606504d))

Co-authored-by: openhands <openhands@all-hands.dev>

- Log expansion of issue #46
  ([`ef1d165`](https://github.com/jpshackelford/ohtv/commit/ef1d16501e5d60cc28e628bce6cb2819e853c0b0))

Co-authored-by: openhands <openhands@all-hands.dev>

- Log expansion of issue #51 (ask --agent flag)
  ([`519af35`](https://github.com/jpshackelford/ohtv/commit/519af359cdc86eba5492fddaf51c43c8ba1aa700))

Co-authored-by: openhands <openhands@all-hands.dev>

- Log expansion of issue #52
  ([`bb90b5c`](https://github.com/jpshackelford/ohtv/commit/bb90b5cbd6d9b6e621b63579f7420c2df7efa099))

Co-authored-by: openhands <openhands@all-hands.dev>

- Restructure README and split docs into guides/reference/design
  ([#115](https://github.com/jpshackelford/ohtv/pull/115),
  [`fc420ca`](https://github.com/jpshackelford/ohtv/commit/fc420ca904d728e8a0327157badbc4578a64f173))

The README had grown to 1586 lines (93% of which was a per-command reference section). This
  restructure trims README.md to ~125 lines — pitch, quick start, command index linking into docs/,
  and minimal configuration — and moves the per-command reference into task-oriented guides under
  docs/guides/.

Structure --------- - README.md (1586 → ~125 lines): pitch, quick start, command index, config
  callouts, links into docs/. - docs/README.md: landing page / TOC for the docs tree. -
  docs/guides/: 12 task-oriented pages (installation, getting-started, concepts, syncing, indexing,
  exploration, classification, analysis, customizing-prompts, reporting, search-and-ask,
  automation). - docs/reference/: cli (hand-curated index), configuration, database (renamed from
  docs/DATABASE.md), glossary. - docs/design/: existing design notes, renamed to lowercase-kebab
  (DESIGN_FOO.md → foo.md, ISSUES_FOO.md → foo-issues.md). - docs/contributing/: testing.md (was
  docs/TESTING.md), manual-qa-pr18.md (was MANUAL_QA_PLAN_PR18.md).

Documentation gaps fixed in the same pass ----------------------------------------- - New
  docs/guides/reporting.md documents `ohtv report velocity`, `report weekly-counts`, the `--chart`
  flag, and (for the first time in user-facing docs) the "Reading the chart" convention — including
  the partial_loc hatch + "Partial LOC (NULL)" legend semantics shipped in #103/#106. - New
  "Contributions stage" section in docs/guides/indexing.md documents PR-creation, PR-merge, and
  direct-push detection — closing the audit gaps surfaced for #78/#88 (PR contributions) and #79/#94
  (direct-push detection), neither of which previously had dedicated documentation.

Cross-references ---------------- - AGENTS.md updated to point at the new doc paths. - All internal
  markdown links verified to resolve (Python link-check script in commit message footer). - No
  backward-compat stub redirects — old paths just break, consistent with the project owner's
  direction.

Tests ----- - Full unit suite: 1691 passed (unchanged from main, since this is a pure docs change).

Co-authored-by: openhands <openhands@all-hands.dev>

- Update WORKLOG with PR #66 for issue #59
  ([`e64abea`](https://github.com/jpshackelford/ohtv/commit/e64abeaa4550ebe93816db43342f92d7783faeaf))

Co-authored-by: openhands <openhands@all-hands.dev>

- Update WORKLOG.md with PR #56 merge status
  ([`f254add`](https://github.com/jpshackelford/ohtv/commit/f254add17adda6d48df3fe9b66a5975c8564506b))

Co-authored-by: openhands <openhands@all-hands.dev>

- Update WORKLOG.md with PR #65 merge completion
  ([`8a93bde`](https://github.com/jpshackelford/ohtv/commit/8a93bdee383060c554de2d42a7d6a55de5ed4df7))

Co-authored-by: openhands <openhands@all-hands.dev>

- Update WORKLOG.md with PR #66 merge completion
  ([`d46127c`](https://github.com/jpshackelford/ohtv/commit/d46127ca0eefd4c6983c5643e57d998163f08616))

Co-authored-by: openhands <openhands@all-hands.dev>

- Update WORKLOG.md with PR #69 review fix completion
  ([`986a615`](https://github.com/jpshackelford/ohtv/commit/986a615975a3a9344471b4c149f4c0ea7d7a364f))

Co-authored-by: openhands <openhands@all-hands.dev>

- Worklog update for PR #67 - numeric lookback
  ([`a25abfe`](https://github.com/jpshackelford/ohtv/commit/a25abfeeace849bceffa4ca40e81c8b81bfbd13e))

Co-authored-by: openhands <openhands@all-hands.dev>

- **sync**: Add sync-state ownership map and phased retirement plan
  ([#114](https://github.com/jpshackelford/ohtv/pull/114),
  [`95c99eb`](https://github.com/jpshackelford/ohtv/commit/95c99eb25abe4db2753bcf53aafeda144f2491f6))

Phase A deliverable for #114 (manifest-retirement project): a structured reference map of the
  current sync-state contract. Docs-only — no executable code changes.

What ships:

- docs/reference/sync-state-ownership.md (new, 401 lines): - §1.1 per-conversation field ownership
  table (per `source` value) - §1.2 manifest reader/writer call-site enumeration - §2 brittle-spot
  catalogue (where the dual-store contract leaks) - §3 four-phase retirement plan (A → B → C → D)
  keyed to open issues - §4 glossary, §5 risks, §6 carve-outs (`cloud_listing`, `selected_branch`) -
  AGENTS.md item #27 pointer to the new doc so future edits to `sync_manifest.json` or its overlay
  columns land on the structured contract.

Phase scope: Phase A only. Phases B/C/D remain open work on #114.

Review-round fixes (addresses testing audit on the original commit):

- T1: citation line numbers in §1.2 reader call-sites corrected. - T2: §1.2 reader-enumeration
  tightened (call-sites disambiguated from writer paths). - T5: PR #119 references flipped from
  "future" to "merged" (#110 scenario has shipped). - T7a: §6 `cloud_listing` carve-out clarified as
  scanner-owned snapshot, not a manifest sibling. - T7b: §5 Risks #1 cross-references AGENTS.md item
  #27 instead of duplicating the contract narrative.

Verification: manual docs-accuracy audit (T1–T9) all PASS/N/A after review-round; CI green (lint ✅,
  pytest ✅ 1920 passed, pr-review ✅ "Worth merging" 🟢 LOW risk). No source/test changes → no
  functional regression surface.

Refs #114

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: #110 cloud-sync behavioral harness complete (PR #119)
  ([`32dd2c8`](https://github.com/jpshackelford/ohtv/commit/32dd2c87db28c6b8e98fb5c3c41f73f3c9c1d49f))

Implementation worker handoff entry for #110. No code in this commit — the harness lives on branch
  feat/sync-test-harness-110 (PR #119).

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Add merge entry for PR #105 (Issue #102)
  ([`7495583`](https://github.com/jpshackelford/ohtv/commit/74955834c35c4493e3a6b403ce6298fc74bc02e9))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Impl worker entry for #102 (PR #105)
  ([`5cb8d8e`](https://github.com/jpshackelford/ohtv/commit/5cb8d8ecb33519e9cac956ced0f7b160b98e13f0))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Impl worker entry for #103 (PR #106)
  ([`09e8b3c`](https://github.com/jpshackelford/ohtv/commit/09e8b3cf050d5b07951d9e62a393af7cf5f733d4))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Mark issue #57 expansion complete
  ([`f201dfb`](https://github.com/jpshackelford/ohtv/commit/f201dfb6f29c67dcccfc6b892ebfc57b43fa0d48))

- Numeric argument to -D and -W commands for day/week lookback - Technical approach documented with
  implementation plan - Added ready label to issue

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Record PR #88 - PR contribution detection stage
  ([#78](https://github.com/jpshackelford/ohtv/pull/78),
  [`a635542`](https://github.com/jpshackelford/ohtv/commit/a6355426501a611e5c0f110118147166dd13a379))

Co-authored-by: openhands <openhands@all-hands.dev>

- **worklog**: Testing worker spawn for PR #105
  ([`86825cc`](https://github.com/jpshackelford/ohtv/commit/86825cced7893cef4a55023a809ff5bb09e05418))

Spawned testing worker 2a89daa to manually validate PR #105 (chore(charts): wrap ValueError as
  click.UsageError). Impl worker 87d0f99 from 07:21Z cycle finished cleanly; PR opened on
  chore/charts-unsupported-ext-usage-error-102 with positive bot review. Manual blackbox tests now
  gating merge per the workflow's docs-before-test policy (docs worker skipped — no documented
  behavior changes per #102 expansion).

Co-authored-by: openhands <openhands@all-hands.dev>

### Features

- Add --agent flag for multi-turn investigation mode
  ([#62](https://github.com/jpshackelford/ohtv/pull/62),
  [`be03c0c`](https://github.com/jpshackelford/ohtv/commit/be03c0c31cf20d2bf5e42d752198d17229f424df))

feat: add --agent flag for multi-turn investigation mode (#62)

Add investigation mode to `ohtv ask` command that enables multi-turn LLM interactions for deeper
  analysis of conversation history.

New features: - `--agent` flag enables investigation mode - `--max-steps N` controls maximum
  investigation iterations (default: 5) - Three investigation tools: show_conversation,
  search_conversations, get_refs - Progress display during investigation - Graceful fallback to
  initial RAG answer on errors

New modules: - analysis/agent_tools.py - Custom tools using OpenHands SDK ToolDefinition -
  analysis/investigator.py - InvestigationAgent with direct LLM calls -
  prompts/investigation/system.md - Agent system prompt

Design decision: Uses direct LLM calls instead of full Agent/LocalConversation infrastructure for
  better control over the read-only investigation loop.

Fixes #51

Co-authored-by: openhands <openhands@all-hands.dev>

- Add `ohtv report velocity` command ([#81](https://github.com/jpshackelford/ohtv/pull/81),
  [`fd9f84e`](https://github.com/jpshackelford/ohtv/commit/fd9f84e9bfbcbeb65184ac7baa9f075a7d16cdfc))

Adds `ohtv report velocity` — ISO-week-bucketed merged-PR/direct-push velocity report with table/CSV
  output, --since/--until/--repo/--include-empty flags, and a public `ohtv.reports.velocity` API for
  use by #82's charting script.

Highlights: - ISO-week bucketing via Python's `datetime.isocalendar()` (NOT SQLite %W); correctly
  handles boundary cases (e.g., 2024-12-30 → 2025-W01). - LOC columns render as `-` when unknown
  (NULL LOC / division-by-zero), never as `0` or `inf`. This includes `--include-empty` filler weeks
  — a deliberate deviation from the spec's "zeros across the board" wording (the PR count is still
  `0`; LOC stays `-` to avoid implying knowledge we don't have). See PR #98 test report's nits #1
  and #2. - Word counts use DISTINCT `(change_ref_id, conversation_id)` to prevent triple-counting
  when one conversation creates/pushes/merges the same PR. - `initial_prompt_source` policy: count
  `human` and `unknown`, drop `automation`. - Totals row uses `sum(words)/sum(total_loc)`, not the
  average of per-week ratios. - No new migration; reads existing `change_refs` + `conversations`
  tables.

Test coverage: 40 new unit tests (14 CLI smoke + 26 domain) + 13 manual blackbox tests (incl.
  ISO-boundary regression, DISTINCT triple-count prevention, CSV round-trip). Full suite at 1617
  passing.

Closes #81. Unblocks #82.

- Add conversation labels to gen objs display ([#73](https://github.com/jpshackelford/ohtv/pull/73),
  [`a2ee3cf`](https://github.com/jpshackelford/ohtv/commit/a2ee3cf3a51f442c856995ab19376849c484d9bf))

feat: Add conversation labels to gen objs display

Fixes #53

- Add labels JSON column to conversations table (migration 015) - Parse tags from Cloud API response
  during sync - Display labels in purple in gen objs table/JSON/markdown output - Add --label/-L
  filter option to list and gen objs commands - 23 new tests, all 1165 tests passing

Co-authored-by: openhands <openhands@all-hands.dev>

- Add database schema for contribution tracking
  ([#84](https://github.com/jpshackelford/ohtv/pull/84),
  [`4395eb2`](https://github.com/jpshackelford/ohtv/commit/4395eb26d093f9c182ef592ba1d223003c0562c1))

Adds migration 016 introducing three new SQLite tables to support contribution tracking (PRs, direct
  pushes, and human input metrics):

- `change_refs` — Tracks PRs and direct pushes to main. CHECK constraint restricts `change_type` to
  `'pr' | 'direct_push'` and `status` to `'pending' | 'fetched' | 'merged' | 'closed'`. A
  conditional CHECK enforces that PR rows have `pr_number` and direct-push rows have `commit_range`.
  Two partial unique indexes (`WHERE change_type = 'pr'` and `WHERE change_type = 'direct_push'`)
  work around SQLite treating NULLs as distinct in composite UNIQUE constraints, preventing
  duplicate PR/push entries. - `conversation_contributions` — Links conversations to changes they
  contributed to with CHECK on `contribution_type` (`'created' | 'pushed' | 'merged'`) and a UNIQUE
  constraint on `(conversation_id, change_ref_id, contribution_type)`. - `conversation_human_input`
  — Per-conversation human word/message counts with CHECK on `initial_prompt_source` (`'human' |
  'automation' | 'unknown'`).

All foreign keys use `ON DELETE CASCADE` for consistent cleanup (`repo_id → repositories`,
  `conversation_id → conversations`, `change_ref_id → change_refs`). Schema is pure structure — no
  code populates these tables yet; population follows in dependent issues #77–#83.

Includes 45 unit tests covering table creation, all CHECK constraints, FK CASCADE behavior, partial
  unique index semantics, defaults, indexes, idempotency, and integration with existing data.
  Manually verified that the migration applies cleanly to both fresh and populated databases, all
  constraints are enforced at the SQLite level, and no existing commands (`list`, `db status`,
  `sync`) are affected. Full test suite: 1242 passed.

Closes #76

- Add error analysis for agent/LLM errors (fixes #4)
  ([`8548b04`](https://github.com/jpshackelford/ohtv/commit/8548b0464fac8a8c367dc0a439c917d6fa47a0a1))

Add ability to detect and analyze agent/LLM errors in conversations:

- New errors command: 'ohtv errors <id>' shows detailed error summary for ConversationErrorEvent and
  AgentErrorEvent occurrences - New list filters: '--with-errors' adds error column, '--errors-only'
  shows only conversations with errors - Error classification: TERMINAL (conversation stopped) vs
  RECOVERED (agent continued)

This tracks errors that impact agent behavior, NOT routine terminal command failures (non-zero exit
  codes) which are normal in development.

Files added: - src/ohtv/errors.py - Error analysis module - tests/unit/test_errors.py - 25 unit
  tests

Co-authored-by: openhands <openhands@all-hands.dev>

- Add error counts to show command stats
  ([`0029a4b`](https://github.com/jpshackelford/ohtv/commit/0029a4b39bb9d57ca3c12600b1b2a82d8ebab121))

The show command now includes error counts in its statistics output: - Terminal errors
  (ConversationErrorEvent) - Recovered errors (AgentErrorEvent) - Error type breakdown

This completes the error tracking feature by showing error info in both 'ohtv show' (stats) and
  'ohtv errors' (detailed analysis).

Co-authored-by: openhands <openhands@all-hands.dev>

- Add fetch-loc command to backfill LOC from GitHub API
  ([#80](https://github.com/jpshackelford/ohtv/pull/80),
  [`31917be`](https://github.com/jpshackelford/ohtv/commit/31917bea8f73ef1dd59a4905332dcf7b31e295c7))

Adds `ohtv fetch-loc`: reads pending `change_refs` rows produced by the contributions stages and
  calls the GitHub REST API to populate `lines_added`, `lines_removed`, `files_changed`,
  `merged_at`, and `status` — the network-bound, cached, idempotent backfill that unblocks the
  velocity report and words-per-LOC ratios.

- New CLI command with flags `--repo`, `--force`, `--dry-run`, `--limit`, `-q/--quiet`, `-v`.
  `--repo` reuses the FQN matcher from `list`/`refs`; progress bar goes through
  `make_progress(...)`. Token is read from `GITHUB_TOKEN`; missing on a non-dry-run exits non-zero
  with a pointer to `gh auth token`. Token value is never logged. - `src/ohtv/github_api.py` — thin
  `httpx.Client` wrapper exposing `get_pr` and `get_compare`. Rate-limit handling honors
  `Retry-After`, falls back to `X-RateLimit-Reset`, then exponential backoff + jitter capped at 60s.
  404 → `None` so the orchestrator can mark "tried". - `src/ohtv/fetch_loc.py` — orchestrator.
  Selects candidates via SQL cache predicate, applies a 1h refetch heuristic for `status='open'`
  PRs, dispatches per `change_type` to PR or compare endpoint, commits per row so SIGINT doesn't
  lose work. Graceful 401/404/5xx: marks `fetched_at` and continues; exits non-zero only when every
  attempt failed. - Migration 017 — widens `change_refs.status` CHECK to include `'open'`. Required
  by AC #11 and by the idempotency cache predicate (`status IN ('merged','open','closed')`). Uses
  the canonical SQLite create-new / copy / drop / rename pattern so FKs in
  `conversation_contributions` and row IDs are preserved. - 48 new tests across
  `tests/unit/test_github_api.py`, `tests/unit/test_fetch_loc.py`, and
  `tests/unit/test_cli_fetch_loc.py`. HTTP mocked at the boundary via `pytest-httpx`; DB is real
  in-memory SQLite with full migration replay. Full suite: 1577/1577 pass. - README — full command
  reference with 5+ examples and `GITHUB_TOKEN` added to the env-var table.

Closes #80.

Co-authored-by: openhands <openhands@all-hands.dev>

- Add human_input counting stage ([#85](https://github.com/jpshackelford/ohtv/pull/85),
  [`38d5032`](https://github.com/jpshackelford/ohtv/commit/38d5032472ab9ef7e65836ff91480309ca29d89d))

Adds the `human_input` processing stage that counts human words and messages per conversation,
  distinguishing the initial prompt (first user MessageEvent) from follow-up messages (subsequent
  user MessageEvents). Results are written to `conversation_human_input` (schema from migration 016
  / #84).

Highlights:

- Pure `count_human_input(events)` + DB-writing `process_human_input` stage, registered as the 6th
  entry in the `STAGES` registry. - `ohtv db process` now sources its `click.Choice` allowlist from
  `STAGES.keys()`, eliminating the registry/CLI drift surfaced during manual testing. New invariant
  test in `tests/unit/test_cli_db_process_stages.py` pins that contract. - Tolerates malformed
  events (non-dict events, non-dict `llm_message`, non-list `content`, non-string `text`,
  unparseable JSON files). - Idempotent and uses `event_count` checkpointing via the standard
  `StageStore.mark_complete` flow.

Key downstream contract:

- The upsert deliberately omits `initial_prompt_source` from its `ON CONFLICT ... DO UPDATE SET`
  clause. The stage only fills the count columns and leaves classification of
  `initial_prompt_source` (default `'unknown'`) to a future classifier (issue #83). A new
  integration test, `test_preserves_initial_prompt_source_on_reprocessing` in
  `tests/unit/db/stages/test_human_input.py`, pins this invariant so future reprocessing cannot
  clobber downstream classifier writes.

Test coverage: 1272 unit tests passing; full manual blackbox sweep (two rounds) verifies CLI
  invocation, `db process all` ordering, `ohtv sync` auto-run integration, schema population,
  word-count accuracy, idempotency, `initial_prompt_source` preservation, and no-user-message
  conversations.

Closes #77.

- Add numeric lookback for -D and -W options ([#67](https://github.com/jpshackelford/ohtv/pull/67),
  [`32cd31c`](https://github.com/jpshackelford/ohtv/commit/32cd31c055934e771151c714ede6237ac616ecbc))

feat: add numeric lookback for -D and -W options

Allow users to specify how many days or weeks to look back with a single command: -D 3 for last 3
  days, -W 2 for last 2 weeks.

Implementation: - _parse_numeric_lookback(): detect positive integer values -
  _get_day_lookback_bounds(): calculate multi-day range (N days back) - _get_week_lookback_bounds():
  calculate multi-week range (N weeks back) - _parse_date_filters(): check numeric lookback before
  date parsing

Behavior: - -D N: today + (N-1) days back, matching "last N days" mental model - -W N: current week
  + (N-1) weeks back - -D 1 / -W 1 identical to -D / -W (single period) - Zero/negative values
  rejected with clear error - Leading zeros (e.g., -D 07) parsed as number 7

Works across: list, refs, gen objs, gen run commands

Tests: 25 new unit tests, 14 manual tests verified, all 1090 tests pass

Fixes #57

Co-authored-by: openhands <openhands@all-hands.dev>

- Add ohtv classify command ([#83](https://github.com/jpshackelford/ohtv/pull/83),
  [`ae38940`](https://github.com/jpshackelford/ohtv/commit/ae38940854b3e2edf5178cd37304bcbac24f64ec))

Adds `ohtv classify`, a CLI command that populates `conversation_human_input.initial_prompt_source`
  (`human` | `automation` | `unknown`) so that `ohtv report velocity` (#81) and downstream analytics
  can accurately distinguish human prompts from orchestrator/automation-driven ones. The command
  exposes three modes — a single-conversation override (`classify <id> --source ...`, idempotent, no
  `--confirm` needed), read-only discovery (`--list-unknown` with `-1`/`--format csv|json` and
  optional `--repo OWNER/REPO`), and `--confirm`-gated bulk heuristics (`--no-followups --source
  automation --confirm`, `--has-followups --source human --confirm`, also `--repo`-scopable). The
  `initial_prompt_source` column itself was added by migration 016 in PR #85; this PR ships the tool
  that populates it.

- Single-conv override accepts both 32-char IDs (with or without dashes) and unique short prefixes;
  bulk and `--list-unknown` accept `--repo` filtering. - Bulk UPDATEs always include
  `initial_prompt_source = 'unknown'` in the WHERE clause, so already-classified rows are never
  clobbered; only the single-conv path can flip a non-`unknown` row. - `_resolve_conversation_id`
  mirrors the short-prefix convention from `_find_conversation_dir` (AGENTS.md #14) — exact match
  first, then `LIKE 'prefix%'` — making the documented README pipeline `... --list-unknown -1 | head
  -5 | xargs -I {} ohtv classify {} --source human` actually work end-to-end. - Distinct error
  classes: `NoSuchConversationError` (points at `ohtv db scan`) vs `MissingHumanInputRowError`
  (points at `ohtv db process human_input`). Ambiguous short prefixes raise
  `AmbiguousConversationIdError` listing sample matches. - 34 new tests (25 covering the three
  behaviour modes + heuristic SQL + mutex flag handling; 9 added in the review round for prefix
  resolution and error-message distinction); full suite stays green at 1651 passed.

Closes #83.

- Add ohtv report weekly-counts command ([#92](https://github.com/jpshackelford/ohtv/pull/92),
  [`c3b0f64`](https://github.com/jpshackelford/ohtv/commit/c3b0f6456e73be147b703a88af79536b167b9570))

Adds a new CSV-only report — `ohtv report weekly-counts` — that emits new-conversation counts
  bucketed by ISO 8601 week, with `cloud`, `cli`, and `total` columns. Supports five flags
  (`--since`, `--until`, `--source [cloud|cli|all]`, `--include-empty`, `--exclude-current-week`)
  plus `--out PATH` to write to a file instead of stdout. New code lives in
  `src/ohtv/reports/weekly_counts.py` and a new `@report.command("weekly-counts")` in
  `src/ohtv/cli.py`.

Key implementation choices: ISO week bucketing is computed in Python via
  `ohtv.analysis.periods.make_week_period(get_week_start(...))` rather than in SQL, because SQLite's
  `strftime('%W', ...)` is GNU/POSIX and would mis-bucket boundary dates like 2024-12-30 (regression
  locked in by `test_iso_week_boundary_2024_12_30`, mirroring the rule documented in AGENTS.md for
  the velocity report). The user-facing `cli` label maps to the database's `source='local'` in
  exactly one place — the report module and the `--source` flag — so the CSV reads naturally while
  DB semantics stay intact. Bucketing uses `created_at` (new-conversations-per-week semantics), and
  naive CLI timestamps are treated as UTC, consistent with the rest of the codebase.

Test/QA gate: full suite is 1667/1667 passing (1651 baseline + 16 new — 13 unit tests in
  `tests/unit/reports/test_weekly_counts.py` covering T-1 through T-12 from the issue expansion plus
  an empty-rows header test, and 3 CliRunner smoke tests in
  `tests/unit/reports/test_cli_weekly_counts.py`). All 18 blackbox tests pass against the sandbox
  `~/.ohtv/index.db`. Ruff is clean on every new file; pre-existing lint debt in `src/ohtv/cli.py`
  is untouched.

_This commit was created by an AI agent (OpenHands) on behalf of @jpshackelford._

- Add PR contribution detection stage ([#88](https://github.com/jpshackelford/ohtv/pull/88),
  [`6212195`](https://github.com/jpshackelford/ohtv/commit/6212195eda79c7d4e0d76d8f31399a6d7de47f5f))

Adds a new `contributions` processing stage that walks per-conversation actions and derives PR
  contributions, persisting them to the `change_refs` / `conversation_contributions` tables
  (migration 016).

- New `db process contributions` stage in `src/ohtv/db/stages/contributions.py` with a forward pass
  that tracks the active PR per branch and a backward pass that attributes pre-PR ("orphan") pushes
  to the first subsequent PR on the same branch. Mirrors the structure of `push_pr_links`. - New
  `ContributionsStore` (`src/ohtv/db/stores/contributions_store.py`) with
  `get_or_create_pr_change_ref` / `get_or_create_direct_push_change_ref` and idempotent
  `record_contribution` (INSERT-OR-IGNORE), plus a reprocessing-safe
  `delete_contributions_for_conversation` helper. - Recognizes `OPEN_PR` → `created`, `MERGE_PR` →
  `merged`, and `GIT_PUSH` to a branch with an active PR → `pushed`. - Multi-platform support: host
  (github.com / gitlab.com / bitbucket.org) is captured during `_identify_pr`, carried on
  `_PrIdent`, and used by `_upsert_repo_for` so Repository `canonical_url` is correct for all three
  platforms. Host is also propagated through the MERGE_PR fallback chain (`seen_pr_repo` and
  `_single_repo_for_conversation`). - `orphan_push_branches` uses `set[str]` to dedupe at source
  when multiple pushes hit the same branch before a PR is opened, avoiding redundant backward-pass
  work. - 50+ new tests covering helpers, end-to-end stage runs against an in-memory DB with the
  full migration chain, and platform round-trips for GitHub / GitLab / Bitbucket. Full suite:
  1325/1325 passing.

Fixes #78

Co-authored-by: openhands <openhands@all-hands.dev>

- Add progress bar for embedding generation during sync
  ([#54](https://github.com/jpshackelford/ohtv/pull/54),
  [`3a3a37b`](https://github.com/jpshackelford/ohtv/commit/3a3a37b75c636d198deb53ea668a244dc98f1443))

feat: Add progress bar for embedding generation during sync

Add Rich progress bar to embedding generation that runs after `ohtv sync`. For batches >20
  conversations, displays spinner, progress bar, task counter, and smoothed processing rate. Uses
  parallel processing (ThreadPoolExecutor) with 20 workers for cloud APIs, 4 workers for Ollama.

Key features: - Graceful Ctrl+C handling: in-flight requests complete, partial results saved - Quiet
  mode (--quiet) suppresses progress, verbose mode (-v) shows details - Uses shared RateTracker from
  ohtv.parallel for rate display - EmbeddingWriter provides batched DB writes for efficiency

Review iteration addressed: - Fixed executor shutdown timing (wait=True, cancel_futures=True) -
  Refactored to use shared RateTracker class - Extracted _update_counters helper to reduce
  duplication

Test coverage: 24 unit tests + 9 manual test scenarios verified

Fixes #44

Co-authored-by: openhands <openhands@all-hands.dev>

- Add semantic search with embeddings ([#25](https://github.com/jpshackelford/ohtv/pull/25),
  [`349c79e`](https://github.com/jpshackelford/ohtv/commit/349c79e71154436d55729bff07e16d9215fe54cf))

feat: add semantic search with embeddings (#25)

Implement semantic search across conversations using embedding-based vector search. This enables
  finding conversations by concept/intent rather than exact keyword matches.

New Commands: - `ohtv db embed` - Build embeddings for all conversations - `--estimate` shows cost
  before embedding - `--force` rebuilds all embeddings - `ohtv search` - Search conversations
  semantically or by keyword - Semantic search by default (uses embeddings) - `--exact` flag for
  keyword search (FTS5) - `ohtv ask` - RAG-powered question answering over conversations

Implementation: - Vector storage: SQLite BLOBs + numpy for search - Embedding model: LiteLLM through
  same proxy as `gen` command - Multi-type embeddings: summary and content types - FTS5: Keyword
  search fallback with porter stemming - Auto-embedding: Analysis embeddings created with `gen objs`

Files Changed: - New: embeddings subpackage (client, text_builders, chunking, operations) - New:
  rag.py for RAG question answering - New: embedding_store.py and migration 008_embeddings.py -
  Updated: cli.py with search, ask, and db embed commands - Tests: 74 new tests (587 total passing)

Closes #1

Co-authored-by: openhands <openhands@all-hands.dev>

- Add temporal filtering to RAG ask command (#29)
  ([#31](https://github.com/jpshackelford/ohtv/pull/31),
  [`ad676b6`](https://github.com/jpshackelford/ohtv/commit/ad676b65059ca6271237b2a446e4a742c58c7078))

* feat: Add temporal filtering to RAG ask command (#29)

Implements automatic and explicit temporal filtering for the 'ohtv ask' RAG command:

- Add temporal query extraction module (src/ohtv/analysis/temporal.py) - TemporalQuery dataclass
  with start_date, end_date, cleaned_query - Fast regex extraction for common patterns (yesterday,
  last week, etc.) - LLM fallback for complex temporal expressions

- Add date filtering to embedding search - EmbeddingStore.search() accepts optional
  start_date/end_date - JOIN with conversations table when date filtering is needed -
  get_context_for_rag() passes dates through to search

- Update RAGAnswerer to use temporal extraction - Auto-extracts dates from question, uses cleaned
  query for embedding - Falls back to unfiltered search if temporal filter returns no results -
  RAGAnswer includes temporal_filter_applied and date_range fields

- Add CLI options for explicit date filtering - --since: Start date (YYYY-MM-DD or relative: 7d, 2w,
  1m) - --until: End date (YYYY-MM-DD) - --no-temporal: Disable automatic temporal extraction

- Add parse_date_filter() function in filters.py - Supports absolute dates, relative (Nd/Nw/Nm),
  keywords (today/yesterday)

* feat: Enhance temporal extraction with month names and vague time references

Add support for: - Month qualifiers: early/mid/late + month name (e.g., 'early March', 'mid-April',
  'late December') - Full month references: 'in March', 'in April', etc. - Vague time references: 'a
  few days ago', 'a few weeks back', 'a couple days ago' - 'N days back' as alternative to 'N days
  ago'

Implementation: - Add month name mapping with abbreviations (jan, feb, mar, etc.) - Add
  _infer_year_for_month() to handle future month references (assumes last year) - Early = days 1-10,
  mid = days 10-20, late = days 20-end - 'a few days' = 2-5 days, 'a few weeks' = 2-4 weeks - 'a
  couple days' = 1-3 days, 'a couple weeks' = 1-3 weeks

Co-authored-by: openhands <openhands@all-hands.dev>

- Database cleanup - orphaned embeddings and duplicate conversations
  ([#47](https://github.com/jpshackelford/ohtv/pull/47),
  [`34e8ce0`](https://github.com/jpshackelford/ohtv/commit/34e8ce0bd121fa6ddb6b3b63845fd5c7b1581be5))

fix: database cleanup for orphaned embeddings and duplicate conversations

Fixes two database consistency issues:

1. Orphaned analysis embeddings cleanup: - Added EmbeddingStore methods to detect/delete orphaned
  embeddings - Automatic maintenance task runs on database access - Updated `db status` to show
  orphaned count

2. Conversation ID normalization (migrations 011 + 012): - Normalize dashed IDs in analysis_cache
  table - Normalize dashed IDs in conversations and child tables - Fix _get_conversation_info() to
  normalize IDs from base_state.json

Affected tables: conversations, conversation_repos, conversation_refs, actions, conversation_stages,
  analysis_cache, analysis_skips, embeddings

Test coverage: 6 new unit tests, 919 total tests pass, manual testing verified.

Co-authored-by: openhands <openhands@all-hands.dev>

- Enhance RAG citations with conversation URLs, dates, and refs
  ([#34](https://github.com/jpshackelford/ohtv/pull/34),
  [`ceb56fb`](https://github.com/jpshackelford/ohtv/commit/ceb56fb52debcae4816164e2561ebf010949c107))

feat: enhance RAG citations with URLs, dates, refs, and contextual retrieval

Improve the `ohtv ask` experience with richer citations and smarter retrieval:

## Citation Enhancements - Add clickable cloud URLs to source conversations (14-day retention check)
  - Display conversation dates with relative formatting ("3 days ago") - Show summaries in citation
  output for quick context - Add "See Also" section aggregating related PRs/issues/repos - Use
  fully-qualified refs (owner/repo#123) to avoid ambiguity

## Contextual Retrieval (Anthropic technique) - Prepend metadata preambles to chunks before
  embedding - Include date, summary, and related refs in each chunk - Improves retrieval accuracy
  for date/ref-specific queries

## Automatic Pipeline - `ohtv sync` now generates summaries and embeddings automatically - New
  `--no-llm` and `--no-embed` flags to skip expensive operations - Summary extraction stored in
  conversations table for fast access

## Robust Parallel Processing - Single-writer pattern eliminates SQLite "database is locked" errors
  - GlobalRateLimiter coordinates exponential backoff across all threads - Prevents thundering herd
  when hitting API rate limits (429/5xx)

## Code Quality (review feedback) - Refactor _generate_answer() from ~90 lines into 7 focused
  methods - Add MIN_CONTENT_SPACE constant (no magic numbers) - Add 25 tests for prepend_to_text()
  and _split_content() - Change embedding error logging from debug to warning

## Database - Migration 009: Add `summary` column to conversations table

Closes #32

- Extensible prompt system with unified gen command
  ([#18](https://github.com/jpshackelford/ohtv/pull/18),
  [`2361041`](https://github.com/jpshackelford/ohtv/commit/236104173b917e6bee4ee57a46f84bd56cbc86a7))

Add a customizable prompt system for LLM-powered conversation analysis, replacing hardcoded prompts
  with YAML frontmatter-based prompt files.

## New Commands

- `ohtv gen objs <id>` - Unified analysis with --variant and --context options - `ohtv prompts` -
  List, show, init, and reset prompts

## Features

- **6 variants**: brief, standard, detailed (each with _assess option) - **3 context levels**:
  minimal (user only), standard (user+finish), full (all) - **User customization**: Override prompts
  via ~/.ohtv/prompts/objs/ - **Cache invalidation**: Auto-detects prompt changes via content
  hashing

## Architecture

- `src/ohtv/prompts/objs/` - Prompt family with YAML frontmatter + Markdown -
  `src/ohtv/prompts/discovery.py` - Prompt discovery and resolution -
  `src/ohtv/analysis/transcript.py` - Metadata-driven transcript building

## Breaking Changes

- Removed legacy `ohtv objectives` command (use `ohtv gen objs` instead) - Renamed prompt family
  from `objectives` to `objs`

Co-authored-by: openhands <openhands@all-hands.dev>

- Implement show command for viewing conversation content
  ([`99633e0`](https://github.com/jpshackelford/ohtv/commit/99633e00f60628007ca3fe391e16a2e86feed0af))

Add the show command with comprehensive filtering and formatting options:

Content selection flags: - -u/--user-messages: Include user's messages - -a/--agent-messages:
  Include agent's response messages - -f/--finish: Include finish action message -
  -s/--action-summaries: Include brief tool call summaries - -d/--action-details: Include full tool
  call details - -O/--outputs: Include tool call outputs/observations - -t/--thinking: Include
  thinking/reasoning blocks - -T/--timestamps: Include timestamps on events - -A/--all: Include
  everything - -m/--messages: Shorthand for -u -a -f - -S/--stats: Show only statistics, no content

Display options: - -r/--reverse: Show newest events first - -n/--max: Maximum number of events to
  show - -k/--offset: Skip first N events - -F/--format: Output format (markdown/json/text) -
  -o/--output: Write output to file

Supports prefix matching for conversation IDs and searches both local and cloud-synced conversation
  directories.

Co-authored-by: openhands <openhands@all-hands.dev>

- Multi-trajectory aggregate analysis jobs with period iteration
  ([#27](https://github.com/jpshackelford/ohtv/pull/27),
  [`f62ffad`](https://github.com/jpshackelford/ohtv/commit/f62ffadf5e4c3c48751b8b7bb75da0ddc78ff8d0))

* feat: add multi-trajectory aggregate analysis with period iteration

Implements issue #22: Support for analysis jobs that aggregate multiple trajectories into a single
  synthesized output, with automatic iteration over time periods (weeks, days, months).

## Changes

### Core Infrastructure - Add InputConfig dataclass to metadata.py with mode (single/aggregate),
  source, period, and min_items fields - Add parse_input_config() to parser.py for frontmatter
  parsing - Add is_aggregate and has_period properties to PromptMetadata

### Period Utilities (analysis/periods.py) - PeriodInfo dataclass with ISO labels and date ranges -
  iterate_periods() for generating periods in date ranges - get_last_n_periods() for 'last N'
  queries - compute_period_state_hash() for cache invalidation

### Aggregate Execution (analysis/aggregate.py) - run_aggregate_analysis() - collect items, render
  Jinja2, call LLM - ensure_source_cache_populated() - auto-run source job on uncached - State-hash
  based caching for period-based aggregates

### CLI - Add 'gen run' command for running any prompt job - --per week|day|month to override
  iteration granularity - --last N for last N periods - --out <dir> to write results to separate
  files - Auto-detects aggregate vs single-trajectory jobs

### Example Prompts - reports/weekly.md - weekly summary with themes - themes/discover.md - one-shot
  theme discovery

Fixes #22

Co-authored-by: openhands <openhands@all-hands.dev>

- Report conversation counts by directory in sync --repair
  ([#72](https://github.com/jpshackelford/ohtv/pull/72),
  [`2337ec1`](https://github.com/jpshackelford/ohtv/commit/2337ec1e94f90bf53b5a23bccd5936db84de9abe))

feat(sync): add per-directory conversation counts in repair report

When running `ohtv sync --repair` with multiple conversation directories configured, the report now
  shows a breakdown of conversation counts by directory.

Changes: - Extended RepairResult dataclass with disk_counts_by_dir field - disk_count is now a
  computed property summing per-directory counts - Added _count_conversations_in_dir() helper method
  - Added _format_path_for_display() for home directory abbreviation (~) - Breakdown rows shown only
  when multiple directories have conversations - Empty directories are omitted from the breakdown

Display rules: - Shows indented, dimmed breakdown rows under "Conversations on disk" - Paths display
  with ~ for home directory abbreviation - Single-directory scenarios show no redundant breakdown

Test coverage: - 13 new unit tests for RepairResult, SyncManagerRepair, and path formatting - 7
  manual test scenarios verified (multi-dir, empty dirs, path abbrev, etc.)

Closes #46

Co-authored-by: openhands <openhands@all-hands.dev>

- Sqlite indexing, config command, and CLI improvements
  ([#2](https://github.com/jpshackelford/ohtv/pull/2),
  [`66d3a5b`](https://github.com/jpshackelford/ohtv/commit/66d3a5b65d809f63d172b85b20a64132cbcf2958))

Add comprehensive SQLite indexing infrastructure for conversation labeling with repos, issues, PRs,
  and branches. Includes multi-stage processing pipeline (refs → actions → branch_context →
  push_pr_links) with temporal push-to-PR linking and git checkout branch inference.

Key features: - Database module with migrations, stores, and models - CLI commands: db
  init/scan/process/status/reset, config - Refs command with filtering and machine-readable output
  formats - Action recognition with 18 action types across 6 categories - Progress bars for
  long-running operations - Data directory separation (~/.openhands/ read-only, ~/.ohtv/ for state)

Also includes: - Filter support for list/summary/refs commands (--pr, --repo, --action) - Sync
  --process flag for one-command sync + indexing - Config command for viewing/setting configuration
  - Comprehensive test coverage (244 tests)

Co-authored-by: openhands <openhands@all-hands.dev>

- Standardize progress bars via shared make_progress helper
  ([#91](https://github.com/jpshackelford/ohtv/pull/91),
  [`c594d92`](https://github.com/jpshackelford/ohtv/commit/c594d923ed86778bd04c89aa47de8ea33db62417))

Introduces `src/ohtv/progress.py` exposing `make_progress(*, console, show_rate=True,
  show_remaining=True, show_eta=True, show_current=False, show_cost=False, transient=True)` — the
  single source of truth for Rich progress bars in ohtv. Default arguments reproduce the canonical
  `ohtv sync` layout (spinner → description → bar → % → "N left" → │ → ETA + remaining → rate)
  byte-for-byte. Tail columns (`show_current`, `show_cost`) are opt-in flags that attach without
  reshaping the line. The verb/description is read from `task.description` so callers can update it
  mid-run.

### Migrated 11 call sites onto the helper

- `cli.py` sync canonical — defaults - `cli.py` sync `--update-metadata` refresh — bar-only
  (`show_rate/remaining/eta=False`) - `cli.py` db scan — `show_current=True` - `cli.py` db process —
  `show_current=True` - `cli.py` db migrate-cache — `show_current=True` - `cli.py` db index-cache —
  `show_current=True` - `cli.py` db embed estimate — `show_current=True` - `cli.py` db embed (large
  batch) — `show_cost=True` (now surfaces running spend live) - `cli.py` post-sync embed (small
  batch) — `show_cost=True` (new live-cost display) - `cli.py` gen objs (single + batch) —
  `show_cost=True` - `cli.py` gen run periods — `show_current=True` - `db/maintenance.py`
  auto-runner — bar-only

### Supporting changes

- New `ohtv.parallel.format_remaining(total, processed, failed=0)` — sibling to `format_rate`,
  returns Rich-markup "N left" / "N ok N err" strings. - The last direct `rich.progress` import
  outside `progress.py` is removed; a new lint test (`tests/unit/test_progress_lint.py`) prevents
  drift.

### Test coverage

- 1411 / 1411 unit tests pass. - 27 / 27 dedicated progress-module tests (`test_progress.py`,
  `test_progress_lint.py`, `test_sync_progress_snapshot.py`). -
  `test_sync_progress_output_is_byte_identical_to_pre_migration` rebuilds the pre-migration 9-column
  canonical sync stack and asserts `make_progress()` defaults produce identical bytes for a fixed
  task state. - Manual blackbox tests exercised 9 / 11 migrated sites live; the remaining 2 are
  covered by unit tests.

### Review feedback addressed

- Per the pr-review bot's inline feedback, the misleading metadata-refresh callback comment in
  `cli.py` was rewritten to honestly describe that `manager.update_metadata` does not yield
  intermediate counts, so the "(N changed)" suffix only appears in the final `progress.update` call
  (commit 2c6d399, comment-only).

Closes #91

- Track cache_key for analysis embeddings ([#39](https://github.com/jpshackelford/ohtv/pull/39),
  [`947e526`](https://github.com/jpshackelford/ohtv/commit/947e5261cc2a63a78031c69333a51240cef94f6d))

feat: track cache_key for analysis embeddings

Add cache_key column to embeddings table to track which analysis variant each embedding corresponds
  to. Conversations may have multiple cached LLM analyses with different parameters (e.g.,
  assess=True,context_level=full vs assess=False,context_level=minimal), and we now embed each
  separately.

Changes: - Migration 010: Add cache_key column, update primary key to (conversation_id, embed_type,
  chunk_index, cache_key) - EmbeddingStore: cache_key support in upsert/get/has_embedding methods,
  validation (ValueError for non-analysis types), centralized
  list_conversations_needing_embeddings() for embedding need detection - AnalysisCacheStore:
  count_by_cache_key(), count_conversations_cached() - Operations: load_all_analyses() to embed ALL
  cached analysis variants - CLI: db embed detects missing cache_key variants, db status shows
  breakdown by cache_key with missing embedding warnings

Review decisions implemented: - cache_key validation rejects non-analysis embed_types - Defensive
  chunk_index=0 check in missing embeddings queries - Docstring documentation for cache_key format -
  DRY via centralized list_conversations_needing_embeddings()

Test coverage: 256 new lines (10 tests for cache_key isolation/detection) All 892 unit tests pass.
  Manual testing verified all features.

Co-authored-by: openhands <openhands@all-hands.dev>

- Use agent-provided summary in action extraction
  ([#74](https://github.com/jpshackelford/ohtv/pull/74),
  [`73afe1a`](https://github.com/jpshackelford/ohtv/commit/73afe1a483c2a62b78281fee4b53c482842fb643))

feat: Use agent-provided summary in action extraction

Prefer event.summary field over extracting truncated raw commands in transcript building. This
  improves LLM analysis quality by providing semantic intent instead of hard-to-parse commands.

Changes: - extract_action_summary() now uses event.summary when present - Added include_command
  parameter for full context mode (appends command) - Consolidated duplicate implementation from
  objectives.py to transcript.py - Updated extract_content() to pass include_command based on
  max_length

Test coverage: - 17 new tests for summary extraction behavior - 3 new tests for extract_content
  integration - 1197 total tests passing - Manual tests on 20 cloud conversations verified

Fixes #58

Co-authored-by: openhands <openhands@all-hands.dev>

- **charts**: Hatch partial_loc bars + document NULL LOC convention
  ([#103](https://github.com/jpshackelford/ohtv/pull/103),
  [`d7788da`](https://github.com/jpshackelford/ohtv/commit/d7788da4a30ecdad581f43c5f55fba3aacc54b5e))

- `hatch=` kwarg on Panel 2 (LOC) bars when `partial_loc=True` - `Patch("Partial LOC (NULL)")`
  legend entry explaining the hatch convention - AGENTS.md item #30 NULL-LOC bullet documents the
  convention - 1 new test (`test_partial_loc_bars_carry_hatch_marker`) + 1 extended regression guard
  (`test_bar_calls_receive_expected_pr_counts` now asserts `"hatch" not in first.kwargs` on Panel 1)
  - Unit suite: 1691 passed (1690 baseline + 1 new)

Closes #103

- **contributions**: Detect direct pushes to main/master
  ([#79](https://github.com/jpshackelford/ohtv/pull/79),
  [`03657ed`](https://github.com/jpshackelford/ohtv/commit/03657edb152a45ee0e476af73de37c93f6fc2d4c))

Extends the contributions stage to recognize `git push` actions that land changes directly on `main`
  or `master` without going through a PR, recording them as `change_refs` with
  `change_type="direct_push"` and `status="merged"`.

Key changes: - New `extract_push_info()` helper parses git's per-ref update line for fast-forward
  and force-push variants, returning commit range, branches, and a `force` flag. - `GIT_PUSH`
  recognizer surfaces `commit_range`, `base_commit`, `head_commit`, `remote_branch`, and `force` in
  action metadata. - `_handle_git_push` gains a direct-push branch that upserts a `direct_push`
  change_ref (with `status="merged"`) and a `pushed` contribution when the remote branch is
  `main`/`master`. Disjoint from the existing PR-link forward/backward pass. -
  `get_or_create_direct_push_change_ref` accepts an optional `status` arg (defaults to `"pending"`
  for backwards compat). - Case-sensitive lowercase match avoids spurious hits on branches like
  `mainline`. GitHub-only today; threading host support through the push-target recognizer is left
  as a follow-up.

Internal indexing-stage change — no CLI, flag, or env-var surface, so README intentionally
  untouched.

Test coverage: 26 new tests (10 unit tests on `extract_push_info`, 3 recognizer integration, 11
  contributions-stage integration, 2 store). Full suite: 1375 passing.

Manual testing on 50 real cloud conversations: 23 `direct_push` change_refs materialised on real
  pushes to main, dedup verified across replays, feature-branch pushes correctly ignored.

Closes #79

- **db**: Add set-diff sync schema (migration 018)
  ([#112](https://github.com/jpshackelford/ohtv/pull/112),
  [`f2ccbab`](https://github.com/jpshackelford/ohtv/commit/f2ccbab54b59c988c239e2405fc7d327cc6e8297))

Adds migration 018 (`src/ohtv/db/migrations/018_set_diff_sync_schema.py`) — schema-only groundwork
  for the set-diff sync engine (#111) and manifest retirement (#114). No code path outside the
  migration touches the new schema in this PR; that scope-guarantee is CI-enforced by two regression
  tests.

Schema additions:

* `cloud_listing` table — per-conversation snapshot of the most-recently completed cloud listing.
  Columns mirror the `/api/v1/app-conversations/search` `items[]` payload. PK is the normalized
  (dashless) `conversation_id` (AGENTS.md item #14). No FK to `conversations(id)` so cloud-only rows
  are representable. `snapshot_id` supports incremental page-by-page commits with atomic-replace
  semantics in #111. * `conversations.cloud_updated_at` column — records the cloud's `updated_at` at
  last download; distinct from the event-derived `conversations.updated_at` (migration 006).
  Backfilled in-migration from `~/.ohtv/sync_manifest.json` with graceful no-op on missing,
  malformed, non-object, or empty manifests. * `sync_kv` table — empty key/value placeholder for
  sync-state scalars currently in `sync_manifest.json`. Drained by #114; written by #111 for
  snapshot bookkeeping. * Three indexes: `idx_cloud_listing_updated_at`,
  `idx_cloud_listing_snapshot`, `idx_conversations_cloud_updated_at`.

Tests: 25 new (1746 → 1771 passing; 3 skipped, 10 xfailed unchanged; 0 regressions). 100% line
  coverage on the new migration.

Scope guarantee:

* `TestScopeGuarantee::test_sync_kv_only_in_migration` — the new K/V table name appears in exactly
  one file. * `TestScopeGuarantee::test_no_sql_consumer_of_new_schema` — every reference to the new
  identifiers outside the migration file is in a documented pre-existing allow-list.

Closes #112.

Co-authored-by: openhands <openhands@all-hands.dev>

- **embed**: Add Ollama support and parallel processing
  ([#28](https://github.com/jpshackelford/ohtv/pull/28),
  [`17cc991`](https://github.com/jpshackelford/ohtv/commit/17cc991fb108e586ead67b05ee697607763e0a97))

feat(embed): add Ollama support and parallel processing

Adds local embedding support via Ollama, parallel processing for faster batch operations, and
  improved error handling.

- Ollama embeddings: use `--model ollama/nomic-embed-text` for local - Parallel: 20 workers for API,
  2 workers for Ollama - Suppress LiteLLM debug spam during batch operations - Error handling:
  deduplicate and show top 3 with counts - Interrupts: Ctrl+C saves progress, re-run completes
  remaining - Fix chunk skipping bug for resume after interrupt

- **embeddings**: Support EMBEDDING_API_KEY / EMBEDDING_BASE_URL overrides
  ([#118](https://github.com/jpshackelford/ohtv/pull/118),
  [`1a968ce`](https://github.com/jpshackelford/ohtv/commit/1a968ced09bc4a838cc67763689a81d657d2c8a9))

Allow embeddings to target a different LiteLLM proxy / OpenAI-compatible endpoint than chat models.
  This is needed when (for example) the main proxy used for chat does not expose embedding models,
  but a separate evaluation proxy does.

Behavior: - get_effective_embedding_api_key() and get_effective_embedding_base_url() prefer
  EMBEDDING_API_KEY / EMBEDDING_BASE_URL when set, otherwise fall back to LLM_API_KEY /
  LLM_BASE_URL. Existing single-proxy setups continue to work unchanged. - get_embedding(),
  test_litellm_embedding(), get_current_config(), and is_embedding_configured() all use the new
  helpers. - Error message when no key is configured now mentions both env vars.

Docs and the module docstring are updated. Adds unit tests covering the override, fallback, and "no
  key" paths (including a small fake-litellm test that asserts the wire credentials match the
  EMBEDDING_* values).

Co-authored-by: openhands <openhands@all-hands.dev>

- **gen-titles**: Add `ohtv gen titles` to auto-rename placeholder-titled cloud conversations
  ([#89](https://github.com/jpshackelford/ohtv/pull/89),
  [`bc1052e`](https://github.com/jpshackelford/ohtv/commit/bc1052e73b4f1cd370b1e5967b22dfd4aac27967))

Adds a new cloud-source-only `ohtv gen titles` command that:

- Selects placeholder-titled cloud conversations by default (`^Conversation [0-9a-f]{5,32}$`), with
  `--all-titled` to widen the selector. - Reuses the `gen objs` filter surface
  (--day/--week/--since/--until/--pr/--repo/--label/-n/--all/--offset/--reverse) plus title-specific
  flags (--all-titled, --dry-run, --workers, --batch-size, --model, -y, --verbose). - Probes the
  analysis cache (detailed_assess > detailed > standard_assess > standard > brief_assess > brief)
  and skips cache-miss conversations before any LLM call. - Batches LLM calls (default 25/chunk)
  with single-conv retry on parse failure and a length re-prompt + hard-truncate fallback. - PATCHes
  cloud titles in parallel via the new `CloudClient.update_conversation(id, *, title=...)`, routed
  through `_request_with_retry` so `Retry-After` headers are honoured (default 5 workers,
  hard-capped at 50). - Writes back locally via manifest (normalized conv IDs) +
  `ConversationStore.update_metadata(id, title=...)` from #86 / PR #94; no `last_sync_at` advance,
  no `sync_count` increment. - Surfaces `Manifest updated: N/M` in live mode and `Manifest entries
  found: N/M` in dry-run, yellow when partial. - Ships a customizable prompt at
  `src/ohtv/prompts/titles/default.md` (user override at `~/.ohtv/prompts/titles/default.md`); `ohtv
  prompts show titles/default` works (family/variant resolver added in review round 1).

Review round 1 fixes (both manual-test blockers from round 0): - `6969e95` fix(prompts): teach
  'prompts show' to accept family/variant paths - `5b1f33a2` fix(gen-titles): normalize dashed conv
  ids in manifest writeback (+ partial-manifest yellow path + Manifest updated/entries found: N/M
  summary)

Tests: 1529 passed (+8 over the 1521-test baseline). New tests cover the manifest ID-normalization
  path, partial-manifest yellow summary, and the `prompts show` family/variant resolver.

Closes #89

- **list**: Add --idle flag and show refs by default
  ([#40](https://github.com/jpshackelford/ohtv/pull/40),
  [`a9c41d9`](https://github.com/jpshackelford/ohtv/commit/a9c41d9fbfcb874281aab1a035c6925c26859769))

* feat(list): add --idle flag and show refs by default

Changes to `ohtv list`:

1. **Refs shown by default**: Git refs (repos, PRs, issues) are now shown by default in the title
  cell. Use `--no-refs` to hide them.

2. **New `--idle` flag**: Shows time since last activity instead of duration. - `--idle` uses
  default threshold of 7 minutes - `--idle 15` uses custom threshold - Colorized: red if < threshold
  (active), green if >= threshold (quiet)

Example: ``` ohtv list --repo conversation-search --since 4h --idle

ID Source Started Idle Events Title abc123 cloud 2025-05-02 10:30 3m 42 [Impl] Phase 1 Refs:
  conversation-search#1 def456 cloud 2025-05-02 09:15 47m 28 [Review] PR #1 Refs:
  conversation-search#1 ```

This supports orchestration workflows that need to detect active vs quiet conversations before
  spawning new workers.

Co-authored-by: openhands <openhands@all-hands.dev>

- **list**: Add date filtering options (--since, --until, --day, --week)
  ([`8612b12`](https://github.com/jpshackelford/ohtv/commit/8612b124bbe01df7b49c92afe813f89edbb1d7b6))

Add options to filter conversations by date: - --since/-S DATE: Show conversations from DATE onwards
  - --until/-U DATE: Show conversations up to DATE - --day/-D [DATE]: Show conversations from a
  single day (defaults to today) - --week/-W [DATE]: Show conversations from the week containing
  DATE (defaults to today)

Weeks start on Sunday. The 'today' keyword is supported for date values.

Co-authored-by: openhands <openhands@all-hands.dev>

- **locks**: Add sync.lock writer mutex with --lock-timeout flag
  ([#109](https://github.com/jpshackelford/ohtv/pull/109),
  [`4799ad0`](https://github.com/jpshackelford/ohtv/commit/4799ad03e17b4f75130b11f0a9b3dcf8c050b7a6))

Fixes #109.

Adds a process-level writer mutex that serializes the three commands that mutate the local sync
  state, closing the silent-clobber window between `sync` (manifest + `update_metadata`) and `db
  scan` (`extract_metadata` upsert from a stale `manifest_map` snapshot).

## Gated commands

| Command | Lock label | |---------|-----------| | `ohtv sync` (full, `--repair`,
  `--update-metadata`, `--force -n`) | `sync` | | `ohtv db scan` | `scan` | | `ohtv gen titles` |
  `gen-titles` |

Each gains a `--lock-timeout SECONDS` flag. Default is `0` = **fail-fast**: a contested lock raises
  `SyncLockTimeout` and exits 1 with a message pointing at the lock file. `--lock-timeout=N` polls
  every ~100 ms up to N seconds.

`ohtv sync --status` is read-only and deliberately short-circuits **before** the lock is acquired
  (covered by a CLI test that spies on the patched `sync_lock`).

All other read-only commands — `list`, `show`, `refs`, `errors`, `search`, `ask`, `report *`, `db
  status`, `db process *`, `db embed`, `gen objs` — do NOT take the lock. A parametrized regression
  test scans `--help` for each and asserts `--lock-timeout` is absent (negative contract).

## Lock implementation

`src/ohtv/locks.py` exposes a `sync_lock(label, timeout=0)` context manager backed by
  `fcntl.flock(LOCK_EX | LOCK_NB)`. The lock file lives at `$OHTV_DIR/sync.lock` and the holder
  writes a `<pid> <label>` stamp into it on acquire (useful for `ps`/forensics; the file is
  intentionally left on disk after release). `$OHTV_DIR` is created on demand for fresh installs.

Windows = no-op + logged warning (`fcntl` is POSIX-only); tracked for follow-up via
  `msvcrt.locking`.

## Docs

New section **"Column Ownership and the `sync.lock` Writer Mutex"** in `docs/reference/database.md`
  documents:

- the full per-column ownership partition for `conversations` (every column on the post-#112/#108
  schema mapped to its canonical writer per `source` value, including the `COALESCE` semantics added
  for `parent_conversation_id` in #108), - the mutex contract, - why `fcntl.flock` over `BEGIN
  IMMEDIATE` (manifest is on the filesystem, not under SQLite; in-memory `manifest_map` staleness
  predates any DB transaction; lock outlives any single DB connection).

`selected_branch` is codified as **scanner-only**: sync is forbidden from writing it, and it must
  not become a parameter of `ConversationStore.update_metadata`.

Updated guides: `docs/guides/syncing.md`, `docs/guides/indexing.md`, `docs/guides/analysis.md`,
  `docs/reference/cli.md`. AGENTS.md item #27 extended with a `#109` sub-bullet. README
  intentionally unchanged (no new top-level command surface).

## Tests

- `tests/unit/test_locks.py` — 8 tests: acquire/release/file-stays, owner stamp, fresh-install
  directory creation, same-process non-nesting (Linux `flock(2)` per-fd semantics), real
  cross-process fail-fast subprocess, `timeout>0` wait-then-succeed, `timeout=0.3` deadline-honoring
  raise, Windows no-op branch. - `tests/unit/test_cli_sync_lock.py` — 16 tests: `--lock-timeout`
  advertised on the three writers (parametrized), absent on 9 read-only commands (parametrized
  negative contract), `SyncLockTimeout` surfaced as exit 1 with the lock-file message on `sync` and
  `db scan`, `sync --status` skips the lock, `db scan` smoke test.

Full suite: **1897 passed, 3 skipped, 4 xfailed**. No regressions. Lint debt is pre-existing
  baseline.

Co-authored-by: openhands <openhands@all-hands.dev>

- **prompts**: Add display schema for variant-aware table rendering
  ([#24](https://github.com/jpshackelford/ohtv/pull/24),
  [`d08c871`](https://github.com/jpshackelford/ohtv/commit/d08c871e0308a91c6fd1f874f29594728b84f33d))

feat(prompts): add display schema for variant-aware table rendering

Add a `display` section to prompt frontmatter that controls how results are rendered in batch mode
  tables. This enables prompts like `standard_assess` to show additional columns (Status with emoji
  badges) and combined fields (Primary/Secondary outcomes in the Summary column).

Key changes: - Add FieldRef, ColumnDef, DisplaySchema dataclasses in metadata.py - Add display
  schema parser in parser.py - Add pluggable formatters (date, status_badge, bullet_list, truncate)
  - Add TableRenderer class for schema-based rendering - Update _print_summary_table to use display
  schema when available - Add display schemas to brief.md and standard_assess.md prompts

The standard_assess variant now renders a 4-column table: - ID, Date, Status (✅❌🔄), Summary (goal +
  outcomes)

Prompts without display schemas fall back to the default 3-column format for backward compatibility.

Closes #23

- **refs**: Add --actions flag to show only write actions
  ([`88b20aa`](https://github.com/jpshackelford/ohtv/commit/88b20aad6d3d119fb1a2dcb6d166e541d9904b6d))

Add -a/--actions flag to filter refs output to only show refs where write actions (created, pushed,
  commented, etc.) were detected.

Output is sorted by action priority: 1. created (green) 2. merged (green) 3. pushed (yellow) 4.
  commented (yellow) 5. reviewed (yellow) 6. closed (dim) 7. cloned (dim)

Example: $ ohtv refs abc123 --actions created OpenHands/software-agent-sdk/issues/2184 pushed
  OpenHands/software-agent-sdk cloned OpenHands/software-agent-sdk

Co-authored-by: openhands <openhands@all-hands.dev>

- **refs**: Add interaction type detection for refs command
  ([`040c9cb`](https://github.com/jpshackelford/ohtv/commit/040c9cb0710cdecc4e6b231385c5cbc90d65b569))

Enhance the refs command to show what actions were taken on each reference: - Repositories: cloned,
  pushed - Pull Requests: created, pushed, commented, merged, closed, reviewed - Issues: created,
  commented, closed

Implementation: - Add INTERACTION_COMMAND_PATTERNS for git push, clone, gh pr/issue commands - Add
  ExtractedRef and RefInteractions dataclasses for tracking - Add
  _detect_interactions_from_conversation() to scan events for patterns - Add
  _extract_ref_from_command() to extract refs from commands/output - Update _display_refs() to show
  interaction annotations

Only marks successful interactions (exit_code == 0). Refs without detected interactions show without
  annotation (implicit 'viewed').

Example output: • https://github.com/owner/repo [pushed] • https://github.com/owner/repo/pull/123
  [created, commented]

Implements SPEC_REFS_INTERACTION_TYPES.md specification.

Co-authored-by: openhands <openhands@all-hands.dev>

- **reports**: Add --chart flag to velocity for publication-quality charts
  ([#82](https://github.com/jpshackelford/ohtv/pull/82),
  [`77ce880`](https://github.com/jpshackelford/ohtv/commit/77ce8804dab8be223b27bcbe3e9d75bfe7785a01))

Adds a 3-panel matplotlib chart renderer for `ohtv report velocity`, built on top of the existing
  #81 data path. Publication-quality static charts (.png / .svg / .pdf) can now leave the terminal
  and end up in papers, decks, and issues.

What landed:

- **3-panel layout, shared ISO-week x-axis** — Panel 1: PR counts (created bars + merged overlay).
  Panel 2: LOC ± (added upward green, removed downward red). Panel 3: Words-per-LOC (line +
  markers). - **`--mark-date YYYY-MM-DD`** overlays a vertical reference line on all three panels
  (e.g., "orchestration started"). - **`--title <str>`** sets the figure `suptitle`; default
  `"Development Velocity"`. - **Extension-driven format** — `.png` / `.svg` / `.pdf` is inferred
  from the output path; no `--format` flag. - **Lazy matplotlib import** — `import
  ohtv.reports.charts` does NOT pull in matplotlib at module load. Missing matplotlib → friendly
  `click.UsageError` pointing at `pip install ohtv[charts]`. - **`scripts/chart_velocity.py`
  standalone shim** — consumes CSV from `ohtv report velocity --format csv` on stdin OR as a
  positional file argument; produces an identical figure to the CLI subcommand. - **All #81 filters
  still work** — `--since` / `--until` / `--repo` / `--include-empty` apply identically with or
  without `--chart`. - **No changes to the velocity data path** — `fetch_raw_rows` /
  `bucket_by_iso_week` / `aggregate_velocity` are untouched. Only addition to `velocity.py` is
  `VelocityRow.from_csv_dict` (pure additive helper for the CSV shim). - **Empty result set** → no
  crash; same hint as #81's empty-table path; exit 0; NO file written. - **Docs bundled in-diff** —
  README.md (new chart section, copy-pasteable example) + AGENTS.md (new architecture item #30:
  chart layout, gap handling, lazy-import rationale).

Verification (commit 0a85d36):

- ✅ `PR Review by OpenHands/pr-review` check: SUCCESS (04:11Z). - ✅ AI code-review bot: 🟢 Good taste
  — _"Elegant, pragmatic solution that solves a real problem with minimal complexity."_ - ✅ Manual
  test report (04:28Z, comment 4551281621): all 9 ACs (AC-1 through AC-9) satisfied; 1688/1688
  pytest pass; 21/21 focused chart tests pass (11 unit + 6 CLI smoke + 4 standalone-script); ruff
  clean on new files. - 🟡 Two minor non-blocking UX nits filed as follow-up issues
  (ValueError-vs-UsageError on bad extension; NULL-vs-zero LOC bar visual).

Closes #82

This squash-merge was performed by an AI agent (OpenHands) on behalf of @jpshackelford.

Co-authored-by: openhands <openhands@all-hands.dev>

- **show**: Add --refs flag to display write actions summary
  ([`5562c81`](https://github.com/jpshackelford/ohtv/commit/5562c8165be2b9f794ee02c4e5295c4841d98186))

Add -R/--refs flag to show command that displays git refs with detected write actions (created,
  pushed, commented, etc.) after the stats table.

Also included with --all/-A flag.

Example: $ ohtv show abc123 --refs # Conversation: abc123 **Title:** Fix bug in parser ...stats
  table...

created OpenHands/repo/issues/42 pushed OpenHands/repo commented OpenHands/repo/pull/123

Co-authored-by: openhands <openhands@all-hands.dev>

- **show**: Add human-readable action details and flexible output options
  ([`f0d46e2`](https://github.com/jpshackelford/ohtv/commit/f0d46e2f244dfc7177e4eec46c1734e9213c1f5a))

- Replace -O/--outputs with -o/--trunc-output and -O/--full-output - -o shows truncated output (2000
  chars) with exit codes - -O shows full output without truncation - Make -d/--action-details show
  human-readable format: - terminal: shows '$ <command>' instead of JSON - file_editor: shows 'view
  /path' or 'edit /path (str_replace)' - Other tools: key=value pairs - Add --debug-tool-call for
  raw tool_call JSON and observation metadata - Shows working directory for observations in debug
  mode - Exit codes now always shown on observations when using -o or -O - Rename --output to --file
  to avoid confusion with new -o flag - Update -A/--all to include full_output and debug_tool_call -
  Update README.md and AGENTS.md with new documentation

Co-authored-by: openhands <openhands@all-hands.dev>

- **sync**: Add --repair option to check and fix sync state consistency
  ([#42](https://github.com/jpshackelford/ohtv/pull/42),
  [`d235f32`](https://github.com/jpshackelford/ohtv/commit/d235f32353579f6980a88051d34b16d0ebf9684a))

feat(sync): add --repair option to check and fix sync state consistency

Adds `ohtv sync --repair` command to diagnose and fix sync state inconsistencies that can occur
  after failed syncs or when the manifest gets out of sync with actual files on disk.

Features: - Compares manifest entries vs actual files on disk - Queries cloud API for total
  conversation count - Reports ghost entries (manifest but not disk) and orphaned files -
  `--dry-run` mode for safe checking without modification - Graceful degradation when API key
  unavailable

Implementation: - RepairResult dataclass with is_consistent and cloud_disk_match properties -
  SyncManager.repair() method with UUID format normalization - Rich CLI display with clear
  discrepancy categorization - 16 new unit tests (47 total sync tests) - 8 manual end-to-end
  scenarios verified

Co-authored-by: openhands <openhands@all-hands.dev>

- **sync**: Add --update-metadata to refresh cached title + labels
  ([#93](https://github.com/jpshackelford/ohtv/pull/93),
  [`89a1352`](https://github.com/jpshackelford/ohtv/commit/89a135268e8fa3fc88621f647482174b3f1c248f))

Adds `ohtv sync --update-metadata` to refresh cached metadata (title, labels) for already-synced
  cloud conversations without re-downloading trajectories. Also auto-fires at the end of a normal
  sync when new conversations were downloaded.

Behavior: - Mutex-exclusive with --force, --repair, --status, --dry-run - Writes manifest first,
  then DB; per-row errors recorded but don't abort the loop - DB connection lifecycle protected by
  try/finally - No trajectory download, no sync-bookkeeping mutation

Closes #86.

- **sync**: Add parallel downloads with progress bar and graceful shutdown
  ([#33](https://github.com/jpshackelford/ohtv/pull/33),
  [`35ad387`](https://github.com/jpshackelford/ohtv/commit/35ad387e9ae821dae745576e4fb3df1c7b1a2189))

feat(sync): add parallel downloads with progress bar and graceful shutdown

Add parallel download support to the sync command with Rich progress bar, matching the performance
  improvements already in `gen` and `embed` commands.

Changes: - Add new `ohtv.parallel` module with shared utilities: - `format_rate()` for processing
  rate display - `RateTracker` for thread-safe rate tracking with smoothing - `run_parallel()` for
  generic parallel execution - `graceful_shutdown_handler()` for SIGINT/SIGTERM handling

- Parallel sync implementation: - Use ThreadPoolExecutor with 3 workers (conservative for rate
  limits) - Add `_categorize_conversations()` for upfront action planning - Add
  `_download_parallel()` and `_download_sequential()` helpers - Thread-safe result counter updates

- CLI progress improvements: - Rich progress bar with processing rate and ETA - Graceful shutdown
  (Ctrl+C finishes current downloads) - Elapsed time display in completion message

- Rate limiting improvements in cloud.py: - Global rate limiter shared across all workers - Circuit
  breaker: max_retries=50 prevents infinite hang - Exponential backoff with jitter (2s → 60s cap)

- Tests: 17 new tests for parallel module, 3 for sync parallel functionality

- **sync**: Include sub-conversations in cloud listing
  ([#108](https://github.com/jpshackelford/ohtv/pull/108),
  [`211d9ba`](https://github.com/jpshackelford/ohtv/commit/211d9ba4388b62d937b15059f234c39d15ca977d))

The cloud listing endpoint defaults include_sub_conversations=false, so pre-#108 builds silently
  dropped every delegated sub-conversation from ohtv sync. This makes ohtv sync the complete mirror
  of what the cloud UI and /count report.

Key changes: - CloudClient: default-on include_sub_conversations=True on search_conversations,
  search_all_conversations, and count_conversations. Forwarded as the lowercase literal "true" on
  the wire and omitted entirely when False (locked by a regression test against case-sensitive cloud
  parsers). - Migration 019: additive parent_conversation_id TEXT NULL column on conversations +
  partial index idx_conversations_parent ... WHERE parent_conversation_id IS NOT NULL. No backfill
  needed; next sync repopulates from the listing. - Sync + scanner writeback:
  Syncer._listing_row_to_conv_dict carries parent_conversation_id end-to-end; scanner reads it from
  the cloud_listing snapshot via load_cloud_listing_parents(); ConversationStore upsert uses
  COALESCE so scanner re-upserts don't clobber sync-written values. Ids normalized (dashless) per
  AGENTS.md #14. - Backward-compat guard: listing payloads missing the field are treated as "unknown
  / root" rather than crashing. - Manifest stays parent-agnostic (DB-only structural metadata,
  matching the ownership shape of cloud_updated_at and labels). - Behavioural scenarios 17 + 18
  added to the #110 harness (sub-conv lands locally with kwarg forwarded on every page; legacy
  payloads without the field still parse). - Docs updated: README, AGENTS.md item #31,
  docs/guides/syncing.md, docs/reference/database.md.

Test count: 1805 → 1824 passing (+19). Manual testing: 17/17 PASS including fresh-DB sync, migration
  019 idempotency, partial-index usage, backward compat, lowercase wire shape, and default-on
  behavior.

Fixes #108

- **sync**: Manifest as full cloud metadata cache
  ([#87](https://github.com/jpshackelford/ohtv/pull/87),
  [`d3d3f9c`](https://github.com/jpshackelford/ohtv/commit/d3d3f9ccd028b5c1d32830b319f40c4d044fac60))

- Extends sync_manifest entries with `selected_repository`, `selected_branch`, and `created_at`
  (additive schema; pre-#87 manifests still load). - Cold-start scanner skips `base_state.json`
  entirely for cloud convs whose manifest entry is fully populated; local CLI convs unchanged.
  Regression test asserts zero `Path.read_text` calls on the file. - `sync --update-metadata`
  refreshes the new fields except `selected_branch` — the cloud listing API does not return it; it
  can only change via a full trajectory re-download. - `sync --repair --fix` rebuilds orphaned
  manifest entries from one shared cloud-listing fetch with null-filled fallback when there is no
  API key or the listing call fails. - Widens `ConversationStore.update_metadata` to accept
  `selected_repository` and `created_at` with `_UNSET` sentinel semantics distinguishing "leave
  unchanged" from "clear". `created_at` requires `datetime` (or `None`); raw strings raise
  `TypeError`. - Introduces `MetadataDiff` dataclass replacing the legacy `(title_changed,
  labels_changed)` tuple; carries per-field booleans and new values to avoid re-normalization in the
  update path. - +50 new tests across scanner / store / sync (1688 → 1738 green); 8/8 AC verified
  including the headline cold-start zero-read property.

Closes #87

- **sync**: Recover from cloud/local gap via set-diff engine
  ([#111](https://github.com/jpshackelford/ohtv/pull/111),
  [`92a2805`](https://github.com/jpshackelford/ohtv/commit/92a2805b9ffe04282e5e08dd7a19aa42793a5d31))

Replace the pre-#111 cursor-based sync (`updated_since=last_sync_at`) with a set-diff engine that
  always lists the full cloud catalog and reconciles it against the local manifest. The 1126-item
  cloud/local gap that motivated the issue becomes structurally impossible: missing-locally rows
  download as new, stale-locally rows download as updated (via `!=`, so server-side rewinds also
  heal), and removed-from-cloud rows are dropped from the manifest with a per-id `WARN
  sync.removed_from_cloud` log line.

Implementation - New `cloud_listing` snapshot table with full lifecycle: `start_snapshot` /
  `upsert_row` / `commit_snapshot` / `abandon_snapshot`. Pages commit incrementally so an
  interrupted sync resumes mid-listing; the swap to the new snapshot is atomic. - New stores:
  `cloud_listing_store.py` (snapshot + set-diff helpers `missing_locally` / `stale_locally` /
  `removed_from_cloud`) and `sync_state_store.py` (k/v wrapper over `sync_kv` for snapshot
  bookkeeping and `last_sync_at` mirror so #114 can drain the manifest without a flag-day). -
  `ConversationStore.record_cloud_download`: minimal upsert that never overwrites scanner-owned
  metadata (`title`, `event_count`, `labels`) but always advances `cloud_updated_at`. -
  `SyncManager._run_set_diff_pass`: orchestrates Phase 1 (listing) and Phase 2 (set-diff dispatch),
  reusing the existing parallel/sequential download pipeline. - `last_sync_at` survives only as a UX
  field; the engine no longer consults it as a gate.

Review-cycle fixes folded into this commit - fix(sync): JSON-encode `pr_number` list in
  `cloud_listing` (round-1 T1 blocker; the cloud API returns a list and raw bind crashed SQLite). -
  feat(sync): warn on cloud-side removals + document the scalability boundary in
  `docs/guides/syncing.md` (round-1 review-r1 response). - fix(sync): normalize offset-naive
  `--since` to UTC at the top of `_passes_since_filter` (round-2 T6 blocker; previously crashed
  comparing naive vs aware `cloud_updated_at`).

Tests - 25 new unit tests in `tests/unit/db/stores/test_cloud_listing_store.py` and
  `tests/unit/db/stores/test_sync_state_store.py` covering snapshot lifecycle, set-diff helpers,
  dashed↔undashed id normalization (AGENTS.md #14), JSON column round-trip, and k/v bookkeeping. - 6
  behavioral xfails dropped now that the engine actually satisfies them: cursor-advance resume,
  backdated `updated_at`, visibility flip, mid-sync crash, same-listing idempotency, and the
  Hypothesis idempotence property. - +2 parametrized regression tests for the T6 `--since`
  normalization. - Suite: 1805 passed, 3 skipped, 4 xfailed (remaining xfails owned by #112/#113 or
  fake-only pagination artifacts — see PR for table).

AGENTS.md compliance - #27 (manifest as canonical metadata): preserved. Manifest is the diff's
  source-of-truth; `cloud_updated_at` is opportunistic for #114. - #11 (DB stage order): untouched
  (`refs → actions → branch_context → push_pr_links`). - #14 (id normalization): respected at every
  new store boundary.

Manual verification Round-2 re-test against the real cloud (T1–T8 + T6 fix) returned APPROVE (LGTM)
  at 2026-05-28T22:56:47Z. Steady-state sync, gap recovery, `--since` filter, manifest coherence,
  and docs accuracy all verified end-to-end.

Out of scope - #113 user-facing removed-from-cloud reporting + `--repair --fix`. - #114 manifest
  retirement (engine moving to `conversations` table). - FakeCloudClient keyset pagination (needed
  to lift two fake-only xfails).

This PR was authored by an AI agent (OpenHands) on behalf of @jpshackelford.

Closes #111

- **sync**: Rewrite --repair into four-category reconciliation
  ([#113](https://github.com/jpshackelford/ohtv/pull/113),
  [`764410d`](https://github.com/jpshackelford/ohtv/commit/764410d85ad94e23fd98ada26978f2a89ef873c9))

Replaces the legacy ghost/orphan diff with a cloud-vs-local set-diff engine over the #112
  cloud_listing snapshot. `ohtv sync --repair` now reports four labeled buckets: - New on cloud
  (created after last snapshot) - Missing locally (existed before snapshot, never synced) - Removed
  from cloud (in local DB/manifest, not in current listing) - Modified on cloud (cloud_updated_at >
  local cache)

`--repair --fix` downloads + refetches without touching removed entries. `--repair --fix --prune`
  opt-ins to destructive deletion of cloud-only rows; defense-in-depth source='cloud' filter at
  delete time prevents any local-CLI conversation from being pruned. Bare `--prune` raises Click
  UsageError exit 2.

Degraded listing (HTTP failure) short-circuits to non-destructive only and preserves the previous
  snapshot atomically (per #112 abandon contract). Normal sync() now surfaces manifest dropouts via
  SyncResult.removed_from_cloud_ids.

Review fix: cloud_count derivation now reads CloudListingStore.count() directly instead of the
  disk_count-based estimate (which mixed cloud, local-CLI, and orphan rows).

Tests: +20 in tests/unit/sync/test_repair.py; behavioral suite scenarios #4 and #13 markers flipped
  to passing. Full suite 1918 passed / 2 skipped / 3 xfailed; lint clean.

Closes #113.

- **tests**: Cloud-sync behavioral harness ([#110](https://github.com/jpshackelford/ohtv/pull/110),
  [`d2465f3`](https://github.com/jpshackelford/ohtv/commit/d2465f3e89b55ba62e4f7b6c6fff323072cd55d1))

- Lands `tests/unit/sync/` with `builders.py` + `strategies.py` + `conftest.py` (physical
  separation; Hypothesis quarantined to its own module so collection-time imports stay cheap) - 16
  behavioral scenarios covering #110's surface (full-resync, partial-resync,
  manifest-canonical-metadata, sub-conv exclusion, repair categories) - Strict-xfail markers gate
  #111/#112/#113 behaviors; markers come off as features ship, assertions stay -
  `_RecordingCloudClient` migrated to the new harness; ~8-line dedup refactor in
  `FakeCloudClient._filter_by_updated_since` per review feedback - `AGENTS.md` paragraph pointing
  future #111/#112/#113 work at `tests/unit/sync/` and codifying the marker convention

Closes #110
