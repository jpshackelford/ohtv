# Orchestration Hints

Project-specific configuration for the generic pr-workflow orchestrator.

## Project

- Repository: jpshackelford/ohtv
- Type: cli

## Automation

- ID: c202ca20-60d5-4f5b-9d53-3d7308c1d95b
- Quiet threshold: 2

## Setup Commands

```bash
# Install tkt if not available
which tkt || uv tool install git+https://github.com/jpshackelford/tickster

# Add repo to tkt board
tkt repo add jpshackelford/ohtv 2>/dev/null || true

# Sync conversation history for ohtv commands (optional - only needed if testing ohtv itself)
# uv run ohtv sync -n 20
```

## Phases

- Issue expansion: enabled
- Priority assessment: enabled
- Manual testing: required
- Self-review: enabled
- Docs update before testing: enabled

## Plugin Source

github:jpshackelford/.openhands/plugins/pr-workflow@main

## Project-Specific Notes

### Manual Testing Requirements

This project requires CLI-based blackbox testing for all PRs. The `/manual-test` skill
in `.agents/skills/manual-test.md` defines the ohtv-specific testing procedure.

**Key requirements:**
- All tests MUST go through the CLI (`uv run ohtv ...`), not Python imports
- Conversation data sync may be needed before testing (`uv run ohtv sync -n 20`)
- README examples must be verified as part of testing
- Unit tests must pass (`uv run pytest tests/ -v`)

### Documentation Updates

Documentation must be updated BEFORE manual testing:
- README.md should reflect any new commands, flags, or behavior changes
- Manual testers will verify README examples work correctly
