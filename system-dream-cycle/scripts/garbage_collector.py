import os
import time
import argparse
import fnmatch
import json
from pathlib import Path

def parse_age(age_str):
    if age_str.endswith('h'):
        return float(age_str[:-1]) * 3600
    if age_str.endswith('d'):
        return float(age_str[:-1]) * 86400
    return float(age_str)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True, help='Directory path to clean')
    parser.add_argument('--max-age', default='24h', help='Age threshold, e.g., 24h, 7d')
    parser.add_argument('--exclude', nargs='*', default=[], help='Glob patterns to exclude')
    args = parser.parse_args()

    max_age_seconds = parse_age(args.max_age)
    now = time.time()
    
    stats = {
        "scanned": 0, 
        "deleted": 0, 
        "ignored_by_exclude": 0, 
        "ignored_by_age": 0, 
        "errors": 0
    }
    
    root_path = Path(args.path)
    if not root_path.exists():
        print(json.dumps({"error": f"Path not found: {args.path}"}))
        return

    exclude_patterns = [pat.strip() for pat in args.exclude]

    for filepath in root_path.rglob('*'):
        if not filepath.is_file():
            continue
            
        stats["scanned"] += 1
        
        rel_path = filepath.relative_to(root_path).as_posix()
        
        # Check exclusion
        is_excluded = any(fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(filepath.name, pat) for pat in exclude_patterns)
        if is_excluded:
            stats["ignored_by_exclude"] += 1
            continue
            
        try:
            mtime = filepath.stat().st_mtime
            age = now - mtime
            if age > max_age_seconds:
                filepath.unlink()
                stats["deleted"] += 1
            else:
                stats["ignored_by_age"] += 1
        except Exception as e:
            stats["errors"] += 1

    print(json.dumps(stats, indent=2))

if __name__ == '__main__':
    main()
