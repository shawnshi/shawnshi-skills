from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.common import SCRIPTS, load_module, run_python, runtime_tx as tx
from tests.fixture_builder import build_pending_letter_workspace, record_action_assertion, record_external_request


validator = load_module("discovery_call_validate_outputs", SCRIPTS / "validate_outputs.py")


class LetterLifecycleTests(unittest.TestCase):
    def _govern(self, workspace: Path, *args: str) -> dict:
        result = run_python(
            "validate_outputs.py",
            [str(workspace), *args, "--json"],
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["errors"], 0, payload)
        return payload

    def _submit_revision(self, workspace: Path, candidate: Path) -> None:
        candidate.mkdir()
        for source in workspace.glob("*.md"):
            shutil.copy2(source, candidate / source.name)
        shutil.copytree(workspace / "runtime", candidate / "runtime")

        issues: list = []
        documents = validator.load_documents(candidate, issues)
        self.assertFalse([issue for issue in issues if issue.severity == "error"], issues)
        by_type = {doc.frontmatter["artifact_type"]: doc for doc in documents}
        letter = by_type["customer_letter_internal"]
        total = by_type["comprehensive_report"]
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat().replace("+00:00", "Z")
        run_id = validator.new_run_id(now)
        next_letter_version = str(int(letter.frontmatter["content_version"]) + 1)
        revised = letter.text.replace(
            "诚请您确认九月技术交流的合适时间",
            "诚请您确认十月技术交流的合适时间",
        )
        revised = validator.replace_flat_frontmatter(
            revised,
            {
                "latest_run_id": run_id,
                "content_version": next_letter_version,
                "updated_at": timestamp,
                "review_status": "pending",
            },
        )
        revised = validator.append_letter_review_record(
            revised,
            timestamp=timestamp,
            version=next_letter_version,
            run_id=run_id,
            summary="完成正文修订并重新提交审核",
            owner=letter.frontmatter["runtime_owner"],
            review_status="pending",
        )
        letter_data = letter.frontmatter | {
            "latest_run_id": run_id,
            "content_version": next_letter_version,
            "updated_at": timestamp,
            "review_status": "pending",
        }
        actions = {
            "institution_research": "reused",
            "customer_letter_internal": "updated",
        }
        updated_total = validator.update_operation_rows(
            total,
            by_type,
            metadata={"customer_letter_internal": letter_data},
            paths={"customer_letter_internal": letter.path},
            actions=actions,
        )
        next_total_version = str(int(total.frontmatter["content_version"]) + 1)
        updated_total = validator.replace_flat_frontmatter(
            updated_total,
            {
                "latest_run_id": run_id,
                "content_version": next_total_version,
                "updated_at": timestamp,
                "workflow_stage": "review",
                **validator.readiness_reset_updates(),
            },
        )
        summary = validator.operation_summary(
            total,
            "revise_letter",
            actions,
            letter.frontmatter["evidence_cutoff_date"],
        )
        updated_total = validator.append_operation_record(
            updated_total,
            timestamp=timestamp,
            version=next_total_version,
            run_id=run_id,
            summary=summary,
            owner=total.frontmatter["runtime_owner"],
        )
        (candidate / letter.path.name).write_text(revised, encoding="utf-8")
        (candidate / total.path.name).write_text(updated_total, encoding="utf-8")

        revision, digest = tx.manifest_state(workspace)
        live_manifest = json.loads((workspace / tx.MANIFEST_REL).read_text(encoding="utf-8"))
        from tests.fixture_builder import _rebuild_manifest
        _rebuild_manifest(candidate, list(live_manifest.get("selected_modules", [])))
        marker = {
            "schema": "discovery-call-candidate-receipt/v1",
            "context_id": total.frontmatter["context_id"],
            "run_id": run_id,
            "source_manifest_revision": revision,
            "source_manifest_sha256": digest,
            "source_workspace": str(workspace.resolve()),
            "candidate_workspace": str(candidate.resolve()),
            "payload_sha256": tx.sha256_file(candidate / tx.MANIFEST_REL),
        }
        (candidate / "runtime" / "candidate-receipt.json").write_text(
            json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        committed = run_python(
            "commit_run.py",
            [
                str(workspace),
                "--candidate-workspace",
                str(candidate),
                "--expected-manifest-revision",
                str(revision),
                "--expected-manifest-sha256",
                digest,
                "--operation",
                "submit_letter_revision",
                "--json",
            ],
        )
        self.assertEqual(committed.returncode, 0, committed.stderr or committed.stdout)

    def test_approve_emit_begin_revision_reapprove_emit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_letter_workspace(root / "output")
            self._govern(workspace)
            blocked_strict = run_python(
                "validate_outputs.py", [str(workspace), "--strict", "--json"]
            )
            self.assertEqual(blocked_strict.returncode, 1)
            blocked_codes = {
                issue["code"] for issue in json.loads(blocked_strict.stdout)["issues"]
            }
            self.assertIn("ready_for_use_required", blocked_codes)

            record_action_assertion(workspace, event_id="facts-first", actor_id="reviewer-letter-facts", operation="review_letter_facts", artifact_type="customer_letter_internal")
            facts = self._govern(
                workspace,
                "--review-letter-facts",
                "--reviewer", "吴芳（客户信事实复核岗）",
                "--actor-id", "reviewer-letter-facts",
                "--action-event-id", "facts-first",
            )
            self.assertEqual(facts["operation"], "review_letter_facts")
            record_action_assertion(workspace, event_id="approve-first", actor_id="approver-li", operation="approve_letter", artifact_type="customer_letter_internal")
            approved = self._govern(
                workspace,
                "--approve-letter",
                "--approver",
                "李明（客户沟通审批岗）",
                "--actor-id",
                "approver-li",
                "--action-event-id",
                "approve-first",
            )
            self.assertEqual(approved["operation"], "approve_letter")
            internal = next(workspace.glob("*客户信（内部待审核稿）.md"))
            approved_meta = tx.parse_frontmatter(internal.read_text(encoding="utf-8"))
            self.assertEqual(approved_meta["review_status"], "approved")
            self.assertEqual(approved_meta["approved_content_version"], approved_meta["content_version"])
            self.assertRegex(approved_meta["approved_body_sha256"], r"^[0-9a-f]{64}$")

            record_external_request(workspace, event_id="request-first")
            emitted = self._govern(
                workspace,
                "--emit-external",
                "--actor-id",
                "requester-wang",
                "--request-event-id",
                "request-first",
            )
            self.assertEqual(emitted["operation"], "emit_external")
            external = next(workspace.glob("*客户信（外发版）.md"))
            first_external_hash = hashlib.sha256(external.read_bytes()).hexdigest()

            record_action_assertion(workspace, event_id="revision-first", actor_id="letter-editor", operation="begin_letter_revision", artifact_type="customer_letter_internal")
            revision = self._govern(
                workspace,
                "--begin-letter-revision",
                "--reviewer",
                "赵敏（客户信修订岗）",
                "--actor-id",
                "letter-editor",
                "--action-event-id",
                "revision-first",
            )
            self.assertEqual(revision["operation"], "begin_letter_revision")
            self.assertFalse(external.exists())
            archives = list((workspace / "archive" / "letters").glob("*.md"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(hashlib.sha256(archives[0].read_bytes()).hexdigest(), first_external_hash)
            revision_meta = tx.parse_frontmatter(internal.read_text(encoding="utf-8"))
            self.assertEqual(revision_meta["review_status"], "changes_requested")
            self.assertTrue(all(not revision_meta[field] for field in validator.APPROVAL_FIELDS))

            self._submit_revision(workspace, root / "revision-candidate")
            pending_meta = tx.parse_frontmatter(internal.read_text(encoding="utf-8"))
            self.assertEqual(pending_meta["review_status"], "pending")
            self.assertIn("十月技术交流", internal.read_text(encoding="utf-8"))

            record_action_assertion(workspace, event_id="facts-second", actor_id="reviewer-letter-facts", operation="review_letter_facts", artifact_type="customer_letter_internal")
            self._govern(
                workspace,
                "--review-letter-facts",
                "--reviewer", "吴芳（客户信事实复核岗）",
                "--actor-id", "reviewer-letter-facts",
                "--action-event-id", "facts-second",
            )
            record_action_assertion(workspace, event_id="approve-second", actor_id="approver-zhou", operation="approve_letter", artifact_type="customer_letter_internal")
            reapproved = self._govern(
                workspace,
                "--approve-letter",
                "--approver",
                "周岚（客户沟通审批岗）",
                "--actor-id",
                "approver-zhou",
                "--action-event-id",
                "approve-second",
            )
            self.assertEqual(reapproved["operation"], "approve_letter")
            record_external_request(workspace, event_id="request-second")
            reemitted = self._govern(
                workspace,
                "--emit-external",
                "--actor-id",
                "requester-wang",
                "--request-event-id",
                "request-second",
            )
            self.assertEqual(reemitted["operation"], "emit_external")
            latest_external = next(workspace.glob("*客户信（外发版）.md"))
            self.assertIn("十月技术交流", latest_external.read_text(encoding="utf-8"))
            self.assertEqual(len(list((workspace / "archive" / "letters").glob("*.md"))), 1)

            final_validation = self._govern(workspace)
            self.assertEqual(final_validation["errors"], 0)
            history = internal.read_text(encoding="utf-8")
            self.assertIn("批准内部稿", history)
            self.assertIn("归档现行外发版并开始修订", history)
            self.assertIn("生成客户信外发版", history)

            record_action_assertion(workspace, event_id="ready-letter-final", actor_id="ready-letter", operation="mark_ready:letter", artifact_type="comprehensive_report")
            ready = self._govern(
                workspace,
                "--mark-ready",
                "--reviewer",
                "陈洁（交付就绪审核岗）",
                "--actor-id",
                "ready-letter",
                "--action-event-id",
                "ready-letter-final",
            )
            self.assertEqual(ready["operation"], "mark_ready")
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            total_meta = tx.parse_frontmatter(total.read_text(encoding="utf-8"))
            self.assertEqual(total_meta["ready_for_use"], "true")
            self.assertEqual(total_meta["readiness_content_version"], total_meta["content_version"])
            runtime_manifest = json.loads(
                (workspace / "runtime" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(runtime_manifest["ready_for_use"])
            strict = self._govern(workspace, "--strict")
            self.assertEqual(strict["errors"], 0)


if __name__ == "__main__":
    unittest.main()
