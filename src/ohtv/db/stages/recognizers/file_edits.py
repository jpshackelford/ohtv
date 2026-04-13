"""Recognizers for file editing actions."""

import os.path
from typing import Sequence

from ohtv.db.models.action import ActionType, ConversationAction
from ohtv.db.stages.recognizers.context import RecognizerContext


# File extensions for code files
CODE_EXTENSIONS = {
    # Python
    ".py", ".pyw", ".pyi",
    # JavaScript/TypeScript
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    # Web
    ".vue", ".svelte", ".astro",
    # Java/JVM
    ".java", ".kt", ".kts", ".scala", ".clj", ".cljs", ".groovy",
    # C/C++
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx",
    # Go
    ".go",
    # Rust
    ".rs",
    # Ruby
    ".rb", ".rake",
    # PHP
    ".php",
    # C#
    ".cs",
    # Swift
    ".swift",
    # Erlang/Elixir
    ".ex", ".exs", ".erl", ".hrl",
    # Lua
    ".lua",
    # Perl
    ".pl", ".pm",
    # R
    ".r", ".R",
    # Shell
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    # Other
    ".sql", ".m", ".mm", ".nim", ".zig", ".d", ".dart", ".v", ".hs", ".ml", ".mli",
}

# File extensions for documentation
DOC_EXTENSIONS = {
    ".md", ".markdown",
    ".rst", ".rest",
    ".txt",
    ".adoc", ".asciidoc",
    ".tex",
    ".org",
    ".wiki",
}

# Documentation filenames (without extension)
DOC_FILENAMES = {
    "readme",
    "changelog",
    "changes",
    "history",
    "news",
    "license",
    "licence",
    "copying",
    "contributing",
    "contributors",
    "authors",
    "todo",
    "makefile",
    "dockerfile",
}


def recognize_file_edits(
    event: dict,
    context: RecognizerContext,
) -> Sequence[ConversationAction]:
    """Recognize file editing actions from file_editor tool calls.
    
    Detects:
    - EDIT_CODE: Edits to code files
    - EDIT_DOCS: Edits to documentation files
    - EDIT_OTHER: Edits to other file types
    - STUDY_CODE: View operations on code files (when studying, not editing)
    """
    if event.get("kind") != "ActionEvent":
        return []
    
    tool_name = event.get("tool_name", "")
    if tool_name != "file_editor":
        return []
    
    action = event.get("action", {})
    if not isinstance(action, dict):
        return []
    
    command = action.get("command", "")
    path = action.get("path", "")
    
    if not path:
        return []
    
    # Determine file type
    file_type = _classify_file(path)
    
    # Editing commands
    if command in ("str_replace", "insert", "create"):
        action_type = {
            "code": ActionType.EDIT_CODE,
            "docs": ActionType.EDIT_DOCS,
            "other": ActionType.EDIT_OTHER,
        }[file_type]
        
        return [
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=action_type,
                target=path,
                metadata={
                    "command": command,
                    "file_type": file_type,
                    "extension": os.path.splitext(path)[1].lower(),
                },
                event_id=event.get("id"),
            )
        ]
    
    # View command - study code (only for code files, and only if no edit follows)
    # We track this to understand research/study patterns
    if command == "view" and file_type == "code":
        # Check if this is part of an edit sequence (view before edit)
        # Look ahead for an edit to the same file
        for i in range(context.current_index + 1, min(context.current_index + 5, len(context.events))):
            future_event = context.events[i]
            if future_event.get("kind") == "ActionEvent":
                future_tool = future_event.get("tool_name", "")
                future_action = future_event.get("action", {})
                if (
                    future_tool == "file_editor"
                    and future_action.get("path") == path
                    and future_action.get("command") in ("str_replace", "insert")
                ):
                    # This view is part of an edit sequence, skip it
                    return []
        
        return [
            ConversationAction(
                id=None,
                conversation_id=context.conversation_id,
                action_type=ActionType.STUDY_CODE,
                target=path,
                metadata={
                    "command": "view",
                    "extension": os.path.splitext(path)[1].lower(),
                },
                event_id=event.get("id"),
            )
        ]
    
    return []


def _classify_file(path: str) -> str:
    """Classify a file as 'code', 'docs', or 'other'."""
    # Get basename and extension
    basename = os.path.basename(path).lower()
    _, ext = os.path.splitext(basename)
    name_without_ext = basename.rsplit(".", 1)[0] if "." in basename else basename
    
    # Check by extension first
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in DOC_EXTENSIONS:
        return "docs"
    
    # Check by filename
    if name_without_ext in DOC_FILENAMES:
        return "docs"
    
    # Config files are "other"
    return "other"
