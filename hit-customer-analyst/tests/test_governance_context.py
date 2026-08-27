from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.common import SCRIPTS, load_module


governance = load_module("discovery_call_governance", SCRIPTS / "governance.py")
NOW = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
CONTEXT_ID = "dcx-20260827-abcdefgh"
CUSTOMER_ID = "customer.demo"


def registry(*, display_name: str = "李明（外发审批岗）", role: str = "external_approver") -> dict:
    return {
        "schema": governance.GOVERNANCE_SCHEMA,
        "context_id": CONTEXT_ID,
        "customer_id": CUSTOMER_ID,
        "runtime_actor_id": "employee-runtime",
        "updated_at": "2026-08-27T07:00:00Z",
        "actors": {
            "employee-1001": {
                "display_name": display_name,
                "actor_type": "human",
                "identity_provider": "corp-sso",
                "status": "active",
                "grants": [
                    {
                        "grant_id": "grant-1001",
                        "role": role,
                        "operations": ["approve_letter", "emit_external", "mark_ready:letter"],
                        "business_modes": ["letter"],
                        "customer_ids": [CUSTOMER_ID],
                        "valid_from": "2026-08-01T00:00:00Z",
                        "expires_at": "2026-09-01T00:00:00Z",
                    }
                ],
            }
        },
        "external_requests": {},
    }


class GovernanceContextTests(unittest.TestCase):
    def workspace(self, payload: dict) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        runtime = root / "runtime"
        runtime.mkdir()
        payload.setdefault("action_assertions", {})
        key = Ed25519PrivateKey.generate()
        issuer, key_id = "test-host", "test-key"
        identity = {
            "schema": governance.IDENTITY_ASSERTION_SCHEMA,
            "issuer": issuer,
            "audience": governance.TRUST_AUDIENCE,
            "key_id": key_id,
            "issued_at": "2026-01-01T00:00:00Z",
            "expires_at": "2027-01-01T00:00:00Z",
        }
        payload["identity_assertion"] = identity
        canonical = json.dumps(governance.identity_assertion_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        identity["signature"] = base64.b64encode(key.sign(canonical)).decode()
        for event_id, event in payload.get("external_requests", {}).items():
            event.update({
                "schema": governance.EXTERNAL_REQUEST_ASSERTION_SCHEMA,
                "request_id": event_id,
                "operation": "emit_external",
                "business_mode": "letter",
                "session_id": "session-test",
                "nonce": "0123456789abcdef0123456789abcdef",
                "issuer": issuer,
                "audience": governance.TRUST_AUDIENCE,
                "key_id": key_id,
                "issued_at": event["requested_at"],
            })
            canonical = json.dumps(governance.external_request_assertion_payload(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            event["signature"] = base64.b64encode(key.sign(canonical)).decode()
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        os.environ[governance.PUBLIC_KEY_ENV] = base64.b64encode(public).decode()
        os.environ[governance.TRUSTED_ISSUER_ENV] = issuer
        os.environ[governance.TRUSTED_KEY_ID_ENV] = key_id
        (runtime / "governance-context.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return root

    def test_resolves_only_scoped_active_human_grant(self):
        root = self.workspace(registry())
        resolved = governance.resolve_actor(
            root,
            actor_id="employee-1001",
            display_name="李明（外发审批岗）",
            operation="approve_letter",
            required_roles={"external_approver"},
            context_id=CONTEXT_ID,
            customer_id=CUSTOMER_ID,
            business_mode="letter",
            at=NOW,
        )
        self.assertEqual(resolved.actor_id, "employee-1001")
        self.assertEqual(resolved.grant_id, "grant-1001")

    def test_generic_display_cannot_become_an_approver(self):
        root = self.workspace(registry(display_name="AI"))
        with self.assertRaises(governance.GovernanceError):
            governance.resolve_actor(
                root,
                actor_id="employee-1001",
                display_name="AI",
                operation="approve_letter",
                required_roles={"external_approver"},
                context_id=CONTEXT_ID,
                customer_id=CUSTOMER_ID,
                business_mode="letter",
                at=NOW,
            )

    def test_wrong_role_or_expired_grant_fails_closed(self):
        wrong = self.workspace(registry(role="evidence_reviewer"))
        with self.assertRaises(governance.GovernanceError):
            governance.resolve_actor(
                wrong,
                actor_id="employee-1001",
                display_name="李明（外发审批岗）",
                operation="approve_letter",
                required_roles={"external_approver"},
                context_id=CONTEXT_ID,
                customer_id=CUSTOMER_ID,
                business_mode="letter",
                at=NOW,
            )
        expired_payload = registry()
        expired_payload["actors"]["employee-1001"]["grants"][0]["expires_at"] = "2026-08-27T07:59:59Z"
        expired = self.workspace(expired_payload)
        with self.assertRaises(governance.GovernanceError):
            governance.resolve_actor(
                expired,
                actor_id="employee-1001",
                display_name="李明（外发审批岗）",
                operation="approve_letter",
                required_roles={"external_approver"},
                context_id=CONTEXT_ID,
                customer_id=CUSTOMER_ID,
                business_mode="letter",
                at=NOW,
            )

    def test_external_request_is_after_approval_bound_and_single_use(self):
        payload = registry(role="requester")
        payload["external_requests"]["request-1001"] = {
            "event_type": "external_output_requested",
            "actor_id": "employee-1001",
            "source": "authenticated_user_turn",
            "verified": True,
            "context_id": CONTEXT_ID,
            "customer_id": CUSTOMER_ID,
            "approval_run_id": "dcr-20260827T070000-abcd",
            "internal_content_version": "2",
            "approved_body_sha256": "a" * 64,
            "approved_context_sha256": "b" * 64,
            "requested_at": "2026-08-27T07:55:00Z",
            "expires_at": "2026-08-27T08:05:00Z",
            "consumed_at": None,
            "consumed_by_run_id": None,
        }
        root = self.workspace(payload)
        internal = {
            "latest_run_id": "dcr-20260827T070000-abcd",
            "content_version": "2",
            "approved_body_sha256": "a" * 64,
            "approved_context_sha256": "b" * 64,
            "approved_at": "2026-08-27T07:00:00Z",
        }
        total = {
            "context_id": CONTEXT_ID,
            "customer_id": CUSTOMER_ID,
            "business_mode": "letter",
        }
        loaded, event, actor = governance.resolve_external_request(
            root,
            event_id="request-1001",
            actor_id="employee-1001",
            internal=internal,
            total=total,
            at=NOW,
        )
        self.assertEqual(event["actor_id"], actor.actor_id)
        consumed = governance.consume_external_request(
            loaded,
            event_id="request-1001",
            consumed_at="2026-08-27T08:00:00Z",
            run_id="dcr-20260827T080000-efgh",
        )
        self.assertEqual(
            consumed["external_requests"]["request-1001"]["consumed_by_run_id"],
            "dcr-20260827T080000-efgh",
        )
        consumed_root = self.workspace(consumed)
        with self.assertRaises(governance.GovernanceError):
            governance.resolve_external_request(
                consumed_root,
                event_id="request-1001",
                actor_id="employee-1001",
                internal=internal,
                total=total,
                at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
