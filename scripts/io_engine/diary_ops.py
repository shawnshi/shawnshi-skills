import argparse
import sys
import os
import shutil
import re
import tempfile
from datetime import datetime
import json
import glob

# Dynamically resolve the .gemini path using the user's home directory
GEMINI_ROOT = os.path.join(os.path.expanduser("~"), ".gemini")

PATH_MAPPING = {
    "privacy": os.path.join(GEMINI_ROOT, "MEMORY", "privacy"),
    "diary": os.path.join(GEMINI_ROOT, "MEMORY", "privacy", "Diary"),
    "mentat": os.path.join(GEMINI_ROOT, "MEMORY", "privacy", "Diary", "mentat_audit")
}

def resolve_path(path_alias):
    return PATH_MAPPING.get(path_alias.lower(), path_alias)

def validate_content(content, file_path=""):
    """
    Validate content integrity before writing.
    Enforces dynamic Schema presence based on file path context.
    """
    # 1. 基础的时间戳断言 (所有日记类型都必须有)
    if not re.search(r'^#\s\d{4}-\d{2}-\d{2}', content, re.MULTILINE):
        return False, "Content missing standard date header (# YYYY-MM-DD)."
    
    file_path_lower = file_path.lower()
    
    # 2. 路由校验：Mentat 逻辑审计日志
    if "mentat_audit" in file_path_lower or "mentat" in file_path_lower:
        if "**1. 观测" not in content or "**4. 执行" not in content:
            return False, "Mentat Schema Violation: 缺失核心 OODA 标题 (**1. 观测, **4. 执行)。"
        return True, ""
        
    # 3. 路由校验：周报/复盘类日志 (WEEKLY/MONTHLY)
    if "周报" in content or "复盘" in content or "Weekly" in content:
        # 放宽限制，只要有基础结构即可
        if "战术" not in content and "审计" not in content:
             return False, "Audit Schema Violation: 缺失战术或审计相关内容。"
        return True, ""

    # 4. 路由校验：标准个人日记 (User Diary - 默认降级)
    mandatory_headers = ['## 今日工作', '## 核心产出', '## 明日战术锁定']
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
    
    # 将文件路径传入验证函数，激活基于路径的 Schema 路由
    is_valid, err_msg = validate_content(new_content, file_path)
    if not is_valid:
        return {"status": "error", "message": f"Validation Failed: {err_msg}"}

    if not file_path.lower().endswith('.md'):
        os.makedirs(file_path, exist_ok=True)
        date_match = re.search(r'^#\s(\d{4}-\d{2}-\d{2})', new_content, re.MULTILINE)
        date_str = date_match.group(1) if date_match else None
        
        # 特殊处理 Mentat 审计日志的文件命名 (可选)
        if "mentat_audit" in file_path.lower():
            filename = get_quarterly_filename(date_str).replace(".md", "_Audit.md")
        else:
            filename = get_quarterly_filename(date_str)
            
        file_path = os.path.join(file_path, filename)

    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    existing_content = ""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_content = f.read()

    full_content = new_content + ("\n\n" if not new_content.endswith("\n") else "\n") + existing_content
    try:
        dir_name = os.path.dirname(os.path.abspath(file_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(full_content)
        os.replace(tmp_path, file_path)
        
        # [NEW HOOK] 如果写入成功且包含系统重构标签，抛出强制提醒
        sys_warning = ""
        if "#Architecture" in new_content or "#Mentat" in new_content:
            sys_warning = "🚨 DETECTED SYSTEM REFACTOR TAG. AGENT MUST CALL mentat-insight-diary NOW!"
            
        return {"status": "success", "message": f"Entry prepended to {file_path}", "sys_warning": sys_warning}
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
