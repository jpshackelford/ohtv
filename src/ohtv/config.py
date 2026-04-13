"""Configuration management for ohtv.

Configuration hierarchy (highest priority first):
1. Environment variables
2. Config file (~/.ohtv/config.toml)
3. Defaults
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[import-not-found]


# Config keys that can be set via `ohtv config set`
CONFIGURABLE_KEYS = {
    "local_conversations_dir": "Path to local CLI conversations",
    "cloud_conversations_dir": "Path to synced cloud conversations", 
    "cloud_base_url": "OpenHands Cloud API URL",
    "source": "Default source: 'local' or 'cloud'",
}


@dataclass
class ConfigValue:
    """A configuration value with its source."""
    
    value: str | Path | None
    source: str  # "env", "file", "default"
    
    def __str__(self) -> str:
        if self.value is None:
            return "(not set)"
        return str(self.value)


@dataclass
class ConfigWithSources:
    """Configuration with source tracking for display."""
    
    local_conversations_dir: ConfigValue
    cloud_conversations_dir: ConfigValue
    cloud_base_url: ConfigValue
    api_key: ConfigValue
    source: ConfigValue
    ohtv_dir: ConfigValue
    manifest_path: Path
    config_file_path: Path


@dataclass
class Config:
    """Configuration for ohtv."""

    local_conversations_dir: Path
    cloud_conversations_dir: Path
    cloud_base_url: str
    api_key: str | None
    source: str  # "local" or "cloud"
    _sources: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables and config file."""
        home = Path.home()
        file_config = _load_config_file()
        sources: dict[str, str] = {}
        
        local_dir, local_src = _get_local_conversations_dir(home, file_config)
        cloud_dir, cloud_src = _get_cloud_conversations_dir(home, file_config)
        cloud_url, url_src = _get_cloud_base_url(file_config)
        source_val, source_src = _get_source(file_config)
        
        sources["local_conversations_dir"] = local_src
        sources["cloud_conversations_dir"] = cloud_src
        sources["cloud_base_url"] = url_src
        sources["source"] = source_src
        
        return cls(
            local_conversations_dir=local_dir,
            cloud_conversations_dir=cloud_dir,
            cloud_base_url=cloud_url,
            api_key=_get_api_key(home),
            source=source_val,
            _sources=sources,
        )
    
    def with_sources(self) -> ConfigWithSources:
        """Get configuration with source information for display."""
        home = Path.home()
        api_key = self.api_key
        api_source = "env" if os.environ.get("OH_API_KEY") else "file" if api_key else "default"
        
        ohtv_dir = get_ohtv_dir()
        ohtv_source = "env" if os.environ.get("OHTV_DIR") else "default"
        
        return ConfigWithSources(
            local_conversations_dir=ConfigValue(self.local_conversations_dir, self._sources.get("local_conversations_dir", "default")),
            cloud_conversations_dir=ConfigValue(self.cloud_conversations_dir, self._sources.get("cloud_conversations_dir", "default")),
            cloud_base_url=ConfigValue(self.cloud_base_url, self._sources.get("cloud_base_url", "default")),
            api_key=ConfigValue("****" if api_key else None, api_source),
            source=ConfigValue(self.source, self._sources.get("source", "default")),
            ohtv_dir=ConfigValue(ohtv_dir, ohtv_source),
            manifest_path=get_manifest_path(),
            config_file_path=get_config_file_path(),
        )


def _load_config_file() -> dict:
    """Load configuration from TOML file if it exists."""
    config_path = get_config_file_path()
    if not config_path.exists():
        return {}
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def _get_local_conversations_dir(home: Path, file_config: dict) -> tuple[Path, str]:
    """Get local conversations directory with source."""
    env_dir = os.environ.get("OHTV_CONVERSATIONS_DIR")
    if env_dir:
        return Path(env_dir).expanduser(), "env"
    file_dir = file_config.get("local_conversations_dir")
    if file_dir:
        return Path(file_dir).expanduser(), "file"
    return home / ".openhands" / "conversations", "default"


def _get_cloud_conversations_dir(home: Path, file_config: dict) -> tuple[Path, str]:
    """Get cloud conversations directory with source."""
    env_dir = os.environ.get("OHTV_CLOUD_CONVERSATIONS_DIR")
    if env_dir:
        return Path(env_dir).expanduser(), "env"
    file_dir = file_config.get("cloud_conversations_dir")
    if file_dir:
        return Path(file_dir).expanduser(), "file"
    return home / ".openhands" / "cloud" / "conversations", "default"


def _get_cloud_base_url(file_config: dict) -> tuple[str, str]:
    """Get cloud base URL with source."""
    env_url = os.environ.get("OHTV_CLOUD_URL")
    if env_url:
        return env_url, "env"
    file_url = file_config.get("cloud_base_url")
    if file_url:
        return file_url, "file"
    return "https://app.all-hands.dev", "default"


def _get_source(file_config: dict) -> tuple[str, str]:
    """Get default source with source tracking."""
    env_source = os.environ.get("OHTV_SOURCE")
    if env_source:
        return env_source, "env"
    file_source = file_config.get("source")
    if file_source:
        return file_source, "file"
    return "local", "default"


def _get_api_key(home: Path) -> str | None:
    """Get API key from env or file."""
    api_key = os.environ.get("OH_API_KEY")
    if api_key:
        return api_key
    key_file = home / ".openhands" / "cloud" / "api_key.txt"
    if key_file.exists():
        return key_file.read_text().strip()
    return None


def get_config_file_path() -> Path:
    """Get path to config file."""
    return get_ohtv_dir() / "config.toml"


def get_manifest_path() -> Path:
    """Get path to sync manifest file."""
    return get_ohtv_dir() / "sync_manifest.json"


def get_openhands_dir() -> Path:
    """Get the base OpenHands directory (~/.openhands).
    
    This is read-only for ohtv, except for sync which writes conversations.
    """
    return Path.home() / ".openhands"


def get_ohtv_dir() -> Path:
    """Get the ohtv data directory (~/.ohtv).
    
    All ohtv-generated data (database, cache, logs, sync manifest) is stored here.
    Can be overridden with OHTV_DIR environment variable.
    """
    env_dir = os.environ.get("OHTV_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".ohtv"


def save_config_value(key: str, value: str) -> None:
    """Save a configuration value to the config file.
    
    Args:
        key: Configuration key (must be in CONFIGURABLE_KEYS)
        value: Value to set
        
    Raises:
        ValueError: If key is not configurable
    """
    if key not in CONFIGURABLE_KEYS:
        raise ValueError(f"Unknown config key: {key}. Valid keys: {', '.join(CONFIGURABLE_KEYS)}")
    
    config_path = get_config_file_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing config
    existing = {}
    if config_path.exists():
        with open(config_path, "rb") as f:
            existing = tomllib.load(f)
    
    # Update value
    existing[key] = value
    
    # Write back as TOML
    _write_toml(config_path, existing)


def _write_toml(path: Path, data: dict) -> None:
    """Write dictionary to TOML file."""
    lines = ["# ohtv configuration", "# See 'ohtv config --help' for available settings", ""]
    for key, value in sorted(data.items()):
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    lines.append("")
    path.write_text("\n".join(lines))
