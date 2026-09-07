"""Regression tests for the strategy skill's local state and quality tools.

The suite deliberately exercises the command-line interfaces.  These are the
interfaces used by agents and automation, so exit status and machine-readable
errors are part of the contract alongside the Python implementation details.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
BLACKBOARD = SCRIPTS / "blackboard.py"
ASSEMBLER = SCRIPTS / "assembler.py"
GATE = SCRIPTS / "strategy_gate.py"


def run_cli(
    script: Path,
    *arguments: object,
    timeout: int = 30,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(script), *(str(argument) for argument in arguments)],
        cwd=SKILL_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        input=input_text,
        timeout=timeout,
        check=False,
    )


def json_payload(result: subprocess.CompletedProcess[str]) -> dict:
    """Decode a CLI result regardless of whether success/error uses stdout/stderr."""

    candidates = [result.stdout.strip(), result.stderr.strip()]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise AssertionError(
        "command did not return one JSON object\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def assert_structured_failure(
    test: unittest.TestCase, result: subprocess.CompletedProcess[str]
) -> dict:
    test.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
    test.assertNotIn("Traceback", result.stdout + result.stderr)
    payload = json_payload(result)
    test.assertIn(payload.get("status"), {"error", "fail", "invalid", "draft"})
    return payload


def load_blackboard_module():
    spec = importlib.util.spec_from_file_location(
        "strategy_blackboard_for_tests", BLACKBOARD
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load blackboard module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def brief_state(
    *, compliance_required: bool = False, maturity: str = "review_ready"
) -> dict:
    """Build a minimal schema-current brief with no structural errors."""

    module = load_blackboard_module()
    state = module.default_state("门诊流程优化", "brief")
    state["metadata"]["maturity"] = maturity
    state["alignment"].update(
        {
            "decision": "是否分阶段实施门诊流程优化",
            "questions_to_decide": ["是否批准试点"],
            "audience": ["管理层"],
            "organization": {
                "name": "测试医院",
                "type": "hospital_buyer",
                "region": "中国大陆",
            },
            "time_horizon": {
                "start": "2026-01-01",
                "end": "2026-12-31",
                "description": "一年",
            },
            "success_metrics": [
                {
                    "id": "MET-001",
                    "name": "平均等候时间",
                    "baseline": 30,
                    "target": 20,
                    "unit": "分钟",
                    "timeframe": "上线后三个月",
                    "source": "院方运营报表",
                    "status": "client_provided",
                }
            ],
            "constraints": ["不中断门诊服务"],
            "unacceptable_risks": ["患者安全事件"],
        }
    )
    state["evidence"]["records"] = [
        {
            "evidence_id": "EV-OPS-001",
            "record_type": "verified_fact",
            "claim": "现行流程存在重复录入",
            "source_title": "院方流程访谈纪要",
            "publisher": "测试医院",
            "source_type": "user_material",
            "published_at": None,
            "event_or_data_period": "2026-01-01",
            "accessed_at": "2026-01-01",
            "region_and_population": "中国大陆门诊患者",
            "locator": "院方流程访谈纪要，第1页",
            "method_and_denominator": "流程访谈",
            "limitations": "待通过系统日志复核",
            "independence_group": "院方材料",
            "strength": "medium",
            "status": "active",
            "supersedes": None,
        }
    ]
    state["logic_mesh"]["core_judgment"] = "分阶段推进"
    state["decisions"].update(
        {
            "recommendation": "先试点再扩围",
            "action_levers": ["选择单一科室试点"],
            "management_decisions": ["批准试点范围"],
            "residual_risks": ["采用率不足"],
        }
    )
    state["quantitative_model"].update(
        {
            "applicable": False,
            "not_applicable_reason": "本轮只决定是否进入验证阶段",
        }
    )
    state["portfolio"].update(
        {
            "applicable": False,
            "not_applicable_reason": "本轮只有一个候选项目",
        }
    )
    if compliance_required:
        state["compliance_context"].update(
            {
                "applicability": "required",
                "rationale": "涉及患者健康数据跨境处理",
                "jurisdiction": "中国大陆",
                "as_of": "2026-01-01",
                "intended_use": "内部方案评审",
                "data_types": ["患者健康数据"],
                "affected_users": ["患者", "医务人员"],
                "review_required": True,
                "escalations": [
                    {
                        "reviewer": "测试审核人",
                        "role": "数据合规负责人",
                        "as_of": "2026-01-02",
                        "status": "completed",
                    }
                ],
                "status": "professionally_reviewed",
            }
        )
    else:
        state["compliance_context"].update(
            {
                "applicability": "not_applicable",
                "rationale": "普通内部流程讨论",
            }
        )

    validation = module.validate_state(state)
    if validation.get("errors"):
        raise AssertionError(f"test fixture has schema errors: {validation}")
    if maturity == "decision_ready" and validation.get("ready") is not True:
        raise AssertionError(f"decision-ready fixture is not ready: {validation}")
    return state


def investment_state() -> dict:
    """Build a fully traceable investment case whose arithmetic is reproducible."""

    state = brief_state(maturity="decision_ready")
    state["metadata"]["mode"] = "investment-case"
    state["alignment"]["budget"] = {
        "amount": 200,
        "currency": "CNY",
        "period": "2026",
        "source": "院方预算批复",
        "status": "client_provided",
    }
    state["logic_mesh"].update(
        {
            "alternatives": ["分阶段实施", "维持现状"],
            "counter_evidence": ["采用率不足可能使预期收益无法兑现"],
        }
    )
    state["roadmap"].update(
        {
            "phases": [
                {
                    "id": "PH-001",
                    "name": "试点",
                    "timeframe": "2026Q1",
                    "owner": "PMO",
                    "outcomes": ["完成试点"],
                    "exit_criteria": ["试点验收通过"],
                    "dependencies": [],
                    "status": "proposed",
                }
            ],
            "governance": {
                "executive_sponsor": "分管院长",
                "accountable_owner": "项目负责人",
                "decision_forum": "项目委员会",
                "review_cadence": "每月",
            },
        }
    )
    state["portfolio"].update(
        {
            "applicable": True,
            "not_applicable_reason": "",
            "candidates": [
                {
                    "id": "PRJ-001",
                    "name": "分阶段实施",
                    "category": "数字化",
                    "owner": "PMO",
                    "status": "proposed",
                },
                {
                    "id": "PRJ-002",
                    "name": "维持现状",
                    "category": "替代方案",
                    "owner": "PMO",
                    "status": "proposed",
                },
            ],
            "scoring_criteria": [{"id": "CR-001", "name": "价值", "weight": 1}],
            "prioritization": [
                {"candidate_id": "PRJ-001", "rank": 1},
                {"candidate_id": "PRJ-002", "rank": 2},
            ],
            "gate_results": [
                {
                    "candidate_id": "PRJ-001",
                    "gate": "财务",
                    "result": "pass",
                    "rationale": "预算可用",
                    "owner": "财务负责人",
                },
                {
                    "candidate_id": "PRJ-002",
                    "gate": "战略",
                    "result": "conditional",
                    "rationale": "不满足改进目标",
                    "owner": "管理层",
                },
            ],
        }
    )

    cash_flows = [
        {
            "id": "CF-B-0",
            "scenario_id": "SCN-BASE",
            "period": 0,
            "cost": 100,
            "benefit": 0,
            "net": -100,
        },
        {
            "id": "CF-B-1",
            "scenario_id": "SCN-BASE",
            "period": 1,
            "cost": 0,
            "benefit": 150,
            "net": 150,
        },
        {
            "id": "CF-D-0",
            "scenario_id": "SCN-DOWN",
            "period": 0,
            "cost": 100,
            "benefit": 0,
            "net": -100,
        },
        {
            "id": "CF-D-1",
            "scenario_id": "SCN-DOWN",
            "period": 1,
            "cost": 0,
            "benefit": 80,
            "net": 80,
        },
    ]
    formulas: list[dict] = []
    outputs: list[dict] = []
    scenario_values = {
        "B": {
            "scenario_id": "SCN-BASE",
            "cash_flow_ids": ["CF-B-0", "CF-B-1"],
            "total_benefit": 150,
            "roi": 0.5,
            "npv": 36.36363636,
        },
        "D": {
            "scenario_id": "SCN-DOWN",
            "cash_flow_ids": ["CF-D-0", "CF-D-1"],
            "total_benefit": 80,
            "roi": -0.2,
            "npv": -27.27272727,
        },
    }
    metric_specs = (
        ("TCO", "tco", "nominal_TCO", 100, "CNY"),
        ("BEN", "total_benefit", "total_benefit", None, "CNY"),
        ("ROI", "roi", "roi", None, "ratio"),
        ("NPV", "npv", "npv", None, "CNY"),
    )
    for prefix, values in scenario_values.items():
        for suffix, formula_type, metric, fixed_value, unit in metric_specs:
            formula_id = f"F-{prefix}-{suffix}"
            output_id = f"OUT-{prefix}-{suffix}"
            formula = {
                "id": formula_id,
                "name": f"{prefix}-{suffix}",
                "formula_type": formula_type,
                "scenario_id": values["scenario_id"],
                "expression": f"recompute({formula_type})",
                "input_ids": values["cash_flow_ids"],
                "output_id": output_id,
            }
            if formula_type == "npv":
                formula["discount_rate_assumption_id"] = "AS-R"
            formulas.append(formula)
            outputs.append(
                {
                    "id": output_id,
                    "scenario_id": values["scenario_id"],
                    "formula_id": formula_id,
                    "metric": metric,
                    "value": fixed_value if fixed_value is not None else values[metric],
                    "unit": unit,
                }
            )

    state["quantitative_model"].update(
        {
            "applicable": True,
            "not_applicable_reason": "",
            "model_type": "hospital_buyer",
            "currency": "CNY",
            "horizon_years": 1,
            "discount_rate_assumption_id": "AS-R",
            "validation_tolerance": {
                "amount_absolute": 0.01,
                "ratio_absolute": 0.000001,
                "percentage_point_absolute": 0.05,
                "relative": 0.000001,
            },
            "baseline": {"period": "2025", "cost": 100},
            "counterfactual": {"description": "不实施项目"},
            "assumptions": [
                {
                    "id": "AS-R",
                    "name": "折现率",
                    "value": 0.1,
                    "unit": "ratio",
                    "source": "财务情景假设",
                    "as_of": "2026-01-01",
                    "region": "中国大陆",
                    "status": "scenario_assumption",
                    "rationale": "用于情景测算",
                }
            ],
            "cost_items": [
                {
                    "id": "COST-001",
                    "name": "项目投入",
                    "category": "CapEx",
                    "timing": "t0",
                    "amount": 100,
                    "evidence_id": "EV-OPS-001",
                }
            ],
            "benefit_items": [
                {
                    "id": "BEN-001",
                    "name": "可现金化收益",
                    "type": "cash",
                    "baseline": 0,
                    "formula": "F-B-BEN",
                    "attribution": 1,
                    "owner": "财务负责人",
                    "status": "scenario_assumption",
                    "value": 150,
                }
            ],
            "cash_flows": cash_flows,
            "formulas": formulas,
            "scenarios": [
                {
                    "id": "SCN-BASE",
                    "name": "基准情景",
                    "scenario_type": "base",
                    "assumption_ids": ["AS-R"],
                    "discount_rate_assumption_id": "AS-R",
                    "cash_flow_ids": ["CF-B-0", "CF-B-1"],
                    "output": [
                        "OUT-B-TCO",
                        "OUT-B-BEN",
                        "OUT-B-ROI",
                        "OUT-B-NPV",
                    ],
                },
                {
                    "id": "SCN-DOWN",
                    "name": "下行情景",
                    "scenario_type": "downside",
                    "assumption_ids": ["AS-R"],
                    "discount_rate_assumption_id": "AS-R",
                    "cash_flow_ids": ["CF-D-0", "CF-D-1"],
                    "output": [
                        "OUT-D-TCO",
                        "OUT-D-BEN",
                        "OUT-D-ROI",
                        "OUT-D-NPV",
                    ],
                },
            ],
            "sensitivity": [{"variable": "benefit", "range": "80-150"}],
            "outputs": outputs,
        }
    )

    validation = load_blackboard_module().validate_state(state)
    if validation.get("errors") or validation.get("warnings"):
        raise AssertionError(f"investment fixture is not ready: {validation}")
    return state


def validate_state_cli(
    state: dict, *, strict: bool = True
) -> subprocess.CompletedProcess[str]:
    """Persist a state at the canonical path and exercise the validate CLI."""

    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    path = root / "tmp" / "strategy_blackboard.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    arguments: list[object] = ["--workspace-root", root, "validate"]
    if strict:
        arguments.append("--strict")
    result = run_cli(BLACKBOARD, *arguments)
    directory.cleanup()
    return result


def documented_json(marker: str) -> dict:
    text = (SKILL_ROOT / "examples" / "workflow_example.md").read_text(encoding="utf-8")
    match = re.search(r"<!-- " + re.escape(marker) + r" -->\s*```json\s*(.*?)```", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"missing documented machine example: {marker}")
    return json.loads(match.group(1))


class DocumentedInvestmentContractTests(unittest.TestCase):
    def test_documented_cash_flows_update_and_pass_strict_cli(self):
        patch = documented_json("cash-flow-v2")
        state = investment_state()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tmp" / "strategy_blackboard.json"
            path.parent.mkdir()
            path.write_text(json.dumps(state), encoding="utf-8")
            result = run_cli(BLACKBOARD, "--workspace-root", root, "update",
                             "--section", "quantitative_model", "--value", "-",
                             input_text=json.dumps(patch))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = run_cli(BLACKBOARD, "--workspace-root", root, "validate", "--strict")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json_payload(result)["ready"])

    def test_documented_period_remains_required_and_unique(self):
        for defect in ("missing", "duplicate", "invalid_index"):
            state = investment_state()
            state["quantitative_model"].update(documented_json("cash-flow-v2"))
            rows = state["quantitative_model"]["cash_flows"]
            if defect == "missing":
                del rows[0]["period"]
            elif defect == "duplicate":
                rows[1]["period"] = rows[0]["period"]
            else:
                rows[1]["period_index"] = -1
            with self.subTest(defect=defect):
                payload = assert_structured_failure(self, validate_state_cli(state))
                self.assertFalse(payload["ready"])
                expected = {"missing": "REQUIRED", "duplicate": "DUPLICATE_PERIOD",
                            "invalid_index": "UNVERIFIABLE_FORMULA"}[defect]
                self.assertIn(expected, {x["code"] for x in payload["issues"]})

    def test_unknown_documented_as_gap_and_blocked_not_an_enum(self):
        patch = documented_json("unresolved-gate-v2")
        state = investment_state()
        for section, fields in patch.items():
            state[section].update(fields)
        self.assertEqual(state["metadata"]["maturity"], "blocked")
        self.assertTrue(state["evidence"]["gaps"])
        gate = state["portfolio"]["gate_results"][0]
        self.assertEqual(gate["result"], "fail")
        self.assertIn("GP-", gate["rationale"])
        result = validate_state_cli(state, strict=False)
        self.assertEqual(json_payload(result)["errors"], [])
        self.assertFalse(json_payload(result)["ready"])
        self.assertNotEqual(validate_state_cli(state).returncode, 0)
        gate["result"] = "unknown"
        payload = assert_structured_failure(self, validate_state_cli(state))
        self.assertIn("GATE_RESULT", {x["code"] for x in payload["issues"]})


class BlackboardLockBoundaryTests(unittest.TestCase):
    def test_target_existence_probes_hold_the_same_lock_as_replace(self) -> None:
        module = load_blackboard_module()
        for operation in ("load", "save", "update"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = module.blackboard_path(root)
                state = brief_state()
                with module._file_lock(target, exclusive=True):
                    module._atomic_write_unlocked(target, state)
                real_lock = module._file_lock
                real_exists = Path.exists
                held = False

                @contextmanager
                def guarded_lock(path, *, exclusive):
                    nonlocal held
                    with real_lock(path, exclusive=exclusive):
                        held = True
                        try:
                            yield
                        finally:
                            held = False

                def guarded_exists(path):
                    if path == target:
                        self.assertTrue(held, "target stat escaped the transaction lock")
                    return real_exists(path)

                with patch.object(module, "_file_lock", guarded_lock), patch.object(
                    Path, "exists", guarded_exists
                ), patch.object(module, "_print"):
                    if operation == "load":
                        module.load_state(root)
                    elif operation == "save":
                        module.save_state(target, state)
                    else:
                        module.cmd_update(module.argparse.Namespace(
                            workspace_root=root, expect_revision=None,
                            section="evidence", key="gaps", action="append",
                            value='"synthetic-gap"',
                        ))

    @unittest.skipUnless(sys.platform == "win32", "Windows byte-range lock")
    def test_failed_acquisition_is_not_masked_by_an_unlock_attempt(self) -> None:
        import msvcrt
        module = load_blackboard_module()
        acquisition_error = PermissionError("synthetic lock acquisition failure")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            msvcrt, "locking", side_effect=[acquisition_error, OSError("spurious unlock")]
        ) as locking:
            with self.assertRaises(PermissionError) as caught:
                with module._file_lock(Path(directory) / "state.json", exclusive=True):
                    self.fail("failed acquisition entered the transaction")
            self.assertIs(caught.exception, acquisition_error)
            self.assertEqual(locking.call_count, 1)


class BlackboardCliTests(unittest.TestCase):
    def test_uninitialized_workspace_fails_instead_of_manufacturing_state(self) -> None:
        commands = [
            ("status",),
            ("update", "--section", "evidence", "--key", "gaps",
             "--action", "append", "--value", '"synthetic-gap"'),
        ]
        for arguments in commands:
            with self.subTest(command=arguments[0]), tempfile.TemporaryDirectory() as directory:
                result = run_cli(BLACKBOARD, "--workspace-root", directory, *arguments)
                payload = assert_structured_failure(self, result)
                self.assertEqual(payload["error"]["code"], "NOT_INITIALIZED")
                self.assertEqual(payload["error"]["message"],
                                 "blackboard is not initialized; run the init command first")
                self.assertFalse((Path(directory) / "tmp" / "strategy_blackboard.json").exists())

    def test_ready_is_a_hard_gate_even_with_strict_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            initialized = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "init",
                "--topic",
                "测试主题",
                "--mode",
                "deep-dive",
            )
            self.assertEqual(
                initialized.returncode, 0, initialized.stdout + initialized.stderr
            )
            result = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "ready",
                "--strict",
            )

        payload = assert_structured_failure(self, result)
        self.assertFalse(payload["ready"])
        self.assertTrue(payload["warnings"])

    def test_investment_draft_allows_alignment_or_evidence_as_first_update(
        self,
    ) -> None:
        first_updates = (
            ("alignment", "decision", "set", "是否批准投资案例研究"),
            ("evidence", "gaps", "append", "待补充预算依据"),
        )
        for section, key, action, value in first_updates:
            with (
                self.subTest(section=section),
                tempfile.TemporaryDirectory() as directory,
            ):
                initialized = run_cli(
                    BLACKBOARD,
                    "--workspace-root",
                    directory,
                    "init",
                    "--topic",
                    "渐进式投资案例",
                    "--mode",
                    "investment-case",
                )
                self.assertEqual(
                    initialized.returncode,
                    0,
                    initialized.stdout + initialized.stderr,
                )
                updated = run_cli(
                    BLACKBOARD,
                    "--workspace-root",
                    directory,
                    "update",
                    "--section",
                    section,
                    "--key",
                    key,
                    "--action",
                    action,
                    "--value",
                    json.dumps(value, ensure_ascii=False),
                )
                self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
                status = json_payload(
                    run_cli(BLACKBOARD, "--workspace-root", directory, "status")
                )

            self.assertEqual(status["revision"], 1)
            stored = status["state"][section][key]
            self.assertEqual(stored, [value] if action == "append" else value)

    def test_enabled_investment_model_still_blocks_bad_cash_flow_and_reference(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            initialized = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "init",
                "--topic",
                "错误量化模型",
                "--mode",
                "investment-case",
            )
            self.assertEqual(
                initialized.returncode, 0, initialized.stdout + initialized.stderr
            )
            result = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "update",
                "--section",
                "quantitative_model",
                "--value",
                json.dumps(
                    {
                        "applicable": True,
                        "horizon_years": 1,
                        "cash_flows": [
                            {
                                "id": "CF-BAD",
                                "scenario_id": "SCN-NOT-FOUND",
                                "period": 0,
                                "cost": 100,
                                "benefit": 0,
                                "net": 999,
                            }
                        ],
                    }
                ),
            )
            status = json_payload(
                run_cli(BLACKBOARD, "--workspace-root", directory, "status")
            )

        payload = assert_structured_failure(self, result)
        self.assertEqual(payload["error"]["code"], "INVALID_UPDATE")
        errors = payload["error"]["details"]["errors"]
        self.assertTrue(
            any("existing scenario ID" in error for error in errors), payload
        )
        self.assertTrue(
            any("does not equal benefit-cost" in error for error in errors), payload
        )
        self.assertEqual(status["revision"], 0)
        self.assertIsNone(status["state"]["quantitative_model"]["applicable"])
        self.assertEqual(status["state"]["quantitative_model"]["cash_flows"], [])

    def test_fifty_concurrent_appends_are_atomic_and_lossless(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            initialized = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "init",
                "--topic",
                "并发测试",
                "--mode",
                "deep-dive",
            )
            self.assertEqual(
                initialized.returncode, 0, initialized.stdout + initialized.stderr
            )

            start_together = threading.Barrier(50)

            def append(index: int) -> subprocess.CompletedProcess[str]:
                start_together.wait(timeout=15)
                return run_cli(
                    BLACKBOARD,
                    "--workspace-root",
                    directory,
                    "update",
                    "--section",
                    "evidence",
                    "--key",
                    "gaps",
                    "--action",
                    "append",
                    "--value",
                    json.dumps(f"gap-{index:02d}"),
                    timeout=60,
                )

            with ThreadPoolExecutor(max_workers=50) as executor:
                results = list(executor.map(append, range(50)))

            failures = [
                (result.returncode, result.stdout, result.stderr)
                for result in results
                if result.returncode != 0
            ]
            self.assertEqual(failures, [])

            path = Path(directory) / "tmp" / "strategy_blackboard.json"
            state = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(state["metadata"]["revision"], 50)
        self.assertEqual(len(state["evidence"]["gaps"]), 50)
        self.assertEqual(
            set(state["evidence"]["gaps"]),
            {f"gap-{index:02d}" for index in range(50)},
        )

    def test_corrupt_json_returns_structured_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tmp" / "strategy_blackboard.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"metadata": ', encoding="utf-8")
            result = run_cli(BLACKBOARD, "--workspace-root", directory, "validate")

        payload = assert_structured_failure(self, result)
        self.assertEqual(payload["error"]["code"], "INVALID_JSON")
        self.assertIn("line", payload["error"]["details"])

    def test_update_accepts_json_from_file_and_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            initialized = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "init",
                "--topic",
                "批量输入测试",
                "--mode",
                "brief",
            )
            self.assertEqual(
                initialized.returncode, 0, initialized.stdout + initialized.stderr
            )

            value_file = Path(directory) / "alignment.json"
            value_file.write_text(
                json.dumps(
                    {
                        "decision": "来自文件的决策问题",
                        "audience": ["管理层"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            from_file = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "update",
                "--section",
                "alignment",
                "--value",
                f"@{value_file}",
            )
            self.assertEqual(
                from_file.returncode, 0, from_file.stdout + from_file.stderr
            )

            from_stdin = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "update",
                "--section",
                "decisions",
                "--key",
                "residual_risks",
                "--value",
                "-",
                input_text='["stdin-risk"]',
            )
            self.assertEqual(
                from_stdin.returncode, 0, from_stdin.stdout + from_stdin.stderr
            )

            status = run_cli(BLACKBOARD, "--workspace-root", directory, "status")
            state = json_payload(status)["state"]

        self.assertEqual(state["alignment"]["decision"], "来自文件的决策问题")
        self.assertEqual(state["alignment"]["audience"], ["管理层"])
        self.assertEqual(state["decisions"]["residual_risks"], ["stdin-risk"])

    def test_external_update_value_rejects_bad_json_structurally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            initialized = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "init",
                "--topic",
                "坏JSON测试",
                "--mode",
                "brief",
            )
            self.assertEqual(
                initialized.returncode, 0, initialized.stdout + initialized.stderr
            )

            malformed_file = Path(directory) / "malformed.json"
            malformed_file.write_text('{"decision": ', encoding="utf-8")
            file_result = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "update",
                "--section",
                "alignment",
                "--value",
                f"@{malformed_file}",
            )
            stdin_result = run_cli(
                BLACKBOARD,
                "--workspace-root",
                directory,
                "update",
                "--section",
                "decisions",
                "--key",
                "residual_risks",
                "--value",
                "-",
                input_text='["unfinished"',
            )

        for transport, result in (("file", file_result), ("stdin", stdin_result)):
            with self.subTest(transport=transport):
                payload = assert_structured_failure(self, result)
                self.assertEqual(payload["error"]["code"], "VALUE_JSON_INVALID")
                self.assertIn("line", payload["error"]["details"])

    def test_correct_investment_values_pass_strict_recalculation(self) -> None:
        result = validate_state_cli(investment_state())

        payload = json_payload(result)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["warnings"], [])

    def test_missing_and_case_mismatched_references_are_blocking(self) -> None:
        for name, bad_reference in (
            ("missing", "CF-NOT-FOUND"),
            ("case_mismatch", "cf-b-0"),
        ):
            state = investment_state()
            state["quantitative_model"]["formulas"][0]["input_ids"][0] = bad_reference
            with self.subTest(case=name):
                result = validate_state_cli(state)
                payload = assert_structured_failure(self, result)
                issues = payload["issues"]
                self.assertTrue(
                    any(
                        issue["code"] == "UNKNOWN_REFERENCE"
                        and issue["path"].endswith("input_ids[0]")
                        for issue in issues
                    ),
                    payload,
                )

    def test_incorrect_cash_flow_identity_is_blocking(self) -> None:
        state = investment_state()
        state["quantitative_model"]["cash_flows"][1]["net"] = 149

        result = validate_state_cli(state)
        payload = assert_structured_failure(self, result)
        self.assertTrue(
            any(
                issue["code"] == "ARITHMETIC_MISMATCH"
                and "cash_flows[1].net" in issue["path"]
                for issue in payload["issues"]
            ),
            payload,
        )

    def test_incorrect_scenario_roi_and_npv_outputs_are_blocking(self) -> None:
        for output_id, wrong_value in (
            ("OUT-B-ROI", 0.75),
            ("OUT-D-NPV", 999),
        ):
            state = investment_state()
            output = next(
                item
                for item in state["quantitative_model"]["outputs"]
                if item["id"] == output_id
            )
            output["value"] = wrong_value
            with self.subTest(output=output_id):
                result = validate_state_cli(state)
                payload = assert_structured_failure(self, result)
                self.assertTrue(
                    any(
                        issue["code"] == "ARITHMETIC_MISMATCH"
                        and issue["path"].endswith(".value")
                        for issue in payload["issues"]
                    ),
                    payload,
                )


class AssemblerCliTests(unittest.TestCase):
    def assemble(
        self, directory: str, *arguments: object
    ) -> subprocess.CompletedProcess[str]:
        return run_cli(ASSEMBLER, "--path", directory, *arguments)

    def test_preserves_markdown_rules_and_triple_quoted_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chapter = Path(directory) / "chapter1.md"
            chapter.write_text(
                "---\ntitle: remove only this frontmatter\n---\n"
                "# 中心判断\n第一段\n---\n## 关键证据\n"
                '"""这段三引号正文必须保留"""\n---\n收尾\n',
                encoding="utf-8",
            )
            result = self.assemble(
                directory, "--output", "report.md", "--mode", "brief"
            )
            report = (Path(directory) / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("remove only this frontmatter", report)
        self.assertIn("第一段\n---\n## 关键证据", report)
        self.assertIn('"""这段三引号正文必须保留"""', report)
        self.assertIn("---\n收尾", report)

    def test_quoted_frontmatter_preserves_body_and_rejects_empty(self):
        keys = ('"title"', "'title'", r'"ti\"tle"', "'ti''tle'")
        for key in keys:
            for body in ("# Body\nUseful\n---\nKept\n", " \n"):
                with self.subTest(key=key, body=body), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "chapter1.md").write_text(
                        f"---\n{key}: private-metadata\n---\n{body}", encoding="utf-8"
                    )
                    output = root / "report.md"
                    result = self.assemble(directory, "--output", "report.md", "--mode", "brief")
                    if body.strip():
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        report = output.read_text(encoding="utf-8")
                        self.assertNotIn("private-metadata", report)
                        self.assertIn(body.strip(), report)
                    else:
                        payload = assert_structured_failure(self, result)
                        self.assertEqual(payload["error"]["code"], "empty_chapters")
                        self.assertFalse(output.exists())
                        output.write_bytes(b"original\r\n")
                        result = self.assemble(directory, "--output", "report.md", "--mode", "brief", "--force")
                        payload = assert_structured_failure(self, result)
                        self.assertEqual(payload["error"]["code"], "empty_chapters")
                        self.assertEqual(output.read_bytes(), b"original\r\n")

    def test_cleaned_empty_chapters_fail_without_writing_or_overwriting(self):
        for contents in (("",), (" \n\t",), ("---\ntitle: metadata\n---\n",),
                         ("", "---\ntitle: metadata\n---\n \n")):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for i, content in enumerate(contents, 1):
                    (root / f"chapter{i}.md").write_text(content, encoding="utf-8")
                result = self.assemble(directory, "--output", "nested/report.md", "--mode", "brief")
                payload = assert_structured_failure(self, result)
                self.assertEqual(payload["error"]["code"], "empty_chapters")
                self.assertFalse((root / "nested").exists())
                output = root / "report.md"
                output.write_text("original", encoding="utf-8")
                result = self.assemble(directory, "--output", "report.md", "--mode", "brief", "--force")
                assert_structured_failure(self, result)
                self.assertEqual(output.read_text(encoding="utf-8"), "original")

    def test_mixed_empty_chapters_are_warned_and_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapter1.md").write_text(" \n", encoding="utf-8")
            (root / "chapter2.md").write_text("# Body\nUseful\n---\nKept\n", encoding="utf-8")
            result = self.assemble(directory, "--mode", "brief")
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json_payload(result)
            self.assertEqual(payload["status"], "success_with_warnings")
            self.assertEqual(payload["chapters_merged"], 1)
            self.assertEqual(payload["chapter_order"], ["chapter2.md"])
            self.assertTrue(any("chapter1.md" in w and "skipped" in w for w in payload["warnings"]))
            self.assertIn("Useful\n---\nKept", (root / "final_report.md").read_text(encoding="utf-8"))

    def test_explicit_empty_draft_warns_but_never_claims_formal_maturity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapter1.md").write_text("---\ntitle: metadata\n---\n", encoding="utf-8")
            result = self.assemble(directory, "--mode", "brief", "--allow-empty")
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json_payload(result)
            self.assertEqual(payload["chapters_merged"], 0)
            self.assertEqual(payload["status"], "success_with_warnings")
            for maturity in ("decision_ready", "approved_for_execution"):
                state = brief_state(maturity="decision_ready")
                state["metadata"]["maturity"] = maturity
                blackboard = root / "blackboard.json"
                blackboard.write_text(json.dumps(state), encoding="utf-8")
                result = self.assemble(directory, "--mode", "brief", "--allow-empty",
                                       "--blackboard", blackboard, "--output", "formal.md")
                assert_structured_failure(self, result)
                self.assertFalse((root / "formal.md").exists())

    def test_leading_horizontal_rules_without_yaml_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = "---\nA paragraph, not YAML\n---\n"
            (root / "chapter1.md").write_text(body, encoding="utf-8")
            result = self.assemble(directory, "--mode", "brief")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn(body, (root / "final_report.md").read_text(encoding="utf-8"))

    def test_zero_chapters_is_a_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.assemble(
                directory, "--output", "report.md", "--mode", "brief"
            )

        payload = assert_structured_failure(self, result)
        self.assertEqual(payload["error"]["code"], "no_chapters")

    def test_formal_modes_require_a_blackboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "chapter1.md").write_text(
                "# 正文\n内容\n", encoding="utf-8"
            )
            for mode in ("board-memo", "deep-dive", "investment-case"):
                with self.subTest(mode=mode):
                    result = self.assemble(
                        directory,
                        "--output",
                        f"{mode}.md",
                        "--mode",
                        mode,
                    )
                    payload = assert_structured_failure(self, result)
                    self.assertEqual(payload["error"]["code"], "blackboard_required")

    def test_output_path_cannot_escape_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as parent_directory:
            parent = Path(parent_directory)
            root = parent / "project"
            root.mkdir()
            (root / "chapter1.md").write_text("# 正文\n内容\n", encoding="utf-8")
            result = self.assemble(
                str(root),
                "--output",
                "../escaped-report.md",
                "--mode",
                "brief",
            )
            self.assertFalse((parent / "escaped-report.md").exists())

        payload = assert_structured_failure(self, result)
        self.assertEqual(payload["error"]["code"], "output_outside_project")

    def test_refuses_overwrite_unless_force_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chapter = Path(directory) / "chapter1.md"
            chapter.write_text("# 第一版\n旧正文\n", encoding="utf-8")
            first = self.assemble(directory, "--output", "report.md", "--mode", "brief")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            output = Path(directory) / "report.md"
            original = output.read_text(encoding="utf-8")

            chapter.write_text("# 第二版\n新正文\n", encoding="utf-8")
            refused = self.assemble(
                directory, "--output", "report.md", "--mode", "brief"
            )
            self.assertEqual(output.read_text(encoding="utf-8"), original)
            refusal = assert_structured_failure(self, refused)
            self.assertEqual(refusal["error"]["code"], "output_exists")

            replaced = self.assemble(
                directory,
                "--output",
                "report.md",
                "--mode",
                "brief",
                "--force",
            )
            updated = output.read_text(encoding="utf-8")

        self.assertEqual(replaced.returncode, 0, replaced.stdout + replaced.stderr)
        self.assertIn("新正文", updated)
        self.assertNotEqual(updated, original)

    def test_duplicate_numbers_have_deterministic_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapters").mkdir()
            files = {
                "chapter10.md": "# 十\n",
                "chapter2.md": "# 二B\n",
                "chapter02-a.md": "# 二A\n",
                "chapters/2-c.md": "# 二C\n",
                "chapters/chapter1.md": "# 一\n",
            }
            for relative_path, content in files.items():
                (root / relative_path).write_text(content, encoding="utf-8")
            result = self.assemble(
                directory, "--output", "report.md", "--mode", "brief"
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json_payload(result)
        self.assertEqual(
            payload["chapter_order"],
            [
                "chapters/chapter1.md",
                "chapter02-a.md",
                "chapter2.md",
                "chapters/2-c.md",
                "chapter10.md",
            ],
        )
        self.assertEqual(payload["duplicate_chapter_numbers"][0]["number"], 2)

    def test_utf8_bom_and_crlf_frontmatter_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chapter = Path(directory) / "chapter1.md"
            chapter.write_bytes(
                (
                    "\ufeff---\r\ntitle: remove me\r\n---\r\n# 正文\r\n保留内容\r\n"
                ).encode("utf-8")
            )
            result = self.assemble(
                directory, "--output", "report.md", "--mode", "brief"
            )
            report = (Path(directory) / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("\ufeff", report)
        self.assertNotIn("title: remove me", report)
        self.assertIn("# 正文", report)
        self.assertIn("保留内容", report)

    def test_blackboard_and_assembler_modes_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapter1.md").write_text("# 正文\n内容\n", encoding="utf-8")
            blackboard = root / "blackboard.json"
            blackboard.write_text(
                json.dumps(brief_state(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = self.assemble(
                directory,
                "--output",
                "report.md",
                "--mode",
                "deep-dive",
                "--blackboard",
                blackboard,
            )

        payload = assert_structured_failure(self, result)
        self.assertEqual(payload["error"]["code"], "blackboard_mode_mismatch")

    def test_report_header_uses_blackboard_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapter1.md").write_text("# 正文\n内容\n", encoding="utf-8")
            blackboard = root / "blackboard.json"
            blackboard.write_text(
                json.dumps(brief_state(maturity="decision_ready"), ensure_ascii=False),
                encoding="utf-8",
            )
            result = self.assemble(
                directory,
                "--output",
                "report.md",
                "--mode",
                "brief",
                "--blackboard",
                blackboard,
            )
            report = (root / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Maturity: decision_ready", report)


class StrategyGateCliTests(unittest.TestCase):
    def test_brief_without_blackboard_is_explicitly_textual_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chapter1.md").write_text("# 建议\n仅供讨论。\n", encoding="utf-8")
            assembled = run_cli(ASSEMBLER, "--path", root, "--mode", "brief")
            self.assertEqual(assembled.returncode, 0, assembled.stdout)
            report = root / "final_report.md"
            args = ("--path", report, "--mode", "brief")
            self.assertNotEqual(run_cli(GATE, *args).returncode, 0)
            result = run_cli(GATE, *args, "--textual-only")
            self.assertEqual(result.returncode, 0, result.stdout)
            payload = json_payload(result)
            self.assertEqual(payload["scope"], "textual_only")
            self.assertIsNone(payload["blackboard_ready"])
            self.assertIn("financial", payload["unchecked"])
            self.assertNotEqual(
                run_cli(GATE, *args, "--textual-only", "--strict").returncode, 0
            )
            for mode in ("board-memo", "deep-dive", "investment-case"):
                with self.subTest(mode=mode):
                    self.assertNotEqual(
                        run_cli(
                            GATE, "--path", report, "--mode", mode, "--textual-only"
                        ).returncode,
                        0,
                    )
            for text in (
                "Maturity: decision_ready",
                "Maturity: approved_for_execution",
                "无成熟度",
                "Maturity: working_draft\nMaturity: decision_ready",
            ):
                with self.subTest(text=text):
                    report.write_text(text, encoding="utf-8")
                    self.assertNotEqual(
                        run_cli(GATE, *args, "--textual-only").returncode, 0
                    )

    def write_state(self, root: Path, state: dict) -> Path:
        path = root / "blackboard.json"
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return path

    def run_gate(
        self,
        root: Path,
        report_text: str,
        state: dict,
        *,
        mode: str = "brief",
        strict: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        report = root / "report.md"
        report.write_text(report_text, encoding="utf-8")
        blackboard = self.write_state(root, state)
        arguments: list[object] = [
            "--path",
            report,
            "--mode",
            mode,
            "--blackboard",
            blackboard,
        ]
        if strict:
            arguments.append("--strict")
        return run_cli(GATE, *arguments)

    def test_empty_report_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(Path(directory), " \n\t", brief_state())

        payload = assert_structured_failure(self, result)
        self.assertTrue(
            any("report text is empty" in error for error in payload["errors"])
        )

    def test_real_placeholders_are_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(
                Path(directory),
                "核心判断：分阶段推进。建议先试点。风险可控。\n"
                "[待填充]\n{{roi}}\nTBD\n",
                brief_state(),
            )

        payload = assert_structured_failure(self, result)
        placeholder_error = next(
            error for error in payload["errors"] if "unresolved placeholders" in error
        )
        self.assertIn("[待填充]", placeholder_error)
        self.assertIn("{{roi}}", placeholder_error)
        self.assertIn("TBD", placeholder_error)

    def test_normal_amount_and_budget_heading_is_not_a_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(
                Path(directory),
                "# [金额与预算]\n核心判断：分阶段推进。建议先试点并保留回退。风险需要监测。\n",
                brief_state(),
            )

        payload = json_payload(result)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(
            any("unresolved placeholders" in error for error in payload["errors"])
        )

    def test_strict_mode_blocks_quality_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(
                Path(directory),
                "核心判断：分阶段推进。建议先试点。行动可回退。风险需要监测。\n",
                brief_state(),
                strict=True,
            )

        payload = assert_structured_failure(self, result)
        self.assertEqual(payload["errors"], [])
        self.assertTrue(payload["warnings"])
        self.assertTrue(payload["strict"])
        self.assertTrue(payload["blocking"])

    def test_decision_ready_delivery_requires_strict_gate(self) -> None:
        report = (
            "Maturity: decision_ready\n"
            "核心判断：分阶段推进。建议先试点。行动可回退。风险需要监测。\n"
        )
        state = brief_state(maturity="decision_ready")
        with tempfile.TemporaryDirectory() as first_directory:
            non_strict = self.run_gate(Path(first_directory), report, state)
        non_strict_payload = assert_structured_failure(self, non_strict)
        self.assertTrue(
            any("requires --strict" in error for error in non_strict_payload["errors"])
        )

        with tempfile.TemporaryDirectory() as second_directory:
            strict = self.run_gate(Path(second_directory), report, state, strict=True)
        strict_payload = json_payload(strict)
        self.assertEqual(strict.returncode, 0, strict.stdout + strict.stderr)
        self.assertEqual(strict_payload["status"], "pass")
        self.assertTrue(strict_payload["blackboard_ready"])

    def test_invalid_blackboard_json_is_a_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.md"
            report.write_text("有效正文", encoding="utf-8")
            blackboard = root / "blackboard.json"
            blackboard.write_text('{"metadata": ', encoding="utf-8")
            result = run_cli(
                GATE,
                "--path",
                report,
                "--mode",
                "brief",
                "--blackboard",
                blackboard,
            )

        payload = assert_structured_failure(self, result)
        self.assertTrue(any("blackboard JSON" in error for error in payload["errors"]))

    def test_invalid_blackboard_schema_is_structured_and_does_not_crash(self) -> None:
        invalid = brief_state()
        invalid["logic_mesh"] = "broken"
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(
                Path(directory),
                "核心判断：分阶段推进。建议先试点。风险需要监测。",
                invalid,
            )

        payload = assert_structured_failure(self, result)
        self.assertTrue(
            any("logic_mesh" in error for error in payload["errors"]), payload
        )

    def test_report_and_blackboard_modes_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_gate(
                Path(directory),
                "核心判断：分阶段推进。建议先试点。风险需要监测。",
                brief_state(),
                mode="deep-dive",
            )

        payload = assert_structured_failure(self, result)
        self.assertTrue(any("mode mismatch" in error for error in payload["errors"]))

    def test_high_risk_topics_require_complete_compliance_context(self) -> None:
        high_risk_report = (
            "核心判断：分阶段推进患者健康数据跨境处理。"
            "建议先试点。行动可回退。风险需要监测。"
        )
        incomplete = brief_state()
        incomplete["compliance_context"].update(
            {
                "applicability": "required",
                "rationale": "涉及患者健康数据跨境处理",
                "jurisdiction": "",
                "as_of": "",
                "intended_use": "",
                "data_types": [],
                "affected_users": [],
            }
        )
        complete = brief_state(compliance_required=True)

        with tempfile.TemporaryDirectory() as first_directory:
            missing_result = self.run_gate(
                Path(first_directory), high_risk_report, incomplete, strict=True
            )
        missing_payload = assert_structured_failure(self, missing_result)
        self.assertTrue(
            any(
                "compliance context is incomplete" in warning
                for warning in missing_payload["warnings"]
            )
        )

        with tempfile.TemporaryDirectory() as second_directory:
            complete_result = self.run_gate(
                Path(second_directory), high_risk_report, complete
            )
        complete_payload = json_payload(complete_result)
        self.assertEqual(
            complete_result.returncode,
            0,
            complete_result.stdout + complete_result.stderr,
        )
        self.assertFalse(
            any(
                "compliance context is incomplete" in warning
                for warning in complete_payload["warnings"]
            )
        )
        self.assertFalse(
            any(
                "professional review" in warning
                for warning in complete_payload["warnings"]
            )
        )
        self.assertIn(
            "personal_and_health_data", complete_payload["compliance_review_topics"]
        )
        self.assertIn("cross_border_data", complete_payload["compliance_review_topics"])

    def test_quantitative_table_warning_is_aggregated_and_honors_provenance(
        self,
    ) -> None:
        table = (
            "核心判断：分阶段推进。建议先试点。行动可回退。风险需要监测。\n\n"
            "| 项目 | 金额 |\n"
            "| --- | ---: |\n"
            "| 软件 | 100万元 |\n"
            "| 实施 | 50万元 |\n"
            "| 运维 | 20万元 |\n"
        )
        with tempfile.TemporaryDirectory() as first_directory:
            unsupported = self.run_gate(Path(first_directory), table, brief_state())
        unsupported_payload = json_payload(unsupported)
        table_warnings = [
            warning
            for warning in unsupported_payload["warnings"]
            if "table starting line" in warning
        ]
        self.assertEqual(len(table_warnings), 1, unsupported_payload)

        sourced_variants = (
            table.replace(
                "| 项目 | 金额 |",
                "| 项目 | 金额 | 来源 |",
            )
            .replace(
                "| --- | ---: |",
                "| --- | ---: | --- |",
            )
            .replace("| 软件 | 100万元 |", "| 软件 | 100万元 | 院方预算表 |")
            .replace("| 实施 | 50万元 |", "| 实施 | 50万元 | 院方预算表 |")
            .replace("| 运维 | 20万元 |", "| 运维 | 20万元 | 院方预算表 |"),
            table + "来源：院方预算表；截至：2026年1月。\n",
        )
        for index, sourced in enumerate(sourced_variants):
            with (
                self.subTest(provenance_variant=index),
                tempfile.TemporaryDirectory() as directory,
            ):
                result = self.run_gate(Path(directory), sourced, brief_state())
                payload = json_payload(result)
                self.assertFalse(
                    any(
                        "table starting line" in warning
                        for warning in payload["warnings"]
                    ),
                    payload,
                )

    def test_terminology_first_use_and_restricted_words(self) -> None:
        cases = (
            (
                "bare_abbreviation",
                "核心判断：HIS应分阶段推进。建议先试点。行动可回退。风险需要监测。",
                "abbreviation 'HIS'",
                True,
            ),
            (
                "defined_abbreviation",
                "核心判断：医院信息系统（HIS）应分阶段推进。建议先试点。行动可回退。风险需要监测。",
                "abbreviation 'HIS'",
                False,
            ),
            (
                "restricted_word",
                "核心判断：这不是卖软件。建议先试点。行动可回退。风险需要监测。",
                "restricted term '卖软件'",
                True,
            ),
        )
        for name, report, warning_fragment, should_warn in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                result = self.run_gate(Path(directory), report, brief_state())
                payload = json_payload(result)
                matching = [
                    warning
                    for warning in payload["warnings"]
                    if warning_fragment in warning
                ]
                self.assertEqual(bool(matching), should_warn, payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
