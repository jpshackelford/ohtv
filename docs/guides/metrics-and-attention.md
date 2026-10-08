# Metrics and human attention

ohtv can tell you more than what an agent did. It can tell you **how much
human attention each conversation, and each merged PR, took**. This page is
the overview. It lists the metrics, explains how the engagement metric works,
summarises what the data has shown so far, and gives recipes for answering
real questions.

For command-by-command detail, follow the links to the other guides.

## The question these metrics answer

> Does agent orchestration let us ship more per unit of human effort?

No single number answers that. ohtv records several signals, and each one
measures a different thing:

| Signal | Measures | Source |
|---|---|---|
| **Human words / messages** | How *much* the human said | `conversation_human_input` |
| **Engaged minutes** | How *long* the human was paying attention | `conversation_engagement` |
| **Attention periods** | How many separate times the human came back | `conversation_engagement` |
| **Unattended share** | How many conversations needed no steering at all | `conversation_engagement` |
| **Merged PRs / direct pushes** | What was delivered | `change_refs` |
| **Lines changed (LOC)** | How big the delivery was | `change_refs` (via `fetch-loc`) |

Two conversations with the same word count can differ a lot in supervision.
One person might type 200 words over 25 minutes of close steering. Another
might type 200 words in two short bursts hours apart. Words say how much was
typed, and engaged minutes say how long someone was watching. Use both.

## Metric catalogue

| Metric | Where to get it | Needs |
|---|---|---|
| Engaged time, periods, engaged share of duration | `ohtv show <id>`, `ohtv list --with-engagement`, `gen objs --with-engagement` | `db process engagement` |
| Engagement filters | `--engaged`, `--no-engaged`, `--min-engaged 5m`, `--min-engagement-ratio 25` on `list` and every `gen` subcommand | `db process engagement` |
| Human words and messages | `ohtv report velocity` (Words, Msgs, Words/LOC) | `db process human_input`, `classify` |
| Merged PRs and LOC per week | `ohtv report velocity` (table, CSV, `--chart`) | `db process contributions`, `fetch-loc` |
| Outcomes per conversation (PRs and issues, with state) | `ohtv list --with-outcomes` | `refs`, `actions`, `contributions` |
| Conversations created per week | `ohtv report weekly-counts` | none |
| What the human actually typed | `ohtv messages` | `db process engagement` |
| Daily or weekly summary of work | `ohtv report worklog` | `db process engagement`, an LLM key for synthesis |

Build the index first with `ohtv sync --process` and `ohtv fetch-loc`. See
[indexing](indexing.md) and [reporting](reporting.md).

## How engaged minutes work

The metric needs no content inspection. It uses only timestamps: how long
before each of your messages was the agent still active?

### Plain-language version

1. The first user message starts the conversation. Every later user message
   is a **follow-up**.
2. A follow-up counts as **attended** if it arrived soon after the event
   just before it (default 12 minutes). That means you were around when you
   sent it.
3. An attended follow-up gets credit for the time since your previous
   message, because you were presumably reading along. That credit is
   capped. If your previous message was more than an hour ago (default), you
   only get a zero-length "touch". You came back, but nobody watches an
   agent for ten hours straight.
4. Blocks of credit that sit close together merge into one **attention
   period**. Engaged time is the total length of the periods.

Conversations with zero or one user message are **fire-and-forget**. They
store `engaged_seconds = 0`, not `NULL`.

### The two constants

| Symbol | Flag | Default | Meaning |
|---|---|---|---|
| `T` | `--threshold` (seconds) | 12 min (720) | Silence tolerance: how long can you be quiet while the agent works and still count as present? |
| `T_a` | `--sustained-attention` (seconds) | 1 h (3600), **provisional** | Sustained-attention window: how long can you plausibly watch in one stretch before we assume you walked away? |

Both values are stored on every row, along with an algorithm version. Rows
computed under different settings stay distinguishable.

```bash
ohtv db process engagement                                   # defaults
ohtv db process engagement --threshold 600 --force           # T = 10 min
ohtv db process engagement --sustained-attention 1800 --force  # T_a = 30 min
```

### Worked example

A conversation runs about 10 hours. You steer it for the first 8 minutes,
leave, and come back after the agent has run overnight:

```
00:00   You:   "Implement the feature"                (initial prompt)
04:30   Agent: ...working...
05:00   You:   "Also handle the empty case"           ← 30 s after the last event: attended
07:50   Agent: ...working...
08:00   You:   "Looks good, keep going"                ← attended
        Agent: acts every ~3 minutes for ~10 hours
10:05   You:   "Thanks, ship it"                       ← 30 s after the last agent event
```

| Algorithm | Engaged | Periods |
|---|---|---|
| v2 (current, `T_a` = 1 h) | **8 min** | 2 (the opening session, plus a touch when you came back) |
| v1 (no `T_a` cap, `--sustained-attention 999999999`) | **10 h 5 min** | 1 |

I ran this with `compute_engagement`. The v1 result is the bug described in
[Lessons learned](#2-the-overnight-overcount-issue-184).

### Edge cases

- **Events after your last message** do not extend an attention period.
- `T = 0` makes every gap unattended, so engaged time is 0.
- A very large `T` makes every follow-up attended.
- A follow-up straight after the initial prompt, with no events between, is
  a period of 0 seconds. The period counter still records that you touched
  the conversation.
- Total duration is `last_event_ts - first_event_ts` from the event files.
  It is not `updated_at - created_at` from `base_state.json`, which can
  drift.

## What we've learned so far

These results come from the maintainer's own data and from the PRs and
issues that shaped the metric. They show how the numbers behave in
practice. They are not general benchmarks.

### 1. Most steering is immediate, and the threshold barely matters

A study over a single ohtv index (4,791 conversations, 9,935 follow-up
gaps) looked at the gap between each follow-up and the event before it.
The study ran before the `T_a` cap existed. Full detail is in
[the threshold analysis](../design/engagement-threshold-analysis.md).

| Gap before a follow-up | Share of follow-ups | Cumulative |
|---|---|---|
| under 30 s | 69.6% | 69.6% |
| under 1 min | 5.0% | 74.6% |
| 1–3 min | 12.4% | 87.0% |
| 3–8 min | 7.4% | 94.4% |
| 8–12 min | 1.7% | 96.1% |
| over 12 min | 3.9% | 100% |

- **The median gap is about zero seconds.** Most steering happens while
  the person is watching the agent live.
- **Counts fall off sharply around 10 minutes.** Beyond that they plateau at
  about 25–28 gaps per minute. That plateau is "came back later" territory.
- **Choosing `T` changes the totals very little.** Engaged hours across the
  corpus moved from 2,604 h at `T` = 6 min to 2,659 h at 12 min and 2,717 h
  at 28 min, about 4% across the whole range. In all cases engaged time was
  roughly 23–24% of total conversation time.
- **Most conversations were never steered.** Only 1,505 of the 4,791 had any
  follow-up message. By subtraction, about 69% were fire-and-forget.
- **Gaps of 8–12 minutes are mostly inattention.** About 65% of them had
  little content on both sides (under 300 agent words and under 50 user
  words). Only about 2% followed 700 or more agent words, which would
  justify a long read. About a third of gaps in that range are real
  reading and composing time, and the rest are brief distraction. That mix
  stays the same from 5 to 15 minutes, so no content-based cutoff favours
  8 over 10 or 12.

The study's conclusion was that 12 minutes is reasonable and 10 is slightly
better supported. Pick one value and use it for every period you compare.
A higher `T` counts more attention, so it errs on the side of understating
any efficiency gain.

> The totals above come from the first, uncapped version of the metric.
> Re-run the sweep (`scripts/engagement_threshold_sweep.py`) on your own
> index before quoting absolute numbers.

### 2. The overnight overcount (issue #184)

While charting data for an orchestration-impact presentation, nine
conversations showed 4–21 hours of "engagement", each recorded as a single
attention period:

| Engaged | Total duration | Share |
|---|---|---|
| 20.7 h | 36.7 h | 56% |
| 14.0 h | 14.0 h | 99% |
| 12.7 h | 13.2 h | 96% |

Normal interactive sessions in the same data showed 45–57 minutes engaged.

The cause: an agent working overnight emits an event every few minutes.
That kept the "were you present?" check satisfied for the morning
follow-up. The credited block then stretched back to the previous user
message, which was 14 hours earlier. The nine rows inflated engaged time by
about 50 hours.

Why it matters: the issue notes that this inflated engagement most for
pre-orchestration conversations, which tended to be longer interactive
sessions, and made week-over-week comparisons unreliable.

The fix (v2, PR #185) added the `T_a` cap. Early drafts reused `T` for this,
and a reviewer pointed out that `T` already means something else. The result
is two constants with separate meanings and defaults.

### 3. Count roots, not subs

Delegated sub-conversations are stored as their own conversations. After
sub-conversation sync landed, two reports quietly double-counted:

- `report velocity` counted a sub's follow-up words when the sub pushed to
  its parent's PR (issue #124).
- `report weekly-counts` counted every delegated sub as a new conversation
  (PR #152).

Both now aggregate at **root** level, and sub-conversations are classified
`sub_agent` and contribute zero human words. Use `root_conversation_id` in
any query of your own (see [the recipes](#recipes)).

### 4. Look at pushes as well as PRs

In an early 50-conversation sample, indexing found 23 direct pushes to
`main` and only 1 PR. A PR-only count would have missed almost all
delivered work in that workflow. Velocity reports count direct pushes and
merged PRs in the same bucket. It was a small sample from one workflow, so
check your own mix before relying on it.

### 5. What has not been measured yet

The repo does not yet contain a result for the original question, whether
orchestration changed throughput per attention-hour. The study recommends
this analysis:

1. Lead with the unattended share, which does not depend on `T`.
2. Show merged PRs and LOC per attention-hour over time.
3. Repeat the analysis at `T` = 8, 10 and 12 minutes to show the conclusion
   holds.
4. Compare like with like: same repos, similar task types.

No built-in report computes PRs per attention-hour yet. [The recipes](#recipes)
below show how to get it from SQL.

## Using the metrics

### Look at one conversation

```bash
ohtv show <id>
#   Duration: 50m 12s
#   Engaged:  4m 24s in 2 periods (8.8% of 50m total)
```

### Compare many conversations

```bash
ohtv list --with-engagement                # Engaged / Periods / Eng% columns
ohtv list --enriched -A --week             # engagement + resulting PRs/issues
ohtv list --engaged --week                 # anything you steered
ohtv list --no-engaged --week              # fire-and-forget (includes unprocessed rows)
ohtv list --min-engaged 30m                # at least 30 minutes of attention
ohtv list --min-engagement-ratio 50        # watched for at least half of wall time
```

`--min-engaged` accepts `30s`, `5m`, `1h`, `1h30m`. A bare number means
minutes.

Add `--event-dates` to interpret date filters against when engagement
*happened* instead of when the conversation was created. That finds
long-running conversations you picked up again this week. See
[exploration](exploration.md).

### Read what you said

```bash
ohtv messages -D 7             # your messages from the last 7 days, grouped by conversation
ohtv messages -W -F json
```

### Summarise a day or week

```bash
ohtv report worklog --date -1 --engaged --min-engaged 5m
ohtv report worklog --week --format markdown -o worklog.md
```

### Track delivery

```bash
ohtv report velocity --since 12w
ohtv report velocity --chart velocity.png --since 2026-01-01 --mark-date 2026-03-01
```

`--mark-date` draws a vertical line on each panel. Use it for the date
orchestration was introduced. Words/LOC is the report's human-effort
measure. It does not use engaged minutes. For that, use the recipes below.

## Recipes

The index is a SQLite file at `~/.ohtv/index.db`. Open it with `sqlite3`. All
queries below work at root-conversation level.

### Share of conversations that were never steered, by month

```sql
SELECT strftime('%Y-%m', c.created_at)                       AS month,
       COUNT(*)                                              AS conversations,
       SUM(COALESCE(ce.engaged_seconds, 0) = 0)              AS unattended,
       ROUND(100.0 * SUM(COALESCE(ce.engaged_seconds, 0) = 0) / COUNT(*), 1) AS pct_unattended
FROM conversations c
LEFT JOIN conversation_engagement ce ON ce.conversation_id = c.id
WHERE c.id = c.root_conversation_id
GROUP BY month
ORDER BY month;
```

A missing engagement row counts as unattended here. This matches
`--no-engaged`. Run `ohtv db process engagement` first so that unprocessed
conversations do not inflate the number.

### Merged PRs and LOC per attention-hour, by month

```sql
WITH merged AS (
    SELECT id,
           strftime('%Y-%m', merged_at)          AS month,
           lines_added + lines_removed           AS loc
    FROM change_refs
    WHERE status = 'merged' AND merged_at IS NOT NULL
),
roots AS (
    SELECT DISTINCT m.month, c.root_conversation_id AS root_id
    FROM merged m
    JOIN conversation_contributions cc ON cc.change_ref_id = m.id
    JOIN conversations c               ON c.id = cc.conversation_id
),
attention AS (
    SELECT r.month, SUM(ce.engaged_seconds) / 3600.0 AS hours
    FROM roots r
    JOIN conversation_engagement ce ON ce.conversation_id = r.root_id
    GROUP BY r.month
)
SELECT m.month,
       COUNT(*)                                        AS merged,
       SUM(m.loc)                                      AS loc,
       ROUND(a.hours, 1)                               AS attention_hours,
       ROUND(COUNT(*) / NULLIF(a.hours, 0), 2)         AS prs_per_attention_hour,
       ROUND(SUM(m.loc) / NULLIF(a.hours, 0), 0)       AS loc_per_attention_hour
FROM merged m
LEFT JOIN attention a ON a.month = m.month
GROUP BY m.month
ORDER BY m.month;
```

Notes on reading this:

- It attributes a conversation's *whole* engaged time to the month its PR
  merged. A long conversation that spans months will land in one.
- A conversation that contributes to several PRs in one month counts once for
  that month, which is the root-level dedupe from [lesson 3](#3-count-roots-not-subs).
- It ignores attention spent on conversations that never produced a merged
  PR. If that is the question, drop the `merged` join and compare totals.
- `loc` is `NULL` for PRs that `fetch-loc` has not reached. Check
  `lines_added IS NULL` before trusting `loc_per_attention_hour`.
- Use calendar months here. SQLite's `%W` is not ISO weeks (see the
  [glossary](../reference/glossary.md)).

### Check sensitivity to `T`

```bash
for t in 480 600 720; do
  ohtv db process engagement --threshold $t --force
  sqlite3 ~/.ohtv/index.db "SELECT $t, ROUND(SUM(engaged_seconds)/3600.0, 1) FROM conversation_engagement;"
done
```

Re-run the recipes for each `T` and check that your conclusion holds in all
three. Finish by restoring the value you intend to report with.

## Pitfalls

- **Sub-conversations.** Count and sum at root level (`id =
  root_conversation_id`). Otherwise delegated work inflates counts and
  human words.
- **`T_a` is a placeholder.** The 1-hour default was picked to remove the
  overnight outliers while keeping 30–60 minute sessions. It has not been
  tuned against labelled data (issue #186, on hold). Treat it as a
  plausible value, not a measured one. Keep it constant across periods.
- **Mixing settings.** Rows record the `T`, `T_a` and algorithm version they
  were computed under. Re-process with `--force` before comparing rows
  computed with different settings.
- **Old rows.** Rows from before PR #185 carry algorithm version 1. Re-run
  `ohtv db process engagement --force` to pick up the cap.
- **NULL versus zero.** An engagement of `0` means the conversation was
  processed and not steered. A missing row means it was never processed.
  Likewise NULL LOC means not fetched, while zero LOC means no lines
  changed.
- **Unclassified conversations.** Velocity treats `unknown` initial prompts
  as human. If automation starts many conversations in your setup, run
  [`ohtv classify`](classification.md) first.
- **Attention is inferred.** The metric guesses presence from timing. Someone
  can leave a window open and reply quickly, or read closely without
  replying. It compares periods well when the settings are constant, but it
  is not a stopwatch.
- **Higher `T` is conservative.** It counts more attention, which understates
  efficiency gains.

## Open questions

- **Tune `T_a`** against hand-labelled conversations (issue #186).
- **Add attention-hours to `report velocity`.** Today the report uses words
  only, and the per-attention-hour ratios need the recipes above.
- **Tail time.** Agent activity after your last message does not extend an
  attention period. A forward extension was considered and deferred.
- **Orchestration impact.** The before/after comparison the metrics were
  built for has not been published in the repo.

## Further reading

- [Design: conversation metrics](../design/conversation-metrics.md): schema,
  algorithm and edge cases.
- [Threshold analysis](../design/engagement-threshold-analysis.md): the full
  tables behind the lessons above.
- [Indexing: engagement stage](indexing.md#engagement-stage)
- [Exploration](exploration.md): `list` and `show` flags.
- [Reporting](reporting.md): `velocity`, `weekly-counts`, `fetch-loc`.
- [Classification](classification.md): human versus automation.
- [Database reference](../reference/database.md)
- Scripts: `scripts/engagement_threshold_sweep.py`,
  `scripts/analyze_engagement.py`, `scripts/analyze_gaps_with_content.py`.
