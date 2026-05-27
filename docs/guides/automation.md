# Automation

ohtv is designed to be run from cron / scheduled tasks. This page
collects the patterns that make scripted use pleasant.

## Quiet mode

Every long-running command supports `-q` / `--quiet`, which suppresses
progress bars and per-row chatter and only prints final summaries (or
nothing if there's nothing to report).

```sh
ohtv sync --quiet --process
ohtv fetch-loc --quiet
ohtv db process all --quiet
```

Combine with cron + `2>&1 | tee -a ~/ohtv-cron.log` for an audit trail.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic runtime error (logged to `~/.ohtv/logs/ohtv.log`) |
| 2 | Click usage error — bad flag, missing argument, unsupported extension |

Scripts should treat any non-zero exit as a failure. The error message is
always written to stderr; stdout is reserved for the command's structured
output (CSV, JSON, etc.).

## Environment-variable precedence

API keys are resolved in this order, with the first non-empty winning:

1. Command-line flag (where applicable, e.g. `--model`)
2. Environment variable (`OPENHANDS_API_KEY`, `LLM_API_KEY`, `GITHUB_TOKEN`)
3. Legacy aliases (`OH_API_KEY` falls back to `OPENHANDS_API_KEY`)
4. Default — typically a polite error explaining which variable is missing

The `OHTV_DIR` variable is the only one without a flag override; set it in
the cron shell or systemd unit, not on the command line.

## Typical cron recipes

### Nightly sync + analysis

```sh
# /etc/cron.d/ohtv  (or systemd timer / launchd plist)
OPENHANDS_API_KEY=...
LLM_API_KEY=...
GITHUB_TOKEN=...

# Every night at 02:00 — sync, index, backfill LOC, generate analyses
0 2 * * *  user  cd ~ && ohtv sync --process --quiet && \
                          ohtv fetch-loc --quiet && \
                          ohtv gen objs --quiet
```

### Weekly velocity CSV

```sh
# Every Monday at 09:00 — drop a CSV into the team's reports folder
0 9 * * 1  user  ohtv report velocity --since 4w --format csv \
                     > ~/reports/velocity-$(date +\%Y-W\%V).csv
```

### Weekly chart for a Slack message

```sh
# Every Monday at 09:05 — render a chart and post it
5 9 * * 1  user  ohtv report velocity --since 12w --chart /tmp/velocity.png \
                     --title "Velocity (last 12 weeks)" \
                 && curl -F file=@/tmp/velocity.png ... slack-webhook
```

### Metadata refresh (catches cloud-side title/label edits)

```sh
# Every 15 minutes — pick up cloud-side renames without re-downloading
*/15 * * * *  user  ohtv sync --update-metadata --quiet
```

See [syncing.md](syncing.md) for the full `--update-metadata` semantics.

## Logging

ohtv logs to `~/.ohtv/logs/ohtv.log`:

- Rotates at 1 MB, keeps 3 backups
- INFO level by default; pass `-v` / `--verbose` on any command to also
  send DEBUG to console
- Override the level globally with `OHTV_LOG_LEVEL=DEBUG`

The log is structured enough for `grep` + `awk` but not for parser-strict
tooling. If you want machine-readable run records, use `--format json` on
the command itself rather than parsing logs.
