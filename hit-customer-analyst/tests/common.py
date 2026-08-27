from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
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
governance = load_module("governance", SCRIPTS / "governance.py")


def run_python(
    script: str,
    args: Sequence[str],
    *,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / script), *map(str, args)],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=process_env,
        check=False,
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_intake(
    directory: Path,
    customer_name: str,
    business_mode: str,
    *,
    organization_scope: str | None = None,
    conflicting_role: bool = False,
) -> Path:
    """Write a deterministic ready intake, or a deliberately blocked role conflict."""
    candidate_sets = [
        {
            "field": "customer_name",
            "candidates": [
                {
                    "candidate_id": "customer-1",
                    "value": customer_name,
                    "status": "asserted",
                    "source_ref": "test:user-turn:1",
                }
            ],
        },
        {
            "field": "organization_scope",
            "candidates": [
                {
                    "candidate_id": "scope-1",
                    "value": organization_scope or customer_name,
                    "status": "asserted",
                    "source_ref": "test:user-turn:1",
                }
            ],
        },
    ]
    if business_mode in {"briefing", "standard_visit"}:
        role_candidates = [
            {
                "candidate_id": "role-1",
                "value": "信息中心主任",
                "status": "asserted",
                "source_ref": "test:user-turn:1",
            }
        ]
        if conflicting_role:
            role_candidates.append(
                {
                    "candidate_id": "role-2",
                    "value": "分管副院长",
                    "status": "asserted",
                    "source_ref": "test:attachment:1",
                }
            )
        candidate_sets.append({"field": "target_role", "candidates": role_candidates})
        candidate_sets.extend(
            [
                {
                    "field": "visit_objective",
                    "candidates": [{"candidate_id": "objective-1", "value": "核实客户核心任务", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "minimum_next_step",
                    "candidates": [{"candidate_id": "step-1", "value": "确认下一次技术交流", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
            ]
        )
    if business_mode == "strategic_account":
        candidate_sets.extend(
            [
                {
                    "field": "strategy_variant",
                    "candidates": [{"candidate_id": "variant-1", "value": "account_planning", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "strategic_question",
                    "candidates": [{"candidate_id": "question-1", "value": "未来90天是否值得持续投入", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "planning_horizon",
                    "candidates": [{"candidate_id": "horizon-1", "value": "90天", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "minimum_next_step",
                    "candidates": [{"candidate_id": "step-1", "value": "完成机会资格复核", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
            ]
        )
    if business_mode == "letter":
        candidate_sets.extend(
            [
                {
                    "field": "recipient_role",
                    "candidates": [{"candidate_id": "recipient-1", "value": "信息中心主任", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "letter_scenario",
                    "candidates": [{"candidate_id": "scenario-1", "value": "拜访后正式跟进", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "letter_purpose",
                    "candidates": [{"candidate_id": "purpose-1", "value": "确认下一次技术交流安排", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "expected_action",
                    "candidates": [{"candidate_id": "action-1", "value": "确认九月技术交流时间", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "signer",
                    "candidates": [{"candidate_id": "signer-1", "value": "战略咨询部", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
                {
                    "field": "delivery_channel",
                    "candidates": [{"candidate_id": "channel-1", "value": "正式邮件", "status": "asserted", "source_ref": "test:user-turn:1"}],
                },
            ]
        )
    payload = {
        "schema": "discovery-call-intake/v1",
        "request_id": "test-request-001",
        "business_mode": business_mode,
        "candidate_sets": candidate_sets,
        "confirmations": [],
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"intake-{business_mode}-{time.time_ns()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path
