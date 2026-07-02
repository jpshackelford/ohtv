"""Lightweight utilities for extracting content from OpenHands conversation events.

This package provides battle-tested utilities for:
- Extracting message content, action summaries, and observations
- Parsing repository and reference URLs (GitHub, GitLab, Bitbucket)
- Computing engagement metrics
- Counting human input (words and messages)

All utilities work with standard Python dicts (event JSON) and have zero
non-stdlib dependencies.
"""

__version__ = "0.1.0"

# Re-export main extraction functions for convenient imports
from ohtv_utils.extraction.messages import (
    DEFAULT_OBSERVATION_TRUNCATE,
    extract_action_summary,
    extract_message_content,
    extract_observation_content,
)
from ohtv_utils.extraction.refs import parse_ref_url, parse_repo_url
from ohtv_utils.metrics.engagement import (
    DEFAULT_SUSTAINED_ATTENTION_SECONDS,
    DEFAULT_THRESHOLD_SECONDS,
    EngagementMetrics,
    compute_engagement,
)
from ohtv_utils.metrics.human_input import (
    HumanInputMetrics,
    count_human_input,
)

__all__ = [
    # Version
    "__version__",
    # Message extraction
    "DEFAULT_OBSERVATION_TRUNCATE",
    "extract_action_summary",
    "extract_message_content",
    "extract_observation_content",
    # Ref parsing
    "parse_ref_url",
    "parse_repo_url",
    # Engagement
    "DEFAULT_SUSTAINED_ATTENTION_SECONDS",
    "DEFAULT_THRESHOLD_SECONDS",
    "EngagementMetrics",
    "compute_engagement",
    # Human input
    "HumanInputMetrics",
    "count_human_input",
]
