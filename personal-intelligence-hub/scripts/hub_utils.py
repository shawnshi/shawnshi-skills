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
        str(Path.home() / ".gemini" / "MEMORY" / "raw" / "news"),
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


def get_api_model() -> str:
    return os.environ.get("PIH_LLM_MODEL", "gemini/gemini-3.1-pro-preview")


def has_llm_runner() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def run_llm(prompt: str, fallback_used: bool = False) -> str:
    from litellm import completion
    import litellm
    litellm.drop_params = True

    if not has_llm_runner():
        raise RuntimeError("No API key configured for personal-intelligence-hub. Set GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY.")

    model = get_api_model()

    try:
        response = completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e)
        if not fallback_used and ("429" in error_msg or "exhausted" in error_msg.lower() or "quota" in error_msg.lower()):
            print(f"[WARN] Primary LLM failed ({error_msg}). Retrying...")
            return run_llm(prompt, fallback_used=True)
        raise RuntimeError(f"LLM API request failed: {error_msg}")
