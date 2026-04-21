import hashlib
import yaml
from pathlib import Path
from ohtv.prompts.metadata import (
    EventFilter, ContextLevel, PromptMetadata,
    DisplaySchema, ColumnDef, FieldRef
)


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


def parse_context_level(data: dict) -> ContextLevel:
    """Parse a context level definition from frontmatter data.
    
    Args:
        data: Dict with 'number', 'name', 'include', and optional 'exclude' and 'truncate' keys
        
    Returns:
        ContextLevel instance
    """
    include = [parse_event_filter(f) for f in data.get("include", [])]
    exclude = [parse_event_filter(f) for f in data.get("exclude", [])]
    
    return ContextLevel(
        number=data.get("number"),
        name=data.get("name", ""),
        include=include,
        exclude=exclude,
        truncate=data.get("truncate", 0)
    )


def parse_field_ref(data: dict | str) -> FieldRef:
    """Parse a field reference from frontmatter data.
    
    Args:
        data: Either a string (field name) or dict with 'field', optional 'format', 'prefix'
        
    Returns:
        FieldRef instance
    """
    if isinstance(data, str):
        return FieldRef(field_name=data)
    return FieldRef(
        field_name=data.get("field", ""),
        format=data.get("format"),
        prefix=data.get("prefix")
    )


def parse_column_def(data: dict) -> ColumnDef:
    """Parse a column definition from frontmatter data.
    
    Args:
        data: Dict with 'name', and either 'field' or 'fields' plus optional formatting
        
    Returns:
        ColumnDef instance
    """
    fields = []
    if "fields" in data:
        fields = [parse_field_ref(f) for f in data["fields"]]
    
    return ColumnDef(
        name=data.get("name", ""),
        field=data.get("field"),
        fields=fields,
        format=data.get("format"),
        width=data.get("width"),
        combine=data.get("combine", "newline"),
        show_when=data.get("show_when")
    )


def parse_display_schema(data: dict) -> DisplaySchema:
    """Parse a display schema from frontmatter data.
    
    Args:
        data: Dict with 'table' key containing column definitions
        
    Returns:
        DisplaySchema instance
    """
    columns = []
    if "table" in data:
        table_data = data["table"]
        if "columns" in table_data:
            columns = [parse_column_def(c) for c in table_data["columns"]]
    
    return DisplaySchema(columns=columns)


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
    
    # Parse context levels - handle both formats
    context_levels = {}
    default_context = 1
    
    if "context_levels" in frontmatter:
        # Old format: context_levels as list
        for level_data in frontmatter["context_levels"]:
            number = level_data.get("number")
            if number is not None:
                context_levels[number] = parse_context_level(level_data)
    elif "context" in frontmatter:
        # New format: nested context with default and levels
        context_data = frontmatter["context"]
        default_context = context_data.get("default", 1)
        
        if "levels" in context_data:
            for number, level_data in context_data["levels"].items():
                level_data_with_number = {**level_data, "number": int(number)}
                context_levels[int(number)] = parse_context_level(level_data_with_number)
    
    # Compute content hash
    content_hash = hashlib.sha256(prompt_content.encode()).hexdigest()[:16]
    
    # Handle output schema (may be nested under "output")
    output_schema = frontmatter.get("output_schema")
    if output_schema is None and "output" in frontmatter:
        output_schema = frontmatter["output"].get("schema")
    
    # Parse display schema if present
    display = None
    if "display" in frontmatter:
        display = parse_display_schema(frontmatter["display"])
    
    return PromptMetadata(
        id=prompt_id,
        family=family,
        variant=variant,
        description=frontmatter.get("description", ""),
        default=frontmatter.get("default", False),
        context_levels=context_levels,
        default_context=frontmatter.get("default_context", default_context),
        output_schema=output_schema,
        handler=frontmatter.get("handler"),
        tags=frontmatter.get("tags", []),
        path=path,
        content=prompt_content,
        content_hash=content_hash,
        display=display
    )
