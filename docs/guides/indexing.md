# Indexing: `ohtv db`

Build and maintain the local SQLite index that powers `list`, `refs`, `gen`, `search`, and reporting. See [reference/database.md](../reference/database.md) for the schema.

## `ohtv db` - Database Management

Manages the SQLite index database that tracks conversations and their relationships to repositories, issues, and PRs. The database enables fast lookups and future aggregate queries.

See [reference/database.md](../reference/database.md) for the full schema.

## `ohtv db init` - Initialize Database

Creates or migrates the database schema.

```bash
ohtv db init
```

## `ohtv db scan` - Register Conversations

Scans the filesystem and registers conversations in the database. Uses modification time for fast change detection.

```bash
# Scan and register new/changed conversations
ohtv db scan

# Force update all conversations (after backup restore)
ohtv db scan --force

# Remove entries for deleted conversations
ohtv db scan --remove-missing

# Verbose output
ohtv db scan -v
```

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Update all conversations regardless of mtime |
| `--remove-missing` | Remove DB entries for conversations no longer on disk |
| `--lock-timeout SECONDS` | Wait up to N seconds for `$OHTV_DIR/sync.lock` instead of failing fast. Default `0` = fail-fast. |
| `-v, --verbose` | Show detailed output |

> **Writer mutex.** `ohtv db scan` writes to the `conversations` table
> and so acquires the same `$OHTV_DIR/sync.lock` that `ohtv sync` and
> `ohtv gen titles` use. The default is fail-fast — if `ohtv sync` is
> running in another terminal or a cron job, `db scan` will exit 1 with
> a pointer to the lock file. Pass `--lock-timeout=N` to wait. See
> [reference/database.md § Column Ownership and the `sync.lock` Writer Mutex](../reference/database.md#column-ownership-and-the-synclock-writer-mutex)
> for the canonical contract.

## `ohtv db process` - Run Processing Stages

Runs processing stages on registered conversations. Each stage extracts specific data and stores it in the database.

```bash
# Process refs (repos, issues, PRs) for all pending conversations
ohtv db process refs

# Process actions (file edits, git ops, PRs, etc.)
ohtv db process actions

# Run all stages in sequence
ohtv db process all

# Force reprocess all conversations
ohtv db process refs --force

# Process a specific conversation
ohtv db process refs --conversation abc123

# Verbose output
ohtv db process refs -v
```

**Available Stages:**
| Stage | Description |
|-------|-------------|
| `refs` | Extract repository, issue, and PR references |
| `actions` | Recognize actions (file edits, git ops, PRs, issues, Notion, etc.) |
| `contributions` | Walk the action timeline to attribute PR creation/merge/push contributions to `change_refs` (depends on `actions`) |
| `human_input` | Count human input events per conversation; preserves `initial_prompt_source` for future classification |
| `all` | Run all stages in sequence |

Stage dependencies are respected when running `all` (e.g. `contributions` runs after `actions`). Running a stage individually before its dependencies have completed is allowed but produces no useful results — prefer `db process all` unless you know what you're doing.

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Reprocess all conversations |
| `-c, --conversation ID` | Process only this conversation |
| `-v, --verbose` | Show detailed output |

### Contributions stage

The `contributions` stage attributes code-landing events to the
conversations that produced them, writing rows to `change_refs` and
`conversation_contributions`. It runs after `actions` (which surfaces the
raw git/PR events) and powers the downstream `report velocity`,
`fetch-loc`, and `list --action` commands.

Three event types are recognized as **contributions**:

1. **PR creation** — A `gh pr create` / browser-opened-PR event that
   creates a new PR. The change_ref is opened in `kind='pr_create'` state
   and linked to the originating conversation. ([PR #78/#88](https://github.com/jpshackelford/ohtv/pull/88))
2. **PR merge** — A merge event landing on the target branch. Updates the
   linked change_ref with `merged_at`. If the original creator
   conversation differs from the merger conversation (e.g. a different
   agent run did the merge), both contributions are recorded.
3. **Direct push to `main`/`master`** — A `git push` that lands a commit
   on the protected default branch *without* an associated PR open/merge
   event. Recorded as `kind='push'` in `change_refs`. ([PR #79/#94](https://github.com/jpshackelford/ohtv/pull/94))

Direct pushes are treated as first-class contributions for LOC and
velocity accounting: `report velocity` includes them in Panel 1's "PRs
merged" bar (the column header is conventional shorthand) and `fetch-loc`
populates their `lines_added` / `lines_removed` from the GitHub commit
API rather than the PR API.

#### How direct-push detection works

The `git_operations` recognizer (added in PR #94) inspects each
`git push` action and asks:

- Did the push target `refs/heads/main` or `refs/heads/master`?
- Is there a PR open/merge event in the same conversation referencing the
  pushed SHA?

If both checks say *push to default branch* AND *no associated PR event*,
the push is recorded as a direct-push change_ref. Otherwise the push is
treated as part of a PR workflow (and the PR event provides the
contribution).

This means **squash-merges and rebase-merges via the GitHub UI are NOT
direct pushes** — they come with their own merge event. Only literal
`git push origin main` (or comparable) lands here.

#### Filtering for direct pushes

```bash
# List conversations that pushed directly to main/master
ohtv list --action pushed

# In velocity reports, direct pushes are aggregated into the same bucket
# as merged PRs. To split them, drop into the database and group by
# change_refs.kind.
```

## `ohtv db reset` - Delete Database

Deletes the database to start fresh. Source conversation files are NOT affected.

```bash
# Delete with confirmation prompt
ohtv db reset

# Delete without confirmation
ohtv db reset --yes
```

**Options:**
| Flag | Description |
|------|-------------|
| `-y, --yes` | Skip confirmation prompt |

## `ohtv db status` - Show Database Status

Displays database statistics.

```bash
ohtv db status
```

**Example Output:**
```
Database: /Users/you/.ohtv/index.db
Size: 6.1 MB

Records:
  Conversations: 1297 (1183 roots + 114 subs across 42 trees)
  Repositories: 156
  References (issues/PRs): 428
  Repo Links: 892
  Reference Links: 1245
  Actions: 17770

Actions by type:
  edit-code: 5258
  study-code: 4098
  edit-docs: 1840
  git-commit: 1569
  git-push: 1335
  check-ci: 1290
  ...
```

## `ohtv db migrate-cache` - Migrate Cache Files

Migrates LLM analysis cache files from legacy locations (inside conversation directories) to the centralized location (`~/.ohtv/cache/analysis/`). This is needed if you have cache files from older versions of ohtv.

**Note:** If legacy cache files are detected, `ohtv gen objs` will display a warning prompting you to run this migration.

```bash
# Preview what would be migrated (no changes made)
ohtv db migrate-cache --dry-run

# Migrate cache files (copies to new location, keeps originals)
ohtv db migrate-cache

# Migrate and delete original files after successful copy
ohtv db migrate-cache --delete-legacy

# Show detailed progress
ohtv db migrate-cache -v
```

**Options:**
| Flag | Description |
|------|-------------|
| `--dry-run` | Show what would be migrated without making changes |
| `--delete-legacy` | Delete legacy cache files after successful migration |
| `-v, --verbose` | Show detailed output |

## `ohtv db embed` - Build Embeddings for Search

Generates vector embeddings for semantic search and RAG (Retrieval-Augmented Generation). Creates multiple embedding types per conversation:
- **analysis** - Goal + outcomes from cached LLM analysis
- **summary** - User messages + refs (repos/PRs/issues) + file paths
- **content** - File contents + terminal outputs (chunked if large)

```bash
# Build embeddings for new conversations
ohtv db embed

# Show cost estimate without embedding
ohtv db embed --estimate

# Rebuild all embeddings
ohtv db embed --force

# Skip confirmation prompt
ohtv db embed --yes
```

**Options:**
| Flag | Description |
|------|-------------|
| `-f, --force` | Rebuild all embeddings |
| `--estimate` | Show cost estimate only |
| `-y, --yes` | Skip confirmation prompt |
| `-v, --verbose` | Show detailed output |

---

