from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.common import research_plan as rp, run_python, write_intake
from tests.fixture_builder import _rebuild_manifest, build_pending_letter_workspace


def file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class ReleaseNegativeExtensionTests(unittest.TestCase):
    """Behavioral coverage for release-hardening contracts N53/N56/N57/N61."""

    def test_N53_modified_intake_cannot_preserve_preflight_identity_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root / "intakes", "甲医院", "briefing")
            original = json.loads(intake.read_text(encoding="utf-8"))
            original_gate = rp.PREFLIGHT.evaluate_intake(original)

            changed = json.loads(json.dumps(original, ensure_ascii=False))
            customer_set = next(
                item for item in changed["candidate_sets"] if item["field"] == "customer_name"
            )
            customer_set["candidates"][0]["value"] = "乙医院"
            intake.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            changed_gate = rp.PREFLIGHT.evaluate_intake(changed)
            self.assertNotEqual(original_gate["input_sha256"], changed_gate["input_sha256"])

            output = root / "output"
            before = file_hashes(root)
            result = run_python(
                "init_workspace.py",
                [
                    "甲医院",
                    "--output-root",
                    str(output),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(intake),
                    "--json",
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("customer_name", result.stderr)
            self.assertEqual(file_hashes(root), before)
            self.assertFalse(output.exists())

    def test_N56_research_plan_rejects_direct_write_to_formal_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "formal-workspace"
            workspace.mkdir()
            before = file_hashes(workspace)
            with self.assertRaisesRegex(rp.PlanError, "拒绝直接写正式workspace"):
                rp.RuntimeWorkspace(workspace, source_workspace=workspace)
            self.assertEqual(file_hashes(workspace), before)

    def test_N57_candidate_profile_rejects_scaffold_and_profile_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root / "intakes", "候选校验医院", "briefing")
            initialized = run_python(
                "init_workspace.py",
                [
                    "候选校验医院",
                    "--output-root",
                    str(root / "output"),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "briefing",
                    "--intake-input",
                    str(intake),
                    "--json",
                ],
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
            workspace = Path(json.loads(initialized.stdout)["workspace"])

            candidate = run_python("validate_outputs.py", [str(workspace), "--json"])
            self.assertEqual(candidate.returncode, 1)
            candidate_payload = json.loads(candidate.stdout)
            candidate_codes = {issue["code"] for issue in candidate_payload["issues"]}
            self.assertIn("placeholder_remaining", candidate_codes)
            self.assertEqual(candidate_payload["deliverable_state"], "invalid")

            conflict = run_python(
                "validate_outputs.py",
                [str(workspace), "--strict", "--profile", "candidate", "--json"],
            )
            self.assertEqual(conflict.returncode, 2)
            self.assertRegex(conflict.stderr, r"strict|profile|互斥")

    def test_N61_missing_claim_ttl_fields_are_machine_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary) / "output")
            evidence_path = workspace / "runtime" / "evidence-manifest.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            claim = next(iter(evidence["claims"].values()))
            claim.pop("ttl_days")
            evidence_path.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _rebuild_manifest(workspace, ["institution", "letter"])

            result = run_python(
                "validate_outputs.py",
                [str(workspace), "--profile", "candidate", "--json"],
            )
            self.assertEqual(result.returncode, 1)
            codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
            self.assertIn("machine_claim_fields_missing", codes)


if __name__ == "__main__":
    unittest.main()
