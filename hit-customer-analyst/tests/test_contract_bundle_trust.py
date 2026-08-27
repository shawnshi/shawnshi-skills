from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.common import CONFIG, SCRIPTS, SKILL_ROOT, load_module


validator = load_module("contract_bundle_trust_validator", SCRIPTS / "validate_outputs.py")


class ContractBundleTrustTests(unittest.TestCase):
    def _schema_copy(self, root: Path) -> Path:
        target = root / "schemas"
        shutil.copytree(SKILL_ROOT / "schemas", target)
        return target

    def _validate_with_schema_root(self, schema_root: Path, profile: str):
        workspace = schema_root.parent / f"workspace-{profile}"
        workspace.mkdir(exist_ok=True)
        with mock.patch.object(validator, "SCHEMA_ROOT", schema_root):
            return validator.validate(
                workspace,
                strict=profile == "release",
                emit=False,
                validation_profile=profile,
            )

    def test_original_contract_bundle_matches_code_trust_anchors(self):
        issues = []
        self.assertTrue(validator.validate_trusted_contract_bundle(issues), issues)
        self.assertEqual(issues, [])
        self.assertEqual(
            set(validator.TRUSTED_SCHEMA_SHA256),
            {path.name for path in (SKILL_ROOT / "schemas").glob("*.schema.json")},
        )
        self.assertTrue(
            all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in validator.TRUSTED_SCHEMA_SHA256.values())
        )
        self.assertRegex(validator.TRUSTED_BUSINESS_CONFIG_SHA256, r"^[0-9a-f]{64}$")

    def test_empty_search_plan_schema_fails_candidate_and_release_without_rewrite(self):
        for profile in ("candidate", "release"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                schema_root = self._schema_copy(Path(temporary))
                target = schema_root / "search-plan.schema.json"
                target.write_text("{}\n", encoding="utf-8")
                issues, documents, result_path, operation = self._validate_with_schema_root(
                    schema_root, profile
                )
                self.assertEqual(
                    {issue.code for issue in issues},
                    {"runtime_machine_contract_unavailable"},
                )
                self.assertEqual(documents, [], "contract failure must precede artifact loading")
                self.assertIsNone(result_path)
                self.assertIsNone(operation)
                self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")

    def test_governance_schema_digest_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            schema_root = self._schema_copy(Path(temporary))
            target = schema_root / "governance-context.schema.json"
            target.write_text("{}\n", encoding="utf-8")
            issues, documents, _, _ = self._validate_with_schema_root(schema_root, "candidate")
            self.assertEqual(
                {issue.code for issue in issues},
                {"runtime_machine_contract_unavailable"},
            )
            self.assertEqual(documents, [])
            self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")

    def test_missing_machine_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            schema_root = self._schema_copy(Path(temporary))
            (schema_root / "evidence-manifest.schema.json").unlink()
            issues, documents, _, _ = self._validate_with_schema_root(schema_root, "candidate")
            self.assertEqual(
                {issue.code for issue in issues},
                {"runtime_machine_contract_unavailable"},
            )
            self.assertEqual(documents, [])

    def test_business_mode_config_digest_tamper_fails_before_content_without_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "business-modes.json"
            shutil.copy2(CONFIG, config)
            config.write_text("{}\n", encoding="utf-8")
            workspace = root / "workspace"
            workspace.mkdir()
            with mock.patch.object(validator, "BUSINESS_CONFIG_PATH", config):
                issues, documents, result_path, operation = validator.validate(
                    workspace,
                    strict=False,
                    emit=False,
                    validation_profile="candidate",
                )
            self.assertEqual(
                {issue.code for issue in issues},
                {"runtime_business_contract_unavailable"},
            )
            self.assertEqual(documents, [])
            self.assertIsNone(result_path)
            self.assertIsNone(operation)
            self.assertEqual(config.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
