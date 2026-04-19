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

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from .assemble_template import assemble
    from .plan_validator import print_validation_report, validate_plan_file
except ImportError:
    from assemble_template import assemble
    from plan_validator import print_validation_report, validate_plan_file

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
    parser.add_argument("--dry-run", action="store_true", help="Validates the plan without invoking COM assembly")
    parser.add_argument("--manifest", help="Optional template manifest JSON path")
    parser.add_argument("--strict", action="store_true", help="Enforce config-root ownership checks during validation")
    args = parser.parse_args()

    plan_file_path = Path(args.plan_file).resolve()
    validation = validate_plan_file(plan_file_path, manifest_path=args.manifest, strict=args.strict)
    if validation["errors"]:
        print_validation_report(validation)
        sys.exit(1)

    if validation["warnings"]:
        print_validation_report(validation)

    data = validation["data"]
    template_path = data["template_path"]
    output_path = data["output_path"]
    plan = data["plan"]

    print(f"[*] Starting assembly driven by: {plan_file_path.name}{' (DRY_RUN)' if args.dry_run else ''}")
    
    if args.dry_run:
        print("[+] Dry-run passed. Plan validation succeeded.")
        sys.exit(0)

    start_time = time.time()
    try:
        assemble(plan, output_path, template_path, manifest_path=args.manifest)
        duration = time.time() - start_time
        write_telemetry(plan_file_path.name, len(plan), duration)
    except Exception as e:
        print(f"[!] Assembly failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
