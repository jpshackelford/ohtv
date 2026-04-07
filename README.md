# ohtv - OpenHands Trajectory Viewer

CLI tool for viewing and syncing OpenHands conversation histories.

## Installation

```bash
uv pip install -e .
# or
pip install -e .
```

## Usage

### Sync Cloud Conversations

```bash
# Set your API key
export OH_API_KEY=your_api_key

# Sync all conversations (incremental - only downloads changes)
ohtv sync

# Force re-download everything
ohtv sync --force

# Dry run - show what would sync
ohtv sync --dry-run

# Check sync status
ohtv sync --status

# Quiet mode for cron jobs
ohtv sync --quiet
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OH_API_KEY` | OpenHands Cloud API key | Required for cloud operations |
| `OHTV_CLOUD_URL` | Cloud base URL | `https://app.all-hands.dev` |
| `OHTV_CONVERSATIONS_DIR` | Local conversations directory | `~/.openhands/conversations` |
| `OHTV_CLOUD_CONVERSATIONS_DIR` | Downloaded cloud conversations | `~/.openhands/cloud/conversations` |

## Storage

Downloaded cloud conversations are stored separately from CLI-generated conversations:

```
~/.openhands/
├── conversations/              # Local CLI conversations
└── cloud/
    ├── api_key.txt            # Cloud API key (optional)
    ├── sync_manifest.json     # Sync state tracking
    ├── logs/
    │   └── ohtv.log           # Application log (rotated, 1MB max)
    └── conversations/          # Downloaded cloud conversations
```

## Logging

Logs are written to `~/.openhands/cloud/logs/ohtv.log`:
- Rotates at 1MB, keeps 3 backups
- Use `-v/--verbose` to also print debug output to console
