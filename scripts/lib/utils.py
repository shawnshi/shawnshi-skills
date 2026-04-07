import json
import re
from pathlib import Path

def discovery_root() -> Path:
    """Dynamically discover the .gemini root directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pai").exists() or (parent / ".env").exists():
            return parent
    # Fallback to a safe guess if discovery fails
    return Path.home() / ".gemini"

PROJECT_ROOT = discovery_root()
NEWS_DIR = PROJECT_ROOT / "MEMORY" / "raw" / "news"
HUB_DIR = PROJECT_ROOT / "skills" / "personal-intelligence-hub"

def clean_json_output(raw_text: str) -> dict:
    """
    Robustly extract and parse JSON from CLI output that may contain 
    headers, footers, or ANSI escape codes.
    """
    # Remove ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|[\[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', raw_text)
    
    # Greedy extraction between first '{' and last '}'
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    
    if start_idx == -1 or end_idx == -1:
        raise ValueError("No JSON object found in response.")
        
    json_str = text[start_idx:end_idx+1]
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Fallback: try to fix common trailing comma issues or other noise
        # This is a basic attempt; further complexity can be added if needed
        raise ValueError(f"Failed to parse extracted JSON: {e}\nRaw extracted: {json_str[:100]}...")

if __name__ == "__main__":
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"News Dir: {NEWS_DIR}")
