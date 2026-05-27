# Reporting: velocity, weekly counts, LOC backfill

The `ohtv report` family produces analytical views over your indexed
conversations and the change_refs they contributed (PR creations,
PR merges, and direct pushes). For per-conversation LOC numbers, run
[`ohtv fetch-loc`](#ohtv-fetch-loc---backfill-prpush-loc-from-github)
first to backfill `lines_added` / `lines_removed` from the GitHub API.

## Prerequisites

These commands read from the local SQLite index, so you need a synced and
processed corpus first:

```sh
ohtv sync --process   # sync + run indexing pipeline
ohtv fetch-loc        # backfill LOC for change_refs (network-bound, idempotent)
```

If `lines_added` is NULL for every row in a bucket, the LOC column will
render as `-` (table) or empty (CSV) — that's not a bug, it just means
`fetch-loc` hasn't been run (or the GitHub API call hasn't succeeded yet)
for those refs.

---

## `ohtv report velocity` — Weekly velocity report

Aggregates merged PRs, LOC added/removed, human-input words, and a
words-per-LOC ratio by ISO week (`YYYY-Www`, Monday-start). Joins
`change_refs` × `conversation_contributions` × `conversation_human_input`.

```sh
# Table to stdout (default)
ohtv report velocity

# CSV for downstream processing
ohtv report velocity --format csv > velocity.csv

# Restrict to one repo, last 12 weeks
ohtv report velocity --since 12w --repo jpshackelford/ohtv

# 3-panel publication-quality chart (needs the [charts] extra)
ohtv report velocity --chart velocity.png \
    --since 2026-01-01 --mark-date 2026-03-01 --title "Q1 2026"
```

### Options

| Option | Description |
|---|---|
| `--format [table\|csv]` | Output format. Default `table`. |
| `--since TEXT` | Lower bound on `merged_at`. Absolute (`YYYY-MM-DD`) or relative (`7d`, `2w`, `1m`). |
| `--until TEXT` | Upper bound on `merged_at`. Absolute date only. |
| `--repo TEXT` | Restrict to one repo. Accepts URL, `owner/repo`, or short name (FQN-aware matcher). |
| `--include-empty` | Emit weeks with zero merged PRs (default: omit). |
| `--no-totals` | Suppress the totals row (table only; CSV never has one). |
| `--chart FILE` | Write a 3-panel chart to `FILE` instead of a table/CSV. Extension drives the format: `.png` / `.svg` / `.pdf`. Requires `pip install ohtv[charts]`. |
| `--mark-date YYYY-MM-DD` | Draw a vertical reference line at this date on every panel. Only meaningful with `--chart`. |
| `--title TEXT` | Figure suptitle (only meaningful with `--chart`). Default: `Development Velocity`. |
| `-v, --verbose` | Show the rendered SQL and per-week row counts. |

### Reading the chart

`--chart` writes a 3-panel figure with a shared X axis (ISO weeks):

1. **Panel 1 — PR counts.** Solid blue bars showing the number of merged
   PRs in each week. Direct pushes to `main`/`master` (see
   [indexing § Contributions stage](indexing.md#contributions-stage))
   are also counted here.
2. **Panel 2 — Diverging LOC bars.** Added lines plotted above zero in green,
   removed lines plotted below zero in red. Bars use a `///` **hatch** when
   the week has any rows with `partial_loc=True` (i.e. at least one merged
   PR or push still has NULL `lines_added` — typically because `fetch-loc`
   hasn't been run or the GitHub API call hasn't succeeded yet). A legend
   entry **"Partial LOC (NULL)"** documents the convention on every chart.
   Fully-known rows render as solid bars.
3. **Panel 3 — Words / LOC ratio.** Human-typed words per line of code, as
   a line + marker plot. Weeks with `words_per_loc=None` produce **gaps**
   in the line rather than misleading zeros (e.g. a week with no human
   input or no LOC data is intentionally not interpolated through).

If `--mark-date` is set, a dashed vertical line is drawn across all three
panels at the corresponding week boundary. Useful for marking release
dates, team changes, or other reference points.

**Empty data:** if the time range has zero rows, the command prints the
same "no data" hint as the table path and exits cleanly **without
writing a file**.

### NULL vs zero LOC

ohtv carefully distinguishes "we don't have LOC for this row" (NULL) from
"this PR genuinely added zero lines" (zero). NULLs render as:
- Table format: `-` in the LOC columns
- CSV format: empty string
- Chart Panel 2: the row contributes 0 to the bar height but the bar
  is hatched, and the legend entry `Partial LOC (NULL)` makes the
  convention visible

For the gory details on the storage model see
[reference/database.md](../reference/database.md#change_refs).

---

## `ohtv report weekly-counts` — New-conversation counts by week

Emit a CSV of how many conversations were created each ISO week, optionally
split into `cloud` and `cli` (local) columns. Useful for tracking adoption
trends or filing-rate normalization.

```sh
# All sources, all time, CSV to stdout
ohtv report weekly-counts

# Last 4 weeks, exclude the in-progress week
ohtv report weekly-counts --since 4w --exclude-current-week

# Only CLI conversations, write to file
ohtv report weekly-counts --source cli --out cli-counts.csv

# Include zero-week rows for time-series plotting
ohtv report weekly-counts --since 2026-01-01 --include-empty
```

The CSV header is always `week,cloud,cli,total`. The `cli` column counts
conversations stored with `source='local'` in the DB — the CSV header uses
`cli` because it reads more naturally in a report.

### Options

| Option | Description |
|---|---|
| `--since TEXT` | Lower bound on `created_at`. Absolute or relative. |
| `--until TEXT` | Upper bound on `created_at`. Absolute or relative. |
| `--source [cloud\|cli\|all]` | Restrict to one source. `cli` maps to DB `source='local'`. Default `all`. |
| `--include-empty` | Emit zero-row weeks (default: omit). |
| `--exclude-current-week` | Omit the in-progress (current) ISO week from output. |
| `--out FILE` | Write CSV to `FILE` instead of stdout. |

---

## `ohtv fetch-loc` - Backfill PR/Push LOC from GitHub

Reads pending `change_refs` rows produced by `db process contributions` (PR creations, PR merges, and direct pushes) and calls the GitHub REST API to populate `lines_added`, `lines_removed`, `files_changed`, `merged_at`, and `status`. This is the network-bound, cached, idempotent backfill that powers velocity and human-words-per-LOC reports.

Requires a `GITHUB_TOKEN` (a read-only PAT or the output of `gh auth token`) on non-dry-run invocations. The token is read from the environment and is never logged or printed.

`fetch-loc` slots in after the indexing pipeline once the `actions` and `contributions` stages have populated `change_refs`:

```
sync → db scan → db process all → fetch-loc → db embed
```

```bash
# Preview which rows would be fetched (no token required, no HTTP, no DB writes)
ohtv fetch-loc --dry-run

# Real run — populate LOC for every pending change_ref across all repos
GITHUB_TOKEN=$(gh auth token) ohtv fetch-loc

# Restrict to a single repo (same FQN-aware matcher as `list` / `refs`)
GITHUB_TOKEN=$(gh auth token) ohtv fetch-loc --repo myorg/myrepo

# Re-fetch rows that are already populated (e.g. after a schema fix)
GITHUB_TOKEN=$(gh auth token) ohtv fetch-loc --repo myorg/myrepo --force

# Cap work per invocation (useful for first-time backfills on large indexes)
GITHUB_TOKEN=$(gh auth token) ohtv fetch-loc --limit 50

# Quiet mode for cron jobs (no progress bar, no summary)
GITHUB_TOKEN=$(gh auth token) ohtv fetch-loc --quiet
```

**Options:**
| Flag | Description |
|------|-------------|
| `--repo TEXT` | Restrict to one repo (URL, `owner/repo`, or short name — same matcher as `list` / `refs`) |
| `--force` | Re-fetch rows even if `lines_added` is already populated |
| `--dry-run` | Show what would be fetched without making API calls or DB writes |
| `--limit N` | Cap rows processed this run (default: unlimited) |
| `-q, --quiet` | Minimal output (no progress bar, no end-of-run summary) |
| `-v, --verbose` | Show debug output |

**Behavioral notes:**
- **Idempotent by default.** Rows where `lines_added` and `fetched_at` are both populated are skipped on subsequent runs. Use `--force` to override.
- **Open-PR cache window.** Rows with `status='open'` are re-fetched after a 1 h cache window so they can transition to `merged` or `closed`. Open and closed-unmerged PRs update `status` only — no LOC numbers are written.
- **Rate-limit aware.** Honors `Retry-After`, falls back to `X-RateLimit-Reset`, then exponential backoff + jitter capped at 60 s. Warns when `X-RateLimit-Remaining < 100`.
- **Graceful per-row errors.** A 401, 404, or 5xx on a single row marks that row as "tried" (`fetched_at = now()`) and the run continues. The command only exits non-zero when *every* attempt failed.
- **Non-GitHub repos skipped.** `change_refs` whose canonical URL points at GitLab / Bitbucket / etc. are logged and skipped — only GitHub is supported in v1.
- **Missing token.** On a non-dry-run, if `GITHUB_TOKEN` is unset the command exits non-zero with a pointer to `gh auth token`. The token value is never written to logs.

---

