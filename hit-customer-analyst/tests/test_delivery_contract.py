from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.common import SCRIPTS, load_module, run_python
from tests.fixture_builder import _rebuild_manifest, build_pending_strategy_workspace

v = load_module("validate_outputs", SCRIPTS / "validate_outputs.py")
e = load_module("briefing_export", SCRIPTS / "export_briefing.py")


class DeliveryContractTests(unittest.TestCase):
    def build(self, root, mode="standard_visit"):
        return build_pending_strategy_workspace(
            root, business_mode=mode, role_only=True
        )

    def total(self, ws):
        return next(ws.glob("*客户研究与拜访准备报告.md"))

    def change(self, ws, path, transform):
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
        _rebuild_manifest(ws, ["institution", "leader", "strategy"])

    def approve(self, ws):
        for module in ("leader", "strategy"):
            result = run_python(
                "validate_outputs.py",
                [
                    str(ws),
                    "--approve-artifact",
                    module,
                    "--reviewer",
                    "合成审核员甲（测试岗）",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def ready(self, ws):
        return run_python(
            "validate_outputs.py",
            [str(ws), "--mark-ready", "--reviewer", "合成审核员乙（测试岗）", "--json"],
        )

    def test_missing_owner_bad_date_and_duplicate_action_reject_ready(self):
        for defect in ("owner", "action_owner", "date", "duplicate", "action"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                ws = self.build(Path(temp))

                def mutate(text, defect=defect):
                    if defect == "owner":
                        return text.replace(
                            "| account_owner | 合成客户负责人（测试岗） |",
                            "| account_owner | 待确认 |",
                        )
                    if defect == "action_owner":
                        return text.replace(
                            "| 确认后续交流条件 | 合成行动负责人（测试岗） |",
                            "| 确认后续交流条件 | 待确认 |",
                        )
                    if defect in {"date", "duplicate"}:
                        row = next(
                            line
                            for line in text.splitlines()
                            if line.startswith("| 确认后续交流条件 |")
                        )
                        replacement = (
                            "| 确认后续交流条件 | 合成行动负责人（测试岗） | 2026-02-30 |"
                            if defect == "date"
                            else row + "\n" + row
                        )
                        return text.replace(row, replacement)
                    return text.replace(
                        "| action | owner | due_date |", "| action | owner | 缺少日期 |"
                    )

                self.change(ws, self.total(ws), mutate)
                self.approve(ws)
                before = self.total(ws).read_bytes()
                result = self.ready(ws)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "account_owner_required"
                    if defect == "owner"
                    else "main_action_required",
                    result.stdout,
                )
                self.assertEqual(before, self.total(ws).read_bytes())
        self.assertFalse(v.date_valid("2026-02-30"))

    def test_no_meeting_monitor_account_plan_can_be_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            ws = self.build(Path(temp), "strategic_account")
            strategy = next(ws.glob("*交流策略与议题设计.md"))

            def account(text):
                return (
                    text.replace(
                        "## 议程",
                        "## 账户经营计划\n\n经营周期：未来30天；建议monitor。停止条件：需求不成立则停止投入。",
                    )
                    .replace("## 参会分工", "## 验证责任")
                    .replace("## 会后行动", "## 复核动作")
                    .replace("## 材料与演示计划", "## 证据计划")
                )

            self.change(ws, strategy, account)
            self.approve(ws)
            result = self.ready(ws)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertNotIn("## 议程", strategy.read_text(encoding="utf-8"))
            result = run_python("validate_outputs.py", [str(ws), "--strict", "--json"])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_briefing_missing_body_and_unknown_claim_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ws = self.build(Path(temp), "briefing")
            self.approve(ws)
            result = self.ready(ws)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("briefing_body_required", result.stdout)
            self.change(
                ws,
                self.total(ws),
                lambda text: (
                    text
                    + "\n<!-- briefing:start -->\n事实 CLM-I-999\n<!-- briefing:end -->\n"
                ),
            )
            self.assertTrue(
                any(i.severity == "error" for i in v.validate(ws, False, False)[0])
            )

    def test_briefing_export_bound_to_reviewed_total(self):
        with tempfile.TemporaryDirectory() as temp:
            ws = self.build(Path(temp), "briefing")
            for artifact in ws.glob("*.md"):
                artifact.write_text(
                    artifact.read_text(encoding="utf-8").replace(
                        "CLM-I-001", "CLM-I-1000"
                    ),
                    encoding="utf-8",
                )
            from tests.test_candidate_revision import BRIEF
            body = BRIEF.replace("CLM-I-001", "CLM-I-1000").strip()
            self.change(
                ws,
                self.total(ws),
                lambda text: (
                    text
                    + "\n<!-- briefing:start -->\n"
                    + body
                    + "\n<!-- briefing:end -->\n"
                ),
            )
            with self.assertRaises(ValueError):
                e.export(ws)
            self.approve(ws)
            result = self.ready(ws)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(e.export(ws), body + "\n")
            rendered = e.export(ws, "html")
            self.assertIn("size:A4", rendered)
            self.assertNotIn("任务上下文", rendered)
            self.assertNotIn("<script", rendered)
            self.change(
                ws, self.total(ws), lambda text: text.replace("低投入", "高投入")
            )
            with self.assertRaises(ValueError):
                e.export(ws)

    def test_briefing_limits_reject_instead_of_clipping(self):
        for body in ("x" * 1601, "行\n" * 49, "\u202e伪装"):
            with self.assertRaises(ValueError):
                v.briefing_lines(body)
        self.assertEqual(len(v.briefing_lines("院" * 72)), 2)


if __name__ == "__main__":
    unittest.main()
