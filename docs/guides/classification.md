# Classification: `ohtv classify`

Conversation **source** (cloud vs CLI) is auto-detected during indexing but can be inspected, overridden, or bulk-updated.

## `ohtv classify` - Classify Conversation Source

Populates `conversation_human_input.initial_prompt_source` (default `unknown`)
with one of `human` | `automation` | `unknown`. The classification is a
prerequisite for accurate human-vs-automation breakdowns in
`ohtv report velocity` and other downstream metrics.

The command has three behavior modes - single-conversation override, read-only
discovery, and bulk heuristic with a `--confirm` safety gate. **The heuristic
bulk operations only ever touch rows currently set to `unknown`**, so prior
manual overrides are never clobbered by a re-run of `--no-followups` /
`--has-followups`. (The automatic sub-conversation step described
[below](#automatic-sub-conversation-classification) is the one exception — it
runs on every invocation and *can* overwrite a sub previously set to
`human`, by design.)

```bash
# 1) Discovery - list conversations still classified as unknown.
ohtv classify --list-unknown                            # rich table
ohtv classify --list-unknown -1                         # one short_id per line (pipe-friendly)
ohtv classify --list-unknown --repo openhands/openhands # narrow by repo

# 2) Single-conversation override (no --confirm needed).
ohtv classify abc12345 --source human                   # mark one as human
ohtv classify abc12345 --source automation              # override an earlier human flag
ohtv classify abc12345 --source unknown                 # reset

# 3) Bulk heuristic - preview, then apply with --confirm.
ohtv classify --no-followups --source automation                # preview: "Would classify N..."
ohtv classify --no-followups --source automation --confirm      # actually write
ohtv classify --has-followups --source human --confirm          # symmetric heuristic

# 4) Bulk narrowed by repo (writes only matching conversations).
ohtv classify --no-followups --source automation --repo foo/bar --confirm

# 5) Pipe -1 output back into single-conv classification for ad-hoc batches.
ohtv classify --list-unknown -1 | head -5 | xargs -I {} \
  ohtv classify {} --source human
```

**Output formats** (`--list-unknown` only): `table` (default), `lines` /
`-1`, `csv`, `json`. Machine-readable formats suppress Rich decoration so
the output is safe to pipe.

**Heuristic semantics:**

- `--no-followups` -> rows with `followup_message_count = 0`. These ran to
  completion without mid-flight human steering and are most likely
  orchestrator-spawned automation workers.
- `--has-followups` -> rows with `followup_message_count >= 1`. These had a
  human in the loop and are most likely human-initiated.

The heuristics are imperfect by design (an orchestrator may steer mid-run; a
human may one-shot a prompt). The single-conversation override path is the
intended way to correct individual misclassifications.

**Refusing on missing rows:** If you run `ohtv classify <id> --source human`
against a conversation that does not yet have a row in
`conversation_human_input`, the command refuses with an actionable hint to
run `ohtv db process human_input` first. Silent inserts would mask an
unfinished ingestion pipeline and would distort downstream LOC + velocity
metrics that assume the row reflects the actual events.

## Automatic Sub-Conversation Classification

A **sub-conversation** is a delegated agent run — a conversation spawned by
another OpenHands conversation rather than initiated by a human. In the
database, sub-conversations are exactly the rows where
`conversations.parent_conversation_id IS NOT NULL` (populated by migration
019 from the cloud listing API; see AGENTS.md item #31).

Sub-conversations are **never human-initiated by definition** — the parent
agent generates their initial prompt (the delegated task description), so
the only correct value for `initial_prompt_source` on a sub is `automation`.
To enforce this invariant, every `ohtv classify` invocation runs a single
self-healing SQL `UPDATE` *before* dispatching to its mode-specific work
(single override, `--list-unknown`, or bulk heuristic). The update flips
every sub-conversation whose `initial_prompt_source` is not already
`automation` (typically `unknown`, occasionally a stale `human` left over
from a pre-fix `--has-followups --source human` bulk run) to `automation`.

When the auto-step changes one or more rows, the CLI prints:

```
Auto-classified N sub-conversation(s) as 'automation'.
```

(Suppressed when `N = 0`, i.e. the steady-state case once your DB is
consistent.)

**Key properties:**

- **Always-on.** Runs at the top of every `ohtv classify` invocation —
  including `--list-unknown` and single-conversation overrides. No new
  flag, no opt-out.
- **Idempotent.** A second back-to-back invocation reports `N = 0` and
  performs no writes (the `WHERE initial_prompt_source <> 'automation'`
  guard makes the second pass a no-op).
- **Roots are untouched.** The `WHERE EXISTS (... parent_conversation_id
  IS NOT NULL ...)` predicate excludes root conversations entirely —
  their classification is still owned by the heuristic / single-override
  paths above.
- **Subs without a `conversation_human_input` row are silently skipped.**
  If the `human_input` stage has not processed a sub yet, the `EXISTS`
  join has nothing to update. No error, no special-case branch.
- **One overwrite case.** If you previously ran
  `ohtv classify <sub_id> --source human` (or a pre-fix bulk heuristic)
  and left a sub at `human`, the next `ohtv classify` invocation will
  revert it to `automation`. This is the intended behavior of Issue
  \#126: a sub marked `human` was always a misclassification, since the
  initial prompt on a sub is the parent's delegated task, not a human
  request.
- **Within a single invocation, manual overrides still win.** The
  auto-step runs first, then the mode-specific work. So
  `ohtv classify <sub_id> --source human` will flip the sub back to
  `human` *for that invocation* — but the next `classify` run will
  correct it again. To make a sub stay `human` you would have to suppress
  the auto-step entirely, which the CLI deliberately does not allow.

**Schema guardrail.** The auto-step requires the
`conversations.parent_conversation_id` column to exist. If it is missing
(e.g. an older DB that has not been re-scanned since migration 019), the
command prints an actionable error and exits non-zero:

```
Error: classify requires migration 019 (parent_conversation_id); run 'ohtv db scan' to apply pending migrations
```

---

