"""Text building functions for each embedding type.

Converts conversation data into text suitable for embedding.
Supports contextual chunk enrichment (Anthropic's "contextual retrieval" technique).
"""

from dataclasses import dataclass, field
from datetime import datetime

# Minimum characters required for content after subtracting preamble.
# If preamble is so long that less than this remains for content,
# we truncate the preamble to ensure meaningful content is embedded.
MIN_CONTENT_SPACE = 100


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
    
    def prepend_to_text(self, content: str, max_chars: int = 3000, max_refs: int = 7) -> list[str]:
        """Prepend preamble to content, splitting into multiple chunks if needed.
        
        This ensures no data is lost - if content is too long to fit with the
        preamble, it's split into overlapping chunks, each with the preamble.
        
        Args:
            content: The main content text
            max_chars: Maximum total characters (default: 3000 for Ollama safety)
            max_refs: Maximum number of refs in preamble
            
        Returns:
            List of strings, each with preamble + content portion, fitting max_chars
        """
        preamble = self.build_preamble(max_refs=max_refs)
        
        if not preamble:
            # No preamble - just split content if needed
            if len(content) <= max_chars:
                return [content]
            return self._split_content(content, max_chars)
        
        # Calculate available space for content
        available_for_content = max_chars - len(preamble)
        
        if available_for_content < MIN_CONTENT_SPACE:
            # Preamble is too long - shouldn't happen, but handle it
            available_for_content = 500
            preamble = preamble[:max_chars - 500]
        
        # If content fits, return single chunk
        if len(content) <= available_for_content:
            return [preamble + content]
        
        # Split content into pieces that fit, with overlap
        content_pieces = self._split_content(content, available_for_content)
        return [preamble + piece for piece in content_pieces]
    
    def _split_content(self, content: str, max_chars: int, overlap: int = 200) -> list[str]:
        """Split content into overlapping pieces that fit max_chars.
        
        Args:
            content: Text to split
            max_chars: Maximum chars per piece
            overlap: Character overlap between pieces
            
        Returns:
            List of content pieces
        """
        if len(content) <= max_chars:
            return [content]
        
        pieces = []
        start = 0
        
        while start < len(content):
            end = start + max_chars
            
            if end >= len(content):
                # Last piece
                pieces.append(content[start:])
                break
            
            # Try to break at word boundary
            break_at = content.rfind(' ', start, end)
            if break_at > start + max_chars * 0.7:
                end = break_at
            
            pieces.append(content[start:end])
            
            # Next piece starts with overlap
            start = end - overlap
            if start < 0:
                start = 0
        
        return pieces


@dataclass
class ConversationTexts:
    """All text components for a conversation's embeddings.
    
    All fields are lists of TextChunk to support splitting long content
    into multiple overlapping chunks while preserving all data.
    """
    analysis_chunks: list["TextChunk"] = field(default_factory=list)
    summary_chunks: list["TextChunk"] = field(default_factory=list)
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
    initial_content_chunks = chunk_text(content_text)
    
    def _text_to_chunks(text: str | None, metadata: ConversationMetadata | None) -> list[TextChunk]:
        """Convert text to chunks, applying preamble and splitting if needed."""
        if not text or not text.strip():
            return []
        
        if metadata:
            pieces = metadata.prepend_to_text(text)
        else:
            # No metadata - still need to respect max size for Ollama
            max_chars = 3000
            if len(text) <= max_chars:
                pieces = [text]
            else:
                # Simple split without preamble
                pieces = []
                start = 0
                overlap = 200
                while start < len(text):
                    end = min(start + max_chars, len(text))
                    if end < len(text):
                        break_at = text.rfind(' ', start, end)
                        if break_at > start + max_chars * 0.7:
                            end = break_at
                    pieces.append(text[start:end])
                    if end >= len(text):
                        break
                    start = end - overlap
        
        return [
            TextChunk(
                text=piece.strip(),
                chunk_index=i,
                estimated_tokens=int(len(piece.split()) * 1.3),
            )
            for i, piece in enumerate(pieces)
            if piece.strip()
        ]
    
    # Build chunks for all text types
    analysis_chunks = _text_to_chunks(analysis_text, metadata)
    summary_chunks = _text_to_chunks(summary_text, metadata)
    
    # Content chunks - process each initial chunk through preamble/splitting
    content_chunks = []
    chunk_index = 0
    for initial_chunk in initial_content_chunks:
        if metadata:
            pieces = metadata.prepend_to_text(initial_chunk.text)
        else:
            pieces = [initial_chunk.text]
        
        for piece in pieces:
            if piece.strip():
                content_chunks.append(TextChunk(
                    text=piece.strip(),
                    chunk_index=chunk_index,
                    estimated_tokens=int(len(piece.split()) * 1.3),
                ))
                chunk_index += 1

    return ConversationTexts(
        analysis_chunks=analysis_chunks,
        summary_chunks=summary_chunks,
        content_chunks=content_chunks,
    )
