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

VALID_PHASES = [
    "0_initiation", "1_roundtable", "2_ghost_deck",
    "3_drafting", "4_audit", "5_delivery"
]

PHASE_ARTIFACT_MAP = {
    "1_roundtable": ["red_team_report", "research_context"],
    "2_ghost_deck": ["outline"],
    "5_delivery": ["final_draft"],
}

def get_project_dir(topic):
    safe_topic = "".join([c for c in topic if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
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
        # Atomic write: write to temp file first, then rename
        tmp_path = file_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if os.path.exists(file_path):
            os.replace(tmp_path, file_path)
        else:
            os.rename(tmp_path, file_path)
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
        "phase_history": [
            {"phase": "0_initiation", "timestamp": datetime.now().isoformat()}
        ],
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
    
    # Phase gate-checking: validate phase name
    if phase not in VALID_PHASES:
        return {
            "status": "error",
            "message": f"Invalid phase: '{phase}'. Valid phases: {VALID_PHASES}"
        }
    
    current_phase = state.get("phase", "0_initiation")
    current_idx = VALID_PHASES.index(current_phase) if current_phase in VALID_PHASES else -1
    target_idx = VALID_PHASES.index(phase)
    
    # Allow same phase (re-entry) and next phase only. No skipping.
    if target_idx > current_idx + 1:
        return {
            "status": "error",
            "message": f"Phase gate violation: cannot skip from '{current_phase}' to '{phase}'. "
                       f"Next valid phase: '{VALID_PHASES[current_idx + 1]}'"
        }
    
    # Allow rollback (target_idx < current_idx) for troubleshooting
    if target_idx < current_idx:
        rollback_warning = f"Rolling back from '{current_phase}' to '{phase}'"
    else:
        rollback_warning = None
    
    state["phase"] = phase
    if "phase_history" not in state:
        state["phase_history"] = []
    state["phase_history"].append({
        "phase": phase,
        "timestamp": datetime.now().isoformat(),
        "rollback": rollback_warning
    })
    
    if data:
        state["context"].update(data)
        
    result = save_state(project_path, state)
    if rollback_warning:
        result["warning"] = rollback_warning
    return result

def save_artifact(project_path, key, content):
    state = load_state(project_path)
    if "error" in state: return state
    
    # Validate artifact belongs to current or earlier phase
    current_phase = state.get("phase", "0_initiation")
    expected_phases = [p for p, keys in PHASE_ARTIFACT_MAP.items() if key in keys]
    if expected_phases:
        expected_idx = VALID_PHASES.index(expected_phases[0])
        current_idx = VALID_PHASES.index(current_phase) if current_phase in VALID_PHASES else -1
        if current_idx < expected_idx:
            return {
                "status": "error",
                "message": f"Artifact '{key}' belongs to phase '{expected_phases[0]}', "
                           f"but current phase is '{current_phase}'. Advance phase first."
            }
    
    filename = f"{key}.md"
    file_path = os.path.join(project_path, filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    state["artifacts"][key] = filename
    return save_state(project_path, state)

def read_status(project_path):
    state = load_state(project_path)
    if not state:
        return {"status": "error", "message": f"No project found at '{project_path}'"}
    if "error" in state:
        return state
    
    # Enrich with phase progress indicator
    current_phase = state.get("phase", "0_initiation")
    if current_phase in VALID_PHASES:
        idx = VALID_PHASES.index(current_phase)
        state["_progress"] = f"Phase {idx}/{len(VALID_PHASES)-1} ({current_phase})"
        state["_next_phase"] = VALID_PHASES[idx + 1] if idx < len(VALID_PHASES) - 1 else "COMPLETE"
    return state

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Workflow Engine")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Init
    p_init = subparsers.add_parser('init', help='Initialize a new writing project')
    p_init.add_argument('--topic', required=True, help='Topic of the article')

    # Update Phase
    p_update = subparsers.add_parser('update_phase', help='Advance to next phase (gate-checked)')
    p_update.add_argument('--path', required=True, help='Project directory path')
    p_update.add_argument('--phase', required=True, choices=VALID_PHASES,
                         help='Target phase to transition to')
    p_update.add_argument('--data', help="JSON string of context data")

    # Save Artifact
    p_artifact = subparsers.add_parser('save_artifact', help='Save a phase artifact')
    p_artifact.add_argument('--path', required=True, help='Project directory path')
    p_artifact.add_argument('--key', required=True,
                           choices=['red_team_report', 'research_context', 'outline', 'final_draft'],
                           help='Artifact key')
    p_artifact.add_argument('--content', required=True, help='Artifact content (markdown)')

    # Read State
    p_read = subparsers.add_parser('read', help='Read current project state and progress')
    p_read.add_argument('--path', required=True, help='Project directory path')

    args = parser.parse_args()

    if args.command == 'init':
        print(json.dumps(init_project(args.topic), indent=2, ensure_ascii=False))
    elif args.command == 'update_phase':
        data = json.loads(args.data) if args.data else None
        print(json.dumps(update_phase(args.path, args.phase, data), indent=2, ensure_ascii=False))
    elif args.command == 'save_artifact':
        print(json.dumps(save_artifact(args.path, args.key, args.content), indent=2, ensure_ascii=False))
    elif args.command == 'read':
        print(json.dumps(read_status(args.path), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
