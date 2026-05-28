"""Hypothesis strategies for cloud-sync property tests (Issue #110).

These strategies generate well-formed :class:`FakeConversation` instances and
listing-state collections. Property tests in :mod:`test_behavioral` consume
``fake_listing_state`` to drive arbitrary local+cloud reconciliation inputs.

When the real reconciliation logic ships in #111, the property tests will
discover minimal failing inputs via Hypothesis' shrinking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import strategies as st

from .fakes import FakeConversation

# Anchor timestamps to a fixed window so tests stay deterministic-ish across
# runs. The range is 1 year wide which gives Hypothesis plenty of room to
# explore visibility/backdate edge cases without producing dates so far apart
# that human-readable assertions become awkward.
_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)
_WINDOW_DAYS = 365


@st.composite
def conversation_ids(draw) -> str:
    """Generate well-formed cloud conversation ids.

    The real cloud uses 32-char hex; production code (:mod:`ohtv.sync`)
    normalizes by stripping dashes. We generate both forms so reconciliation
    properties cover the normalization path.
    """
    base = draw(
        st.text(
            alphabet="0123456789abcdef",
            min_size=32,
            max_size=32,
        )
    )
    use_dashes = draw(st.booleans())
    if not use_dashes:
        return base
    # Format as 8-4-4-4-12 (RFC-4122 layout) so the strip-dashes round-trip
    # is meaningful.
    return f"{base[0:8]}-{base[8:12]}-{base[12:16]}-{base[16:20]}-{base[20:32]}"


@st.composite
def timestamps(draw) -> datetime:
    """Generate UTC timestamps inside the fixed test window."""
    minutes = draw(st.integers(min_value=0, max_value=_WINDOW_DAYS * 24 * 60))
    return _EPOCH + timedelta(minutes=minutes)


@st.composite
def fake_conversation(draw) -> FakeConversation:
    """Generate a single well-formed :class:`FakeConversation`."""
    created = draw(timestamps())
    # Updated_at >= created_at, which is invariably true on the real cloud.
    extra = draw(st.integers(min_value=0, max_value=_WINDOW_DAYS * 24 * 60))
    updated = created + timedelta(minutes=extra)
    tags = draw(
        st.one_of(
            st.none(),
            st.dictionaries(
                keys=st.text(min_size=1, max_size=16),
                values=st.text(min_size=0, max_size=32),
                max_size=4,
            ),
        )
    )
    return FakeConversation(
        id=draw(conversation_ids()),
        title=draw(st.text(min_size=0, max_size=80)),
        created_at=created,
        updated_at=updated,
        tags=tags or None,
        visible=draw(st.booleans()),
    )


@st.composite
def fake_listing_state(draw, *, max_size: int = 50) -> list[FakeConversation]:
    """Generate a deduplicated list of conversations (cloud-side state)."""
    n = draw(st.integers(min_value=0, max_value=max_size))
    return draw(
        st.lists(
            fake_conversation(),
            min_size=n,
            max_size=n,
            unique_by=lambda c: c.id.replace("-", ""),
        )
    )
