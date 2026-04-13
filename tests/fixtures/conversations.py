"""Fixtures for conversation test data.

Provides functions to load sample conversations and set up test directories.
"""

import json
import shutil
from pathlib import Path
from typing import Iterator

from fixtures import CONVERSATIONS_DIR


def get_sample_conversation_path(name: str) -> Path:
    """Get path to a sample conversation in the fixtures directory.
    
    Args:
        name: Name of the conversation directory (e.g., "conv-with-github-refs")
        
    Returns:
        Path to the conversation directory
        
    Raises:
        FileNotFoundError: If the conversation doesn't exist
    """
    path = CONVERSATIONS_DIR / name
    if not path.exists():
        available = [p.name for p in CONVERSATIONS_DIR.iterdir() if p.is_dir()]
        raise FileNotFoundError(
            f"Sample conversation '{name}' not found. Available: {available}"
        )
    return path


def copy_conversation_to(name: str, dest: Path) -> Path:
    """Copy a sample conversation to a destination directory.
    
    Args:
        name: Name of the sample conversation
        dest: Destination directory (will be created if needed)
        
    Returns:
        Path to the copied conversation directory
    """
    src = get_sample_conversation_path(name)
    conv_dest = dest / name
    shutil.copytree(src, conv_dest)
    return conv_dest


def load_base_state(conv_path: Path) -> dict:
    """Load base_state.json from a conversation directory."""
    return json.loads((conv_path / "base_state.json").read_text())


def load_events(conv_path: Path) -> list[dict]:
    """Load all events from a conversation directory, sorted by filename."""
    events_dir = conv_path / "events"
    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        events.append(json.loads(event_file.read_text()))
    return events


def iter_events(conv_path: Path) -> Iterator[dict]:
    """Iterate over events in a conversation directory, sorted by filename."""
    events_dir = conv_path / "events"
    for event_file in sorted(events_dir.glob("event-*.json")):
        yield json.loads(event_file.read_text())
