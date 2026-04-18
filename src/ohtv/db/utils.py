"""Utility functions for database operations."""

from pathlib import Path

# Reserved source names that cannot be used for extra conversation paths
RESERVED_SOURCES = {"local", "cloud"}


def generate_unique_source_names(paths: list[Path]) -> list[str]:
    """Generate unique source names from directory basenames with collision handling.
    
    Handles collisions both within the provided paths and with reserved built-in
    sources ('local' and 'cloud').
    
    Args:
        paths: List of paths to conversation directories
        
    Returns:
        List of unique source names, one for each path
    """
    if not paths:
        return []
    
    basenames = [path.name for path in paths]
    name_counts: dict[str, int] = {}
    unique_names: list[str] = []
    
    for basename in basenames:
        name = basename.lower().replace(" ", "_").replace("-", "_")
        
        # Handle collision with reserved sources or previously assigned names
        final_name = name
        counter = 1
        while final_name in RESERVED_SOURCES or final_name in name_counts:
            final_name = f"{name}_{counter}"
            counter += 1
        
        name_counts[final_name] = 1
        unique_names.append(final_name)
    
    return unique_names
