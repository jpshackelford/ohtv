"""Prompt management for ohtv.

Prompts are stored as markdown files and can be customized by users.
The system checks for user prompts in ~/.ohtv/prompts/ first, then
falls back to the default prompts bundled with the package.

Usage:
    from ohtv.prompts import get_prompt
    
    prompt = get_prompt("brief")  # Gets the brief analysis prompt
    prompt = get_prompt("brief_assess")  # Gets the brief analysis prompt with assessment
"""

import logging
from pathlib import Path

from ohtv.config import get_ohtv_dir

log = logging.getLogger("ohtv")

# Available prompt names (without .md extension)
PROMPT_NAMES = [
    "brief",
    "brief_assess",
    "standard",
    "standard_assess",
    "detailed",
    "detailed_assess",
]


def get_default_prompts_dir() -> Path:
    """Get the path to the default prompts directory bundled with the package."""
    return Path(__file__).parent


def get_user_prompts_dir() -> Path:
    """Get the path to user-customizable prompts directory (~/.ohtv/prompts/)."""
    return get_ohtv_dir() / "prompts"


def get_prompt(name: str) -> str:
    """Load a prompt by name, checking user directory first, then defaults.
    
    Args:
        name: Prompt name without .md extension (e.g., "brief", "standard_assess")
        
    Returns:
        The prompt text content
        
    Raises:
        ValueError: If the prompt name is unknown
        FileNotFoundError: If the prompt file cannot be found
    """
    if name not in PROMPT_NAMES:
        raise ValueError(f"Unknown prompt: {name}. Valid prompts: {', '.join(PROMPT_NAMES)}")
    
    filename = f"{name}.md"
    
    # Check user directory first
    user_path = get_user_prompts_dir() / filename
    if user_path.exists():
        log.debug("Loading user prompt from %s", user_path)
        return user_path.read_text()
    
    # Fall back to default
    default_path = get_default_prompts_dir() / filename
    if default_path.exists():
        log.debug("Loading default prompt from %s", default_path)
        return default_path.read_text()
    
    raise FileNotFoundError(f"Prompt file not found: {filename}")


def init_user_prompts(force: bool = False) -> list[str]:
    """Copy default prompts to user directory for customization.
    
    Args:
        force: If True, overwrite existing user prompts
        
    Returns:
        List of prompt names that were copied
    """
    user_dir = get_user_prompts_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    
    default_dir = get_default_prompts_dir()
    copied = []
    
    for name in PROMPT_NAMES:
        filename = f"{name}.md"
        user_path = user_dir / filename
        default_path = default_dir / filename
        
        if not default_path.exists():
            log.warning("Default prompt missing: %s", filename)
            continue
            
        if user_path.exists() and not force:
            log.debug("Skipping existing user prompt: %s", filename)
            continue
        
        user_path.write_text(default_path.read_text())
        copied.append(name)
        log.debug("Copied prompt: %s", filename)
    
    return copied


def list_prompts() -> list[dict]:
    """List all prompts with their status (default, customized, or missing).
    
    Returns:
        List of dicts with keys: name, status, user_path, default_path
    """
    user_dir = get_user_prompts_dir()
    default_dir = get_default_prompts_dir()
    
    result = []
    for name in PROMPT_NAMES:
        filename = f"{name}.md"
        user_path = user_dir / filename
        default_path = default_dir / filename
        
        has_user = user_path.exists()
        has_default = default_path.exists()
        
        if has_user:
            # Check if customized (different from default)
            if has_default and user_path.read_text() != default_path.read_text():
                status = "customized"
            else:
                status = "copied"
        elif has_default:
            status = "default"
        else:
            status = "missing"
        
        result.append({
            "name": name,
            "status": status,
            "user_path": user_path if has_user else None,
            "default_path": default_path if has_default else None,
        })
    
    return result
