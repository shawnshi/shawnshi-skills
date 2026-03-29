import json
import os
from pathlib import Path
from datetime import datetime

def get_blackboard_file():
    from utils import HUB_DIR
    return HUB_DIR / "tmp" / "intelligence_blackboard.json"

def init_blackboard(trigger_intent):
    file = get_blackboard_file()
    data = {
        "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "status": "INITIATED",
        "intent": trigger_intent,
        "signals": [], # Shared pool for all agents
        "audit_logs": [],
        "artifacts": {}
    }
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data

def update_blackboard(updates):
    file = get_blackboard_file()
    if not file.exists(): data = {}
    else: data = json.loads(file.read_text(encoding='utf-8'))
    
    data.update(updates)
    data["last_updated"] = datetime.now().isoformat()
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def get_blackboard():
    file = get_blackboard_file()
    if not file.exists(): return {}
    return json.loads(file.read_text(encoding='utf-8'))
