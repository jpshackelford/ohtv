"""Pytest fixtures for the cloud-sync behavioral harness (Issue #110).

These fixtures wire :class:`FakeCloudClient` into ``ohtv.sync.SyncManager``
so the scenario suite can exercise real ``sync()`` / ``update_metadata()`` /
``repair()`` code paths against an in-memory cloud.

Two integration patterns are supported:

1. **Direct injection** — for ``update_metadata(client=...)``, the API already
   accepts a client kwarg, so tests just pass the fake.
2. **Import-site patching** — for ``sync()`` and ``repair()``, which still
   instantiate :class:`CloudClient` themselves via ``with CloudClient(...)``,
   the :func:`sync_manager_factory` fixture monkeypatches
   ``ohtv.sync.CloudClient`` to return the fake. **This patch is the
   temporary bridge that Issue #111 retires** by making ``sync()`` accept
   ``client=None``. Once #111 lands, the patch can be dropped and the
   fixture simplified.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from .builders import ConvFactory
from .fakes import FakeCloudClient, FakeConversation

if TYPE_CHECKING:
    from ohtv.sync import SyncManager


@pytest.fixture
def fake_cloud() -> FakeCloudClient:
    """A fresh empty :class:`FakeCloudClient` for the test to populate."""
    return FakeCloudClient()


@pytest.fixture
def conv_factory() -> ConvFactory:
    """A fresh :class:`ConvFactory` for batch conversation generation."""
    return ConvFactory()


@pytest.fixture
def sync_manager_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., "SyncManager"]:
    """Build a :class:`SyncManager` wired to the supplied fake cloud client.

    The factory:

    * Routes ``synced_conversations_dir`` under ``tmp_path``.
    * Patches ``ohtv.sync.get_manifest_path`` to point at ``tmp_path``.
    * Monkeypatches ``ohtv.sync.CloudClient`` so the ``with
      CloudClient(...)`` blocks inside ``sync()`` and ``repair()`` yield
      the fake. **Temporary** — Issue #111 makes ``sync()`` accept
      ``client=None``, at which point this patch becomes unnecessary.

    Usage::

        def test_initial_sync(sync_manager_factory, fake_cloud, conv_factory):
            fake_cloud.add(conv_factory.next())
            manager = sync_manager_factory(fake_cloud)
            result = manager.sync()
            assert result.new == 1
    """
    from ohtv.sync import SyncManager

    def _factory(
        cloud: FakeCloudClient,
        *,
        api_key: str = "test-key",
        cloud_api_url: str = "https://example.test",
    ) -> SyncManager:
        config = MagicMock()
        config.api_key = api_key
        config.cloud_api_url = cloud_api_url
        config.synced_conversations_dir = tmp_path / "synced"
        config.local_conversations_dir = tmp_path / "local"
        config.extra_conversation_paths = []

        manifest_path = tmp_path / "sync_manifest.json"
        monkeypatch.setattr(
            "ohtv.sync.get_manifest_path", lambda: manifest_path
        )

        # The import-site patch is the bridge until #111 lands.
        # ``CloudClient(...)`` is the production-code constructor call; we
        # discard the (base_url, api_key) args and hand back the
        # already-built fake so the ``with`` block sees a working
        # context manager.
        monkeypatch.setattr(
            "ohtv.sync.CloudClient", lambda *_a, **_kw: cloud
        )

        return SyncManager(config)

    return _factory


@pytest.fixture
def seeded_local_state(
    tmp_path: Path,
    fake_cloud: FakeCloudClient,
    sync_manager_factory: Callable[..., "SyncManager"],
) -> Callable[[Iterable[FakeConversation]], "SyncManager"]:
    """Seed paired local+cloud state and return a wired :class:`SyncManager`.

    Given an iterable of :class:`FakeConversation` to register on the cloud,
    runs an initial ``sync()`` so the manifest and on-disk state mirror the
    cloud. Returns the manager so the test can immediately mutate the cloud
    and call ``sync()`` again to exercise an incremental scenario.
    """

    def _seed(conversations: Iterable[FakeConversation]) -> "SyncManager":
        for c in conversations:
            fake_cloud.add(c)
        manager = sync_manager_factory(fake_cloud)
        manager.sync()
        return manager

    return _seed
