from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.common import bind_intake_payload, load_json, run_python, write_intake


class InitializerCLITests(unittest.TestCase):
    def initialize(self, root: Path, name: str = "示例医院", *extra: str):
        arguments = list(extra)
        if "--business-mode" not in arguments:
            arguments.extend(["--business-mode", "briefing"])
        if "--business-mode" in arguments and "--intake-input" not in arguments:
            mode = arguments[arguments.index("--business-mode") + 1]
            arguments.extend(["--intake-input", str(write_intake(root, name, mode))])
        result = run_python(
            "init_workspace.py",
            [
                name,
                "--output-root",
                str(root),
                "--task-timezone",
                "Asia/Shanghai",
                "--runtime-owner",
                "测试负责人",
                *arguments,
                "--json",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def test_initializer_happy_path_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.initialize(Path(temporary), "示例医院")
            workspace = Path(payload["workspace"])
            self.assertEqual(len(list(workspace.glob("*.md"))), 4)
            self.assertTrue((workspace / "runtime" / "manifest.json").is_file())
            manifest = load_json(workspace / "runtime" / "manifest.json")
            self.assertEqual(manifest["context_id"], payload["context_id"])
            self.assertEqual(manifest["task_timezone"], "Asia/Shanghai")
            self.assertEqual(payload["task_timezone"], "Asia/Shanghai")
            validation = run_python("validate_outputs.py", [str(workspace), "--profile", "scaffold", "--json"])
            self.assertEqual(validation.returncode, 0, validation.stderr or validation.stdout)

    def test_four_business_modes_map_to_compatible_route_depth_modules(self):
        help_result = run_python("init_workspace.py", ["--help"])
        if "--business-mode" not in help_result.stdout:
            self.skipTest("当前init CLI尚未支持--business-mode")
        expected = {
            "briefing": ("visit_prep", "quick", {"institution", "strategy"}),
            "standard_visit": (
                "visit_prep",
                "standard",
                {"institution", "strategy"},
            ),
            "strategic_account": (
                "strategy",
                "deep",
                {"institution", "strategy"},
            ),
            "letter": ("letter", "standard", {"institution", "letter"}),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for mode, (route, depth, modules) in expected.items():
                with self.subTest(mode=mode):
                    output_root = root / mode
                    output_root.mkdir()
                    payload = self.initialize(
                        output_root,
                        f"示例医院-{mode}",
                        "--business-mode",
                        mode,
                    )
                    self.assertEqual(payload["business_mode"], mode)
                    self.assertEqual(payload["route"], route)
                    self.assertEqual(payload["depth"], depth)
                    self.assertEqual(set(payload["selected_modules"]), modules)

    def test_briefing_is_registered_in_status_and_run_partition(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.initialize(
                Path(temporary),
                "示例医院-速览",
                "--business-mode",
                "briefing",
            )
            workspace = Path(payload["workspace"])
            total = next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
            self.assertRegex(total, r"(?m)^\| 会前速览 \| true \| created \|")
            self.assertIn("selected_modules=institution,strategy,briefing", total)
            self.assertIn("not_called=leader,internal,letter,external_letter", total)
            self.assertEqual(len(list(workspace.glob("*会前速览.md"))), 1)

    def test_briefing_fact_without_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.initialize(
                Path(temporary),
                "示例医院-证据门禁",
                "--business-mode",
                "briefing",
            )
            workspace = Path(payload["workspace"])
            briefing = next(workspace.glob("*会前速览.md"))
            text = briefing.read_text(encoding="utf-8").replace(
                "| {{最多5条已核实事实}} | {{只填F或F2；至少1个CLM-I/L/N-###}} | {{一句话}} |",
                "| 医院已发布年度重点任务 | F | 用于开场确认 |",
            )
            briefing.write_text(text, encoding="utf-8")
            result = run_python(
                "validate_outputs.py",
                [str(workspace), "--profile", "candidate", "--json"],
            )
            self.assertNotEqual(result.returncode, 0)
            codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
            self.assertIn("briefing_fact_claim_missing", codes)

    def test_duplicate_context_id_is_rejected(self):
        context_id = "dcx-20260826-DupA1234"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.initialize(root, "示例医院", "--context-id", context_id)
            second = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(root),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--context-id",
                    context_id,
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(write_intake(root, "示例医院", "briefing")),
                    "--json",
                ],
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("context_id已在输出根目录使用", second.stderr)
            self.assertTrue(Path(first["workspace"]).is_dir())

    def test_fenced_yaml_is_not_misread_as_second_frontmatter(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.initialize(Path(temporary), "示例医院")
            workspace = Path(payload["workspace"])
            institution = next(workspace.glob("*机构研究报告.md"))
            institution.write_text(
                institution.read_text(encoding="utf-8")
                + "\n```yaml\n---\nowner: forged\n---\n```\n",
                encoding="utf-8",
            )
            result = run_python("validate_outputs.py", [str(workspace), "--json"])
            # A direct edit is correctly rejected as manifest drift.  The
            # regression under test is narrower: a fenced YAML example must
            # never be parsed as a second document frontmatter block.
            payload = json.loads(result.stdout)
            codes = {issue["code"] for issue in payload["issues"]}
            self.assertIn("runtime_manifest_artifact_drift", codes)
            self.assertNotIn("frontmatter_duplicate_block", codes)

    def test_legacy_route_without_business_mode_is_blocked_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "must-not-exist"
            result = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(output_root),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--route",
                    "visit_prep",
                    "--mode",
                    "quick",
                    "--modules",
                    "institution,strategy",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--business-mode", result.stderr)
            self.assertFalse(output_root.exists())

    def test_project_id_is_bound_to_the_same_intake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root, "示例医院", "briefing")
            payload = json.loads(intake.read_text(encoding="utf-8"))
            payload["candidate_sets"].append(
                {
                    "field": "project_id",
                    "candidates": [
                        {
                            "candidate_id": "project-a",
                            "value": "project.A",
                            "status": "asserted",
                            "source_ref": "test:user-turn:1",
                        }
                    ],
                }
            )
            bind_intake_payload(intake, payload)
            output_root = root / "out"
            result = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(output_root),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(intake),
                    "--project-id",
                    "project.B",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("project_id", result.stderr)
            self.assertFalse(output_root.exists())

    def test_letter_context_is_rendered_from_ready_intake(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.initialize(Path(temporary), "示例医院", "--business-mode", "letter")
            workspace = Path(payload["workspace"])
            letter = next(workspace.glob("*客户信（内部待审核稿）.md")).read_text(encoding="utf-8")
            for expected in (
                'letter_scenario: "拜访后正式跟进"',
                'recipient_role: "信息中心主任"',
                'letter_purpose: "确认下一次技术交流安排"',
                'expected_action: "确认九月技术交流时间"',
                'signer: "战略咨询部"',
                'delivery_channel: "正式邮件"',
            ):
                self.assertIn(expected, letter)


if __name__ == "__main__":
    unittest.main()
