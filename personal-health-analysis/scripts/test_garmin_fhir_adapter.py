import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import garmin_fhir_adapter as fhir


SOURCE_SHA256 = "a" * 64


class FHIRResearchExportContractTests(unittest.TestCase):
    def test_status_declares_research_only_scope_without_data_access(self):
        status = fhir.get_export_status()
        self.assertEqual(status["status"], "FHIR_EXPORT_RESEARCH_ONLY")
        self.assertTrue(status["enabled"])
        self.assertFalse(status["clinical_interoperability"])
        self.assertFalse(status["data_accessed"])
        self.assertEqual(status["fhir_version"], "4.0.1")
        self.assertEqual(status["validation_scope"], "local_research_contract_only")
        self.assertEqual(set(status["external_gates"].values()), {"not_performed"})

    def test_observation_uses_text_semantics_and_no_loinc_mapping(self):
        observation = fhir.create_observation(
            42.5,
            "2026-08-08",
            "hrv_ms",
            source_sha256=SOURCE_SHA256,
            firmware_version="12.34",
        )
        self.assertEqual(observation["resourceType"], "Observation")
        self.assertEqual(observation["status"], "unknown")
        self.assertEqual(observation["valueQuantity"]["code"], "ms")
        self.assertIn("Garmin", observation["code"]["text"])
        self.assertNotIn("coding", observation["code"])
        self.assertNotIn("interpretation", observation)
        self.assertNotIn("referenceRange", observation)
        self.assertIn("consumer wearable", observation["note"][0]["text"].lower())

    def test_unsupported_or_invalid_observation_fails_closed(self):
        cases = (
            (42, "2026-08-08", "stress"),
            (True, "2026-08-08", "hrv_ms"),
            (float("nan"), "2026-08-08", "hrv_ms"),
            (42, "not-a-date", "hrv_ms"),
        )
        for value, date_str, metric in cases:
            with self.subTest(metric=metric, value=value):
                with self.assertRaises(fhir.FHIRContractError):
                    fhir.create_observation(
                        value,
                        date_str,
                        metric,
                        source_sha256=SOURCE_SHA256,
                    )
        with self.assertRaises(fhir.FHIRContractError):
            fhir.create_observation(
                42, "2026-08-08", "hrv_ms", source_sha256="not-a-digest"
            )
        with self.assertRaises(fhir.FHIRContractError):
            fhir.create_observation(
                42,
                "2026-08-08",
                "hrv_ms",
                source_sha256=SOURCE_SHA256,
                device_serial_hash="raw-device-serial",
            )

    def test_hash_fields_reject_normalization_and_non_string_values(self):
        invalid_values = ("A" * 64, f" {SOURCE_SHA256}", f"{SOURCE_SHA256} ", 1)
        for invalid in invalid_values:
            with self.subTest(field="source_sha256", value=repr(invalid)):
                with self.assertRaises(fhir.FHIRContractError):
                    fhir.create_observation(
                        42,
                        "2026-08-08",
                        "hrv_ms",
                        source_sha256=invalid,
                    )
            with self.subTest(field="device_serial_hash", value=repr(invalid)):
                with self.assertRaises(fhir.FHIRContractError):
                    fhir.create_observation(
                        42,
                        "2026-08-08",
                        "hrv_ms",
                        source_sha256=SOURCE_SHA256,
                        device_serial_hash=invalid,
                    )
            observation = fhir.create_observation(
                42, "2026-08-08", "hrv_ms", source_sha256=SOURCE_SHA256
            )
            with self.subTest(field="input_sha256", value=repr(invalid)):
                with self.assertRaises(fhir.FHIRContractError):
                    fhir.create_fhir_bundle(
                        [observation],
                        source_sha256=SOURCE_SHA256,
                        input_sha256=invalid,
                    )

    def test_bundle_contains_unique_full_urls_and_provenance(self):
        observations = [
            fhir.create_observation(
                42, "2026-08-08", "hrv_ms", source_sha256=SOURCE_SHA256
            ),
            fhir.create_observation(
                58,
                "2026-08-08",
                "resting_heart_rate_bpm",
                source_sha256=SOURCE_SHA256,
            ),
        ]
        bundle = fhir.create_fhir_bundle(
            observations,
            source_sha256=SOURCE_SHA256,
            recorded_at="2026-08-08T12:00:00+00:00",
        )
        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "collection")
        self.assertEqual(len(bundle["entry"]), 3)
        full_urls = [entry["fullUrl"] for entry in bundle["entry"]]
        self.assertEqual(len(full_urls), len(set(full_urls)))
        self.assertTrue(all(value.startswith("urn:uuid:") for value in full_urls))
        provenance = bundle["entry"][-1]["resource"]
        self.assertEqual(provenance["resourceType"], "Provenance")
        self.assertEqual(len(provenance["target"]), 2)
        fhir.validate_research_bundle(bundle)

    def test_export_requires_acknowledgement_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            input_path = root / "input.json"
            output_path = root / "bundle.json"
            input_path.write_text(
                json.dumps(
                    {
                        "source_sha256": SOURCE_SHA256,
                        "recorded_at": "2026-08-08T12:00:00+00:00",
                        "observations": [
                            {
                                "metric": "sleep_duration_seconds",
                                "date": "2026-08-08",
                                "value": 25200,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                denied = fhir.main(
                    ["export", "--input", str(input_path), "--output", str(output_path)]
                )
            self.assertEqual(denied, fhir.EXIT_AUTHORIZATION)
            self.assertFalse(output_path.exists())

            with contextlib.redirect_stdout(io.StringIO()):
                exported = fhir.main(
                    [
                        "export",
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--acknowledge-research-only",
                    ]
                )
            self.assertEqual(exported, fhir.EXIT_OK)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["resourceType"], "Bundle")
            provenance = payload["entry"][-1]["resource"]
            identifiers = {
                entity["what"]["identifier"]["system"]: entity["what"]["identifier"]["value"]
                for entity in provenance["entity"]
            }
            self.assertEqual(identifiers[fhir._SOURCE_HASH_SYSTEM], SOURCE_SHA256)
            self.assertEqual(
                identifiers[fhir._INPUT_HASH_SYSTEM],
                fhir.hashlib.sha256(input_path.read_bytes()).hexdigest(),
            )

            original = output_path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                exists = fhir.main(
                    [
                        "export",
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--acknowledge-research-only",
                    ]
                )
            self.assertEqual(exists, fhir.EXIT_OUTPUT_EXISTS)
            self.assertEqual(output_path.read_bytes(), original)

    def test_atomic_no_overwrite_preserves_concurrent_target(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output_path = Path(temp_root) / "bundle.json"
            observation = fhir.create_observation(
                42, "2026-08-08", "hrv_ms", source_sha256=SOURCE_SHA256
            )
            bundle = fhir.create_fhir_bundle(
                [observation], source_sha256=SOURCE_SHA256
            )
            original_link = fhir.os.link

            def create_racing_target(source, target):
                Path(target).write_text("RACE_SENTINEL", encoding="utf-8")
                return original_link(source, target)

            with mock.patch.object(fhir.os, "link", side_effect=create_racing_target):
                with self.assertRaises(FileExistsError):
                    fhir._atomic_write_json(bundle, output_path, overwrite=False)

            self.assertEqual(
                output_path.read_text(encoding="utf-8"), "RACE_SENTINEL"
            )
            self.assertEqual(list(output_path.parent.glob(".bundle.json.*.tmp")), [])

    def test_source_has_no_authentication_or_loinc_registry(self):
        source = Path(fhir.__file__).read_text(encoding="utf-8").lower()
        self.assertNotIn("get_client", source)
        self.assertNotIn("http://loinc.org", source)
        self.assertNotIn("loinc_codes", source)


if __name__ == "__main__":
    unittest.main()
