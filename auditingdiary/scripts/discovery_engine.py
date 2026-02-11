import os
import json
from datetime import datetime, timedelta
import re

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

def scan_new_files(paths, days=7):
    """
    Scan directories for files modified within the last N days.
    """
    new_files = []
    cutoff = datetime.now() - timedelta(days=days)
    
    for path in paths:
        if not os.path.exists(path):
            continue
            
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if mtime > cutoff:
                        new_files.append({
                            "name": file,
                            "path": file_path,
                            "mtime": mtime.strftime("%Y-%m-%d %H:%M:%S")
                        })
    return new_files

def main():
    # Use relative path from script location
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nodes_path = os.path.join(base_dir, "references", "work_nodes.md")
    
    paths = load_work_nodes(nodes_path)
    new_outputs = scan_new_files(paths)
    
    print(json.dumps(new_outputs, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
