"""Unit tests for :mod:`ohtv.classify` (issue #83).

Test plan mapping (numbering matches the technical-approach comment on
issue #83):

* test #1 — :class:`TestCountMatching.test_count_matching_no_followups`
* test #2 — :class:`TestCountMatching.test_count_matching_has_followups`
* test #3 — :class:`TestCountMatching.test_count_matching_with_repo_filter`
* test #4 — :class:`TestApplyClassification.test_apply_classification_idempotent`
* test #5 — :class:`TestApplyClassification.test_apply_classification_only_touches_unknowns`
* test #6 — :class:`TestSetSingle.test_set_single_conversation`
* test #7 — :class:`TestSetSingle.test_set_single_conversation_missing_row`
* test #8 — :class:`TestListUnknown.test_list_unknown_with_repo_filter`

Acceptance criterion mapping (issue body checklist → test):

* AC1 (single-conv override, no --confirm) → test #6
* AC2 (single-conv idempotency) → also test #6
  (CLI smoke #13 covers the no-confirm path end-to-end)
* AC3 (--list-unknown + --repo + machine-readable) → test #8
* AC4 (bulk preview, no writes) → CLI smoke #11
* AC5 (bulk apply --confirm) → test #5 + CLI smoke #12
* AC6 (--has-followups --confirm) → test #2 + extension of test #5
* AC7 (--repo narrows both bulk and --list-unknown) → test #3 + test #8
* AC8 (missing conversation_human_input row handled gracefully) → test #7
* AC9 (invalid --source rejected) → CLI smoke #10
* AC10 (heuristic SQL + --confirm gate covered by tests) → all of the above
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from ohtv.classify import (
    FILTER_HAS_FOLLOWUPS,
    FILTER_NO_FOLLOWUPS,
    AmbiguousConversationIdError,
    InvalidSourceError,
    MissingHumanInputRowError,
    NoSuchConversationError,
    _assert_parent_column_present,
    apply_classification,
    apply_sub_classification,
    count_matching,
    list_unknown,
    set_single,
)
from ohtv.db.migrations import migrate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn() -> sqlite3.Connection:
    """In-memory DB with the full migration chain replayed.

    This is the same pattern used by tests/unit/db/stages/test_human_input.py
    and is the repo convention — we do NOT mock the database.
    """
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    migrate(c)
    yield c
    c.close()


def _insert_conversation(
    conn: sqlite3.Connection,
    conv_id: str,
    *,
    title: str = "test conv",
    created_at: str | None = None,
    location: str = "/tmp/fake",
    event_count: int = 1,
    parent_conversation_id: str | None = None,
) -> None:
    """Insert a row into ``conversations``. ID is stored normalised.

    ``parent_conversation_id`` is optional (issue #126); pass a non-NULL
    value to mark the row as a sub-conversation.
    """
    if created_at is None:
        created_at = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO conversations "
        "(id, location, event_count, title, created_at, parent_conversation_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, location, event_count, title, created_at, parent_conversation_id),
    )


def _insert_human_input(
    conn: sqlite3.Connection,
    conv_id: str,
    *,
    initial_prompt_words: int = 5,
    followup_word_count: int = 0,
    followup_message_count: int = 0,
    initial_prompt_source: str = "unknown",
    event_count: int = 1,
) -> None:
    """Insert a row into ``conversation_human_input``."""
    conn.execute(
        """
        INSERT INTO conversation_human_input (
            conversation_id,
            initial_prompt_words,
            initial_prompt_source,
            followup_word_count,
            followup_message_count,
            processed_at,
            event_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conv_id,
            initial_prompt_words,
            initial_prompt_source,
            followup_word_count,
            followup_message_count,
            "2024-06-01T12:00:00+00:00",
            event_count,
        ),
    )


def _insert_repo(
    conn: sqlite3.Connection,
    *,
    canonical_url: str,
    fqn: str,
    short_name: str,
) -> int:
    """Insert a repository and return its id."""
    cur = conn.execute(
        "INSERT INTO repositories (canonical_url, fqn, short_name) "
        "VALUES (?, ?, ?) RETURNING id",
        (canonical_url, fqn, short_name),
    )
    return cur.fetchone()[0]


def _link_conv_to_repo(
    conn: sqlite3.Connection,
    conv_id: str,
    repo_id: int,
    *,
    link_type: str = "write",
) -> None:
    conn.execute(
        "INSERT INTO conversation_repos (conversation_id, repo_id, link_type) "
        "VALUES (?, ?, ?)",
        (conv_id, repo_id, link_type),
    )


def _seed_simple_followups_mix(conn: sqlite3.Connection) -> None:
    """Three convs with 0 followups, two with >=1 followup.

    Used by both ``count_matching`` test #1 and #2 to keep the fixture
    minimal and the expected counts obvious.
    """
    # 0 followups (3 convs)
    for i in range(3):
        cid = f"nofu{i:028d}"
        _insert_conversation(conn, cid, title=f"no-fu {i}")
        _insert_human_input(conn, cid, followup_message_count=0)
    # >=1 followup (2 convs)
    for i in range(2):
        cid = f"hasfu{i:027d}"
        _insert_conversation(conn, cid, title=f"has-fu {i}")
        _insert_human_input(conn, cid, followup_message_count=i + 1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCountMatching:
    """Tests #1, #2, #3."""

    def test_count_matching_no_followups(self, conn):
        """Test #1: filter='no_followups' counts the 0-followup unknowns."""
        _seed_simple_followups_mix(conn)
        assert count_matching(conn, filter_=FILTER_NO_FOLLOWUPS) == 3

    def test_count_matching_has_followups(self, conn):
        """Test #2: filter='has_followups' counts the >=1-followup unknowns."""
        _seed_simple_followups_mix(conn)
        assert count_matching(conn, filter_=FILTER_HAS_FOLLOWUPS) == 2

    def test_count_matching_with_repo_filter(self, conn):
        """Test #3: --repo narrows the bulk count.

        Three no-followup convs exist; only one is linked to ``foo/bar``,
        so ``--repo foo/bar`` should report 1.
        """
        _seed_simple_followups_mix(conn)
        repo_id = _insert_repo(
            conn,
            canonical_url="https://github.com/foo/bar",
            fqn="foo/bar",
            short_name="bar",
        )
        # Link only the first no-followup conv to foo/bar.
        _link_conv_to_repo(conn, "nofu" + "0".zfill(28), repo_id)

        assert (
            count_matching(conn, filter_=FILTER_NO_FOLLOWUPS, repo="foo/bar") == 1
        )
        # And by short name too:
        assert (
            count_matching(conn, filter_=FILTER_NO_FOLLOWUPS, repo="bar") == 1
        )
        # An unknown repo yields 0, not "all rows".
        assert (
            count_matching(conn, filter_=FILTER_NO_FOLLOWUPS, repo="ghost/repo") == 0
        )

    def test_count_matching_skips_already_classified(self, conn):
        """Bulk count must only see ``initial_prompt_source = 'unknown'`` rows.

        Belt-and-suspenders for test #5 — guarantees the preview shown to
        the user matches what an apply would actually change.
        """
        _seed_simple_followups_mix(conn)
        # Flip one of the 3 no-fu rows to 'human' manually.
        conn.execute(
            "UPDATE conversation_human_input SET initial_prompt_source = 'human' "
            "WHERE conversation_id = ?",
            ("nofu" + "0".zfill(28),),
        )
        assert count_matching(conn, filter_=FILTER_NO_FOLLOWUPS) == 2


class TestApplyClassification:
    """Tests #4 and #5."""

    def test_apply_classification_idempotent(self, conn):
        """Test #4: second apply with the same source reports 0 changed."""
        _seed_simple_followups_mix(conn)

        first = apply_classification(
            conn, filter_=FILTER_NO_FOLLOWUPS, source="automation"
        )
        second = apply_classification(
            conn, filter_=FILTER_NO_FOLLOWUPS, source="automation"
        )

        assert first == 3
        assert second == 0  # nothing left at 'unknown' matching the predicate.

    def test_apply_classification_only_touches_unknowns(self, conn):
        """Test #5: must not clobber manual overrides.

        Pre-mark one of the no-followup rows as 'human'. A bulk apply
        with --source automation must leave that row alone.
        """
        _seed_simple_followups_mix(conn)
        manual_id = "nofu" + "0".zfill(28)
        conn.execute(
            "UPDATE conversation_human_input SET initial_prompt_source = 'human' "
            "WHERE conversation_id = ?",
            (manual_id,),
        )

        changed = apply_classification(
            conn, filter_=FILTER_NO_FOLLOWUPS, source="automation"
        )

        assert changed == 2  # the other two no-followup rows

        # The manually-flagged row is still 'human'.
        row = conn.execute(
            "SELECT initial_prompt_source FROM conversation_human_input "
            "WHERE conversation_id = ?",
            (manual_id,),
        ).fetchone()
        assert row["initial_prompt_source"] == "human"

        # The has-followups rows are untouched (still 'unknown').
        leftover = conn.execute(
            "SELECT COUNT(*) AS n FROM conversation_human_input "
            "WHERE initial_prompt_source = 'unknown'"
        ).fetchone()["n"]
        assert leftover == 2

    def test_apply_classification_has_followups_path(self, conn):
        """Symmetric to test #5: --has-followups --source human only flips unknowns.

        Locks in AC6 (``--has-followups --source human --confirm`` works).
        """
        _seed_simple_followups_mix(conn)
        changed = apply_classification(
            conn, filter_=FILTER_HAS_FOLLOWUPS, source="human"
        )
        assert changed == 2

        sources = {
            row["conversation_id"]: row["initial_prompt_source"]
            for row in conn.execute(
                "SELECT conversation_id, initial_prompt_source "
                "FROM conversation_human_input"
            )
        }
        # has-fu now human, no-fu still unknown.
        assert sources["hasfu" + "0".zfill(27)] == "human"
        assert sources["hasfu" + "1".zfill(27)] == "human"
        assert sources["nofu" + "0".zfill(28)] == "unknown"

    def test_apply_classification_rejects_invalid_source(self, conn):
        _seed_simple_followups_mix(conn)
        with pytest.raises(InvalidSourceError):
            apply_classification(
                conn, filter_=FILTER_NO_FOLLOWUPS, source="bogus"  # type: ignore[arg-type]
            )

    def test_apply_classification_with_repo_filter(self, conn):
        """AC7: --repo narrows the bulk update."""
        _seed_simple_followups_mix(conn)
        repo_id = _insert_repo(
            conn,
            canonical_url="https://github.com/foo/bar",
            fqn="foo/bar",
            short_name="bar",
        )
        only_linked = "nofu" + "0".zfill(28)
        _link_conv_to_repo(conn, only_linked, repo_id)

        changed = apply_classification(
            conn,
            filter_=FILTER_NO_FOLLOWUPS,
            source="automation",
            repo="foo/bar",
        )
        assert changed == 1

        # The unlinked no-fu rows should still be 'unknown'.
        still_unknown = conn.execute(
            "SELECT COUNT(*) AS n FROM conversation_human_input "
            "WHERE initial_prompt_source = 'unknown' "
            "AND followup_message_count = 0"
        ).fetchone()["n"]
        assert still_unknown == 2


class TestSetSingle:
    """Tests #6 and #7."""

    def test_set_single_conversation(self, conn):
        """Test #6: set one row, no others change. Idempotent re-run."""
        _seed_simple_followups_mix(conn)
        target = "hasfu" + "0".zfill(27)

        result = set_single(conn, conversation_id=target, source="human")
        assert result.changed is True
        assert result.previous_source == "unknown"
        assert result.new_source == "human"

        rows = {
            r["conversation_id"]: r["initial_prompt_source"]
            for r in conn.execute(
                "SELECT conversation_id, initial_prompt_source "
                "FROM conversation_human_input"
            )
        }
        assert rows[target] == "human"
        # No others flipped.
        for cid, src in rows.items():
            if cid == target:
                continue
            assert src == "unknown"

        # Second call with the same source: no change.
        second = set_single(conn, conversation_id=target, source="human")
        assert second.changed is False

    def test_set_single_accepts_dashed_id(self, conn):
        """AGENTS.md item #14: dashed IDs are normalised before lookup."""
        # Stored without dashes.
        cid = "abcdef12345678901234567890abcdef"
        _insert_conversation(conn, cid)
        _insert_human_input(conn, cid)

        dashed = (
            "abcdef12-3456-7890-1234-567890abcdef"
        )  # equivalent UUID-style form
        result = set_single(conn, conversation_id=dashed, source="automation")
        assert result.changed is True
        assert result.conversation_id == cid

    def test_set_single_can_flip_already_classified(self, conn):
        """The single-conv override path explicitly CAN flip non-unknowns."""
        cid = "humanrow" + "1".zfill(24)
        _insert_conversation(conn, cid)
        _insert_human_input(conn, cid, initial_prompt_source="automation")

        result = set_single(conn, conversation_id=cid, source="human")
        assert result.changed is True
        assert result.previous_source == "automation"
        assert result.new_source == "human"

    def test_set_single_conversation_missing_row(self, conn):
        """Test #7 / AC8: refuse on missing human-input row with clear message."""
        cid = "missrow" + "1".zfill(25)
        _insert_conversation(conn, cid)  # conversation exists,
        # but no row in conversation_human_input.

        with pytest.raises(MissingHumanInputRowError) as exc:
            set_single(conn, conversation_id=cid, source="human")

        msg = str(exc.value)
        assert cid in msg
        assert "ohtv db process human_input" in msg


class TestSetSingleShortIdResolution:
    """Tests for short-ID prefix resolution in :func:`set_single`.

    Mirrors the convention in ``_find_conversation_dir`` (AGENTS.md item
    #14): callers may pass either a full 32-char ID or a unique short
    prefix. Fixes bug B-1 (README example #5: ``classify --list-unknown
    -1 | head -5 | xargs ohtv classify {}``) and bug B-2 (distinct error
    message for "no such conversation" vs "stage hasn't run").
    """

    def test_set_single_resolves_short_prefix(self, conn):
        """B-1: a unique 8-char short ID resolves to the full row."""
        cid = "deadbeefcafef00d1234567890abcdef"
        _insert_conversation(conn, cid)
        _insert_human_input(conn, cid)

        # Mirrors what ``classify --list-unknown -1`` emits: 8 chars.
        result = set_single(conn, conversation_id="deadbeef", source="human")
        assert result.changed is True
        assert result.conversation_id == cid

        # The DB was actually updated with the full ID.
        stored = conn.execute(
            "SELECT initial_prompt_source FROM conversation_human_input "
            "WHERE conversation_id = ?",
            (cid,),
        ).fetchone()
        assert stored["initial_prompt_source"] == "human"

    def test_set_single_ambiguous_short_prefix_is_rejected(self, conn):
        """B-1: prefix that matches multiple convs raises, with sample matches."""
        # Three conversations all starting with "abcd1234".
        prefix = "abcd1234"
        cids = [
            prefix + "00" + "0".zfill(22),
            prefix + "11" + "1".zfill(22),
            prefix + "22" + "2".zfill(22),
        ]
        for cid in cids:
            _insert_conversation(conn, cid)
            _insert_human_input(conn, cid)

        with pytest.raises(AmbiguousConversationIdError) as exc:
            set_single(conn, conversation_id=prefix, source="human")

        msg = str(exc.value)
        assert prefix in msg
        assert "3 matches" in msg
        # Useful sample is included so the user can disambiguate.
        for cid in cids:
            assert cid[:12] in msg
        # The exception itself also exposes the match list for tooling.
        assert sorted(exc.value.matches) == sorted(cids)

        # No row was touched.
        flipped = conn.execute(
            "SELECT COUNT(*) AS n FROM conversation_human_input "
            "WHERE initial_prompt_source != 'unknown'"
        ).fetchone()["n"]
        assert flipped == 0

    def test_set_single_unknown_id_raises_no_such_conversation(self, conn):
        """B-2: ID that matches no conversation raises NoSuchConversationError.

        The message must NOT blame ``conversation_human_input`` — the
        problem is that the conversation itself isn't indexed.
        """
        # DB has *some* conversation, just not the requested one. This
        # also exercises the "no prefix collision possible" path.
        _insert_conversation(conn, "ffffffff" + "f".zfill(24))

        with pytest.raises(NoSuchConversationError) as exc:
            set_single(conn, conversation_id="00000000", source="human")

        msg = str(exc.value)
        assert "00000000" in msg
        # The B-2 fix: the error must distinguish itself from
        # MissingHumanInputRowError. It must NOT mention the human-input
        # row or suggest running ``ohtv db process human_input``.
        assert "conversation_human_input" not in msg
        assert "ohtv db process human_input" not in msg
        # And it must point at the real remediation.
        assert "ohtv db scan" in msg

    def test_set_single_distinguishes_missing_conv_from_missing_human_input(
        self, conn
    ):
        """B-2: same fixture style, two distinct exception types.

        ``MissingHumanInputRowError`` fires only when the conversation
        row exists but the ``human_input`` stage hasn't produced its row
        yet. ``NoSuchConversationError`` fires when the conversation row
        doesn't exist at all.
        """
        # Case A: no conversation row at all.
        with pytest.raises(NoSuchConversationError):
            set_single(conn, conversation_id="aa" + "a".zfill(30), source="human")

        # Case B: conversation row exists, but no human_input row.
        cid = "bb" + "b".zfill(30)
        _insert_conversation(conn, cid)
        with pytest.raises(MissingHumanInputRowError):
            set_single(conn, conversation_id=cid, source="human")

    def test_set_single_full_id_skips_prefix_path(self, conn):
        """A 32-char exact match must not trigger a LIKE scan.

        Regression guard: a full ID that happens to be a prefix of
        another conversation must still resolve unambiguously via the
        exact-match fast path.
        """
        short_target = "aaaa1111" + "0".zfill(24)
        long_neighbour = "aaaa1111" + "x" + "0".zfill(23)
        # ``long_neighbour`` shares the first 8 chars with ``short_target``.
        # If we passed "aaaa1111" we'd hit ambiguity; passing the full
        # ``short_target`` must resolve directly.
        _insert_conversation(conn, short_target)
        _insert_human_input(conn, short_target)
        _insert_conversation(conn, long_neighbour)
        _insert_human_input(conn, long_neighbour)

        result = set_single(
            conn, conversation_id=short_target, source="automation"
        )
        assert result.changed is True
        assert result.conversation_id == short_target

    def test_set_single_dashed_short_prefix_is_normalised(self, conn):
        """Dashes inside a short-ID prefix are still stripped before lookup."""
        cid = "deadbeef" + "0".zfill(24)
        _insert_conversation(conn, cid)
        _insert_human_input(conn, cid)

        # Caller passes a dashed short prefix; resolver must strip it.
        result = set_single(
            conn, conversation_id="dead-beef", source="human"
        )
        assert result.changed is True
        assert result.conversation_id == cid


class TestListUnknown:
    """Test #8."""

    def test_list_unknown_with_repo_filter(self, conn):
        """Test #8 + AC3 + AC7: --list-unknown narrows by --repo."""
        # Two unknowns, one classified.
        _insert_conversation(conn, "unkA" + "1".zfill(28), title="A")
        _insert_human_input(conn, "unkA" + "1".zfill(28))
        _insert_conversation(conn, "unkB" + "1".zfill(28), title="B")
        _insert_human_input(conn, "unkB" + "1".zfill(28))
        _insert_conversation(conn, "hum1" + "1".zfill(28), title="H")
        _insert_human_input(
            conn, "hum1" + "1".zfill(28), initial_prompt_source="human"
        )

        # Link only conv A to foo/bar.
        repo_id = _insert_repo(
            conn,
            canonical_url="https://github.com/foo/bar",
            fqn="foo/bar",
            short_name="bar",
        )
        _link_conv_to_repo(conn, "unkA" + "1".zfill(28), repo_id)

        # Unfiltered: both unknowns.
        unfiltered = list_unknown(conn)
        assert {r.short_id for r in unfiltered} == {"unkA0000", "unkB0000"}

        # Filtered: only A.
        filtered = list_unknown(conn, repo="foo/bar")
        assert [r.short_id for r in filtered] == ["unkA0000"]
        assert filtered[0].repo == "foo/bar"
        assert filtered[0].title == "A"

    def test_list_unknown_respects_limit(self, conn):
        for i in range(5):
            cid = f"limit{i:027d}"
            _insert_conversation(conn, cid, title=f"row{i}")
            _insert_human_input(conn, cid)

        assert len(list_unknown(conn, limit=2)) == 2

    def test_list_unknown_excludes_classified(self, conn):
        cid = "done1" + "0".zfill(27)
        _insert_conversation(conn, cid)
        _insert_human_input(conn, cid, initial_prompt_source="automation")
        assert list_unknown(conn) == []


# ---------------------------------------------------------------------------
# Issue #126 — sub-conversation auto-classification
# ---------------------------------------------------------------------------


def _seed_root_and_sub(
    conn: sqlite3.Connection,
    *,
    root_source: str = "unknown",
    sub_source: str = "unknown",
) -> tuple[str, str]:
    """Seed one root + one sub. Returns ``(root_id, sub_id)`` (normalised)."""
    root_id = "root1" + "0".zfill(27)
    sub_id = "sub01" + "0".zfill(27)
    _insert_conversation(conn, root_id, title="root")
    _insert_conversation(
        conn, sub_id, title="sub", parent_conversation_id=root_id
    )
    _insert_human_input(conn, root_id, initial_prompt_source=root_source)
    _insert_human_input(conn, sub_id, initial_prompt_source=sub_source)
    return root_id, sub_id


def _read_source(conn: sqlite3.Connection, cid: str) -> str | None:
    row = conn.execute(
        "SELECT initial_prompt_source FROM conversation_human_input "
        "WHERE conversation_id = ?",
        (cid,),
    ).fetchone()
    return row["initial_prompt_source"] if row else None


class TestApplySubClassification:
    """Issue #126 — :func:`apply_sub_classification`.

    Test plan (the auto-step writes the system-managed ``'sub_agent'``
    value introduced by migration 022; see the PR discussion on #146 for
    why ``'sub_agent'`` is distinct from ``'automation'``):

    * T-A — sub gets auto-classified from ``unknown``.
    * T-B — sub residual ``human`` (from a pre-fix bulk run) is corrected.
    * T-B2 — sub residual ``automation`` (from an earlier draft of this
      fix that reused the automation label) is corrected.
    * T-C — already-correct sub is a no-op (idempotency).
    * T-D — sub without a ``conversation_human_input`` row no-ops without
      raising.
    * T-E — manual override (``set_single``) wins within one invocation
      (operator-agency vs deterministic-ground-truth tension).
    """

    def test_t_a_sub_auto_classified_from_unknown(self, conn):
        """T-A: sub 'unknown' -> 'sub_agent'; root untouched; returns 1."""
        root_id, sub_id = _seed_root_and_sub(conn)

        changed = apply_sub_classification(conn)

        assert changed == 1
        assert _read_source(conn, sub_id) == "sub_agent"
        # Root is NOT a sub (parent_conversation_id IS NULL) so it must
        # stay 'unknown' — the auto-step refuses to touch roots even by
        # accident.
        assert _read_source(conn, root_id) == "unknown"

    def test_t_b_sub_residual_human_corrected(self, conn):
        """T-B: residual 'human' on a sub flips to 'sub_agent'.

        Models the post-bug state after a pre-fix
        ``--has-followups --source human`` bulk run mis-classified subs.
        """
        _, sub_id = _seed_root_and_sub(conn, sub_source="human")

        changed = apply_sub_classification(conn)

        assert changed == 1
        assert _read_source(conn, sub_id) == "sub_agent"

    def test_t_b2_sub_residual_automation_corrected(self, conn):
        """T-B2: residual 'automation' on a sub flips to 'sub_agent'.

        Models the post-bug state of any DB that ran an earlier draft of
        issue #126 (which set subs to ``'automation'``) before the
        switch to a dedicated ``'sub_agent'`` value. The auto-step must
        repair these silently — operators do not need to re-classify
        manually.
        """
        _, sub_id = _seed_root_and_sub(conn, sub_source="automation")

        changed = apply_sub_classification(conn)

        assert changed == 1
        assert _read_source(conn, sub_id) == "sub_agent"

    def test_t_c_already_correct_sub_is_noop(self, conn):
        """T-C: idempotency — second invocation returns 0."""
        _seed_root_and_sub(conn)

        first = apply_sub_classification(conn)
        second = apply_sub_classification(conn)

        assert first == 1
        assert second == 0

    def test_t_d_sub_without_human_input_row_silently_skipped(self, conn):
        """T-D: sub with no ``conversation_human_input`` row no-ops.

        The ``human_input`` stage hasn't processed the sub yet. The
        helper's ``UPDATE ... WHERE EXISTS (...)`` form has nothing to
        update — return 0, no exception, no special-case branch.
        """
        root_id = "rootB" + "0".zfill(27)
        sub_id = "subB1" + "0".zfill(27)
        _insert_conversation(conn, root_id, title="root no-hi")
        _insert_conversation(
            conn, sub_id, title="sub no-hi", parent_conversation_id=root_id
        )
        # NOTE: NO _insert_human_input for either row.

        changed = apply_sub_classification(conn)

        assert changed == 0

    def test_t_e_manual_override_wins_within_invocation(self, conn):
        """T-E: ``set_single`` after the auto-step flips back to 'human'.

        Documents AC5: within one ``ohtv classify`` invocation the
        operator override is the terminal write. On the NEXT invocation
        the auto-step would correct it back to ``'sub_agent'`` — that's
        the desired deterministic-ground-truth behavior.
        """
        _, sub_id = _seed_root_and_sub(conn)

        # Step 1: auto-step runs first (this is what the CLI command
        # body does at the top of `classify`).
        assert apply_sub_classification(conn) == 1
        assert _read_source(conn, sub_id) == "sub_agent"

        # Step 2: operator passes `ohtv classify <sub_id> --source human`.
        # `set_single` flips already-classified rows by design.
        result = set_single(conn, conversation_id=sub_id, source="human")

        assert result.changed is True
        assert result.previous_source == "sub_agent"
        assert result.new_source == "human"
        assert _read_source(conn, sub_id) == "human"

    def test_followup_counts_untouched(self, conn):
        """AC6: auto-step only writes ``initial_prompt_source``.

        ``followup_word_count`` and ``followup_message_count`` are
        written by the ``human_input`` stage from event data and must
        survive the auto-step unchanged.
        """
        root_id = "rootC" + "0".zfill(27)
        sub_id = "subC1" + "0".zfill(27)
        _insert_conversation(conn, root_id, title="root")
        _insert_conversation(
            conn, sub_id, title="sub", parent_conversation_id=root_id
        )
        _insert_human_input(
            conn,
            sub_id,
            followup_word_count=42,
            followup_message_count=7,
        )

        apply_sub_classification(conn)

        row = conn.execute(
            "SELECT followup_word_count, followup_message_count "
            "FROM conversation_human_input WHERE conversation_id = ?",
            (sub_id,),
        ).fetchone()
        assert row["followup_word_count"] == 42
        assert row["followup_message_count"] == 7


class TestAssertParentColumnPresent:
    """AC7 — guardrail when migration 019 hasn't run."""

    def test_passes_on_migrated_schema(self, conn):
        """No exception on the current migration chain (column present)."""
        _assert_parent_column_present(conn)  # does not raise

    def test_raises_when_column_missing(self):
        """Drop the column and confirm the guardrail fires.

        Using a fresh in-memory DB and a minimal `conversations` table
        without the column models the pre-migration-019 state. This is
        cheaper and more robust than partial-replaying the migration
        chain.
        """
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT)"
        )

        with pytest.raises(RuntimeError, match="migration 019"):
            _assert_parent_column_present(c)
        c.close()
