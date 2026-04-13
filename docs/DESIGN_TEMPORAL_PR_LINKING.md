# Design: Temporal Push-to-PR Linking

## Overview

This document describes the design for implementing temporal-aware push-to-PR linking. The current implementation links pushes to PRs based on branch name matching, but doesn't account for temporal ordering. This causes issues when:

1. Pushes occur before the PR is created
2. The same branch is reused for multiple PRs over time

## Current State

### What We Have

```
Stage ordering: refs → actions → branch_context → push_pr_links
```

- **`branch_context`**: Creates branch refs from GIT_PUSH actions, links conversations to branches
- **`push_pr_links`**: Builds a map of `owner/repo:branch → PR URL` and links pushes to PRs

### Current Limitations

1. **Map-based approach loses temporal info**: Building `{branch: PR}` map from all OPEN_PR actions means all pushes link to the last PR for that branch

2. **No backward linking**: Pushes before PR creation don't link because PR doesn't exist yet when building the map

### Test Scenarios Documenting These Issues

From `tests/unit/db/stages/fixtures/push_pr_scenarios.py`:

- `SCENARIO_PUSH_BEFORE_PR` - Push → Push → PR → Push (only last push links)
- `SCENARIO_BRANCH_REUSE` - PR1 → Push → PR2 → Push (both link to PR2)

## Proposed Solution

### Core Insight

Process events in temporal order, maintaining "active PR" state per branch:

```python
branch_active_pr: dict[str, str] = {}  # branch_key → pr_url

for action in actions_ordered_by_event_id:
    if action.type == OPEN_PR:
        # This PR becomes active for this branch
        branch_active_pr[branch_key] = action.target
        
    elif action.type == GIT_PUSH:
        # Link to currently active PR (if any)
        active_pr = branch_active_pr.get(branch_key)
        if active_pr:
            link(action, active_pr)
```

### Two-Pass Approach for Pre-PR Pushes

The simple forward pass doesn't handle pushes BEFORE PR creation. We need a second pass:

```
Pass 1 (Forward): Link pushes to active PR
Pass 2 (Backward): Link orphan pushes to first subsequent PR on same branch
```

Example:
```
Event 1: Push branch-A  (orphan - no PR yet)
Event 2: Push branch-A  (orphan - no PR yet)
Event 3: PR created for branch-A  ← Pass 1 records this
Event 4: Push branch-A  ← Pass 1 links to PR
[End of events]
← Pass 2: Link events 1,2 to the PR from event 3
```

### Implementation Plan

#### Phase 1: Temporal Forward Linking

Modify `push_pr_links.py`:

```python
def process_push_pr_links(conn, conversation):
    actions = action_store.get_by_conversation(conversation.id)  # ordered by id
    
    # Track active PR per branch (temporal state)
    branch_active_pr: dict[str, str] = {}
    
    # Track pushes that couldn't be linked (for pass 2)
    orphan_pushes: list[tuple[ConversationAction, str]] = []  # (action, branch_key)
    
    for action in actions:
        branch_key = _make_branch_key(action)
        if not branch_key:
            continue
            
        if action.action_type == ActionType.OPEN_PR:
            branch_active_pr[branch_key] = action.target
            
        elif action.action_type == ActionType.GIT_PUSH:
            pr_url = branch_active_pr.get(branch_key)
            if pr_url:
                _link_push_to_pr(action, pr_url, ref_store, link_store)
            else:
                orphan_pushes.append((action, branch_key))
    
    # Pass 2: Link orphan pushes to first PR on their branch
    _link_orphan_pushes(orphan_pushes, branch_active_pr, ref_store, link_store)
```

#### Phase 2: Store Temporal Branch State (Optional)

If we need richer temporal queries later, store branch transitions:

```sql
CREATE TABLE branch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- 'push', 'pr_create', 'checkout'
    owner TEXT NOT NULL,
    repo TEXT NOT NULL,
    branch TEXT NOT NULL,
    pr_url TEXT,  -- NULL for pushes, set for PR creates
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
```

This would enable queries like:
- "What PRs were created for this branch in this conversation?"
- "What was the active PR when this push happened?"

#### Phase 3: Branch Context Tracking (Future)

Track `git checkout` commands to know current branch even when `git push` doesn't specify it:

```python
# In branch_context processor
current_branch: dict[str, str] = {}  # repo_path → branch

for action in actions:
    if is_checkout_command(action):
        repo_path, branch = extract_checkout_info(action)
        current_branch[repo_path] = branch
        
    elif action.type == GIT_PUSH:
        if not action.metadata.get("branch"):
            # Infer from tracked state
            action.metadata["branch"] = current_branch.get(repo_path)
```

## Testing Strategy

### Unit Tests

Use the fixtures in `tests/unit/db/stages/fixtures/push_pr_scenarios.py`:

```python
def test_temporal_forward_linking():
    """Pushes after PR creation link correctly."""
    # Use SCENARIO_SIMPLE_SINGLE_BRANCH
    
def test_orphan_push_backward_linking():
    """Pushes before PR creation link to subsequent PR."""
    # Use SCENARIO_PUSH_BEFORE_PR
    
def test_branch_reuse_temporal():
    """Multiple PRs on same branch link pushes to correct PR."""
    # Use SCENARIO_BRANCH_REUSE
```

### Integration Tests

Process real conversation data and verify:
1. Branch refs created for all pushed branches
2. Pushes correctly linked to PRs
3. `refs` command shows correct annotations

## Migration Path

1. **No schema migration needed** - Uses existing tables
2. **Reprocessing required** - Run `ohtv db process push_pr_links --force` after upgrade
3. **Backward compatible** - New behavior is strictly better (links more correctly)

## Open Questions

1. **Should orphan pushes link at all?** 
   - Pro: Captures work that led to the PR
   - Con: May link unrelated pushes if branch was reused before PR
   - Decision: Link with a different link type (e.g., `CONTRIBUTED`) vs `WRITE`?

2. **Handle PR close/merge events?**
   - When PR is merged, should we stop linking new pushes to it?
   - Probably yes - need to track PR state transitions

3. **Cross-conversation branch reuse?**
   - Same branch in different conversations → different PRs
   - Current: Each conversation is isolated (correct)
   - Future: Track across conversations for "PR history"?

## Success Criteria

- [x] All 7 test scenarios pass with correct linking (16 tests in test_push_pr_links.py)
- [x] Real conversation `a711cbbc61f0` shows pushes linked to correct PRs (all 6 PRs have WRITE links)
- [ ] `refs` command shows push annotations on PRs (display not yet updated to use DB links)
- [x] No regression in existing tests (216 tests passing)

## References

- `tests/unit/db/stages/fixtures/push_pr_scenarios.py` - Test scenarios
- `src/ohtv/db/stages/push_pr_links.py` - Current implementation
- `src/ohtv/db/stages/branch_context.py` - Branch tracking
- Conversation `a711cbbc61f0` - Real multi-PR conversation for testing
