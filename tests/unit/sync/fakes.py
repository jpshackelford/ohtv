"""Programmable in-memory replacement for ``ohtv.sources.cloud.CloudClient``.

This is the foundation of the cloud-sync behavioral test harness (Issue
#110). The fake is duck-typed against the methods that ``src/ohtv/sync.py``,
``SyncManager.repair()``, and ``SyncManager.update_metadata()`` actually
invoke against the real client. Concretely, that surface is:

* ``search_conversations(updated_since, limit, page_id) -> (items, next_page_id)``
* ``search_all_conversations(updated_since) -> list[dict]``
* ``count_conversations() -> int``
* ``download_trajectory(conversation_id) -> bytes``
* ``update_conversation(conversation_id, *, title=None, tags=None) -> None``
* ``close()`` / ``__enter__`` / ``__exit__`` — context manager protocol

The fake also exposes test-only knobs (``add``, ``remove``, ``backdate``,
``set_visible``, ``fail_listing_at_page``, ``fail_download``,
``mutate_between_pages``) so scenarios can simulate the cloud-side failure
modes that motivated Issue #110.

The recording attributes (``search_calls``, ``download_calls``,
``update_calls``) are intentionally compatible with the inline
``_RecordingCloudClient`` that used to live at ``tests/unit/test_sync.py:890``
— callers can migrate by changing the import without rewriting their
assertions. The old class is being folded into this one rather than kept
parallel; see Issue #110's technical-approach comment.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .builders import make_trajectory_zip


def _utc_now() -> datetime:
    """Default clock — overridable by ``FakeCloudClient(clock=...)``."""
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime | None) -> str | None:
    """Render an optional ``datetime`` as canonical ``YYYY-MM-DDTHH:MM:SSZ``."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FakeConversation:
    """In-memory cloud conversation used by :class:`FakeCloudClient`.

    Attributes:
        id: Conversation id (any format — dashed or undashed both pass
            through unchanged so the harness can exercise normalization).
        title: Cloud-side title.
        created_at: When the conversation was first created on the cloud.
        updated_at: Last cloud-side mutation timestamp. The default
            ``created_at_desc`` listing order on the real cloud is keyed
            off this field's sibling ``created_at``; ``updated_at`` is what
            ``sync()`` uses as its incremental cutoff.
        tags: Optional cloud-side tags / labels dict (``None`` distinguishes
            "key never sent" from ``{}`` which means "explicitly cleared").
        trajectory_zip: Pre-built trajectory ZIP bytes. ``None`` triggers a
            lazy build via :func:`make_trajectory_zip` on first download.
        visible: When ``False``, the conversation is filtered out of every
            listing response but still answers ``download_trajectory`` /
            ``update_conversation`` (lets tests simulate the "vanished from
            listing but blob still on disk" case).
        selected_repository: Optional repo for Issue #87 metadata. Surfaces
            in the listing payload only.
    """

    id: str
    title: str = "Untitled"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    tags: dict[str, str] | None = None
    trajectory_zip: bytes | None = None
    visible: bool = True
    selected_repository: str | None = None

    def to_listing_dict(self) -> dict:
        """Serialize to the dict shape the real listing API returns."""
        return {
            "id": self.id,
            "title": self.title,
            "created_at": _iso_z(self.created_at),
            "updated_at": _iso_z(self.updated_at),
            "tags": self.tags,
            "selected_repository": self.selected_repository,
        }


@dataclass(frozen=True)
class SearchCall:
    """Recorded ``search_*`` invocation for assertion convenience."""

    method: str  # "search_conversations" or "search_all_conversations"
    updated_since: datetime | None
    limit: int | None = None
    page_id: str | None = None


@dataclass(frozen=True)
class UpdateCall:
    """Recorded ``update_conversation`` invocation."""

    conversation_id: str
    title: str | None
    tags: dict[str, str] | None


class FakeCloudClient:
    """Programmable in-memory fake of ``ohtv.sources.cloud.CloudClient``.

    Construct with the conversations the cloud "knows about", then optionally
    pre-stage failures and visibility flips with the test-only knobs before
    the system under test makes its first call. Every protocol call is
    recorded on the call-recording attributes (``search_calls``,
    ``download_calls``, ``update_calls``) so assertions can verify the
    sequence and arguments after the fact.
    """

    SortKey = Literal["created_at_desc", "updated_at_desc"]

    def __init__(
        self,
        conversations: Iterable[FakeConversation] = (),
        *,
        page_size: int = 100,
        sort: SortKey = "created_at_desc",
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._store: dict[str, FakeConversation] = {c.id: c for c in conversations}
        self._page_size = page_size
        self._sort: FakeCloudClient.SortKey = sort
        self._clock = clock

        # Failure injection state.
        self._fail_listing_at_page: dict[int, BaseException] = {}
        self._fail_downloads: dict[str, BaseException] = {}
        self._mutators_between_pages: list[Callable[["FakeCloudClient"], None]] = []
        self._listing_page_counter = 0

        # Call recording — shape compatible with _RecordingCloudClient.
        # ``search_calls`` carries ``updated_since`` values for back-compat;
        # ``search_log`` carries the richer :class:`SearchCall` records.
        self.search_calls: list[datetime | None] = []
        self.search_log: list[SearchCall] = []
        self.download_calls: list[str] = []
        self.update_calls: list[UpdateCall] = []
        self.closed: bool = False

    # ------------------------------------------------------------------
    # Test-only knobs
    # ------------------------------------------------------------------
    def add(self, conv: FakeConversation) -> None:
        """Add (or replace) a conversation in the in-memory store."""
        self._store[conv.id] = conv

    def remove(self, conv_id: str) -> None:
        """Remove a conversation entirely (simulates a cloud-side delete)."""
        self._store.pop(conv_id, None)

    def set_visible(self, conv_id: str, visible: bool) -> None:
        """Toggle whether a conversation appears in listing responses."""
        if conv_id in self._store:
            self._store[conv_id].visible = visible

    def backdate(self, conv_id: str, updated_at: datetime) -> None:
        """Set a conversation's ``updated_at`` to an arbitrary value.

        Useful for the "backdated visibility" scenario where a conversation
        is mutated server-side but its ``updated_at`` ends up older than
        the local manifest's ``last_sync_at``.
        """
        if conv_id in self._store:
            self._store[conv_id].updated_at = updated_at

    def set_page_size(self, n: int) -> None:
        """Override the pagination page size after construction."""
        self._page_size = n

    def fail_listing_at_page(self, n: int, exc: BaseException) -> None:
        """Raise ``exc`` when listing serves its ``n``-th page (1-indexed)."""
        self._fail_listing_at_page[n] = exc

    def fail_download(self, conv_id: str, exc: BaseException) -> None:
        """Raise ``exc`` when ``download_trajectory(conv_id)`` is invoked."""
        self._fail_downloads[conv_id] = exc

    def mutate_between_pages(
        self, callback: Callable[["FakeCloudClient"], None]
    ) -> None:
        """Register a callback to run between every pair of listing pages.

        Each callback runs exactly once per inter-page boundary, in
        registration order. Lets tests simulate items appearing or
        disappearing mid-listing (the keyset-drift case called out in the
        Issue #110 plan).
        """
        self._mutators_between_pages.append(callback)

    @property
    def page_size(self) -> int:
        return self._page_size

    @property
    def store(self) -> dict[str, FakeConversation]:
        """Read-only view of the in-memory store — useful for assertions."""
        return dict(self._store)

    # ------------------------------------------------------------------
    # CloudClient protocol surface
    # ------------------------------------------------------------------
    def _visible_sorted(self) -> list[FakeConversation]:
        """Return the visible conversations in deterministic listing order."""
        visible = [c for c in self._store.values() if c.visible]
        if self._sort == "updated_at_desc":
            key = lambda c: (c.updated_at, c.id)  # noqa: E731
        else:
            key = lambda c: (c.created_at, c.id)  # noqa: E731
        # Stable secondary key on id keeps ties reproducible.
        return sorted(visible, key=key, reverse=True)

    @staticmethod
    def _filter_by_updated_since(
        candidates: list[FakeConversation], updated_since: datetime | None
    ) -> list[FakeConversation]:
        """Filter ``candidates`` to those with ``updated_at >= updated_since``.

        Both the threshold and each candidate's ``updated_at`` are normalized to
        UTC before comparison; naive datetimes are treated as UTC. Returns
        ``candidates`` unchanged when ``updated_since`` is ``None``.
        """
        if updated_since is None:
            return candidates
        since = updated_since
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return [
            c
            for c in candidates
            if (
                c.updated_at
                if c.updated_at.tzinfo
                else c.updated_at.replace(tzinfo=timezone.utc)
            )
            >= since
        ]

    def search_conversations(
        self,
        updated_since: datetime | None = None,
        limit: int = 100,
        page_id: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """Mirror :meth:`CloudClient.search_conversations`."""
        self.search_log.append(
            SearchCall(
                method="search_conversations",
                updated_since=updated_since,
                limit=limit,
                page_id=page_id,
            )
        )

        # 1-indexed offset implied by the opaque page_id token.
        offset = int(page_id) if page_id else 0
        page_number = (offset // max(limit, 1)) + 1

        if page_number in self._fail_listing_at_page:
            raise self._fail_listing_at_page[page_number]

        candidates = self._filter_by_updated_since(
            self._visible_sorted(), updated_since
        )

        page = candidates[offset : offset + limit]
        next_offset = offset + len(page)
        next_page_id = str(next_offset) if next_offset < len(candidates) else None

        return [c.to_listing_dict() for c in page], next_page_id

    def search_all_conversations(
        self, updated_since: datetime | None = None
    ) -> list[dict]:
        """Mirror :meth:`CloudClient.search_all_conversations`."""
        self.search_calls.append(updated_since)
        self.search_log.append(
            SearchCall(method="search_all_conversations", updated_since=updated_since)
        )

        all_items: list[dict] = []
        page_id: str | None = None
        self._listing_page_counter = 0

        while True:
            self._listing_page_counter += 1
            # Failure injection has to fire BEFORE we call search_conversations
            # because the public method records its own call as a child
            # SearchCall; we want the parent search_all_conversations call
            # to be the one that raises.
            if self._listing_page_counter in self._fail_listing_at_page:
                raise self._fail_listing_at_page[self._listing_page_counter]

            items, next_page_id = self._serve_page(
                updated_since=updated_since, page_id=page_id
            )
            all_items.extend(items)
            if not next_page_id:
                break

            # Inter-page mutation hook (run AFTER yielding the page but
            # BEFORE serving the next one). Each registered mutator runs
            # exactly once per boundary, in order.
            for mutator in self._mutators_between_pages:
                mutator(self)

            page_id = next_page_id

        return all_items

    def _serve_page(
        self, *, updated_since: datetime | None, page_id: str | None
    ) -> tuple[list[dict], str | None]:
        """Internal: serve one page WITHOUT recording a duplicate SearchCall.

        ``search_conversations`` records and serves; ``search_all_conversations``
        needs the serving logic but should record exactly one call against the
        public surface. Sharing :meth:`search_conversations` would record an
        extra ``SearchCall`` per page, which clutters assertions.
        """
        offset = int(page_id) if page_id else 0
        candidates = self._filter_by_updated_since(
            self._visible_sorted(), updated_since
        )
        page = candidates[offset : offset + self._page_size]
        next_offset = offset + len(page)
        next_page_id = str(next_offset) if next_offset < len(candidates) else None
        return [c.to_listing_dict() for c in page], next_page_id

    def count_conversations(self) -> int:
        """Mirror :meth:`CloudClient.count_conversations`.

        Counts only visible conversations — matches the cloud's behavior of
        hiding archived / deleted conversations from the count endpoint.
        """
        return sum(1 for c in self._store.values() if c.visible)

    def download_trajectory(self, conversation_id: str) -> bytes:
        """Mirror :meth:`CloudClient.download_trajectory`."""
        self.download_calls.append(conversation_id)
        if conversation_id in self._fail_downloads:
            raise self._fail_downloads[conversation_id]
        conv = self._store.get(conversation_id)
        if conv is None:
            # The real API returns 404 → httpx raises HTTPStatusError; we
            # raise a plain LookupError here so tests can distinguish a
            # missing fixture from an injected failure.
            raise LookupError(f"No FakeConversation registered for {conversation_id!r}")
        if conv.trajectory_zip is None:
            conv.trajectory_zip = make_trajectory_zip(
                conv_id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                selected_repository=conv.selected_repository,
            )
        return conv.trajectory_zip

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Mirror :meth:`CloudClient.update_conversation`.

        Mutates the in-memory store so subsequent listing calls reflect the
        edit (the real cloud does the same). Honors the "no-op when neither
        key is supplied" contract so the recording attribute can be used to
        assert that pure no-op invocations never reach the wire.
        """
        if title is None and tags is None:
            return
        self.update_calls.append(
            UpdateCall(conversation_id=conversation_id, title=title, tags=tags)
        )
        conv = self._store.get(conversation_id)
        if conv is not None:
            if title is not None:
                conv.title = title
            if tags is not None:
                conv.tags = tags

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeCloudClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class RecordingCloudClient(FakeCloudClient):
    """Back-compat shim for the inline ``_RecordingCloudClient`` in
    ``tests/unit/test_sync.py``.

    The constructor accepts a raw ``list[dict]`` listing payload (the shape
    the cloud API returns) instead of :class:`FakeConversation` instances.
    Useful when a test wants to drive ``update_metadata`` with a sparse,
    handcrafted listing where the field shape itself is part of the
    assertion (e.g., ``{"id": ..., "tags": None}`` for a "no tags" probe).

    Subclassing :class:`FakeCloudClient` rather than reimplementing keeps
    the migration painless: existing tests just swap the import. The shim
    overrides ``search_all_conversations`` to return the verbatim listing
    so the tests' dict literals reach the production code unchanged.
    """

    def __init__(self, listing: list[dict]):
        super().__init__()
        self._raw_listing: list[dict] = listing

    def search_all_conversations(
        self, updated_since: datetime | None = None
    ) -> list[dict]:
        self.search_calls.append(updated_since)
        self.search_log.append(
            SearchCall(
                method="search_all_conversations", updated_since=updated_since
            )
        )
        return list(self._raw_listing)

    def download_trajectory(self, conversation_id: str) -> bytes:  # pragma: no cover
        # Tests that use this shim never expect downloads to happen — record
        # the call so they can assert ``client.download_calls == []``, but
        # do NOT raise LookupError (the underlying store is empty by design).
        self.download_calls.append(conversation_id)
        return b""
