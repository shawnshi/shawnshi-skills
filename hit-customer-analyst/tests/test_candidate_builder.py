from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import (
    SCRIPTS,
    attest_candidate,
    load_module,
    refresh_candidate_seal_request,
    run_python,
    runtime_tx as tx,
)
from tests.fixture_builder import (
    _install_machine_bundle,
    _rebuild_manifest,
    _replace_frontmatter,
    build_pending_strategy_workspace,
)


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
        self.intake = next(self.workspace.parent.glob("intake-standard_visit-*.json"))
        self.total_path = next(self.workspace.glob("*客户研究与拜访准备报告.md"))
        self.strategy_path = next(self.workspace.glob("*交流策略与议题设计.md"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def payload(self) -> dict:
        revision, digest = tx.manifest_state(self.workspace)
        total = tx.parse_frontmatter(self.total_path.read_text(encoding="utf-8"))
        strategy_text = self.strategy_path.read_text(encoding="utf-8")
        strategy = tx.parse_frontmatter(strategy_text)
        strategy_body = body_from_text(strategy_text)
        updated_strategy_body = strategy_body.replace(
            "| verification | 核实任务、角色、预算与采购时序 | 方案顾问 |",
            "| verification | 核实任务、角色、预算、采购时序与验收标准 | 方案顾问 |",
            1,
        )
        if updated_strategy_body == strategy_body:
            raise AssertionError("candidate fixture缺少受控CRM verification行。")
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
                    "body": updated_strategy_body,
                    "metadata": {
                        "target_contact_level": strategy["target_contact_level"],
                        "visit_objective": strategy["visit_objective"],
                        "minimum_next_step": strategy["minimum_next_step"],
                    },
                    "key_claim_ids": "CLM-I-001, CLM-L-001",
                    "summary_sync_status": "synced",
                    "downstream_invalidation": "none",
                    "gaps_blockers": "none",
                },
            ],
        }

    def run_builder(
        self,
        payload: dict,
        *,
        output_name: str = "candidates",
        env: dict[str, str] | None = None,
    ):
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
                "--intake-input",
                str(self.intake),
                "--json",
            ],
            env=env,
        )

    def test_N71_build_and_commit_reject_current_request_revision_drift(self):
        binding = json.loads(self.intake.read_text(encoding="utf-8"))["request_binding"]
        receipt = json.loads(
            (self.intake.parent / binding["receipt_file"]).read_text(encoding="utf-8")
        )
        drifted_context = {
            "request_id": receipt["request_id"],
            "business_mode": receipt["business_mode"],
            "receipt_id": receipt["receipt_id"],
            "request_bundle_id": receipt["request_bundle_id"],
            "request_revision": receipt["request_revision"] + 1,
            "last_user_event_id": "test-user-event-999",
            "raw_request_sha256": receipt["raw_request_sha256"],
        }
        drift_env = {
            "DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON": json.dumps(
                drifted_context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        }
        for repetition in range(3):
            with self.subTest(repetition=repetition):
                output_name = f"drift-{repetition}"
                before_live = {
                    str(path.relative_to(self.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.workspace.rglob("*")
                    if path.is_file() and not path.is_symlink()
                }
                blocked_build = self.run_builder(
                    self.payload(),
                    output_name=output_name,
                    env=drift_env,
                )
                self.assertEqual(blocked_build.returncode, 2)
                self.assertIn("当前会话头", blocked_build.stderr)
                self.assertFalse((self.root / output_name).exists())
                after_live = {
                    str(path.relative_to(self.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.workspace.rglob("*")
                    if path.is_file() and not path.is_symlink()
                }
                self.assertEqual(after_live, before_live)

                built = self.run_builder(self.payload(), output_name=f"valid-{repetition}")
                self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
                result = json.loads(built.stdout)
                candidate = Path(result["candidate_workspace"])
                commit_args = result["next_commit"]["argv"][2:]
                before_commit = {
                    "live": {
                        str(path.relative_to(self.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in self.workspace.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    },
                    "candidate": {
                        str(path.relative_to(candidate)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in candidate.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    },
                }
                blocked_commit = run_python("commit_run.py", commit_args, env=drift_env)
                self.assertEqual(blocked_commit.returncode, 2)
                self.assertIn("当前会话头", blocked_commit.stderr)
                after_commit = {
                    "live": {
                        str(path.relative_to(self.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in self.workspace.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    },
                    "candidate": {
                        str(path.relative_to(candidate)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in candidate.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    },
                }
                self.assertEqual(after_commit, before_commit)

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
        self.assertEqual(
            parameters["candidate_attestation_file"],
            str(candidate / "runtime" / "candidate-attestation.json"),
        )

        attest_candidate(candidate)
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
        candidate = Path(output["candidate_workspace"])
        attest_candidate(candidate)
        marker_path = candidate / "runtime" / "candidate-receipt.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["final_manifest_sha256"] = "0" * 64
        marker_path.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        committed = subprocess.run(
            output["next_commit"]["argv"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(committed.returncode, 2)
        self.assertIn("未绑定当前candidate manifest", committed.stderr)

    def test_commit_without_host_attestation_is_fail_closed(self):
        result = self.run_builder(self.payload(), output_name="missing-attestation")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        before = tx.manifest_state(self.workspace)
        committed = subprocess.run(output["next_commit"]["argv"], text=True, capture_output=True, check=False)
        self.assertEqual(committed.returncode, 2)
        self.assertIn("candidate attestation", committed.stderr)
        self.assertEqual(tx.manifest_state(self.workspace), before)

    def test_committed_attestation_summary_is_durable_and_tamper_detected(self):
        payload = self.payload()
        result = self.run_builder(payload, output_name="durable-attestation")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        candidate = Path(output["candidate_workspace"])
        attest_candidate(candidate)
        committed = subprocess.run(output["next_commit"]["argv"], text=True, capture_output=True, check=False)
        self.assertEqual(committed.returncode, 0, committed.stderr or committed.stdout)

        manifest_path = self.workspace / tx.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audit = manifest["candidate_attestation"]
        self.assertEqual(audit["schema"], "discovery-call-candidate-attestation-audit/v3")
        self.assertEqual(audit["run_id"], payload["run"]["run_id"])
        self.assertEqual(audit["context_id"], payload["context_id"])
        self.assertEqual(audit["source_manifest_revision"], payload["expected_manifest_revision"])
        self.assertEqual(audit["source_manifest_sha256"], payload["expected_manifest_sha256"])
        self.assertRegex(audit["attestation_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(audit["intake_gate_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(audit["signature"])
        self.assertRegex(audit["nonce"], r"^[A-Za-z0-9_-]{22,128}$")

        audit["context_id"] = "dcx-20260827-ZZZZ9999"
        tx.atomic_write_json(manifest_path, manifest)
        validation = run_python("validate_outputs.py", [str(self.workspace), "--profile", "candidate", "--json"])
        self.assertEqual(validation.returncode, 1)
        codes = {issue["code"] for issue in json.loads(validation.stdout)["issues"]}
        self.assertIn("candidate_attestation_lineage_drift", codes)

    def test_commit_rejects_post_seal_artifact_tamper_and_missing_runtime_bundle(self):
        for mutation in ("artifact", "remove_all_runtime"):
            with self.subTest(mutation=mutation):
                result = self.run_builder(self.payload(), output_name=f"sealed-{mutation}")
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                output = json.loads(result.stdout)
                candidate = Path(output["candidate_workspace"])
                attest_candidate(candidate)
                before = {
                    str(path.relative_to(self.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.workspace.rglob("*")
                    if path.is_file()
                    and not path.is_symlink()
                    and not path.name.startswith(".discovery-call.")
                }
                if mutation == "artifact":
                    target = next(candidate.glob("*交流策略与议题设计.md"))
                    target.write_text(target.read_text(encoding="utf-8") + "\n封印后改写\n", encoding="utf-8")
                else:
                    for name in (
                        "search-plan.json",
                        "source-cache.json",
                        "evidence-manifest.json",
                        "run-metrics.json",
                    ):
                        (candidate / "runtime" / name).unlink()
                committed = subprocess.run(
                    output["next_commit"]["argv"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(committed.returncode, 2)
                after = {
                    str(path.relative_to(self.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in self.workspace.rglob("*")
                    if path.is_file()
                    and not path.is_symlink()
                    and not path.name.startswith(".discovery-call.")
                }
                self.assertEqual(after, before)

    def test_commit_rejects_locally_resealed_manifest_without_new_host_attestation(self):
        result = self.run_builder(self.payload(), output_name="local-reseal")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        candidate = Path(output["candidate_workspace"])
        attest_candidate(candidate)
        signed_manifest = json.loads((candidate / tx.MANIFEST_REL).read_text(encoding="utf-8"))

        target = next(candidate.glob("*交流策略与议题设计.md"))
        target.write_text(target.read_text(encoding="utf-8") + "\n本地重写但未经宿主重签。\n", encoding="utf-8")
        _rebuild_manifest(candidate, ["institution", "leader", "strategy"])
        rebuilt = json.loads((candidate / tx.MANIFEST_REL).read_text(encoding="utf-8"))
        rebuilt["transaction_sequence"] = signed_manifest["transaction_sequence"]
        tx.atomic_write_json(candidate / tx.MANIFEST_REL, rebuilt)
        refresh_candidate_seal_request(candidate)

        before = tx.manifest_state(self.workspace)
        committed = subprocess.run(output["next_commit"]["argv"], text=True, capture_output=True, check=False)
        self.assertEqual(committed.returncode, 2)
        self.assertIn("candidate attestation", committed.stderr)
        self.assertEqual(tx.manifest_state(self.workspace), before)

    def test_each_machine_file_missing_or_replaced_is_fail_closed(self):
        names = ("search-plan.json", "source-cache.json", "evidence-manifest.json", "run-metrics.json")
        for name in names:
            for mutation in ("missing", "replaced"):
                with self.subTest(name=name, mutation=mutation):
                    result = self.run_builder(self.payload(), output_name=f"machine-{name}-{mutation}")
                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                    output = json.loads(result.stdout)
                    candidate = Path(output["candidate_workspace"])
                    attest_candidate(candidate)
                    target = candidate / "runtime" / name
                    if mutation == "missing":
                        target.unlink()
                    else:
                        target.write_bytes(b"{}\n")
                    before = tx.manifest_state(self.workspace)
                    committed = subprocess.run(output["next_commit"]["argv"], text=True, capture_output=True, check=False)
                    self.assertEqual(committed.returncode, 2)
                    self.assertEqual(tx.manifest_state(self.workspace), before)

    def test_candidate_byte_swap_after_preview_is_rejected_without_write(self):
        result = self.run_builder(self.payload(), output_name="toctou-swap")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        candidate = Path(output["candidate_workspace"])
        attest_candidate(candidate)

        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        commit_module = load_module("discovery_call_commit_run_toctou", SCRIPTS / "commit_run.py")
        args = commit_module.build_parser().parse_args(output["next_commit"]["argv"][2:])
        original_preview = commit_module._preview

        def swap_after_preview(workspace, planned, deletes, strict):
            original_preview(workspace, planned, deletes, strict)
            target = candidate / "runtime" / "run-metrics.json"
            target.write_bytes(target.read_bytes() + b" \n")

        before = tx.manifest_state(self.workspace)
        with patch.object(commit_module, "_preview", side_effect=swap_after_preview):
            with self.assertRaises(tx.CASMismatch):
                commit_module.commit(args)
        self.assertEqual(tx.manifest_state(self.workspace), before)

    def test_N123_candidate_attestation_cannot_authorize_unbound_deletes_three_times(self):
        archive = self.workspace / "archive" / "letters"
        archive.mkdir(parents=True)
        protected = archive / "受保护历史客户信.md"
        protected.write_text("历史客户信不得由候选提交删除。\n", encoding="utf-8")

        def snapshot() -> dict[str, bytes]:
            return {
                path.relative_to(self.workspace).as_posix(): path.read_bytes()
                for path in self.workspace.rglob("*")
                if path.is_file() and not path.is_symlink()
            }

        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        commit_module = load_module(
            "discovery_call_commit_run_delete_disabled",
            SCRIPTS / "commit_run.py",
        )
        last_output: dict[str, object] | None = None
        for repetition in range(3):
            with self.subTest(repetition=repetition):
                built = self.run_builder(
                    self.payload(),
                    output_name=f"n123-delete-{repetition}",
                )
                self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
                output = json.loads(built.stdout)
                last_output = output
                candidate = Path(output["candidate_workspace"])
                attest_candidate(candidate)
                before = snapshot()

                public_attempt = subprocess.run(
                    [
                        *output["next_commit"]["argv"],
                        "--delete",
                        protected.relative_to(self.workspace).as_posix(),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(public_attempt.returncode, 2)
                self.assertIn("unrecognized arguments: --delete", public_attempt.stderr)
                self.assertEqual(snapshot(), before)

                internal_args = commit_module.build_parser().parse_args(
                    output["next_commit"]["argv"][2:]
                )
                internal_args.delete = [protected.relative_to(self.workspace).as_posix()]
                with self.assertRaisesRegex(tx.TxError, "删除接口已禁用"):
                    commit_module.commit(internal_args)
                self.assertEqual(snapshot(), before)
                self.assertTrue(protected.is_file())

        assert last_output is not None
        valid_commit = subprocess.run(
            last_output["next_commit"]["argv"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(valid_commit.returncode, 0, valid_commit.stderr or valid_commit.stdout)
        self.assertTrue(protected.is_file())

    def test_N124_preview_crossing_attestation_expiry_is_zero_write_three_times(self):
        def stable_snapshot() -> dict[str, bytes]:
            return {
                path.relative_to(self.workspace).as_posix(): path.read_bytes()
                for path in self.workspace.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and not path.name.startswith(".discovery-call.")
            }

        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        last_output: dict[str, object] | None = None
        for repetition in range(3):
            with self.subTest(phase="pre_wal_expiry", repetition=repetition):
                built = self.run_builder(
                    self.payload(),
                    output_name=f"n124-expiry-{repetition}",
                )
                self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
                output = json.loads(built.stdout)
                last_output = output
                candidate = Path(output["candidate_workspace"])
                attestation_path = attest_candidate(candidate)
                envelope = json.loads(attestation_path.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(
                    envelope["expires_at"].replace("Z", "+00:00")
                )

                commit_module = load_module(
                    f"discovery_call_commit_run_expiry_{repetition}",
                    SCRIPTS / "commit_run.py",
                )
                args = commit_module.build_parser().parse_args(
                    output["next_commit"]["argv"][2:]
                )
                original_preview = commit_module._preview

                class PreviewClock(datetime):
                    current = datetime.now(timezone.utc)

                    @classmethod
                    def now(cls, tz=None):
                        value = cls.current
                        return value if tz is None else value.astimezone(tz)

                preview_calls = 0

                def cross_expiry_after_preview(workspace, planned, deletes, strict):
                    nonlocal preview_calls
                    original_preview(workspace, planned, deletes, strict)
                    preview_calls += 1
                    PreviewClock.current = expires_at + timedelta(seconds=1)

                before = stable_snapshot()
                with patch.object(commit_module, "datetime", PreviewClock):
                    with patch.object(
                        commit_module,
                        "_preview",
                        side_effect=cross_expiry_after_preview,
                    ):
                        with self.assertRaisesRegex(
                            tx.TxError,
                            "candidate_attestation_invalid.*WAL前复验失败",
                        ):
                            commit_module.commit(args)
                self.assertEqual(preview_calls, 1)
                self.assertEqual(stable_snapshot(), before)
                self.assertFalse(tx.unfinished_transaction(self.workspace))
                self.assertFalse(any(self.workspace.glob(".discovery-call.tx-*")))

        assert last_output is not None
        valid_commit = subprocess.run(
            last_output["next_commit"]["argv"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(valid_commit.returncode, 0, valid_commit.stderr or valid_commit.stdout)
        manifest_path = self.workspace / tx.MANIFEST_REL
        valid_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audit = valid_manifest["candidate_attestation"]
        issued_at = datetime.fromisoformat(audit["issued_at"].replace("Z", "+00:00"))
        host_authorized_at = datetime.fromisoformat(
            audit["host_authorized_at"].replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(audit["expires_at"].replace("Z", "+00:00"))
        self.assertLessEqual(issued_at, host_authorized_at)
        self.assertLess(host_authorized_at, expires_at)
        self.assertNotIn("verified_at", audit)
        self.assertNotIn("wal_authorized_at", audit)

        invalid_manifest = json.loads(json.dumps(valid_manifest, ensure_ascii=False))
        invalid_manifest["candidate_attestation"]["host_authorized_at"] = (
            expires_at + timedelta(seconds=1)
        ).isoformat().replace("+00:00", "Z")
        manifest_path.write_text(
            json.dumps(invalid_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for repetition in range(3):
            with self.subTest(phase="postflight_time_contract", repetition=repetition):
                validation = run_python(
                    "validate_outputs.py",
                    [str(self.workspace), "--profile", "candidate", "--json"],
                )
                self.assertEqual(validation.returncode, 1)
                codes = {
                    issue["code"]
                    for issue in json.loads(validation.stdout)["issues"]
                }
                self.assertIn("candidate_attestation_time_invalid", codes)

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

    def test_candidate_rejects_v1_or_unsigned_ttl_permission_fields(self):
        for mutation in ("v1", "published_at"):
            with self.subTest(mutation=mutation):
                evidence_path = self.workspace / "runtime" / "evidence-manifest.json"
                cache_path = self.workspace / "runtime" / "source-cache.json"
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                source = next(iter(evidence["sources"].values()))
                if mutation == "v1":
                    source["capture_receipt"]["schema"] = "discovery-call-source-capture-receipt/v1"
                else:
                    source["published_at"] = "2026-08-20T00:00:00Z"
                    cache["entries"][source["cache_key"]]["published_at"] = source["published_at"]
                    tx.atomic_write_json(cache_path, cache)
                tx.atomic_write_json(evidence_path, evidence)
                _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
                result = run_python(
                    "validate_outputs.py",
                    [str(self.workspace), "--profile", "candidate", "--json"],
                )
                self.assertEqual(result.returncode, 1)
                codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
                self.assertIn("source_capture_receipt_invalid", codes)
                # Restore a clean fixture for the next subcase.
                _install_machine_bundle(self.workspace, ["institution", "leader", "strategy"])
                _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])

    def test_internal_evidence_requires_internal_carrier_and_authorization(self):
        institution = next(self.workspace.glob("*机构研究报告.md"))
        text = institution.read_text(encoding="utf-8")
        text = text.replace("| CLM-I-001 | F | public |", "| CLM-I-001 | F | N |", 1)
        text = text.replace("| 2026-08-26 | A | official-site | public |", "| 2026-08-26 | internal | official-site | internal-authorized |", 1)
        institution.write_text(text, encoding="utf-8")
        _rebuild_manifest(self.workspace, ["institution", "leader", "strategy"])
        result = run_python(
            "validate_outputs.py",
            [str(self.workspace), "--profile", "candidate", "--json"],
        )
        self.assertEqual(result.returncode, 1)
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("internal_claim_carrier_invalid", codes)
        self.assertIn("internal_source_carrier_invalid", codes)
        self.assertIn("authorization_required", codes)
        self.assertIn("capability_receipt_unverified", codes)

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
                if variant == "account_planning":
                    self.assertIn("必须绑定scheduled_visit分支", result.stderr)
                else:
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
