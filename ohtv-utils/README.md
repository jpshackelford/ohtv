# ohtv-utils

Lightweight utilities for extracting content from OpenHands conversation events.

## Overview

`ohtv-utils` provides battle-tested, token-efficient extraction utilities for working with OpenHands conversation events. These utilities were extracted from the [ohtv](https://github.com/jpshackelford/ohtv) project and can be used independently without requiring the full ohtv sync infrastructure.

## Features

- **Zero dependencies** - Uses only Python standard library
- **Lightweight** - ~50KB installed
- **Battle-tested** - Extracted from production ohtv codebase
- **Type-safe** - Full type hints for Python 3.12+

## Installation

```bash
pip install ohtv-utils
```

## Usage

### Message Extraction

```python
from ohtv_utils.extraction import extract_message_content, extract_action_summary

# Process events from API
response = api_request(f"/conversation/{conv_id}/events/search?limit=100")
events = response['items']

# Extract messages
user_messages = [
    extract_message_content(e)
    for e in events
    if e.get('kind') == 'MessageEvent' and e.get('source') == 'user'
]
```

### Reference Extraction

```python
from ohtv_utils.extraction import parse_repo_url, parse_ref_url

# Parse repository URL
repo = parse_repo_url("https://github.com/owner/repo")
# Returns: {"canonical_url": "https://github.com/owner/repo", "fqn": "owner/repo", "short_name": "repo"}

# Parse PR URL
pr = parse_ref_url("https://github.com/owner/repo/pull/123", "pr")
# Returns: {"ref_type": "pr", "url": "...", "fqn": "owner/repo#123", "display_name": "repo #123"}
```

### Engagement Metrics

```python
from ohtv_utils.metrics import compute_engagement

# Compute engagement score
engagement = compute_engagement(events)
print(f"Engaged: {engagement.engaged_seconds}s over {engagement.attention_periods} periods")
```

### Human Input Counting

```python
from ohtv_utils.metrics import count_human_input

# Count user messages and words
metrics = count_human_input(events)
print(f"Initial prompt: {metrics.initial_prompt_words} words")
print(f"Follow-ups: {metrics.followup_message_count} messages, {metrics.followup_word_count} words")
```

## API Reference

### extraction.messages

- `extract_message_content(event, include_critic=False)` - Extract text from MessageEvent
- `extract_action_summary(event, include_command=False)` - Extract summary from ActionEvent
- `extract_observation_content(event, max_length=800)` - Extract content from ObservationEvent

### extraction.refs

- `parse_repo_url(url)` - Parse repository URL into dict
- `parse_ref_url(url, ref_type)` - Parse issue/PR URL into dict

### metrics.engagement

- `compute_engagement(events, threshold_seconds=720, sustained_attention_seconds=3600)` - Compute engagement metrics
- `EngagementMetrics` - Dataclass with engagement results

### metrics.human_input

- `count_human_input(events)` - Count human messages and words
- `HumanInputMetrics` - Dataclass with word/message counts

## Requirements

- Python 3.12 or later
- No external dependencies

## License

MIT License - see LICENSE file for details

## Contributing

This package is extracted from [ohtv](https://github.com/jpshackelford/ohtv). Contributions should be made to the ohtv repository.
