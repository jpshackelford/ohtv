#!/usr/bin/env python3
"""Render a velocity chart from CSV (stdin or file).

Standalone shim for the original-issue (#82) pipeline:

    ohtv report velocity --format csv | python scripts/chart_velocity.py --output v.png

The CLI's ``ohtv report velocity --chart PATH`` covers the
direct-from-DB case. This script exists for the
"already-have-a-CSV-laying-around" workflow and is kept deliberately
thin: parse CSV → build :class:`VelocityRow` list → call
:func:`plot_velocity`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from ohtv.reports.charts import plot_velocity
from ohtv.reports.velocity import VelocityRow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        help="CSV file (default: stdin).",
    )
    parser.add_argument("--output", "-o", required=True, help="Output path (.png/.svg/.pdf).")
    parser.add_argument("--mark-date", help="YYYY-MM-DD vertical reference line.")
    parser.add_argument("--title", default="Development Velocity", help="Figure suptitle.")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, newline="") as handle:
            rows = [VelocityRow.from_csv_dict(row) for row in csv.DictReader(handle)]
    else:
        rows = [VelocityRow.from_csv_dict(row) for row in csv.DictReader(sys.stdin)]

    if not rows:
        print("No data to chart.", file=sys.stderr)
        return 0

    mark_date = (
        datetime.strptime(args.mark_date, "%Y-%m-%d").date() if args.mark_date else None
    )
    plot_velocity(rows, Path(args.output), mark_date=mark_date, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
