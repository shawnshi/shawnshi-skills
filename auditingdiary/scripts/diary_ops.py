"""
<!-- Input: Operation (prepend/search/stats/backup/read), File Path, Content/Query -->
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
import tempfile
from datetime import datetime
import json
import glob

# Optimization 1: Centralized Path Mapping to bypass Shell Escaping/Workspace limits
PATH_MAPPING = {
    "privacy": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/privacy",
    "article": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/Article",
    "winning": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/winning",
    "diary": "D:/OneDrive/10-19 战略交付/15. 演讲与输出/15.3 个人文章/note-gen-sync/note-gen-sync/privacy/Diary"
}

def resolve_path(path_alias):
    """Resolves logical alias to absolute path."""
    return PATH_MAPPING.get(path_alias.lower(), path_alias)

def load_config():
    """Load configuration from references/config.md. Returns dict with parsed values."""
    config = {
        "max_backup_count": 50,
        "search_result_limit": 100,
        "context_lines": 20,
        "auto_backup": False,
    }
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references", "config.md")
    if not os.path.exists(config_path):
        return config
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        mapping = {
            "Max Backup Count": ("max_backup_count", int),
            "Search Result Limit": ("search_result_limit", int),
            "Context Lines in Search": ("context_lines", int),
            "Auto Backup": ("auto_backup", lambda v: v.lower() == 'true'),
        }
        for label, (key, cast) in mapping.items():
            match = re.search(rf'{re.escape(label)}.*?\*\*值:\*\*\s*`([^`]+)`', content, re.DOTALL)
            if match:
                try:
                    config[key] = cast(match.group(1).strip())
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return config

CONFIG = load_config()

def validate_content(content):
    """
    Validate content integrity before writing.
    Must contain a date header (e.g., # 2026-02-08).
    """
    if not re.search(r'^#\s\d{4}-\d{2}-\d{2}', content, re.MULTILINE):
        return False, "Content missing standard date header (# YYYY-MM-DD)."
    return True, ""

def get_quarterly_filename(date_str):
    """Determine the filename based on the quarter of the given date."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        quarter = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{quarter}.md"
    except:
        now = datetime.now()
        quarter = (now.month - 1) // 3 + 1
        return f"{now.year}-Q{quarter}.md"

def get_all_diary_files(base_path):
    """Retrieve all markdown files in a directory, or the file itself if it's a file."""
    if os.path.isfile(base_path):
        return [base_path]
    if os.path.isdir(base_path):
        files = glob.glob(os.path.join(base_path, "*.md"))
        return sorted(files)
    return []

def read_all_diary_content(base_path):
    """Read contents of all diary files and concatenate them."""
    files = get_all_diary_files(base_path)
    if not files:
        return ""
    all_content = []
    for file in files:
        with open(file, 'r', encoding='utf-8') as f:
            all_content.append(f.read())
    return "\n\n".join(all_content)

def safe_prepend(file_path, new_content):
    """
    Safely prepend content to a file.
    Creates the file if it doesn't exist.
    If file_path is a directory (doesn't end in .md), determines the quarterly filename.
    """
    file_path = resolve_path(file_path)
    
    # 0. Validation
    is_valid, err_msg = validate_content(new_content)
    if not is_valid:
        return {"status": "error", "message": f"Validation Failed: {err_msg}"}

    # Extract date for filename calculation if path is a directory
    if not file_path.lower().endswith('.md'):
        os.makedirs(file_path, exist_ok=True)
        date_match = re.search(r'^#\s(\d{4}-\d{2}-\d{2})', new_content, re.MULTILINE)
        date_str = date_match.group(1) if date_match else None
        filename = get_quarterly_filename(date_str)
        file_path = os.path.join(file_path, filename)

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

    # 4. Truly Atomic Write (tempfile + os.replace)
    try:
        dir_name = os.path.dirname(os.path.abspath(file_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(full_content)
            os.replace(tmp_path, file_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        return {"status": "success", "message": f"Entry prepended to {file_path}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to write file: {str(e)}"}

def search_diary(file_path, query, context_lines=None):
    file_path = resolve_path(file_path)
    if context_lines is None:
        context_lines = CONFIG["context_lines"]
    search_limit = CONFIG["search_result_limit"]
    
    files = get_all_diary_files(file_path)
    if not files:
        return {"status": "error", "message": f"Diary files not found at {file_path}"}

    matches = []
    current_date = "Unknown Date"
    date_pattern = re.compile(r'^#\s(\d{4}-\d{2}-\d{2})')

    lines = []
    for f_path in files:
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                lines.extend(f.readlines())
        except Exception as e:
             return {"status": "error", "message": f"Failed to read file {f_path}: {str(e)}"}

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
            if len(matches) >= search_limit: break
    
    return {"status": "success", "count": len(matches), "results": matches}

def _split_entries(content):
    """Split diary content into individual date entries."""
    entries = []
    date_pattern = re.compile(r'^#\s(\d{4}-\d{2}-\d{2})', re.MULTILINE)
    matches = list(date_pattern.finditer(content))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        entries.append({"date": m.group(1), "content": content[start:end]})
    return entries

def generate_stats(file_path):
    file_path = resolve_path(file_path)
    content = read_all_diary_content(file_path)
    if not content:
        return {"status": "error", "message": "Diary files not found."}

    stats = {"total_entries": 0, "audits": {"weekly": 0, "monthly": 0, "annual": 0}, "tags": {}, "moods": {"😊": 0, "😐": 0, "😔": 0}, "focus_sum": 0, "focus_count": 0}

    entries = _split_entries(content)
    stats["total_entries"] = len(entries)
    stats["audits"]["weekly"] = content.count("## 本周审计")
    stats["audits"]["monthly"] = content.count("## 月度审计")
    stats["audits"]["annual"] = content.count("## 年度审计")
    tags = re.findall(r'(#[\w/\u4e00-\u9fa5]+)', content)
    for tag in tags:
        if tag[1].isdigit(): continue 
        stats["tags"][tag] = stats["tags"].get(tag, 0) + 1

    mood_pattern = re.compile(r'情绪状态.*?[:：]\s*(.*)', re.MULTILINE)
    for entry in entries:
        mood_match = mood_pattern.search(entry["content"])
        if mood_match:
            mood_line = mood_match.group(1)
            emojis_found = re.findall(r'(😊|😐|😔)', mood_line)
            if len(emojis_found) == 1:
                stats["moods"][emojis_found[0]] += 1
            elif len(emojis_found) > 1:
                stats["moods"][emojis_found[0]] += 1

    focus_matches = re.findall(r'专注度.*?(⭐+)', content)
    for stars in focus_matches:
        stats["focus_sum"] += len(stars); stats["focus_count"] += 1
    if stats["focus_count"] > 0: stats["avg_focus"] = round(stats["focus_sum"] / stats["focus_count"], 2)
    stats["top_tags"] = sorted(stats["tags"].items(), key=lambda x: x[1], reverse=True)[:15]
    return {"status": "success", "data": stats}

def read_diary(file_path, date_from=None, date_to=None):
    """Read diary entries within an optional date range."""
    file_path = resolve_path(file_path)
    content = read_all_diary_content(file_path)
    if not content:
        return {"status": "error", "message": f"Diary files not found at {file_path}"}

    entries = _split_entries(content)
    if date_from or date_to:
        filtered = []
        for entry in entries:
            d = entry["date"]
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            filtered.append(entry)
        entries = filtered
    return {"status": "success", "count": len(entries), "entries": entries}

def backup_diary(file_path, backup_dir):
    file_path = resolve_path(file_path)
    max_backups = CONFIG["max_backup_count"]
    files = get_all_diary_files(file_path)
    if not files: 
        return {"status": "error", "message": "Diary files not found."}
    
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    backup_paths = []
    for file in files:
        filename = os.path.basename(file)
        # Unique backup name for each quarter file
        backup_path = os.path.join(backup_dir, f"{os.path.splitext(filename)[0]}_backup_{timestamp}.md")
        try:
            shutil.copy2(file, backup_path)
            backup_paths.append(backup_path)
        except Exception as e: 
            return {"status": "error", "message": f"Backup failed for {file}: {str(e)}"}
            
    # Cleanup old backups per file prefix
    for file in files:
        filename = os.path.basename(file)
        prefix = os.path.splitext(filename)[0] + "_backup_"
        all_backups_for_file = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith(prefix)])
        if len(all_backups_for_file) > max_backups:
            for old_backup in all_backups_for_file[:-max_backups]:
                try:
                    os.remove(old_backup)
                except:
                    pass

    return {"status": "success", "backup_paths": backup_paths}

def main():
    parser = argparse.ArgumentParser(description="Diary Operations Engine")
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_prepend = subparsers.add_parser('prepend', help='Prepend content to diary file')
    p_prepend.add_argument('--file', required=True)
    p_prepend.add_argument('--content')
    p_prepend.add_argument('--content_file')

    p_search = subparsers.add_parser('search', help='Search diary for a keyword')
    p_search.add_argument('--file', required=True)
    p_search.add_argument('--query', required=True)

    p_read = subparsers.add_parser('read', help='Read diary entries by date range')
    p_read.add_argument('--file', required=True)
    p_read.add_argument('--from', dest='date_from', help='Start date (YYYY-MM-DD)')
    p_read.add_argument('--to', dest='date_to', help='End date (YYYY-MM-DD)')

    p_stats = subparsers.add_parser('stats', help='Generate diary statistics')
    p_stats.add_argument('--file', required=True)

    p_backup = subparsers.add_parser('backup', help='Backup diary file')
    p_backup.add_argument('--file', required=True)
    p_backup.add_argument('--dir', required=True)

    args = parser.parse_args()
    result = {"status": "error", "message": "Unknown command"}

    if args.command == 'prepend':
        content = ""
        if args.content_file:
            try:
                with open(args.content_file, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                result = {"status": "error", "message": f"Failed to read content file: {str(e)}"}
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return
        elif args.content:
            content = args.content.replace('\\n', '\n')
        else:
            result = {"status": "error", "message": "Either --content or --content_file is required for prepend."}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        result = safe_prepend(args.file, content)
    elif args.command == 'search':
        result = search_diary(args.file, args.query)
    elif args.command == 'read':
        result = read_diary(args.file, date_from=args.date_from, date_to=args.date_to)
    elif args.command == 'stats':
        result = generate_stats(args.file)
    elif args.command == 'backup':
        result = backup_diary(args.file, args.dir)

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
