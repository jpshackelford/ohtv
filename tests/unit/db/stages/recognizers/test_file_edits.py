"""Tests for file edit recognizers."""

import pytest

from ohtv.db.models.action import ActionType
from ohtv.db.stages.recognizers.context import RecognizerContext
from ohtv.db.stages.recognizers.file_edits import (
    CODE_EXTENSIONS,
    DOC_EXTENSIONS,
    _classify_file,
    recognize_file_edits,
)


class TestClassifyFile:
    """Tests for file classification."""
    
    def test_classifies_python_files_as_code(self):
        assert _classify_file("/path/to/app.py") == "code"
        assert _classify_file("test.pyi") == "code"
    
    def test_classifies_javascript_files_as_code(self):
        assert _classify_file("app.js") == "code"
        assert _classify_file("component.tsx") == "code"
    
    def test_classifies_go_files_as_code(self):
        assert _classify_file("main.go") == "code"
    
    def test_classifies_markdown_as_docs(self):
        assert _classify_file("README.md") == "docs"
        assert _classify_file("CHANGELOG.md") == "docs"
    
    def test_classifies_rst_as_docs(self):
        assert _classify_file("docs/api.rst") == "docs"
    
    def test_classifies_readme_without_extension_as_docs(self):
        assert _classify_file("README") == "docs"
        assert _classify_file("LICENSE") == "docs"
    
    def test_classifies_json_as_other(self):
        assert _classify_file("package.json") == "other"
    
    def test_classifies_yaml_as_other(self):
        assert _classify_file("config.yaml") == "other"


class TestRecognizeFileEdits:
    """Tests for file edit recognition."""
    
    @pytest.fixture
    def context(self):
        """Create a basic recognizer context."""
        return RecognizerContext(
            conversation_id="test-conv-1",
            events=[],
            current_index=0,
        )
    
    def test_recognizes_code_edit(self, context):
        """Should recognize str_replace on Python file as EDIT_CODE."""
        event = {
            "id": "event-1",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "str_replace",
                "path": "/workspace/app/main.py",
            }
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.EDIT_CODE
        assert actions[0].target == "/workspace/app/main.py"
        assert actions[0].metadata["file_type"] == "code"
    
    def test_recognizes_docs_edit(self, context):
        """Should recognize edit on markdown as EDIT_DOCS."""
        event = {
            "id": "event-2",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "str_replace",
                "path": "/workspace/README.md",
            }
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.EDIT_DOCS
    
    def test_recognizes_create_as_edit(self, context):
        """Should recognize create command as an edit."""
        event = {
            "id": "event-3",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "create",
                "path": "/workspace/new_module.py",
            }
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.EDIT_CODE
    
    def test_recognizes_config_as_other(self, context):
        """Should recognize config file edits as EDIT_OTHER."""
        event = {
            "id": "event-4",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "str_replace",
                "path": "/workspace/config.yaml",
            }
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.EDIT_OTHER
    
    def test_ignores_non_action_events(self, context):
        """Should not recognize non-ActionEvent."""
        event = {
            "kind": "MessageEvent",
            "tool_name": "file_editor",
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 0
    
    def test_ignores_non_file_editor_actions(self, context):
        """Should not recognize non-file_editor tools."""
        event = {
            "kind": "ActionEvent",
            "tool_name": "terminal",
            "action": {"command": "cat file.py"},
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 0
    
    def test_recognizes_view_code_as_study(self, context):
        """Should recognize view on code file as STUDY_CODE (when not editing)."""
        event = {
            "id": "event-5",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "view",
                "path": "/workspace/app.py",
            }
        }
        context.events = [event]
        
        actions = recognize_file_edits(event, context)
        
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.STUDY_CODE
    
    def test_view_before_edit_not_study(self, context):
        """Should not recognize view as study if followed by edit of same file."""
        view_event = {
            "id": "event-6",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "view",
                "path": "/workspace/app.py",
            }
        }
        edit_event = {
            "id": "event-7",
            "kind": "ActionEvent",
            "tool_name": "file_editor",
            "action": {
                "command": "str_replace",
                "path": "/workspace/app.py",
            }
        }
        context.events = [view_event, edit_event]
        context.current_index = 0
        
        actions = recognize_file_edits(view_event, context)
        
        # Should skip because it's followed by an edit
        assert len(actions) == 0
