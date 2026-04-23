"""Summary extraction stage.

Extracts summaries from objective analysis cache and stores them in the
conversations table for use in RAG contextual enrichment.
"""

import logging
import sqlite3
from pathlib import Path

from ohtv.analysis.cache import load_analysis
from ohtv.db.models import Conversation
from ohtv.db.stores import ConversationStore, StageStore

log = logging.getLogger("ohtv")

STAGE_NAME = "summaries"


def process_summaries(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Extract summary from analysis cache and store in database.

    Loads the objective analysis from cache (if available) and extracts
    the goal as a summary for use in RAG contextual enrichment.

    Args:
        conn: Database connection
        conversation: The conversation to process
    """
    conv_dir = Path(conversation.location)
    conv_store = ConversationStore(conn)
    stage_store = StageStore(conn)

    # Load analysis from cache
    analysis = load_analysis(conv_dir)
    if analysis:
        # Extract goal as summary
        goal = analysis.get("goal")
        if goal:
            conv_store.update_summary(conversation.id, goal)
            log.debug("Extracted summary for %s: %s", conversation.id[:8], goal[:50])

    # Mark stage as complete (even if no summary found - we tried)
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)
