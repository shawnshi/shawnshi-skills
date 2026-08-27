from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.common import (
    SKILL_ROOT,
    load_json,
    research_plan as rp,
    run_python,
    runtime_tx as tx,
    write_intake,
)
from tests.fixture_builder import (
    _replace_frontmatter,
    _source_capture_receipt,
    build_pending_strategy_workspace,
)

import capability_receipt as cr


class CapabilityReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.private_key = Ed25519PrivateKey.generate()
        public_raw = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.trust_env = json.dumps(
            {"corp-iam": {"cap-key-1": base64.b64encode(public_raw).decode("ascii")}},
            separators=(",", ":"),
        )
        self.expected = {
            "receipt_id": "receipt-001",
            "actor_id": "employee-001",
            "run_id": "dcr-20260827T080000-Ab12",
            "connector_id": "ragflow-prod",
            "operation": "internal_read",
            "tenant_id": "tenant-demo",
            "customer_id": "customer-demo",
            "project_id": "project-demo",
            "allowed_project_ids": ["project-demo"],
            "authorization_owner": "data-owner-001",
            "authorization_expires_at": (self.now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "authorized_roots": ["customer/project-demo"],
            "allowed_dataset_aliases": ["project-memory"],
            "allowed_confidentiality": ["internal-authorized"],
            "authorization_purpose": "准备本次客户拜访",
        }

    def envelope(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": cr.RECEIPT_SCHEMA,
            "issuer": "corp-iam",
            "audience": cr.RECEIPT_AUDIENCE,
            "key_id": "cap-key-1",
            "issued_at": (self.now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (self.now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
            **self.expected,
        }
        value.update(overrides)
        signed = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        value["signature"] = base64.b64encode(self.private_key.sign(signed)).decode("ascii")
        return value

    def write_receipt(self, directory: Path, **overrides: object) -> Path:
        path = directory / "host-receipt.json"
        path.write_text(json.dumps(self.envelope(**overrides), ensure_ascii=False), encoding="utf-8")
        return path

    def test_valid_host_receipt_is_verified_without_private_key_artifact(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False
        ):
            path = self.write_receipt(Path(temporary))
            verified = cr.verify_capability_receipt(path, expected=self.expected, at=self.now)
            self.assertEqual(verified.receipt_id, self.expected["receipt_id"])
            self.assertEqual(verified.actor_id, self.expected["actor_id"])
            self.assertRegex(verified.receipt_sha256, r"^[0-9a-f]{64}$")
            self.assertFalse(any("private" in item.name.casefold() for item in Path(temporary).iterdir()))

    def test_missing_trust_key_signature_and_expiry_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_receipt(root)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(cr.CapabilityReceiptError):
                    cr.verify_capability_receipt(path, expected=self.expected, at=self.now)

            missing_signature = self.envelope()
            del missing_signature["signature"]
            path.write_text(json.dumps(missing_signature, ensure_ascii=False), encoding="utf-8")
            with patch.dict(os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False):
                with self.assertRaises(cr.CapabilityReceiptError):
                    cr.verify_capability_receipt(path, expected=self.expected, at=self.now)

            path.write_text(
                json.dumps(
                    self.envelope(
                        issued_at=(self.now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                        expires_at=(self.now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False):
                with self.assertRaises(cr.CapabilityReceiptError):
                    cr.verify_capability_receipt(path, expected=self.expected, at=self.now)

    def test_every_authority_dimension_is_bound(self):
        mismatches = {
            "actor_id": "employee-999",
            "run_id": "dcr-20260827T080001-Zz99",
            "connector_id": "other-connector",
            "operation": "internal_write",
            "tenant_id": "tenant-other",
            "customer_id": "customer-other",
            "project_id": "project-other",
            "allowed_project_ids": ["project-other"],
            "authorized_roots": ["other/root"],
            "allowed_dataset_aliases": ["winning-product"],
            "allowed_confidentiality": ["restricted"],
            "authorization_purpose": "其他用途",
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False
        ):
            path = self.write_receipt(Path(temporary))
            for field, bad_value in mismatches.items():
                with self.subTest(field=field):
                    expected = dict(self.expected)
                    expected[field] = bad_value
                    with self.assertRaises(cr.CapabilityReceiptError):
                        cr.verify_capability_receipt(path, expected=expected, at=self.now)

    def test_tampered_signed_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False
        ):
            path = self.write_receipt(Path(temporary))
            value = json.loads(path.read_text(encoding="utf-8"))
            value["authorized_roots"] = ["other/root"]
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(cr.CapabilityReceiptError):
                cr.verify_capability_receipt(path, expected=self.expected, at=self.now)

    def _plan_args(self) -> dict[str, object]:
        return {
            "business_mode": "standard_visit",
            "context_id": "dcx-20260827-Abcd1234",
            "run_id": self.expected["run_id"],
            "customer_name": "示例医院",
            "customer_id": self.expected["customer_id"],
            "organization_scope": "示例医院主院区",
            "project_id": self.expected["project_id"],
            "tenant_id": self.expected["tenant_id"],
            "allowed_project_ids": self.expected["allowed_project_ids"],
            "authorization_expires_at": self.expected["authorization_expires_at"],
            "authorization_owner": self.expected["authorization_owner"],
            "connector_id": self.expected["connector_id"],
            "authorized_roots": self.expected["authorized_roots"],
            "allowed_dataset_aliases": self.expected["allowed_dataset_aliases"],
            "allowed_confidentiality": self.expected["allowed_confidentiality"],
            "authorization_purpose": self.expected["authorization_purpose"],
            "capability_receipt_id": self.expected["receipt_id"],
            "authorization_actor_id": self.expected["actor_id"],
            "selected_modules": ["institution", "leader", "strategy", "internal"],
            "business_fields": {
                "customer_name": "示例医院",
                "organization_scope": "示例医院主院区",
                "target_contact_level": "信息中心主任",
                "visit_objective": "确认年度建设重点",
                "minimum_next_step": "安排专题方案交流",
            },
            "generated_at": self.now,
        }

    def test_self_reported_id_cannot_ready_or_generate_internal_query(self):
        plan = rp.build_search_plan(**self._plan_args())
        self.assertFalse(plan["planning_ready"])
        self.assertTrue(plan["internal_queries_suppressed"])
        self.assertIn("capability_receipt_verified", plan["gate_results"]["failed"])
        self.assertFalse(any(query["channel"] == "internal" for query in plan["queries"]))

    def test_signed_exact_receipt_enables_internal_plan(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False
        ):
            path = self.write_receipt(Path(temporary))
            plan = rp.build_search_plan(**self._plan_args(), capability_receipt_file=path)
            self.assertTrue(plan["planning_ready"], plan["gate_results"])
            self.assertFalse(plan["internal_queries_suppressed"])
            self.assertTrue(any(query["channel"] == "internal" for query in plan["queries"]))
            audit = plan["authorization_context"]
            self.assertTrue(audit["capability_receipt_verified"])
            self.assertEqual(audit["authorization_actor_id"], self.expected["actor_id"])

    def test_initializer_records_only_verified_receipt_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            intake = write_intake(root, "示例医院", "standard_visit", organization_scope="示例医院主院区")
            intake_payload = load_json(intake)
            intake_payload["candidate_sets"].append(
                {
                    "field": "project_id",
                    "candidates": [
                        {
                            "candidate_id": "project-1",
                            "value": self.expected["project_id"],
                            "status": "asserted",
                            "source_ref": "test:user-turn:1",
                        }
                    ],
                }
            )
            intake.write_text(json.dumps(intake_payload, ensure_ascii=False), encoding="utf-8")
            receipt = self.write_receipt(root)
            arguments = [
                "示例医院",
                "--output-root", str(output),
                "--business-mode", "standard_visit",
                "--intake-input", str(intake),
                "--task-timezone", "Asia/Shanghai",
                "--context-id", "dcx-20260827-Abcd1234",
                "--run-id", str(self.expected["run_id"]),
                "--customer-id", str(self.expected["customer_id"]),
                "--organization-scope", "示例医院主院区",
                "--runtime-owner", "测试负责人",
                "--modules", "institution,leader,internal,strategy",
                "--tenant-id", str(self.expected["tenant_id"]),
                "--project-id", str(self.expected["project_id"]),
                "--allowed-project-ids", str(self.expected["project_id"]),
                "--authorization-owner", str(self.expected["authorization_owner"]),
                "--authorization-expires-at", str(self.expected["authorization_expires_at"]),
                "--authorization-purpose", str(self.expected["authorization_purpose"]),
                "--internal-connector-id", str(self.expected["connector_id"]),
                "--capability-receipt-id", str(self.expected["receipt_id"]),
                "--authorization-actor-id", str(self.expected["actor_id"]),
                "--capability-receipt-file", str(receipt),
                "--authorized-root", str(self.expected["authorized_roots"][0]),
                "--allowed-dataset-alias", str(self.expected["allowed_dataset_aliases"][0]),
                "--allowed-confidentiality", str(self.expected["allowed_confidentiality"][0]),
                "--json",
            ]
            result = run_python(
                "init_workspace.py",
                arguments,
                env={cr.TRUSTED_KEYS_ENV: self.trust_env},
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            workspace = Path(json.loads(result.stdout)["workspace"])
            authorization = load_json(workspace / "runtime" / "manifest.json")["authorization"]
            self.assertTrue(authorization["capability_receipt_verified"])
            self.assertEqual(authorization["authorization_actor_id"], self.expected["actor_id"])
            self.assertRegex(authorization["capability_receipt_sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(any(path.name == receipt.name for path in workspace.rglob("*")))

    def test_initializer_tampered_receipt_leaves_no_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            intake = write_intake(root, "示例医院", "standard_visit", organization_scope="示例医院主院区")
            receipt = self.write_receipt(root)
            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["actor_id"] = "employee-999"
            receipt.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            result = run_python(
                "init_workspace.py",
                [
                    "示例医院", "--output-root", str(output),
                    "--business-mode", "standard_visit", "--intake-input", str(intake),
                    "--task-timezone", "Asia/Shanghai", "--run-id", str(self.expected["run_id"]),
                    "--modules", "institution,leader,internal,strategy",
                    "--capability-receipt-id", str(self.expected["receipt_id"]),
                    "--authorization-actor-id", str(self.expected["actor_id"]),
                    "--capability-receipt-file", str(receipt), "--json",
                ],
                env={cr.TRUSTED_KEYS_ENV: self.trust_env},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("capability_receipt_invalid", result.stderr)
            self.assertFalse(any(path.is_dir() for path in output.iterdir()))

    def test_init_scope_a_candidate_b_signed_plan_no_hits_commit(self):
        """Prove the intended two-run authorization path is reachable.

        Init/resume run A establishes only stable scope.  Candidate and search
        plan run B consume a fresh host-signed B receipt; commit re-verifies the
        same receipt at the current time.  The first commit attempt deliberately
        omits the receipt while connector_status is still not_configured, proving
        that a locally self-reported verified flag cannot pass commit.
        """

        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False
        ):
            root = Path(temporary)
            live_root = root / "live"
            workspace = build_pending_strategy_workspace(live_root)
            total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
            before = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))

            intake = write_intake(
                root / "intake-a",
                "示例医院",
                "standard_visit",
                organization_scope=before["organization_scope"],
            )
            intake_payload = load_json(intake)
            intake_payload["candidate_sets"].append(
                {
                    "field": "project_id",
                    "candidates": [
                        {
                            "candidate_id": "project-a",
                            "value": "project-demo",
                            "status": "asserted",
                            "source_ref": "test:user-turn:1",
                        }
                    ],
                }
            )
            intake.write_text(json.dumps(intake_payload, ensure_ascii=False), encoding="utf-8")
            authorization_expires_at = (self.now + timedelta(minutes=10)).isoformat().replace(
                "+00:00", "Z"
            )
            initialized = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root", str(live_root),
                    "--context-id", before["context_id"],
                    "--resume",
                    "--business-mode", "standard_visit",
                    "--intake-input", str(intake),
                    "--runtime-owner", "测试负责人",
                    "--modules", "institution,leader,internal,strategy",
                    "--tenant-id", "tenant-demo",
                    "--project-id", "project-demo",
                    "--allowed-project-ids", "project-demo",
                    "--authorization-owner", "data-owner-001",
                    "--authorization-expires-at", authorization_expires_at,
                    "--authorization-purpose", "准备本次客户拜访",
                    "--internal-connector-id", "ragflow-prod",
                    "--authorized-root", "customer/project-demo",
                    "--allowed-dataset-alias", "project-memory",
                    "--allowed-confidentiality", "internal-authorized",
                    "--json",
                ],
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
            init_result = json.loads(initialized.stdout)
            run_a = init_result["latest_run_id"]
            live_manifest = load_json(workspace / "runtime" / "manifest.json")
            self.assertEqual(live_manifest["latest_run_id"], run_a)
            self.assertFalse(live_manifest["authorization"]["capability_receipt_verified"])
            self.assertEqual(live_manifest["authorization"]["capability_receipt_id"], "")

            prior = datetime.fromisoformat(
                tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))["updated_at"].replace("Z", "+00:00")
            )
            run_b_at = max(datetime.now(timezone.utc).replace(microsecond=0), prior)
            run_b = f"dcr-{run_b_at.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}"
            revision, digest = tx.manifest_state(workspace)
            internal_body = """
# 示例医院内部信息检索报告

## 1. 授权、连接与范围

本轮仅按已登记的租户、客户、项目、数据集、密级和用途范围准备检索；connector_status=not_configured，尚未调用连接器。

## 2. 命中摘要

尚未执行检索，因此不陈述命中或无命中结论。

## 3. 冲突与使用边界

内部资料不得自动升级为外部事实，且不得越出本次拜访准备用途。

## 4. 主张台账

本轮尚无内部主张。

## 5. 来源台账

本轮尚无内部来源记录。

## 6. 检索审计与下一步

等待宿主签发与候选run绑定的能力收据后执行检索；CRM/PIMS写回为not_requested。
"""
            payload = {
                "schema": "discovery-call-candidate-run/v1",
                "context_id": before["context_id"],
                "expected_manifest_revision": revision,
                "expected_manifest_sha256": digest,
                "run": {
                    "run_id": run_b,
                    "updated_at": run_b_at.isoformat().replace("+00:00", "Z"),
                    "evidence_cutoff_date": before["evidence_cutoff_date"],
                    "runtime_owner": "候选构建负责人",
                    "workflow_stage": "review",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "objective": "形成带内部检索的标准拜访候选成果",
                },
                "artifacts": [
                    {"artifact_type": "institution_research", "action": "reused", "key_claim_ids": "CLM-I-001"},
                    {"artifact_type": "leader_research", "action": "reused", "key_claim_ids": "CLM-L-001"},
                    {
                        "artifact_type": "internal_retrieval",
                        "action": "updated",
                        "module_status": "partial",
                        "freshness_status": "current",
                        "connector_status": "not_configured",
                        "body": internal_body,
                        "metadata": {},
                        "key_claim_ids": "",
                        "summary_sync_status": "synced",
                        "downstream_invalidation": "none",
                        "gaps_blockers": "等待本run授权后检索",
                    },
                    {"artifact_type": "visit_strategy", "action": "reused", "key_claim_ids": "CLM-I-001, CLM-L-001"},
                ],
            }
            payload_path = root / "candidate-b.json"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            built = run_python(
                "build_candidate.py",
                [
                    str(workspace),
                    "--payload", str(payload_path),
                    "--output-root", str(root / "candidates"),
                    "--json",
                ],
            )
            self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
            candidate = Path(json.loads(built.stdout)["candidate_workspace"])
            self.assertNotEqual(run_a, run_b)

            dynamic_expected = {
                "receipt_id": "receipt-run-b",
                "actor_id": "employee-run-b",
                "run_id": run_b,
                "connector_id": "ragflow-prod",
                "operation": "internal_read",
                "tenant_id": "tenant-demo",
                "customer_id": live_manifest["customer_id"],
                "project_id": "project-demo",
                "allowed_project_ids": ["project-demo"],
                "authorization_owner": "data-owner-001",
                "authorization_expires_at": authorization_expires_at,
                "authorized_roots": ["customer/project-demo"],
                "allowed_dataset_aliases": ["project-memory"],
                "allowed_confidentiality": ["internal-authorized"],
                "authorization_purpose": "准备本次客户拜访",
            }
            receipt = self.write_receipt(root, **dynamic_expected)
            candidate_manifest = load_json(candidate / "runtime" / "manifest.json")
            prior_evidence = load_json(candidate / "runtime" / "evidence-manifest.json")
            plan = rp.build_search_plan(
                business_mode="standard_visit",
                context_id=before["context_id"],
                run_id=run_b,
                customer_name="示例医院",
                customer_id=live_manifest["customer_id"],
                organization_scope=before["organization_scope"],
                project_id="project-demo",
                tenant_id="tenant-demo",
                allowed_project_ids=["project-demo"],
                authorization_expires_at=authorization_expires_at,
                authorization_owner="data-owner-001",
                connector_id="ragflow-prod",
                authorized_roots=["customer/project-demo"],
                allowed_dataset_aliases=["project-memory"],
                allowed_confidentiality=["internal-authorized"],
                authorization_purpose="准备本次客户拜访",
                capability_receipt_id="receipt-run-b",
                authorization_actor_id="employee-run-b",
                capability_receipt_file=receipt,
                selected_modules=candidate_manifest["selected_modules"],
                people=["张主任"],
                business_fields={
                    "customer_name": "示例医院",
                    "organization_scope": before["organization_scope"],
                    "target_contact_level": "信息中心主任",
                    "visit_objective": "核实客户核心任务",
                    "minimum_next_step": "确认下一次技术交流",
                },
                generated_at=run_b_at,
                intake_preflight=live_manifest["intake_preflight"],
            )
            self.assertTrue(plan["planning_ready"], plan["gate_results"])
            self.assertTrue(any(query["channel"] == "internal" for query in plan["queries"]))
            rp.RuntimeWorkspace(candidate, source_workspace=workspace).materialize(
                plan,
                project_id="project-demo",
                generated_at=run_b_at,
            )

            commit_base = [
                str(workspace),
                "--candidate-workspace", str(candidate),
                "--expected-manifest-revision", str(revision),
                "--expected-manifest-sha256", digest,
                "--json",
            ]
            locally_asserted = run_python(
                "commit_run.py",
                commit_base,
                env={cr.TRUSTED_KEYS_ENV: self.trust_env},
            )
            self.assertEqual(locally_asserted.returncode, 2)
            self.assertIn("--capability-receipt-file", locally_asserted.stderr)
            self.assertEqual(tx.manifest_state(workspace), (revision, digest))

            internal_path = next(candidate.glob("*内部信息检索报告.md"))
            internal_text = internal_path.read_text(encoding="utf-8")
            internal_text = _replace_frontmatter(internal_text, {"connector_status": "no_hits"})
            internal_text = internal_text.replace(
                "connector_status=not_configured，尚未调用连接器",
                "connector_status=no_hits；连接器返回零条范围内记录",
            ).replace(
                "尚未执行检索，因此不陈述命中或无命中结论。",
                "本轮在授权范围和查询条件下无命中；该结果不表示相关资料不存在。",
            )
            internal_path.write_text(internal_text, encoding="utf-8")

            candidate_total_path = next(candidate.glob("*客户研究与拜访准备报告.md"))
            total_lines = candidate_total_path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(total_lines):
                if line.startswith("| 内部检索 |"):
                    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    self.assertEqual(len(cells), 15)
                    cells[5] = "no_hits"
                    total_lines[index] = "| " + " | ".join(cells) + " |"
                    break
            else:
                self.fail("综合报告缺少内部检索状态行")
            candidate_total_path.write_text("\n".join(total_lines).rstrip() + "\n", encoding="utf-8")

            evidence_path = candidate / "runtime" / "evidence-manifest.json"
            evidence = load_json(evidence_path)
            evidence["sources"] = prior_evidence["sources"]
            evidence["claims"] = prior_evidence["claims"]
            evidence["query_links"] = {}
            evidence["updated_at"] = run_b_at.isoformat().replace("+00:00", "Z")
            evidence["connector_audit"].update(
                {
                    "status": "no_hits",
                    "call_id": "rag-call-run-b",
                    "called_at": run_b_at.isoformat().replace("+00:00", "Z"),
                    "server_filter_verified": True,
                    "response_scope_verified": True,
                    "response_fingerprint": "sha256:" + hashlib.sha256(b"[]").hexdigest(),
                    "isolated_record_count": 0,
                }
            )
            source_cache_path = candidate / "runtime" / "source-cache.json"
            source_cache = load_json(source_cache_path)
            receipt_total = {
                "latest_run_id": run_b,
                "customer_id": live_manifest["customer_id"],
            }
            for source_id, source in evidence["sources"].items():
                capture_receipt = _source_capture_receipt(
                    source_id,
                    source,
                    receipt_total,
                    "project-demo",
                )
                source["capture_receipt"] = capture_receipt
                source_cache["entries"][source["cache_key"]]["capture_receipt"] = capture_receipt
            tx.atomic_write_json(evidence_path, evidence)
            tx.atomic_write_json(source_cache_path, source_cache)

            candidate_manifest = load_json(candidate / "runtime" / "manifest.json")
            total = tx.parse_frontmatter(candidate_total_path.read_text(encoding="utf-8"))
            refreshed_manifest = tx.build_manifest(
                candidate,
                identity={
                    "context_id": total["context_id"],
                    "customer_id": total["customer_id"],
                    "customer_display_name": total["customer_display_name"],
                    "organization_scope": total["organization_scope"],
                },
                business_mode=total["business_mode"],
                route=total["route"],
                depth=total["depth"],
                task_timezone=candidate_manifest.get("task_timezone"),
                latest_run_id=total["latest_run_id"],
                content_version=total["content_version"],
                stage=total["workflow_stage"],
                ready_for_use=False,
                selected_modules=candidate_manifest["selected_modules"],
                authorization=candidate_manifest["authorization"],
                transaction_sequence=candidate_manifest["transaction_sequence"],
                intake_preflight=candidate_manifest["intake_preflight"],
            )
            candidate_manifest_path = candidate / "runtime" / "manifest.json"
            tx.atomic_write_json(candidate_manifest_path, refreshed_manifest)
            marker_path = candidate / "runtime" / "candidate-receipt.json"
            marker = load_json(marker_path)
            marker["payload_sha256"] = hashlib.sha256(candidate_manifest_path.read_bytes()).hexdigest()
            tx.atomic_write_json(marker_path, marker)

            validation = run_python(
                "validate_outputs.py", [str(candidate), "--profile", "candidate", "--json"]
            )
            self.assertEqual(validation.returncode, 0, validation.stdout or validation.stderr)
            combined_trust_env = os.environ[cr.TRUSTED_KEYS_ENV]
            committed = run_python(
                "commit_run.py",
                [*commit_base, "--capability-receipt-file", str(receipt)],
                env={cr.TRUSTED_KEYS_ENV: combined_trust_env},
            )
            self.assertEqual(committed.returncode, 0, committed.stderr or committed.stdout)
            final_manifest = load_json(workspace / "runtime" / "manifest.json")
            self.assertEqual(final_manifest["latest_run_id"], run_b)
            self.assertEqual(final_manifest["evidence_run_id"], run_b)
            self.assertEqual(final_manifest["authorization"]["capability_receipt_id"], "receipt-run-b")
            self.assertTrue(final_manifest["authorization"]["capability_receipt_verified"])
            final_evidence = load_json(workspace / "runtime" / "evidence-manifest.json")
            self.assertEqual(final_evidence["connector_audit"]["status"], "no_hits")
            self.assertEqual(final_evidence["run_id"], run_b)

    def test_receipt_schema_is_packaged(self):
        schema = json.loads(
            (SKILL_ROOT / "schemas" / "capability-receipt.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema"]["const"], cr.RECEIPT_SCHEMA)

    def source_envelope(self, **overrides: object) -> tuple[dict[str, object], dict[str, object]]:
        retrieved = (self.now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        expected: dict[str, object] = {
            "source_id": "SRC-I-001",
            "locator": "https://example.org/source",
            "final_url": "https://example.org/source",
            "canonical_locator": "https://example.org/source",
            "content_sha256": "a" * 64,
            "length": 128,
            "capture_method": "text-nfc-lf-utf8-v1",
            "retrieved_at": retrieved,
            "run_id": self.expected["run_id"],
            "customer_id": self.expected["customer_id"],
            "project_id": self.expected["project_id"],
        }
        envelope: dict[str, object] = {
            "schema": cr.SOURCE_RECEIPT_SCHEMA,
            "issuer": "corp-iam",
            "audience": cr.SOURCE_RECEIPT_AUDIENCE,
            "key_id": "cap-key-1",
            "issued_at": (self.now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (self.now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
            "receipt_id": "source-receipt-001",
            **expected,
        }
        envelope.update(overrides)
        signed = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        envelope["signature"] = base64.b64encode(self.private_key.sign(signed)).decode("ascii")
        return envelope, expected

    def test_source_capture_receipt_positive_tamper_and_missing_fail_closed(self):
        receipt, expected = self.source_envelope()
        with patch.dict(os.environ, {cr.TRUSTED_KEYS_ENV: self.trust_env}, clear=False):
            verified = cr.verify_source_capture_receipt(receipt, expected=expected, at=self.now)
            self.assertRegex(verified.receipt_sha256, r"^[0-9a-f]{64}$")

            tampered = dict(receipt)
            tampered["content_sha256"] = "b" * 64
            with self.assertRaises(cr.CapabilityReceiptError):
                cr.verify_source_capture_receipt(tampered, expected=expected, at=self.now)

            missing = dict(receipt)
            missing.pop("signature")
            with self.assertRaises(cr.CapabilityReceiptError):
                cr.verify_source_capture_receipt(missing, expected=expected, at=self.now)


if __name__ == "__main__":
    unittest.main()
