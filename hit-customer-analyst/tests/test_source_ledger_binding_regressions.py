from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.common import load_json, run_python, runtime_tx as tx
from tests.fixture_builder import (
    _install_machine_bundle,
    _rebuild_manifest,
    build_pending_strategy_workspace,
    record_action_assertion,
)


def workspace_hashes(workspace: Path) -> dict[str, str]:
    return {
        str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in workspace.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class SourceLedgerBindingRegressionTests(unittest.TestCase):
    def assert_profiles_block_three_times(
        self,
        workspace: Path,
        expected_codes: set[str],
    ) -> None:
        baseline = workspace_hashes(workspace)
        for attempt in range(1, 4):
            for profile in ("candidate", "release"):
                with self.subTest(attempt=attempt, profile=profile):
                    result = run_python(
                        "validate_outputs.py",
                        [str(workspace), "--profile", profile, "--json"],
                    )
                    self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                    payload = json.loads(result.stdout)
                    codes = {issue["code"] for issue in payload["issues"]}
                    self.assertTrue(expected_codes & codes, (expected_codes, codes))
                    self.assertEqual(workspace_hashes(workspace), baseline)

    def test_N122_claim_source_receipt_and_f2_bindings_fail_closed_three_times(self):
        locator_variants = {
            "markdown_commitment": (
                "[承诺三个月上线](https://example.org/hospital/profile)",
                {"source_ledger_markup_forbidden", "source_locator_machine_drift"},
            ),
            "markdown_href_swap": (
                "[https://example.org/hospital/profile](https://safe.example.net/other)",
                {"source_ledger_markup_forbidden", "source_locator_machine_drift"},
            ),
            "raw_locator_swap": (
                "https://safe.example.net/forged",
                {"source_ledger_machine_drift", "source_locator_machine_drift"},
            ),
        }
        for name, (replacement, expected) in locator_variants.items():
            with self.subTest(variant=name), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                institution = next(workspace.glob("*机构研究报告.md"))
                text = institution.read_text(encoding="utf-8")
                institution.write_text(
                    text.replace(
                        "https://example.org/hospital/profile",
                        replacement,
                        1,
                    ),
                    encoding="utf-8",
                )
                _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
                self.assert_profiles_block_three_times(workspace, expected)

        claim_variants = {
            "claim_text": (
                "| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 |",
                "| CLM-I-001 | F | public | verified_single | 示例医院承诺三个月上线 |",
                {"claim_ledger_machine_drift"},
            ),
            "support_ref_smuggling": (
                "SRC-I-001 | 无 | 高",
                "SRC-I-001；客户已承诺采购 | 无 | 高",
                {"claim_support_refs_invalid", "claim_ledger_machine_drift"},
            ),
        }
        for name, (old, new, expected) in claim_variants.items():
            with self.subTest(variant=name), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                institution = next(workspace.glob("*机构研究报告.md"))
                text = institution.read_text(encoding="utf-8")
                self.assertIn(old, text)
                institution.write_text(text.replace(old, new, 1), encoding="utf-8")
                _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
                self.assert_profiles_block_three_times(workspace, expected)

        with self.subTest(variant="machine_and_markdown_title_with_old_receipt"), tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            institution = next(workspace.glob("*机构研究报告.md"))
            text = institution.read_text(encoding="utf-8")
            institution.write_text(
                text.replace("示例医院官网简介", "承诺三个月上线", 1),
                encoding="utf-8",
            )
            evidence_path = workspace / "runtime" / "evidence-manifest.json"
            evidence = load_json(evidence_path)
            evidence["sources"]["SRC-I-001"]["source_title"] = "承诺三个月上线"
            tx.atomic_write_json(evidence_path, evidence)
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            self.assert_profiles_block_three_times(
                workspace,
                {"source_capture_receipt_invalid", "source_cache_binding_missing"},
            )

        with self.subTest(variant="f2_markdown_independence_cannot_override_signed_lineage"), tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            institution = next(workspace.glob("*机构研究报告.md"))
            text = institution.read_text(encoding="utf-8")
            text = text.replace(
                "| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001 | 无 | 高 | 用于拜访主体确认 |",
                "| CLM-I-001 | F2 | public | corroborated | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001, SRC-I-002 | 无 | 高 | 用于拜访主体确认 |",
                1,
            )
            first_row = "| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | none | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |"
            second_row = "| SRC-I-002 | 示例医院官网公告 | 示例医院 | https://example.org/hospital/profile-2 | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | none | sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc | official:example-hospital | true |"
            self.assertIn(first_row, text)
            institution.write_text(text.replace(first_row, first_row + "\n" + second_row, 1), encoding="utf-8")
            _install_machine_bundle(workspace, ["institution", "leader", "strategy"])
            signed_text = institution.read_text(encoding="utf-8")
            forged_row = second_row.replace(
                "| official-site |",
                "| independent-site |",
                1,
            ).replace(
                "| official:example-hospital |",
                "| independent:publisher |",
                1,
            )
            institution.write_text(signed_text.replace(second_row, forged_row, 1), encoding="utf-8")
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            self.assert_profiles_block_three_times(
                workspace,
                {
                    "source_ledger_machine_drift",
                    "fact2_source_groups_not_independent",
                    "fact2_upstream_not_independent",
                    "fact2_sources_not_fourfold_independent",
                },
            )

    def test_N122_canonical_signed_and_independently_reviewed_release_passes_three_times(self):
        from tests.test_delivery_structure_regressions import DeliveryStructureRegressionTests

        for repetition in range(1, 4):
            with self.subTest(repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                payload = DeliveryStructureRegressionTests(
                    methodName="runTest"
                ).complete_strategic_release(workspace)
                self.assertEqual(payload["validation_profile"], "release")
                self.assertEqual(payload["deliverable_state"], "release_ready")

    def test_N122_self_consistent_fabricated_claim_still_requires_independent_review_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            institution = next(workspace.glob("*机构研究报告.md"))
            text = institution.read_text(encoding="utf-8")
            old = "| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 |"
            new = "| CLM-I-001 | F | public | verified_single | 示例医院已承诺三个月上线 |"
            self.assertIn(old, text)
            institution.write_text(text.replace(old, new, 1), encoding="utf-8")
            # Rebuild a fully self-consistent candidate machine bundle.  This
            # proves the candidate seal/record equality is only integrity, not
            # semantic evidence review.
            _install_machine_bundle(workspace, ["institution", "leader", "strategy"])
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            candidate_baseline = workspace_hashes(workspace)
            for attempt in range(1, 4):
                with self.subTest(stage="candidate", attempt=attempt):
                    result = run_python(
                        "validate_outputs.py",
                        [str(workspace), "--profile", "candidate", "--json"],
                    )
                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                    self.assertEqual(workspace_hashes(workspace), candidate_baseline)

            def govern(*args: str) -> None:
                result = run_python("validate_outputs.py", [str(workspace), *args, "--json"])
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            for event_id, actor_id, operation, artifact_type, target, reviewer in (
                (
                    "approve-leader",
                    "reviewer-leader",
                    "approve_artifact:leader",
                    "leader_research",
                    "leader",
                    "孙宁（人物事实审核岗）",
                ),
                (
                    "approve-strategy",
                    "reviewer-strategy",
                    "approve_artifact:strategy",
                    "visit_strategy",
                    "strategy",
                    "钱琳（拜访策略审核岗）",
                ),
            ):
                record_action_assertion(
                    workspace,
                    event_id=event_id,
                    actor_id=actor_id,
                    operation=operation,
                    artifact_type=artifact_type,
                )
                govern(
                    "--approve-artifact",
                    target,
                    "--reviewer",
                    reviewer,
                    "--actor-id",
                    actor_id,
                    "--action-event-id",
                    event_id,
                )

            record_action_assertion(
                workspace,
                event_id="ready-strategic",
                actor_id="ready-strategic",
                operation="mark_ready:strategic_account",
                artifact_type="comprehensive_report",
            )
            blocked_baseline = workspace_hashes(workspace)
            for attempt in range(1, 4):
                with self.subTest(stage="mark_ready", attempt=attempt):
                    result = run_python(
                        "validate_outputs.py",
                        [
                            str(workspace),
                            "--mark-ready",
                            "--reviewer",
                            "刘宁（战略账户责任岗）",
                            "--actor-id",
                            "ready-strategic",
                            "--action-event-id",
                            "ready-strategic",
                            "--json",
                        ],
                    )
                    self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                    payload = json.loads(result.stdout)
                    operation_messages = [
                        issue["message"]
                        for issue in payload["issues"]
                        if issue["code"] == "operation_failed"
                    ]
                    self.assertTrue(operation_messages, payload)
                    self.assertIn("institution_research", "\n".join(operation_messages))
                    self.assertEqual(workspace_hashes(workspace), blocked_baseline)
                with self.subTest(stage="release", attempt=attempt):
                    result = run_python(
                        "validate_outputs.py",
                        [str(workspace), "--profile", "release", "--json"],
                    )
                    self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                    payload = json.loads(result.stdout)
                    self.assertIn(
                        "research_fact_review_required",
                        {issue["code"] for issue in payload["issues"]},
                    )
                    self.assertEqual(workspace_hashes(workspace), blocked_baseline)

    def test_N122_signed_fourfold_independent_f2_passes_three_times_and_release(self):
        from tests.test_delivery_structure_regressions import DeliveryStructureRegressionTests

        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            institution = next(workspace.glob("*机构研究报告.md"))
            text = institution.read_text(encoding="utf-8")
            text = text.replace(
                "| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001 | 无 | 高 | 用于拜访主体确认 |",
                "| CLM-I-001 | F2 | public | corroborated | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001, SRC-I-002 | 无 | 高 | 用于拜访主体确认 |",
                1,
            )
            first_row = "| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | none | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |"
            second_row = "| SRC-I-002 | 市级公开项目公告 | 市级主管部门 | https://example.net/public/project-2 | 2026-08-24 | 2026-08-26 | A | government-project | public | 示例医院 | none | sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc | government:project-2 | true |"
            self.assertIn(first_row, text)
            institution.write_text(text.replace(first_row, first_row + "\n" + second_row, 1), encoding="utf-8")
            _install_machine_bundle(workspace, ["institution", "leader", "strategy"])
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            baseline = workspace_hashes(workspace)
            for attempt in range(1, 4):
                with self.subTest(attempt=attempt):
                    result = run_python(
                        "validate_outputs.py",
                        [str(workspace), "--profile", "candidate", "--json"],
                    )
                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                    self.assertEqual(workspace_hashes(workspace), baseline)
            released = DeliveryStructureRegressionTests(
                methodName="runTest"
            ).complete_strategic_release(workspace)
            self.assertEqual(released["deliverable_state"], "release_ready")


if __name__ == "__main__":
    unittest.main()
