from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
CONFIG = SKILL_ROOT / "config" / "business-modes.json"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


research_plan = load_module("discovery_call_research_plan", SCRIPTS / "research_plan.py")
runtime_tx = load_module("runtime_tx", SCRIPTS / "runtime_tx.py")


def run_python(
    script: str,
    args: Sequence[str],
    *,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env["PYTHONDONTWRITEBYTECODE"] = "1"
    process_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / script), *map(str, args)],
        cwd=SKILL_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        env=process_env,
        check=False,
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
