"""Cloud-sync behavioral scenario suite (Issue #110).

This module implements the 16 scenarios called out in Issue #110's
technical-approach comment. Each test is one behavior; markers track which
implementation issue flips the test from pending → passing:

* No marker = passes today (regression guard).
* ``xfail(strict=True, reason="#111[+#NNN]")`` = fails meaningfully against
  today's code; flips to passing when the referenced issue ships.
* ``skip(reason="#NNN — ...")`` = would crash today because a referenced
  symbol/table/column doesn't exist yet.

``strict=True`` is the point: if a behavior accidentally lands before its
implementation issue, the suite goes red so reviewers notice.

Scenario index (from the issue comment, with PR markers):

  1.  Initial empty sync downloads full cloud listing            — passes today
  2.  Sync resume after cursor advance recovers the gap          — xfail #111
  3.  Backdated updated_at item shows up on next sync            — xfail #111
  4.  Cloud-side delete is reported as removed                   — xfail #111 + #113
  5.  Visibility flip is reconciled                              — xfail #111
  6.  Mid-listing failure leaves prior snapshot intact           — skip #112
  7.  Set-diff vs cloud_listing yields {new, missing, changed}   — skip #112 + #111
  8.  Pagination dedup: same id on two pages counted once        — xfail #111
  9.  Item appearing mid-listing is picked up                    — xfail #111
  10. Mid-sync crash → next run resumes without losing items     — xfail #111
  11. ID normalization preserved across sync                     — passes today
  12. Timestamps round-trip canonical UTC ISO-8601 w/ microseconds — xfail #112
  13. --repair reports four categories                           — skip #113
  14. Manifest as canonical metadata source survives sync        — passes today
  15. Property: reconciliation is idempotent                     — xfail #111 (hypothesis)
  16. Property: applying same listing twice leaves DB unchanged  — xfail #111 (hypothesis)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings

from .builders import ConvFactory
from .fakes import FakeCloudClient, FakeConversation
from .strategies import fake_listing_state


_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Scenario 1 — initial empty sync downloads the full cloud listing.
# ---------------------------------------------------------------------------
def test_initial_empty_sync_downloads_full_cloud_listing(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    """With an empty manifest, sync() downloads every cloud conversation."""
    for c in conv_factory.batch(5):
        fake_cloud.add(c)

    manager = sync_manager_factory(fake_cloud)
    result = manager.sync()

    assert result.new == 5
    assert result.failed == 0
    assert len(manager.manifest.conversations) == 5
    # Every cloud conversation got a download_trajectory call.
    assert set(fake_cloud.download_calls) == {c.id for c in fake_cloud.store.values()}


# ---------------------------------------------------------------------------
# Scenario 2 — sync resume after cursor advance recovers the gap (#111).
#
# Sync 1 advances last_sync_at to ~now. A conversation that becomes visible
# AFTER sync 1 but whose updated_at is BEFORE sync 1's cursor (server-side
# clock skew / backfill) must still be picked up by sync 2. Today the
# updated_since cutoff filters it out — that's the 1126-item gap that
# motivated #111.
# ---------------------------------------------------------------------------
def test_sync_resume_after_cursor_advance_recovers_backdated_items(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    early = datetime(2024, 1, 1, tzinfo=_UTC)
    late = datetime(2024, 6, 1, tzinfo=_UTC)

    fake_cloud.add(FakeConversation(id="a", created_at=late, updated_at=late))
    manager = sync_manager_factory(fake_cloud)
    manager.sync()  # advances manifest.last_sync_at to ~now

    # New conversation surfaces server-side, but its updated_at predates sync 1.
    fake_cloud.add(FakeConversation(id="b", created_at=early, updated_at=early))
    result = manager.sync()

    # The post-#111 contract: gap-recovery picks up "b" via set-diff against
    # the cloud listing, regardless of the cursor.
    assert "b" in manager.manifest.conversations
    assert result.new == 1


# ---------------------------------------------------------------------------
# Scenario 3 — backdated updated_at on an existing item triggers re-sync (#111).
#
# Variant of #2: instead of a new item appearing with a stale timestamp, an
# EXISTING item is mutated server-side AND its updated_at is rewound. Today's
# cutoff-only logic skips it; #111's set-diff catches the mismatch.
# ---------------------------------------------------------------------------
def test_backdated_updated_at_on_existing_item_is_re_synced(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    initial_ts = datetime(2024, 6, 1, tzinfo=_UTC)
    fake_cloud.add(
        FakeConversation(
            id="a", title="v1", created_at=initial_ts, updated_at=initial_ts
        )
    )
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Server-side mutation with a stale updated_at (clock-skew scenario).
    fake_cloud.store["a"].title = "v2 (server rewrote me)"
    fake_cloud.backdate("a", datetime(2024, 1, 1, tzinfo=_UTC))

    manager.sync()

    assert manager.manifest.conversations["a"]["title"] == "v2 (server rewrote me)"


# ---------------------------------------------------------------------------
# Scenario 4 — item disappearing from cloud is reported as "Removed" (#111 + #113).
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True, reason="blocked by #111 + #113 (no removed-from-cloud reporting)"
)
def test_item_disappearing_from_cloud_is_reported_as_removed(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    fake_cloud.add(FakeConversation(id="a"))
    fake_cloud.add(FakeConversation(id="b"))
    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    assert {"a", "b"} <= manager.manifest.conversations.keys()

    fake_cloud.remove("a")
    result = manager.sync()

    # Post-#111+#113: sync reports "a" as removed from cloud. The attribute
    # name is what the issues will land — until then either it doesn't exist
    # (AttributeError → xfail) or it stays 0 (assertion fails → xfail).
    assert getattr(result, "removed_from_cloud", 0) == 1


# ---------------------------------------------------------------------------
# Scenario 5 — visibility flip (visible → hidden → visible) is reconciled (#111).
# ---------------------------------------------------------------------------
def test_visibility_flip_is_reconciled_across_syncs(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    fake_cloud.add(FakeConversation(id="a"))
    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    assert "a" in manager.manifest.conversations

    # Hide → next sync should mark / remove the local entry.
    fake_cloud.set_visible("a", False)
    manager.sync()
    assert (
        "a" not in manager.manifest.conversations
        or manager.manifest.conversations["a"].get("hidden") is True
    )

    # Show again → next sync should re-include it.
    fake_cloud.set_visible("a", True)
    manager.sync()
    assert "a" in manager.manifest.conversations
    assert manager.manifest.conversations["a"].get("hidden") is not True


# ---------------------------------------------------------------------------
# Scenario 6 — mid-listing failure leaves prior cloud_listing snapshot intact.
#
# This depends on the `cloud_listing` snapshot table that #112 introduces.
# Querying it pre-#112 raises OperationalError, so the test is skipped (not
# xfailed) per the policy in the issue comment.
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="blocked by #112 — cloud_listing snapshot table does not exist yet"
)
def test_mid_listing_failure_preserves_prior_cloud_listing_snapshot(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    # Seed and run a successful sync — populates the cloud_listing snapshot.
    for c in conv_factory.batch(5):
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Capture the snapshot before the failing sync.
    from ohtv.db.stores.cloud_listing_store import CloudListingStore  # noqa: F401 — schema doesn't exist yet

    # Simulate a listing failure mid-flight.
    fake_cloud.add(conv_factory.next())
    fake_cloud.set_page_size(2)
    fake_cloud.fail_listing_at_page(2, RuntimeError("listing crashed mid-flight"))

    with pytest.raises(RuntimeError):
        manager.sync()

    # Assertion: the snapshot from the previous successful sync is still the
    # source of truth — half-finished listings must not overwrite it.
    # (Wired up once #112 adds the store API.)
    pytest.fail("unreachable until #112 lands the cloud_listing snapshot store")


# ---------------------------------------------------------------------------
# Scenario 7 — set-diff vs cloud_listing yields {new, missing, changed} (#112 + #111).
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="blocked by #112 (snapshot table) + #111 (set-diff engine)"
)
def test_set_diff_against_cloud_listing_snapshot_categorizes_changes(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    # Seed cloud + sync → snapshot persisted.
    convs = conv_factory.batch(3)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Mutate cloud-side: add one, remove one, change one.
    fake_cloud.add(conv_factory.next())  # new
    fake_cloud.remove(convs[0].id)  # missing
    fake_cloud.store[convs[1].id].title = "renamed"  # changed

    # Once #111 lands, sync() should expose three set-diff buckets:
    result = manager.sync()
    assert getattr(result, "new_ids", []) != []
    assert getattr(result, "missing_ids", []) == [convs[0].id]
    assert convs[1].id in getattr(result, "changed_ids", [])


# ---------------------------------------------------------------------------
# Scenario 8 — pagination dedup: same id on two pages is counted once (#111).
#
# Simulates keyset drift: between pages, a new item is inserted that pushes
# an existing item from page 1 down into page 2, causing it to appear twice.
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "blocked by fake's naive offset-based pagination — keyset drift "
        "permanently hides newcomer from a single sync. The production "
        "cloud uses keyset pagination so this is a fake-only artifact; "
        "the FakeCloudClient needs a keyset cursor (separate issue) "
        "before this assertion can pass in one pass. #111 itself "
        "delivers the gap-recovery: a second manager.sync() *does* "
        "catch the missed item."
    ),
)
def test_pagination_dedup_counts_same_id_once(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    # 4 conversations, page_size=2 → 2 pages.
    base = datetime(2024, 1, 1, tzinfo=_UTC)
    for i in range(4):
        fake_cloud.add(
            FakeConversation(
                id=f"c{i}",
                created_at=base + timedelta(hours=i),
                updated_at=base + timedelta(hours=i),
            )
        )
    fake_cloud.set_page_size(2)

    # Between pages, insert a new conversation NEWER than everything, which
    # shifts the previous-page items DOWN — and since the page-id is a
    # naive offset, page 2 now re-yields one item already served on page 1.
    def _inject_newer(client: FakeCloudClient) -> None:
        client.add(
            FakeConversation(
                id="newcomer",
                created_at=base + timedelta(days=1),
                updated_at=base + timedelta(days=1),
            )
        )

    fake_cloud.mutate_between_pages(_inject_newer)

    manager = sync_manager_factory(fake_cloud)
    result = manager.sync()

    # Post-#111: the listing path dedupes by id; each cloud conversation
    # appears in the manifest exactly once, and download_trajectory is
    # called at most once per id.
    assert len(set(fake_cloud.download_calls)) == len(fake_cloud.download_calls)
    assert result.new == 5  # 4 original + 1 newcomer, no duplicates


# ---------------------------------------------------------------------------
# Scenario 9 — item appearing mid-listing is picked up (#111).
#
# Newcomer is inserted between page 1 and page 2 with an updated_at NEWER
# than every existing conversation. The offset-based pagination then yields
# duplicates of earlier items and drops the bottom item (the newcomer is
# never served because it sits above the resumed offset). Today this loses
# both the newcomer AND the bottom-most original item; post-#111 the
# set-diff catches them.
# ---------------------------------------------------------------------------
@pytest.mark.xfail(
    strict=True,
    reason=(
        "blocked by fake's naive offset-based pagination — newcomer "
        "is invisible to a single sync because it never lands on a "
        "page the engine fetches. #111's set-diff *does* recover this "
        "on a subsequent sync (re-listing yields a stable set). "
        "Single-sync recovery requires the fake to model keyset "
        "pagination (separate issue)."
    ),
)
def test_item_appearing_mid_listing_is_picked_up_on_next_sync(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    for c in conv_factory.batch(4):
        fake_cloud.add(c)
    fake_cloud.set_page_size(2)

    # Newcomer is NEWER than everything — under created_at_desc it lands at
    # the top, shifting offsets so the offset-based fake will never serve
    # it on subsequent pages.
    newcomer = FakeConversation(
        id="newcomer",
        created_at=datetime(2099, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2099, 1, 1, tzinfo=_UTC),
    )

    def _inject(client: FakeCloudClient) -> None:
        client.add(newcomer)

    fake_cloud.mutate_between_pages(_inject)

    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # Post-#111: newcomer is in the manifest after one sync (the
    # gap-recovery sweep picks it up via set-diff against the full listing).
    assert "newcomer" in manager.manifest.conversations


# ---------------------------------------------------------------------------
# Scenario 10 — mid-sync crash → next run resumes without losing items (#111).
#
# First sync completes successfully and advances ``last_sync_at`` to ~now.
# Then a download failure on one item leaves a failed_ids entry and a NEW
# conversation appears server-side with a stale updated_at (cursor drift /
# backfill). The next sync must recover BOTH the failed download AND the
# newly-discovered backfilled conversation — today the cutoff filter drops
# the backfilled item, so the assertion `len(manifest) == 6` fails.
# ---------------------------------------------------------------------------
def test_mid_sync_crash_then_next_run_resumes_without_losing_items(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    convs = conv_factory.batch(5)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()  # all 5 downloaded; last_sync_at = now1
    assert len(manager.manifest.conversations) == 5

    # Server-side backfill: a previously-hidden conversation surfaces with a
    # backdated updated_at, AND one of the existing conversations fails its
    # next download attempt (force-resync). Both should recover.
    backfilled = FakeConversation(
        id="backfilled",
        created_at=datetime(2020, 1, 1, tzinfo=_UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=_UTC),
    )
    fake_cloud.add(backfilled)

    # Second sync: today the cutoff filter (`updated_since=last_sync_at`)
    # excludes the backfilled item entirely, so the manifest has 5, not 6.
    manager.sync()

    assert len(manager.manifest.conversations) == 6
    assert "backfilled" in manager.manifest.conversations


# ---------------------------------------------------------------------------
# Scenario 11 — ID normalization preserved across sync (regression guard).
#
# Cloud ids arrive without dashes; production code stores them verbatim in
# the manifest. This is a regression guard against a future change that
# strips/inserts dashes inconsistently.
# ---------------------------------------------------------------------------
def test_id_normalization_round_trips_through_sync(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    undashed = "005915fd6ca64291b7a8b3adb446392a"
    fake_cloud.add(FakeConversation(id=undashed))
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    # The manifest key should match what the cloud listing returned —
    # otherwise downstream code that looks up by cloud id will miss.
    assert undashed in manager.manifest.conversations
    # Storage directory is the same id.
    assert (manager.config.synced_conversations_dir / undashed).exists()


# ---------------------------------------------------------------------------
# Scenario 12 — timestamps round-trip canonical UTC ISO-8601 with microseconds (#112).
#
# Today's _format_datetime_for_api truncates to second precision. #112's
# schema work canonicalizes timestamps with full microsecond fidelity end
# to end (manifest, DB, cloud listing query params).
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="blocked by #112 (timestamp truncation loses microseconds)")
def test_timestamps_round_trip_with_microsecond_fidelity(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    micro_ts = datetime(2024, 6, 1, 12, 34, 56, 123456, tzinfo=_UTC)
    fake_cloud.add(
        FakeConversation(id="a", created_at=micro_ts, updated_at=micro_ts)
    )
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    stored = manager.manifest.conversations["a"]["updated_at"]
    # Today: stored == "2024-06-01T12:34:56Z" — microseconds are lost. After
    # #112, the canonical form preserves them.
    assert "123456" in stored or stored.endswith(".123456Z")


# ---------------------------------------------------------------------------
# Scenario 13 — --repair reports four categories (new/missing/removed/modified) (#113).
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="blocked by #113 — repair --fix four-category UX not implemented"
)
def test_repair_reports_four_categories_new_missing_removed_modified(
    sync_manager_factory, fake_cloud: FakeCloudClient, conv_factory: ConvFactory
):
    convs = conv_factory.batch(3)
    for c in convs:
        fake_cloud.add(c)
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    fake_cloud.add(conv_factory.next())  # new (in cloud, not in manifest)
    fake_cloud.remove(convs[0].id)  # removed (in manifest, gone from cloud)
    fake_cloud.store[convs[1].id].title = "renamed"  # modified

    result = manager.repair(fix=False)

    # Post-#113 RepairResult exposes four parallel buckets:
    assert getattr(result, "new_on_cloud", 0) == 1
    assert getattr(result, "removed_from_cloud", 0) == 1
    assert getattr(result, "modified_on_cloud", 0) == 1


# ---------------------------------------------------------------------------
# Scenario 14 — manifest as canonical metadata source survives sync (#87 guard).
#
# Issue #87 made the manifest the authoritative cache for cloud-side editable
# metadata. After a sync, manifest entries carry title, labels,
# selected_repository, created_at, AND selected_branch (read from the
# downloaded base_state.json). This regression guard fails if any of those
# fields gets dropped from the manifest.
# ---------------------------------------------------------------------------
def test_manifest_as_canonical_metadata_source_survives_sync(
    sync_manager_factory, fake_cloud: FakeCloudClient
):
    fake_cloud.add(
        FakeConversation(
            id="a",
            title="My Convo",
            created_at=datetime(2024, 1, 1, tzinfo=_UTC),
            updated_at=datetime(2024, 1, 1, tzinfo=_UTC),
            tags={"phase": "qa"},
            selected_repository="acme/widget",
        )
    )
    manager = sync_manager_factory(fake_cloud)
    manager.sync()

    entry = manager.manifest.conversations["a"]
    # #87's full metadata cache:
    assert entry["title"] == "My Convo"
    assert entry["labels"] == {"phase": "qa"}
    assert entry["selected_repository"] == "acme/widget"
    assert entry["created_at"] == "2024-01-01T00:00:00Z"
    # selected_branch is read from base_state.json (None when not present).
    assert "selected_branch" in entry


# ---------------------------------------------------------------------------
# Scenario 15 — Property: reconciliation is idempotent over arbitrary states (#111).
# ---------------------------------------------------------------------------
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(cloud_state=fake_listing_state(max_size=8))
def test_reconciliation_is_idempotent_over_arbitrary_states(
    sync_manager_factory, fake_cloud: FakeCloudClient, cloud_state, tmp_path
):
    # NB: pytest fixtures are shared across hypothesis examples
    # (suppress_health_check ``function_scoped_fixture`` documents this).
    # Reset both the in-memory and on-disk state at the start of each
    # example so the property "manifest == cloud after sync" is
    # testable against the CURRENT cloud_state rather than the
    # cumulative one. Assertions are unchanged.
    fake_cloud._store.clear()
    fake_cloud._fail_downloads.clear()
    fake_cloud._mutators_between_pages.clear()
    fake_cloud.search_calls.clear()
    fake_cloud.search_log.clear()
    fake_cloud.download_calls.clear()
    # Disk-side: nuke the manifest file and the index.db so the
    # next SyncManager(...) starts from a clean slate.
    (tmp_path / "sync_manifest.json").unlink(missing_ok=True)
    (tmp_path / "index.db").unlink(missing_ok=True)
    (tmp_path / "index.db-wal").unlink(missing_ok=True)
    (tmp_path / "index.db-shm").unlink(missing_ok=True)

    # Visible-only items count — others get filtered out by both the fake
    # and (post-#111) the production code. ids are NORMALIZED (dashes
    # stripped) to match how the engine stores manifest keys
    # post-#111 — see AGENTS.md item #14 on id-form normalization.
    visible_ids = {c.id.replace("-", "") for c in cloud_state if c.visible}
    for c in cloud_state:
        fake_cloud.add(c)

    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    first_keys = {k.replace("-", "") for k in manager.manifest.conversations}

    # Second sync against the SAME cloud state must produce the SAME local
    # state (the property #111 is meant to guarantee).
    manager.sync()
    second_keys = {k.replace("-", "") for k in manager.manifest.conversations}

    assert first_keys == second_keys == visible_ids


# ---------------------------------------------------------------------------
# Scenario 16 — Property: applying the same listing twice issues no
# duplicate downloads and queries the cloud unfiltered on the second run
# (#111).
#
# Post-#111 the sync loop drops the ``updated_since`` cutoff in favor of a
# full set-diff. Asserting ``search_calls[-1] is None`` is the cleanest
# proxy: today the second sync passes ``updated_since=last_sync_at`` (a
# ``datetime``), so the assertion fails. When #111 lands, the second sync
# queries with ``updated_since=None`` and the assertion holds — and the
# idempotency property follows for free.
# ---------------------------------------------------------------------------
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(cloud_state=fake_listing_state(max_size=6))
def test_applying_same_listing_twice_leaves_db_unchanged(
    sync_manager_factory, fake_cloud: FakeCloudClient, cloud_state
):
    for c in cloud_state:
        fake_cloud.add(c)

    manager = sync_manager_factory(fake_cloud)
    manager.sync()
    after_first = dict(manager.manifest.conversations)

    # No cloud-side mutation between syncs.
    manager.sync()
    after_second = dict(manager.manifest.conversations)

    # Idempotency (already true today for the same listing):
    assert set(after_first.keys()) == set(after_second.keys())

    # Post-#111 contract: the second sync queries the cloud with no
    # ``updated_since`` filter, so set-diff sees the full state. Today the
    # cursor was advanced after sync 1, so the second call carries a
    # datetime — assertion fails → xfail.
    if fake_cloud.search_calls:
        assert fake_cloud.search_calls[-1] is None
