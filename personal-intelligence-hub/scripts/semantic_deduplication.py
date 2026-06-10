import json
import sqlite3
from pathlib import Path
import sys

def main():
    candidates_path = Path(r"C:\Users\shich\.gemini\MEMORY\raw\news\_runtime\personal-intelligence-hub\intelligence_candidates.json")
    db_path = Path(r"C:\Users\shich\.gemini\MEMORY\wiki\.meta\vector_lake.db")
    
    if not candidates_path.exists():
        return
        
    try:
        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    except Exception:
        return
        
    if not db_path.exists():
        print("[WARNING] Vector lake DB not found, skipping semantic dedup.")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Determine table name to query (nodes, entities, etc.)
        tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        target_table = "nodes" if "nodes" in tables else ("entities" if "entities" in tables else None)
        
        filtered_items = []
        dropped_count = 0
        
        for item in candidates.get("items", []):
            title = item.get("title", "").strip().replace("'", "''")
            if not title:
                continue
                
            if target_table:
                # Check for exact or highly similar substring to avoid duplicate reasoning
                query = f"SELECT id FROM {target_table} WHERE content LIKE '%{title[:30]}%' LIMIT 1"
                try:
                    res = cursor.execute(query).fetchone()
                    if res:
                        dropped_count += 1
                        continue
                except sqlite3.OperationalError:
                    pass
                    
            filtered_items.append(item)
            
        candidates["items"] = filtered_items
        candidates_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Semantic dedup: dropped {dropped_count} duplicates based on Vector Lake.")
    except Exception as e:
        print(f"[WARNING] Semantic dedup failed: {e}")

if __name__ == "__main__":
    main()
