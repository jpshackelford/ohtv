# Specification: Refs Command Interaction Type Detection

## Overview

Enhance the `ohtv refs` command to indicate not just *which* GitHub/GitLab/Bitbucket references were encountered in a conversation, but also *how* the agent interacted with them.

## Current Behavior

The `refs` command extracts URLs from conversation events and categorizes them:

```
$ ohtv refs abc123

Repositories
  • https://github.com/owner/repo

Issues
  • https://github.com/owner/repo/issues/42

Pull Requests / Merge Requests
  • https://github.com/owner/repo/pull/123
```

## Proposed Enhancement

Add interaction type annotations to each reference:

```
$ ohtv refs abc123

Repositories
  • https://github.com/owner/repo [cloned]

Issues
  • https://github.com/owner/repo/issues/42 [commented]
  • https://github.com/owner/repo/issues/99 [created]

Pull Requests / Merge Requests
  • https://github.com/owner/repo/pull/123 [created, pushed]
  • https://github.com/owner/repo/pull/456 [commented]
  • https://github.com/owner/repo/pull/789 [viewed]
```

## Interaction Types

### For Repositories

| Type | Description | Reliability |
|------|-------------|-------------|
| `cloned` | Repository was cloned via `git clone` | HIGH |
| `pushed` | Commits were pushed to this repo | HIGH |
| `referenced` | Just mentioned/viewed (default) | N/A |

### For Pull Requests / Merge Requests

| Type | Description | Reliability |
|------|-------------|-------------|
| `created` | PR was created in this conversation | HIGH |
| `pushed` | Commits were pushed to the PR's branch | HIGH |
| `commented` | A comment was added to the PR | HIGH |
| `merged` | PR was merged | HIGH |
| `closed` | PR was closed | HIGH |
| `reviewed` | A review was submitted | MEDIUM |
| `viewed` | Just viewed/read (default, no explicit action detected) | N/A |

### For Issues

| Type | Description | Reliability |
|------|-------------|-------------|
| `created` | Issue was created in this conversation | HIGH |
| `commented` | A comment was added to the issue | HIGH |
| `closed` | Issue was closed | HIGH |
| `viewed` | Just viewed/read (default) | N/A |

## Detection Heuristics

### HIGH Reliability Patterns

These patterns can be detected with high confidence by searching for specific command patterns and their successful outputs in the trajectory.

#### Git Push Detection

**Pattern:** `git push` command followed by successful output

```
# Search ActionEvent for CmdRunAction containing:
git push origin <branch>
git push -u origin <branch>
git push --force origin <branch>

# Verify ObservationEvent contains success indicators:
- "To github.com:owner/repo.git"
- "Branch 'branch' set up to track"
- "[new branch]" or "branch -> branch"
```

**Correlation:** Match the repository URL from the push output to the refs list.

#### GitHub CLI - PR Creation

**Pattern:** `gh pr create` followed by successful output

```
# ActionEvent command:
gh pr create --title "..." --body "..."
gh pr create -B main -H feature-branch

# ObservationEvent contains:
- "Creating pull request for"
- "https://github.com/owner/repo/pull/123"
```

**Extraction:** Parse the PR URL from the output to match against refs.

#### GitHub CLI - PR Comment

**Pattern:** `gh pr comment` or `gh pr review`

```
# ActionEvent command:
gh pr comment 123 --body "..."
gh pr review 123 --approve
gh pr review 123 --comment --body "..."

# ObservationEvent contains:
- (no explicit success message, but exit code 0)
```

**Extraction:** Parse PR number from command, construct URL.

#### GitHub CLI - Issue Creation

**Pattern:** `gh issue create` followed by output

```
# ActionEvent command:
gh issue create --title "..." --body "..."

# ObservationEvent contains:
- "https://github.com/owner/repo/issues/123"
```

#### GitHub CLI - Issue Comment

**Pattern:** `gh issue comment`

```
# ActionEvent command:
gh issue comment 42 --body "..."
```

#### GitHub CLI - Close/Merge

```
# ActionEvent commands:
gh pr merge 123
gh pr close 123
gh issue close 42
```

### MEDIUM Reliability Patterns

These patterns provide useful signal but have more edge cases.

#### API Calls via curl/fetch

```
# POST to create PR
curl -X POST https://api.github.com/repos/owner/repo/pulls

# POST to comment
curl -X POST https://api.github.com/repos/owner/repo/issues/123/comments
```

**Caveat:** Requires parsing request body to determine intent; may have auth failures.

#### MCP Tool Calls (if GitHub MCP is used)

```
# Look for tool calls with names like:
github_create_pull_request
github_add_comment
github_create_issue
```

**Caveat:** Varies by MCP configuration; tool names may differ.

### NOT RECOMMENDED (Low Reliability)

These patterns are too unreliable to implement:

- **Inferring from URL presence alone**: Can't distinguish reading a PR from interacting with it
- **Inferring from browser navigation**: MCP browser tools show visited URLs but not actions taken
- **Inferring from fetch tool**: Just downloading content, not interacting

## Implementation Notes

### Data Flow

1. **Phase 1 (existing):** Extract all git URLs from event text
2. **Phase 2 (new):** Scan events for interaction patterns
3. **Phase 3 (new):** Correlate patterns with extracted URLs
4. **Phase 4 (existing):** Display results with annotations

### Correlation Challenges

**PR ↔ Branch correlation:**
When we see `git push origin feature-branch`, we need to determine which PR (if any) this branch is associated with. Options:
- Look for `gh pr create -H feature-branch` in the same conversation
- Look for PR URLs that mention the branch name
- Accept partial matches when branch name appears in command context

**Issue/PR number extraction:**
Need regex patterns to extract numbers from:
- `gh pr comment 123` → PR #123
- `gh issue close 42` → Issue #42
- URLs in outputs: `https://github.com/owner/repo/pull/123`

### State Machine

For each ref URL, maintain a set of detected interaction types:

```python
@dataclass
class RefInteraction:
    url: str
    ref_type: Literal["repo", "pr", "issue"]
    interactions: set[str]  # {"created", "pushed", "commented", etc.}
```

### Output Options

Consider adding CLI flags:

```bash
# Default: show interaction types
ohtv refs abc123

# Show only refs with write interactions (exclude "viewed")
ohtv refs abc123 --writes-only

# JSON output for scripting
ohtv refs abc123 --format json
```

JSON output structure:
```json
{
  "repos": [
    {"url": "https://github.com/owner/repo", "interactions": ["cloned", "pushed"]}
  ],
  "issues": [
    {"url": "https://github.com/owner/repo/issues/42", "interactions": ["created"]}
  ],
  "prs": [
    {"url": "https://github.com/owner/repo/pull/123", "interactions": ["commented"]}
  ]
}
```

## Scope Limitations

### In Scope

- GitHub (github.com) - full support
- GitLab (gitlab.com) - partial support (common `glab` CLI patterns)
- Bitbucket (bitbucket.org) - minimal support (less common CLI)

### Out of Scope (for initial implementation)

- Self-hosted instances (custom domains)
- API authentication verification (we detect commands, not auth success)
- Real-time validation against actual git hosting APIs

## Future Enhancements

1. **Confidence scores**: Instead of binary presence, show confidence level
2. **Timeline**: Show when each interaction occurred in the conversation
3. **Aggregation across conversations**: "Show all PRs I pushed to this week"
4. **Integration with `ohtv show`**: Highlight interactions in conversation view

## Open Questions

1. **How to handle failed interactions?** If `git push` fails, should we still note "attempted push"?
   - Recommendation: Only mark interactions where we detect success indicators

2. **Should "viewed" be explicit or implicit?** Currently, if no interactions detected, the ref is implicitly "viewed".
   - Recommendation: Make "viewed" implicit (don't show annotation for view-only refs)

3. **Performance impact?** Second pass through events may slow down large conversations.
   - Recommendation: Lazy evaluation; only scan for patterns if `--detailed` flag or similar

---

## Experimental Validation

Two experimental scripts validate these heuristics against real trajectory data:

1. `experiments/analyze_interactions.py` - Detects interaction patterns and success rates
2. `experiments/analyze_correlation.py` - Validates ref extraction and matching accuracy

### Interaction Detection Results (994 conversations)

| Pattern | Detected | Successful | Success Rate |
|---------|----------|------------|--------------|
| `git_push` | 711 | 592 | 83.3% |
| `gh_issue_create` | 66 | 55 | 83.3% |
| `gh_pr_comment` | 33 | 30 | 90.9% |
| `gh_issue_comment` | 26 | 23 | 88.5% |
| `gh_pr_create` | 8 | 6 | 75.0% |
| `gh_pr_close` | 4 | 3 | 75.0% |
| `gh_issue_close` | 2 | 2 | 100.0% |
| `gh_pr_merge` | 2 | 2 | 100.0% |
| **Total** | **852** | **713** | **83.7%** |

### Ref Correlation Results (Critical for matching to correct entity)

| Pattern | Detected | Ref Extracted | Matched to Refs | Match Rate |
|---------|----------|---------------|-----------------|------------|
| `git_push` | 711 | 592 (83%) | 589 | **99.5%** |
| `gh_issue_create` | 66 | 55 (83%) | 55 | **100%** |
| `gh_pr_comment` | 33 | 33 (100%) | 33 | **100%** |
| `gh_issue_comment` | 26 | 26 (100%) | 20 | **76.9%** |
| `gh_pr_create` | 8 | 6 (75%) | 6 | **100%** |
| `gh_pr_close` | 4 | 4 (100%) | 3 | **75%** |
| `gh_issue_close` | 2 | 2 (100%) | 2 | **100%** |
| `gh_pr_merge` | 2 | 2 (100%) | 2 | **100%** |
| **Total** | **852** | **720 (84.5%)** | **710** | **98.6%** |

**Key metric: Of refs we can extract, 98.6% correctly match a ref URL in the conversation.**

### Key Findings

1. **High correlation accuracy**: When we can extract the target ref from a command/output, we match it to the correct conversation ref 98.6% of the time.

2. **Extraction is the bottleneck**: 84.5% extraction rate. The 15.5% failures are primarily:
   - Auth failures (no successful output to parse)
   - Chained commands where push output is truncated

3. **gh commands are most reliable**: Commands like `gh pr comment 123 --repo owner/repo` have explicit repo/number info, giving 100% extraction and high match rates.

4. **git push relies on output parsing**: The repo URL comes from "To https://github.com/..." in the output, which is only present on successful pushes.

### Extraction Strategy by Pattern

| Pattern | Primary Extraction | Fallback |
|---------|-------------------|----------|
| `gh pr/issue comment/review/close N` | `--repo` flag + number from command | Output URL |
| `gh pr/issue create` | PR/Issue URL from output | N/A |
| `gh pr merge N` | Success message `owner/repo#N` | `--repo` flag |
| `git push` | "To https://github.com/..." from output | N/A |

### False Negative Categories (correctly marked as failures)

- Token/auth expired: `Password for 'https://ghu_...@github.com':`
- Missing remote: `fatal: The current branch ... has no upstream branch`
- Permission denied
- Network errors

### Recommended Detection Strategy

1. **Primary**: Check `exit_code == 0`
2. **Extract ref**: Parse command for `--repo owner/repo` and number, or parse output for URLs
3. **Normalize URLs**: Remove `.git` suffix, trailing slashes
4. **Match to refs**: Compare extracted ref to conversation's refs list
5. **Handle failures gracefully**: If extraction fails, the interaction is detected but not attributed to a specific ref

### Running the Experiments

```bash
cd trajectory-viewer

# Interaction detection analysis
uv run python experiments/analyze_interactions.py --limit 500

# Correlation analysis (ref extraction + matching)
uv run python experiments/analyze_correlation.py --limit 500

# See unmatched interactions to debug extraction
uv run python experiments/analyze_correlation.py --limit 500 --show-unmatched

# Verbose mode - see all matches
uv run python experiments/analyze_correlation.py --limit 500 -v
```

### Future Experiment Ideas

1. **Cross-validate with GitHub API**: For a sample of conversations, query GitHub to confirm the interactions actually happened
2. **False positive detection**: Check if any "viewed" refs were actually modified via a different code path (e.g., API calls we don't detect)
3. **Time-based analysis**: Track how interaction patterns have changed over time (new CLI versions, etc.)
4. **Edge cases**: Analyze the ~1.4% of extracted refs that don't match - are they errors or legitimate misses?

### Adding New Patterns

To test a new pattern heuristic:

1. Add the pattern to `COMMAND_PATTERNS` in `experiments/analyze_interactions.py`
2. Add success indicators to `SUCCESS_PATTERNS` if needed
3. Run analysis on a large sample
4. Check failure cases manually to distinguish false negatives from actual failures
5. Update this spec with results

---

*This specification was created based on discussion in conversation 9f482a1aa53b4115a5e9c8e5ae32fb6c.*
