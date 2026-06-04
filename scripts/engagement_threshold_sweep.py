"""Engagement-threshold tuning sweep — Issue #163.

Re-computes the engagement metric for every conversation in the local
DB at a fixed set of candidate thresholds, and emits two CSVs that can
be plotted offline to pick the empirically-grounded ``T``:

* ``--out totals.csv`` — one row per threshold with the per-corpus
  totals: number of conversations with any engagement, sum of
  engaged seconds, total conversation duration, ratio.
* ``--gap-histogram gaps.csv`` — one row per (preceding-event → user
  message) gap across the corpus. Plotting a histogram of the
  ``gap_seconds`` column reveals the trough between the "human
  reaction time" mode and the "came back later" mode.

The sweep does NOT mutate the ``conversation_engagement`` table — each
threshold is computed in-memory from the on-disk event files. Re-running
is safe and cheap (O(events) per conversation per threshold).

Usage::

    uv run python -m scripts.engagement_threshold_sweep \\
        --out engagement_totals.csv \\
        --gap-histogram engagement_gaps.csv

    # Custom threshold set (in minutes):
    uv run python -m scripts.engagement_threshold_sweep -t 6 8 10 12 14

    # Filter to one repository / source:
    uv run python -m scripts.engagement_threshold_sweep --source cloud
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ohtv.db import get_ready_connection
from ohtv.db.stages.engagement import (
    _parse_timestamp,
    compute_engagement,
)

DEFAULT_MINUTES = [6, 8, 12, 14, 16, 18, 20, 22, 24, 26, 28]


def _iter_events(conv_location: str) -> list[dict]:
    events_dir = Path(conv_location) / "events"
    if not events_dir.exists():
        return []
    out: list[dict] = []
    for f in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _list_conversations(conn, source: str | None) -> list[tuple[str, str]]:
    """Return (id, location) pairs from the DB, optionally filtered by source."""
    sql = "SELECT id, location FROM conversations WHERE location IS NOT NULL"
    params: list[object] = []
    if source:
        sql += " AND source = ?"
        params.append(source)
    cur = conn.execute(sql, params)
    return [(row[0], row[1]) for row in cur.fetchall()]


def _user_message_gaps(events: list[dict]) -> list[float]:
    """Gap in seconds from each follow-up user message to its preceding event.

    Only follow-up messages (i.e. not the first user message) are emitted.
    Malformed events / unparseable timestamps are skipped.
    """
    parsed: list[tuple[datetime | None, bool]] = []
    for event in events:
        if not isinstance(event, dict):
            parsed.append((None, False))
            continue
        ts = _parse_timestamp(event.get("timestamp"))
        is_user = (
            event.get("kind") == "MessageEvent"
            and event.get("source") == "user"
        )
        parsed.append((ts, is_user))

    user_idx = [i for i, (ts, is_user) in enumerate(parsed) if is_user and ts is not None]
    if len(user_idx) < 2:
        return []

    gaps: list[float] = []
    for k in range(1, len(user_idx)):
        u_i = user_idx[k]
        u_ts = parsed[u_i][0]
        assert u_ts is not None
        # Walk left to most-recent parseable timestamp.
        p_ts: datetime | None = None
        for j in range(u_i - 1, -1, -1):
            cand = parsed[j][0]
            if cand is not None:
                p_ts = cand
                break
        if p_ts is None:
            continue
        gaps.append((u_ts - p_ts).total_seconds())
    return gaps


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "-t", "--threshold-minutes",
        type=float,
        nargs="+",
        default=DEFAULT_MINUTES,
        help=f"Candidate thresholds, in minutes (default: {DEFAULT_MINUTES})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("engagement_totals.csv"),
        help="Per-threshold totals output path (default: engagement_totals.csv)",
    )
    p.add_argument(
        "--gap-histogram",
        type=Path,
        default=None,
        help="Optional path for the per-user-message gap CSV (one row per gap)",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Filter conversations by source (e.g. 'cloud', 'local')",
    )
    args = p.parse_args(argv)

    threshold_seconds_list = [int(round(m * 60)) for m in args.threshold_minutes]

    with get_ready_connection(show_progress=False) as conn:
        convs = _list_conversations(conn, args.source)

    # Pre-load events once per conversation; reuse across thresholds.
    print(f"Sweeping {len(convs)} conversation(s) across "
          f"{len(threshold_seconds_list)} threshold(s)...", file=sys.stderr)

    gaps_rows: list[dict] = []
    per_threshold_totals: dict[int, dict[str, int | float]] = {
        t: {"engaged_seconds": 0, "total_duration_seconds": 0,
            "engaged_convs": 0, "attention_periods": 0,
            "follow_up_user_message_count": 0,
            "attended_user_message_count": 0}
        for t in threshold_seconds_list
    }
    total_conv_count = 0

    for conv_id, location in convs:
        events = _iter_events(location)
        if not events:
            continue
        total_conv_count += 1

        if args.gap_histogram:
            for gap in _user_message_gaps(events):
                gaps_rows.append({
                    "conversation_id": conv_id,
                    "gap_seconds": gap,
                })

        for t in threshold_seconds_list:
            m = compute_engagement(events, threshold_seconds=t)
            bucket = per_threshold_totals[t]
            bucket["engaged_seconds"] = int(bucket["engaged_seconds"]) + m.engaged_seconds
            bucket["attention_periods"] = int(bucket["attention_periods"]) + m.attention_periods
            bucket["follow_up_user_message_count"] = (
                int(bucket["follow_up_user_message_count"])
                + m.follow_up_user_message_count
            )
            bucket["attended_user_message_count"] = (
                int(bucket["attended_user_message_count"])
                + m.attended_user_message_count
            )
            if m.total_duration_seconds is not None:
                bucket["total_duration_seconds"] = (
                    int(bucket["total_duration_seconds"]) + m.total_duration_seconds
                )
            if m.engaged_seconds > 0:
                bucket["engaged_convs"] = int(bucket["engaged_convs"]) + 1

    # Totals CSV
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "threshold_seconds",
            "threshold_minutes",
            "conversations_total",
            "engaged_conversations",
            "engaged_seconds_total",
            "total_duration_seconds",
            "engagement_ratio",
            "attention_periods_total",
            "follow_up_user_message_total",
            "attended_user_message_total",
            "generated_at",
        ])
        gen_at = datetime.now(timezone.utc).isoformat()
        for t in threshold_seconds_list:
            row = per_threshold_totals[t]
            total_dur = int(row["total_duration_seconds"])
            ratio = (
                int(row["engaged_seconds"]) / total_dur
                if total_dur > 0 else 0.0
            )
            writer.writerow([
                t,
                round(t / 60, 2),
                total_conv_count,
                int(row["engaged_convs"]),
                int(row["engaged_seconds"]),
                total_dur,
                f"{ratio:.4f}",
                int(row["attention_periods"]),
                int(row["follow_up_user_message_count"]),
                int(row["attended_user_message_count"]),
                gen_at,
            ])
    print(f"Wrote totals → {args.out}", file=sys.stderr)

    # Gap histogram CSV (optional)
    if args.gap_histogram is not None:
        args.gap_histogram.parent.mkdir(parents=True, exist_ok=True)
        with args.gap_histogram.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["conversation_id", "gap_seconds"])
            for r in gaps_rows:
                writer.writerow([r["conversation_id"], f"{r['gap_seconds']:.3f}"])
        print(
            f"Wrote {len(gaps_rows)} gap(s) → {args.gap_histogram}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
