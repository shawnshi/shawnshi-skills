"""Regression tests for the solution-architect quality gate scripts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]


class ScriptTestCase(unittest.TestCase):
    def run_script(
        self, script: str, *arguments: object
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT_DIR / script),
                *(str(argument) for argument in arguments),
            ],
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            check=False,
            timeout=30,
        )
        try:
            report = json.loads(completed.stdout)
        except (
            json.JSONDecodeError
        ) as exc:  # pragma: no cover - improves failure diagnostics
            self.fail(
                f"{script} did not emit JSON (exit={completed.returncode}).\n"
                f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}\n{exc}"
            )
        return completed, report

    def write_draft(self, directory: Path, content: str) -> Path:
        path = directory / "draft.md"
        path.write_text(content, encoding="utf-8")
        return path


class LogicCheckerTests(ScriptTestCase):
    def test_registered_legacy_and_curly_placeholders_block_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "# 摘要\n现状已核实，风险已登记。负责人 [OWNER]，测试 [TEST]，证据 [待核验]，值 {{FIELD}}。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "brief",
                "--stage",
                "release",
                "--review-complete",
            )
        self.assertEqual(completed.returncode, 1)
        finding = next(
            item
            for item in report["errors"]
            if item["code"] == "E_UNRESOLVED_PLACEHOLDER"
        )
        self.assertEqual(
            finding["instances"], ["[OWNER]", "[TEST]", "[待核验]", "{{FIELD}}"]
        )

    def test_technical_identifiers_are_not_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "# 摘要\n现状依据 [HL7_V2] 和 [ISO_27001] 核验，风险已登记。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "brief",
                "--stage",
                "release",
                "--review-complete",
            )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn(
            "E_UNRESOLVED_PLACEHOLDER", {item["code"] for item in report["errors"]}
        )

    def test_review_allows_controlled_placeholders_only_in_gap_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 评审结论\n目标架构、非功能、证据台账与风险已审阅。\n"
                "## 信息缺口与取证计划\n接口峰值为 {{PEAK_LOAD}}，由 {{OWNER}} 取证。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py", draft, "--profile", "review", "--stage", "review"
            )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn(
            "E_UNRESOLVED_PLACEHOLDER", {item["code"] for item in report["errors"]}
        )
        self.assertIn(
            "W_CONTROLLED_REVIEW_PLACEHOLDER",
            {item["code"] for item in report["warnings"]},
        )

    def test_review_blocks_placeholders_in_commitment_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 评审结论\n目标架构由 {{OWNER}} 负责，非功能、证据台账与风险已审阅。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py", draft, "--profile", "review", "--stage", "review"
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "E_UNRESOLVED_PLACEHOLDER", {item["code"] for item in report["errors"]}
        )

    def test_negative_scope_does_not_satisfy_required_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 范围\n现状已核实。本次不涉及迁移、不需要目标架构，且不纳入 TCO。风险已登记。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "proposal",
                "--stage",
                "review",
                "--require",
                "architecture,migration,tco",
            )
        self.assertEqual(completed.returncode, 1)
        missing = {
            item["module"]
            for item in report["errors"]
            if item["code"] == "E_MISSING_REQUIRED_MODULE"
        }
        self.assertEqual(missing, {"architecture", "migration", "tco"})

    def test_unsourced_tco_and_roi_block_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 方案\n现状、目标架构、安全与迁移验收范围已明确，风险已登记。TCO 4200万元，ROI 53%。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "proposal",
                "--stage",
                "release",
                "--review-complete",
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "E_UNSOURCED_QUANTIFIED_BENEFIT",
            {item["code"] for item in report["errors"]},
        )

    def test_sourced_quantification_is_not_a_release_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 方案\n现状、目标架构、安全与迁移验收范围已明确，风险已登记。\n"
                "TCO 4200万元，ROI 53%；来源：客户材料；资料日期：2026-08-01；适用地区：中国。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "proposal",
                "--stage",
                "release",
                "--review-complete",
            )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn(
            "E_UNSOURCED_QUANTIFIED_BENEFIT",
            {item["code"] for item in report["errors"]},
        )

    def test_release_quantification_requires_unit_date_and_region(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 方案\n现状、目标架构、安全、非功能、验收指标与风险已记录。\n"
                "ROI = 0.53；来源：客户测量记录。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "proposal",
                "--stage",
                "release",
                "--review-complete",
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "E_INCOMPLETE_QUANT_METADATA", {item["code"] for item in report["errors"]}
        )

    def test_release_review_is_not_reported_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary), "# 摘要\n现状已核实，风险已登记。\n"
            )
            completed, report = self.run_script(
                "logic_checker.py", draft, "--profile", "brief", "--stage", "release"
            )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["summary"]["review_count"], 1)
        self.assertFalse(report["gate"]["release_ready"])

    def test_duplicate_and_empty_sections_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 1. 现状\n## 2. 现状\n正文。\n",
            )
            completed, report = self.run_script(
                "logic_checker.py", draft, "--profile", "proposal", "--stage", "draft"
            )
        self.assertEqual(completed.returncode, 1)
        codes = {item["code"] for item in report["errors"]}
        self.assertIn("E_DUPLICATE_SECTION", codes)
        self.assertIn("E_EMPTY_SECTION", codes)
        self.assertEqual(
            [item["title"] for item in report["structure"]["sections"]],
            ["1. 现状", "2. 现状"],
        )

    def test_brief_accepts_h1_and_design_is_a_supported_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            brief = self.write_draft(
                Path(temporary), "# 摘要\n现状已核实，风险已登记。\n"
            )
            brief_completed, brief_report = self.run_script(
                "logic_checker.py", brief, "--profile", "brief", "--stage", "draft"
            )
            design = Path(temporary) / "design.md"
            design.write_text("## 详细设计\n架构设计与风险已记录。\n", encoding="utf-8")
            design_completed, design_report = self.run_script(
                "logic_checker.py", design, "--profile", "design", "--stage", "draft"
            )
        self.assertEqual(brief_completed.returncode, 0)
        self.assertNotIn(
            "E_MISSING_HEADINGS", {item["code"] for item in brief_report["errors"]}
        )
        self.assertEqual(design_completed.returncode, 0)
        self.assertEqual(design_report["profile"], "design")

    def test_utf8_bom_and_crlf_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = Path(temporary) / "bom.md"
            draft.write_bytes(
                "# 摘要\r\n现状已核实，风险已登记。\r\n".encode("utf-8-sig")
            )
            completed, report = self.run_script(
                "logic_checker.py", draft, "--profile", "brief", "--stage", "draft"
            )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn(
            "E_MISSING_HEADINGS", {item["code"] for item in report["errors"]}
        )

    def test_oversized_input_is_a_structured_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = Path(temporary) / "large.md"
            with draft.open("wb") as handle:
                handle.truncate(10 * 1024 * 1024 + 1)
            completed, report = self.run_script("logic_checker.py", draft)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["errors"][0]["code"], "E_FILE_READ")

    def test_conditional_modules_use_documented_names_and_are_not_profile_defaults(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "## 方案\n现状、目标架构、安全、非功能、验收指标与风险已记录。\n",
            )
            default_completed, default_report = self.run_script(
                "logic_checker.py", draft, "--profile", "proposal", "--stage", "draft"
            )
            required_completed, required_report = self.run_script(
                "logic_checker.py",
                draft,
                "--profile",
                "proposal",
                "--stage",
                "review",
                "--require",
                "migration,clinical-safety,evidence",
            )
        self.assertEqual(default_completed.returncode, 0)
        default_modules = {item.get("module") for item in default_report["warnings"]}
        self.assertNotIn("migration", default_modules)
        self.assertNotIn("clinical-safety", default_modules)
        self.assertEqual(required_completed.returncode, 1)
        required_modules = {
            item.get("module")
            for item in required_report["errors"]
            if item["code"] == "E_MISSING_REQUIRED_MODULE"
        }
        self.assertEqual(required_modules, {"migration", "clinical-safety", "evidence"})

    def test_read_failure_uses_runtime_exit_code(self) -> None:
        missing = (
            Path(tempfile.gettempdir()) / "quality-gate-file-that-does-not-exist.md"
        )
        completed, report = self.run_script("logic_checker.py", missing)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["errors"][0]["code"], "E_FILE_READ")

    def test_invalid_stage_is_a_structured_argument_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(Path(temporary), "# 摘要\n正文。\n")
            completed, report = self.run_script(
                "logic_checker.py", draft, "--stage", "publish"
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["errors"][0]["code"], "E_ARGUMENT")


class BuzzwordAuditorTests(ScriptTestCase):
    def test_code_quotes_and_inline_code_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary),
                "> **赋能**\n\n```text\n**赋能**\n```\n\n正文中的 `**赋能**` 是术语示例。\n",
            )
            completed, report = self.run_script(
                "buzzword_auditor.py", draft, "--bold-hint", 0
            )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["summary"]["bold_count"], 0)
        self.assertEqual(report["warnings"], [])

    def test_negative_bold_hint_is_structured_argument_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(Path(temporary), "正文。\n")
            completed, report = self.run_script(
                "buzzword_auditor.py", draft, "--bold-hint", -1
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["errors"][0]["code"], "E_ARGUMENT")

    def test_output_failure_does_not_print_a_prior_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = self.write_draft(root, "正文。\n")
            blocker = root / "not-a-directory"
            blocker.write_text("x", encoding="utf-8")
            completed, report = self.run_script(
                "buzzword_auditor.py", draft, "--output", blocker / "report.json"
            )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["errors"][0]["code"], "E_FILE_WRITE")


class QaRunnerTests(ScriptTestCase):
    def test_release_ready_exit_contract(self) -> None:
        cases = [
            ([], False, 0, False),
            (["--require-release-ready"], False, 1, False),
            (["--require-release-ready", "--review-complete"], False, 0, True),
            (["--require-release-ready", "--review-complete"], True, 1, False),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for flags, has_error, exit_code, ready in cases:
                with self.subTest(flags=flags, has_error=has_error):
                    content = "# 摘要\n现状已核实，风险已登记。\n"
                    if has_error:
                        content += "负责人 [OWNER]。\n"
                    draft = self.write_draft(Path(temporary), content)
                    completed, report = self.run_script(
                        "qa_runner.py",
                        draft,
                        "--profile",
                        "brief",
                        "--stage",
                        "release",
                        *flags,
                    )
                    self.assertEqual(completed.returncode, exit_code)
                    self.assertIs(report["gate"]["release_ready"], ready)
                    self.assertEqual(bool(report["errors"]), has_error)

    def test_require_release_ready_rejects_non_release_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary), "# 摘要\n现状已核实，风险已登记。\n"
            )
            for stage in ("draft", "review"):
                with self.subTest(stage=stage):
                    completed, report = self.run_script(
                        "qa_runner.py",
                        draft,
                        "--stage",
                        stage,
                        "--require-release-ready",
                    )
                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(report["errors"][0]["code"], "E_ARGUMENT")

    def test_combines_logic_and_style_and_writes_one_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft = self.write_draft(root, "# 摘要\n**现状**已核实，风险已登记。\n")
            output = root / "qa.json"
            completed, report = self.run_script(
                "qa_runner.py",
                draft,
                "--profile",
                "brief",
                "--stage",
                "draft",
                "--bold-hint",
                0,
                "--output",
                output,
            )
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report, saved)
        self.assertEqual(set(report["components"]), {"logic", "style"})
        self.assertIn("style", {item["component"] for item in report["warnings"]})

    def test_read_failure_uses_runtime_exit_code(self) -> None:
        missing = Path(tempfile.gettempdir()) / "qa-runner-file-that-does-not-exist.md"
        completed, report = self.run_script("qa_runner.py", missing)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["errors"][0]["code"], "E_FILE_READ")


class ResourceValidatorTests(ScriptTestCase):
    def make_manifest(
        self, root: Path, content: str, *, expected_hash: str | None = None
    ) -> Path:
        references = root / "references"
        references.mkdir()
        resource = references / "resource.md"
        resource.write_text(content, encoding="utf-8")
        digest = expected_hash or hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest = {
            "schema_version": 1,
            "hash_algorithm": "SHA-256",
            "text_hash_normalization": "LF",
            "top_level_directories": ["references"],
            "resource_directories": [{"name": "references", "file_count": 1}],
            "top_level_file_hashes": [],
            "resource_file_hashes": [
                {"path": "references/resource.md", "sha256": digest}
            ],
            "declared_local_dependencies": [],
        }
        manifest_path = root / "resource-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_valid_manifest_passes_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.make_manifest(root, "# Resource\nUseful content.\n")
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            completed, report = self.run_script("resource_validator.py", manifest)
            after = sorted(path.relative_to(root) for path in root.rglob("*"))
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(before, after)

    def test_hash_mismatch_and_placeholder_are_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.make_manifest(
                root, "<!-- Placeholder -->", expected_hash="0" * 64
            )
            completed, report = self.run_script("resource_validator.py", manifest)
        self.assertEqual(completed.returncode, 1)
        codes = {item["code"] for item in report["errors"]}
        self.assertIn("E_HASH_MISMATCH", codes)
        self.assertIn("E_RESOURCE_PLACEHOLDER", codes)

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "skill"
            root.mkdir()
            outside = parent / "outside.md"
            outside.write_text("secret", encoding="utf-8")
            manifest = {
                "hash_algorithm": "SHA-256",
                "text_hash_normalization": "LF",
                "top_level_directories": [],
                "resource_directories": [],
                "top_level_file_hashes": [],
                "resource_file_hashes": [{"path": "../outside.md", "sha256": "0" * 64}],
                "declared_local_dependencies": [],
            }
            manifest_path = root / "resource-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            completed, report = self.run_script("resource_validator.py", manifest_path)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "E_PATH_OUTSIDE_SKILL", {item["code"] for item in report["errors"]}
        )

    def test_invalid_json_uses_runtime_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "resource-manifest.json"
            manifest.write_text("not json", encoding="utf-8")
            completed, report = self.run_script("resource_validator.py", manifest)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["errors"][0]["code"], "E_MANIFEST_READ")

    def test_dependency_hash_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.make_manifest(root, "# Resource\nUseful content.\n")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["declared_local_dependencies"] = [
                {"path": "references/resource.md", "exists": True, "sha256": "f" * 64}
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            completed, report = self.run_script("resource_validator.py", manifest_path)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "E_DEPENDENCY_HASH_MISMATCH", {item["code"] for item in report["errors"]}
        )


if __name__ == "__main__":
    unittest.main()
