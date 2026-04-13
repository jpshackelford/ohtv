"""Action recognizers for detecting activities in conversation events.

This module provides an extensible framework for recognizing actions
from conversation events. Each recognizer is a function that examines
an event and its context to determine if it represents a specific action.

To add a new recognizer:
1. Create a function that takes (event, context) and returns list[ConversationAction]
2. Import it here and add to the RECOGNIZERS list

Recognizers are run in order, and each can produce multiple actions.
"""

from typing import Protocol, Sequence

from ohtv.db.models.action import ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.file_edits import recognize_file_edits
from ohtv.db.stages.recognizers.git_operations import recognize_git_operations
from ohtv.db.stages.recognizers.github_actions import recognize_github_actions
from ohtv.db.stages.recognizers.notion_actions import recognize_notion_actions
from ohtv.db.stages.recognizers.research import recognize_research_actions
from ohtv.db.stages.recognizers.skill_invocations import recognize_skill_invocations


class Recognizer(Protocol):
    """Protocol for action recognizers."""
    
    def __call__(
        self,
        event: dict,
        context: RecognizerContext,
    ) -> Sequence[ConversationAction]:
        """Examine an event and return any recognized actions."""
        ...


# Registry of all recognizers. Order matters - run in sequence.
RECOGNIZERS: list[Recognizer] = [
    recognize_file_edits,
    recognize_git_operations,
    recognize_github_actions,
    recognize_notion_actions,
    recognize_research_actions,
    recognize_skill_invocations,
]


def recognize_all(
    event: dict,
    context: RecognizerContext,
) -> list[ConversationAction]:
    """Run all recognizers on an event and collect actions."""
    actions = []
    for recognizer in RECOGNIZERS:
        actions.extend(recognizer(event, context))
    return actions


__all__ = [
    "RECOGNIZERS",
    "Recognizer",
    "RecognizerContext",
    "recognize_all",
]
