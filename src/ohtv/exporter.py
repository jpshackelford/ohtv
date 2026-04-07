"""Export cloud trajectories to local format."""

import json
import re
import zipfile
from io import BytesIO
from pathlib import Path


class TrajectoryExporter:
    """Convert cloud trajectory format to local CLI format."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def export_from_zip_bytes(self, conversation_id: str, zip_bytes: bytes) -> Path:
        """Export trajectory from zip bytes to local format."""
        conv_dir = self.output_dir / conversation_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        events_dir = conv_dir / "events"
        events_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                self._process_zip_entry(zf, name, conv_dir, events_dir)

        return conv_dir

    def _process_zip_entry(
        self,
        zf: zipfile.ZipFile,
        name: str,
        conv_dir: Path,
        events_dir: Path,
    ) -> None:
        """Process a single entry from the zip file."""
        if name == "meta.json":
            self._convert_meta(zf.read(name), conv_dir)
        elif name.startswith("event_"):
            self._convert_event(zf.read(name), name, events_dir)

    def _convert_meta(self, content: bytes, conv_dir: Path) -> None:
        """Convert meta.json to base_state.json."""
        meta = json.loads(content)
        base_state = _meta_to_base_state(meta)
        (conv_dir / "base_state.json").write_text(json.dumps(base_state, indent=2))

    def _convert_event(self, content: bytes, name: str, events_dir: Path) -> None:
        """Convert cloud event file to local format."""
        new_name = _convert_event_filename(name)
        (events_dir / new_name).write_bytes(content)


def _meta_to_base_state(meta: dict) -> dict:
    """Convert cloud meta.json to local base_state.json format."""
    return {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "selected_repository": meta.get("selected_repository"),
        "selected_branch": meta.get("selected_branch"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "agent": {
            "llm": {"model": meta.get("llm_model", "unknown")},
            "tools": [],
        },
    }


def _convert_event_filename(cloud_name: str) -> str:
    """Convert cloud filename to local format.
    
    event_000042_abc123.json -> event-00042-abc123.json
    """
    match = re.match(r"event_(\d{6})_(.+)\.json", cloud_name)
    if match:
        seq = int(match.group(1))
        uuid = match.group(2)
        return f"event-{seq:05d}-{uuid}.json"
    return cloud_name


def count_events(conv_dir: Path) -> int:
    """Count events in a local conversation directory."""
    events_dir = conv_dir / "events"
    if not events_dir.exists():
        return 0
    return len(list(events_dir.glob("event-*.json")))
