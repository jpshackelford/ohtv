from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Literal


@dataclass
class FieldRef:
    """Reference to a field in the analysis output, with optional formatting."""
    field_name: str
    format: str | None = None
    prefix: str | None = None


@dataclass
class ColumnDef:
    """Column definition for table display."""
    name: str
    field: str | None = None
    fields: list[FieldRef | str] = dataclass_field(default_factory=list)
    format: str | None = None
    width: int | None = None
    combine: Literal["newline", "space", "comma"] = "newline"
    show_when: str | None = None

    def get_field_refs(self) -> list[FieldRef]:
        """Get all field references as FieldRef objects.
        
        If `field` is set (single field), returns a single-item list.
        If `fields` is set, returns the list with strings converted to FieldRef.
        """
        if self.field:
            return [FieldRef(field_name=self.field, format=self.format)]
        result = []
        for f in self.fields:
            if isinstance(f, str):
                result.append(FieldRef(field_name=f))
            else:
                result.append(f)
        return result


@dataclass
class DisplaySchema:
    """Schema for displaying analysis results in table format."""
    columns: list[ColumnDef] = dataclass_field(default_factory=list)

    def get_column(self, name: str) -> ColumnDef | None:
        """Get column definition by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None


@dataclass
class EventFilter:
    """Filter for matching events in context level definitions."""
    source: Literal["user", "agent", "*"] = "*"
    kind: Literal["MessageEvent", "ActionEvent", "ErrorEvent", "*"] = "*"
    tool: str | None = None

    def matches(self, event: dict) -> bool:
        """Check if this filter matches an event.
        
        Args:
            event: Event dict with 'source', 'kind', and optionally 'tool_name' fields
            
        Returns:
            True if event matches this filter, False otherwise
        """
        if self.source != "*" and event.get("source") != self.source:
            return False
        
        if self.kind != "*" and event.get("kind") != self.kind:
            return False
        
        if self.tool is not None:
            if event.get("kind") != "ActionEvent":
                return False
            if event.get("tool_name") != self.tool:
                return False
        
        return True


@dataclass
class ContextLevel:
    """A context level definition from prompt frontmatter."""
    number: int
    name: str
    include: list[EventFilter]
    exclude: list[EventFilter] = dataclass_field(default_factory=list)
    truncate: int = 0

    def matches(self, event: dict) -> bool:
        """Check if event should be included at this context level.
        
        Match if ANY include filter matches AND NO exclude filter matches.
        
        Args:
            event: Event dict to match against
            
        Returns:
            True if event should be included at this level, False otherwise
        """
        if not any(f.matches(event) for f in self.include):
            return False
        
        if any(f.matches(event) for f in self.exclude):
            return False
        
        return True


@dataclass
class PromptMetadata:
    """Metadata parsed from prompt file frontmatter."""
    id: str
    family: str
    variant: str
    description: str = ""
    default: bool = False
    context_levels: dict[int, ContextLevel] = dataclass_field(default_factory=dict)
    default_context: int = 1
    output_schema: dict | None = None
    handler: str | None = None
    tags: list[str] = dataclass_field(default_factory=list)
    path: Path | None = None
    content: str = ""
    content_hash: str = ""
    display: DisplaySchema | None = None

    def get_context_level(self, level: int | str) -> ContextLevel:
        """Get context level by number or name.
        
        Args:
            level: Context level number or name
            
        Returns:
            ContextLevel matching the given number or name
            
        Raises:
            ValueError: If level not found
        """
        if isinstance(level, int):
            if level not in self.context_levels:
                raise ValueError(f"Unknown context level: {level}")
            return self.context_levels[level]
        
        for ctx in self.context_levels.values():
            if ctx.name == level:
                return ctx
        
        raise ValueError(f"Unknown context level: {level}")
