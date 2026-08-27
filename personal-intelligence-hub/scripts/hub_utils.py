from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path


HUB_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = HUB_DIR.parent.parent
NEWS_DIR = Path(
    os.environ.get(
        "PIH_NEWS_DIR",
        str(Path.home() / "MEMORY" / "raw" / "news"),
    )
)
RUNTIME_DIR = Path(
    os.environ.get(
        "PIH_RUNTIME_DIR",
        str(Path.home() / "MEMORY" / "brain" / "personal-intelligence-hub" / "runtime"),
    )
)

BLACKBOARD_PATH = RUNTIME_DIR / "intelligence_blackboard.json"
LATEST_SCAN_PATH = RUNTIME_DIR / "latest_scan.json"
CURRENT_SCAN_PATH = RUNTIME_DIR / "current_scan.json"
FETCH_CACHE_PATH = RUNTIME_DIR / "fetch_cache.json"
HISTORY_PATH = NEWS_DIR / ".pih_history_v2.json"
REFINED_PATH = RUNTIME_DIR / "intelligence_current_refined.json"
CANDIDATES_PATH = RUNTIME_DIR / "intelligence_candidates.json"


WINDOWS_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)
WINDOWS_TRANSIENT_REPLACE_ERRORS = {5, 32, 33}


def ensure_runtime_dirs() -> None:
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


def _replace_with_retry(source: Path, destination: Path) -> None:
    for attempt in range(len(WINDOWS_REPLACE_RETRY_DELAYS) + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            retryable = (
                os.name == "nt"
                and exc.winerror in WINDOWS_TRANSIENT_REPLACE_ERRORS
                and attempt < len(WINDOWS_REPLACE_RETRY_DELAYS)
            )
            if not retryable:
                raise
            time.sleep(WINDOWS_REPLACE_RETRY_DELAYS[attempt])


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_with_retry(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def atomic_dump_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def clean_json_output(text: str):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output.")
    return json.loads(match.group(0))


