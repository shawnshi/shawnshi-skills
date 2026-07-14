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
    parser.add_argument('--apply', action='store_true', help='Delete listed files. Without this flag, preview only.')
    args = parser.parse_args()

    max_age_seconds = parse_age(args.max_age)
    now = time.time()
    
    stats = {
        "scanned": 0, 
        "candidates": 0,
        "deleted": 0, 
        "ignored_by_exclude": 0, 
        "ignored_by_age": 0, 
        "errors": 0
    }
    
    root_path = Path(args.path).expanduser().resolve()
    if not root_path.is_dir():
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
                stats["candidates"] += 1
                if args.apply:
                    filepath.unlink()
                    stats["deleted"] += 1
            else:
                stats["ignored_by_age"] += 1
        except Exception as e:
            stats["errors"] += 1

    stats["mode"] = "apply" if args.apply else "preview"
    stats["root"] = str(root_path)
    print(json.dumps(stats, indent=2))

if __name__ == '__main__':
    main()
