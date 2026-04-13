"""Tests for Notion action recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.notion_actions import recognize_notion_actions


class TestRecognizeNotionActions:
    """Tests for Notion action recognition."""
    
    @pytest.fixture
    def make_context(self):
        """Factory for creating recognizer context."""
        def _make(events, current_index=0):
            return RecognizerContext(
                conversation_id="test-conv",
                events=events,
                current_index=current_index,
            )
        return _make
    
    def test_recognizes_notion_read_mcp_tool(self, make_context):
        """Should recognize Notion read via MCP tool."""
        action_event = {
            "id": "event-1",
            "kind": "ActionEvent",
            "tool_name": "context-layer_notion__retrieve_a_page",
            "action": {
                "page_id": "abc123",
            }
        }
        
        context = make_context([action_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.READ_NOTION
        assert actions[0].target == "abc123"
        assert actions[0].metadata["source"] == "mcp"
    
    def test_recognizes_notion_write_mcp_tool(self, make_context):
        """Should recognize Notion write via MCP tool."""
        action_event = {
            "id": "event-2",
            "kind": "ActionEvent",
            "tool_name": "context-layer_notion__post_page",
            "action": {
                "page_id": "def456",
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "Page created"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.WRITE_NOTION
    
    def test_recognizes_notion_search_as_read(self, make_context):
        """Should recognize Notion search as read action."""
        action_event = {
            "id": "event-3",
            "kind": "ActionEvent",
            "tool_name": "context-layer_notion__post_search",
            "action": {}
        }
        
        context = make_context([action_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.READ_NOTION
    
    def test_recognizes_notion_api_read_curl(self, make_context):
        """Should recognize Notion read via curl API call."""
        action_event = {
            "id": "event-4",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "curl -s https://api.notion.com/v1/pages/abc123 -H 'Authorization: Bearer $NOTION_KEY'"
            }
        }
        
        context = make_context([action_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.READ_NOTION
        assert actions[0].metadata["source"] == "api"
    
    def test_recognizes_notion_api_write_curl(self, make_context):
        """Should recognize Notion write via curl POST."""
        action_event = {
            "id": "event-5",
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {
                "command": "curl -X POST https://api.notion.com/v1/pages -d '{...}'"
            }
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 0,
                "content": [{"type": "text", "text": "{}"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.WRITE_NOTION
    
    def test_ignores_failed_notion_write(self, make_context):
        """Should not recognize failed Notion write."""
        action_event = {
            "id": "event-6",
            "kind": "ActionEvent",
            "tool_name": "context-layer_notion__post_page",
            "action": {}
        }
        obs_event = {
            "kind": "ObservationEvent",
            "observation": {
                "exit_code": 1,
                "content": [{"type": "text", "text": "Error"}],
            }
        }
        
        context = make_context([action_event, obs_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 0
    
    def test_ignores_non_action_events(self, make_context):
        """Should not recognize non-ActionEvent."""
        event = {
            "kind": "MessageEvent",
            "role": "user",
        }
        
        context = make_context([event])
        actions = recognize_notion_actions(event, context)
        
        assert len(actions) == 0
    
    def test_ignores_unrelated_tools(self, make_context):
        """Should not recognize unrelated tools."""
        action_event = {
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {"command": "view"},
        }
        
        context = make_context([action_event])
        actions = recognize_notion_actions(action_event, context)
        
        assert len(actions) == 0
