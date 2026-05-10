import os
import re
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', required=True, help='Root directory to scan for graph entities (e.g., MEMORY)')
    args = parser.parse_args()

    root_path = Path(args.dir)
    if not root_path.exists():
        print(json.dumps({"error": f"Path not found: {args.dir}"}))
        return

    link_pattern = re.compile(r'\[\[(.*?)\]\]')
    
    defined_entities = set()
    all_links = set()
    file_to_links = {}

    # Identify all defined entities and extract links
    for filepath in root_path.rglob('*.md'):
        # We consider the filename (without extension) as an entity definition.
        # This matches standard obsidian/roam entity logic.
        defined_entities.add(filepath.stem)
        
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            links = link_pattern.findall(content)
            if links:
                file_to_links[str(filepath.relative_to(root_path))] = list(set(links))
                all_links.update(links)
        except Exception:
            pass

    orphans = {}
    for fpath, links in file_to_links.items():
        for link in links:
            # If the linked entity does not exist as a file stem
            if link not in defined_entities:
                if link not in orphans:
                    orphans[link] = []
                orphans[link].append(fpath)

    # Sort orphans by frequency of references to help prioritize creation
    sorted_orphans = sorted(orphans.keys(), key=lambda k: len(orphans[k]), reverse=True)

    report = {
        "total_files_scanned": len(defined_entities),
        "total_unique_links": len(all_links),
        "orphan_count": len(orphans),
        "top_orphans_by_frequency": sorted_orphans[:10],
        "orphans": orphans
    }
    
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
