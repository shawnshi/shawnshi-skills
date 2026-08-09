import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import fhir_external_acceptance as acceptance
from garmin_fhir_adapter import create_fhir_bundle, create_observation


class FhirExternalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        observation = create_observation(
            42.0,
            "2026-08-08",
            "hrv_ms",
            source_sha256="1" * 64,
        )
        self.bundle = create_fhir_bundle(
            [observation],
            source_sha256="1" * 64,
            recorded_at="2026-08-08T00:00:00+00:00",
        )
        self.bundle_path = self.root / "bundle.json"
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")
        self.bundle_hash = hashlib.sha256(self.bundle_path.read_bytes()).hexdigest()
        self.tool = self.root / "validator.jar"
        self.package = self.root / "hl7.fhir.r4.core.tgz"
        self.tool.write_bytes(b"synthetic validator evidence")
        self.package.write_bytes(b"synthetic r4 package evidence")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _artifact(path: Path) -> dict:
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def _evidence(self) -> dict:
        return {
            "version": 1,
            "bundle_sha256": self.bundle_hash,
            "gates": {
                "r4_structure": {"required": False, "status": "not_requested"},
                "profile_ig": {"required": False, "status": "not_requested"},
                "terminology": {"required": False, "status": "not_requested"},
                "receiver": {"required": False, "status": "not_requested"},
            },
        }

    def _evaluate(self, evidence: dict) -> dict:
        evidence_path = self.root / "evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        return acceptance.evaluate_acceptance(self.bundle_path, evidence_path)

    def test_no_required_gate_cannot_be_reported_as_passed(self):
        result = self._evaluate(self._evidence())
        self.assertFalse(result["ok"])
        self.assertFalse(result["clinical_interoperability"])

    def test_unsigned_hash_bound_r4_assertion_cannot_close_external_gate(self):
        evidence = self._evidence()
        evidence["gates"]["r4_structure"] = {
            "required": True,
            "status": "passed",
            "validator": {**self._artifact(self.tool), "version": "synthetic-tested-version"},
            "r4_package": {
                **self._artifact(self.package),
                "id": "hl7.fhir.r4.core",
                "version": "4.0.1",
            },
            "result": {"exit_code": 0, "error_count": 0, "fatal_count": 0},
        }
        result = self._evaluate(evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "external_acceptance_not_established")
        self.assertEqual(result["evidence_trust"], "caller_supplied_hash_bound_not_signed")
        self.assertTrue(result["evidence_contract_ok"])
        self.assertFalse(result["external_acceptance_established"])
        self.assertEqual(result["external_gates"]["r4_structure"]["status"], "indeterminate")
        self.assertEqual(
            result["external_gates"]["r4_structure"]["reason"],
            "unsigned_caller_evidence_cannot_establish_pass",
        )
        self.assertEqual(len(result["hash_checked_artifacts"]), 2)

    def test_schema_or_validator_not_run_remains_failed_when_required(self):
        evidence = self._evidence()
        evidence["gates"]["r4_structure"] = {
            "required": True,
            "status": "indeterminate",
        }
        result = self._evaluate(evidence)
        self.assertFalse(result["ok"])

    def test_required_coding_profile_fails_for_text_only_export(self):
        evidence = self._evidence()
        evidence["gates"]["profile_ig"] = {
            "required": True,
            "status": "passed",
            "profiles": [
                {
                    "resource_type": resource_type,
                    "canonical": f"https://example.test/StructureDefinition/{resource_type}",
                    "version": "1.0.0",
                    "required_coding": resource_type == "Observation",
                    "package": self._artifact(self.package),
                }
                for resource_type in ("Bundle", "Observation", "Provenance")
            ],
            "result": {"exit_code": 0, "error_count": 0, "fatal_count": 0},
        }
        result = self._evaluate(evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["external_gates"]["profile_ig"]["reason"],
            "text_only_export_conflicts_with_required_coding",
        )

    def test_text_only_export_cannot_claim_terminology_equivalence(self):
        evidence = self._evidence()
        evidence["gates"]["terminology"] = {"required": True, "status": "passed"}
        result = self._evaluate(evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["external_gates"]["terminology"]["status"], "failed")

    def test_receiver_transport_without_attestation_cannot_pass(self):
        evidence = self._evidence()
        evidence["gates"]["receiver"] = {
            "required": True,
            "status": "passed",
            "result": {
                "actual_delivery": True,
                "synthetic_data": True,
                "real_health_data": False,
                "transport_status": 200,
                "operation_outcome_error_count": 0,
            },
        }
        result = self._evaluate(evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["external_gates"]["receiver"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
