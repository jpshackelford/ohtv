"""Recognizers for research and study actions."""

from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext


# Web browsing tool names
WEB_TOOLS = {
    "fetch_fetch",
    "playwright_browser_navigate",
    "playwright_browser_snapshot",
    "playwright_browser_click",
    "playwright_browser_type",
}

# Tools that indicate web research activity
BROWSER_TOOLS = {
    "playwright_browser_navigate",
    "playwright_browser_snapshot",
    "playwright_browser_click",
    "playwright_browser_type",
    "playwright_browser_press_key",
    "playwright_browser_select_option",
    "playwright_browser_hover",
    "playwright_browser_take_screenshot",
    "playwright_browser_evaluate",
}


def recognize_research_actions(
    event: dict,
    context: RecognizerContext,
) -> Sequence[ConversationAction]:
    """Recognize research and study actions.
    
    Detects:
    - WEB_RESEARCH: Web browsing via fetch_fetch or playwright tools
    
    Note: STUDY_CODE is handled in file_edits.py for file_editor view actions
    """
    if event.get("kind") != "ActionEvent":
        return []
    
    tool_name = event.get("tool_name", "")
    
    # Web research via fetch tool
    if tool_name == "fetch_fetch":
        action = event.get("action", {})
        url = action.get("url", "")
        
        return [
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=ActionType.WEB_RESEARCH,
                target=url,
                metadata={"tool": "fetch"},
                event_id=event.get("id"),
            )
        ]
    
    # Web research via playwright browser
    if tool_name in BROWSER_TOOLS:
        action = event.get("action", {})
        
        # For navigate, capture the URL
        target = None
        if tool_name == "playwright_browser_navigate":
            target = action.get("url")
        
        # Only log navigate actions to avoid duplicates
        # (other browser actions are part of the same browsing session)
        if tool_name != "playwright_browser_navigate":
            # Check if we already logged a web_research for this browsing session
            # by looking at recent actions in context state
            recent_browser = context.state.get("recent_browser_action", 0)
            if context.current_index - recent_browser < 5:
                return []  # Skip, we already logged a recent browser action
        
        context.state["recent_browser_action"] = context.current_index
        
        return [
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=ActionType.WEB_RESEARCH,
                target=target,
                metadata={"tool": "playwright"},
                event_id=event.get("id"),
            )
        ]
    
    return []
