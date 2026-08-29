from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import (
    SCRIPTS,
    TEST_REQUEST_ISSUER,
    bind_intake_payload,
    load_module,
)


migration = load_module("discovery_call_workspace_migration", SCRIPTS / "migrate_workspace.py")
initializer = load_module("discovery_call_workspace_migration_initializer", SCRIPTS / "init_workspace.py")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class WorkspaceSubjectMigrationTests(unittest.TestCase):
    customer_name = "甲市中心医院"
    organization_scope = "甲市中心医院主院区"
    customer_id = "crm:account-legacy-001"

    def _legacy_workspace(self, root: Path, *, customer_id: str | None = None) -> Path:
        workspace = root / "legacy-workspace"
        runtime = workspace / "runtime"
        runtime.mkdir(parents=True)
        manifest = {
            "schema": "discovery-call-runtime/v1",
            "context_id": "dcx-20260827-abcd1234",
            "customer_id": customer_id or self.customer_id,
            "customer_display_name": self.customer_name,
            "organization_scope": self.organization_scope,
            "business_mode": "briefing",
            "route": "visit_prep",
            "depth": "quick",
            "latest_run_id": "dcr-20260827T010000-abcd",
            "content_version": "1",
            "stage": "scaffold",
            "ready_for_use": False,
            "selected_modules": ["institution", "strategy"],
            "authorization": {},
            "artifacts": {},
            "runtime_files": {},
            "transaction_sequence": 4,
            "updated_at": "2026-08-26T01:00:00Z",
        }
        (runtime / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return workspace

    def _intake(
        self,
        root: Path,
        *,
        entity_key: str = "cn-health-org-citya-hospital-001",
        jurisdiction: str = "CN-TEST-01",
        customer_id: str | None = None,
        id_source: str = "host_attested_external",
    ) -> Path:
        customer_id = customer_id or self.customer_id
        subject_payload = {
            "canonical_customer_name": self.customer_name,
            "canonical_entity_key": entity_key,
            "jurisdiction": jurisdiction,
        }
        subject_sha = hashlib.sha256(canonical_json(subject_payload).encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        subject = {
            "schema": "discovery-call-subject-resolution/v1",
            "attestation_id": "subject-migration-" + subject_sha[:16],
            "issuer": TEST_REQUEST_ISSUER,
            "customer_id": customer_id,
            "canonical_customer_name": self.customer_name,
            "canonical_entity_key": entity_key,
            "jurisdiction": jurisdiction,
            "canonical_subject_sha256": subject_sha,
            "organization_scope_sha256": hashlib.sha256(self.organization_scope.encode("utf-8")).hexdigest(),
            "id_source": id_source,
            "evidence_sha256": hashlib.sha256(("host-evidence|" + entity_key).encode("utf-8")).hexdigest(),
            "issued_at": iso(now - timedelta(minutes=1)),
            "expires_at": iso(now + timedelta(hours=1)),
        }
        payload = {
            "schema": "discovery-call-intake/v3",
            "request_id": "migration-request-001",
            "business_mode": "briefing",
            "candidate_sets": [
                {
                    "field": "customer_name",
                    "candidates": [{"candidate_id": "customer-1", "value": self.customer_name, "status": "asserted", "source_ref": "test:user:1"}],
                },
                {
                    "field": "organization_scope",
                    "candidates": [{"candidate_id": "scope-1", "value": self.organization_scope, "status": "asserted", "source_ref": "test:user:1"}],
                },
                {
                    "field": "target_role",
                    "candidates": [{"candidate_id": "role-1", "value": "信息中心主任", "status": "asserted", "source_ref": "test:user:1"}],
                },
                {
                    "field": "visit_objective",
                    "candidates": [{"candidate_id": "objective-1", "value": "确认数字化建设重点", "status": "asserted", "source_ref": "test:user:1"}],
                },
                {
                    "field": "minimum_next_step",
                    "candidates": [{"candidate_id": "step-1", "value": "确认下一次技术交流", "status": "asserted", "source_ref": "test:user:1"}],
                },
            ],
            "confirmations": [],
            "subject_resolution": subject,
        }
        return bind_intake_payload(root / "intake" / "migration.json", payload)

    def test_dry_run_is_byte_and_tree_side_effect_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            intake = self._intake(root)
            before = tree_bytes(workspace)
            result = migration.migrate_workspace(workspace, intake, dry_run=True)
            self.assertEqual(result["status"], "planned")
            self.assertTrue(result["dry_run"])
            self.assertEqual(tree_bytes(workspace), before)

    def test_migration_backs_up_original_preserves_id_and_allows_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            intake = self._intake(root)
            manifest_path = workspace / "runtime" / "manifest.json"
            original = manifest_path.read_bytes()
            result = migration.migrate_workspace(workspace, intake)
            self.assertEqual(result["status"], "migrated")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["customer_id"], self.customer_id)
            self.assertEqual(manifest["subject_binding"]["customer_id"], self.customer_id)
            self.assertEqual(
                manifest["intake_preflight"]["subject_resolution"],
                manifest["subject_binding"],
            )
            self.assertEqual(manifest["transaction_sequence"], 5)
            backup = workspace / result["backup_path"]
            self.assertEqual((backup / "manifest.original.json").read_bytes(), original)
            self.assertEqual(
                (backup / "manifest.original.sha256").read_text(encoding="ascii"),
                hashlib.sha256(original).hexdigest() + "\n",
            )
            receipt = json.loads((backup / "migration-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["source_manifest_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(receipt["replacement_manifest_sha256"], hashlib.sha256(manifest_path.read_bytes()).hexdigest())

            gate = migration._verified_gate(intake)
            initializer.assert_resume_subject_binding(manifest, gate)

    def test_repeated_migration_is_idempotent_and_does_not_refresh_attestation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            intake = self._intake(root)
            migration.migrate_workspace(workspace, intake)
            before = tree_bytes(workspace)
            result = migration.migrate_workspace(workspace, intake)
            self.assertEqual(result["status"], "already_migrated")
            self.assertEqual(tree_bytes(workspace), before)

    def test_N132_same_name_different_derived_entity_cannot_rebind_legacy_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entity_a = "cn-health-org-citya-hospital-a"
            payload_a = {
                "canonical_customer_name": self.customer_name,
                "canonical_entity_key": entity_a,
                "jurisdiction": "CN-TEST-01",
            }
            subject_a_sha = hashlib.sha256(canonical_json(payload_a).encode("utf-8")).hexdigest()
            legacy_id = "cust-" + subject_a_sha[:12]
            workspace = self._legacy_workspace(root, customer_id=legacy_id)
            entity_b = "cn-health-org-citya-hospital-b"
            payload_b = {
                "canonical_customer_name": self.customer_name,
                "canonical_entity_key": entity_b,
                "jurisdiction": "CN-TEST-01",
            }
            subject_b_sha = hashlib.sha256(canonical_json(payload_b).encode("utf-8")).hexdigest()
            intake = self._intake(
                root,
                entity_key=entity_b,
                customer_id="cust-" + subject_b_sha[:12],
                id_source="canonical_derived",
            )
            before = tree_bytes(workspace)
            with self.assertRaisesRegex(migration.MigrationError, "不得改号"):
                migration.migrate_workspace(workspace, intake)
            self.assertEqual(tree_bytes(workspace), before)

    def test_existing_signed_lineage_rejects_same_id_name_but_different_entity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            old_subject_payload = {
                "canonical_customer_name": self.customer_name,
                "canonical_entity_key": "cn-health-org-citya-hospital-old",
                "jurisdiction": "CN-TEST-01",
            }
            old_sha = hashlib.sha256(canonical_json(old_subject_payload).encode("utf-8")).hexdigest()
            manifest_path = workspace / "runtime" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["intake_preflight"] = {
                "subject_resolution": {
                    "schema": "discovery-call-subject-resolution/v1",
                    "issuer": TEST_REQUEST_ISSUER,
                    "customer_id": self.customer_id,
                    "canonical_customer_name": self.customer_name,
                    "canonical_entity_key": old_subject_payload["canonical_entity_key"],
                    "jurisdiction": old_subject_payload["jurisdiction"],
                    "canonical_subject_sha256": old_sha,
                    "organization_scope_sha256": hashlib.sha256(self.organization_scope.encode("utf-8")).hexdigest(),
                    "id_source": "host_attested_external",
                }
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            intake = self._intake(root, entity_key="cn-health-org-citya-hospital-new")
            before = tree_bytes(workspace)
            with self.assertRaisesRegex(migration.MigrationError, "已有不同的签名主体"):
                migration.migrate_workspace(workspace, intake)
            self.assertEqual(tree_bytes(workspace), before)

    def test_post_replace_failure_restores_manifest_and_removes_new_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            intake = self._intake(root)
            before = tree_bytes(workspace)
            with patch.object(migration, "_after_manifest_replace", side_effect=RuntimeError("injected")):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    migration.migrate_workspace(workspace, intake)
            self.assertEqual(tree_bytes(workspace), before)
            self.assertFalse((workspace / "runtime" / "migrations").exists())

    def test_backup_promotion_failure_leaves_workspace_tree_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            intake = self._intake(root)
            before = tree_bytes(workspace)
            real_replace = migration.os.replace

            def fail_backup_promotion(source, destination):
                if Path(destination).name.startswith("sbm-"):
                    raise OSError("injected backup promotion failure")
                return real_replace(source, destination)

            with patch.object(migration.os, "replace", side_effect=fail_backup_promotion):
                with self.assertRaisesRegex(OSError, "backup promotion"):
                    migration.migrate_workspace(workspace, intake)
            self.assertEqual(tree_bytes(workspace), before)
            self.assertFalse((workspace / "runtime" / "migrations").exists())

    def test_noncooperating_cas_writer_is_not_clobbered_by_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._legacy_workspace(root)
            intake = self._intake(root)
            manifest_path = workspace / "runtime" / "manifest.json"
            external_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            external_payload["updated_at"] = "2026-08-27T23:59:59Z"
            external_bytes = (
                json.dumps(external_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            real_prepare = migration._prepare_backup

            def prepare_then_external_write(*args, **kwargs):
                created = real_prepare(*args, **kwargs)
                manifest_path.write_bytes(external_bytes)
                return created

            with patch.object(migration, "_prepare_backup", side_effect=prepare_then_external_write):
                with self.assertRaisesRegex(migration.MigrationError, "CAS变化"):
                    migration.migrate_workspace(workspace, intake)
            self.assertEqual(manifest_path.read_bytes(), external_bytes)
            self.assertFalse((workspace / "runtime" / "migrations").exists())


if __name__ == "__main__":
    unittest.main()
