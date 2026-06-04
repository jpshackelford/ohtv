# Engagement Threshold Analysis: Empirical Tuning Study

**Date:** 2026-05-27  
**Analyst:** OpenHands AI Agent on behalf of @jpshackelford  
**Related Issues:** [#163](https://github.com/jpshackelford/ohtv/issues/163), [#165](https://github.com/jpshackelford/ohtv/pull/165), [#167](https://github.com/jpshackelford/ohtv/issues/167), [#168](https://github.com/jpshackelford/ohtv/issues/168), [#169](https://github.com/jpshackelford/ohtv/issues/169), [#170](https://github.com/jpshackelford/ohtv/issues/170)

---

## Executive Summary

This document records the empirical analysis conducted to determine the optimal sustained-attention threshold (T) for the "engaged human minutes" metric in ohtv. The analysis processed 4,791 conversations containing 9,935 follow-up user message gaps across 11 candidate thresholds (6-28 minutes).

**Key Findings:**
1. ~70% of all follow-up user messages occur within 30 seconds of the preceding event
2. 92.9% occur within 6 minutes; 96.1% within 12 minutes
3. The distribution shows a cliff at ~10 minutes where gap counts drop sharply
4. Content analysis reveals ~65% of gaps in the 8-12 minute range are likely inattention (low content on both sides)
5. **The 12-minute default chosen in PR #165 is reasonable**, though 10 minutes is slightly more defensible empirically

**Recommendation:** For the intended use case (measuring orchestration impact on throughput), threshold choice matters less than consistency. Focus on unambiguous metrics (completely unattended conversations) and ratio analysis (PRs per attention-minute) with a consistent threshold.

---

## 1. Background

### 1.1 The Engagement Metric (PR #165)

[PR #165](https://github.com/jpshackelford/ohtv/pull/165) introduced a per-conversation "engaged human minutes" metric to ohtv, addressing [Issue #163](https://github.com/jpshackelford/ohtv/issues/163). The metric estimates how long a human was actively monitoring/steering each conversation, inferred from temporal gaps around user messages.

**Algorithm (from Issue #163):**

1. Order events by timestamp ascending; find user-message indices `Uᵢ`
2. For each follow-up `Uᵢ` (i ≥ 1), examine gap from preceding event `Pᵢ`. If `Uᵢ.ts - Pᵢ.ts ≤ T`, record attended block `(Uᵢ₋₁.ts, Uᵢ.ts)`
3. Merge adjacent blocks with seam ≤ T into attention periods
4. `engaged_seconds = Σ (period.end - period.start)`

**Key Design Decisions:**
- Threshold T stored per-row in `conversation_engagement` table for distinguishability
- Fire-and-forget conversations (0-1 user messages) get `engaged_seconds = 0` (not NULL)
- Tail events after last user message do NOT extend attention periods

### 1.2 The Threshold Question

PR #165 shipped with T = 12 minutes as the default, based on the issue author's intuition ("noticed the message → read response → composed reply"). The issue explicitly called for empirical tuning:

> "Rather than guess: implement the algorithm parameterized on T, run it across the corpus at T ∈ {6, 8, 12, 14, 16, 18, 20, 22, 24, 26, 28} minutes, plot the gap histogram to find the trough between 'human reaction time' and 'came back later' modes."

**This tuning was not performed before merging PR #165.** The sweep script (`scripts/engagement_threshold_sweep.py`) was created but the results were never analyzed.

---

## 2. Methodology

### 2.1 Data Collection

We ran the engagement threshold sweep against the full ohtv corpus:

```bash
uv tool run --from git+https://github.com/jpshackelford/ohtv.git@main \
  python scripts/engagement_threshold_sweep.py \
  --out engagement_totals.csv \
  --gap-histogram engagement_gaps.csv
```

**Corpus Statistics:**
- Total conversations: 4,791 (4,777 roots + 14 sub-conversations)
- Conversations with follow-up gaps: 1,505
- Total follow-up user message gaps: 9,935

### 2.2 Analysis Scripts

Two analysis scripts were developed:

1. **`scripts/analyze_engagement.py`** — Basic analysis of totals and gap distribution
2. **`scripts/analyze_gaps_with_content.py`** — Content-aware analysis correlating gaps with word counts

The content-aware script enriches each gap with:
- `agent_words_between`: Total words in agent messages between the previous user message and this one
- `user_response_words`: Word count of the user's follow-up message
- `immediate_prev_words`: Word count of the immediately preceding event

---

## 3. Findings

### 3.1 Gap Distribution Overview

The gap distribution is heavily front-loaded:

| Range | Count | % | Cumulative % |
|-------|-------|---|--------------|
| 0-30s | 6,911 | 69.6% | 69.6% |
| 30s-1m | 495 | 5.0% | 74.6% |
| 1-2m | 807 | 8.1% | 82.7% |
| 2-3m | 426 | 4.3% | 87.0% |
| 3-5m | 461 | 4.6% | 91.6% |
| 5-8m | 282 | 2.8% | 94.4% |
| 8-10m | 108 | 1.1% | 95.5% |
| 10-12m | 57 | 0.6% | 96.1% |
| 12-15m | 70 | 0.7% | 96.8% |
| 15-20m | 54 | 0.5% | 97.3% |
| 20-30m | 60 | 0.6% | 97.9% |
| 30-60m | 68 | 0.7% | 98.6% |
| 1-2hr | 51 | 0.5% | 99.1% |
| 2hr+ | 85 | 0.9% | 100.0% |

**Key Observation:** The median gap is essentially 0 seconds. Most human steering happens in real-time — users are actively watching the agent work.

### 3.2 Threshold Sweep Totals

| Threshold | Engaged Convs | Engaged Hours | Periods | Attended Msgs | Ratio |
|-----------|---------------|---------------|---------|---------------|-------|
| 6 min | 1,459 | 2,604.3 | 1,771 | 9,226 | 23.12% |
| 8 min | 1,467 | 2,627.5 | 1,726 | 9,382 | 23.32% |
| 12 min | 1,480 | 2,659.3 | 1,675 | 9,547 | 23.60% |
| 14 min | 1,481 | 2,672.7 | 1,653 | 9,600 | 23.72% |
| 16 min | 1,483 | 2,682.2 | 1,644 | 9,632 | 23.81% |
| 20 min | 1,484 | 2,695.2 | 1,628 | 9,671 | 23.92% |
| 28 min | 1,487 | 2,717.3 | 1,607 | 9,720 | 24.12% |

**Observation:** Engagement metrics stabilize quickly. Moving from T=6 to T=8 adds only 0.9% more engaged time; T=8 to T=12 adds another 1.2%. Beyond 12 minutes, gains are marginal (<0.5% per step).

### 3.3 Derivative Analysis: Finding the Cliff

We examined the rate of change in gap counts to identify where the distribution transitions from "still watching" to "came back later":

| Bin | Count | Δ from prev | Signal |
|-----|-------|-------------|--------|
| 5-6 min | 126 | (baseline) | |
| 6-7 min | 89 | -37 | **SIGNIFICANT DROP** |
| 7-8 min | 67 | -22 | **SIGNIFICANT DROP** |
| 8-9 min | 57 | -10 | moderate drop |
| 9-10 min | 51 | -6 | moderate drop |
| 10-11 min | 31 | -20 | **SIGNIFICANT DROP** |
| 11-12 min | 26 | -5 | stable |
| 12-13 min | 28 | +2 | stable |
| 13-14 min | 25 | -3 | stable |

**Finding:** The counts show significant drops at 6-7, 7-8, and 10-11 minutes. After 10 minutes, the distribution flattens into a plateau (~25-28 gaps per minute), suggesting this is the "came back later" territory.

### 3.4 Marginal Analysis: 8-12 Minute Range

| Threshold Change | Gaps Added | % of Total | Assessment |
|-----------------|------------|------------|------------|
| 6→8 min | 156 | 1.57% | Likely still watching |
| 8→10 min | 108 | 1.09% | Likely still watching |
| 10→12 min | 57 | 0.57% | Borderline |
| 12→14 min | 53 | 0.53% | Diminishing returns |
| 14→16 min | 32 | 0.32% | Noise |

### 3.5 Content-Aware Analysis

To test whether long gaps are justified by content volume (reading/composing time) vs. inattention, we correlated gaps with word counts.

**Definition of "low content" (likely inattention):**
- Agent words between messages < 300 AND
- User response words < 50

**Results for 8-12 minute gaps:**

| Metric | Value |
|--------|-------|
| Total gaps in range | 165 |
| Low agent content (<300 words) | 147 (89%) |
| Low agent + low user | 108 (65%) ← **likely inattention** |
| High agent content (≥700 words) | 4 (2%) ← likely reading |

**Inattention rate by gap range:**

| Gap Range | Total | Low Content | % Inattention |
|-----------|-------|-------------|---------------|
| 5-6 min | 126 | 85 | 67.5% |
| 6-7 min | 89 | 55 | 61.8% |
| 7-8 min | 67 | 41 | 61.2% |
| 8-9 min | 57 | 36 | 63.2% |
| 9-10 min | 51 | 33 | 64.7% |
| 10-11 min | 31 | 21 | 67.7% |
| 11-12 min | 26 | 18 | 69.2% |
| 12-15 min | 70 | 45 | 64.3% |
| 15-20 min | 54 | 31 | 57.4% |

**Key Finding:** The inattention rate is remarkably consistent (~61-69%) across the 5-15 minute range. There is no clear content-based breakpoint that would distinguish 8 from 10 from 12 minutes. About 1/3 of gaps in this range are legitimate reading/composing time; 2/3 are likely brief inattention.

---

## 4. Conclusions

### 4.1 Threshold Recommendation

Based on the analysis:

1. **The 12-minute default is reasonable.** It captures 96.1% of all follow-up gaps and sits in a stable region of the distribution.

2. **10 minutes is slightly more defensible empirically.** It sits right at the second significant drop (10-11 min shows -20 gap drop) and captures 95.5% of gaps.

3. **8 minutes would be conservative.** It captures 94.4% and is just before the distribution fully stabilizes.

**For academic rigor, we recommend:**
- Use 10 or 12 minutes as the primary threshold
- Show sensitivity analysis at 8, 10, and 12 minutes to demonstrate robustness

### 4.2 Intended Use Case: Orchestration Impact Analysis

The primary use case is demonstrating that AI orchestration increases PR throughput without increasing (or while decreasing) human attention time.

**Recommended Metrics:**

1. **Completely Unattended Conversations** (threshold-independent)
   - Definition: Zero follow-up user messages OR zero attention periods
   - This is unambiguous and the cleanest metric

2. **Efficiency Ratios** (threshold-dependent but consistent)
   - Merged PRs per attention-hour
   - Merged LOC per attention-hour
   - Use same threshold for all time periods being compared

**Why Threshold Choice Matters Less:**
- For unattended conversations: No dependency on T
- For ratio analysis: Consistency matters more than absolute value
- A higher T is actually more conservative (counts more attention time, understating efficiency gains)

### 4.3 Robustness Considerations

To make the orchestration impact argument bulletproof:

1. **Lead with unambiguous metrics** — % of completely unattended conversations
2. **Show ratio trends** — PRs/LOC per attention-minute over time
3. **Demonstrate threshold robustness** — Show conclusions hold at T=8, 10, and 12
4. **Control for confounds** — Compare similar conversation types (same repos, similar complexity)

---

## 5. Artifacts and Data

### 5.1 Generated Files

| File | Location | Description |
|------|----------|-------------|
| `engagement_totals.csv` | `~/engagement_totals.csv` | Per-threshold aggregate stats |
| `engagement_gaps.csv` | `~/engagement_gaps.csv` | All 9,935 follow-up gaps with timestamps |
| `enriched_gaps.csv` | `~/enriched_gaps.csv` | Gaps enriched with word counts |

### 5.2 Analysis Scripts

| Script | Location | Purpose |
|--------|----------|---------|
| `engagement_threshold_sweep.py` | `scripts/` | Run threshold sweep (from ohtv repo) |
| `analyze_engagement.py` | `scripts/` | Basic gap distribution analysis |
| `analyze_gaps_with_content.py` | `scripts/` | Content-aware gap analysis |

### 5.3 Filed Issues

| Issue | Title | Purpose |
|-------|-------|---------|
| [#167](https://github.com/jpshackelford/ohtv/issues/167) | Add engagement columns to `ohtv list` | Show engagement in list output |
| [#168](https://github.com/jpshackelford/ohtv/issues/168) | Add engagement fields to `ohtv gen objs` JSON | Include in JSON export |
| [#169](https://github.com/jpshackelford/ohtv/issues/169) | Add engagement to `gen objs` markdown | Show below Duration line |
| [#170](https://github.com/jpshackelford/ohtv/issues/170) | Filter by engagement level | `--engaged`, `--min-engaged` flags |

---

## 6. Next Steps

For the follow-up session:

1. **Compute LOC / Merged PR Analysis**
   - Query `change_refs` table for merged PRs with LOC
   - Join with `conversation_engagement` for attention minutes
   - Aggregate by time period (weekly/monthly)

2. **Track Orchestration Rollout**
   - Identify when orchestration features were deployed
   - Compare pre/post metrics

3. **Build Visualization**
   - Time series of:
     - % unattended conversations
     - PRs per attention-hour
     - LOC per attention-hour
   - Annotate with orchestration milestones

4. **Sensitivity Analysis**
   - Repeat analysis at T=8, 10, 12 minutes
   - Confirm conclusions are robust

---

## Appendix A: Statistical Summary

```
Corpus: 4,791 conversations, 9,935 follow-up user message gaps

Gap Distribution Percentiles:
  p25:    0.0 seconds (0.0 min)
  p50:    0.0 seconds (0.0 min)  [median]
  p75:   62.8 seconds (1.0 min)
  p90:  249.0 seconds (4.1 min)
  p95:  539.8 seconds (9.0 min)
  p99: 5825.2 seconds (97.1 min)

  Min:     0.0 seconds
  Max: 2,063,018.9 seconds (34,383 min ≈ 24 days)
  Mean:  959.8 seconds (16.0 min)
```

---

## Appendix B: Raw Threshold Sweep Output

```
threshold_seconds,threshold_minutes,conversations_total,engaged_conversations,
engaged_seconds_total,total_duration_seconds,engagement_ratio,attention_periods_total,
follow_up_user_message_total,attended_user_message_total,generated_at

360,6.0,4791,1459,9375526,40551997,0.2312,1771,9935,9226,2026-05-27T...
480,8.0,4791,1467,9459058,40551997,0.2332,1726,9935,9382,...
720,12.0,4791,1480,9573593,40551997,0.2360,1675,9935,9547,...
840,14.0,4791,1481,9621773,40551997,0.2372,1653,9935,9600,...
960,16.0,4791,1483,9656059,40551997,0.2381,1644,9935,9632,...
1080,18.0,4791,1483,9680885,40551997,0.2387,1636,9935,9653,...
1200,20.0,4791,1484,9702688,40551997,0.2392,1628,9935,9671,...
1320,22.0,4791,1484,9720984,40551997,0.2397,1621,9935,9684,...
1440,24.0,4791,1485,9749265,40551997,0.2404,1616,9935,9701,...
1560,26.0,4791,1486,9764237,40551997,0.2407,1612,9935,9710,...
1680,28.0,4791,1487,9782268,40551997,0.2412,1607,9935,9720,...
```

---

*Document generated by OpenHands AI Agent. For questions or clarifications, refer to the original conversation or contact @jpshackelford.*
