"""Weekly conversation count report (issue #92).

CSV export of new-conversation counts bucketed by ISO 8601 week
(``YYYY-Www``, Monday-start), split by source: ``cloud`` and ``cli``.

Pure data layer — no Click imports, no Rich, no filesystem state.
:func:`aggregate_weekly_counts` is the importable surface that
charting (issue #82) is expected to reuse.

Design notes
------------

* The ISO week label is computed in Python via
  :func:`ohtv.analysis.periods.make_week_period`. SQLite's
  ``strftime('%W', ...)`` is GNU/POSIX, not ISO 8601, and
  ``strftime('%V', ...)`` is unreliable across SQLite builds; both
  mis-bucket the 2024-12-30 / 2025-W01 boundary. The companion
  regression test (T-4) locks this in.

* Bucketing is by ``conversations.created_at`` (NOT ``updated_at``),
  matching the "new conversations per week" semantics in the issue
  title. ``updated_at`` would double-count long-running conversations
  whose touch dates cross week boundaries.

* Naming gotcha: the DB stores ``source = 'local'`` for CLI
  conversations (see :mod:`ohtv.sources.base`). The CSV header uses
  ``cli`` instead because that is what the issue title says and what
  reads naturally in a report. The translation happens here, at the
  report layer — every other layer keeps the existing ``local``
  vocabulary.

* Timezone caveat: cloud ``created_at`` is UTC; CLI ``created_at`` is
  whatever the producer wrote, often naive. We assume naive
  timestamps are UTC for bucketing (consistent with the rest of the
  codebase — see AGENTS.md item 5). This is best-effort and can mis-
  bucket conversations created within a few hours of a week boundary
  on machines in non-UTC time zones.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import IO, Iterable, Sequence

from ohtv.analysis.periods import get_week_start, iterate_periods, make_week_period


# CSV column order. ``cli`` comes before ``total`` to match the
# issue body exactly.
CSV_HEADER = ("week", "cloud", "cli", "total")

# DB-side source value for CLI / local conversations.
_DB_SOURCE_LOCAL = "local"
_DB_SOURCE_CLOUD = "cloud"


# Pure SQL — bucketing happens in Python (see module docstring).
_WEEKLY_COUNTS_SQL = """
SELECT created_at, source
FROM conversations
WHERE created_at IS NOT NULL
  AND (:since   IS NULL OR created_at >= :since)
  AND (:until   IS NULL OR created_at <  :until)
  AND (:source  IS NULL OR source = :source)
ORDER BY created_at
"""


@dataclass
class WeeklyCountsRow:
    """One ISO-week bucket of conversation counts.

    ``week_iso`` is the ISO 8601 label ``YYYY-Www`` (zero-padded,
    Monday-start). ``cloud`` and ``cli`` are mutually exclusive
    counts; ``total = cloud + cli``.
    """

    week_iso: str
    cloud: int
    cli: int
    total: int


@dataclass
class WeeklyCountsReport:
    """Container returned by :func:`aggregate_weekly_counts`.

    ``rows`` is in ascending ISO-week order. ``metadata`` is the
    bag the CLI ``--verbose`` path (if any) and downstream charting
    (#82) might consume; today it holds the rendered SQL, the bind
    parameters, and the raw input row count.
    """

    rows: list[WeeklyCountsRow]
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------


def fetch_rows(
    conn: sqlite3.Connection,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    source: str | None = None,
) -> list[sqlite3.Row]:
    """Fetch ``(created_at, source)`` for conversations in range.

    Args:
        conn: SQLite connection (row_factory will be coerced to
            :class:`sqlite3.Row` if unset).
        since: Inclusive lower bound on ``created_at`` (UTC datetime).
        until: Exclusive upper bound on ``created_at`` (UTC datetime).
        source: Optional DB source filter; values are ``'cloud'`` /
            ``'local'``. ``None`` includes both.

    Returns:
        List of rows ordered by ``created_at`` ascending. Rows whose
        ``created_at`` is NULL are filtered out at the SQL layer.
    """
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        _WEEKLY_COUNTS_SQL,
        {
            "since": _to_iso_z(since),
            "until": _to_iso_z(until),
            "source": source,
        },
    )
    return list(cursor.fetchall())


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def _parse_created_at(value: str | None) -> datetime | None:
    """Parse a ``conversations.created_at`` ISO timestamp to UTC.

    Naive timestamps are assumed UTC — see the module-level
    timezone caveat. Returns ``None`` for unparseable / empty input
    so callers can skip defensively.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso_z(dt: datetime | None) -> str | None:
    """Format a UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ`` for SQL bind."""
    if dt is None:
        return None
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_label(d: date) -> str:
    """ISO-week label ``YYYY-Www`` for any date in that week."""
    return make_week_period(get_week_start(d)).iso


def aggregate_weekly_counts(
    rows: Iterable[sqlite3.Row],
    *,
    include_empty: bool = False,
    exclude_current_week: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
    today: date | None = None,
) -> WeeklyCountsReport:
    """Fold ``(created_at, source)`` rows into ISO-week buckets.

    Args:
        rows: Iterable of rows produced by :func:`fetch_rows`. Each
            row must expose ``["created_at"]`` and ``["source"]``.
        include_empty: When True, emit zero-rows for every ISO week
            in the range that has no conversations. Range is bounded
            by ``since`` / ``until`` if given; otherwise by the
            earliest / latest seen row.
        exclude_current_week: When True, drop the row whose
            ``week_iso`` matches today's ISO week (best-effort UTC).
        since: Iteration lower bound (UTC). Used to anchor
            ``include_empty`` zero-fill.
        until: Iteration upper bound (UTC, exclusive). Used to anchor
            ``include_empty`` zero-fill.
        today: Override "today" for ``exclude_current_week``;
            primarily for tests.

    Returns:
        :class:`WeeklyCountsReport` with per-week rows in ascending
        order. Rows with unparseable ``created_at`` are silently
        skipped.
    """
    buckets: dict[str, dict[str, int]] = {}
    earliest: date | None = None
    latest: date | None = None
    raw_count = 0
    skipped = 0

    for row in rows:
        raw_count += 1
        created_at = _parse_created_at(row["created_at"])
        if created_at is None:
            skipped += 1
            continue
        bucket_date = created_at.date()
        if earliest is None or bucket_date < earliest:
            earliest = bucket_date
        if latest is None or bucket_date > latest:
            latest = bucket_date
        label = _iso_label(bucket_date)
        bucket = buckets.setdefault(label, {"cloud": 0, "cli": 0})
        src = row["source"]
        if src == _DB_SOURCE_CLOUD:
            bucket["cloud"] += 1
        elif src == _DB_SOURCE_LOCAL:
            bucket["cli"] += 1
        # Any other source value is silently ignored — keeps the
        # report stable if a new source kind is added later.

    if include_empty:
        # Determine zero-fill range. Honour explicit bounds first;
        # otherwise span the actual data.
        if since is not None:
            range_start = since.astimezone(timezone.utc).date()
        elif earliest is not None:
            range_start = earliest
        else:
            range_start = date.today()
        if until is not None:
            # ``until`` is exclusive; use it directly as the iteration
            # end (iterate_periods will include the week containing
            # range_end). If until is week-aligned, this still
            # includes that week's bucket — that's the intuitive
            # behaviour for a date range.
            range_end = until.astimezone(timezone.utc).date()
        elif latest is not None:
            range_end = latest
        else:
            range_end = date.today()
        if range_end < range_start:
            range_end = range_start
        for period in iterate_periods(range_start, range_end, "week"):
            buckets.setdefault(period.iso, {"cloud": 0, "cli": 0})

    if exclude_current_week:
        ref_today = today if today is not None else datetime.now(timezone.utc).date()
        current_label = _iso_label(ref_today)
        buckets.pop(current_label, None)

    out: list[WeeklyCountsRow] = []
    for label in sorted(buckets):
        b = buckets[label]
        out.append(
            WeeklyCountsRow(
                week_iso=label,
                cloud=b["cloud"],
                cli=b["cli"],
                total=b["cloud"] + b["cli"],
            )
        )

    metadata = {
        "sql": _WEEKLY_COUNTS_SQL,
        "params": {
            "since": _to_iso_z(since),
            "until": _to_iso_z(until),
        },
        "raw_row_count": raw_count,
        "skipped_unparseable": skipped,
        "bucket_count": len(out),
    }
    return WeeklyCountsReport(rows=out, metadata=metadata)


# ---------------------------------------------------------------------------
# CSV emission
# ---------------------------------------------------------------------------


def format_csv(
    rows: Sequence[WeeklyCountsRow],
    file: IO[str],
    *,
    header: bool = True,
) -> None:
    """Write rows as RFC 4180 CSV to ``file``.

    Always uses ``\\r\\n`` line terminators (RFC 4180 default for
    stdlib :mod:`csv`). The header row is included unless
    ``header=False`` — but the CLI never disables it; the keyword is
    there only for callers that want to splice multiple reports.
    """
    writer = csv.writer(file)
    if header:
        writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow([row.week_iso, row.cloud, row.cli, row.total])
