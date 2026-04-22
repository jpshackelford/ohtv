"""Text building functions for each embedding type.

Converts conversation data into text suitable for embedding.
Supports contextual chunk enrichment (Anthropic's "contextual retrieval" technique).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConversationMetadata:
    """Metadata for contextual chunk enrichment.
    
    Used to prepend context to chunks before embedding, improving
    retrieval accuracy (Anthropic's "contextual retrieval" technique).
    """
    conversation_id: str
    created_at: datetime | None = None
    summary: str | None = None
    ref_fqns: list[str] = field(default_factory=list)  # e.g., ["jpshackelford/ohtv#23"]
    
    def build_preamble(self, max_refs: int = 7) -> str:
        """Build a contextual preamble for chunk enrichment.
        
        Args:
            max_refs: Maximum number of refs to include (default: 7)
            
        Returns:
            Formatted preamble string with date, summary, and refs
        """
        parts = []
        
        if self.created_at:
            parts.append(f"Date: {self.created_at.strftime('%Y-%m-%d')}")
        
        if self.summary:
            # Truncate summary if too long
            summary = self.summary[:200] + "..." if len(self.summary) > 200 else self.summary
            parts.append(f"Summary: {summary}")
        
        if self.ref_fqns:
            limited_refs = self.ref_fqns[:max_refs]
            parts.append(f"Related: {', '.join(limited_refs)}")
        
        if parts:
            return "\n".join(parts) + "\n---\n"
        return ""


@dataclass
class ConversationTexts:
    """All text components for a conversation's embeddings."""
    analysis_text: str | None = None
    summary_text: str | None = None
    content_chunks: list["TextChunk"] = field(default_factory=list)


@dataclass
class TextChunk:
    """A chunk of text for embedding."""
    text: str
    chunk_index: int
    estimated_tokens: int


def build_analysis_text(analysis: dict) -> str | None:
    """Build text from cached LLM analysis for 'analysis' embedding.

    This is the highest-signal embedding - what was the conversation about?

    Args:
        analysis: Cached analysis dict (from gen objs)

    Returns:
        Formatted text or None if no meaningful analysis
    """
    if not analysis:
        return None

    parts = []

    goal = analysis.get("goal", "")
    if goal:
        parts.append(f"Goal: {goal}")

    primary = analysis.get("primary_outcomes", [])
    if primary:
        parts.append("Outcomes: " + "; ".join(primary))

    secondary = analysis.get("secondary_outcomes", [])
    if secondary:
        parts.append("Additional: " + "; ".join(secondary))

    tags = analysis.get("tags", [])
    if tags:
        parts.append("Tags: " + ", ".join(tags))

    if not parts:
        return None

    return "\n".join(parts)


def build_summary_text(
    events: list[dict],
    refs: list[dict] | None = None,
) -> str:
    """Build summary text for 'summary' embedding.

    Includes user messages, refs (repos/PRs/issues), and file paths.
    This is the "searchable metadata" embedding.

    Args:
        events: List of conversation events
        refs: List of git refs from database (optional)

    Returns:
        Formatted summary text
    """
    from ohtv.analysis.transcript import extract_message_content

    lines = []
    file_paths: set[str] = set()
    commands: list[str] = []

    for event in events:
        kind = event.get("kind", "")
        source = event.get("source", "")

        if kind == "MessageEvent" and source == "user":
            content = extract_message_content(event)
            if content:
                if len(content) > 1000:
                    content = content[:1000] + "..."
                lines.append(f"[USER]: {content}")

        elif kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            action = event.get("action", {}) or {}

            if tool_name == "file_editor":
                path = action.get("path", "")
                if path:
                    file_paths.add(path)
            elif tool_name == "terminal":
                cmd = action.get("command", "")
                if cmd and len(cmd) < 100:
                    commands.append(cmd)
            elif tool_name == "finish":
                message = action.get("message", "")
                if message:
                    if len(message) > 500:
                        message = message[:500] + "..."
                    lines.append(f"[FINISH]: {message}")

    if refs:
        ref_lines = []
        repos = set()
        prs = []
        issues = []

        for ref in refs:
            ref_type = ref.get("ref_type", "")
            url = ref.get("url", "")

            if ref_type == "repo":
                repos.add(url)
            elif ref_type == "pull_request":
                prs.append(url)
            elif ref_type == "issue":
                issues.append(url)

        if repos:
            ref_lines.append(f"Repositories: {', '.join(repos)}")
        if prs:
            ref_lines.append(f"PRs: {', '.join(prs)}")
        if issues:
            ref_lines.append(f"Issues: {', '.join(issues)}")

        if ref_lines:
            lines.append("[REFS]:\n" + "\n".join(ref_lines))

    if file_paths:
        sorted_paths = sorted(file_paths)[:20]
        lines.append(f"[FILES]: {', '.join(sorted_paths)}")

    if commands:
        unique_cmds = list(dict.fromkeys(commands))[:10]
        lines.append(f"[COMMANDS]: {'; '.join(unique_cmds)}")

    return "\n\n".join(lines)


def build_content_text(events: list[dict]) -> str:
    """Build full content text for 'content' embedding.

    Includes file contents, terminal outputs - the detailed content.
    This gets chunked if too long.

    Args:
        events: List of conversation events

    Returns:
        Full content text
    """
    from ohtv.analysis.transcript import extract_message_content

    sections = []

    for event in events:
        kind = event.get("kind", "")
        source = event.get("source", "")

        if kind == "MessageEvent" and source == "user":
            content = extract_message_content(event)
            if content:
                sections.append(f"[USER]: {content}")

        elif kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            action = event.get("action", {}) or {}

            if tool_name == "file_editor":
                path = action.get("path", "")
                command = action.get("command", "")

                if command == "create":
                    file_text = action.get("file_text", "")
                    if file_text and len(file_text) < 5000:
                        sections.append(f"[FILE {path}]:\n{file_text}")
                elif command == "str_replace":
                    new_str = action.get("new_str", "")
                    if new_str and len(new_str) < 3000:
                        sections.append(f"[EDIT {path}]:\n{new_str}")

            elif tool_name == "terminal":
                cmd = action.get("command", "")
                if cmd:
                    sections.append(f"[COMMAND]: {cmd}")

            elif tool_name == "finish":
                message = action.get("message", "")
                if message:
                    sections.append(f"[FINISH]: {message}")

            elif tool_name == "think":
                thought = action.get("thought", "")
                if thought:
                    sections.append(f"[THINKING]: {thought}")

        elif kind == "ObservationEvent":
            content = event.get("content", "")
            if content and len(content) < 2000:
                if len(content) > 1000:
                    content = content[:1000] + "..."
                sections.append(f"[OUTPUT]: {content}")

    return "\n\n".join(sections)


def build_lean_transcript(events: list[dict]) -> str:
    """Build a lean transcript for embedding (user messages + finish blocks).

    DEPRECATED: Use build_summary_text() or build_content_text() instead.
    Kept for backward compatibility.

    Args:
        events: List of conversation events

    Returns:
        Plain text transcript with speaker labels
    """
    from ohtv.analysis.transcript import extract_message_content

    lines = []

    for event in events:
        kind = event.get("kind", "")
        source = event.get("source", "")

        if kind == "MessageEvent" and source == "user":
            content = extract_message_content(event)
            if content:
                lines.append(f"[USER]: {content}")

        elif kind == "ActionEvent":
            tool_name = event.get("tool_name", "")
            if tool_name == "finish":
                action = event.get("action", {})
                message = action.get("message", "")
                if message:
                    if len(message) > 2000:
                        message = message[:2000] + "..."
                    lines.append(f"[FINISH]: {message}")
            elif tool_name == "think":
                action = event.get("action", {})
                thought = action.get("thought", "")
                if thought:
                    if len(thought) > 1000:
                        thought = thought[:1000] + "..."
                    lines.append(f"[THINKING]: {thought}")

    return "\n\n".join(lines)


def build_conversation_texts(
    events: list[dict],
    analysis: dict | None = None,
    refs: list[dict] | None = None,
    metadata: ConversationMetadata | None = None,
) -> ConversationTexts:
    """Build all text components for a conversation's embeddings.

    Args:
        events: List of conversation events
        analysis: Cached analysis dict (from gen objs)
        refs: List of git refs from database
        metadata: Optional metadata for contextual preamble enrichment

    Returns:
        ConversationTexts with all components (with preambles if metadata provided)
    """
    from .chunking import chunk_text

    analysis_text = build_analysis_text(analysis) if analysis else None
    summary_text = build_summary_text(events, refs)
    content_text = build_content_text(events)
    content_chunks = chunk_text(content_text)
    
    # Apply contextual preamble enrichment if metadata provided
    preamble = metadata.build_preamble() if metadata else ""
    
    if preamble:
        if analysis_text:
            analysis_text = preamble + analysis_text
        if summary_text:
            summary_text = preamble + summary_text
        for chunk in content_chunks:
            chunk.text = preamble + chunk.text

    return ConversationTexts(
        analysis_text=analysis_text.strip() if analysis_text and analysis_text.strip() else None,
        summary_text=summary_text.strip() if summary_text and summary_text.strip() else None,
        content_chunks=content_chunks,
    )
