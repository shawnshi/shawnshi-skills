"""
<!-- Input: Action (init/update/read), Project Path, Key, Value -->
<!-- Output: JSON Status or Value -->
<!-- Pos: scripts/memory_manager.py. Semantic Core for research projects. -->

!!! Maintenance Protocol: Ensure atomic writes to prevent corruption of working_memory.json.
"""

import argparse
import json
import os
import sys
from datetime import datetime

MEMORY_FILE = "working_memory.json"
META_FILE = "_DIR_META.md"

def load_memory(project_path):
    file_path = os.path.join(project_path, MEMORY_FILE)
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"Corrupt memory file: {str(e)}"}

def save_memory(project_path, data):
    file_path = os.path.join(project_path, MEMORY_FILE)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "path": file_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def init_project(project_path, topic):
    if not os.path.exists(project_path):
        os.makedirs(project_path)
    
    # 1. Initialize working_memory.json
    memory = {
        "meta": {
            "topic": topic,
            "created_at": datetime.now().isoformat(),
            "status": "🟢 扫描收集"
        },
        "insights": [],
        "entities": {},
        "fact_sheet": {
            "technical_anchors": [],
            "core_viewpoints": []
        },
        "progress": {
            "current_chapter": 0,
            "total_chapters": 0
        }
    }
    status = save_memory(project_path, memory)
    
    # 2. Automatically generate _DIR_META.md (Optimization 3) with GEB-Flow YAML
    meta_content = f"""---
Title: {topic}
Date: {datetime.now().strftime('%Y-%m-%d')}
Status: 🟢 扫描收集
Author: Strategic Architect
---

# _DIR_META.md

## Architecture Vision
Research project: {topic}. 
Structured deep dive following the Research Analyst V6.0 protocol.

## Member Index
- `working_memory.json`: [Meta] Semantic core and state tracker.
- `outline.md`: [Plan] Approved research structure.
- `chapter_*.md`: [Data] Research chapters with standard GEB-Flow headers.
- `sources/`: [Resource] Raw intelligence and references.

> ⚠️ **Protocol**: Managed by research-analyst engine. DO NOT modify manually.
"""
    with open(os.path.join(project_path, META_FILE), 'w', encoding='utf-8') as f:
        f.write(meta_content)
    
    return status

def update_memory(project_path, key, value, action="set"):
    memory = load_memory(project_path)
    if "error" in memory: return memory

    # Support nested keys (e.g., "progress.current_chapter")
    keys = key.split('.')
    target = memory
    for k in keys[:-1]:
        if k not in target: target[k] = {}
        target = target[k]
    
    last_key = keys[-1]

    if action == "set":
        target[last_key] = value
    elif action == "append":
        if last_key not in target: target[last_key] = []
        if isinstance(target[last_key], list):
            target[last_key].append(value)
    
    return save_memory(project_path, memory)

def main():
    parser = argparse.ArgumentParser(description="Research Memory Manager")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Init
    p_init = subparsers.add_parser('init')
    p_init.add_argument('--path', required=True)
    p_init.add_argument('--topic', required=True)

    # Update
    p_update = subparsers.add_parser('update')
    p_update.add_argument('--path', required=True)
    p_update.add_argument('--key', required=True)
    p_update.add_argument('--value', required=True)
    p_update.add_argument('--action', choices=['set', 'append'], default='set')

    # Read
    p_read = subparsers.add_parser('read')
    p_read.add_argument('--path', required=True)

    args = parser.parse_args()

    if args.command == 'init':
        print(json.dumps(init_project(args.path, args.topic)))
    elif args.command == 'update':
        try:
            val = json.loads(args.value)
        except:
            val = args.value
        print(json.dumps(update_memory(args.path, args.key, val, args.action)))
    elif args.command == 'read':
        print(json.dumps(load_memory(args.path), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
