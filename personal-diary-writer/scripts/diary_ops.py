# diary_ops.py - User Diary Atomic I/O Engine (Restored & Cleaned)

import argparse
import sys
import os
import shutil
import re
import tempfile
from datetime import datetime
import json
import glob

PATH_MAPPING = {
    "privacy": "C:/Users/shich/.gemini/MEMORY/privacy",
    "diary": "C:/Users/shich/.gemini/MEMORY/privacy/Diary"
}

def resolve_path(path_alias):
    return PATH_MAPPING.get(path_alias.lower(), path_alias)

def validate_content(content):
    """
    Validate content integrity before writing.
    Enforces User Diary Schema presence (7-header standard).
    """
    if not re.search(r'^#\s\d{4}-\d{2}-\d{2}', content, re.MULTILINE):
        return False, "Content missing standard date header (# YYYY-MM-DD)."
    
    mandatory_headers = ['## 今日工作', '## 核心产出', '## 明日战术锁定', '## 认知结晶', '## 能量管理']
    for h in mandatory_headers:
        if h not in content:
            return False, f"User Diary Schema Violation: Missing mandatory header '{h}'."
            
    return True, ""

def get_quarterly_filename(date_str):
    try:
        clean_date = re.search(r'(\d{4}-\d{2}-\d{2})', date_str).group(1)
        dt = datetime.strptime(clean_date, "%Y-%m-%d")
        quarter = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{quarter}.md"
    except:
        now = datetime.now()
        quarter = (now.month - 1) // 3 + 1
        return f"{now.year}-Q{quarter}.md"

def safe_prepend(file_path, new_content):
    file_path = resolve_path(file_path)
    is_valid, err_msg = validate_content(new_content)
    if not is_valid:
        return {"status": "error", "message": f"Validation Failed: {err_msg}"}

    if not file_path.lower().endswith('.md'):
        os.makedirs(file_path, exist_ok=True)
        date_match = re.search(r'^#\s(\d{4}-\d{2}-\d{2})', new_content, re.MULTILINE)
        date_str = date_match.group(1) if date_match else None
        filename = get_quarterly_filename(date_str)
        file_path = os.path.join(file_path, filename)

    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    existing_content = ""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()

    full_content = new_content + ("\n" if not new_content.endswith("\n") else "") + existing_content
    try:
        dir_name = os.path.dirname(os.path.abspath(file_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(full_content)
        os.replace(tmp_path, file_path)
        return {"status": "success", "message": f"Entry prepended to {file_path}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed: {str(e)}"}

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    p_prepend = subparsers.add_parser('prepend')
    p_prepend.add_argument('--file', required=True)
    p_prepend.add_argument('--content')
    p_prepend.add_argument('--content_file')
    args = parser.parse_args()
    
    content = ""
    if args.content_file:
        with open(args.content_file, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = args.content.replace('\n', '\n')
    
    print(json.dumps(safe_prepend(args.file, content)))

if __name__ == "__main__":
    main()
