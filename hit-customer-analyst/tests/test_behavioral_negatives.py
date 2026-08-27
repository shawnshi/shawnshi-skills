from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.common import SCRIPTS, load_module, run_python, runtime_tx as tx, write_intake
from tests.fixture_builder import (
    build_pending_letter_workspace,
    build_pending_strategy_workspace,
    record_action_assertion,
    record_external_request,
)


validator = load_module("discovery_call_behavioral_validator", SCRIPTS / "validate_outputs.py")
initializer = load_module("discovery_call_behavioral_initializer", SCRIPTS / "init_workspace.py")


class BehavioralNegativeTests(unittest.TestCase):
    """Real mutations and process-level assertions, separate from case mapping."""

    def initialize(self, output_root: Path, *extra: str) -> Path:
        intake = write_intake(
            output_root / "intakes",
            "行为测试医院",
            "briefing",
        )
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
                "--business-mode",
                "briefing",
                "--intake-input",
                str(intake),
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

    def assert_validation_code(self, workspace: Path, *codes: str, strict: bool = False) -> set[str]:
        extra = ("--strict",) if strict else ()
        returncode, actual = self.validate_codes(workspace, *extra)
        self.assertEqual(returncode, 1)
        self.assertTrue(set(codes) & actual, f"expected one of {codes}; got {sorted(actual)}")
        return actual

    def review_and_approve_letter(self, workspace: Path, prefix: str) -> object:
        fact_event = f"{prefix}-facts"
        record_action_assertion(
            workspace,
            event_id=fact_event,
            actor_id="reviewer-letter-facts",
            operation="review_letter_facts",
            artifact_type="customer_letter_internal",
        )
        reviewed = run_python(
            "validate_outputs.py",
            [
                str(workspace),
                "--review-letter-facts",
                "--reviewer",
                "吴芳（客户信事实复核岗）",
                "--actor-id",
                "reviewer-letter-facts",
                "--action-event-id",
                fact_event,
                "--json",
            ],
        )
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr or reviewed.stdout)
        approval_event = f"{prefix}-approval"
        record_action_assertion(
            workspace,
            event_id=approval_event,
            actor_id="approver-li",
            operation="approve_letter",
            artifact_type="customer_letter_internal",
        )
        approved = run_python(
            "validate_outputs.py",
            [
                str(workspace),
                "--approve-letter",
                "--approver",
                "李明（客户沟通审批岗）",
                "--actor-id",
                "approver-li",
                "--action-event-id",
                approval_event,
                "--json",
            ],
        )
        self.assertEqual(approved.returncode, 0, approved.stderr or approved.stdout)
        return approved

    def build_emitted_letter_workspace(self, output_root: Path) -> Path:
        workspace = build_pending_letter_workspace(output_root)
        self.review_and_approve_letter(workspace, "negative-case")
        record_external_request(workspace, event_id="negative-case-request")
        emitted = run_python(
            "validate_outputs.py",
            [
                str(workspace),
                "--emit-external",
                "--actor-id",
                "requester-wang",
                "--request-event-id",
                "negative-case-request",
                "--json",
            ],
        )
        self.assertEqual(emitted.returncode, 0, emitted.stderr or emitted.stdout)
        return workspace

    @staticmethod
    def total_path(workspace: Path) -> Path:
        return next(workspace.glob("*客户研究与拜访准备报告.md"))

    @staticmethod
    def institution_path(workspace: Path) -> Path:
        return next(workspace.glob("*机构研究报告.md"))

    @staticmethod
    def letter_path(workspace: Path) -> Path:
        return next(workspace.glob("*客户信（内部待审核稿）.md"))

    @staticmethod
    def external_path(workspace: Path) -> Path:
        return next(workspace.glob("*客户信（外发版）.md"))

    @staticmethod
    def alter_status_row(path: Path, label: str, transform) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith(f"| {label} |"))
        lines[index] = transform(lines[index])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def sha256_map(workspace: Path) -> dict[str, str]:
        return {
            str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in workspace.rglob("*")
            if path.is_file() and not path.name.startswith(".discovery-call-")
        }

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

    def test_N07_unselected_artifact_cannot_be_updated(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            total = self.total_path(workspace)
            self.alter_status_row(
                total,
                "机构研究",
                lambda row: row.replace("| true | created |", "| false | updated |", 1),
            )
            self.assert_validation_code(workspace, "run_action_unselected")

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

    def test_N09_completed_research_requires_claim_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8")
            start = text.index("## 9. 主张台账")
            end = text.index("## 10. 来源台账")
            institution.write_text(text[:start] + text[end:], encoding="utf-8")
            self.assert_validation_code(workspace, "completed_claim_ledger_missing")

    def test_N10_completed_research_requires_source_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8")
            institution.write_text(text[: text.index("## 10. 来源台账")], encoding="utf-8")
            self.assert_validation_code(workspace, "completed_source_ledger_missing")

    def test_N11_orphan_claim_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            institution.write_text(
                institution.read_text(encoding="utf-8") + "\n未定义主张 CLM-I-999。\n",
                encoding="utf-8",
            )
            self.assert_validation_code(workspace, "claim_orphan_reference")

    def test_N12_claim_source_orphan_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| SRC-I-001 | 无 | 高 |", "| SRC-I-999 | 无 | 高 |", 1
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(
                workspace, "claim_source_orphan", "source_orphan_reference"
            )

    def test_N13_claim_requires_supporting_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| SRC-I-001 | 无 | 高 |", "|  | 无 | 高 |", 1
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(workspace, "claim_source_missing")

    def test_N14_unknown_claim_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| CLM-I-001 | F | public |", "| CLM-I-001 | U | public |", 1
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(workspace, "claim_type_invalid")

    def test_N15_fact_verification_mapping_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| CLM-I-001 | F | public | verified_single |",
                "| CLM-I-001 | F | public | corroborated |",
                1,
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(workspace, "fact_mapping_invalid")

    def test_N16_legacy_evidence_identifier_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            institution.write_text(
                institution.read_text(encoding="utf-8") + "\n遗留证据 I-E001。\n",
                encoding="utf-8",
            )
            self.assert_validation_code(workspace, "legacy_evidence_id")

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

    def test_N18_external_markers_must_be_unique_and_ordered(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            text = letter.read_text(encoding="utf-8")
            text = text.replace("`EXTERNAL_BODY_START`", "`EXTERNAL_BODY_END`", 1)
            letter.write_text(text, encoding="utf-8")
            self.assert_validation_code(workspace, "external_markers_invalid")

    def test_N19_external_file_requires_approved_internal_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            self.replace_line(letter, "review_status:", 'review_status: "pending"')
            self.assert_validation_code(workspace, "external_source_unapproved")

    def test_N20_external_file_rejects_internal_terms(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            external = self.external_path(workspace)
            external.write_text(
                external.read_text(encoding="utf-8") + "\n价格底线：内部信息。\n",
                encoding="utf-8",
            )
            self.assert_validation_code(workspace, "external_internal_leak")

    def test_N21_external_body_must_equal_approved_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            external = self.external_path(workspace)
            external.write_text(
                external.read_text(encoding="utf-8").replace("九月技术交流", "十月技术交流", 1),
                encoding="utf-8",
            )
            self.assert_validation_code(workspace, "external_body_drift")

    def test_N22_fact2_requires_two_independent_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| CLM-I-001 | F | public | verified_single |",
                "| CLM-I-001 | F2 | public | corroborated |",
                1,
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(
                workspace,
                "fact2_sources_insufficient",
                "fact2_sources_not_fourfold_independent",
            )

    def test_N23_external_source_must_be_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            self.replace_line(letter, "freshness_status:", 'freshness_status: "stale"')
            self.assert_validation_code(workspace, "external_source_stale")

    def test_N24_letter_route_review_requires_internal_letter(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            self.letter_path(workspace).unlink()
            self.assert_validation_code(workspace, "route_required_artifact_missing")

    def test_N25_strict_rejects_nonterminal_initial_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            returncode, codes = self.validate_codes(workspace, "--strict")
            self.assertEqual(returncode, 1)
            self.assertIn("strict_total_not_ready", codes)
            self.assertIn("strict_workflow_stage_not_ready", codes)

    def test_N26_refresh_route_requires_resume_and_research_only_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            intake = write_intake(Path(temporary) / "intakes", "行为测试医院", "briefing")
            result = run_python(
                "init_workspace.py",
                [
                    "行为测试医院",
                    "--output-root",
                    temporary,
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(intake),
                    "--route",
                    "refresh",
                    "--modules",
                    "institution,strategy",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"refresh|续建|研究模块")

    def test_N27_output_route_requires_research_carrier(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_python(
                "init_workspace.py",
                [
                    "行为测试医院",
                    "--output-root",
                    temporary,
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--route",
                    "strategy",
                    "--modules",
                    "strategy",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"business-mode|intake-input|业务模式")

    def test_N28_resume_without_new_cutoff_preserves_existing_evidence_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root)
            total = self.total_path(workspace)
            before = tx.parse_frontmatter(total.read_text(encoding="utf-8"))
            intake = write_intake(root / "intakes", "示例医院", "standard_visit")
            resumed = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(root),
                    "--context-id",
                    before["context_id"],
                    "--resume",
                    "--business-mode",
                    "standard_visit",
                    "--intake-input",
                    str(intake),
                    "--runtime-owner",
                    "测试负责人",
                    "--json",
                ],
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr or resumed.stdout)
            after = tx.parse_frontmatter(total.read_text(encoding="utf-8"))
            self.assertEqual(after["evidence_cutoff_date"], before["evidence_cutoff_date"])
            self.assertEqual(after["freshness_status"], before["freshness_status"])

    def test_N29_status_registry_requires_exact_fifteen_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            total = self.total_path(workspace)
            self.alter_status_row(
                total,
                "机构研究",
                lambda row: "|".join(row.split("|")[:-2]) + " |",
            )
            self.assert_validation_code(workspace, "status_row_missing")

    def test_N30_review_stage_rejects_nonterminal_selected_research(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            total = self.total_path(workspace)
            self.replace_line(total, "workflow_stage:", 'workflow_stage: "review"')
            self.assert_validation_code(
                workspace,
                "selected_module_nonterminal",
                "review_stage_research_stale",
                "review_stage_status_invalid",
            )

    def test_N31_approved_letter_requires_bound_approval_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            self.review_and_approve_letter(workspace, "n31")
            letter = self.letter_path(workspace)
            self.replace_line(
                letter,
                "approved_body_sha256:",
                f'approved_body_sha256: "{"0" * 64}"',
            )
            self.assert_validation_code(
                workspace, "approval_metadata_required", "approval_body_drift"
            )

    def test_N32_external_candidate_rejects_html_comment(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            text = letter.read_text(encoding="utf-8").replace(
                "张主任，您好：", "张主任，您好：\n\n<!-- internal -->", 1
            )
            letter.write_text(text, encoding="utf-8")
            self.assert_validation_code(
                workspace, "external_candidate_leak", "external_html_comment"
            )

    def test_N33_external_lineage_metadata_cannot_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            external = self.external_path(workspace)
            self.replace_line(
                external,
                "source_internal_content_version:",
                'source_internal_content_version: "999"',
            )
            self.assert_validation_code(
                workspace, "external_metadata_drift", "external_lineage_version_drift"
            )

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

    def test_N36_emit_transaction_rolls_back_on_postflight_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            self.review_and_approve_letter(workspace, "n36")
            record_external_request(workspace, event_id="postflight-failure-request")
            issues: list = []
            documents = validator.load_documents(workspace, issues)
            self.assertFalse([issue for issue in issues if issue.severity == "error"])
            snapshot = validator.capture_workspace_snapshot(workspace, documents)
            internal = self.letter_path(workspace)
            total = self.total_path(workspace)
            before = {
                internal.name: hashlib.sha256(internal.read_bytes()).hexdigest(),
                total.name: hashlib.sha256(total.read_bytes()).hexdigest(),
            }
            with mock.patch.object(
                validator,
                "validate_loaded",
                side_effect=RuntimeError("forced postflight failure"),
            ):
                with self.assertRaises(Exception):
                    validator.emit_external(
                        workspace,
                        documents,
                        "requester-wang",
                        "postflight-failure-request",
                        snapshot,
                    )
            after = {
                internal.name: hashlib.sha256(internal.read_bytes()).hexdigest(),
                total.name: hashlib.sha256(total.read_bytes()).hexdigest(),
            }
            self.assertEqual(after, before)
            self.assertFalse(list(workspace.glob("*客户信（外发版）.md")))

    def test_N37_changes_requested_letter_cannot_be_directly_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            record_action_assertion(
                workspace,
                event_id="n37-revision",
                actor_id="letter-editor",
                operation="begin_letter_revision",
                artifact_type="customer_letter_internal",
            )
            revision = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--begin-letter-revision",
                    "--reviewer",
                    "赵敏（客户信修订岗）",
                    "--actor-id",
                    "letter-editor",
                    "--action-event-id",
                    "n37-revision",
                    "--json",
                ],
            )
            self.assertEqual(revision.returncode, 0, revision.stderr or revision.stdout)
            record_action_assertion(
                workspace,
                event_id="n37-direct-approval",
                actor_id="approver-li",
                operation="approve_letter",
                artifact_type="customer_letter_internal",
            )
            before = self.sha256_map(workspace)
            result = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--approve-letter",
                    "--approver",
                    "李明（客户沟通审批岗）",
                    "--actor-id",
                    "approver-li",
                    "--action-event-id",
                    "n37-direct-approval",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 1)
            codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
            self.assertIn("operation_failed", codes)
            self.assertEqual(self.sha256_map(workspace), before)

    def test_N38_source_fields_are_machine_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| 示例医院 | https://example.org/hospital/profile |",
                "| 示例医院 |  |",
                1,
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(workspace, "source_locator_missing")

    def test_N39_letter_rejects_unsafe_claim_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            institution = self.institution_path(workspace)
            text = institution.read_text(encoding="utf-8").replace(
                "| CLM-I-001 | F | public | verified_single |",
                "| CLM-I-001 | A | public | asserted |",
                1,
            )
            institution.write_text(text, encoding="utf-8")
            self.assert_validation_code(
                workspace,
                "letter_claim_not_externally_verified",
                "output_uses_unsafe_claim",
            )

    def test_N40_run_history_integrity_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            total = self.total_path(workspace)
            lines = total.read_text(encoding="utf-8").splitlines()
            heading = lines.index("## 9. 版本与同步记录")
            row_index = next(
                i
                for i in range(heading + 1, len(lines))
                if lines[i].startswith("| 20")
            )
            cells = lines[row_index].split("|")
            cells[2] = " 9 "
            lines[row_index] = "|".join(cells)
            total.write_text("\n".join(lines) + "\n", encoding="utf-8")
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertTrue(any(code.startswith("run_history_") for code in codes), sorted(codes))

    def test_N41_terminal_gap_requires_actionable_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            institution = self.institution_path(workspace)
            self.replace_line(institution, "module_status:", 'module_status: "partial"')
            total = self.total_path(workspace)

            def mutate(row: str) -> str:
                cells = row.split("|")
                cells[4] = " partial "
                cells[14] = " 无 "
                return "|".join(cells)

            self.alter_status_row(total, "机构研究", mutate)
            self.replace_line(total, "workflow_stage:", 'workflow_stage: "review"')
            self.assert_validation_code(workspace, "terminal_gap_missing")

    def test_N42_initializer_transaction_removes_new_files_on_postflight_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root / "intakes", "事务回滚医院", "briefing")
            args = initializer.build_parser().parse_args(
                [
                    "事务回滚医院",
                    "--output-root",
                    str(root),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(intake),
                    "--modules",
                    "institution",
                ]
            )
            with mock.patch.object(
                initializer,
                "validate_workspace_postflight",
                side_effect=RuntimeError("forced initializer postflight failure"),
            ):
                with self.assertRaises(RuntimeError):
                    initializer.initialize(args)
            self.assertFalse(list(root.glob("客户研究-*")))

    def test_N43_new_workspace_requires_time_basis(self):
        with tempfile.TemporaryDirectory() as temporary:
            intake = write_intake(Path(temporary) / "intakes", "行为测试医院", "briefing")
            result = run_python(
                "init_workspace.py",
                [
                    "行为测试医院",
                    "--output-root",
                    temporary,
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(intake),
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--task-timezone", result.stderr)
            self.assertIn("--evidence-cutoff-date", result.stderr)

    def test_N44_letter_context_fields_must_be_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            self.remove_frontmatter_key(letter, "recipient_role")
            self.assert_validation_code(
                workspace, "approval_metadata_required", "letter_context_unresolved"
            )

    def test_N45_strategy_context_fields_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary) / "output")
            strategy = next(workspace.glob("*交流策略与议题设计.md"))
            self.remove_frontmatter_key(strategy, "visit_objective")
            self.assert_validation_code(
                workspace, "strategy_context_required", "strategy_context_unresolved"
            )

    def test_N46_refresh_cannot_be_forged_as_first_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.initialize(Path(temporary), "--modules", "institution")
            total = self.total_path(workspace)
            text = total.read_text(encoding="utf-8")
            text = text.replace('route: "visit_prep"', 'route: "refresh"', 1)
            text = text.replace("route=visit_prep;", "route=refresh;", 1)
            total.write_text(text, encoding="utf-8")
            self.assert_validation_code(
                workspace, "refresh_not_resume", "refresh_first_run_invalid", strict=True
            )

    def test_N47_letter_review_history_must_exist_and_track_latest_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            text = letter.read_text(encoding="utf-8")
            letter.write_text(
                text[: text.index("## 4. 版本与审核记录（严禁外发）")],
                encoding="utf-8",
            )
            returncode, codes = self.validate_codes(workspace)
            self.assertEqual(returncode, 1)
            self.assertTrue(
                any(code.startswith("letter_review_history_") for code in codes),
                sorted(codes),
            )

    def test_N48_stale_output_cannot_remain_pending_or_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            letter = self.letter_path(workspace)
            self.replace_line(letter, "freshness_status:", 'freshness_status: "stale"')
            self.assert_validation_code(workspace, "output_review_freshness_conflict")

    def test_N49_external_artifact_action_is_generated_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self.build_emitted_letter_workspace(Path(temporary) / "output")
            total = self.total_path(workspace)
            self.alter_status_row(
                total,
                "客户信外发版",
                lambda row: row.replace("| true | generated |", "| true | created |", 1),
            )
            self.assert_validation_code(
                workspace,
                "external_run_action_invalid",
                "run_history_external_action_invalid",
            )

    def test_N50_approval_context_change_blocks_emit_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            self.review_and_approve_letter(workspace, "n50")
            record_external_request(workspace, event_id="context-drift-request")
            letter = self.letter_path(workspace)
            self.replace_line(letter, "letter_purpose:", 'letter_purpose: "已被篡改的目的"')
            before = self.sha256_map(workspace)
            result = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--emit-external",
                    "--actor-id",
                    "requester-wang",
                    "--request-event-id",
                    "context-drift-request",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 1)
            codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
            self.assertIn("approval_context_drift", codes)
            self.assertEqual(self.sha256_map(workspace), before)
            self.assertFalse(list(workspace.glob("*客户信（外发版）.md")))

    def test_N51_refresh_modules_are_rejected_for_new_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            intake = write_intake(
                Path(temporary) / "intakes",
                "行为测试医院",
                "strategic_account",
            )
            result = run_python(
                "init_workspace.py",
                [
                    "行为测试医院",
                    "--output-root",
                    temporary,
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "strategic_account",
                    "--intake-input",
                    str(intake),
                    "--modules",
                    "institution,strategy",
                    "--refresh-modules",
                    "institution",
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r"refresh-modules|续建|新建")

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
            self.assertRegex(result.stderr, r"file-map.*禁用|candidate-workspace")
            self.assertFalse((workspace.parent / "escaped.md").exists())

    def test_internal_selection_without_authorization_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root / "intakes", "行为测试医院", "standard_visit")
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
                    "--intake-input",
                    str(intake),
                    "--modules",
                    "internal",
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
