import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

def get_history_file():
    from utils import NEWS_DIR
    return NEWS_DIR / "pushed_history_v2.json"

def generate_fingerprint(title, source):
    """Generate a stable hash for a signal based on title and source."""
    if not title: return "unknown"
    clean_text = "".join(filter(str.isalnum, title.lower()))
    return hashlib.md5(f"{clean_text}|{source.lower()}".encode('utf-8')).hexdigest()

def load_history():
    hfile = get_history_file()
    if not hfile.exists(): 
        return {"urls": {}, "fingerprints": {}}
    try:
        data = json.loads(hfile.read_text(encoding='utf-8'))
        # Ensure correct structure
        if "urls" not in data: data = {"urls": data, "fingerprints": {}}
        
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        # Clean up old records while loading
        return {
            "urls": {u: d for u, d in data.get("urls", {}).items() if d > cutoff},
            "fingerprints": {f: d for f, d in data.get("fingerprints", {}).items() if d > cutoff}
        }
    except Exception: 
        return {"urls": {}, "fingerprints": {}}

def save_history(urls, fingerprints):
    hfile = get_history_file()
    history = load_history()
    now_str = datetime.now().isoformat()
    
    for u in urls: 
        if u: history["urls"][u] = now_str
    for f in fingerprints: 
        if f: history["fingerprints"][f] = now_str
        
    hfile.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')

def is_redundant(url, title, source):
    history = load_history()
    if url and url in history["urls"]: 
        return True
    
    fp = generate_fingerprint(title, source)
    if fp in history["fingerprints"]: 
        return True
        
    return False

if __name__ == "__main__":
    h = load_history()
    print(f"Current blacklist: {len(h['urls'])} URLs, {len(h['fingerprints'])} fingerprints")
