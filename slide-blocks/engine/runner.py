# -*- coding: utf-8 -*-
"""
runner.py - JSON-driven execution entry point for the slide assembly engine.
Usage: python engine/runner.py <path_to_plan.json>
"""
import sys
import json
import argparse
import time
from datetime import datetime
from pathlib import Path

_ENGINE_DIR = Path(__file__).parent

from assemble_template import assemble

def write_telemetry(plan_name, slide_count, duration):
    """Mentat 强制协议：将执行遥测数据写入全局审计库"""
    audit_dir = Path(r"C:\Users\shich\.gemini\MEMORY\skill_audit")
    if not audit_dir.exists():
        try:
            audit_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return
            
    log_file = audit_dir / "skill-usage.jsonl"
    record = {
        "timestamp": datetime.now().isoformat(),
        "skill_name": "slide-blocks",
        "action": "assemble",
        "plan_name": plan_name,
        "slide_count": slide_count,
        "duration_sec": round(duration, 2),
        "status": "success"
    }
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

def main():
    parser = argparse.ArgumentParser(description="SlideBlocks JSON Runner")
    parser.add_argument("plan_file", help="Path to the JSON plan file")
    parser.add_argument("--dry-run", action="store_true", help="Validates file paths without invoking COM assembly")
    args = parser.parse_args()

    plan_file_path = Path(args.plan_file).resolve()
    if not plan_file_path.exists():
        print(f"[!] Plan file not found: {plan_file_path}")
        sys.exit(1)

    try:
        with open(plan_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] Failed to parse JSON plan: {e}")
        sys.exit(1)

    template_path = data.get("template_path")
    output_path = data.get("output_path")
    plan = data.get("plan")

    if not template_path or not output_path or not plan:
        print("[!] Invalid JSON structure. Must contain 'template_path', 'output_path', and 'plan'.")
        sys.exit(1)

    print(f"[*] Starting assembly driven by: {plan_file_path.name}{' (DRY_RUN)' if args.dry_run else ''}")
    
    if args.dry_run:
        errors = []
        if not Path(template_path).exists():
            errors.append(f"Template not found: {template_path}")
        for i, step in enumerate(plan):
            if "src" in step:
                if not Path(step["src"]).exists():
                    errors.append(f"Step {i} source not found: {step['src']}")
        if errors:
            print("[!] Dry-run failed. Missing files:")
            for e in errors:
                print("   -", e)
            sys.exit(1)
        else:
            print("[+] Dry-run passed. All files exist.")
            sys.exit(0)

    start_time = time.time()
    try:
        assemble(plan, output_path, template_path)
        duration = time.time() - start_time
        write_telemetry(plan_file_path.name, len(plan), duration)
    except Exception as e:
        print(f"[!] Assembly failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
