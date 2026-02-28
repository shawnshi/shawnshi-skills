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
    # Option 1: Step up from this file's location
    # intelligence-hub/scripts/utils.py -> parents[4] is .gemini
    p = Path(__file__).resolve().parents[4]
    if (p / ".env").exists() or (p / "MEMORY").exists():
        return p
        
    # Option 2: Look for .gemini in current working directory and its parents
    p = Path.cwd()
    for parent in [p] + list(p.parents):
        if (parent / ".git").exists() or (parent / ".env").exists():
            return parent
            
    # Fallback to the hardcoded relative path if all else fails
    return Path(__file__).resolve().parents[4]

def get_hub_dir():
    """Returns the intelligence-hub skill directory."""
    return Path(__file__).resolve().parents[1]

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
