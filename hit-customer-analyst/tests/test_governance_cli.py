from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.common import run_python
from tests.fixture_builder import build_pending_letter_workspace, record_action_assertion, record_external_request


def hashes(workspace: Path) -> dict[str, str]:
    selected = list(workspace.glob("*.md")) + list((workspace / "runtime").glob("*.json"))
    return {
        str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(selected)
        if path.is_file() and not path.is_symlink()
    }


class GovernanceCliTests(unittest.TestCase):
    def approve(self, workspace: Path) -> None:
        record_action_assertion(workspace, event_id="institution-cli", actor_id="reviewer-institution", operation="approve_artifact:institution", artifact_type="institution_research")
        institution = run_python(
            "validate_outputs.py",
            [str(workspace), "--approve-artifact", "institution", "--reviewer", "周洁（机构事实审核岗）", "--actor-id", "reviewer-institution", "--action-event-id", "institution-cli", "--json"],
        )
        self.assertEqual(institution.returncode, 0, institution.stderr or institution.stdout)
        record_action_assertion(workspace, event_id="facts-cli", actor_id="reviewer-letter-facts", operation="review_letter_facts", artifact_type="customer_letter_internal")
        facts = run_python(
            "validate_outputs.py",
            [str(workspace), "--review-letter-facts", "--reviewer", "吴芳（客户信事实复核岗）", "--actor-id", "reviewer-letter-facts", "--action-event-id", "facts-cli", "--json"],
        )
        self.assertEqual(facts.returncode, 0, facts.stderr or facts.stdout)
        record_action_assertion(workspace, event_id="approve-cli", actor_id="approver-li", operation="approve_letter", artifact_type="customer_letter_internal")
        approved = run_python(
            "validate_outputs.py",
            [str(workspace), "--approve-letter", "--approver", "李明（客户沟通审批岗）", "--actor-id", "approver-li", "--action-event-id", "approve-cli", "--json"],
        )
        self.assertEqual(approved.returncode, 0, approved.stderr or approved.stdout)

    def test_missing_or_untrusted_actor_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            before = hashes(workspace)
            missing = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--approve-letter",
                    "--approver",
                    "李明（客户沟通审批岗）",
                    "--json",
                ],
            )
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(hashes(workspace), before)
            record_action_assertion(workspace, event_id="facts-untrusted", actor_id="reviewer-letter-facts", operation="review_letter_facts", artifact_type="customer_letter_internal")
            facts = run_python(
                "validate_outputs.py",
                [str(workspace), "--review-letter-facts", "--reviewer", "吴芳（客户信事实复核岗）", "--actor-id", "reviewer-letter-facts", "--action-event-id", "facts-untrusted", "--json"],
            )
            self.assertEqual(facts.returncode, 0, facts.stderr or facts.stdout)
            record_action_assertion(workspace, event_id="approve-untrusted", actor_id="approver-li", operation="approve_letter", artifact_type="customer_letter_internal")
            before = hashes(workspace)
            generic = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--approve-letter",
                    "--approver",
                    "领导",
                    "--actor-id",
                    "unknown-actor",
                    "--action-event-id",
                    "approve-untrusted",
                    "--json",
                ],
            )
            self.assertEqual(generic.returncode, 1)
            self.assertEqual(hashes(workspace), before)

    def test_letter_cannot_be_ready_before_external_request_and_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            self.approve(workspace)
            before = hashes(workspace)
            record_action_assertion(workspace, event_id="ready-before-external", actor_id="ready-letter", operation="mark_ready:letter", artifact_type="comprehensive_report")
            before = hashes(workspace)
            ready = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--mark-ready",
                    "--reviewer",
                    "陈洁（交付就绪审核岗）",
                    "--actor-id",
                    "ready-letter",
                    "--action-event-id",
                    "ready-before-external",
                    "--json",
                ],
            )
            self.assertEqual(ready.returncode, 1)
            payload = json.loads(ready.stdout)
            self.assertIn("letter_external_required", payload["issues"][0]["message"])
            self.assertEqual(hashes(workspace), before)

    def test_external_requires_bound_event_and_consumes_it_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            self.approve(workspace)
            before = hashes(workspace)
            missing = run_python(
                "validate_outputs.py",
                [str(workspace), "--emit-external", "--actor-id", "requester-wang", "--json"],
            )
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(hashes(workspace), before)
            record_external_request(workspace, event_id="request-cli")
            emitted = run_python(
                "validate_outputs.py",
                [
                    str(workspace),
                    "--emit-external",
                    "--actor-id",
                    "requester-wang",
                    "--request-event-id",
                    "request-cli",
                    "--json",
                ],
            )
            self.assertEqual(emitted.returncode, 0, emitted.stderr or emitted.stdout)
            governance = json.loads(
                (workspace / "runtime" / "governance-context.json").read_text(encoding="utf-8")
            )
            event = governance["external_requests"]["request-cli"]
            self.assertTrue(event["consumed_at"])
            self.assertTrue(event["consumed_by_run_id"])
            self.assertEqual(len(list(workspace.glob("*客户信（外发版）.md"))), 1)


if __name__ == "__main__":
    unittest.main()
