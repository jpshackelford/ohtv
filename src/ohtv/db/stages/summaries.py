"""Summary extraction stage.

Extracts summaries from objective analysis cache and stores them in the
conversations table for use in RAG contextual enrichment.
"""

import logging
from pathlib import Path

from ohtv.analysis.cache import load_analysis
from ohtv.db.stores import ConversationStore

log = logging.getLogger("ohtv")


def process_summaries(
    conn,
    conv_dirs: list[Path],
    force: bool = False,
) -> int:
    """Extract summaries from analysis cache and store in database.
    
    Args:
        conn: Database connection
        conv_dirs: List of conversation directories to process
        force: If True, reprocess even if summary already exists
    
    Returns:
        Number of summaries extracted
    """
    conv_store = ConversationStore(conn)
    extracted = 0
    
    for conv_dir in conv_dirs:
        conv_id = conv_dir.name
        
        # Skip if already has summary (unless force)
        if not force:
            conv = conv_store.get(conv_id)
            if conv and conv.summary:
                continue
        
        # Load analysis from cache
        analysis = load_analysis(conv_dir)
        if not analysis:
            continue
        
        # Extract goal as summary
        goal = analysis.get("goal")
        if goal:
            if conv_store.update_summary(conv_id, goal):
                extracted += 1
                log.debug("Extracted summary for %s: %s", conv_id[:8], goal[:50])
    
    return extracted


def extract_summary_for_conversation(
    conn,
    conv_dir: Path,
) -> str | None:
    """Extract and store summary for a single conversation.
    
    Args:
        conn: Database connection
        conv_dir: Conversation directory
    
    Returns:
        Extracted summary or None if not available
    """
    conv_id = conv_dir.name
    conv_store = ConversationStore(conn)
    
    # Load analysis from cache
    analysis = load_analysis(conv_dir)
    if not analysis:
        return None
    
    # Extract goal as summary
    goal = analysis.get("goal")
    if goal:
        conv_store.update_summary(conv_id, goal)
        return goal
    
    return None
