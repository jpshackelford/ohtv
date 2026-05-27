# Classification: `ohtv classify`

Conversation **source** (cloud vs CLI) is auto-detected during indexing but can be inspected, overridden, or bulk-updated.

## `ohtv classify` - Classify Conversation Source

Populates `conversation_human_input.initial_prompt_source` (default `unknown`)
with one of `human` | `automation` | `unknown`. The classification is a
prerequisite for accurate human-vs-automation breakdowns in
`ohtv report velocity` and other downstream metrics.

The command has three behavior modes - single-conversation override, read-only
discovery, and bulk heuristic with a `--confirm` safety gate. **Bulk
operations only ever touch rows currently set to `unknown`**, so prior manual
overrides are never clobbered by a re-run.

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

---

