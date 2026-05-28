"""Sanity tests for the cloud-sync test harness itself (Issue #110).

These tests verify the fake behaves like the real ``CloudClient`` for the
slice of the protocol that ``sync.py`` consumes. They are NOT scenario tests
— they exist so future contributors can trust the fake before adding new
behavioral scenarios on top of it.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone

import pytest

from .builders import ConvFactory, make_trajectory_zip
from .fakes import FakeCloudClient, FakeConversation, SearchCall, UpdateCall


class TestMakeTrajectoryZip:
    """Builder produces zips the production exporter can read."""

    def test_zip_round_trips_via_zipfile(self):
        zip_bytes = make_trajectory_zip(conv_id="abc")
        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = sorted(zf.namelist())
            assert "meta.json" in names
            event_names = [n for n in names if n.startswith("event_")]
            assert len(event_names) == 1

    def test_custom_events_are_serialized_in_order(self):
        events = [
            {"id": "first", "kind": "MessageEvent"},
            {"id": "second", "kind": "ActionEvent"},
        ]
        zip_bytes = make_trajectory_zip(conv_id="x", events=events)
        import io
        import json

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            event_files = sorted(n for n in zf.namelist() if n.startswith("event_"))
            assert len(event_files) == 2
            first = json.loads(zf.read(event_files[0]))
            second = json.loads(zf.read(event_files[1]))
            assert first["id"] == "first"
            assert second["id"] == "second"

    def test_extra_files_land_at_specified_paths(self):
        zip_bytes = make_trajectory_zip(
            conv_id="x", extra_files={"notes/README.md": "hello"}
        )
        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert zf.read("notes/README.md") == b"hello"


class TestConvFactory:
    """The deterministic factory yields monotonically newer ids/timestamps."""

    def test_next_advances_id_counter(self):
        f = ConvFactory()
        a = f.next()
        b = f.next()
        assert a.id != b.id
        assert b.created_at > a.created_at

    def test_batch_returns_n_conversations(self):
        f = ConvFactory()
        batch = f.batch(10)
        assert len(batch) == 10
        assert len({c.id for c in batch}) == 10


class TestFakeCloudClientListing:
    """Listing surface matches CloudClient.search_* contracts."""

    def test_empty_listing_returns_empty_list(self, fake_cloud: FakeCloudClient):
        assert fake_cloud.search_all_conversations() == []

    def test_listing_returns_all_visible_conversations(
        self, fake_cloud: FakeCloudClient
    ):
        for i in range(3):
            fake_cloud.add(
                FakeConversation(
                    id=f"c{i}",
                    title=f"T{i}",
                    created_at=datetime(2024, 1, 1 + i, tzinfo=timezone.utc),
                )
            )
        items = fake_cloud.search_all_conversations()
        assert len(items) == 3
        assert {item["id"] for item in items} == {"c0", "c1", "c2"}

    def test_default_sort_is_created_at_desc(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(
            FakeConversation(id="old", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
        )
        fake_cloud.add(
            FakeConversation(id="new", created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
        )
        items = fake_cloud.search_all_conversations()
        assert [i["id"] for i in items] == ["new", "old"]

    def test_pagination_serves_one_page_per_page_size(
        self, fake_cloud: FakeCloudClient
    ):
        f = ConvFactory()
        for c in f.batch(7):
            fake_cloud.add(c)
        fake_cloud.set_page_size(3)
        items = fake_cloud.search_all_conversations()
        assert len(items) == 7

    def test_search_conversations_returns_next_page_id(
        self, fake_cloud: FakeCloudClient
    ):
        f = ConvFactory()
        for c in f.batch(5):
            fake_cloud.add(c)
        fake_cloud.set_page_size(2)
        page1, next_id = fake_cloud.search_conversations(limit=2)
        assert len(page1) == 2
        assert next_id is not None
        page2, next_id_2 = fake_cloud.search_conversations(limit=2, page_id=next_id)
        assert len(page2) == 2
        assert next_id_2 is not None
        page3, last = fake_cloud.search_conversations(limit=2, page_id=next_id_2)
        assert len(page3) == 1
        assert last is None

    def test_updated_since_filters_out_old_conversations(
        self, fake_cloud: FakeCloudClient
    ):
        fake_cloud.add(
            FakeConversation(id="old", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
        )
        fake_cloud.add(
            FakeConversation(id="new", updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
        )
        cutoff = datetime(2024, 3, 1, tzinfo=timezone.utc)
        items = fake_cloud.search_all_conversations(updated_since=cutoff)
        assert [i["id"] for i in items] == ["new"]

    def test_invisible_conversations_are_hidden_from_listing(
        self, fake_cloud: FakeCloudClient
    ):
        fake_cloud.add(FakeConversation(id="visible"))
        fake_cloud.add(FakeConversation(id="hidden", visible=False))
        items = fake_cloud.search_all_conversations()
        assert [i["id"] for i in items] == ["visible"]


class TestFakeCloudClientFailureInjection:
    """Failure-injection knobs surface the requested exceptions."""

    def test_fail_listing_at_page_raises_on_that_page(
        self, fake_cloud: FakeCloudClient
    ):
        f = ConvFactory()
        for c in f.batch(5):
            fake_cloud.add(c)
        fake_cloud.set_page_size(2)
        # Page boundaries: 1 (items 0-1), 2 (items 2-3), 3 (items 4)
        fake_cloud.fail_listing_at_page(2, RuntimeError("network blip"))
        with pytest.raises(RuntimeError, match="network blip"):
            fake_cloud.search_all_conversations()

    def test_fail_download_raises_for_that_conversation(
        self, fake_cloud: FakeCloudClient
    ):
        fake_cloud.add(FakeConversation(id="bad"))
        fake_cloud.fail_download("bad", RuntimeError("blob 500"))
        with pytest.raises(RuntimeError, match="blob 500"):
            fake_cloud.download_trajectory("bad")

    def test_mutate_between_pages_fires_once_per_boundary(
        self, fake_cloud: FakeCloudClient
    ):
        f = ConvFactory()
        for c in f.batch(4):
            fake_cloud.add(c)
        fake_cloud.set_page_size(2)

        boundary_count: list[int] = []

        def _bump(_client: FakeCloudClient) -> None:
            boundary_count.append(1)

        fake_cloud.mutate_between_pages(_bump)
        fake_cloud.search_all_conversations()
        # 4 conversations / page_size 2 = 2 pages = 1 boundary
        assert len(boundary_count) == 1


class TestFakeCloudClientDownloadAndCount:
    """Download + count match CloudClient semantics."""

    def test_download_returns_lazy_built_zip(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="abc", title="Foo"))
        zip_bytes = fake_cloud.download_trajectory("abc")
        # Same conversation, called twice — cache means same bytes object.
        assert fake_cloud.download_trajectory("abc") == zip_bytes

    def test_download_unknown_id_raises_lookup_error(
        self, fake_cloud: FakeCloudClient
    ):
        with pytest.raises(LookupError):
            fake_cloud.download_trajectory("nope")

    def test_count_only_counts_visible(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="v1"))
        fake_cloud.add(FakeConversation(id="v2"))
        fake_cloud.add(FakeConversation(id="h", visible=False))
        assert fake_cloud.count_conversations() == 2


class TestFakeCloudClientUpdateMetadata:
    """update_conversation mirrors CloudClient: keys-only-when-passed."""

    def test_no_op_when_neither_title_nor_tags(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="abc", title="Same"))
        fake_cloud.update_conversation("abc")
        assert fake_cloud.update_calls == []

    def test_title_update_mutates_store(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="abc", title="Old"))
        fake_cloud.update_conversation("abc", title="New")
        assert fake_cloud.store["abc"].title == "New"
        assert fake_cloud.update_calls == [
            UpdateCall(conversation_id="abc", title="New", tags=None)
        ]

    def test_tags_update_mutates_store(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="abc"))
        fake_cloud.update_conversation("abc", tags={"k": "v"})
        assert fake_cloud.store["abc"].tags == {"k": "v"}


class TestFakeCloudClientCallRecording:
    """Recording attributes are compatible with the legacy _RecordingCloudClient."""

    def test_search_calls_records_updated_since(self, fake_cloud: FakeCloudClient):
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
        fake_cloud.search_all_conversations(updated_since=cutoff)
        # _RecordingCloudClient API: list of updated_since values.
        assert fake_cloud.search_calls == [cutoff]
        # New richer log:
        assert fake_cloud.search_log == [
            SearchCall(
                method="search_all_conversations", updated_since=cutoff
            )
        ]

    def test_download_calls_record_conversation_ids(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="a"))
        fake_cloud.add(FakeConversation(id="b"))
        fake_cloud.download_trajectory("a")
        fake_cloud.download_trajectory("b")
        assert fake_cloud.download_calls == ["a", "b"]

    def test_close_is_idempotent_and_recorded(self, fake_cloud: FakeCloudClient):
        assert fake_cloud.closed is False
        fake_cloud.close()
        assert fake_cloud.closed is True
        fake_cloud.close()  # second close is a no-op
        assert fake_cloud.closed is True

    def test_context_manager_closes_on_exit(self):
        client = FakeCloudClient()
        with client as inner:
            assert inner is client
        assert client.closed is True


class TestBackdateAndVisibility:
    """The test-only knobs let scenarios construct adversarial cloud states."""

    def test_backdate_mutates_updated_at(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(
            FakeConversation(id="abc", updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
        )
        new_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        fake_cloud.backdate("abc", new_ts)
        assert fake_cloud.store["abc"].updated_at == new_ts

    def test_set_visible_toggles_listing_visibility(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="abc"))
        assert [i["id"] for i in fake_cloud.search_all_conversations()] == ["abc"]
        fake_cloud.set_visible("abc", False)
        assert fake_cloud.search_all_conversations() == []
        fake_cloud.set_visible("abc", True)
        assert [i["id"] for i in fake_cloud.search_all_conversations()] == ["abc"]

    def test_remove_simulates_cloud_side_delete(self, fake_cloud: FakeCloudClient):
        fake_cloud.add(FakeConversation(id="abc"))
        fake_cloud.remove("abc")
        assert fake_cloud.search_all_conversations() == []
        assert "abc" not in fake_cloud.store


class TestSyncManagerFactory:
    """The fixture wires the fake into a real SyncManager end-to-end."""

    def test_factory_returns_real_sync_manager(
        self, sync_manager_factory, fake_cloud: FakeCloudClient, tmp_path
    ):
        from ohtv.sync import SyncManager

        manager = sync_manager_factory(fake_cloud)
        assert isinstance(manager, SyncManager)
        assert manager.config.api_key == "test-key"
        assert manager.manifest_path == tmp_path / "sync_manifest.json"

    def test_sync_uses_fake_for_listing(
        self, sync_manager_factory, fake_cloud: FakeCloudClient
    ):
        fake_cloud.add(
            FakeConversation(
                id="abc",
                title="Hello",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )
        manager = sync_manager_factory(fake_cloud)
        result = manager.sync()
        assert result.new == 1
        # The fake recorded the listing call (initial sync passes
        # updated_since=None because the manifest has no last_sync_at).
        assert fake_cloud.search_calls == [None]
        assert fake_cloud.download_calls == ["abc"]


class TestSeededLocalState:
    """seeded_local_state lets tests start from a primed manifest."""

    def test_seeded_local_state_returns_manager_with_synced_data(
        self, seeded_local_state
    ):
        convs = [
            FakeConversation(
                id="abc",
                title="Hi",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ]
        manager = seeded_local_state(convs)
        assert "abc" in manager.manifest.conversations


def test_make_trajectory_zip_is_a_valid_zip_archive():
    """A trajectory built by the helper passes zipfile's integrity check."""
    blob = make_trajectory_zip(conv_id="probe")
    import io

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.testzip() is None
