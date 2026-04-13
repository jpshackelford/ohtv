"""Actions processing stage - extracts and stores recognized actions.

This stage:
1. Loads all events from a conversation
2. Runs each event through the recognizer pipeline
3. Stores recognized actions in the database
4. Tracks completion via conversation_stages
"""

import json
import sqlite3
from pathlib import Path

from ohtv.db.models import Conversation
from ohtv.db.stages.recognizers import RecognizerContext, recognize_all
from ohtv.db.stores import ActionStore, StageStore


STAGE_NAME = "actions"


def process_actions(conn: sqlite3.Connection, conversation: Conversation) -> None:
    """Process actions for a single conversation and store in DB.
    
    Loads events from the conversation directory, runs them through
    action recognizers, and stores the results.
    
    Args:
        conn: Database connection
        conversation: The conversation to process
    """
    conv_dir = Path(conversation.location)
    events_dir = conv_dir / "events"
    
    if not events_dir.exists():
        # No events, just mark complete
        stage_store = StageStore(conn)
        stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)
        return
    
    # Load all events
    events = _load_events(events_dir)
    
    if not events:
        stage_store = StageStore(conn)
        stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)
        return
    
    # Initialize stores
    action_store = ActionStore(conn)
    stage_store = StageStore(conn)
    
    # Clear any existing actions for this conversation (in case of reprocessing)
    action_store.delete_for_conversation(conversation.id)
    
    # Create context for recognizers
    context = RecognizerContext(
        conversation_id=conversation.id,
        events=events,
        current_index=0,
        state={},
    )
    
    # Process each event
    all_actions = []
    for i, event in enumerate(events):
        context.current_index = i
        actions = recognize_all(event, context)
        all_actions.extend(actions)
    
    # Bulk insert actions
    if all_actions:
        action_store.insert_many(all_actions)
    
    # Mark stage complete
    stage_store.mark_complete(conversation.id, STAGE_NAME, conversation.event_count)


def _load_events(events_dir: Path) -> list[dict]:
    """Load all events from a conversation's events directory."""
    events = []
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            data = json.loads(event_file.read_text())
            events.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return events
