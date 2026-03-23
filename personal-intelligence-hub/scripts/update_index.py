import os
import re
import json
import sys
from pathlib import Path
from datetime import datetime

# Add lib to path
LIB_DIR = Path(r"C:\Users\shich\.gemini\scripts\lib")
if str(LIB_DIR) not in sys.path:
    sys.path.append(str(LIB_DIR))

from hub_utils import NEWS_DIR
from history_manager import get_history_file

HISTORY_FILE = get_history_file()

def rebuild_history():
    urls = {}
    fingerprints = {}
    
    # Standard URL pattern (avoids issues with parentheses if simple enough)
    url_pattern = re.compile(r"https?://[^\s\)\"\'\\\[\]<>]+")
    
    today_str = datetime.now().isoformat()
    
    # Scan all briefings
    search_dirs = [NEWS_DIR, NEWS_DIR / "2026Q1"]
    files = []
    for d in search_dirs:
        if d.exists():
            files.extend(list(d.glob("intelligence_*.md")))

    for file in files:
        content = file.read_text(encoding='utf-8')
        matches = url_pattern.findall(content)
        for url in matches:
            # Cleanup trailing common punctuation
            url = url.rstrip('.,;)]')
            urls[url] = today_str

    # Preserve existing history data
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
            if "urls" in data:
                for u, d in data["urls"].items():
                    if u not in urls: urls[u] = d
                for f, d in data.get("fingerprints", {}).items():
                    fingerprints[f] = d
            else:
                # Handle old flat format
                for u, d in data.items():
                    if u not in urls: urls[u] = d
        except: pass

    final_data = {
        "urls": urls,
        "fingerprints": fingerprints
    }
    
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(final_data, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"✅ History rebuilt: {len(urls)} URLs indexed from {len(files)} files.")

if __name__ == "__main__":
    rebuild_history()
