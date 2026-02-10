"""
<!-- Input: Action (init/update/read), Topic, Phase, Data -->
<!-- Output: JSON Status or Workflow State -->
<!-- Pos: scripts/workflow_engine.py. Central nervous system for multi-agent orchestration. -->

!!! Maintenance Protocol: Ensure atomic writes to writing_progress.json.
!!! Used to pass context between Concept Analyzer, Roundtable, and Writer.
"""

import argparse
import json
import os
import sys
from datetime import datetime

STATE_FILE = "writing_progress.json"

def get_project_dir(topic):
    # Sanitize topic for folder name
    safe_topic = "".join([c for c in topic if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
    # Use a standard location in user's workspace
    # Assuming relative to where the script is called, or absolute if configured.
    # For simplicity, we use a 'writing_projects' folder in user home or current root.
    # Here we default to current working dir subfolder for portability.
    return os.path.join("writing_projects", f"{safe_topic}_{datetime.now().strftime('%Y%m')}")

def load_state(project_path):
    file_path = os.path.join(project_path, STATE_FILE)
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"Corrupt state file: {str(e)}"}

def save_state(project_path, data):
    if not os.path.exists(project_path):
        os.makedirs(project_path)
    file_path = os.path.join(project_path, STATE_FILE)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {"status": "success", "path": file_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def init_project(topic):
    project_path = get_project_dir(topic)
    if os.path.exists(os.path.join(project_path, STATE_FILE)):
        return {"status": "exists", "path": project_path, "state": load_state(project_path)}
    
    state = {
        "meta": {
            "topic": topic,
            "created_at": datetime.now().isoformat(),
            "status": "active"
        },
        "phase": "0_initiation",
        "artifacts": {
            "red_team_report": None,
            "research_context": None,
            "outline": None,
            "final_draft": None
        },
        "context": {}
    }
    res = save_state(project_path, state)
    res["project_path"] = project_path
    return res

def update_phase(project_path, phase, data=None):
    state = load_state(project_path)
    if "error" in state: return state
    
    state["phase"] = phase
    if data:
        # Merge data into context
        state["context"].update(data)
        
    return save_state(project_path, state)

def save_artifact(project_path, key, content):
    state = load_state(project_path)
    if "error" in state: return state
    
    # Save content to file
    filename = f"{key}.md"
    file_path = os.path.join(project_path, filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    state["artifacts"][key] = filename
    return save_state(project_path, state)

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Workflow Engine")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Init
    p_init = subparsers.add_parser('init')
    p_init.add_argument('--topic', required=True)

    # Update Phase
    p_update = subparsers.add_parser('update_phase')
    p_update.add_argument('--path', required=True)
    p_update.add_argument('--phase', required=True)
    p_update.add_argument('--data', help="JSON string of context data")

    # Save Artifact
    p_artifact = subparsers.add_parser('save_artifact')
    p_artifact.add_argument('--path', required=True)
    p_artifact.add_argument('--key', required=True, choices=['red_team_report', 'research_context', 'outline', 'final_draft'])
    p_artifact.add_argument('--content', required=True)

    # Read State
    p_read = subparsers.add_parser('read')
    p_read.add_argument('--path', required=True)

    args = parser.parse_args()

    if args.command == 'init':
        print(json.dumps(init_project(args.topic)))
    elif args.command == 'update_phase':
        data = json.loads(args.data) if args.data else None
        print(json.dumps(update_phase(args.path, args.phase, data)))
    elif args.command == 'save_artifact':
        print(json.dumps(save_artifact(args.path, args.key, args.content)))
    elif args.command == 'read':
        print(json.dumps(load_state(args.path), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
