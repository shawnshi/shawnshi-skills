from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.common import load_json, run_python


class InitializerCLITests(unittest.TestCase):
    def initialize(self, root: Path, name: str = "示例医院", *extra: str):
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
                *extra,
                "--json",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def test_initializer_happy_path_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.initialize(Path(temporary), "示例医院", "--modules", "institution")
            workspace = Path(payload["workspace"])
            self.assertEqual(len(list(workspace.glob("*.md"))), 2)
            self.assertTrue((workspace / "runtime" / "manifest.json").is_file())
            manifest = load_json(workspace / "runtime" / "manifest.json")
            self.assertEqual(manifest["context_id"], payload["context_id"])
            validation = run_python("validate_outputs.py", [str(workspace), "--json"])
            self.assertEqual(validation.returncode, 0, validation.stderr or validation.stdout)

    def test_four_business_modes_map_to_compatible_route_depth_modules(self):
        help_result = run_python("init_workspace.py", ["--help"])
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--business-mode", help_result.stdout)
        expected = {
            "briefing": ("visit_prep", "quick", {"institution", "strategy"}),
            "standard_visit": (
                "visit_prep",
                "standard",
                {"institution", "leader", "strategy"},
            ),
            "strategic_account": (
                "strategy",
                "deep",
                {"institution", "leader", "strategy"},
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
                    workspace = Path(payload["workspace"])
                    manifest = load_json(workspace / "runtime" / "manifest.json")
                    self.assertEqual(manifest["business_mode"], mode)
                    self.assertFalse(manifest["ready_for_use"])
                    validation = run_python("validate_outputs.py", [str(workspace), "--json"])
                    self.assertEqual(validation.returncode, 0, validation.stderr or validation.stdout)
                    self.assertEqual(json.loads(validation.stdout)["errors"], 0)

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


if __name__ == "__main__":
    unittest.main()
