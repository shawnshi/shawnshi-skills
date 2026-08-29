from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from tests.common import (
    attest_candidate,
    candidate_attestation as ca,
    load_json,
    run_python,
    runtime_tx as tx,
)
from tests.fixture_builder import build_pending_letter_workspace, build_pending_strategy_workspace


def _body(text: str) -> str:
    lines = text.splitlines()
    end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    return "\n".join(lines[end + 1 :]).strip()


def _snapshot_tree(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot.append((relative, "symlink", str(path.readlink())))
        elif path.is_dir():
            snapshot.append((relative, "directory", ""))
        elif path.is_file():
            snapshot.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return snapshot


class RuntimeTransactionTests(unittest.TestCase):
    @staticmethod
    def _install_complete_unfinished_transaction(workspace: Path) -> Path:
        """Install an all-after journal without invoking a destructive failpoint."""

        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "controlled.md"
        before_raw = b"before\n"
        after_raw = b"after\n"
        target.write_bytes(before_raw)
        before = tx.file_state(target).as_dict()
        tx_dir = workspace / f"{tx.TX_DIR_PREFIX}recoverytest"
        (tx_dir / "new").mkdir(parents=True)
        (tx_dir / "old").mkdir()
        (tx_dir / "new" / "0000.bin").write_bytes(after_raw)
        (tx_dir / "old" / "0000.bin").write_bytes(before_raw)
        target.write_bytes(after_raw)
        tx.atomic_write_json(
            workspace / tx.JOURNAL_NAME,
            {
                "schema": tx.JOURNAL_SCHEMA,
                "tx_id": "recoverytest",
                "operation": "commit_run",
                "workspace": str(workspace.resolve()),
                "state": "committing",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "tx_dir": tx_dir.name,
                "entries": [
                    {
                        "target": target.name,
                        "before": before,
                        "after_exists": True,
                        "after_sha256": tx.sha256_bytes(after_raw),
                        "new": "new/0000.bin",
                        "old": "old/0000.bin",
                    }
                ],
                "applied": [target.name],
            },
        )
        return target

    @staticmethod
    def _install_candidate_bundle_journal(
        workspace: Path,
        after_manifest: dict,
        *,
        include_research_bundle: bool = True,
    ) -> None:
        targets = [tx.MANIFEST_REL]
        if include_research_bundle:
            targets.extend(
                [
                    tx.SEARCH_PLAN_REL,
                    tx.SOURCE_CACHE_REL,
                    tx.EVIDENCE_MANIFEST_REL,
                    tx.RUN_METRICS_REL,
                ]
            )
        tx_id = "candidate" + uuid.uuid4().hex[:12]
        tx_dir = workspace / f"{tx.TX_DIR_PREFIX}{tx_id}"
        (tx_dir / "new").mkdir(parents=True)
        (tx_dir / "old").mkdir()
        manifest_raw = (
            json.dumps(after_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        entries: list[dict[str, object]] = []
        for index, relative in enumerate(targets):
            target = workspace / relative
            before_raw = target.read_bytes()
            after_raw = manifest_raw if relative == tx.MANIFEST_REL else before_raw
            new_rel = f"new/{index:04d}.bin"
            old_rel = f"old/{index:04d}.bin"
            (tx_dir / new_rel).write_bytes(after_raw)
            (tx_dir / old_rel).write_bytes(before_raw)
            entries.append(
                {
                    "target": relative.as_posix(),
                    "before": tx.file_state(target).as_dict(),
                    "after_exists": True,
                    "after_sha256": tx.sha256_bytes(after_raw),
                    "new": new_rel,
                    "old": old_rel,
                }
            )
        tx.atomic_write_json(
            workspace / tx.JOURNAL_NAME,
            {
                "schema": tx.JOURNAL_SCHEMA,
                "tx_id": tx_id,
                "operation": "commit_run",
                "workspace": str(workspace.resolve()),
                "state": "committing",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "tx_dir": tx_dir.name,
                "entries": entries,
                "applied": [],
            },
        )

    @staticmethod
    def _payload_snapshot(workspace: Path) -> dict[str, bytes]:
        paths = list(workspace.glob("*.md")) + list((workspace / "runtime").glob("*.json"))
        return {
            path.relative_to(workspace).as_posix(): path.read_bytes()
            for path in sorted(paths, key=lambda item: item.as_posix())
            if path.is_file() and not path.is_symlink()
        }

    @staticmethod
    def _valid_recovery_audit(root: Path, workspace: Path) -> dict:
        manifest_path = workspace / tx.MANIFEST_REL
        formal_manifest = load_json(manifest_path)
        candidate = root / "recovery-candidate"
        (candidate / "runtime").mkdir(parents=True)
        candidate_manifest_path = candidate / tx.MANIFEST_REL
        candidate_manifest_path.write_text(
            json.dumps(
                {
                    "schema": tx.RUNTIME_SCHEMA,
                    "customer_id": formal_manifest["customer_id"],
                    "intake_preflight": formal_manifest["intake_preflight"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        marker = {
            "schema": ca.MARKER_SCHEMA,
            "context_id": formal_manifest["context_id"],
            "run_id": formal_manifest["latest_run_id"],
            "source_manifest_revision": formal_manifest["transaction_sequence"],
            "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "source_workspace": str(workspace.resolve()),
            "candidate_workspace": str(candidate.resolve()),
            "input_payload_sha256": hashlib.sha256(b"recovery-candidate-input").hexdigest(),
            "final_manifest_sha256": hashlib.sha256(candidate_manifest_path.read_bytes()).hexdigest(),
        }
        (candidate / ca.MARKER_REL).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        attestation_path = attest_candidate(candidate)
        expected = load_json(candidate / ca.REQUEST_REL)
        verified = ca.verify_candidate_attestation(attestation_path, expected=expected)
        ca.claim_candidate_attestation_nonce(verified, workspace=workspace)
        return verified.audit_summary(expected)

    def initialize(self, root: Path) -> dict:
        workspace = build_pending_strategy_workspace(root)
        total = tx.parse_frontmatter(
            next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
        )
        return {"workspace": str(workspace), "context_id": total["context_id"]}

    def resume_args(self, root: Path, context_id: str, *extra: str) -> list[str]:
        intake = next(root.glob("intake-standard_visit-*.json"))
        return [
            "示例医院",
            "--output-root",
            str(root),
            "--context-id",
            context_id,
            "--resume",
            "--business-mode",
            "standard_visit",
            "--intake-input",
            str(intake),
            "--runtime-owner",
            "测试负责人",
            "--lock-timeout",
            "10",
            *extra,
            "--json",
        ]

    def test_concurrent_resumes_both_succeed_without_lost_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = self.initialize(root)
            workspace = Path(initial["workspace"])
            before = load_json(workspace / "runtime" / "manifest.json")
            args = self.resume_args(root, initial["context_id"])
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(run_python, "init_workspace.py", args) for _ in range(2)]
                results = [future.result(timeout=20) for future in futures]
            for result in results:
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payloads = [json.loads(result.stdout) for result in results]
            self.assertEqual(len({payload["latest_run_id"] for payload in payloads}), 2)
            after = load_json(workspace / "runtime" / "manifest.json")
            self.assertEqual(after["transaction_sequence"], before["transaction_sequence"] + 2)
            self.assertEqual(before["task_timezone"], "Asia/Shanghai")
            self.assertEqual(after["task_timezone"], before["task_timezone"])
            total = next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
            for payload in payloads:
                self.assertGreaterEqual(total.count(payload["latest_run_id"]), 1)

    def test_unfinished_journal_requires_and_accepts_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = self.initialize(root)
            workspace = Path(initial["workspace"])
            crashed = run_python(
                "init_workspace.py",
                self.resume_args(root, initial["context_id"]),
                env={"DISCOVERY_CALL_TX_SIGKILL_AFTER": "1"},
            )
            self.assertNotEqual(crashed.returncode, 0)
            self.assertTrue((workspace / tx.JOURNAL_NAME).is_file())
            blocked = run_python(
                "init_workspace.py", self.resume_args(root, initial["context_id"])
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("未完成事务", blocked.stderr)
            recovered = run_python(
                "init_workspace.py",
                self.resume_args(
                    root,
                    initial["context_id"],
                    "--recover",
                    "--recovery-strategy",
                    "auto",
                ),
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr or recovered.stdout)
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
            self.assertEqual(
                load_json(workspace / "runtime" / "manifest.json")["task_timezone"],
                "Asia/Shanghai",
            )
            validation = run_python(
                "validate_outputs.py", [str(workspace), "--profile", "scaffold", "--json"]
            )
            self.assertEqual(validation.returncode, 0, validation.stderr or validation.stdout)

    def test_recovery_without_attested_postflight_rolls_back_and_failed_postflight_restores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            no_proof = root / "no-proof"
            target = self._install_complete_unfinished_transaction(no_proof)
            result = tx.recover_transaction(
                no_proof,
                strategy="roll-forward",
                postflight=None,
            )
            self.assertEqual(result, "rolled_back")
            self.assertEqual(target.read_bytes(), b"before\n")
            self.assertFalse((no_proof / tx.JOURNAL_NAME).exists())

            rejected = root / "rejected"
            target = self._install_complete_unfinished_transaction(rejected)
            with self.assertRaisesRegex(RuntimeError, "invalid recovered candidate"):
                tx.recover_transaction(
                    rejected,
                    strategy="roll-forward",
                    postflight=lambda _workspace: (_ for _ in ()).throw(
                        RuntimeError("invalid recovered candidate")
                    ),
                )
            self.assertEqual(target.read_bytes(), b"before\n")
            self.assertFalse((rejected / tx.JOURNAL_NAME).exists())

            accepted = root / "accepted"
            target = self._install_complete_unfinished_transaction(accepted)
            result = tx.recover_transaction(
                accepted,
                strategy="roll-forward",
                postflight=lambda workspace: self.assertEqual(
                    (workspace / "controlled.md").read_bytes(),
                    b"after\n",
                ),
            )
            self.assertEqual(result, "rolled_forward")
            self.assertEqual(target.read_bytes(), b"after\n")
            self.assertFalse((accepted / tx.JOURNAL_NAME).exists())

    def test_invalid_before_workspace_is_reported_without_traceback_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary) / "live")
            institution = next(workspace.glob("*机构研究报告.md"))
            institution.write_text(
                institution.read_text(encoding="utf-8")
                + "\n---\ninvalid_second_frontmatter: true\n---\n",
                encoding="utf-8",
            )
            manifest_path = workspace / tx.MANIFEST_REL
            manifest = load_json(manifest_path)
            manifest["artifacts"]["institution_research"]["sha256"] = hashlib.sha256(
                institution.read_bytes()
            ).hexdigest()
            tx.atomic_write_json(manifest_path, manifest)
            before = self._payload_snapshot(workspace)

            result = run_python(
                "recover_workspace.py",
                [str(workspace), "--strategy", "auto", "--json"],
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("ERROR:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(self._payload_snapshot(workspace), before)

    def test_public_recover_roll_forward_always_rolls_back_forged_and_valid_after(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root / "live")
            original_manifest = load_json(workspace / tx.MANIFEST_REL)
            forged_manifest = json.loads(json.dumps(original_manifest, ensure_ascii=False))
            forged_manifest["transaction_sequence"] += 1
            forged_manifest["candidate_attestation"] = {
                "schema": ca.AUDIT_SCHEMA,
                "attestation_schema": ca.ATTESTATION_SCHEMA,
                "signature": "locally-forged",
            }

            for repetition in range(3):
                with self.subTest(phase="forged_after", repetition=repetition):
                    before = self._payload_snapshot(workspace)
                    self._install_candidate_bundle_journal(workspace, forged_manifest)
                    result = run_python(
                        "recover_workspace.py",
                        [str(workspace), "--strategy", "roll-forward", "--json"],
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("public_roll_forward_disabled", result.stderr)
                    self.assertEqual(self._payload_snapshot(workspace), before)
                    self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
                    self.assertFalse(any(workspace.glob(f"{tx.TX_DIR_PREFIX}*")))

            valid_audit = self._valid_recovery_audit(root, workspace)
            valid_manifest = load_json(workspace / tx.MANIFEST_REL)
            valid_manifest["transaction_sequence"] += 1
            valid_manifest["candidate_attestation"] = valid_audit
            before_valid_recovery = self._payload_snapshot(workspace)
            self._install_candidate_bundle_journal(workspace, valid_manifest)
            result = run_python(
                "recover_workspace.py",
                [str(workspace), "--strategy", "roll-forward", "--json"],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("public_roll_forward_disabled", result.stderr)
            self.assertEqual(self._payload_snapshot(workspace), before_valid_recovery)
            self.assertEqual(
                load_json(workspace / tx.MANIFEST_REL).get("candidate_attestation"),
                original_manifest.get("candidate_attestation"),
            )
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
            self.assertFalse(any(workspace.glob(f"{tx.TX_DIR_PREFIX}*")))
            no_transaction = run_python(
                "recover_workspace.py",
                [str(workspace), "--strategy", "roll-forward", "--json"],
            )
            self.assertEqual(
                no_transaction.returncode,
                0,
                no_transaction.stderr or no_transaction.stdout,
            )
            self.assertEqual(
                json.loads(no_transaction.stdout)["recovery"],
                "no_transaction",
            )

            letter_workspace = build_pending_letter_workspace(root / "letter-live")
            letter_manifest = load_json(letter_workspace / tx.MANIFEST_REL)
            forged_letter_manifest = json.loads(
                json.dumps(letter_manifest, ensure_ascii=False)
            )
            forged_letter_manifest["transaction_sequence"] += 1
            forged_letter_manifest["candidate_attestation"] = {
                "schema": ca.AUDIT_SCHEMA,
                "attestation_schema": ca.ATTESTATION_SCHEMA,
                "signature": "locally-forged-letter",
            }
            for repetition in range(3):
                with self.subTest(phase="letter_without_research_bundle", repetition=repetition):
                    before = self._payload_snapshot(letter_workspace)
                    self._install_candidate_bundle_journal(
                        letter_workspace,
                        forged_letter_manifest,
                        include_research_bundle=False,
                    )
                    result = run_python(
                        "recover_workspace.py",
                        [str(letter_workspace), "--strategy", "roll-forward", "--json"],
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("public_roll_forward_disabled", result.stderr)
                    self.assertEqual(self._payload_snapshot(letter_workspace), before)
                    self.assertFalse((letter_workspace / tx.JOURNAL_NAME).exists())
                    self.assertFalse(any(letter_workspace.glob(f"{tx.TX_DIR_PREFIX}*")))

    def test_N72_disabled_file_map_cannot_trigger_recovery_side_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = self.initialize(root)
            workspace = Path(initial["workspace"])
            crashed = run_python(
                "init_workspace.py",
                self.resume_args(root, initial["context_id"]),
                env={"DISCOVERY_CALL_TX_SIGKILL_AFTER": "1"},
            )
            self.assertNotEqual(crashed.returncode, 0)
            self.assertTrue((workspace / tx.JOURNAL_NAME).is_file())
            candidate = root / "legacy-candidate.md"
            candidate.write_text("legacy candidate", encoding="utf-8")
            mapping = root / "legacy-map.json"
            mapping.write_text(
                json.dumps({"legacy.md": str(candidate)}), encoding="utf-8"
            )
            manifest_path = workspace / "runtime" / "manifest.json"
            manifest = load_json(manifest_path)
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            baseline = _snapshot_tree(root)
            for _ in range(3):
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
                        "--recover",
                        "--recovery-strategy",
                        "auto",
                        "--json",
                    ],
                )
                self.assertEqual(result.returncode, 2)
                self.assertRegex(result.stderr, r"file-map.*禁用|candidate-workspace")
                self.assertEqual(_snapshot_tree(root), baseline)
                self.assertTrue((workspace / tx.JOURNAL_NAME).is_file())

    def test_commit_run_manifest_cas_rejects_stale_second_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root / "live")
            manifest_path = workspace / "runtime" / "manifest.json"
            manifest = load_json(manifest_path)
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
            strategy_path = next(workspace.glob("*交流策略与议题设计.md"))
            total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
            strategy_text = strategy_path.read_text(encoding="utf-8")
            strategy = tx.parse_frontmatter(strategy_text)
            strategy_body = _body(strategy_text)
            updated_strategy_body = strategy_body.replace(
                "| verification | 核实任务、角色、预算与采购时序 | 方案顾问 |",
                "| verification | 核实任务、角色、预算、采购时序与验收标准 | 方案顾问 |",
                1,
            )
            self.assertNotEqual(updated_strategy_body, strategy_body)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            run_id = f"dcr-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}"
            payload = {
                "schema": "discovery-call-candidate-run/v1",
                "context_id": total["context_id"],
                "expected_manifest_revision": manifest["transaction_sequence"],
                "expected_manifest_sha256": digest,
                "run": {
                    "run_id": run_id,
                    "updated_at": now.isoformat().replace("+00:00", "Z"),
                    "evidence_cutoff_date": total["evidence_cutoff_date"],
                    "runtime_owner": "CAS测试负责人",
                    "workflow_stage": "review",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "objective": "验证candidate CAS",
                },
                "artifacts": [
                    {"artifact_type": "institution_research", "action": "reused", "key_claim_ids": "CLM-I-001"},
                    {"artifact_type": "leader_research", "action": "reused", "key_claim_ids": "CLM-L-001"},
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
            payload_path = root / "candidate-payload.json"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            intake = next(workspace.parent.glob("intake-standard_visit-*.json"))
            built = run_python(
                "build_candidate.py",
                [
                    str(workspace),
                    "--payload", str(payload_path),
                    "--output-root", str(root / "candidate"),
                    "--intake-input", str(intake),
                    "--json",
                ],
            )
            self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
            build_result = json.loads(built.stdout)
            attest_candidate(Path(build_result["candidate_workspace"]))
            args = build_result["next_commit"]["argv"][2:]
            first = run_python("commit_run.py", args)
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            second = run_python("commit_run.py", args)
            self.assertEqual(second.returncode, 2)
            self.assertIn("CAS", second.stderr)

    def test_runtime_transaction_rolls_back_all_files_on_postflight_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            first = workspace / "first.txt"
            second = workspace / "second.txt"
            first.write_text("before", encoding="utf-8")

            def fail(_workspace: Path) -> None:
                raise RuntimeError("postflight failed")

            with tx.output_root_lock(workspace.parent, timeout=2):
                with tx.workspace_lock(workspace, timeout=2):
                    with self.assertRaises(RuntimeError):
                        tx.transactional_commit(
                            workspace,
                            {first: "after", second: "created"},
                            operation="test_rollback",
                            postflight=fail,
                        )
            self.assertEqual(first.read_text(encoding="utf-8"), "before")
            self.assertFalse(second.exists())
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())

    def test_workspace_lock_rejects_symlink_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            target = root / "unrelated.txt"
            target.write_text("must remain unchanged", encoding="utf-8")
            (workspace / tx.WORKSPACE_LOCK_NAME).symlink_to(target)

            with self.assertRaises(tx.TxError):
                with tx.workspace_lock(workspace, timeout=0.1):
                    self.fail("symlink lock must never be acquired")
            self.assertEqual(target.read_text(encoding="utf-8"), "must remain unchanged")


if __name__ == "__main__":
    unittest.main()
