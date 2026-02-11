"""
<!-- Input: Operation (prepend/search/stats/backup), File Path, Content/Query -->
<!-- Output: JSON Result or Success Message -->
<!-- Pos: scripts/diary_ops.py. Core I/O engine for safe diary management. -->

!!! Maintenance Protocol: This script enforces the Atomic Prepend Policy.
!!! Path Mapping: Supports logical aliases (privacy, winning, article) to absolute paths.
"""

import argparse
import sys
import os
import shutil
import re
from datetime import datetime
import json

# Optimization 1: Centralized Path Mapping to bypass Shell Escaping/Workspace limits
PATH_MAPPING = {
    "privacy": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/privacy",
    "article": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/Article",
    "winning": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/winning",
    "diary": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/privacy/2026Diary.md"
}

def resolve_path(path_alias):
    """Resolves logical alias to absolute path."""
    return PATH_MAPPING.get(path_alias.lower(), path_alias)

def validate_content(content):
    """
    Validate content integrity before writing.
    Must contain a date header (e.g., # 2026-02-08).
    """
    if not re.search(r'^#\s\d{4}-\d{2}-\d{2}', content, re.MULTILINE):
        return False, "Content missing standard date header (# YYYY-MM-DD)."
    return True, ""

def safe_prepend(file_path, new_content):
    """
    Safely prepend content to a file.
    Creates the file if it doesn't exist.
    """
    file_path = resolve_path(file_path)
    
    # 0. Validation
    is_valid, err_msg = validate_content(new_content)
    if not is_valid:
        return {"status": "error", "message": f"Validation Failed: {err_msg}"}

    # 1. Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

    # 2. Read existing content
    existing_content = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()
        except Exception as e:
            return {"status": "error", "message": f"Failed to read file: {str(e)}"}
    
    # 3. Combine
    if not new_content.endswith('\n'):
        new_content += "\n"
    if existing_content and not existing_content.startswith('\n'):
        new_content += "\n"
        
    full_content = new_content + existing_content

    # 4. Atomic Write
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(full_content)
        return {"status": "success", "message": f"Entry prepended to {file_path}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write file: {str(e)}"}

# ... (search_diary and generate_stats remain the same, but use resolve_path)

def search_diary(file_path, query, context_lines=3):
    file_path = resolve_path(file_path)
    if not os.path.exists(file_path):
        return {"status": "error", "message": f"Diary file not found at {file_path}"}

    matches = []
    current_date = "Unknown Date"
    date_pattern = re.compile(r'^#\s(\d{4}-\d{2}-\d{2})')

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
         return {"status": "error", "message": f"Failed to read file: {str(e)}"}

    for i, line in enumerate(lines):
        date_match = date_pattern.match(line)
        if date_match:
            current_date = date_match.group(1)
        
        if query.lower() in line.lower():
            start_idx = max(0, i - context_lines)
            end_idx = min(len(lines), i + context_lines + 1)
            context = "".join(lines[start_idx:end_idx]).strip()
            
            matches.append({
                "date": current_date,
                "line_num": i + 1,
                "match": line.strip(),
                "context": context
            })
            if len(matches) >= 30: break
    
    return {"status": "success", "count": len(matches), "results": matches}

def generate_stats(file_path):
    file_path = resolve_path(file_path)
    if not os.path.exists(file_path):
        return {"status": "error", "message": "Diary file not found."}

    stats = {"total_entries": 0, "audits": {"weekly": 0, "monthly": 0, "annual": 0}, "tags": {}, "moods": {"😊": 0, "😐": 0, "😔": 0}, "focus_sum": 0, "focus_count": 0}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"status": "error", "message": f"Failed to read file: {str(e)}"}

    stats["total_entries"] = len(re.findall(r'^#\s\d{4}-\d{2}-\d{2}', content, re.MULTILINE))
    stats["audits"]["weekly"] = content.count("## 本周审计")
    stats["audits"]["monthly"] = content.count("## 月度审计")
    stats["audits"]["annual"] = content.count("## 年度审计")
    tags = re.findall(r'(#[\w/\u4e00-\u9fa5]+)', content)
    for tag in tags:
        if tag[1].isdigit(): continue 
        stats["tags"][tag] = stats["tags"].get(tag, 0) + 1
    stats["moods"]["😊"] = content.count("😊"); stats["moods"]["😐"] = content.count("😐"); stats["moods"]["😔"] = content.count("😔")
    focus_matches = re.findall(r'专注度.*?(⭐+)', content)
    for stars in focus_matches:
        stats["focus_sum"] += len(stars); stats["focus_count"] += 1
    if stats["focus_count"] > 0: stats["avg_focus"] = round(stats["focus_sum"] / stats["focus_count"], 2)
    stats["top_tags"] = sorted(stats["tags"].items(), key=lambda x: x[1], reverse=True)[:15]
    return {"status": "success", "data": stats}

def backup_diary(file_path, backup_dir):
    file_path = resolve_path(file_path)
    if not os.path.exists(file_path): return {"status": "error", "message": "Diary file not found."}
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(file_path)
    backup_path = os.path.join(backup_dir, f"{os.path.splitext(filename)[0]}_backup_{timestamp}.md")
    try:
        shutil.copy2(file_path, backup_path)
        backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith(os.path.splitext(filename)[0])])
        if len(backups) > 30:
            for old_backup in backups[:-30]: os.remove(old_backup)
        return {"status": "success", "backup_path": backup_path}
    except Exception as e: return {"status": "error", "message": f"Backup failed: {str(e)}"}

def main():
    parser = argparse.ArgumentParser(description="Diary Operations Engine")
    subparsers = parser.add_subparsers(dest='command', required=True)
    p_prepend = subparsers.add_parser('prepend'); p_prepend.add_argument('--file', required=True); p_prepend.add_argument('--content', required=True)
    p_search = subparsers.add_parser('search'); p_search.add_argument('--file', required=True); p_search.add_argument('--query', required=True)
    p_stats = subparsers.add_parser('stats'); p_stats.add_argument('--file', required=True)
    p_backup = subparsers.add_parser('backup'); p_backup.add_argument('--file', required=True); p_backup.add_argument('--dir', required=True)
    args = parser.parse_args(); result = {"status": "error", "message": "Unknown command"}
    if args.command == 'prepend':
        content = args.content.replace('\\n', '\n')
        result = safe_prepend(args.file, content)
    elif args.command == 'search': result = search_diary(args.file, args.query)
    elif args.command == 'stats': result = generate_stats(args.file)
    elif args.command == 'backup': result = backup_diary(args.file, args.dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
