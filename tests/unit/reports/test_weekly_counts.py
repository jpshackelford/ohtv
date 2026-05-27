"""Unit tests for :mod:`ohtv.reports.weekly_counts` (issue #92).

Exercises the row-shaping + bucketing logic against an in-memory
SQLite DB with the real migration history applied. No DB mocks.

The ``conn`` fixture lives in ``conftest.py``.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import date, datetime, timezone

from ohtv.reports.weekly_counts import (
    CSV_HEADER,
    WeeklyCountsReport,
    WeeklyCountsRow,
    aggregate_weekly_counts,
    fetch_rows,
    format_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_conv(
    conn: sqlite3.Connection,
    conv_id: str,
    *,
    created_at: str | None,
    source: str = "cloud",
) -> None:
    """Minimal conversations insert covering the columns this report touches."""
    conn.execute(
        "INSERT INTO conversations (id, location, created_at, source) "
        "VALUES (?, ?, ?, ?)",
        (conv_id, f"/tmp/{conv_id}", created_at, source),
    )
    conn.commit()


def _aggregate(
    conn: sqlite3.Connection, **kwargs
) -> WeeklyCountsReport:
    """Run fetch_rows + aggregate_weekly_counts in one shot."""
    rows = fetch_rows(
        conn,
        since=kwargs.pop("since", None),
        until=kwargs.pop("until", None),
        source=kwargs.pop("source", None),
    )
    return aggregate_weekly_counts(rows, **kwargs)


def _row(report: WeeklyCountsReport, week: str) -> WeeklyCountsRow:
    for r in report.rows:
        if r.week_iso == week:
            return r
    raise AssertionError(
        f"week {week!r} not in {[r.week_iso for r in report.rows]}"
    )


# ---------------------------------------------------------------------------
# T-1
# ---------------------------------------------------------------------------


def test_single_conversation_one_week(conn: sqlite3.Connection) -> None:
    """One cloud conv → one row, cloud=1 cli=0 total=1."""
    _insert_conv(conn, "c1", created_at="2024-03-05T12:00:00Z", source="cloud")
    report = _aggregate(conn)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week_iso == "2024-W10"
    assert row.cloud == 1
    assert row.cli == 0
    assert row.total == 1


# ---------------------------------------------------------------------------
# T-2
# ---------------------------------------------------------------------------


def test_mixed_sources_same_week(conn: sqlite3.Connection) -> None:
    """3 cloud + 2 local in the same ISO week → cloud=3 cli=2 total=5."""
    for i in range(3):
        _insert_conv(
            conn, f"cloud{i}", created_at=f"2024-03-05T1{i}:00:00Z", source="cloud"
        )
    for i in range(2):
        _insert_conv(
            conn, f"cli{i}", created_at=f"2024-03-06T1{i}:00:00Z", source="local"
        )
    report = _aggregate(conn)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week_iso == "2024-W10"
    assert row.cloud == 3
    assert row.cli == 2
    assert row.total == 5


# ---------------------------------------------------------------------------
# T-3
# ---------------------------------------------------------------------------


def test_multiple_weeks_chronological_order(conn: sqlite3.Connection) -> None:
    """Three weeks of data → three rows in ascending ISO-week order."""
    _insert_conv(conn, "c1", created_at="2024-03-05T12:00:00Z", source="cloud")  # W10
    _insert_conv(conn, "c2", created_at="2024-03-12T12:00:00Z", source="cloud")  # W11
    _insert_conv(conn, "c3", created_at="2024-03-19T12:00:00Z", source="cloud")  # W12
    report = _aggregate(conn)
    assert [r.week_iso for r in report.rows] == ["2024-W10", "2024-W11", "2024-W12"]
    for r in report.rows:
        assert r.cloud == 1
        assert r.cli == 0
        assert r.total == 1


# ---------------------------------------------------------------------------
# T-4 — Year-boundary regression (mandatory)
# ---------------------------------------------------------------------------


def test_iso_week_boundary_2024_12_30(conn: sqlite3.Connection) -> None:
    """2024-12-30 (a Monday) belongs to ISO 2025-W01, not 2024-W53.

    SQLite ``strftime('%W', ...)`` reports week 53. This test locks
    in the Python-side ``isocalendar()`` round-trip used by
    :func:`make_week_period`.
    """
    _insert_conv(conn, "c1", created_at="2024-12-30T12:00:00Z", source="cloud")
    _insert_conv(conn, "c2", created_at="2024-12-31T23:59:59Z", source="local")
    report = _aggregate(conn)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week_iso == "2025-W01"
    assert row.cloud == 1
    assert row.cli == 1
    assert row.total == 2


# ---------------------------------------------------------------------------
# T-5 — Sunday→Monday crossover
# ---------------------------------------------------------------------------


def test_sunday_to_monday_crossover(conn: sqlite3.Connection) -> None:
    """A Sunday-night conv and a Monday-morning conv land in different weeks."""
    # 2025-01-05 is Sunday → 2025-W01. 2025-01-06 is Monday → 2025-W02.
    _insert_conv(conn, "c_sun", created_at="2025-01-05T23:00:00Z", source="cloud")
    _insert_conv(conn, "c_mon", created_at="2025-01-06T01:00:00Z", source="cloud")
    report = _aggregate(conn)
    assert [r.week_iso for r in report.rows] == ["2025-W01", "2025-W02"]
    assert _row(report, "2025-W01").total == 1
    assert _row(report, "2025-W02").total == 1


# ---------------------------------------------------------------------------
# T-6 — include_empty
# ---------------------------------------------------------------------------


def test_include_empty_fills_gaps(conn: sqlite3.Connection) -> None:
    """W10 + W12 with include_empty=True → 3 rows (W10, W11=zeros, W12)."""
    _insert_conv(conn, "c1", created_at="2024-03-05T12:00:00Z", source="cloud")  # W10
    _insert_conv(conn, "c2", created_at="2024-03-19T12:00:00Z", source="cloud")  # W12
    report = _aggregate(conn, include_empty=True)
    weeks = [r.week_iso for r in report.rows]
    assert weeks == ["2024-W10", "2024-W11", "2024-W12"]
    filler = _row(report, "2024-W11")
    assert filler.cloud == 0
    assert filler.cli == 0
    assert filler.total == 0


# ---------------------------------------------------------------------------
# T-7 — exclude_current_week
# ---------------------------------------------------------------------------


def test_exclude_current_week_drops_today(conn: sqlite3.Connection) -> None:
    """A conv last week + a conv this week, --exclude-current-week → 1 row."""
    # Anchor "today" deterministically. Pick a Wednesday so "last week"
    # is unambiguous.
    today = date(2025, 3, 19)  # Wed of 2025-W12
    last_week_day = date(2025, 3, 10)  # Mon of 2025-W11
    _insert_conv(conn, "c_last", created_at=f"{last_week_day}T12:00:00Z", source="cloud")
    _insert_conv(conn, "c_today", created_at=f"{today}T12:00:00Z", source="cloud")
    rows = fetch_rows(conn)
    report = aggregate_weekly_counts(rows, exclude_current_week=True, today=today)
    assert [r.week_iso for r in report.rows] == ["2025-W11"]
    assert _row(report, "2025-W11").cloud == 1


# ---------------------------------------------------------------------------
# T-8 — source filter
# ---------------------------------------------------------------------------


def test_source_filter_cli(conn: sqlite3.Connection) -> None:
    """source='local' filter → cloud column is 0 for every row."""
    for i in range(3):
        _insert_conv(
            conn, f"cloud{i}", created_at=f"2024-03-05T1{i}:00:00Z", source="cloud"
        )
    for i in range(2):
        _insert_conv(
            conn, f"cli{i}", created_at=f"2024-03-05T2{i}:00:00Z", source="local"
        )
    report = _aggregate(conn, source="local")
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.cloud == 0
    assert row.cli == 2
    assert row.total == 2


# ---------------------------------------------------------------------------
# T-9 — since/until bounds
# ---------------------------------------------------------------------------


def test_since_until_bounds(conn: sqlite3.Connection) -> None:
    """``since`` is inclusive, ``until`` is exclusive.

    Boundary-on-since lands inside; boundary-on-until lands outside.
    """
    _insert_conv(conn, "c_before", created_at="2024-03-04T12:00:00Z", source="cloud")
    _insert_conv(conn, "c_on_since", created_at="2024-03-05T00:00:00Z", source="cloud")
    _insert_conv(conn, "c_inside", created_at="2024-03-06T12:00:00Z", source="cloud")
    _insert_conv(conn, "c_on_until", created_at="2024-03-12T00:00:00Z", source="cloud")
    _insert_conv(conn, "c_after", created_at="2024-03-13T00:00:00Z", source="cloud")

    since_dt = datetime(2024, 3, 5, tzinfo=timezone.utc)
    until_dt = datetime(2024, 3, 12, tzinfo=timezone.utc)
    report = _aggregate(conn, since=since_dt, until=until_dt)

    # c_on_since + c_inside are in W10; nothing else falls inside.
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week_iso == "2024-W10"
    assert row.cloud == 2
    assert row.cli == 0
    assert row.total == 2


# ---------------------------------------------------------------------------
# T-10 — NULL created_at silently skipped
# ---------------------------------------------------------------------------


def test_null_created_at_skipped(conn: sqlite3.Connection) -> None:
    """``created_at IS NULL`` rows are filtered at the SQL layer.

    No crash, no row, no count contribution.
    """
    _insert_conv(conn, "c_null", created_at=None, source="cloud")
    _insert_conv(conn, "c_ok", created_at="2024-03-05T12:00:00Z", source="cloud")
    report = _aggregate(conn)
    assert len(report.rows) == 1
    assert report.rows[0].cloud == 1
    assert report.rows[0].total == 1
    # And the SQL-layer skip is the reason — the bucket loop in
    # Python never sees the row at all.
    assert report.metadata["raw_row_count"] == 1
    assert report.metadata["skipped_unparseable"] == 0


# ---------------------------------------------------------------------------
# T-11 — naive timestamp treated as UTC
# ---------------------------------------------------------------------------


def test_naive_timestamp_treated_as_utc(conn: sqlite3.Connection) -> None:
    """A local-source conv with a naive ISO timestamp is bucketed as if UTC.

    This is the documented behaviour from the module docstring and
    matches the codebase's treatment of naive local timestamps
    (AGENTS.md item 5).
    """
    _insert_conv(conn, "c_naive", created_at="2024-03-05T12:00:00", source="local")
    report = _aggregate(conn)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.week_iso == "2024-W10"
    assert row.cli == 1
    assert row.cloud == 0


# ---------------------------------------------------------------------------
# T-12 — CSV header uses `cli` not `local`
# ---------------------------------------------------------------------------


def test_csv_header_uses_cli_not_local() -> None:
    """The CSV header must be exactly ``week,cloud,cli,total``.

    Regression for the naming translation between the DB column
    value (``local``) and the user-facing CSV column (``cli``).
    """
    buf = io.StringIO()
    rows = [WeeklyCountsRow(week_iso="2024-W10", cloud=3, cli=2, total=5)]
    format_csv(rows, buf)
    output = buf.getvalue()
    first_line = output.splitlines()[0]
    assert first_line == "week,cloud,cli,total"
    # And the constant agrees.
    assert CSV_HEADER == ("week", "cloud", "cli", "total")
    # Sanity: the data row uses the same column order.
    assert output.splitlines()[1] == "2024-W10,3,2,5"


# ---------------------------------------------------------------------------
# Extra: format_csv on empty rows still emits header
# ---------------------------------------------------------------------------


def test_format_csv_empty_rows_emits_header_only() -> None:
    """An empty rows list still produces the header line."""
    buf = io.StringIO()
    format_csv([], buf)
    assert buf.getvalue().splitlines() == ["week,cloud,cli,total"]
