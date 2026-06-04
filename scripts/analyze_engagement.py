#!/usr/bin/env python3
"""Analyze engagement threshold sweep results.

Usage:
    python scripts/analyze_engagement.py engagement_totals.csv engagement_gaps.csv
    python scripts/analyze_engagement.py --totals engagement_totals.csv --gaps engagement_gaps.csv
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


def analyze_totals(totals_path: Path) -> None:
    """Analyze the per-threshold totals CSV."""
    print("\n" + "=" * 70)
    print("THRESHOLD SWEEP TOTALS")
    print("=" * 70)
    
    rows = []
    with open(totals_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    if not rows:
        print("No data in totals file.")
        return
    
    # Print header
    print(f"\n{'Threshold':>10} {'Engaged':>12} {'Engaged':>10} {'Periods':>10} {'Attended':>10} {'Ratio':>8}")
    print(f"{'(min)':>10} {'Convs':>12} {'Hours':>10} {'Total':>10} {'Msgs':>10} {'':>8}")
    print("-" * 70)
    
    for row in rows:
        t_min = float(row.get('threshold_minutes', 0))
        engaged_convs = int(row.get('engaged_conversations', 0))
        engaged_secs = int(row.get('engaged_seconds_total', 0))
        engaged_hrs = engaged_secs / 3600
        periods = int(row.get('attention_periods_total', 0))
        attended = int(row.get('attended_user_message_total', 0))
        ratio = float(row.get('engagement_ratio', 0))
        
        print(f"{t_min:>10.0f} {engaged_convs:>12,} {engaged_hrs:>10.1f} {periods:>10,} {attended:>10,} {ratio:>8.2%}")
    
    # Find where metrics stabilize
    print("\n" + "-" * 70)
    print("ANALYSIS:")
    
    if len(rows) >= 2:
        # Look for where engaged_seconds stops growing significantly
        prev_engaged = int(rows[0].get('engaged_seconds_total', 0))
        for i, row in enumerate(rows[1:], 1):
            curr_engaged = int(row.get('engaged_seconds_total', 0))
            pct_change = (curr_engaged - prev_engaged) / prev_engaged * 100 if prev_engaged > 0 else 0
            t_min = float(row.get('threshold_minutes', 0))
            if pct_change < 5:  # Less than 5% growth
                print(f"  • Engagement stabilizes around T={t_min:.0f} min (only {pct_change:.1f}% increase from previous)")
                break
            prev_engaged = curr_engaged


def analyze_gaps(gaps_path: Path) -> None:
    """Analyze the gap histogram CSV."""
    print("\n" + "=" * 70)
    print("GAP DISTRIBUTION ANALYSIS")
    print("=" * 70)
    
    gaps = []
    with open(gaps_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                gaps.append(float(row['gap_seconds']))
            except (KeyError, ValueError):
                continue
    
    if not gaps:
        print("No gap data found.")
        return
    
    gaps.sort()
    n = len(gaps)
    
    # Basic stats
    print(f"\nBasic Statistics (n={n:,} follow-up user messages):")
    print(f"  Min:    {gaps[0]:>10.1f}s ({gaps[0]/60:.1f} min)")
    print(f"  Max:    {gaps[-1]:>10.1f}s ({gaps[-1]/60:.1f} min)")
    print(f"  Mean:   {sum(gaps)/n:>10.1f}s ({sum(gaps)/n/60:.1f} min)")
    print(f"  Median: {gaps[n//2]:>10.1f}s ({gaps[n//2]/60:.1f} min)")
    
    # Percentiles
    print(f"\nPercentiles:")
    for p in [25, 50, 75, 90, 95, 99]:
        idx = int(n * p / 100)
        val = gaps[idx]
        print(f"  p{p:02d}:    {val:>10.1f}s ({val/60:>6.1f} min)")
    
    # Histogram with finer bins for finding the trough
    print(f"\n" + "-" * 70)
    print("GAP HISTOGRAM (looking for bimodal distribution)")
    print("-" * 70)
    
    # Define bins in seconds
    bin_edges = [
        (0, 30, "0-30s"),
        (30, 60, "30s-1m"),
        (60, 120, "1-2m"),
        (120, 180, "2-3m"),
        (180, 300, "3-5m"),
        (300, 480, "5-8m"),
        (480, 600, "8-10m"),
        (600, 720, "10-12m"),
        (720, 900, "12-15m"),
        (900, 1200, "15-20m"),
        (1200, 1800, "20-30m"),
        (1800, 3600, "30-60m"),
        (3600, 7200, "1-2hr"),
        (7200, float('inf'), "2hr+"),
    ]
    
    counts = []
    for low, high, label in bin_edges:
        count = sum(1 for g in gaps if low <= g < high)
        counts.append((low, high, label, count))
    
    max_count = max(c[3] for c in counts) if counts else 1
    bar_width = 40
    
    print(f"\n{'Bin':>10} {'Count':>8} {'%':>6}  Distribution")
    print("-" * 70)
    
    for low, high, label, count in counts:
        pct = count / n * 100
        bar_len = int(count / max_count * bar_width)
        bar = "█" * bar_len
        print(f"{label:>10} {count:>8,} {pct:>5.1f}%  {bar}")
    
    # Find potential troughs (local minima)
    print(f"\n" + "-" * 70)
    print("TROUGH DETECTION (potential threshold candidates)")
    print("-" * 70)
    
    # Smooth the histogram and find local minima
    smoothed = []
    for i in range(len(counts)):
        # Simple 3-point smoothing
        start = max(0, i - 1)
        end = min(len(counts), i + 2)
        avg = sum(c[3] for c in counts[start:end]) / (end - start)
        smoothed.append(avg)
    
    troughs = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] < smoothed[i-1] and smoothed[i] < smoothed[i+1]:
            low, high, label, count = counts[i]
            # Trough is at the upper edge of this bin
            troughs.append((high, label, count))
    
    if troughs:
        print("\nLocal minima found at:")
        for edge_sec, label, count in troughs:
            print(f"  • {label} bin (upper edge: {edge_sec/60:.0f} min) - count: {count}")
        
        # Recommend the first significant trough
        best = troughs[0]
        print(f"\n  ➤ RECOMMENDED THRESHOLD: ~{best[0]/60:.0f} minutes")
        print(f"    (trough at {best[1]} bin suggests human attention drops off here)")
    else:
        print("\nNo clear trough detected. Distribution may be:")
        print("  • Unimodal (most gaps cluster in one range)")
        print("  • The current bin resolution may be too coarse")
    
    # Cumulative analysis
    print(f"\n" + "-" * 70)
    print("CUMULATIVE ANALYSIS (what % of gaps are captured at each threshold)")
    print("-" * 70)
    
    thresholds_min = [6, 8, 10, 12, 14, 16, 18, 20, 25, 30]
    print(f"\n{'Threshold':>12} {'Gaps Below':>12} {'% Captured':>12}")
    print("-" * 40)
    
    for t_min in thresholds_min:
        t_sec = t_min * 60
        below = sum(1 for g in gaps if g <= t_sec)
        pct = below / n * 100
        print(f"{t_min:>10} min {below:>12,} {pct:>11.1f}%")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('totals', nargs='?', help='Path to engagement_totals.csv')
    parser.add_argument('gaps', nargs='?', help='Path to engagement_gaps.csv')
    parser.add_argument('--totals', dest='totals_flag', help='Path to engagement_totals.csv')
    parser.add_argument('--gaps', dest='gaps_flag', help='Path to engagement_gaps.csv')
    
    args = parser.parse_args()
    
    totals_path = args.totals_flag or args.totals
    gaps_path = args.gaps_flag or args.gaps
    
    if not totals_path and not gaps_path:
        # Try default paths
        totals_path = 'engagement_totals.csv'
        gaps_path = 'engagement_gaps.csv'
    
    if totals_path and Path(totals_path).exists():
        analyze_totals(Path(totals_path))
    elif totals_path:
        print(f"Warning: {totals_path} not found, skipping totals analysis")
    
    if gaps_path and Path(gaps_path).exists():
        analyze_gaps(Path(gaps_path))
    elif gaps_path:
        print(f"Warning: {gaps_path} not found, skipping gaps analysis")
    
    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print("""
1. Look at the TROUGH DETECTION section - that's where human attention
   typically drops off (the gap between "still watching" and "came back later")

2. Check the CUMULATIVE ANALYSIS - pick a threshold that captures most
   "quick response" gaps without including too many "came back later" gaps

3. Once you've chosen a threshold, update your corpus:
   
   ohtv db process engagement --threshold <SECONDS> --force
   
   (e.g., --threshold 720 for 12 minutes)
""")


if __name__ == "__main__":
    main()
