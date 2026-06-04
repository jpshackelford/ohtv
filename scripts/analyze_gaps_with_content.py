#!/usr/bin/env python3
"""Analyze gaps with content context (word counts).

Enriches gap analysis by looking at:
1. Word count of agent message(s) preceding the user's response
2. Word count of the user's follow-up message

Hypothesis: Long gaps with high preceding word counts = reading time (justified)
            Long gaps with low preceding word counts = inattention (not engaged)

Usage:
    python scripts/analyze_gaps_with_content.py
    python scripts/analyze_gaps_with_content.py --out enriched_gaps.csv
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict


def count_words(text: str) -> int:
    """Count words in text, handling None and non-strings."""
    if not text or not isinstance(text, str):
        return 0
    # Simple word count - split on whitespace
    return len(text.split())


def parse_timestamp(ts) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        # Handle various ISO formats
        ts = ts.replace('Z', '+00:00')
        if '.' in ts:
            # Truncate microseconds if too long
            parts = ts.split('.')
            if len(parts) == 2:
                frac, tz = parts[1][:6], parts[1][6:]
                ts = f"{parts[0]}.{frac}{tz}"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def get_message_content(event: dict) -> str:
    """Extract message content from an event."""
    # Primary location: llm_message.content[].text (OpenHands format)
    llm_message = event.get('llm_message')
    if isinstance(llm_message, dict):
        content_list = llm_message.get('content', [])
        if isinstance(content_list, list):
            texts = []
            for item in content_list:
                if isinstance(item, dict) and 'text' in item:
                    texts.append(item['text'])
                elif isinstance(item, str):
                    texts.append(item)
            if texts:
                return ' '.join(texts)
        elif isinstance(content_list, str):
            return content_list
    
    # Fallback: direct content field
    content = event.get('content', '')
    if not content:
        content = event.get('message', '')
    if not content:
        content = event.get('output', '')
    if isinstance(content, dict):
        content = content.get('text', '') or content.get('content', '')
    return content if isinstance(content, str) else ''


def load_events(conv_location: str) -> list[dict]:
    """Load events from a conversation directory."""
    events_dir = Path(conv_location) / "events"
    if not events_dir.exists():
        return []
    
    events = []
    for f in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events


def analyze_conversation_gaps(events: list[dict]) -> list[dict]:
    """Analyze gaps with content context for one conversation."""
    results = []
    
    # Parse all events with timestamps
    parsed = []
    for event in events:
        ts = parse_timestamp(event.get('timestamp'))
        kind = event.get('kind', '')
        source = event.get('source', '')
        content = get_message_content(event)
        word_count = count_words(content)
        
        parsed.append({
            'ts': ts,
            'kind': kind,
            'source': source,
            'content': content,
            'word_count': word_count,
            'is_user_msg': kind == 'MessageEvent' and source == 'user',
            'is_agent_msg': kind == 'MessageEvent' and source == 'agent',
        })
    
    # Find user message indices
    user_indices = [i for i, p in enumerate(parsed) if p['is_user_msg'] and p['ts']]
    
    if len(user_indices) < 2:
        return []
    
    # For each follow-up user message, compute gap and context
    for k in range(1, len(user_indices)):
        u_idx = user_indices[k]
        prev_u_idx = user_indices[k - 1]
        
        user_event = parsed[u_idx]
        user_ts = user_event['ts']
        user_words = user_event['word_count']
        
        # Find preceding event timestamp
        prev_ts = None
        prev_idx = None
        for j in range(u_idx - 1, -1, -1):
            if parsed[j]['ts']:
                prev_ts = parsed[j]['ts']
                prev_idx = j
                break
        
        if not prev_ts or not user_ts:
            continue
        
        gap_seconds = (user_ts - prev_ts).total_seconds()
        
        # Count agent words between previous user message and this one
        agent_words_between = 0
        agent_msg_count = 0
        for j in range(prev_u_idx + 1, u_idx):
            if parsed[j]['is_agent_msg']:
                agent_words_between += parsed[j]['word_count']
                agent_msg_count += 1
        
        # Also get the immediate preceding message if it's from agent
        immediate_prev_words = 0
        immediate_prev_kind = ''
        if prev_idx is not None:
            immediate_prev_words = parsed[prev_idx]['word_count']
            immediate_prev_kind = parsed[prev_idx]['kind']
        
        results.append({
            'gap_seconds': gap_seconds,
            'gap_minutes': gap_seconds / 60,
            'user_response_words': user_words,
            'agent_words_between': agent_words_between,
            'agent_msg_count': agent_msg_count,
            'immediate_prev_words': immediate_prev_words,
            'immediate_prev_kind': immediate_prev_kind,
        })
    
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Output enriched CSV')
    parser.add_argument('--gaps-csv', type=Path, default=Path.home() / 'engagement_gaps.csv',
                        help='Input gaps CSV (to get conversation IDs)')
    args = parser.parse_args()
    
    # Get unique conversation IDs from gaps CSV
    conv_ids = set()
    with open(args.gaps_csv) as f:
        reader = csv.DictReader(f)
        for row in reader:
            conv_ids.add(row['conversation_id'])
    
    print(f"Analyzing {len(conv_ids)} conversations with gaps...", file=sys.stderr)
    
    # Get conversation locations from DB
    from ohtv.db import get_ready_connection
    
    conv_locations = {}
    with get_ready_connection(show_progress=False) as conn:
        for conv_id in conv_ids:
            cur = conn.execute(
                "SELECT location FROM conversations WHERE id = ?",
                (conv_id,)
            )
            row = cur.fetchone()
            if row and row[0]:
                conv_locations[conv_id] = row[0]
    
    print(f"Found locations for {len(conv_locations)} conversations", file=sys.stderr)
    
    # Analyze each conversation
    all_gaps = []
    for i, (conv_id, location) in enumerate(conv_locations.items()):
        if (i + 1) % 100 == 0:
            print(f"  Processing {i+1}/{len(conv_locations)}...", file=sys.stderr)
        
        events = load_events(location)
        if not events:
            continue
        
        gaps = analyze_conversation_gaps(events)
        for gap in gaps:
            gap['conversation_id'] = conv_id
            all_gaps.append(gap)
    
    print(f"\nAnalyzed {len(all_gaps)} gaps with content context", file=sys.stderr)
    
    # Output enriched CSV if requested
    if args.out:
        with open(args.out, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'conversation_id', 'gap_seconds', 'gap_minutes',
                'user_response_words', 'agent_words_between', 'agent_msg_count',
                'immediate_prev_words', 'immediate_prev_kind'
            ])
            writer.writeheader()
            writer.writerows(all_gaps)
        print(f"Wrote enriched gaps to {args.out}", file=sys.stderr)
    
    # Analyze the data
    print("\n" + "=" * 70)
    print("GAP ANALYSIS WITH CONTENT CONTEXT")
    print("=" * 70)
    
    # Focus on the 8-12 minute range
    gaps_8_12 = [g for g in all_gaps if 8*60 <= g['gap_seconds'] <= 12*60]
    
    print(f"\nGaps in 8-12 minute range: {len(gaps_8_12)}")
    
    # Categorize by agent word count
    print("\n" + "-" * 70)
    print("GAPS BY PRECEDING AGENT CONTENT VOLUME (8-12 min range)")
    print("-" * 70)
    
    buckets = [
        (0, 100, "0-100 words", "Very short - likely inattention"),
        (100, 300, "100-300 words", "Short - probably inattention"),
        (300, 700, "300-700 words", "Medium - could be reading"),
        (700, 1500, "700-1500 words", "Long - likely reading"),
        (1500, float('inf'), "1500+ words", "Very long - definitely reading"),
    ]
    
    print(f"\n{'Agent Words':>15} {'Count':>8} {'Avg Gap':>10} {'Assessment'}")
    print("-" * 70)
    
    for low, high, label, assessment in buckets:
        matching = [g for g in gaps_8_12 if low <= g['agent_words_between'] < high]
        if matching:
            avg_gap = sum(g['gap_minutes'] for g in matching) / len(matching)
            print(f"{label:>15} {len(matching):>8} {avg_gap:>9.1f}m  {assessment}")
        else:
            print(f"{label:>15} {0:>8} {'--':>10}  {assessment}")
    
    # Now look at user response length
    print("\n" + "-" * 70)
    print("GAPS BY USER RESPONSE LENGTH (8-12 min range)")
    print("-" * 70)
    
    user_buckets = [
        (0, 20, "0-20 words", "Quick reply - was watching"),
        (20, 50, "20-50 words", "Short reply"),
        (50, 150, "50-150 words", "Medium reply - composing"),
        (150, 400, "150-400 words", "Long reply - significant thought"),
        (400, float('inf'), "400+ words", "Very long - major composition"),
    ]
    
    print(f"\n{'User Words':>15} {'Count':>8} {'Avg Gap':>10} {'Assessment'}")
    print("-" * 70)
    
    for low, high, label, assessment in user_buckets:
        matching = [g for g in gaps_8_12 if low <= g['user_response_words'] < high]
        if matching:
            avg_gap = sum(g['gap_minutes'] for g in matching) / len(matching)
            print(f"{label:>15} {len(matching):>8} {avg_gap:>9.1f}m  {assessment}")
        else:
            print(f"{label:>15} {0:>8} {'--':>10}  {assessment}")
    
    # Cross-tabulation: low agent words + low user words = inattention
    print("\n" + "-" * 70)
    print("INATTENTION DETECTION (8-12 min gaps)")
    print("-" * 70)
    
    # Low content on both sides suggests inattention
    low_agent = [g for g in gaps_8_12 if g['agent_words_between'] < 300]
    low_both = [g for g in low_agent if g['user_response_words'] < 50]
    high_agent = [g for g in gaps_8_12 if g['agent_words_between'] >= 700]
    
    print(f"\n  Total gaps 8-12 min:                    {len(gaps_8_12)}")
    print(f"  Low agent content (<300 words):         {len(low_agent)} ({len(low_agent)/len(gaps_8_12)*100:.0f}%)")
    print(f"  Low agent + low user (<50 words):       {len(low_both)} ({len(low_both)/len(gaps_8_12)*100:.0f}%) ← LIKELY INATTENTION")
    print(f"  High agent content (≥700 words):        {len(high_agent)} ({len(high_agent)/len(gaps_8_12)*100:.0f}%) ← LIKELY READING")
    
    # Same analysis for different gap ranges
    print("\n" + "=" * 70)
    print("INATTENTION RATIO BY GAP RANGE")
    print("=" * 70)
    print("\n(Low content = <300 agent words AND <50 user words)")
    print(f"\n{'Gap Range':>12} {'Total':>8} {'Low Content':>12} {'% Inattention':>14}")
    print("-" * 50)
    
    ranges = [
        (5, 6), (6, 7), (7, 8), (8, 9), (9, 10), (10, 11), (11, 12), (12, 15), (15, 20)
    ]
    
    for low_min, high_min in ranges:
        in_range = [g for g in all_gaps if low_min*60 <= g['gap_seconds'] < high_min*60]
        if not in_range:
            continue
        low_content = [g for g in in_range 
                       if g['agent_words_between'] < 300 and g['user_response_words'] < 50]
        pct = len(low_content) / len(in_range) * 100
        print(f"{low_min:>4}-{high_min:<4} min {len(in_range):>8} {len(low_content):>12} {pct:>13.1f}%")
    
    # Recommendation based on content analysis
    print("\n" + "=" * 70)
    print("CONTENT-ADJUSTED RECOMMENDATION")
    print("=" * 70)
    
    # For each threshold, what % of gaps would be "false positives" (low content)
    print("\nFalse positive rate (counting inattention as engagement):")
    print(f"\n{'Threshold':>12} {'Gaps Added':>12} {'Low Content':>12} {'FP Rate':>10}")
    print("-" * 50)
    
    for t in [8, 9, 10, 11, 12]:
        prev_t = t - 1
        added = [g for g in all_gaps if prev_t*60 < g['gap_seconds'] <= t*60]
        low_content = [g for g in added 
                       if g['agent_words_between'] < 300 and g['user_response_words'] < 50]
        if added:
            fp_rate = len(low_content) / len(added) * 100
            print(f"{t:>10} min {len(added):>12} {len(low_content):>12} {fp_rate:>9.1f}%")


if __name__ == "__main__":
    main()
