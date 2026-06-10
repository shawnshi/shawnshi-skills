from __future__ import annotations

import sys
from pathlib import Path

# Ensure the scripts directory is in path if executed directly
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

import fetch_news
import refine

def main() -> None:
    print("=== Phase 1: Fetch News ===")
    import asyncio
    asyncio.run(fetch_news.scan_all())
    
    print("\n=== Phase 2: Refine & Deduplicate ===")
    refine.refine()
    
    import semantic_deduplication
    semantic_deduplication.main()
    
    print("\n[OK] Phase 1 and 2 completed.")
    print("You may now invoke the Intelligence Refinement Subagent to process Phase 3 (LLM Refinement).")

if __name__ == "__main__":
    main()
