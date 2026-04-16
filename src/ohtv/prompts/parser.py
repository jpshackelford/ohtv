import hashlib
import yaml
from pathlib import Path
from ohtv.prompts.metadata import EventFilter, ContextLevel, PromptMetadata


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split content into YAML frontmatter dict and remaining content.
    
    Args:
        content: Full file content
        
    Returns:
        Tuple of (frontmatter dict, remaining content)
        Returns ({}, content) if no frontmatter present
    """
    if not content.startswith("---\n"):
        return {}, content
    
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return {}, content
    
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, content
    
    return frontmatter, parts[2]


def parse_event_filter(data: dict) -> EventFilter:
    """Parse an event filter from frontmatter data.
    
    Args:
        data: Dict with optional 'source', 'kind', and 'tool' keys
        
    Returns:
        EventFilter instance
    """
    return EventFilter(
        source=data.get("source", "*"),
        kind=data.get("kind", "*"),
        tool=data.get("tool")
    )


def parse_context_level(number: int, data: dict) -> ContextLevel:
    """Parse a context level definition from frontmatter data.
    
    Args:
        number: Context level number
        data: Dict with 'name', 'include', and optional 'exclude' and 'truncate' keys
        
    Returns:
        ContextLevel instance
    """
    include = [parse_event_filter(f) for f in data.get("include", [])]
    exclude = [parse_event_filter(f) for f in data.get("exclude", [])]
    
    return ContextLevel(
        number=number,
        name=data.get("name", ""),
        include=include,
        exclude=exclude,
        truncate=data.get("truncate", 0)
    )


def parse_prompt_file(path: Path) -> PromptMetadata:
    """Parse a prompt file and extract metadata from YAML frontmatter.
    
    Args:
        path: Path to the prompt .md file
        
    Returns:
        PromptMetadata with parsed frontmatter and content
        
    The frontmatter should be YAML between --- delimiters at the start of the file.
    If no frontmatter, returns metadata with defaults inferred from path.
    """
    content = path.read_text()
    frontmatter, prompt_content = parse_frontmatter(content)
    
    # Infer family/variant from path if not in frontmatter
    # e.g., prompts/objectives/brief.md -> family="objectives", variant="brief"
    # or prompts/brief.md -> family="default", variant="brief"
    stem = path.stem
    parent = path.parent.name if path.parent.name != "prompts" else "default"
    
    family = frontmatter.get("family", parent)
    variant = frontmatter.get("variant", stem)
    prompt_id = frontmatter.get("id", f"{family}.{variant}")
    
    # Parse context levels
    context_levels = {}
    if "context_levels" in frontmatter:
        for level_data in frontmatter["context_levels"]:
            number = level_data.get("number")
            if number is not None:
                context_levels[number] = parse_context_level(number, level_data)
    
    # Compute content hash
    content_hash = hashlib.sha256(prompt_content.encode()).hexdigest()[:16]
    
    return PromptMetadata(
        id=prompt_id,
        family=family,
        variant=variant,
        description=frontmatter.get("description", ""),
        default=frontmatter.get("default", False),
        context_levels=context_levels,
        default_context=frontmatter.get("default_context", 1),
        output_schema=frontmatter.get("output_schema"),
        handler=frontmatter.get("handler"),
        tags=frontmatter.get("tags", []),
        path=path,
        content=prompt_content,
        content_hash=content_hash
    )
