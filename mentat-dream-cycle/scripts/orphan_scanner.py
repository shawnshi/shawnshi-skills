import os
import re
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', required=True, help='Root directory to scan for graph entities (e.g., MEMORY)')
    parser.add_argument('--prefixes', help='Comma-separated list of entity prefixes to filter (e.g. Concept_,Vendor_)')
    parser.add_argument('--limit', type=int, default=10, help='Max number of top orphans to output to stdout')
    parser.add_argument('--out-file', help='Path to output the full JSON report')
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
        defined_entities.add(filepath.stem)
        
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            links = link_pattern.findall(content)
            if links:
                cleaned_links = []
                for raw_link in links:
                    # Strip alias: [[Entity|Alias]] -> Entity
                    clean_link = raw_link.split('|')[0].strip()
                    # Strip potential incorrect .md extension
                    if clean_link.endswith('.md'):
                        clean_link = clean_link[:-3]
                    cleaned_links.append(clean_link)
                
                if cleaned_links:
                    file_to_links[str(filepath.relative_to(root_path))] = list(set(cleaned_links))
                    all_links.update(cleaned_links)
        except Exception:
            pass

    orphans = {}
    for fpath, links in file_to_links.items():
        for link in links:
            if link not in defined_entities:
                if link not in orphans:
                    orphans[link] = []
                orphans[link].append(fpath)

    # Filter by prefixes if provided
    target_prefixes = tuple(args.prefixes.split(',')) if args.prefixes else None
    
    filtered_orphans = {}
    for link, fpaths in orphans.items():
        if target_prefixes is None or link.startswith(target_prefixes):
            filtered_orphans[link] = fpaths

    # Sort orphans by frequency of references to help prioritize creation
    sorted_filtered_keys = sorted(filtered_orphans.keys(), key=lambda k: len(filtered_orphans[k]), reverse=True)

    report_summary = {
        "total_files_scanned": len(defined_entities),
        "total_unique_links": len(all_links),
        "filtered_orphan_count": len(filtered_orphans),
        "top_orphans_by_frequency": sorted_filtered_keys[:args.limit]
    }

    # Print summary to stdout (Safe for LLM Context)
    print(json.dumps(report_summary, indent=2, ensure_ascii=False))

    # Output full report to file if requested
    if args.out_file:
        full_report = {
            "total_files_scanned": len(defined_entities),
            "total_unique_links": len(all_links),
            "filtered_orphan_count": len(filtered_orphans),
            "orphans": filtered_orphans
        }
        with open(args.out_file, 'w', encoding='utf-8') as f:
            json.dump(full_report, f, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    main()
