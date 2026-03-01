"""
<!-- Intelligence Hub: Common Utilities V1.0 -->
"""
import os
from pathlib import Path

def get_project_root():
    """
    Finds the project root directory (.gemini).
    Tries to find it by looking for the '.gemini' folder or by stepping up from the current file.
    """
    # Option 1: Step up from this file's absolute (virtual) location
    # Using .absolute() instead of .resolve() to prevent escaping via symlinks
    p = Path(__file__).absolute()
    for parent in [p] + list(p.parents):
        if parent.name == ".gemini":
            return parent
        # Stronger check to avoid false positives in subdirectories
        if (parent / "MEMORY").exists() and (parent / ".env").exists():
            return parent
            
    # Option 2: Look in current working directory and its parents
    p_cwd = Path.cwd()
    for parent in [p_cwd] + list(p_cwd.parents):
        if parent.name == ".gemini":
            return parent
        if (parent / "MEMORY").exists() and (parent / ".env").exists():
            return parent
            
    # Fallback to the hardcoded relative path if all else fails
    return Path(__file__).absolute().parents[3]

def get_hub_dir():
    """Returns the intelligence-hub skill directory."""
    return Path(__file__).absolute().parents[1]

def get_memory_dir():
    """Returns the project's MEMORY directory."""
    return get_project_root() / "MEMORY"

def get_news_dir():
    """Returns the MEMORY/news directory."""
    return get_memory_dir() / "news"

PROJECT_ROOT = get_project_root()
HUB_DIR = get_hub_dir()
MEMORY_DIR = get_memory_dir()
NEWS_DIR = get_news_dir()
