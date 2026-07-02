"""Engagement (sustained-attention) computation for conversation events.

Computes "engaged human minutes" - the time spans when a human was actively
engaged with the conversation, based on user message timing relative to
agent activity.

Algorithm uses two distinct timing thresholds:
- T (threshold_seconds): Silence tolerance - how long can human be silent during
  agent activity and still be considered present
- T_a (sustained_attention_seconds): Sustained attention window - caps how far
  back an attended block can extend

See ohtv Issues #163 and #184 for empirical analysis and algorithm details.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


# Default silence-tolerance threshold (T). "How long is a human silent during
# agent activity and still engaged, not absent." Empirically grounded at 12 min.
DEFAULT_THRESHOLD_SECONDS = 12 * 60

# Default sustained-attention window (T_a). "How long can a human plausibly
# stay continuously engaged in one block before we assume they walked away."
# Default: 1 hour (provisional - see ohtv Issue #184 for tuning rationale).
DEFAULT_SUSTAINED_ATTENTION_SECONDS = 60 * 60


@dataclass(frozen=True)
class EngagementMetrics:
    """Engagement numbers for one conversation under one threshold pair.

    Attributes:
        engaged_seconds: Total seconds of engaged time (sum of attention periods)
        attention_periods: Number of distinct attention periods
        follow_up_user_message_count: Total follow-up messages (excludes initial prompt)
        attended_user_message_count: Follow-ups that passed the attention gate
        first_event_ts: Timestamp of first parseable event (or None)
        last_event_ts: Timestamp of last parseable event (or None)
    """

    engaged_seconds: int
    attention_periods: int
    follow_up_user_message_count: int
    attended_user_message_count: int
    first_event_ts: datetime | None = None
    last_event_ts: datetime | None = None

    @property
    def total_duration_seconds(self) -> int | None:
        """Total conversation duration (last_event_ts - first_event_ts) in whole seconds.

        Returns None if either timestamp is missing.
        """
        if self.first_event_ts is None or self.last_event_ts is None:
            return None
        return int((self.last_event_ts - self.first_event_ts).total_seconds())


def compute_engagement(
    events: list[dict],
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
    sustained_attention_seconds: int = DEFAULT_SUSTAINED_ATTENTION_SECONDS,
) -> EngagementMetrics:
    """Compute engagement metrics for conversation events.

    Analyzes user message timing relative to agent activity to determine
    periods of active human engagement. Uses two thresholds:

    - threshold_seconds (T): Silence tolerance. If gap from user message
      to immediately preceding event is <= T, user was present.
    - sustained_attention_seconds (T_a): Sustained attention window. Caps
      how far back an attended block extends from current to previous user
      message.

    Args:
        events: Ordered list of event dicts (from event-*.json files). Events
            must be in chronological order.
        threshold_seconds: Silence-tolerance threshold (T), in seconds.
            Default 720 (12 min). Pass 0 to mark every gap unattended;
            pass very large number to merge whole conversation.
        sustained_attention_seconds: Sustained-attention window (T_a), in
            seconds. Default 3600 (1 h). Caps how far attended blocks
            extend back. Pass 0 to disable extension (every attended
            follow-up is zero-duration touch); pass very large number
            to disable cap.

    Returns:
        EngagementMetrics for the conversation. Malformed events
        (missing/wrong-typed timestamp or kind/source fields) are tolerated
        and silently skipped.

    Example:
        >>> events = [
        ...     {"kind": "MessageEvent", "source": "user", "timestamp": "2024-01-01T10:00:00Z"},
        ...     {"kind": "ActionEvent", "timestamp": "2024-01-01T10:01:00Z"},
        ...     {"kind": "MessageEvent", "source": "user", "timestamp": "2024-01-01T10:02:00Z"},
        ... ]
        >>> metrics = compute_engagement(events)
        >>> metrics.engaged_seconds
        120
        >>> metrics.attention_periods
        1
        >>> metrics.follow_up_user_message_count
        1
    """
    # Pre-extract (timestamp, is_user_message) for every parseable event
    parsed: list[tuple[datetime | None, bool]] = []
    for event in events:
        if not isinstance(event, dict):
            parsed.append((None, False))
            continue
        ts = _parse_timestamp(event.get("timestamp"))
        is_user = event.get("kind") == "MessageEvent" and event.get("source") == "user"
        parsed.append((ts, is_user))

    # First and last parseable event timestamps anchor conversation duration
    parsed_ts = [ts for ts, _ in parsed if ts is not None]
    first_event_ts = parsed_ts[0] if parsed_ts else None
    last_event_ts = parsed_ts[-1] if parsed_ts else None

    user_idx = [i for i, (ts, is_user) in enumerate(parsed) if is_user and ts is not None]
    follow_up_count = max(0, len(user_idx) - 1)

    if len(user_idx) < 2:
        # Fire-and-forget (or empty): no follow-up means no engagement
        return EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=follow_up_count,
            attended_user_message_count=0,
            first_event_ts=first_event_ts,
            last_event_ts=last_event_ts,
        )

    threshold = max(0, int(threshold_seconds))
    attention_window = max(0, int(sustained_attention_seconds))

    # Walk backward over follow-up user messages (skip U₀)
    # For each Uᵢ whose gap to immediately preceding event is <= T,
    # record attended block [Uᵢ₋₁, Uᵢ] if user-to-user gap <= T_a,
    # otherwise record zero-duration touch at Uᵢ
    attended: list[tuple[datetime, datetime]] = []
    for k in range(len(user_idx) - 1, 0, -1):
        u_i = user_idx[k]
        u_ts = parsed[u_i][0]
        assert u_ts is not None  # user_idx filter guarantees this

        # Walk left from u_i to find most recent parseable timestamp
        p_ts: datetime | None = None
        for j in range(u_i - 1, -1, -1):
            cand = parsed[j][0]
            if cand is not None:
                p_ts = cand
                break

        if p_ts is None:
            # Uᵢ is first parseable event - no preceding event to gate
            continue

        gap_seconds = (u_ts - p_ts).total_seconds()
        if gap_seconds > threshold:
            # Silence-tolerance gate failed → not attended
            continue

        # Sustained-attention cap: check user-to-user gap
        prev_user_idx = user_idx[k - 1]
        prev_user_ts = parsed[prev_user_idx][0]
        assert prev_user_ts is not None
        user_gap_seconds = (u_ts - prev_user_ts).total_seconds()

        if user_gap_seconds > attention_window:
            # User silent longer than one continuous session can cover
            # Credit the touch only - they came back but weren't reading along
            attended.append((u_ts, u_ts))
        else:
            # Normal back-and-forth: extend block back to previous user message
            attended.append((prev_user_ts, u_ts))

    if not attended:
        return EngagementMetrics(
            engaged_seconds=0,
            attention_periods=0,
            follow_up_user_message_count=follow_up_count,
            attended_user_message_count=0,
            first_event_ts=first_event_ts,
            last_event_ts=last_event_ts,
        )

    # Merge adjacent attended blocks whose seam gap <= T
    attended.sort()
    periods: list[tuple[datetime, datetime]] = [attended[0]]
    for start, end in attended[1:]:
        prev_start, prev_end = periods[-1]
        seam = (start - prev_end).total_seconds()
        if seam <= threshold:
            # Overlap or within-threshold join → extend
            new_end = max(prev_end, end)
            periods[-1] = (prev_start, new_end)
        else:
            periods.append((start, end))

    engaged_seconds = sum(int((end - start).total_seconds()) for start, end in periods)

    return EngagementMetrics(
        engaged_seconds=engaged_seconds,
        attention_periods=len(periods),
        follow_up_user_message_count=follow_up_count,
        attended_user_message_count=len(attended),
        first_event_ts=first_event_ts,
        last_event_ts=last_event_ts,
    )


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp from an event JSON field.

    Returns None for missing / wrong-typed / unparseable values.
    Naive datetimes are assumed UTC (matches OpenHands cloud timestamps).

    Args:
        value: Timestamp value from event (expected to be string)

    Returns:
        Parsed datetime with UTC timezone, or None if unparseable
    """
    if not isinstance(value, str):
        return None
    raw = value.rstrip("Z")
    if "+" in raw:
        raw = raw.split("+")[0]
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
