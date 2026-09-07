from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.common import run_python
from tests.fixture_builder import build_pending_letter_workspace


class BehavioralNegativeTests(unittest.TestCase):
    """Real mutations and process-level assertions, separate from case mapping."""

    def initialize(self, output_root: Path, *extra: str) -> Path:
        result = run_python(
            "init_workspace.py",
            [
                "行为测试医院",
                "--output-root",
                str(output_root),
                "--task-timezone",
                "Asia/Shanghai",
                "--runtime-owner",
                "测试负责人",
                *extra,
                "--json",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return Path(json.loads(result.stdout)["workspace"])

    def validate_codes(self, workspace: Path, *extra: str) -> tuple[int, set[str]]:
        result = run_python(
            "validate_outputs.py", [str(workspace), *extra, "--json"]
        )
        payload = json.loads(result.stdout)
        return result.returncode, {issue["code"] for issue in payload["issues"]}

    @staticmethod
    def remove_frontmatter_key(path: Path, key: str) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(
            "\n".join(line for line in lines if not line.startswith(f"{key}:")) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def replace_line(path: Path, prefix: str, replacement: str) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
        lines[index] = replacement
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_N01_delete_comprehensive_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            next(workspace.glob("*客户研究与拜访准备报告.md")).unlink()
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("comprehensive_count", codes)

    def test_N02_delete_latest_run_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            self.remove_frontmatter_key(institution, "latest_run_id")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("frontmatter_required", codes)

    def test_N03_invalid_review_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            self.replace_line(
                institution,
                "review_status:",
                'review_status: "review_required"',
            )
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("review_status_invalid", codes)

    def test_N04_invalid_connector_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            self.replace_line(
                institution,
                "connector_status:",
                'connector_status: "not_connected"',
            )
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("connector_status_invalid", codes)

    def test_N05_legacy_owner_and_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            text = institution.read_text(encoding="utf-8").replace(
                'artifact_type: "institution_research"',
                'artifact_type: "institution_research"\nowner: "legacy"\nversion: "9"',
                1,
            )
            institution.write_text(text, encoding="utf-8")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("legacy_metadata", codes)

    def test_N06_selected_module_without_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            lines = total.read_text(encoding="utf-8").splitlines()
            index = next(i for i, line in enumerate(lines) if line.startswith("| 人物研究 |"))
            lines[index] = lines[index].replace(
                "| false | not_called |", "| true | created |", 1
            )
            total.write_text("\n".join(lines) + "\n", encoding="utf-8")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("selected_artifact_missing", codes)

    def test_N08_status_row_drift_from_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            lines = total.read_text(encoding="utf-8").splitlines()
            index = next(i for i, line in enumerate(lines) if line.startswith("| 机构研究 |"))
            cells = lines[index].split("|")
            cells[7] = " stale "
            lines[index] = "|".join(cells)
            total.write_text("\n".join(lines) + "\n", encoding="utf-8")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("status_sync_mismatch", codes)

    def test_N17_relative_link_escapes_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            institution.write_text(
                institution.read_text(encoding="utf-8")
                + "\n[越界证据](../../outside.md)\n",
                encoding="utf-8",
            )
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("link_escape", codes)

    def test_N25_strict_rejects_nonterminal_initial_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--business-mode", "briefing")
            returncode, codes = self.validate_codes(workspace, "--strict")
            self.assertEqual(returncode, 1)
            self.assertIn("strict_total_not_ready", codes)
            self.assertIn("strict_workflow_stage_not_ready", codes)

    def test_N34_artifact_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            os.symlink(institution.name, workspace / "伪造成果.md")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("artifact_symlink", codes)

    def test_N35_duplicate_frontmatter_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            text = institution.read_text(encoding="utf-8").replace(
                'module_status: "queued"',
                'module_status: "queued"\nmodule_status: "completed"',
                1,
            )
            institution.write_text(text, encoding="utf-8")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("frontmatter_duplicate", codes)

    def test_N35_second_top_level_frontmatter_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            institution.write_text(
                institution.read_text(encoding="utf-8")
                + "\n---\nforged_owner: attacker\n---\n",
                encoding="utf-8",
            )
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("frontmatter_duplicate_block", codes)

    def test_N43_new_workspace_requires_time_basis(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_python(
                "init_workspace.py",
                [
                    "行为测试医院",
                    "--output-root",
                    temporary,
                    "--runtime-owner",
                    "测试负责人",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--task-timezone", result.stderr)
            self.assertIn("--evidence-cutoff-date", result.stderr)

    def test_manifest_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = next(workspace.glob("*机构研究报告.md"))
            institution.write_text(
                institution.read_text(encoding="utf-8") + "\n越权直写\n",
                encoding="utf-8",
            )
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("runtime_manifest_artifact_drift", codes)

    def test_commit_run_rejects_file_map_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self.initialize(root / "output", "--modules", "institution")
            manifest_path = workspace / "runtime" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            candidate = root / "candidate.md"
            candidate.write_text("candidate", encoding="utf-8")
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"../escaped.md": str(candidate)}), encoding="utf-8"
            )
            result = run_python(
                "commit_run.py",
                [
                    str(workspace),
                    "--file-map",
                    str(mapping),
                    "--expected-manifest-revision",
                    str(manifest["transaction_sequence"]),
                    "--expected-manifest-sha256",
                    digest,
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("越出工作目录", result.stderr)
            self.assertFalse((workspace.parent / "escaped.md").exists())

    def test_internal_selection_without_authorization_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_python(
                "init_workspace.py",
                [
                    "行为测试医院",
                    "--output-root",
                    str(root),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "standard_visit",
                    "--modules",
                    "institution,leader,internal,strategy",
                    "--json",
                ],
            )
            if result.returncode == 2:
                self.assertRegex(result.stderr, r"授权|authorization|tenant|project")
                return
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            workspace = Path(json.loads(result.stdout)["workspace"])
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("authorization_required", codes)

    def test_approved_letter_without_audit_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            letter = next(workspace.glob("*客户信（内部待审核稿）.md"))
            self.replace_line(letter, "review_status:", 'review_status: "approved"')
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertIn("approver_missing", codes)
            self.assertIn("approval_hash_invalid", codes)
            self.assertIn("approval_context_hash_invalid", codes)

    def test_ready_gate_blocks_strict_pending_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            returncode, codes = self.validate_codes(workspace, "--strict")
            self.assertEqual(returncode, 1)
            self.assertIn("ready_for_use_required", codes)


if __name__ == "__main__":
    unittest.main()
