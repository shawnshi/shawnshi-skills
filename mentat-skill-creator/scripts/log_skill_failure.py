import argparse
import json
import datetime
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Log a skill failure for nightly minibatch processing.")
    parser.add_argument("--skill_name", required=True, help="Name of the skill that failed")
    parser.add_argument("--task_input", required=True, help="The user input or context that triggered the failure")
    parser.add_argument("--failure_reason", required=True, help="Description of what went wrong")
    
    args = parser.parse_args()

    # Determine the path to MEMORY
    # Assuming this script is at ~/.gemini/config/skills/mentat-skill-creator/scripts/log_skill_failure.py
    current_dir = Path(__file__).parent.resolve()
    # Go up to ~/.gemini
    gemini_root = current_dir.parent.parent.parent.parent
    
    audit_dir = gemini_root / "MEMORY" / "skill_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    
    log_path = audit_dir / "failure_batch.jsonl"
    
    record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "skill_name": args.skill_name,
        "task_input": args.task_input,
        "failure_reason": args.failure_reason
    }
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
    print(f"Logged failure for {args.skill_name} to minibatch queue.")

if __name__ == "__main__":
    main()
