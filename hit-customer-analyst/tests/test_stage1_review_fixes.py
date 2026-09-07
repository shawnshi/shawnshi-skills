from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.common import SCRIPTS, SKILL_ROOT, load_json, load_module
from tests.common import research_plan as rp
from tests.common import run_python
from tests.fixture_builder import build_pending_letter_workspace, build_pending_strategy_workspace
from tests.test_profile_and_planning import NOW, build

vo = load_module("stage1_review_validate_outputs", SCRIPTS / "validate_outputs.py")


class ActorPunctuationTests(unittest.TestCase):
    def test_R_ACTOR_PUNCT_label_with_colon_rejected(self):
        self.assertFalse(vo.valid_actor("审批人："))

    def test_R_ACTOR_PUNCT_variants_and_specific_identity_display(self):
        for role in ("销售", "领导", "审核人", "审批人", "责任人", "负责人",
                     "sales", "leader", "reviewer", "approver", "ai", "model"):
            for suffix in ("", "：", ": ", "，。；！？、", ".,;!?", "…—", " ： 。 \u3000"):
                with self.subTest(role=role, suffix=suffix):
                    self.assertFalse(vo.valid_actor(role + suffix))
                    with self.assertRaises(RuntimeError):
                        vo.clean_actor(role + suffix, "--reviewer")
        for actor in ("张三", "孙宁（人物事实审核岗）", "客户沟通审批岗-01",
                      "reviewer.account-01", "审批人:张三", "审批人：张三", "张三。"):
            with self.subTest(actor=actor):
                self.assertTrue(vo.valid_actor(actor))
                self.assertEqual(vo.clean_actor(actor, "--reviewer"), actor)

    def govern(self, workspace, *args):
        result = run_python("validate_outputs.py", [str(workspace), *args, "--json"])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["errors"], 0, result.stdout)

    def assert_cli_rejected_unchanged(self, workspace, *args):
        before = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        self.assertIn(Path("runtime/manifest.json"), before)
        result = run_python("validate_outputs.py", [str(workspace), *args, "--json"])
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["errors"], 1, payload)
        self.assertEqual(payload["issues"][0]["code"], "operation_failed")
        self.assertIn("非泛化角色", payload["issues"][0]["message"])
        after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_R_ACTOR_PUNCT_cli_approval_and_ready_reject_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            letter = build_pending_letter_workspace(root / "letter")
            self.assert_cli_rejected_unchanged(letter, "--approve-letter", "--approver", "审批人：")
            strategy = build_pending_strategy_workspace(root / "strategy")
            self.assert_cli_rejected_unchanged(strategy, "--approve-artifact", "leader", "--reviewer", "审核人。 ")
            for target in ("leader", "strategy"):
                self.govern(strategy, "--approve-artifact", target, "--reviewer", "审批人:张三")
            self.assert_cli_rejected_unchanged(strategy, "--mark-ready", "--reviewer", "reviewer: ")
            self.govern(strategy, "--mark-ready", "--reviewer", "孙宁（人物事实审核岗）")

    def test_R_ACTOR_PUNCT_approved_and_ready_read_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            letter = build_pending_letter_workspace(root / "letter")
            self.govern(letter, "--approve-letter", "--approver", "审批人：张三")
            self.govern(letter, "--emit-external")
            strategy = build_pending_strategy_workspace(root / "strategy")
            for target in ("leader", "strategy"):
                self.govern(strategy, "--approve-artifact", target, "--reviewer", "审批人:张三")
            self.govern(strategy, "--mark-ready", "--reviewer", "张三")
            for workspace in (letter, strategy):
                documents = vo.load_documents(workspace, [])
                for document in documents:
                    if document.frontmatter["review_status"] != "approved":
                        continue
                    field = "approver" if document.frontmatter["artifact_type"].startswith("customer_letter") else "reviewer"
                    code = "approver_missing" if field == "approver" else "reviewer_unassigned"
                    baseline = []
                    vo.validate_frontmatter(document, baseline, False)
                    self.assertNotIn(code, {issue.code for issue in baseline})
                    document.frontmatter[field] = "审批人： 。 "
                    issues = []
                    vo.validate_frontmatter(document, issues, False)
                    self.assertIn(code, {issue.code for issue in issues}, document.path)
            by_type = {doc.frontmatter["artifact_type"]: doc for doc in vo.load_documents(strategy, [])}
            issues = []
            vo.validate_operating_governance(by_type, issues, False)
            self.assertNotIn("readiness_reviewer_unassigned", {issue.code for issue in issues})
            by_type["comprehensive_report"].frontmatter["readiness_reviewer"] = "reviewer: "
            issues = []
            vo.validate_operating_governance(by_type, issues, False)
            self.assertIn("readiness_reviewer_unassigned", {issue.code for issue in issues})


class MetricsCounterTests(unittest.TestCase):
    def test_R_METRICS_COUNTERS_string_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = rp.RuntimeWorkspace(Path(temporary))
            plan = build("briefing")
            paths = runtime.materialize(plan)
            metrics = load_json(paths["run_metrics"])
            metrics["counters"]["queries_executed"] = "broken"
            rp.atomic_write_json(paths["run_metrics"], metrics)
            before = {key: path.read_bytes() for key, path in paths.items()}
            revised = copy.deepcopy(plan)
            revised["generated_at"] = "2026-08-26T05:00:00Z"
            with self.assertRaisesRegex(rp.PlanError, "counters"):
                runtime.materialize(revised)
            self.assertEqual(before, {key: path.read_bytes() for key, path in paths.items()})

    def test_R_METRICS_COUNTERS_schema_boundaries_before_first_write(self):
        schema = load_json(SKILL_ROOT / "schemas" / "run-metrics.schema.json")["properties"]["counters"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(rp.RunMetrics.COUNTERS))
        self.assertEqual(set(schema["properties"]), set(rp.RunMetrics.COUNTERS))
        with tempfile.TemporaryDirectory() as temporary:
            runtime = rp.RuntimeWorkspace(Path(temporary))
            plan = build("briefing")
            paths = runtime.materialize(plan)
            original = load_json(paths["run_metrics"])
            valid = original["counters"]
            invalid = [("not-object", []), ("extra-key", {**valid, "extra": 0})]
            for key, rule in schema["properties"].items():
                self.assertEqual(rule["minimum"], 0)
                types = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
                invalid.append((key + ":missing", {k: v for k, v in valid.items() if k != key}))
                for value in ("1", -1, 1.5, True, False, [], {}):
                    invalid.append((f"{key}:{value!r}", {**valid, key: value}))
                if "null" not in types:
                    invalid.append((key + ":null", {**valid, key: None}))
            revised = {**plan, "generated_at": "2026-08-26T05:00:00Z"}
            for label, counters in invalid:
                with self.subTest(case=label):
                    rp.atomic_write_json(paths["run_metrics"], {**original, "counters": counters})
                    before = {key: path.read_bytes() for key, path in paths.items()}
                    with patch.object(rp, "atomic_write_json", wraps=rp.atomic_write_json) as writer:
                        with self.assertRaisesRegex(rp.PlanError, "counters"):
                            runtime.materialize(revised)
                        writer.assert_not_called()
                    self.assertEqual(before, {key: path.read_bytes() for key, path in paths.items()})

    def test_R_METRICS_COUNTERS_valid_history_preserved_and_incrementable(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = rp.RuntimeWorkspace(Path(temporary))
            plan = build("briefing")
            paths = runtime.materialize(plan)
            metrics = rp.RunMetrics(paths["run_metrics"], plan["context_id"], plan["run_id"], "briefing", NOW)
            for tokens in (None, 0, 10**30):
                with self.subTest(tokens=tokens):
                    value = metrics.initial()
                    value["counters"].update({key: index for index, key in enumerate(rp.RunMetrics.COUNTERS)})
                    value["counters"].update(input_tokens=tokens, output_tokens=tokens)
                    metrics.save(value)
                    before = {key: paths[key].read_bytes() for key in ("run_metrics", "source_cache", "evidence_manifest")}
                    runtime.materialize({**plan, "generated_at": "2026-08-26T05:00:00Z"})
                    self.assertEqual(before, {key: paths[key].read_bytes() for key in before})
                    incremented = metrics.increment(**dict.fromkeys(rp.RunMetrics.COUNTERS, 1))
                    self.assertEqual(incremented["counters"], {key: (count or 0) + 1 for key, count in value["counters"].items()})


if __name__ == "__main__":
    unittest.main()
