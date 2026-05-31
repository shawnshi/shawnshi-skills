import argparse
import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

MEMORY_FILE = "working_memory.json"
META_FILE = "_DIR_META.md"
HYPOTHESIS_FILE = "hypothesis_matrix.json"
EVIDENCE_FILE = "evidence_matrix.csv"
OUTLINE_FILE = "outline.md"
PLAN_FILE = "implementation_plan.md"
SCQA_FILE = "scqa_summary.md"


def write_text_atomic(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json_atomic(path: Path, data):
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def load_memory(project_path: Path):
    file_path = project_path / MEMORY_FILE
    if not file_path.exists():
        return {}
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        return {"error": f"Corrupt memory file: {str(exc)}"}


def save_memory(project_path: Path, data):
    file_path = project_path / MEMORY_FILE
    try:
        write_json_atomic(file_path, data)
        return {"status": "success", "path": str(file_path)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def init_project(project_path: Path, topic: str, mode: str):
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / "sources").mkdir(exist_ok=True)
    (project_path / "chapters").mkdir(exist_ok=True)

    memory = {
        "meta": {
            "topic": topic,
            "mode": mode,
            "created_at": datetime.now().isoformat(),
            "status": "🟢 扫描收集",
        },
        "assets": {
            "hypothesis_matrix": HYPOTHESIS_FILE,
            "evidence_matrix": EVIDENCE_FILE,
            "outline": OUTLINE_FILE,
            "implementation_plan": PLAN_FILE,
            "scqa_summary": SCQA_FILE,
            "final_report": "final_report.md",
        },
        "insights": [],
        "entities": {},
        "fact_sheet": {
            "technical_anchors": [],
            "core_viewpoints": [],
            "action_levers": [],
            "residual_risks": [],
        },
        "progress": {
            "current_chapter": 0,
            "total_chapters": 0,
            "phase": "alignment",
        },
    }
    status = save_memory(project_path, memory)

    hypothesis = {
        "topic": topic,
        "mode": mode,
        "status": "open",
        "hypotheses": [],
    }
    write_json_atomic(project_path / HYPOTHESIS_FILE, hypothesis)

    with (project_path / EVIDENCE_FILE).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "source_type", "claim", "evidence", "implication", "status"])

    write_text_atomic(project_path / OUTLINE_FILE, "# Outline\n\n- 待填充的完整判断句标题\n")
    write_text_atomic(project_path / PLAN_FILE, "# Implementation Plan\n\n## Mode\n- {mode}\n\n## Approval Gates\n- Blackboard validate\n- Strategy gate\n".replace("{mode}", mode))
    write_text_atomic(project_path / SCQA_FILE, "# SCQA Summary\n\n## Situation\n\n## Complication\n\n## Question\n\n## Answer\n")

    meta_content = f"""---
Title: {topic}
Date: {datetime.now().strftime('%Y-%m-%d')}
Status: 🟢 扫描收集
Author: Strategic Architect
Mode: {mode}
---

# _DIR_META.md

## Mandatory Assets
- `{MEMORY_FILE}`
- `{HYPOTHESIS_FILE}`
- `{EVIDENCE_FILE}`
- `{OUTLINE_FILE}`
- `{PLAN_FILE}`
- `chapter_*.md`
- `final_report.md`

## Protocol
Project assets are managed by hit-digital-strategy-partner V18.0.
Do not skip the blackboard gate or result gate.
"""
    write_text_atomic(project_path / META_FILE, meta_content)
    return status


def update_memory(project_path: Path, key: str, value, action: str = "set"):
    memory = load_memory(project_path)
    if "error" in memory:
        return memory

    keys = key.split(".")
    target = memory
    for part in keys[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]

    last_key = keys[-1]
    if action == "set":
        target[last_key] = value
    elif action == "append":
        target.setdefault(last_key, [])
        if isinstance(target[last_key], list):
            target[last_key].append(value)

    return save_memory(project_path, memory)


def main():
    parser = argparse.ArgumentParser(description="Research Memory Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init")
    p_init.add_argument("--path", required=True, type=Path)
    p_init.add_argument("--topic", required=True)
    p_init.add_argument("--mode", required=True, choices=["brief", "deep-dive", "board-memo"])

    p_update = subparsers.add_parser("update")
    p_update.add_argument("--path", required=True, type=Path)
    p_update.add_argument("--key", required=True)
    p_update.add_argument("--value", required=True)
    p_update.add_argument("--action", choices=["set", "append"], default="set")

    p_read = subparsers.add_parser("read")
    p_read.add_argument("--path", required=True, type=Path)

    args = parser.parse_args()

    if args.command == "init":
        print(json.dumps(init_project(args.path, args.topic, args.mode), ensure_ascii=False, indent=2))
    elif args.command == "update":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        print(json.dumps(update_memory(args.path, args.key, value, args.action), ensure_ascii=False, indent=2))
    elif args.command == "read":
        print(json.dumps(load_memory(args.path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
