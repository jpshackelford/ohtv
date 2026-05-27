"""Builders for cloud-sync test fixtures (Issue #110).

* :func:`make_trajectory_zip` — assemble a minimal-but-valid trajectory ZIP,
  promoted from the inline ``_create_minimal_zip()`` helper that previously
  lived at ``tests/unit/test_sync.py:465``. The signature is intentionally
  permissive so scenarios can override ``meta.json`` and append additional
  events without rewriting the helper.
* :class:`ConvFactory` — terse factory for :class:`FakeConversation`
  instances, useful when a test wants 50 conversations with a deterministic
  ``id`` / ``updated_at`` cadence without spelling each one out.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fakes import FakeConversation


_DEFAULT_CREATED = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    """Format a datetime as the cloud's canonical ISO-8601 ``...Z`` string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_trajectory_zip(
    *,
    conv_id: str = "test123",
    title: str = "Test",
    created_at: datetime | str | None = None,
    updated_at: datetime | str | None = None,
    selected_repository: str | None = None,
    selected_branch: str | None = None,
    events: list[dict] | None = None,
    base_state: dict | None = None,
    extra_files: dict[str, bytes | str] | None = None,
) -> bytes:
    """Assemble a minimal-but-valid trajectory ZIP for tests.

    Args:
        conv_id: Conversation id stamped into ``meta.json``.
        title: Conversation title stamped into ``meta.json``.
        created_at: Created timestamp. ``datetime`` instances are normalized to
            UTC ISO-8601 with a ``Z`` suffix; strings are stored verbatim.
            Defaults to 2024-01-01T00:00:00Z.
        updated_at: Updated timestamp. Same semantics as ``created_at``;
            defaults to whatever ``created_at`` ends up being.
        selected_repository: Optional repo to embed in ``meta.json``.
        selected_branch: Optional branch to embed in ``meta.json``.
        events: List of event dicts to write as ``event_NNNNNN_<id>.json``.
            Defaults to a single placeholder ``MessageEvent``.
        base_state: Optional ``base_state.json`` payload (Issue #87 metadata
            lives here for local CLI conversations and certain cloud paths).
        extra_files: Map of additional in-zip paths -> contents (bytes or
            str). Lets scenarios stash deliberately-broken files for
            negative tests without polluting the main API.

    Returns:
        The raw bytes of the ZIP.
    """
    created = created_at if created_at is not None else _DEFAULT_CREATED
    updated = updated_at if updated_at is not None else created
    created_str = created if isinstance(created, str) else _iso(created)
    updated_str = updated if isinstance(updated, str) else _iso(updated)

    meta: dict = {
        "id": conv_id,
        "title": title,
        "created_at": created_str,
        "updated_at": updated_str,
    }
    if selected_repository is not None:
        meta["selected_repository"] = selected_repository
    if selected_branch is not None:
        meta["selected_branch"] = selected_branch

    if events is None:
        events = [{"id": "abc", "kind": "MessageEvent"}]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("meta.json", json.dumps(meta))
        for i, event in enumerate(events, start=1):
            event_id = event.get("id", f"evt{i}")
            zf.writestr(f"event_{i:06d}_{event_id}.json", json.dumps(event))
        if base_state is not None:
            zf.writestr("base_state.json", json.dumps(base_state))
        for path, content in (extra_files or {}).items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(path, content)
    return buffer.getvalue()


@dataclass
class ConvFactory:
    """Tiny helper for generating deterministic ``FakeConversation`` batches.

    Each call to :meth:`next` advances the internal counter and timestamp by
    ``step`` so a single factory instance yields a monotonically-newer
    sequence of conversations. Useful for pagination scenarios that need 50
    conversations without 50 lines of boilerplate.
    """

    id_prefix: str = "conv"
    start_at: datetime = field(
        default_factory=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc)
    )
    step: timedelta = field(default_factory=lambda: timedelta(minutes=1))
    _counter: int = 0

    def next(  # noqa: A003 — terse method name matches the iterator vocabulary
        self,
        *,
        title: str | None = None,
        updated_at: datetime | None = None,
        **kwargs,
    ) -> "FakeConversation":
        """Return the next deterministic :class:`FakeConversation`."""
        from .fakes import FakeConversation

        idx = self._counter
        self._counter += 1
        conv_id = f"{self.id_prefix}{idx:04d}"
        created = self.start_at + self.step * idx
        upd = updated_at if updated_at is not None else created
        return FakeConversation(
            id=conv_id,
            title=title or f"Conversation {idx}",
            created_at=created,
            updated_at=upd,
            **kwargs,
        )

    def batch(self, n: int) -> list["FakeConversation"]:
        """Return ``n`` consecutive conversations."""
        return [self.next() for _ in range(n)]
