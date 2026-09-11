"""Synthetic counterexamples and controls for DSP-001 through DSP-010."""

import errno
import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from test_strategy_toolchain import (
    BLACKBOARD,
    GATE,
    SKILL_ROOT,
    brief_state,
    investment_state,
    json_payload,
    load_blackboard_module,
    run_cli,
)

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
gate = importlib.import_module("strategy_gate")

REPORT = "Maturity: decision_ready\n核心判断：分阶段推进。建议先试点。行动可回退。风险需要监测。\n"


def evaluate(state, text=REPORT, **kwargs):
    return gate.evaluate(
        text,
        state["metadata"]["mode"],
        state,
        strict=True,
        medical_terms={},
        compliance_rules={},
        **kwargs,
    )


def embedded_state():
    state = investment_state()
    model = state["quantitative_model"]
    # Keep formula inputs at top level and use separate IDs for embedded rows.
    for scenario in model["scenarios"]:
        scenario["cash_flows"] = [
            dict(row, id="EM-" + row["id"])
            for row in model["cash_flows"]
            if row["scenario_id"] == scenario["id"]
        ]
        del scenario["cash_flow_ids"]
    return state


class StrategyAuditRegressions(unittest.TestCase):
    def setUp(self):
        self.bb = load_blackboard_module()

    def assert_issue(self, state, code, fragment=""):
        result = self.bb.validate_state(state)
        self.assertFalse(result["ready"], result)
        self.assertTrue(
            any(i["code"] == code and fragment in i["path"] for i in result["issues"]),
            result,
        )
        return result

    def test_dsp001_financial_validation_is_mode_independent(self):
        for mode in ("brief", "board-memo", "deep-dive", "investment-case"):
            for applicable in (True, False):
                with self.subTest(mode=mode, applicable=applicable):
                    state = investment_state()
                    state["metadata"]["mode"] = mode
                    state["quantitative_model"]["applicable"] = applicable
                    state["quantitative_model"]["cash_flows"][0]["net"] = 999
                    self.assert_issue(state, "ARITHMETIC_MISMATCH", "net")

    def test_dsp001_nonfinancial_memo_and_valid_model(self):
        state = investment_state()
        state["metadata"]["mode"] = "board-memo"
        self.assertTrue(self.bb.validate_state(state)["ready"])
        state["quantitative_model"] = brief_state()["quantitative_model"]
        self.assertTrue(self.bb.validate_state(state)["ready"])

    def test_dsp002_shared_cash_flow_contract(self):
        for embedded in (False, True):
            for defect, code in (
                ("missing_period", "REQUIRED"),
                ("duplicate_period", "DUPLICATE_PERIOD"),
                ("duplicate_id", "DUPLICATE_ID"),
                ("missing_id", "REQUIRED"),
                ("wrong_scenario", "REFERENCE_MISMATCH"),
                ("nonnumeric", "INVALID_NUMBER"),
            ):
                with self.subTest(embedded=embedded, defect=defect):
                    state = embedded_state() if embedded else investment_state()
                    model = state["quantitative_model"]
                    rows = (
                        model["scenarios"][0]["cash_flows"]
                        if embedded
                        else model["cash_flows"]
                    )
                    if defect == "missing_period":
                        del rows[0]["period"]
                    elif defect == "duplicate_period":
                        rows[1]["period"] = rows[0]["period"]
                    elif defect == "duplicate_id":
                        rows[1]["id"] = rows[0]["id"]
                    elif defect == "missing_id":
                        del rows[0]["id"]
                    elif defect == "wrong_scenario":
                        rows[0]["scenario_id"] = "SCN-DOWN"
                    else:
                        rows[0]["cost"] = "NaN"
                    self.assert_issue(state, code)

    def test_dsp002_valid_embedded_and_top_level_metrics_agree(self):
        for state in (investment_state(), embedded_state()):
            self.assertTrue(self.bb.validate_state(state)["ready"])
        state = embedded_state()
        for scenario in state["quantitative_model"]["scenarios"]:
            for row in scenario["cash_flows"]:
                del row["scenario_id"]  # Inherit the enclosing scenario.
        self.assertTrue(self.bb.validate_state(state)["ready"])

    def test_dsp003_currency_inheritance_and_explicit_mismatch(self):
        for embedded in (False, True):
            for field in ("unit", "currency"):
                for currency in (None, "CNY", "USD", ""):
                    with self.subTest(
                        embedded=embedded, field=field, currency=currency
                    ):
                        state = embedded_state() if embedded else investment_state()
                        model = state["quantitative_model"]
                        row = (
                            model["scenarios"][0]["cash_flows"][0]
                            if embedded
                            else model["cash_flows"][0]
                        )
                        if currency is not None:
                            row[field] = currency
                        if currency in ("USD", ""):
                            self.assert_issue(state, "UNIT")
                        else:
                            self.assertTrue(self.bb.validate_state(state)["ready"])

    def test_dsp004_item_values_reconcile_with_formula(self):
        for collection, field, formula, value in (
            ("benefit_items", "value", "F-B-BEN", 150),
            ("benefit_items", "amount", "F-B-BEN", 150),
            ("cost_items", "amount", "F-B-TCO", 100),
        ):
            for declared in (None, value, 999):
                with self.subTest(
                    collection=collection, field=field, declared=declared
                ):
                    state = investment_state()
                    item = state["quantitative_model"][collection][0]
                    item.pop("value", None)
                    item.pop("amount", None)
                    item["formula"] = formula
                    if declared is not None:
                        item[field] = declared
                    if declared == 999:
                        self.assert_issue(state, "ARITHMETIC_MISMATCH", collection)
                    else:
                        self.assertTrue(self.bb.validate_state(state)["ready"])

    def test_dsp005_report_ids_and_unchecked_prose(self):
        state = investment_state()
        for reference in ("EV-FIN-999", "AS-MISSING", "OUT-MISSING"):
            result = evaluate(state, REPORT + "依据 " + reference)
            self.assertTrue(
                any("unknown report reference" in e for e in result["errors"]), result
            )
        result = evaluate(state, REPORT + "依据 EV-OPS-001、AS-R，ROI 999%。")
        self.assertIn("prose_numbers", result["unchecked"])
        self.assertEqual(result["errors"], [])
        self.assertIn("source_support", result["unchecked"])

    def test_dsp005_explicit_output_binding(self):
        state = investment_state()
        for value, metric, unit, passed in (
            (0.5, "roi", "ratio", True),
            (50, "roi", "%", True),
            (999, "roi", "%", False),
            (0.5, "npv", "ratio", False),
            (0.5, "roi", "CNY", False),
        ):
            with self.subTest(value=value, metric=metric, unit=unit):
                text = (
                    REPORT
                    + f"[[output:OUT-B-ROI metric={metric} value={value} unit={unit}]]"
                )
                result = evaluate(state, text)
                self.assertEqual(not result["blocking"], passed, result)
                if passed:
                    self.assertEqual(len(result["verified_output_references"]), 1)
        result = evaluate(state, REPORT + "[[output:OUT-B-ROI value=999%]]")
        self.assertTrue(result["errors"], result)

    def test_dsp005_binding_is_not_verification_when_state_invalid(self):
        state = investment_state()
        state["quantitative_model"]["cash_flows"][0]["net"] = 999
        result = evaluate(
            state, REPORT + "[[output:OUT-B-ROI metric=roi value=0.5 unit=ratio]]"
        )
        self.assertTrue(result["blocking"])
        self.assertEqual(result["verified_output_references"], [])

    def test_dsp005_binding_units_scenarios_and_nonfinite_values(self):
        state = investment_state()
        output = next(
            item
            for item in state["quantitative_model"]["outputs"]
            if item["id"] == "OUT-B-ROI"
        )
        output.update(value=50, unit="percent")
        self.assertTrue(self.bb.validate_state(state)["ready"])
        for value, unit, valid in (
            ("0.5", "ratio", True),
            ("50", "%", True),
            ("NaN", "%", False),
            ("Infinity", "%", False),
            ("-999", "%", False),
            ("50", "USD", False),
        ):
            with self.subTest(value=value, unit=unit):
                result = evaluate(
                    state,
                    REPORT
                    + f"[[output:OUT-B-ROI metric=roi value={value} unit={unit}]]",
                )
                self.assertEqual(not result["blocking"], valid, result)
                if valid:
                    self.assertEqual(
                        result["verified_output_references"][0]["scenario_id"],
                        output["scenario_id"],
                    )
        for token in (
            "[[output:OUT-MISSING metric=roi value=50 unit=%]]",
            "[[output:OUT-B-ROI metric=roi value=50 unit=%]",
            "[[output:OUT-B-ROI value=50 metric=roi unit=%]]",
        ):
            self.assertTrue(evaluate(state, REPORT + token)["errors"], token)

    def test_dsp005_documented_binding_and_examples(self):
        text = (SKILL_ROOT / "references" / "editor.md").read_text(encoding="utf-8")
        match = re.search(r"\[\[output:OUT-B-ROI[^\n]*?\]\]", text)
        assert match is not None
        token = match.group(0)
        result = evaluate(investment_state(), REPORT + token)
        self.assertFalse(result["blocking"], result)
        self.assertEqual(len(result["verified_output_references"]), 1)
        state = investment_state()
        for example in (
            "```text\nEV-MISSING AS-MISSING OUT-MISSING\n```",
            "> EV-MISSING",
            "    AS-MISSING",
        ):
            self.assertEqual(evaluate(state, REPORT + example)["errors"], [])
        result = evaluate(state, REPORT + "依据 `EV-OPS-001`、`AS-R`。")
        self.assertEqual(result["errors"], [])
        result = evaluate(state, REPORT + "依据 `EV-ops-001`。")
        self.assertTrue(any("unknown report reference" in e for e in result["errors"]))

    def test_dsp006_supersession_retires_old_active_evidence(self):
        state = brief_state(maturity="decision_ready")
        original = deepcopy(state["evidence"]["records"][0])
        correction = dict(
            original,
            evidence_id="EV-OPS-002",
            supersedes="EV-OPS-001",
            status="disputed",
            limitations="Synthetic conflicting source",
        )
        state["evidence"]["records"].append(correction)
        self.assert_issue(state, "MISSING_EVIDENCE")
        self.assertEqual(state["evidence"]["records"][0], original)
        correction["status"] = "active"
        self.assertTrue(self.bb.validate_state(state)["ready"])
        self.assertEqual(
            self.bb.effective_evidence_ids(state["evidence"]["records"]), {"EV-OPS-002"}
        )
        correction["status"] = "superseded"  # Append-only withdrawal notice.
        self.assert_issue(state, "MISSING_EVIDENCE")

    def test_dsp006_rejects_dangling_self_and_cycle(self):
        for defect in ("dangling", "self", "cycle", "type"):
            with self.subTest(defect=defect):
                state = brief_state(maturity="decision_ready")
                first = state["evidence"]["records"][0]
                first["supersedes"] = {
                    "dangling": "EV-OPS-999",
                    "self": "EV-OPS-001",
                    "cycle": "EV-OPS-002",
                    "type": ["EV-OPS-001"],
                }[defect]
                if defect == "cycle":
                    state["evidence"]["records"].append(
                        dict(first, evidence_id="EV-OPS-002", supersedes="EV-OPS-001")
                    )
                self.assert_issue(state, "SUPERSESSION")

    def test_dsp006_append_only_cli_and_invalid_chain_atomicity(self):
        state = brief_state(maturity="decision_ready")
        old = deepcopy(state["evidence"]["records"][0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "tmp" / "strategy_blackboard.json"
            target.parent.mkdir()
            target.write_text(json.dumps(state), encoding="utf-8")
            correction = dict(
                old,
                evidence_id="EV-OPS-002",
                supersedes="EV-OPS-001",
                claim="Corrected synthetic claim",
            )
            args = (
                "--workspace-root",
                root,
                "update",
                "--section",
                "evidence",
                "--key",
                "records",
                "--action",
                "append",
                "--value",
                "-",
            )
            result = run_cli(BLACKBOARD, *args, input_text=json.dumps(correction))
            self.assertEqual(result.returncode, 0, result.stdout)
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["evidence"]["records"][0], old)
            before = target.read_bytes()
            correction["evidence_id"] = "EV-OPS-003"
            correction["supersedes"] = "EV-OPS-999"
            result = run_cli(BLACKBOARD, *args, input_text=json.dumps(correction))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), before)
            result = run_cli(
                BLACKBOARD, *args, input_text=json.dumps(dict(old, claim="Overwrite"))
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), before)

    def test_dsp007_blocked_compliance_is_never_ready_but_draft_saves(self):
        state = brief_state(compliance_required=True, maturity="decision_ready")
        state["compliance_context"].update(
            status="blocked", review_required=False, escalations=[]
        )
        self.assert_issue(state, "COMPLIANCE_BLOCKED")
        state["metadata"]["maturity"] = "working_draft"
        result = self.assert_issue(state, "COMPLIANCE_BLOCKED")
        self.assertEqual(result["errors"], [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "tmp" / "strategy_blackboard.json"
            target.parent.mkdir()
            target.write_text(json.dumps(brief_state()), encoding="utf-8")
            result = run_cli(
                BLACKBOARD,
                "--workspace-root",
                root,
                "update",
                "--section",
                "compliance_context",
                "--value",
                "-",
                input_text=json.dumps(state["compliance_context"]),
            )
            self.assertEqual(result.returncode, 0, result.stdout)
        state = investment_state()
        state["portfolio"]["gate_results"][1]["result"] = "fail"
        self.assertTrue(self.bb.validate_state(state)["ready"])

    def test_dsp008_all_actual_maturity_declarations(self):
        state = brief_state(maturity="decision_ready")
        for suffix in (
            "Maturity: approved_for_execution",
            "成熟度：review_ready",
            "Maturity: imaginary",
        ):
            result = evaluate(state, REPORT + suffix)
            self.assertTrue(result["blocking"], result)
            self.assertTrue(
                any("maturity" in error for error in result["errors"]), result
            )
        result = evaluate(state, REPORT + "成熟度：decision_ready")
        self.assertFalse(result["blocking"], result)

    def test_dsp008_examples_are_not_approval_declarations(self):
        state = brief_state(maturity="decision_ready")
        for example in (
            "```text\nMaturity: approved_for_execution\n```",
            "~~~text\nMaturity: approved_for_execution\n~~~",
            "> Maturity: approved_for_execution",
            "    Maturity: approved_for_execution",
        ):
            with self.subTest(example=example):
                result = evaluate(state, REPORT + example)
                self.assertFalse(result["blocking"], result)
        result = gate.evaluate(
            "Maturity: review_ready\n```\nMaturity: approved_for_execution\n```",
            "brief",
            {},
            textual_only=True,
            medical_terms={},
            compliance_rules={},
        )
        self.assertFalse(result["blocking"], result)

    def test_dsp008_metadata_tables_and_textual_only_consistency(self):
        state = brief_state(maturity="decision_ready")
        for declaration in (
            'maturity: "decision_ready"',
            "**成熟度**：`decision_ready`",
            "| Maturity | decision_ready |",
        ):
            result = evaluate(state, REPORT + declaration)
            self.assertFalse(result["blocking"], result)
        for declaration in (
            'maturity: "approved_for_execution"',
            "| Maturity | approved_for_execution |",
            "Maturity:",
            "Maturity: decision_ready_",
        ):
            result = evaluate(state, REPORT + declaration)
            self.assertTrue(result["blocking"], result)
        for suffix in (
            "Maturity: working_draft",
            "Maturity: approved_for_execution",
            "Maturity: imaginary",
            "Maturity:",
        ):
            result = gate.evaluate(
                "Maturity: review_ready\n" + suffix,
                "brief",
                {},
                textual_only=True,
                medical_terms={},
                compliance_rules={},
            )
            self.assertTrue(result["blocking"], result)
        result = evaluate(
            state, REPORT + "````text\n```\nMaturity: approved_for_execution\n````"
        )
        self.assertFalse(result["blocking"], result)

    def test_dsp009_evidence_package_example_is_complete_and_merges(self):
        text = (SKILL_ROOT / "agents" / "hit-commercial-analyst.md").read_text(
            encoding="utf-8"
        )
        match = re.search(r"```json\s*(.*?)```", text, re.S)
        assert match is not None
        package = json.loads(match.group(1))
        record = package["evidence"][0]
        self.assertTrue(record.keys() >= self.bb.EVIDENCE_FIELDS)
        self.assertIsNone(record["supersedes"])
        for key, value in record.items():
            if value == "":
                record[key] = "Synthetic source"
        state = brief_state(maturity="decision_ready")
        state["evidence"]["records"].append(record)
        self.assertTrue(self.bb.validate_state(state)["ready"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "tmp" / "strategy_blackboard.json"
            target.parent.mkdir()
            target.write_text(
                json.dumps(brief_state(maturity="decision_ready")), encoding="utf-8"
            )
            result = run_cli(
                BLACKBOARD,
                "--workspace-root",
                root,
                "update",
                "--section",
                "evidence",
                "--key",
                "records",
                "--action",
                "append",
                "--value",
                "-",
                input_text=json.dumps(record),
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["evidence"]["records"][-1], record)
        del record["supersedes"]
        self.assert_issue(state, "REQUIRED")

    def test_dsp010_editorial_advice_does_not_block_strict(self):
        state = brief_state(maturity="decision_ready")
        result = gate.evaluate(
            REPORT + "原文引用：卖软件。",
            "brief",
            state,
            strict=True,
            medical_terms={"restricted_words": {"卖软件": "技术服务"}},
            compliance_rules={},
        )
        self.assertFalse(result["blocking"], result)
        self.assertTrue(result["advisories"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["blocking_warnings"], [])
        for text in (REPORT + "[待填写]", REPORT + "ROI 50%"):
            self.assertTrue(evaluate(state, text)["blocking"])
        state = brief_state(compliance_required=True, maturity="decision_ready")
        state["compliance_context"]["escalations"][0]["status"] = "pending"
        self.assertTrue(evaluate(state)["blocking"])

    def test_review_nested_list_declarations_are_not_indented_code(self):
        state = brief_state(maturity="decision_ready")
        for container in (
            "- 决策\n    - ",
            "1. 决策\n    1. ",
            "- 决策\n    ",
            "- 决策\n\n    - ",
            "- 决策\n    - 子项\n        - ",
            "- 决策\n\t- ",
        ):
            for declaration, error in (
                ("Maturity: approved_for_execution", "maturity mismatch"),
                ("EV-MISSING", "unknown report reference"),
            ):
                with self.subTest(container=container, declaration=declaration):
                    result = evaluate(state, REPORT + "\n" + container + declaration)
                    self.assertTrue(any(error in e for e in result["errors"]), result)
            result = evaluate(
                state, REPORT + "\n" + container + "Maturity: decision_ready"
            )
            self.assertFalse(result["blocking"], result)
        result = evaluate(state, REPORT + "\n1. Maturity: approved_for_execution")
        self.assertTrue(any("maturity mismatch" in e for e in result["errors"]), result)

    def test_review_list_code_fences_quotes_and_dedent_controls(self):
        state = brief_state(maturity="decision_ready")
        for example in (
            "    Maturity: approved_for_execution\n    EV-MISSING",
            "- 示例\n\n      Maturity: approved_for_execution\n      EV-MISSING",
            "-     Maturity: approved_for_execution\n      EV-MISSING",
            "1.     Maturity: approved_for_execution\n       EV-MISSING",
            "1. 示例\n\n       Maturity: approved_for_execution\n       EV-MISSING",
            "- 示例\n    ```text\n    Maturity: approved_for_execution\n    EV-MISSING\n    ```",
            "- ```text\n  Maturity: approved_for_execution\n  EV-MISSING\n  ```",
            "- 示例\n    > Maturity: approved_for_execution\n    > EV-MISSING",
            "- 示例\n    - 子项\n\n          Maturity: approved_for_execution\n          EV-MISSING",
            "- 示例\n    - 子项\n\n结束。\n\n    Maturity: approved_for_execution\n    EV-MISSING",
        ):
            with self.subTest(example=example):
                result = evaluate(state, REPORT + "\n" + example)
                self.assertFalse(result["blocking"], result)

    def test_final_r1_list_fence_owner_exit_checks_body(self):
        state = investment_state()
        for prefix, body_indent in (
            ("- ```text\n  示例内容\n\n", ""),
            ("1. ~~~text\n   示例内容\n\n", ""),
            ("- 父项\n  - ```text\n    示例内容\n\n", "  "),
            ("- ```text\n  示例内容\n\n- 正式结论\n", "  "),
        ):
            for declaration, error in (
                ("Maturity: approved_for_execution", "maturity mismatch"),
                ("EV-MISSING", "unknown report reference"),
                (
                    "[[output:OUT-B-ROI metric=roi value=999 unit=%]]",
                    "value mismatch with validated output",
                ),
            ):
                with self.subTest(prefix=prefix, declaration=declaration):
                    text = REPORT + prefix + body_indent + "# 正式结论\n"
                    result = evaluate(state, text + body_indent + declaration)
                    self.assertTrue(result["blocking"], result)
                    self.assertTrue(any(error in e for e in result["errors"]), result)
            result = evaluate(
                state,
                REPORT
                + prefix
                + body_indent
                + "Maturity: decision_ready\n"
                + body_indent
                + "EV-OPS-001\n"
                + body_indent
                + "[[output:OUT-B-ROI metric=roi value=50 unit=%]]",
            )
            self.assertFalse(result["blocking"], result)
            self.assertEqual(len(result["verified_output_references"]), 1)

    def test_final_r1_unclosed_root_and_list_fence_controls(self):
        bad = (
            "Maturity: approved_for_execution\nEV-MISSING\n"
            "[[output:OUT-B-ROI metric=roi value=999 unit=%]]"
        )
        for example in (
            "```text\n- 示例\n\n# 标题\n" + bad,
            "~~~text\n    示例\n\n" + bad,
            "- ```text\n\n" + "\n".join("  " + line for line in bad.splitlines()),
            "- 父项\n  - ```text\n\n"
            + "\n".join("    " + line for line in bad.splitlines()),
        ):
            with self.subTest(example=example):
                result = evaluate(investment_state(), REPORT + example)
                self.assertFalse(result["blocking"], result)
                self.assertEqual(result["verified_output_references"], [])

    def test_final_r2_whitespace_supersession_status_and_immutable_records(self):
        for status in ("active", "disputed", "superseded"):
            for target in ("EV-OPS-001", " EV-OPS-001 "):
                with self.subTest(status=status, target=target):
                    state = brief_state(maturity="decision_ready")
                    first = state["evidence"]["records"][0]
                    first["evidence_id"] = " EV-OPS-001 "
                    old = deepcopy(state)
                    first_bytes = json.dumps(first, ensure_ascii=False).encode("utf-8")
                    state["evidence"]["records"].append(
                        dict(
                            first,
                            evidence_id=" EV-OPS-002 ",
                            supersedes=target,
                            status=status,
                            limitations="Synthetic dispute or withdrawal",
                        )
                    )
                    records_bytes = json.dumps(state["evidence"]["records"]).encode()
                    result = self.bb.validate_state(state)
                    self.assertEqual(result["errors"], [], result)
                    self.assertEqual(result["ready"], status == "active", result)
                    self.assertEqual(
                        self.bb.effective_evidence_ids(state["evidence"]["records"]),
                        {"EV-OPS-002"} if status == "active" else set(),
                    )
                    if status != "active":
                        self.assertTrue(
                            any(
                                i["code"] == "MISSING_EVIDENCE"
                                for i in result["issues"]
                            )
                        )
                    self.bb._assert_evidence_immutable(old, state)
                    self.assertEqual(
                        json.dumps(first, ensure_ascii=False).encode("utf-8"),
                        first_bytes,
                    )
                    self.assertEqual(
                        json.dumps(state["evidence"]["records"]).encode(), records_bytes
                    )
                    changed = deepcopy(state)
                    changed["evidence"]["records"][0]["evidence_id"] = "EV-OPS-001"
                    with self.assertRaises(self.bb.BlackboardError):
                        self.bb._assert_evidence_immutable(old, changed)

    def test_final_r2_normalized_graph_rejects_self_cycle_and_duplicate(self):
        for defect in ("self", "cycle", "duplicate"):
            with self.subTest(defect=defect):
                state = brief_state(maturity="decision_ready")
                first = state["evidence"]["records"][0]
                first["evidence_id"] = " EV-OPS-001 "
                if defect == "self":
                    first["supersedes"] = "EV-OPS-001"
                elif defect == "cycle":
                    first["supersedes"] = " EV-OPS-002 "
                    state["evidence"]["records"].append(
                        dict(first, evidence_id="EV-OPS-002", supersedes="EV-OPS-001")
                    )
                else:
                    state["evidence"]["records"].append(
                        dict(first, evidence_id="EV-OPS-001")
                    )
                self.assert_issue(
                    state, "DUPLICATE_ID" if defect == "duplicate" else "SUPERSESSION"
                )

    def test_final_r2_normalized_ids_reach_financial_and_report_consumers(self):
        state = investment_state()
        first = state["evidence"]["records"][0]
        first["evidence_id"] = " EV-OPS-001 "
        state["quantitative_model"]["cost_items"][0]["evidence_id"] = " EV-OPS-001 "
        before = deepcopy(state)
        self.assertTrue(self.bb.validate_state(state)["ready"])
        self.assertFalse(evaluate(state, REPORT + "EV-OPS-001")["blocking"])
        self.assertEqual(state, before)

    def test_final_r2_append_cli_preserves_whitespace_source_record(self):
        for status in ("active", "disputed", "superseded"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                target = root / "tmp" / "strategy_blackboard.json"
                target.parent.mkdir()
                state = brief_state(maturity="decision_ready")
                first = state["evidence"]["records"][0]
                first["evidence_id"] = " EV-OPS-001 "
                frozen = json.dumps(first, ensure_ascii=False).encode("utf-8")
                target.write_text(json.dumps(state), encoding="utf-8")
                correction = dict(
                    first,
                    evidence_id="EV-OPS-002",
                    supersedes="EV-OPS-001",
                    status=status,
                    limitations="Synthetic dispute or withdrawal",
                )
                result = run_cli(
                    BLACKBOARD,
                    "--workspace-root",
                    root,
                    "update",
                    "--section",
                    "evidence",
                    "--key",
                    "records",
                    "--action",
                    "append",
                    "--value",
                    "-",
                    input_text=json.dumps(correction),
                )
                self.assertEqual(result.returncode, 0, result.stdout)
                saved = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(
                    json.dumps(
                        saved["evidence"]["records"][0], ensure_ascii=False
                    ).encode("utf-8"),
                    frozen,
                )
                self.assertEqual(
                    self.bb.validate_state(saved)["ready"], status == "active"
                )

    @unittest.skipUnless(os.name == "nt", "Windows CRT lock regression")
    def test_review_windows_lock_contention_retries_nonblocking_mode(self):
        import msvcrt

        cases = (
            (exclusive, mode, code)
            for exclusive, mode in ((True, msvcrt.LK_NBLCK), (False, msvcrt.LK_NBRLCK))
            for code in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
        )
        for exclusive, mode, code in cases:
            with (
                self.subTest(exclusive=exclusive, code=code),
                tempfile.TemporaryDirectory() as directory,
            ):
                contention = OSError(code, "synthetic lock contention")
                with (
                    patch(
                        "msvcrt.locking", side_effect=[contention, None, None]
                    ) as locking,
                    patch.object(self.bb.time, "monotonic", side_effect=[0, 0]),
                    patch.object(self.bb.time, "sleep") as sleep,
                ):
                    with self.bb._file_lock(
                        Path(directory) / "board.json", exclusive=exclusive
                    ):
                        self.assertEqual(locking.call_count, 2)
                    self.assertEqual(
                        [call.args[1] for call in locking.call_args_list],
                        [mode, mode, msvcrt.LK_UNLCK],
                    )
                    sleep.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows CRT lock regression")
    def test_review_windows_lock_timeout_and_unrelated_errors_propagate(self):
        for code, clock in (
            (errno.EACCES, [0, 31]),
            (errno.EAGAIN, [0, 31]),
            (errno.EDEADLK, [0, 31]),
            (errno.EBADF, [0]),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                failure = OSError(code, "synthetic failure")
                with (
                    patch("msvcrt.locking", side_effect=failure) as locking,
                    patch.object(self.bb.time, "monotonic", side_effect=clock),
                    patch.object(self.bb.time, "sleep") as sleep,
                ):
                    with (
                        self.assertRaises(OSError) as caught,
                        self.bb._file_lock(
                            Path(directory) / "board.json", exclusive=True
                        ),
                    ):
                        self.fail("must not enter unlocked critical section")
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(locking.call_count, 1)
                    sleep.assert_not_called()

    def test_cross_surface_report_gate_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = investment_state()
            board = root / "board.json"
            board.write_text(json.dumps(state), encoding="utf-8")
            report = root / "report.md"
            for value, expected in ((50, 0), (999, 1)):
                report.write_text(
                    REPORT + f"[[output:OUT-B-ROI metric=roi value={value} unit=%]]",
                    encoding="utf-8",
                )
                result = run_cli(
                    GATE,
                    "--path",
                    report,
                    "--mode",
                    "investment-case",
                    "--blackboard",
                    board,
                    "--strict",
                )
                self.assertEqual(result.returncode, expected, result.stdout)
                self.assertEqual(json_payload(result)["blocking"], bool(expected))


if __name__ == "__main__":
    unittest.main(verbosity=2)
