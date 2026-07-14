from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


HUB_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = HUB_DIR.parent.parent
NEWS_DIR = Path(
    os.environ.get(
        "PIH_NEWS_DIR",
        str(Path.cwd() / "intelligence-output"),
    )
)
RUNTIME_DIR = Path(
    os.environ.get(
        "PIH_RUNTIME_DIR",
        str(NEWS_DIR / "_runtime" / "personal-intelligence-hub"),
    )
)

BLACKBOARD_PATH = RUNTIME_DIR / "intelligence_blackboard.json"
LATEST_SCAN_PATH = RUNTIME_DIR / "latest_scan.json"
CURRENT_SCAN_PATH = RUNTIME_DIR / "current_scan.json"
FETCH_CACHE_PATH = RUNTIME_DIR / "fetch_cache.json"
HISTORY_PATH = RUNTIME_DIR / "pushed_history_v3.json"
REFINED_PATH = NEWS_DIR / "intelligence_current_refined.json"
CANDIDATES_PATH = RUNTIME_DIR / "intelligence_candidates.json"


def ensure_runtime_dirs() -> None:
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_json_output(text: str):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output.")
    return json.loads(match.group(0))


