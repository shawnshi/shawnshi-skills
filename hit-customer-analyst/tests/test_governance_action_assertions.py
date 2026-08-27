from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests import fixture_builder as fixtures
from tests.common import SCRIPTS, governance, load_json, load_module, run_python, runtime_tx as tx


validator = load_module("governance_schema_validator", SCRIPTS / "validate_outputs.py")


def workspace_hashes(workspace: Path) -> dict[str, str]:
    paths = list(workspace.glob("*.md")) + list((workspace / "runtime").glob("*.json"))
    return {
        str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if path.is_file() and not path.is_symlink()
    }


class GovernanceActionAssertionTests(unittest.TestCase):
    def invoke(self, workspace: Path, *args: str):
        return run_python("validate_outputs.py", [str(workspace), *args, "--json"])

    def facts_args(self, event_id: str) -> list[str]:
        return [
            "--review-letter-facts", "--reviewer", "吴芳（客户信事实复核岗）",
            "--actor-id", "reviewer-letter-facts", "--action-event-id", event_id,
        ]

    def test_signed_context_matches_schema_and_actor_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = fixtures.build_pending_letter_workspace(Path(temporary) / "output")
            payload = load_json(workspace / "runtime" / "governance-context.json")
            schema = json.loads((Path(__file__).parents[1] / "schemas" / "governance-context.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(validator.validate_json_contract(payload, schema), [])
            governance.load_governance_context(workspace)
            payload["actors"]["approver-li"]["display_name"] = "伪造审批人"
            tx.atomic_write_json(workspace / "runtime" / "governance-context.json", payload)
            with self.assertRaises(governance.GovernanceError):
                governance.load_governance_context(workspace)

    def test_two_independent_signed_actions_complete_letter_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = fixtures.build_pending_letter_workspace(Path(temporary) / "output")
            fixtures.record_action_assertion(
                workspace, event_id="facts-positive", actor_id="reviewer-letter-facts",
                operation="review_letter_facts", artifact_type="customer_letter_internal",
            )
            facts = self.invoke(workspace, *self.facts_args("facts-positive"))
            self.assertEqual(facts.returncode, 0, facts.stderr or facts.stdout)
            fixtures.record_action_assertion(
                workspace, event_id="approve-positive", actor_id="approver-li",
                operation="approve_letter", artifact_type="customer_letter_internal",
            )
            approved = self.invoke(
                workspace, "--approve-letter", "--approver", "李明（客户沟通审批岗）",
                "--actor-id", "approver-li", "--action-event-id", "approve-positive",
            )
            self.assertEqual(approved.returncode, 0, approved.stderr or approved.stdout)
            internal = tx.parse_frontmatter(next(workspace.glob("*客户信（内部待审核稿）.md")).read_text(encoding="utf-8"))
            self.assertEqual(internal["fact_review_action_event_id"], "facts-positive")
            self.assertEqual(internal["approval_action_event_id"], "approve-positive")
            self.assertNotEqual(internal["fact_reviewer_actor_id"], internal["approver_actor_id"])

    def test_expired_or_wrong_target_fails_without_workspace_write(self):
        for variant in ("expired", "wrong_hash"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                workspace = fixtures.build_pending_letter_workspace(Path(temporary) / "output")
                event_id = f"facts-{variant}"
                fixtures.record_action_assertion(
                    workspace, event_id=event_id, actor_id="reviewer-letter-facts",
                    operation="review_letter_facts", artifact_type="customer_letter_internal",
                )
                path = workspace / "runtime" / "governance-context.json"
                payload = load_json(path)
                event = payload["action_assertions"][event_id]
                if variant == "expired":
                    now = datetime.now(timezone.utc)
                    event["issued_at"] = (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
                    event["expires_at"] = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
                else:
                    event["target_body_sha256"] = "0" * 64
                event["signature"] = fixtures._sign(
                    fixtures._GOVERNANCE_SIGNERS[event["issuer"]], governance.action_assertion_payload(event)
                )
                tx.atomic_write_json(path, payload)
                manifest = load_json(workspace / tx.MANIFEST_REL)
                fixtures._rebuild_manifest(workspace, list(manifest["selected_modules"]))
                before = workspace_hashes(workspace)
                result = self.invoke(workspace, *self.facts_args(event_id))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(workspace_hashes(workspace), before)

    def test_same_nonce_replay_in_clone_fails_without_workspace_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = fixtures.build_pending_letter_workspace(root / "output")
            fixtures.record_action_assertion(
                workspace, event_id="facts-cross-clone", actor_id="reviewer-letter-facts",
                operation="review_letter_facts", artifact_type="customer_letter_internal",
            )
            clone = root / "clone" / workspace.name
            clone.parent.mkdir()
            shutil.copytree(workspace, clone)
            first = self.invoke(workspace, *self.facts_args("facts-cross-clone"))
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            before = workspace_hashes(clone)
            replay = self.invoke(clone, *self.facts_args("facts-cross-clone"))
            self.assertEqual(replay.returncode, 1)
            self.assertIn("跨工作区", replay.stdout)
            self.assertEqual(workspace_hashes(clone), before)


if __name__ == "__main__":
    unittest.main()
