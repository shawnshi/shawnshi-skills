from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import (
    SCRIPTS,
    SKILL_ROOT,
    attest_candidate,
    candidate_attestation as ca,
    governance,
    load_json,
    load_module,
)


validator = load_module(
    "discovery_call_gate_attestation_validator",
    SCRIPTS / "validate_outputs.py",
)


class CandidateAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.formal = self.root / "source"
        self.formal.mkdir()
        nonce_dir = self.root / "host-nonces"
        nonce_dir.mkdir(mode=0o700)
        nonce_dir.chmod(0o700)
        os.environ[governance.NONCE_DIR_ENV] = str(nonce_dir.resolve())
        self.candidate = self.root / "candidate"
        (self.candidate / "runtime").mkdir(parents=True)
        manifest_path = self.candidate / "runtime" / "manifest.json"
        self.intake_gate = {
            "gate_id": "gate-test-001",
            "safety_authorization_codes": ["unauthorized_internal_source"],
        }
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": "discovery-call-runtime/v1",
                    "customer_id": "cust-attestation-test",
                    "intake_preflight": self.intake_gate,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.marker = {
            "schema": ca.MARKER_SCHEMA,
            "context_id": "dcx-20260827-Abcd1234",
            "run_id": "dcr-20260827T120000-Ab12",
            "source_manifest_revision": 7,
            "source_manifest_sha256": hashlib.sha256(b"source-manifest").hexdigest(),
            "source_workspace": str(self.formal.resolve()),
            "candidate_workspace": str(self.candidate.resolve()),
            "input_payload_sha256": hashlib.sha256(b"candidate-input").hexdigest(),
            "final_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }
        (self.candidate / ca.MARKER_REL).write_text(
            json.dumps(self.marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.attestation_path = attest_candidate(self.candidate)
        self.expected = load_json(self.candidate / ca.REQUEST_REL)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_host_attestation_and_packaged_schemas(self):
        verified = ca.verify_candidate_attestation(self.attestation_path, expected=self.expected)
        self.assertRegex(verified.attestation_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(verified.issuer, "discovery-call-test-candidate-host")
        schema_payloads = {
            "candidate-attestation.schema.json": load_json(self.attestation_path),
            "candidate-seal-request.schema.json": self.expected,
        }
        for name, payload in schema_payloads.items():
            schema = load_json(SKILL_ROOT / "schemas" / name)
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(
                validator.validate_json_contract(payload, schema),
                [],
            )

    def test_missing_independent_trust_root_and_drift_fail_closed(self):
        with patch.dict(os.environ, {ca.TRUSTED_KEYS_ENV: ""}, clear=False):
            with self.assertRaises(ca.CandidateAttestationError):
                ca.verify_candidate_attestation(self.attestation_path, expected=self.expected)

        drifted = dict(self.expected)
        drifted["input_payload_sha256"] = "0" * 64
        with self.assertRaises(ca.CandidateAttestationError):
            ca.verify_candidate_attestation(self.attestation_path, expected=drifted)

    def test_expired_attestation_fails_closed(self):
        envelope = load_json(self.attestation_path)
        expires = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
        with self.assertRaises(ca.CandidateAttestationError):
            ca.verify_candidate_attestation(
                self.attestation_path,
                expected=self.expected,
                at=expires + timedelta(seconds=1),
            )
        verified = ca.verify_candidate_attestation(
            self.attestation_path,
            expected=self.expected,
        )
        with self.assertRaisesRegex(ca.CandidateAttestationError, "已过期"):
            ca.claim_candidate_attestation_nonce(
                verified,
                workspace=self.formal,
                at=expires + timedelta(seconds=1),
            )

    def test_wrong_audience_key_extra_and_duplicate_fields_fail_closed(self):
        original = self.attestation_path.read_text(encoding="utf-8")
        envelope = json.loads(original)
        mutations = (
            {**envelope, "audience": "discovery-call-capability"},
            {**envelope, "key_id": "untrusted-candidate-key"},
            {**envelope, "unexpected": "not-allowed"},
        )
        for mutation in mutations:
            with self.subTest(mutation=set(mutation) - set(envelope) or mutation.get("audience") or mutation.get("key_id")):
                self.attestation_path.write_text(json.dumps(mutation, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ca.CandidateAttestationError):
                    ca.verify_candidate_attestation(self.attestation_path, expected=self.expected)
        duplicate = original.rstrip()[:-1] + ',"nonce":"AAAAAAAAAAAAAAAAAAAAAA"}'
        self.attestation_path.write_text(duplicate, encoding="utf-8")
        with self.assertRaises(ca.CandidateAttestationError):
            ca.verify_candidate_attestation(self.attestation_path, expected=self.expected)

    def test_N133_durable_gate_attestation_blocks_gate_time_and_workspace_forgery(self):
        verified = ca.verify_candidate_attestation(
            self.attestation_path,
            expected=self.expected,
        )
        ca.claim_candidate_attestation_nonce(verified, workspace=self.formal)
        audit = verified.audit_summary(self.expected)
        after_expiry = datetime.fromisoformat(
            audit["expires_at"].replace("Z", "+00:00")
        ) + timedelta(days=30)
        historical = ca.verify_persisted_candidate_attestation(
            audit,
            current_intake_gate=self.intake_gate,
            current_workspace=self.formal,
            at=after_expiry,
        )
        self.assertEqual(historical.attestation_sha256, audit["attestation_sha256"])
        self.assertTrue(audit["nonce"])
        self.assertTrue(audit["signature"])

        cleared_gate = {
            **self.intake_gate,
            "safety_authorization_codes": [],
        }
        with self.assertRaisesRegex(ca.CandidateAttestationError, "重新签章"):
            ca.verify_persisted_candidate_attestation(
                audit,
                current_intake_gate=cleared_gate,
                current_workspace=self.formal,
                at=after_expiry,
            )

        double_edited = dict(audit)
        double_edited["intake_gate_sha256"] = ca.canonical_intake_gate_sha256(
            cleared_gate
        )
        with self.assertRaisesRegex(ca.CandidateAttestationError, "签名无效"):
            ca.verify_persisted_candidate_attestation(
                double_edited,
                current_intake_gate=cleared_gate,
                current_workspace=self.formal,
                at=after_expiry,
            )

        forged_local_time = {**audit, "verified_at": audit["issued_at"]}
        with self.assertRaisesRegex(ca.CandidateAttestationError, "字段不完整|未知"):
            ca.verify_persisted_candidate_attestation(
                forged_local_time,
                current_intake_gate=self.intake_gate,
                current_workspace=self.formal,
                at=after_expiry,
            )

        clone = self.root / "clone"
        clone.mkdir()
        with self.assertRaisesRegex(ca.CandidateAttestationError, "禁止克隆"):
            ca.verify_persisted_candidate_attestation(
                audit,
                current_intake_gate=self.intake_gate,
                current_workspace=clone,
                at=after_expiry,
            )

    def test_external_lifecycle_gate_reader_rejects_manifest_double_clear(self):
        verified = ca.verify_candidate_attestation(
            self.attestation_path,
            expected=self.expected,
        )
        ca.claim_candidate_attestation_nonce(verified, workspace=self.formal)
        audit = verified.audit_summary(self.expected)
        workspace = self.formal
        (workspace / "runtime").mkdir(parents=True)
        manifest_path = workspace / "runtime" / "manifest.json"
        manifest = {
            "schema": "discovery-call-runtime/v1",
            "transaction_sequence": 8,
            "intake_preflight": self.intake_gate,
            "candidate_attestation": audit,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(
            validator.internal_only_safety_authorization_codes(workspace),
            ["unauthorized_internal_source"],
        )

        cleared_gate = {
            **self.intake_gate,
            "safety_authorization_codes": [],
        }
        manifest["intake_preflight"] = cleared_gate
        manifest["candidate_attestation"] = {
            **audit,
            "intake_gate_sha256": ca.canonical_intake_gate_sha256(cleared_gate),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        attacked_bytes = manifest_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "candidate_gate_attestation_invalid"):
            validator.internal_only_safety_authorization_codes(workspace)
        self.assertEqual(manifest_path.read_bytes(), attacked_bytes)


if __name__ == "__main__":
    unittest.main()
