"""Configuration management for ohtv."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    """Configuration for ohtv."""

    local_conversations_dir: Path
    cloud_conversations_dir: Path
    cloud_base_url: str
    api_key: str | None
    source: str  # "local" or "cloud"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        home = Path.home()
        return cls(
            local_conversations_dir=_get_local_conversations_dir(home),
            cloud_conversations_dir=_get_cloud_conversations_dir(home),
            cloud_base_url=os.environ.get("OHTV_CLOUD_URL", "https://app.all-hands.dev"),
            api_key=_get_api_key(home),
            source=os.environ.get("OHTV_SOURCE", "local"),
        )


def _get_local_conversations_dir(home: Path) -> Path:
    """Get local conversations directory from env or default."""
    env_dir = os.environ.get("OHTV_CONVERSATIONS_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return home / ".openhands" / "conversations"


def _get_cloud_conversations_dir(home: Path) -> Path:
    """Get cloud conversations directory from env or default."""
    env_dir = os.environ.get("OHTV_CLOUD_CONVERSATIONS_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return home / ".openhands" / "cloud" / "conversations"


def _get_api_key(home: Path) -> str | None:
    """Get API key from env or file."""
    api_key = os.environ.get("OH_API_KEY")
    if api_key:
        return api_key
    key_file = home / ".openhands" / "cloud" / "api_key.txt"
    if key_file.exists():
        return key_file.read_text().strip()
    return None


def get_manifest_path() -> Path:
    """Get path to sync manifest file."""
    return Path.home() / ".openhands" / "cloud" / "sync_manifest.json"
