"""Weekly velocity report: merged PRs/pushes × LOC × human input.

Aggregates rows from the contributions schema (migration 016 +
migration 017's wider status enum) into ISO-week buckets. Pure data
layer — no Click imports, no Rich imports beyond the optional
``format_table`` helper, no filesystem state. The bucketing entry
point :func:`aggregate_velocity` is the importable surface that
charting (issue #82) reuses.

Design notes:

* The week label is always ISO 8601 (``YYYY-Www``). SQLite's
  ``strftime('%W', ...)`` is the GNU/POSIX week number, not ISO —
  e.g., 2024-12-30 is ``2024-W53`` under ``%W`` but ``2025-W01``
  under ISO. We always compute the label in Python via
  :meth:`datetime.date.isocalendar`.

* ``conversation_contributions`` can have multiple rows for the same
  ``(change_ref_id, conversation_id)`` pair (one per ``contribution_type``:
  created / pushed / merged). To avoid triple-counting one
  conversation's words against a single PR we collapse the join to
  DISTINCT ``(change_ref_id, conversation_id)`` pairs in a sub-select
  before joining ``conversation_human_input``.

* ``initial_prompt_source`` policy:

  - ``'human'``     → words = ``initial_prompt_words + followup_word_count``,
                     msgs  = ``1 + followup_message_count``
  - ``'automation'``→ words = ``followup_word_count``,
                     msgs  = ``followup_message_count``
  - ``'unknown'``   → treated as ``'human'`` (optimistic default;
                     see issue #83 for proper classification)

* LOC NULL handling per bucket:

  - All rows NULL → ``+Lines / -Lines / Total`` are *None* (callers
    render this as ``-`` / empty).
  - Some rows NULL, some populated → sum what is known and set
    ``partial_loc=True`` so ``--verbose`` can flag the bucket.
  - All rows populated → straight sum, ``partial_loc=False``.

* ``Words/LOC`` ratio is ``None`` whenever ``total_loc`` is ``0`` /
  ``None``. The totals row recomputes the ratio from
  ``sum(words) / sum(total_loc)`` rather than averaging per-week
  ratios (per the issue acceptance criteria).
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Iterable, Sequence

from ohtv.analysis.periods import iterate_periods


# Pure SQL query — Python performs ISO-week bucketing afterwards.
# The DISTINCT sub-select collapses (created / pushed / merged) rows
# for the same conversation against the same change_ref to one row,
# which is the natural de-dup boundary the issue calls out.
_VELOCITY_SQL = """
SELECT
    cr.id           AS change_ref_id,
    cr.merged_at    AS merged_at,
    cr.lines_added  AS lines_added,
    cr.lines_removed AS lines_removed,
    cr.repo_id      AS repo_id,
    r.fqn           AS repo_fqn,
    COALESCE(SUM(
        CASE chi.initial_prompt_source
            WHEN 'human'      THEN chi.initial_prompt_words + chi.followup_word_count
            WHEN 'automation' THEN chi.followup_word_count
            WHEN 'unknown'    THEN chi.initial_prompt_words + chi.followup_word_count
            ELSE 0
        END
    ), 0) AS human_words,
    COALESCE(SUM(
        CASE chi.initial_prompt_source
            WHEN 'human'      THEN 1 + chi.followup_message_count
            WHEN 'automation' THEN chi.followup_message_count
            WHEN 'unknown'    THEN 1 + chi.followup_message_count
            ELSE 0
        END
    ), 0) AS human_messages
FROM change_refs cr
JOIN repositories r ON r.id = cr.repo_id
LEFT JOIN (
    SELECT DISTINCT change_ref_id, conversation_id
    FROM conversation_contributions
) dcc ON dcc.change_ref_id = cr.id
LEFT JOIN conversation_human_input chi
       ON chi.conversation_id = dcc.conversation_id
WHERE cr.status = 'merged'
  AND cr.change_type IN ('pr', 'direct_push')
  AND (:repo_id IS NULL OR cr.repo_id = :repo_id)
  AND (:since   IS NULL OR cr.merged_at >= :since)
  AND (:until   IS NULL OR cr.merged_at <  :until)
GROUP BY cr.id
ORDER BY cr.merged_at
"""


@dataclass
class VelocityRow:
    """One aggregated bucket of merged changes (or the totals row).

    For per-week rows, ``week`` is the ISO label ``YYYY-Www``. For the
    totals row, ``week`` is ``"Total"``.

    Numeric fields use ``None`` to mean "unknown / undefined" (cell
    renders as ``-`` / empty). ``0`` is a real value (e.g., a real
    week with zero merged PRs under ``--include-empty``).
    """

    week: str
    prs_merged: int
    lines_added: int | None
    lines_removed: int | None
    total_loc: int | None
    human_words: int
    human_messages: int
    words_per_loc: float | None
    partial_loc: bool = False
    # Number of merged change_refs in the bucket with NULL lines_added.
    # Useful for --verbose footnotes; defaults to 0.
    missing_loc_count: int = 0

    @classmethod
    def from_csv_dict(cls, row: dict[str, str]) -> "VelocityRow":
        """Build a :class:`VelocityRow` from a ``csv.DictReader`` row.

        Mirrors the columns written by :func:`format_csv`. Empty
        strings round-trip to ``None`` for the optional numeric
        fields (``lines_added`` / ``lines_removed`` / ``total_loc`` /
        ``words_per_loc``). ``partial_loc`` and ``missing_loc_count``
        are not part of the CSV surface and default to their
        dataclass defaults.

        Used by the standalone ``scripts/chart_velocity.py`` shim
        (issue #82) which renders a chart directly from a CSV pipe.
        """

        def _opt_int(value: str | None) -> int | None:
            if value is None or value == "":
                return None
            return int(value)

        def _opt_float(value: str | None) -> float | None:
            if value is None or value == "":
                return None
            return float(value)

        return cls(
            week=row["week"],
            prs_merged=int(row["prs_merged"]),
            lines_added=_opt_int(row.get("lines_added")),
            lines_removed=_opt_int(row.get("lines_removed")),
            total_loc=_opt_int(row.get("total_loc")),
            human_words=int(row["human_words"]),
            human_messages=int(row["human_messages"]),
            words_per_loc=_opt_float(row.get("words_per_loc")),
        )


@dataclass
class VelocityReport:
    """Container returned by :func:`aggregate_velocity`.

    Bundles per-week rows, the optional totals row, and a metadata
    bag that the ``--verbose`` CLI path consumes (raw SQL, per-week
    raw counts, total raw PR count, etc.).
    """

    rows: list[VelocityRow]
    totals: VelocityRow | None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------


def fetch_raw_rows(
    conn: sqlite3.Connection,
    *,
    repo_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[sqlite3.Row]:
    """Fetch one row per merged ``change_ref`` joined to human-input.

    Args:
        conn: SQLite connection (must have row_factory = sqlite3.Row
            for dict-style access).
        repo_id: Optional ``repositories.id`` to restrict to a single
            repo. ``None`` includes all repos.
        since: Optional ISO-format lower bound on ``merged_at``
            (inclusive). Strings compare lexicographically when both
            sides are ISO 8601 with consistent timezone offsets.
        until: Optional ISO-format upper bound on ``merged_at``
            (exclusive — see issue spec).

    Returns:
        List of ``sqlite3.Row`` rows in ``merged_at`` ascending order.
    """
    # Bind on raw=None when the caller is dict-style only.
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        _VELOCITY_SQL,
        {"repo_id": repo_id, "since": since, "until": until},
    )
    return list(cursor.fetchall())


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def _parse_merged_at(value: str | None) -> datetime | None:
    """Parse a ``merged_at`` ISO timestamp into a tz-aware UTC datetime.

    GitHub timestamps look like ``2024-05-01T12:34:56Z``. We accept
    that and also the ``+00:00`` form. Naive timestamps (no tz info)
    are assumed UTC because every producer in this codebase normalises
    to UTC before persistence.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    # Python 3.11+ handles "Z" via fromisoformat. Older 3.10 doesn't,
    # but we can't tell which is in use — be defensive.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # Fall back: split off tz if odd format.
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_week_label(dt: datetime) -> str:
    """Return ISO-8601 week label ``YYYY-Www`` (zero-padded)."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _ratio_or_none(numerator: int | float | None, denominator: int | float | None) -> float | None:
    """Return ``numerator / denominator`` rounded to 2 decimals, or ``None``."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return round(numerator / denominator, 2)


def bucket_by_iso_week(
    raw_rows: Iterable[sqlite3.Row],
    *,
    include_empty: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[VelocityRow]:
    """Fold per-change_ref rows into ISO-week buckets.

    Args:
        raw_rows: Iterable of rows produced by :func:`fetch_raw_rows`.
        include_empty: When True, emit zero-rows for weeks in the
            iteration range that have no merged changes.
        since: Iteration lower bound (UTC datetime). Only used when
            ``include_empty`` is True. Defaults to the week of the
            earliest row.
        until: Iteration upper bound (UTC datetime, exclusive). Only
            used when ``include_empty`` is True. Defaults to the week
            of the latest row (or "today" if no rows).

    Returns:
        List of :class:`VelocityRow` in ascending week order.
    """
    buckets: dict[str, dict] = {}
    earliest: datetime | None = None
    latest: datetime | None = None

    for row in raw_rows:
        merged_at = _parse_merged_at(row["merged_at"])
        if merged_at is None:
            # A merged change_ref should always have merged_at populated,
            # but skip defensively rather than crashing on bad data.
            continue
        if earliest is None or merged_at < earliest:
            earliest = merged_at
        if latest is None or merged_at > latest:
            latest = merged_at
        label = _iso_week_label(merged_at)
        bucket = buckets.setdefault(
            label,
            {
                "prs_merged": 0,
                "lines_added_sum": 0,
                "lines_removed_sum": 0,
                "any_loc": False,
                "missing_loc": 0,
                "human_words": 0,
                "human_messages": 0,
            },
        )
        bucket["prs_merged"] += 1
        if row["lines_added"] is None:
            bucket["missing_loc"] += 1
        else:
            bucket["any_loc"] = True
            bucket["lines_added_sum"] += int(row["lines_added"])
            bucket["lines_removed_sum"] += int(row["lines_removed"] or 0)
        bucket["human_words"] += int(row["human_words"] or 0)
        bucket["human_messages"] += int(row["human_messages"] or 0)

    if include_empty:
        # Determine iteration range. Honour explicit bounds first;
        # otherwise span the actual data.
        if since is not None:
            range_start = since.astimezone(timezone.utc).date()
        elif earliest is not None:
            range_start = earliest.astimezone(timezone.utc).date()
        else:
            range_start = date.today()
        if until is not None:
            # `until` is the exclusive upper bound; back off one day
            # so the final week of the range is included in iteration.
            end_dt = until.astimezone(timezone.utc) - timedelta(days=1)
            range_end = end_dt.date()
        elif latest is not None:
            range_end = latest.astimezone(timezone.utc).date()
        else:
            range_end = date.today()
        if range_end < range_start:
            range_end = range_start
        for period in iterate_periods(range_start, range_end, "week"):
            label = period.iso
            if label not in buckets:
                buckets[label] = {
                    "prs_merged": 0,
                    "lines_added_sum": 0,
                    "lines_removed_sum": 0,
                    "any_loc": False,
                    "missing_loc": 0,
                    "human_words": 0,
                    "human_messages": 0,
                }

    out: list[VelocityRow] = []
    for label in sorted(buckets):
        b = buckets[label]
        prs = b["prs_merged"]
        if prs == 0:
            # An include-empty filler week — keep LOC unknown rather
            # than reporting 0, to avoid implying we know the answer.
            lines_added: int | None = None
            lines_removed: int | None = None
            total_loc: int | None = None
            partial = False
        elif not b["any_loc"]:
            # Every row in the bucket had NULL lines_added.
            lines_added = None
            lines_removed = None
            total_loc = None
            partial = False
        else:
            lines_added = b["lines_added_sum"]
            lines_removed = b["lines_removed_sum"]
            total_loc = lines_added + lines_removed
            partial = b["missing_loc"] > 0
        out.append(
            VelocityRow(
                week=label,
                prs_merged=prs,
                lines_added=lines_added,
                lines_removed=lines_removed,
                total_loc=total_loc,
                human_words=b["human_words"],
                human_messages=b["human_messages"],
                words_per_loc=_ratio_or_none(b["human_words"], total_loc),
                partial_loc=partial,
                missing_loc_count=b["missing_loc"],
            )
        )
    return out


def compute_totals(rows: Sequence[VelocityRow]) -> VelocityRow:
    """Roll a list of week rows into a single totals row.

    ``words_per_loc`` is ``sum(words) / sum(total_loc)`` — NOT the
    mean of per-week ratios — per the issue acceptance criteria.
    """
    if not rows:
        return VelocityRow(
            week="Total",
            prs_merged=0,
            lines_added=None,
            lines_removed=None,
            total_loc=None,
            human_words=0,
            human_messages=0,
            words_per_loc=None,
        )
    prs = sum(r.prs_merged for r in rows)
    words = sum(r.human_words for r in rows)
    msgs = sum(r.human_messages for r in rows)
    # If any week has a populated LOC sum, fold it in; if every week
    # is None, leave totals as None too. partial_loc bubbles up if
    # ANY week was partial OR if we have a mix of populated and None.
    populated = [r for r in rows if r.lines_added is not None]
    if not populated:
        return VelocityRow(
            week="Total",
            prs_merged=prs,
            lines_added=None,
            lines_removed=None,
            total_loc=None,
            human_words=words,
            human_messages=msgs,
            words_per_loc=None,
        )
    lines_added = sum(int(r.lines_added or 0) for r in populated)
    lines_removed = sum(int(r.lines_removed or 0) for r in populated)
    total_loc = lines_added + lines_removed
    partial = any(r.partial_loc for r in rows) or len(populated) < len(
        [r for r in rows if r.prs_merged > 0]
    )
    return VelocityRow(
        week="Total",
        prs_merged=prs,
        lines_added=lines_added,
        lines_removed=lines_removed,
        total_loc=total_loc,
        human_words=words,
        human_messages=msgs,
        words_per_loc=_ratio_or_none(words, total_loc),
        partial_loc=partial,
    )


# ---------------------------------------------------------------------------
# Top-level entry point (importable from non-CLI code, e.g. issue #82)
# ---------------------------------------------------------------------------


def aggregate_velocity(
    db_path: Path | str | None = None,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    repo: str | None = None,
    include_empty: bool = False,
    conn: sqlite3.Connection | None = None,
) -> VelocityReport:
    """Aggregate merged PRs/pushes into weekly velocity rows.

    Either ``conn`` *or* ``db_path`` must be provided. Passing
    ``conn`` is the path tests + downstream callers (like the
    charting command, issue #82) use to avoid re-opening the
    SQLite file.

    Args:
        db_path: Path to ``index.db``. Ignored if ``conn`` is set.
        since: Lower bound on ``merged_at`` (inclusive, UTC).
        until: Upper bound on ``merged_at`` (exclusive, UTC).
        repo: Optional repo filter. Accepts URL, FQN, or short name —
            normalised through the same path used by ``list --repo``
            / ``refs --repo`` (:class:`RepoStore`).
        include_empty: If True, emit zero-rows for weeks with no
            merged changes (still bounded by ``since`` / ``until``).
        conn: Optional pre-opened SQLite connection.

    Returns:
        :class:`VelocityReport` containing per-week rows, totals row,
        and ``metadata`` with the rendered SQL and raw row counts
        (useful for ``--verbose``).

    Raises:
        ValueError: If neither ``conn`` nor ``db_path`` is provided.
        LookupError: If ``repo`` is given but does not resolve to a
            unique known repository.
    """
    if conn is None and db_path is None:
        raise ValueError("aggregate_velocity requires conn or db_path")

    owns_conn = conn is None
    if conn is None:
        assert db_path is not None  # for type-checkers
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

    try:
        repo_id, repo_label = _resolve_repo(conn, repo)

        # SQLite stores merged_at as ISO-8601 strings. Compare as
        # strings — both sides must share the same Z/offset format,
        # so normalise to "Z" (the GitHub canonical form).
        since_str = _to_iso_z(since)
        until_str = _to_iso_z(until)

        raw_rows = fetch_raw_rows(
            conn,
            repo_id=repo_id,
            since=since_str,
            until=until_str,
        )

        rows = bucket_by_iso_week(
            raw_rows,
            include_empty=include_empty,
            since=since,
            until=until,
        )
        totals = compute_totals([r for r in rows if r.prs_merged > 0])

        metadata = {
            "sql": _VELOCITY_SQL,
            "params": {
                "repo_id": repo_id,
                "since": since_str,
                "until": until_str,
            },
            "repo_label": repo_label,
            "raw_row_count": len(raw_rows),
            "bucket_count": len(rows),
            "missing_loc_total": sum(r.missing_loc_count for r in rows),
        }
        return VelocityReport(rows=rows, totals=totals, metadata=metadata)
    finally:
        if owns_conn:
            conn.close()


def _to_iso_z(dt: datetime | None) -> str | None:
    """Format a UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ`` for SQL bind.

    Returning ``None`` short-circuits the WHERE clause via the
    ``IS NULL`` guard.
    """
    if dt is None:
        return None
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_repo(
    conn: sqlite3.Connection, repo: str | None
) -> tuple[int | None, str | None]:
    """Resolve a user-provided repo filter to ``(repo_id, fqn)``.

    Accepts the same shapes as ``list --repo`` and ``refs --repo``:
    canonical URL, FQN (``owner/repo``), or a short name. Single
    match → its ``id``; zero matches → :class:`LookupError`;
    multiple matches → :class:`LookupError` listing candidates.
    """
    if repo is None:
        return None, None

    from ohtv.db.stores import RepoStore

    target = repo.strip()
    repo_store = RepoStore(conn)
    matched = None
    if "://" in target:
        matched = repo_store.get_by_url(target)
        candidates = [matched] if matched else []
    else:
        candidates = list(repo_store.search_by_name(target))
        if len(candidates) == 1:
            matched = candidates[0]

    if not candidates:
        raise LookupError(
            f"--repo {target!r} did not match any known repository "
            "(run `ohtv db scan` first)."
        )
    if matched is None:
        # >1 candidates
        names = ", ".join(c.fqn for c in candidates[:5])
        raise LookupError(
            f"--repo {target!r} matched {len(candidates)} repos: {names}"
        )
    return matched.id, matched.fqn


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


_TABLE_HEADERS = ["Week", "PRs", "+Lines", "-Lines", "Total", "Words", "Msgs", "Words/LOC"]
_CSV_HEADERS = [
    "week",
    "prs_merged",
    "lines_added",
    "lines_removed",
    "total_loc",
    "human_words",
    "human_messages",
    "words_per_loc",
]


def _fmt_int(value: int | None, blank: str) -> str:
    if value is None:
        return blank
    return f"{value}"


def _fmt_ratio(value: float | None, blank: str) -> str:
    if value is None:
        return blank
    return f"{value:.2f}"


def format_table(
    rows: Sequence[VelocityRow],
    totals: VelocityRow | None,
    console,
    *,
    show_totals: bool = True,
) -> None:
    """Render a Rich table to ``console``.

    Numeric columns are right-aligned. ``-`` is used for unknown
    cells (NULL LOC, undefined ratio). When ``show_totals`` is True
    AND ``totals`` is non-None, a totals row is appended with a
    separator.
    """
    from rich.table import Table

    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Week", style="cyan", no_wrap=True)
    table.add_column("PRs", justify="right")
    table.add_column("+Lines", justify="right")
    table.add_column("-Lines", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Words", justify="right")
    table.add_column("Msgs", justify="right")
    table.add_column("Words/LOC", justify="right")

    blank = "-"
    for r in rows:
        table.add_row(
            r.week,
            _fmt_int(r.prs_merged, blank),
            _fmt_int(r.lines_added, blank),
            _fmt_int(r.lines_removed, blank),
            _fmt_int(r.total_loc, blank),
            _fmt_int(r.human_words, blank),
            _fmt_int(r.human_messages, blank),
            _fmt_ratio(r.words_per_loc, blank),
        )
    if show_totals and totals is not None and rows:
        # `end_section=True` on the previous row would draw the
        # separator; easier: re-add a styled total row with the
        # section divider via a Rich rule above it.
        table.add_section()
        table.add_row(
            f"[bold]{totals.week}[/bold]",
            f"[bold]{_fmt_int(totals.prs_merged, blank)}[/bold]",
            f"[bold]{_fmt_int(totals.lines_added, blank)}[/bold]",
            f"[bold]{_fmt_int(totals.lines_removed, blank)}[/bold]",
            f"[bold]{_fmt_int(totals.total_loc, blank)}[/bold]",
            f"[bold]{_fmt_int(totals.human_words, blank)}[/bold]",
            f"[bold]{_fmt_int(totals.human_messages, blank)}[/bold]",
            f"[bold]{_fmt_ratio(totals.words_per_loc, blank)}[/bold]",
        )
    console.print(table)


def format_csv(rows: Sequence[VelocityRow], stream: IO[str]) -> None:
    """Write a header-only-style CSV (no totals row, no separators).

    Empty / unknown cells render as the empty string (RFC 4180
    friendly). Caller is responsible for passing a writable stream
    (e.g., ``sys.stdout`` or a file opened with ``newline=""``).
    """
    writer = csv.writer(stream)
    writer.writerow(_CSV_HEADERS)
    for r in rows:
        writer.writerow(
            [
                r.week,
                r.prs_merged,
                "" if r.lines_added is None else r.lines_added,
                "" if r.lines_removed is None else r.lines_removed,
                "" if r.total_loc is None else r.total_loc,
                r.human_words,
                r.human_messages,
                "" if r.words_per_loc is None else f"{r.words_per_loc:.2f}",
            ]
        )


__all__ = [
    "VelocityRow",
    "VelocityReport",
    "fetch_raw_rows",
    "bucket_by_iso_week",
    "compute_totals",
    "aggregate_velocity",
    "format_table",
    "format_csv",
]
