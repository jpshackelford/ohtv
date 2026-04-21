"""Table renderer for display schema-based output.

The TableRenderer takes analysis results and a display schema,
and renders them as a Rich table.
"""

from typing import Any
from rich.console import Console
from rich.table import Table

from ohtv.prompts.metadata import DisplaySchema, ColumnDef, FieldRef
from ohtv.prompts.formatters import format_value


class TableRenderer:
    """Renders analysis results as a Rich table using display schema."""
    
    def __init__(self, display_schema: DisplaySchema, console: Console | None = None):
        """Initialize renderer with display schema.
        
        Args:
            display_schema: Schema defining table columns and formatting
            console: Rich console for output (creates new one if not provided)
        """
        self.schema = display_schema
        self.console = console or Console()
    
    def _get_field_value(self, data: dict, field_name: str) -> Any:
        """Get a field value from data dict, supporting nested paths.
        
        Args:
            data: Data dictionary
            field_name: Field name (can include dots for nested access)
            
        Returns:
            Field value or None if not found
        """
        if "." in field_name:
            parts = field_name.split(".")
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return None
            return value
        return data.get(field_name)
    
    def _format_field_ref(self, data: dict, field_ref: FieldRef) -> str:
        """Format a single field reference.
        
        Args:
            data: Data dictionary containing field values
            field_ref: Field reference with formatting instructions
            
        Returns:
            Formatted string for this field
        """
        value = self._get_field_value(data, field_ref.field_name)
        if value is None:
            return ""
        
        formatted = format_value(value, field_ref.format)
        
        if field_ref.prefix and formatted:
            return f"{field_ref.prefix} {formatted}"
        return formatted
    
    def _format_cell(self, data: dict, column: ColumnDef) -> str:
        """Format a cell value for a column.
        
        Args:
            data: Row data dictionary
            column: Column definition
            
        Returns:
            Formatted cell string
        """
        field_refs = column.get_field_refs()
        if not field_refs:
            return ""
        
        parts = []
        for field_ref in field_refs:
            formatted = self._format_field_ref(data, field_ref)
            if formatted:
                parts.append(formatted)
        
        if not parts:
            return ""
        
        # Combine parts according to column specification
        combiners = {
            "newline": "\n\n",
            "space": " ",
            "comma": ", ",
        }
        separator = combiners.get(column.combine, "\n\n")
        return separator.join(parts)
    
    def _should_show_column(self, column: ColumnDef, variant: str | None = None) -> bool:
        """Check if column should be shown for current variant.
        
        Args:
            column: Column definition
            variant: Current prompt variant name
            
        Returns:
            True if column should be displayed
        """
        if column.show_when is None:
            return True
        if variant is None:
            return True
        # show_when can be a variant name or comma-separated list
        allowed = [v.strip() for v in column.show_when.split(",")]
        return variant in allowed
    
    def create_table(self, variant: str | None = None) -> Table:
        """Create a Rich Table with column definitions from schema.
        
        Args:
            variant: Current prompt variant (for show_when filtering)
            
        Returns:
            Configured Rich Table
        """
        table = Table(show_header=True, header_style="bold", show_lines=True)
        
        for col in self.schema.columns:
            if not self._should_show_column(col, variant):
                continue
            
            # Apply column styling based on column name
            style = None
            no_wrap = False
            if col.name.lower() == "id":
                style = "cyan"
                no_wrap = True
            elif col.name.lower() == "date":
                no_wrap = True
            
            width = col.width
            table.add_column(col.name, style=style, width=width, no_wrap=no_wrap)
        
        return table
    
    def render(
        self,
        results: list[dict],
        variant: str | None = None,
        show_summary: bool = True,
        total_count: int | None = None,
        error_count: int = 0,
    ) -> None:
        """Render results as a table to console.
        
        Args:
            results: List of result dictionaries
            variant: Current prompt variant (for show_when filtering)
            show_summary: Whether to show summary line after table
            total_count: Total count for summary (defaults to len(results))
            error_count: Number of errors for summary
        """
        table = self.create_table(variant)
        
        for row_data in results:
            row_values = []
            for col in self.schema.columns:
                if not self._should_show_column(col, variant):
                    continue
                cell_value = self._format_cell(row_data, col)
                row_values.append(cell_value)
            table.add_row(*row_values)
        
        self.console.print(table)
        
        if show_summary:
            total = total_count if total_count is not None else len(results)
            showing = len(results)
            cached = sum(1 for r in results if r.get("cached", False))
            
            parts = [f"Showing {showing} of {total}"]
            if showing > 0:
                parts.append(f"({cached}/{showing} cached)")
            if error_count > 0:
                parts.append(f"{error_count} failed")
            
            self.console.print(f"[dim]{' '.join(parts)}[/dim]")


def get_default_display_schema() -> DisplaySchema:
    """Get the default display schema for backward compatibility.
    
    This matches the original hardcoded table format.
    
    Returns:
        DisplaySchema with ID, Date, and Summary columns
    """
    # Import here to avoid circular dependency - cli.py imports from prompts/__init__.py
    # which re-exports this function, and metadata.py is part of the same package
    from ohtv.prompts.metadata import ColumnDef, FieldRef
    
    return DisplaySchema(columns=[
        ColumnDef(name="ID", field="short_id", width=7),
        ColumnDef(name="Date", field="created_at", format="date", width=10),
        ColumnDef(name="Summary", fields=[
            FieldRef(field_name="goal"),
            FieldRef(field_name="refs_display"),
        ], combine="newline"),
    ])
