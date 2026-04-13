"""Recognizers for skill invocations via slash commands."""

import re
from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext


# Slash command patterns - these appear in user messages
CODE_REVIEW_COMMANDS = re.compile(
    r"(?:^|\s)/codereview(?:-roasted)?(?:\s|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Other skill commands we might want to track
INIT_COMMAND = re.compile(r"(?:^|\s)/init(?:\s|$)", re.IGNORECASE | re.MULTILINE)


def recognize_skill_invocations(
    event: dict,
    context: RecognizerContext,
) -> Sequence[ConversationAction]:
    """Recognize skill invocations from user messages.
    
    Detects:
    - PR_REVIEW: /codereview or /codereview-roasted slash commands
    
    These are recognized from MessageEvents with role="user", since
    slash commands are typed by users to invoke agent skills.
    """
    # Only look at user messages
    if event.get("kind") != "MessageEvent":
        return []
    
    role = event.get("role", "")
    if role != "user":
        return []
    
    # Get message content
    content = _extract_message_content(event)
    if not content:
        return []
    
    actions = []
    
    # Code review slash commands
    if CODE_REVIEW_COMMANDS.search(content):
        # Determine if it's the roasted variant
        is_roasted = "/codereview-roasted" in content.lower()
        
        actions.append(
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=ActionType.PR_REVIEW,
                target=None,  # Could try to extract PR number from context
                metadata={
                    "source": "skill",
                    "skill": "codereview-roasted" if is_roasted else "codereview",
                },
                event_id=event.get("id"),
            )
        )
    
    return actions


def _extract_message_content(event: dict) -> str:
    """Extract text content from a message event."""
    content = event.get("content", [])
    
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts)
    
    return ""
