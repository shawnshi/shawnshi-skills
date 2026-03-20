"""
<!-- Input: Work Nodes config path, days to scan -->
<!-- Output: JSON list of recently modified files -->
<!-- Pos: scripts/discovery_engine.py. Scans work directories for new outputs. -->

!!! Maintenance Protocol: File type filters and scan parameters are configurable via CLI.
"""

import os
import json
import argparse
from datetime import datetime, timedelta
import re

# Default file extensions to scan
DEFAULT_EXTENSIONS = ['.md', '.pptx', '.docx', '.pdf', '.xlsx', '.html']

def load_work_nodes(nodes_path):
    """
    Parse references/work_nodes.md to get directory paths.
    """
    paths = []
    if not os.path.exists(nodes_path):
        return paths
    
    with open(nodes_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Simple regex to find paths in markdown (looks for `path`)
    matches = re.findall(r'- \*\*Path\*\*: `(.*?)`', content)
    return matches

def scan_new_files(paths, days=7, extensions=None):
    """
    Scan directories for files modified within the last N days.
    """
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS
    
    new_files = []
    cutoff = datetime.now() - timedelta(days=days)
    
    for path in paths:
        if not os.path.exists(path):
            continue
            
        for root, dirs, files in os.walk(path):
            for file in files:
                # Check file extension
                _, ext = os.path.splitext(file)
                if ext.lower() not in extensions:
                    continue
                    
                file_path = os.path.join(root, file)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if mtime > cutoff:
                        new_files.append({
                            "name": file,
                            "path": file_path,
                            "extension": ext.lower(),
                            "mtime": mtime.strftime("%Y-%m-%d %H:%M:%S")
                        })
                except OSError:
                    continue
    
    # Sort by modification time, newest first
    new_files.sort(key=lambda x: x["mtime"], reverse=True)
    return new_files

def main():
    parser = argparse.ArgumentParser(description="Work Output Discovery Engine")
    parser.add_argument('--days', type=int, default=7, help='Number of days to look back (default: 7)')
    parser.add_argument('--extensions', nargs='+', help=f'File extensions to scan (default: {DEFAULT_EXTENSIONS})')
    parser.add_argument('--output', help='Output JSON file path (default: stdout)')
    parser.add_argument('--nodes', help='Path to work_nodes.md (default: auto-detect)')
    
    args = parser.parse_args()
    
    # Use relative path from script location
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nodes_path = args.nodes or os.path.join(base_dir, "references", "work_nodes.md")
    
    extensions = args.extensions or DEFAULT_EXTENSIONS
    # Ensure extensions have dot prefix
    extensions = [ext if ext.startswith('.') else f'.{ext}' for ext in extensions]
    
    paths = load_work_nodes(nodes_path)
    new_outputs = scan_new_files(paths, days=args.days, extensions=extensions)
    
    result = json.dumps(new_outputs, ensure_ascii=False, indent=2)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"Results saved to {args.output} ({len(new_outputs)} files found)")
    else:
        print(result)

if __name__ == "__main__":
    main()
