from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.common import run_python, runtime_tx as tx
from tests.fixture_builder import _rebuild_manifest, _replace_frontmatter, build_pending_strategy_workspace


def body_from_text(text: str) -> str:
    lines = text.splitlines()
    end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    return "\n".join(lines[end + 1 :]).strip()


def split_table_cells(line: str) -> list[str]:
    raw = line.strip().strip("|")
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", raw)]


def new_run(total_metadata: dict[str, str]) -> tuple[str, str]:
    prior = datetime.fromisoformat(total_metadata["updated_at"].replace("Z", "+00:00"))
    instant = max(datetime.now(timezone.utc).replace(microsecond=0), prior)
    timestamp = instant.isoformat().replace("+00:00", "Z")
    run_id = f"dcr-{instant.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}"
    return run_id, timestamp


class CandidateBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = build_pending_strategy_workspace(self.root / "live")
        self.total_path = next(self.workspace.glob("*客户研究与拜访准备报告.md"))
        self.strategy_path = next(self.workspace.glob("*交流策略与议题设计.md"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def payload(self) -> dict:
        revision, digest = tx.manifest_state(self.workspace)
        total = tx.parse_frontmatter(self.total_path.read_text(encoding="utf-8"))
        strategy_text = self.strategy_path.read_text(encoding="utf-8")
        strategy = tx.parse_frontmatter(strategy_text)
        run_id, timestamp = new_run(total)
        return {
            "schema": "discovery-call-candidate-run/v1",
            "context_id": total["context_id"],
            "expected_manifest_revision": revision,
            "expected_manifest_sha256": digest,
            "run": {
                "run_id": run_id,
                "updated_at": timestamp,
                "evidence_cutoff_date": total["evidence_cutoff_date"],
                "runtime_owner": "候选构建负责人",
                "workflow_stage": "review",
                "module_status": "completed",
                "freshness_status": "current",
                "objective": "形成标准拜访候选成果",
            },
            "artifacts": [
                {
                    "artifact_type": "institution_research",
                    "action": "reused",
                    "key_claim_ids": "CLM-I-001",
                },
                {
                    "artifact_type": "leader_research",
                    "action": "reused",
                    "key_claim_ids": "CLM-L-001",
                },
                {
                    "artifact_type": "visit_strategy",
                    "action": "updated",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "connector_status": "not_applicable",
                    "body": body_from_text(strategy_text) + "\n\n候选构建器已同步本轮审计状态。",
                    "metadata": {
                        "target_contact_level": strategy["target_contact_level"],
                        "visit_objective": strategy["visit_objective"],
                        "minimum_next_step": strategy["minimum_next_step"],
                    },
                    "key_claim_ids": "CLM-I-001, CLM-L-001",
                    "summary_sync_status": "synced",
                    "downstream_invalidation": "none",
                    "gaps_blockers": "无",
                },
            ],
        }

    def run_builder(self, payload: dict, *, output_name: str = "candidates"):
        payload_path = self.root / f"payload-{uuid.uuid4().hex}.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return run_python(
            "build_candidate.py",
            [
                str(self.workspace),
                "--payload",
                str(payload_path),
                "--output-root",
                str(self.root / output_name),
                "--json",
            ],
        )

    def test_builds_isolated_valid_candidate_and_commit_parameters(self):
        live_hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.workspace.glob("*.md")
        }
        payload = self.payload()
        result = self.run_builder(payload)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        candidate = Path(output["candidate_workspace"])
        self.assertTrue(candidate.is_dir())
        self.assertEqual(candidate.name, self.workspace.name)
        self.assertEqual(output["validation"]["errors"], 0)
        self.assertEqual(
            {item["artifact_type"] for item in output["diff"]},
            {"comprehensive_report", "visit_strategy"},
        )
        self.assertEqual(
            live_hashes,
            {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.workspace.glob("*.md")
            },
            "candidate构建不得修改正式workspace",
        )

        candidate_total = next(candidate.glob("*客户研究与拜访准备报告.md"))
        total_text = candidate_total.read_text(encoding="utf-8")
        total_meta = tx.parse_frontmatter(total_text)
        self.assertEqual(total_meta["latest_run_id"], payload["run"]["run_id"])
        candidate_manifest = json.loads(
            (candidate / "runtime" / "manifest.json").read_text(encoding="utf-8")
        )
        evidence_run = json.loads(
            (candidate / "runtime" / "evidence-manifest.json").read_text(encoding="utf-8")
        )["run_id"]
        self.assertEqual(candidate_manifest["evidence_run_id"], evidence_run)
        self.assertNotEqual(evidence_run, total_meta["latest_run_id"])
        self.assertEqual(total_meta["ready_for_use"], "false")
        status_lines = [
            line
            for line in total_text.splitlines()
            if any(line.startswith(f"| {label} |") for label in ("机构研究", "人物研究", "内部检索", "交流策略", "客户信内部审核稿", "客户信外发版"))
        ]
        self.assertEqual(len(status_lines), 6)
        self.assertTrue(all(len(split_table_cells(line)) == 15 for line in status_lines))
        self.assertIn(payload["run"]["run_id"], total_text)

        parameters = output["next_commit"]["parameters"]
        revision, digest = tx.manifest_state(self.workspace)
        self.assertEqual(parameters["expected_manifest_revision"], revision)
        self.assertEqual(parameters["expected_manifest_sha256"], digest)
        self.assertEqual(parameters["candidate_workspace"], str(candidate))

        committed = subprocess.run(
            output["next_commit"]["argv"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(committed.returncode, 0, committed.stderr or committed.stdout)
        live_total = tx.parse_frontmatter(self.total_path.read_text(encoding="utf-8"))
        self.assertEqual(live_total["latest_run_id"], payload["run"]["run_id"])

    def test_changed_artifact_clears_legacy_approval(self):
        strategy_text = self.strategy_path.read_text(encoding="utf-8")
        strategy = tx.parse_frontmatter(strategy_text)
        approved = _replace_frontmatter(
            strategy_text,
            {
                "review_status": "approved",
                "reviewer": "历史审核人（人物事实岗）",
                "reviewed_at": strategy["updated_at"],
                "reviewed_content_version": strategy["content_version"],
                "reviewed_body_sha256": "f" * 64,
            },
        )
        approved = approved + "\n" + body_from_text(strategy_text) + "\n"
        self.strategy_path.write_text(approved, encoding="utf-8")
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])

        payload = self.payload()
        result = self.run_builder(payload, output_name="approval-reset")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        candidate = Path(json.loads(result.stdout)["candidate_workspace"])
        strategy_candidate = next(candidate.glob("*交流策略与议题设计.md"))
        metadata = tx.parse_frontmatter(strategy_candidate.read_text(encoding="utf-8"))
        self.assertEqual(metadata["review_status"], "pending")
        for field in ("reviewer", "reviewed_at", "reviewed_content_version", "reviewed_body_sha256"):
            self.assertEqual(metadata[field], "")

    def test_rejects_stale_manifest_and_context_without_candidate(self):
        stale = self.payload()
        stale["expected_manifest_revision"] += 1
        result = self.run_builder(stale, output_name="stale")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CAS", result.stderr)
        self.assertFalse((self.root / "stale").exists())

        wrong_context = self.payload()
        wrong_context["context_id"] = "dcx-20260827-AAAAAAAA"
        result = self.run_builder(wrong_context, output_name="wrong-context")
        self.assertEqual(result.returncode, 2)
        self.assertIn("context_id", result.stderr)
        self.assertFalse(any((self.root / "wrong-context").glob("candidate-*")))

    def test_commit_rejects_tampered_candidate_receipt_binding(self):
        result = self.run_builder(self.payload(), output_name="tampered-receipt")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        marker_path = Path(output["candidate_workspace"]) / "runtime" / "candidate-receipt.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["payload_sha256"] = "0" * 64
        marker_path.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        committed = subprocess.run(
            output["next_commit"]["argv"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(committed.returncode, 2)
        self.assertIn("未绑定当前candidate manifest", committed.stderr)

    def test_candidate_rejects_missing_source_capture_receipt(self):
        evidence_path = self.workspace / "runtime" / "evidence-manifest.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        next(iter(evidence["sources"].values())).pop("capture_receipt")
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        result = run_python(
            "validate_outputs.py",
            [str(self.workspace), "--profile", "candidate", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("source_capture_receipt_missing", codes)

    def test_candidate_rejects_tampered_source_capture_receipt(self):
        evidence_path = self.workspace / "runtime" / "evidence-manifest.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        receipt = next(iter(evidence["sources"].values()))["capture_receipt"]
        receipt["content_sha256"] = "b" * 64
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        result = run_python(
            "validate_outputs.py",
            [str(self.workspace), "--profile", "candidate", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("source_capture_receipt_invalid", codes)

    def test_candidate_rejects_expired_persisted_intake_receipt(self):
        manifest_path = self.workspace / "runtime" / "manifest.json"
        plan_path = self.workspace / "runtime" / "search-plan.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        manifest["intake_preflight"]["expires_at"] = "2000-01-01T00:00:00Z"
        plan["intake_preflight"]["expires_at"] = "2000-01-01T00:00:00Z"
        tx.atomic_write_json(manifest_path, manifest)
        tx.atomic_write_json(plan_path, plan)
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        result = run_python(
            "validate_outputs.py",
            [str(self.workspace), "--profile", "candidate", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("intake_preflight_expired", codes)

    def test_candidate_rejects_future_claim_ttl_anchor(self):
        evidence_path = self.workspace / "runtime" / "evidence-manifest.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        claim = next(iter(evidence["claims"].values()))
        future = datetime.now(timezone.utc) + timedelta(days=30)
        claim["evidence_anchor_at"] = future.isoformat().replace("+00:00", "Z")
        claim["verified_at"] = (future + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        claim["expires_at"] = (future + timedelta(days=claim["ttl_days"])).isoformat().replace("+00:00", "Z")
        tx.atomic_write_json(evidence_path, evidence)
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        result = run_python("validate_outputs.py", [str(self.workspace), "--profile", "candidate", "--json"])
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("claim_anchor_in_future", codes)
        self.assertIn("claim_verified_in_future", codes)

    def test_candidate_rejects_malformed_or_missing_machine_bundle(self):
        plan_path = self.workspace / "runtime" / "search-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan.pop("generated_at")
        tx.atomic_write_json(plan_path, plan)
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        malformed = run_python("validate_outputs.py", [str(self.workspace), "--profile", "candidate", "--json"])
        self.assertEqual(malformed.returncode, 1)
        malformed_codes = {issue["code"] for issue in json.loads(malformed.stdout)["issues"]}
        self.assertIn("runtime_machine_contract_invalid", malformed_codes)

        for name in ("search-plan.json", "source-cache.json", "evidence-manifest.json", "run-metrics.json"):
            (self.workspace / "runtime" / name).unlink()
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        missing = run_python("validate_outputs.py", [str(self.workspace), "--profile", "candidate", "--json"])
        self.assertEqual(missing.returncode, 1)
        missing_codes = {issue["code"] for issue in json.loads(missing.stdout)["issues"]}
        self.assertIn("runtime_machine_set_incomplete", missing_codes)

    def test_rejects_external_or_self_asserted_approval_fields(self):
        external = self.payload()
        external["artifacts"][1]["artifact_type"] = "customer_letter_external"
        result = self.run_builder(external, output_name="external")
        self.assertEqual(result.returncode, 2)
        self.assertIn("不允许", result.stderr)

        approval = self.payload()
        strategy = next(
            item for item in approval["artifacts"] if item["artifact_type"] == "visit_strategy"
        )
        strategy["metadata"]["reviewer"] = "AI"
        result = self.run_builder(approval, output_name="approval")
        self.assertEqual(result.returncode, 2)
        self.assertIn("不可写字段", result.stderr)

    def test_rejects_cross_variant_strategy_metadata(self):
        for variant, forbidden_field in (
            ("scheduled_visit", "strategic_question"),
            ("account_planning", "target_contact_level"),
        ):
            with self.subTest(variant=variant):
                payload = self.payload()
                strategy = next(
                    item
                    for item in payload["artifacts"]
                    if item["artifact_type"] == "visit_strategy"
                )
                strategy["metadata"]["strategy_variant"] = variant
                strategy["metadata"][forbidden_field] = "不应进入当前分支"
                result = self.run_builder(
                    payload,
                    output_name=f"cross-variant-{variant}",
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(forbidden_field, result.stderr)
                self.assertIn(variant, result.stderr)

    def test_candidate_rejects_search_plan_strategy_variant_drift(self):
        plan_path = self.workspace / "runtime" / "search-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["strategy_variant"], "scheduled_visit")
        plan["strategy_variant"] = "account_planning"
        tx.atomic_write_json(plan_path, plan)
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])

        result = run_python(
            "validate_outputs.py",
            [str(self.workspace), "--profile", "candidate", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("search_plan_strategy_variant_drift", codes)

    def test_candidate_rejects_manifest_strategy_variant_drift(self):
        manifest_path = self.workspace / "runtime" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        strategy_record = manifest["artifacts"]["visit_strategy"]
        self.assertEqual(strategy_record["strategy_variant"], "scheduled_visit")
        strategy_record["strategy_variant"] = "account_planning"
        tx.atomic_write_json(manifest_path, manifest)

        result = run_python(
            "validate_outputs.py",
            [str(self.workspace), "--profile", "candidate", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("runtime_manifest_strategy_variant_drift", codes)
        self.assertIn("search_plan_strategy_variant_drift", codes)


if __name__ == "__main__":
    unittest.main()
