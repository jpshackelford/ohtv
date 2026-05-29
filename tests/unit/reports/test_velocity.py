"""Unit tests for :mod:`ohtv.reports.velocity` (issue #81).

These tests exercise the row-shaping logic against an in-memory
SQLite DB with the real migration history applied. No mocks for
the DB.

The fixtures live in ``conftest.py``.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timezone

import pytest

from ohtv.reports.velocity import (
    VelocityReport,
    VelocityRow,
    aggregate_velocity,
    bucket_by_iso_week,
    compute_totals,
    fetch_raw_rows,
    format_csv,
)

from tests.unit.reports.conftest import (
    seed_contribution,
    seed_conversation,
    seed_direct_push,
    seed_human_input,
    seed_pr,
    seed_repo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(rows: list[VelocityRow], week: str) -> VelocityRow:
    for r in rows:
        if r.week == week:
            return r
    raise AssertionError(f"week {week!r} not found in {[r.week for r in rows]}")


# ---------------------------------------------------------------------------
# T-1 .. T-12
# ---------------------------------------------------------------------------


def test_single_merged_pr_one_week(conn: sqlite3.Connection) -> None:
    """One merged PR, one conversation → one bucket with correct totals."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/jpshackelford/ohtv")
    seed_conversation(conn, "c1")
    pr_id = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at="2024-03-05T12:00:00Z",  # ISO week 10 of 2024
        lines_added=100,
        lines_removed=20,
    )
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)
    seed_human_input(
        conn,
        conversation_id="c1",
        initial_prompt_words=50,
        initial_prompt_source="human",
        followup_word_count=0,
        followup_message_count=0,
    )

    report = aggregate_velocity(conn=conn)

    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week == "2024-W10"
    assert row.prs_merged == 1
    assert row.lines_added == 100
    assert row.lines_removed == 20
    assert row.total_loc == 120
    assert row.human_words == 50
    assert row.human_messages == 1  # 1 + 0 followups
    assert row.words_per_loc == pytest.approx(0.42, abs=0.01)
    assert row.partial_loc is False


def test_multiple_prs_same_week_aggregate(conn: sqlite3.Connection) -> None:
    """Three PRs merged in the same ISO week collapse to one row."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    for i in (1, 2, 3):
        seed_conversation(conn, f"c{i}")
        seed_human_input(
            conn,
            conversation_id=f"c{i}",
            initial_prompt_words=10 * i,
            initial_prompt_source="human",
            followup_word_count=5,
            followup_message_count=1,
        )
        pr_id = seed_pr(
            conn,
            repo_id=repo_id,
            pr_number=i,
            merged_at="2024-03-05T12:00:00Z",
            lines_added=100 * i,
            lines_removed=10 * i,
        )
        seed_contribution(conn, conversation_id=f"c{i}", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week == "2024-W10"
    assert row.prs_merged == 3
    assert row.lines_added == 600  # 100+200+300
    assert row.lines_removed == 60
    assert row.total_loc == 660
    # words per conv: 10+5=15, 20+5=25, 30+5=35 → 75
    assert row.human_words == 75
    # msgs per conv: 1+1=2 each → 6
    assert row.human_messages == 6


def test_prs_span_multiple_weeks(conn: sqlite3.Connection) -> None:
    """PRs across 3 weeks → 3 rows in ascending week order."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    for i, merged in enumerate(
        ["2024-03-05T12:00:00Z", "2024-03-12T12:00:00Z", "2024-03-19T12:00:00Z"]
    ):
        seed_conversation(conn, f"c{i}")
        seed_human_input(
            conn,
            conversation_id=f"c{i}",
            initial_prompt_words=10,
            initial_prompt_source="human",
        )
        pr_id = seed_pr(conn, repo_id=repo_id, pr_number=i + 1, merged_at=merged)
        seed_contribution(conn, conversation_id=f"c{i}", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    weeks = [r.week for r in report.rows]
    assert weeks == ["2024-W10", "2024-W11", "2024-W12"]


def test_iso_week_boundary_2024_12_30(conn: sqlite3.Connection) -> None:
    """2024-12-30 is in ISO week 2025-W01, NOT 2024-W53.

    This is the canonical SQLite ``%W`` vs ISO regression test. The
    comment in issue #81 calls this exact date out.
    """
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    pr_id = seed_pr(
        conn, repo_id=repo_id, pr_number=1, merged_at="2024-12-30T12:00:00Z"
    )
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=5)

    report = aggregate_velocity(conn=conn)
    assert len(report.rows) == 1
    assert report.rows[0].week == "2025-W01"


def test_iso_week_boundary_sunday_to_monday(conn: sqlite3.Connection) -> None:
    """A PR merged 23:59 UTC Sunday and one at 00:00 UTC Monday land in different weeks."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_conversation(conn, "c2")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=1)
    seed_human_input(conn, conversation_id="c2", initial_prompt_words=1)
    # 2024-03-10 is a Sunday (ISO week 10 of 2024).
    pr1 = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-10T23:59:59Z")
    # 2024-03-11 is the following Monday (ISO week 11).
    pr2 = seed_pr(conn, repo_id=repo_id, pr_number=2, merged_at="2024-03-11T00:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr1)
    seed_contribution(conn, conversation_id="c2", change_ref_id=pr2)

    report = aggregate_velocity(conn=conn)
    weeks = [r.week for r in report.rows]
    assert weeks == ["2024-W10", "2024-W11"]


def test_non_merged_prs_excluded(conn: sqlite3.Connection) -> None:
    """Only ``status='merged'`` PRs are counted; pending/open/closed are dropped."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=10)
    merged_id = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at="2024-03-05T12:00:00Z",
        status="merged",
    )
    seed_pr(conn, repo_id=repo_id, pr_number=2, merged_at=None, status="pending")
    seed_pr(conn, repo_id=repo_id, pr_number=3, merged_at=None, status="open")
    seed_pr(conn, repo_id=repo_id, pr_number=4, merged_at=None, status="closed")
    seed_contribution(conn, conversation_id="c1", change_ref_id=merged_id)

    report = aggregate_velocity(conn=conn)
    assert len(report.rows) == 1
    assert report.rows[0].prs_merged == 1


def test_distinct_contributor_no_double_count(conn: sqlite3.Connection) -> None:
    """One conversation contributing as created+pushed+merged counts once per PR.

    Without the DISTINCT (change_ref_id, conversation_id) sub-select,
    this conversation's words would be triple-counted.
    """
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(
        conn,
        conversation_id="c1",
        initial_prompt_words=20,
        initial_prompt_source="human",
        followup_word_count=10,
        followup_message_count=2,
    )
    pr_id = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at="2024-03-05T12:00:00Z",
    )
    for ctype in ("created", "pushed", "merged"):
        seed_contribution(
            conn, conversation_id="c1", change_ref_id=pr_id, contribution_type=ctype
        )

    report = aggregate_velocity(conn=conn)
    assert len(report.rows) == 1
    row = report.rows[0]
    # Human words = 20 (initial) + 10 (followups) = 30, NOT 90.
    assert row.human_words == 30
    # Msgs = 1 + 2 = 3, NOT 9.
    assert row.human_messages == 3


def test_initial_prompt_source_automation(conn: sqlite3.Connection) -> None:
    """``initial_prompt_source='automation'`` excludes the initial prompt + 1 msg."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(
        conn,
        conversation_id="c1",
        initial_prompt_words=1000,  # should be IGNORED
        initial_prompt_source="automation",
        followup_word_count=15,
        followup_message_count=3,
    )
    pr_id = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    assert report.rows[0].human_words == 15
    assert report.rows[0].human_messages == 3


def test_initial_prompt_source_unknown_counts_as_human(conn: sqlite3.Connection) -> None:
    """``'unknown'`` is treated identically to ``'human'`` until issue #83."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(
        conn,
        conversation_id="c1",
        initial_prompt_words=12,
        initial_prompt_source="unknown",
        followup_word_count=8,
        followup_message_count=2,
    )
    pr_id = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    assert report.rows[0].human_words == 20  # 12 + 8
    assert report.rows[0].human_messages == 3  # 1 + 2


def test_initial_prompt_source_sub_agent_contributes_zero(
    conn: sqlite3.Connection,
) -> None:
    """Issue #126: ``'sub_agent'`` rows contribute 0 words and 0 messages.

    A sub-conversation is an extension of its parent, not an independent
    triggered run. Counting its words against the change_ref the parent
    contributed to would double-count work that is already rolled up in
    the parent's totals. The velocity CASE statement maps ``'sub_agent'``
    explicitly to ``0`` (rather than relying on the ``ELSE 0`` fallback)
    so the intent is visible in the SQL.
    """
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(
        conn,
        conversation_id="c1",
        initial_prompt_words=500,       # ignored
        initial_prompt_source="sub_agent",
        followup_word_count=200,        # ignored
        followup_message_count=10,      # ignored
    )
    pr_id = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    assert report.rows[0].human_words == 0
    assert report.rows[0].human_messages == 0


def test_words_per_loc_zero_denominator(conn: sqlite3.Connection) -> None:
    """All LOC NULL → words_per_loc is None (no divide-by-zero crash)."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(
        conn, conversation_id="c1", initial_prompt_words=40, initial_prompt_source="human"
    )
    pr_id = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at="2024-03-05T12:00:00Z",
        lines_added=None,
        lines_removed=None,
    )
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    row = report.rows[0]
    assert row.lines_added is None
    assert row.lines_removed is None
    assert row.total_loc is None
    assert row.words_per_loc is None
    assert row.partial_loc is False  # not partial — fully unknown
    # CSV renders these as empty strings.
    buf = io.StringIO()
    format_csv([row], buf)
    line = buf.getvalue().splitlines()[1]
    assert line == "2024-W10,1,,,,40,1,"


def test_partial_loc_summed_with_flag(conn: sqlite3.Connection) -> None:
    """Mixed (some fetched, some NULL) → sum knowns and set ``partial_loc=True``."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    for i in (1, 2, 3):
        seed_conversation(conn, f"c{i}")
        seed_human_input(conn, conversation_id=f"c{i}", initial_prompt_words=10)
    # 2 with LOC, 1 NULL.
    fetched_a = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at="2024-03-05T12:00:00Z",
        lines_added=100,
        lines_removed=10,
    )
    fetched_b = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=2,
        merged_at="2024-03-06T12:00:00Z",
        lines_added=200,
        lines_removed=20,
    )
    missing = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=3,
        merged_at="2024-03-07T12:00:00Z",
        lines_added=None,
        lines_removed=None,
    )
    seed_contribution(conn, conversation_id="c1", change_ref_id=fetched_a)
    seed_contribution(conn, conversation_id="c2", change_ref_id=fetched_b)
    seed_contribution(conn, conversation_id="c3", change_ref_id=missing)

    report = aggregate_velocity(conn=conn)
    row = report.rows[0]
    assert row.prs_merged == 3
    # Summed knowns only (100+200=300, 10+20=30, total 330).
    assert row.lines_added == 300
    assert row.lines_removed == 30
    assert row.total_loc == 330
    assert row.partial_loc is True
    assert row.missing_loc_count == 1


def test_include_empty_fills_gaps(conn: sqlite3.Connection) -> None:
    """``include_empty=True`` fills weeks with no merged changes as zero-rows."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_conversation(conn, "c2")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=1)
    seed_human_input(conn, conversation_id="c2", initial_prompt_words=1)
    pr1 = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    pr2 = seed_pr(conn, repo_id=repo_id, pr_number=2, merged_at="2024-03-19T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr1)
    seed_contribution(conn, conversation_id="c2", change_ref_id=pr2)

    report = aggregate_velocity(conn=conn, include_empty=True)
    weeks = [r.week for r in report.rows]
    assert weeks == ["2024-W10", "2024-W11", "2024-W12"]
    # The middle week is empty.
    empty = _row(report.rows, "2024-W11")
    assert empty.prs_merged == 0
    assert empty.lines_added is None
    assert empty.human_words == 0


def test_include_empty_respects_since_until(conn: sqlite3.Connection) -> None:
    """Iteration range honours ``since`` / ``until`` when ``include_empty`` is set."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=1)
    pr_id = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-12T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    since = datetime(2024, 2, 26, tzinfo=timezone.utc)  # ISO week 9
    until = datetime(2024, 3, 25, tzinfo=timezone.utc)  # ISO week 13 boundary
    report = aggregate_velocity(
        conn=conn, since=since, until=until, include_empty=True
    )
    weeks = [r.week for r in report.rows]
    # Weeks 9, 10, 11, 12 should all appear; the actual PR is in W11.
    assert "2024-W09" in weeks
    assert "2024-W11" in weeks
    productive = [r for r in report.rows if r.prs_merged > 0]
    assert len(productive) == 1
    assert productive[0].week == "2024-W11"


def test_repo_filter_excludes_other_repos(conn: sqlite3.Connection) -> None:
    """Filtering by repo drops PRs from other repos."""
    repo_a = seed_repo(conn, canonical_url="https://github.com/team/proj-a")
    repo_b = seed_repo(conn, canonical_url="https://github.com/team/proj-b")
    seed_conversation(conn, "c1")
    seed_conversation(conn, "c2")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=10)
    seed_human_input(conn, conversation_id="c2", initial_prompt_words=20)
    pr_a = seed_pr(conn, repo_id=repo_a, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    pr_b = seed_pr(conn, repo_id=repo_b, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_a)
    seed_contribution(conn, conversation_id="c2", change_ref_id=pr_b)

    report = aggregate_velocity(conn=conn, repo="proj-a")
    assert len(report.rows) == 1
    assert report.rows[0].prs_merged == 1
    assert report.rows[0].human_words == 10  # only c1


def test_repo_filter_unknown_raises_lookup(conn: sqlite3.Connection) -> None:
    """An unrecognised --repo value raises ``LookupError`` for the CLI to catch."""
    seed_repo(conn, canonical_url="https://github.com/team/proj-a")
    with pytest.raises(LookupError):
        aggregate_velocity(conn=conn, repo="nonexistent-repo")


def test_since_until_filters(conn: sqlite3.Connection) -> None:
    """Date range filters drop rows outside [since, until)."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    for i, when in enumerate(
        ["2024-02-15T12:00:00Z", "2024-03-05T12:00:00Z", "2024-04-15T12:00:00Z"]
    ):
        seed_conversation(conn, f"c{i}")
        seed_human_input(conn, conversation_id=f"c{i}", initial_prompt_words=5)
        pr_id = seed_pr(conn, repo_id=repo_id, pr_number=i + 1, merged_at=when)
        seed_contribution(conn, conversation_id=f"c{i}", change_ref_id=pr_id)

    since = datetime(2024, 3, 1, tzinfo=timezone.utc)
    until = datetime(2024, 4, 1, tzinfo=timezone.utc)
    report = aggregate_velocity(conn=conn, since=since, until=until)
    assert len(report.rows) == 1
    assert report.rows[0].week == "2024-W10"


def test_direct_push_counted(conn: sqlite3.Connection) -> None:
    """``change_type='direct_push'`` rows are also aggregated."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=10)
    push_id = seed_direct_push(
        conn,
        repo_id=repo_id,
        commit_range="abc123..def456",
        merged_at="2024-03-05T12:00:00Z",
    )
    seed_contribution(conn, conversation_id="c1", change_ref_id=push_id)

    report = aggregate_velocity(conn=conn)
    assert len(report.rows) == 1
    assert report.rows[0].prs_merged == 1
    assert report.rows[0].lines_added == 50


def test_empty_db_returns_no_rows(conn: sqlite3.Connection) -> None:
    """No change_refs rows → empty report; aggregate function does not crash."""
    report = aggregate_velocity(conn=conn)
    assert report.rows == []
    assert report.totals is not None
    assert report.totals.prs_merged == 0


def test_compute_totals_uses_global_ratio() -> None:
    """The totals row uses ``sum(words) / sum(total_loc)``, NOT the mean."""
    rows = [
        VelocityRow(
            week="2024-W10",
            prs_merged=1,
            lines_added=10,
            lines_removed=0,
            total_loc=10,
            human_words=10,
            human_messages=1,
            words_per_loc=1.00,
        ),
        VelocityRow(
            week="2024-W11",
            prs_merged=1,
            lines_added=1000,
            lines_removed=0,
            total_loc=1000,
            human_words=10,
            human_messages=1,
            words_per_loc=0.01,
        ),
    ]
    totals = compute_totals(rows)
    # Mean of ratios = (1.00 + 0.01) / 2 = 0.505 — wrong.
    # Global ratio = 20 / 1010 = 0.0198 → rounds to 0.02.
    assert totals.words_per_loc == 0.02
    assert totals.prs_merged == 2
    assert totals.lines_added == 1010
    assert totals.total_loc == 1010


def test_compute_totals_handles_all_none_loc() -> None:
    """Totals row keeps ``None`` LOC when no week has populated LOC."""
    rows = [
        VelocityRow(
            week="2024-W10",
            prs_merged=2,
            lines_added=None,
            lines_removed=None,
            total_loc=None,
            human_words=30,
            human_messages=2,
            words_per_loc=None,
        ),
    ]
    totals = compute_totals(rows)
    assert totals.lines_added is None
    assert totals.total_loc is None
    assert totals.words_per_loc is None
    assert totals.human_words == 30


def test_fetch_raw_rows_uses_distinct_subselect(conn: sqlite3.Connection) -> None:
    """Direct test of :func:`fetch_raw_rows` — DISTINCT applied per PR."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_conversation(conn, "c2")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=10)
    seed_human_input(conn, conversation_id="c2", initial_prompt_words=20)
    pr_id = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    # c1 contributes 3 ways; c2 contributes once.
    for ctype in ("created", "pushed", "merged"):
        seed_contribution(
            conn, conversation_id="c1", change_ref_id=pr_id, contribution_type=ctype
        )
    seed_contribution(conn, conversation_id="c2", change_ref_id=pr_id)

    raw = fetch_raw_rows(conn)
    assert len(raw) == 1
    # Words: c1 (10+0) + c2 (20+0) = 30. Without DISTINCT it would be 50.
    assert raw[0]["human_words"] == 30
    assert raw[0]["human_messages"] == 2  # one msg per conv


def test_bucket_by_iso_week_ignores_unparseable_merged_at(conn: sqlite3.Connection) -> None:
    """A bogus ``merged_at`` value is skipped, not crashed on."""

    # Build a fake row payload that mimics sqlite3.Row dict access.
    class _R(dict):
        def __getitem__(self, k):
            return super().__getitem__(k)

    bad = _R(
        change_ref_id=99,
        merged_at="not-a-date",
        lines_added=1,
        lines_removed=0,
        repo_id=1,
        repo_fqn="x/y",
        human_words=0,
        human_messages=0,
    )
    rows = bucket_by_iso_week([bad])
    assert rows == []


def test_aggregate_velocity_requires_conn_or_path() -> None:
    with pytest.raises(ValueError):
        aggregate_velocity()


def test_format_csv_empty_writes_header_only() -> None:
    """Empty input still emits the header line (RFC-4180 friendly)."""
    buf = io.StringIO()
    format_csv([], buf)
    assert (
        buf.getvalue().strip()
        == "week,prs_merged,lines_added,lines_removed,total_loc,human_words,human_messages,words_per_loc"
    )


def test_format_csv_row_shape(conn: sqlite3.Connection) -> None:
    """Round-trip: one PR through aggregate_velocity → format_csv."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=50)
    pr_id = seed_pr(
        conn,
        repo_id=repo_id,
        pr_number=1,
        merged_at="2024-03-05T12:00:00Z",
        lines_added=100,
        lines_removed=20,
    )
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    buf = io.StringIO()
    format_csv(report.rows, buf)
    lines = buf.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("week,")
    assert lines[1] == "2024-W10,1,100,20,120,50,1,0.42"


def test_aggregate_velocity_report_metadata(conn: sqlite3.Connection) -> None:
    """``VelocityReport.metadata`` carries SQL + counts for --verbose."""
    repo_id = seed_repo(conn, canonical_url="https://github.com/x/y")
    seed_conversation(conn, "c1")
    seed_human_input(conn, conversation_id="c1", initial_prompt_words=10)
    pr_id = seed_pr(conn, repo_id=repo_id, pr_number=1, merged_at="2024-03-05T12:00:00Z")
    seed_contribution(conn, conversation_id="c1", change_ref_id=pr_id)

    report = aggregate_velocity(conn=conn)
    assert isinstance(report, VelocityReport)
    assert "SELECT" in report.metadata["sql"].upper()
    assert report.metadata["raw_row_count"] == 1
    assert report.metadata["bucket_count"] == 1
    assert report.metadata["missing_loc_total"] == 0
