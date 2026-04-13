"""Recognizers for Notion actions (MCP tools and API calls)."""

import re
from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext


# Notion MCP tool patterns - these are tool_name values for MCP-based Notion calls
# Read operations
NOTION_READ_TOOLS = {
    "notion__get_self",
    "notion__get_user",
    "notion__get_users",
    "notion__retrieve_a_page",
    "notion__retrieve_a_page_property",
    "notion__retrieve_page_markdown",
    "notion__retrieve_a_block",
    "notion__get_block_children",
    "notion__retrieve_a_data_source",
    "notion__retrieve_database",
    "notion__list_data_source_templates",
    "notion__list_comments",
    "notion__retrieve_comment",
    "notion__list_file_uploads",
    "notion__retrieve_file_upload",
    # Context-layer prefixed versions
    "context-layer_notion__get_self",
    "context-layer_notion__get_user",
    "context-layer_notion__get_users",
    "context-layer_notion__retrieve_a_page",
    "context-layer_notion__retrieve_a_page_property",
    "context-layer_notion__retrieve_page_markdown",
    "context-layer_notion__retrieve_a_block",
    "context-layer_notion__get_block_children",
    "context-layer_notion__retrieve_a_data_source",
    "context-layer_notion__retrieve_database",
    "context-layer_notion__list_data_source_templates",
    "context-layer_notion__list_comments",
    "context-layer_notion__retrieve_comment",
    "context-layer_notion__list_file_uploads",
    "context-layer_notion__retrieve_file_upload",
    "context-layer_notion__post_search",
    "context-layer_notion__post_database_query",
}

# Write operations
NOTION_WRITE_TOOLS = {
    "notion__post_page",
    "notion__patch_page",
    "notion__move_page",
    "notion__update_page_markdown",
    "notion__update_a_block",
    "notion__delete_a_block",
    "notion__patch_block_children",
    "notion__update_a_data_source",
    "notion__update_database",
    "notion__create_a_database",
    "notion__create_database",
    "notion__create_a_comment",
    "notion__create_file",
    "notion__complete_file_upload",
    # Context-layer prefixed versions
    "context-layer_notion__post_page",
    "context-layer_notion__patch_page",
    "context-layer_notion__move_page",
    "context-layer_notion__update_page_markdown",
    "context-layer_notion__update_a_block",
    "context-layer_notion__delete_a_block",
    "context-layer_notion__patch_block_children",
    "context-layer_notion__update_a_data_source",
    "context-layer_notion__update_database",
    "context-layer_notion__create_a_database",
    "context-layer_notion__create_database",
    "context-layer_notion__create_a_comment",
    "context-layer_notion__create_file",
    "context-layer_notion__complete_file_upload",
}

# API call patterns for curl-based Notion access
NOTION_API_READ = re.compile(r"curl.*api\.notion\.com/v1/(search|pages|blocks|databases|users)")
NOTION_API_WRITE = re.compile(r"curl.*-X\s*(POST|PATCH|DELETE).*api\.notion\.com")


def recognize_notion_actions(
    event: dict,
    context: RecognizerContext,
) -> Sequence[ConversationAction]:
    """Recognize Notion actions from MCP tools or API calls.
    
    Detects:
    - READ_NOTION: Reading pages, databases, blocks, users
    - WRITE_NOTION: Creating/updating pages, blocks, databases
    """
    if event.get("kind") != "ActionEvent":
        return []
    
    tool_name = event.get("tool_name", "")
    actions = []
    
    # Check MCP tool names
    if tool_name in NOTION_READ_TOOLS:
        actions.append(
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=ActionType.READ_NOTION,
                target=_extract_notion_target(event),
                metadata={"source": "mcp", "tool": tool_name},
                event_id=event.get("id"),
            )
        )
    elif tool_name in NOTION_WRITE_TOOLS:
        if context.action_succeeded():
            actions.append(
                ConversationAction(
                    id=None,
                    conversation_id=context.conversation_id,
                    action_type=ActionType.WRITE_NOTION,
                    target=_extract_notion_target(event),
                    metadata={"source": "mcp", "tool": tool_name},
                    event_id=event.get("id"),
                )
            )
    
    # Check terminal commands for API calls
    if tool_name == "terminal":
        action = event.get("action", {})
        if isinstance(action, dict):
            command = action.get("command", "")
            
            if NOTION_API_WRITE.search(command):
                if context.action_succeeded():
                    actions.append(
                        ConversationAction(
                            id=None,
                            conversation_id=context.conversation_id,
                            action_type=ActionType.WRITE_NOTION,
                            target=None,
                            metadata={"source": "api"},
                            event_id=event.get("id"),
                        )
                    )
            elif NOTION_API_READ.search(command):
                actions.append(
                    ConversationAction(
                        id=None,
                        conversation_id=context.conversation_id,
                        action_type=ActionType.READ_NOTION,
                        target=None,
                        metadata={"source": "api"},
                        event_id=event.get("id"),
                    )
                )
    
    return actions


def _extract_notion_target(event: dict) -> str | None:
    """Extract page/database ID from Notion action."""
    action = event.get("action", {})
    if not isinstance(action, dict):
        return None
    
    # Look for common ID fields
    for field in ["page_id", "block_id", "database_id", "data_source_id"]:
        if field in action:
            return action[field]
    
    return None
