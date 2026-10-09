"""Regression coverage for the 2026-10-09 slide-architect audit (TS-01–TS-06)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import migrate_v1
import scaffold
from test_tools import FIXTURE, legacy_fixture, run_script
from validator import audit_outline

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


class MigrationSafetyTests(unittest.TestCase):
    def test_explicit_constraints_survive_migration(self):
        original = legacy_fixture().replace(
            "Language: English",
            "Language: English\nConfidentiality: restricted\nAspect_Ratio: 4:3\n"
            "Duration_Minutes: 30\nSource_Cutoff: 2026-08-26\n"
            "Must_Keep: Classification banner\nTemplate_Ref: approved-template.pptx\n"
            "Deck_ID: legacy-brief\nDecision_Owner: Sponsor\nRevision: 7",
        )
        report, document = audit_outline(migrate_v1.migrate(original))
        self.assertFalse(report["errors"], report["errors"])
        expected = {
            "Confidentiality": "restricted",
            "Aspect_Ratio": "4:3",
            "Duration_Minutes": "30",
            "Source_Cutoff": "2026-08-26",
            "Must_Keep": "Classification banner",
            "Template_Ref": "approved-template.pptx",
            "Deck_ID": "legacy-brief",
            "Decision_Owner": "Sponsor",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(value, document["metadata"].get(key))
        self.assertIn("7", document["metadata"]["Revision"])
        self.assertEqual("draft", document["metadata"]["Status"])

    def test_unknown_constraint_is_not_silently_discarded(self):
        original = legacy_fixture().replace("Language: English", "Language: English\nLegal_Hold: do-not-distribute")
        with self.assertRaises(migrate_v1.SafeWriteError) as caught:
            migrate_v1.migrate(original)
        self.assertEqual("E_V1_METADATA_UNMAPPED", caught.exception.code)

    def test_missing_confidentiality_stays_restricted_and_explicitly_open(self):
        report, document = audit_outline(migrate_v1.migrate(legacy_fixture()))
        self.assertFalse(report["errors"])
        self.assertEqual("restricted", document["metadata"]["Confidentiality"])
        descriptions = [item[2] for item in document["slides"][0]["records"]["open_items"]]
        self.assertTrue(any("Confidentiality" in item for item in descriptions))

    def test_invalid_supplied_constraint_blocks_cli_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy.md"
            output = Path(directory) / "migrated.md"
            source.write_text(legacy_fixture().replace("Language: English", "Language: English\nConfidentiality: unknown"), encoding="utf-8")
            result = run_script("migrate_v1.py", source, "--output", output)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())

    def test_inherited_review_is_not_claimed_for_the_migrated_revision(self):
        original = legacy_fixture().replace("Language: English", "Language: English\nReviewed_By: Prior reviewer")
        report, document = audit_outline(migrate_v1.migrate(original))
        self.assertFalse(report["errors"])
        self.assertNotIn("Reviewed_By", document["metadata"])
        self.assertIn("Prior reviewer", document["slides"][0]["evidence"]["Open Items"])


class BundleChangeSetTests(unittest.TestCase):
    def package_pair(self, updated):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "outline.md"
            previous = root / "previous.json"
            current = root / "current.json"
            source.write_text(FIXTURE, encoding="utf-8")
            before = run_script("build-deck.py", source, "-o", previous)
            self.assertEqual(0, before.returncode, before.stdout + before.stderr)
            source.write_text(updated, encoding="utf-8")
            after = run_script("build-deck.py", source, "-o", current, "--previous", previous)
            self.assertEqual(0, after.returncode, after.stdout + after.stderr)
            return json.loads(previous.read_text(encoding="utf-8")), json.loads(current.read_text(encoding="utf-8"))

    def test_style_change_marks_all_slides_for_rebuild(self):
        lines = FIXTURE.splitlines()
        updated = "\n".join("Background: Black with white accents" if line.startswith("Background:") else line for line in lines)
        before, after = self.package_pair(updated)
        self.assertNotEqual(before["deck_hash"], after["deck_hash"])
        self.assertEqual([item["slide_id"] for item in after["slides"]], after["change_set"]["changed_slide_ids"])

    def test_aspect_ratio_and_confidentiality_changes_mark_all_slides(self):
        for updated in (
            FIXTURE.replace("Aspect_Ratio: 16:9", "Aspect_Ratio: 4:3"),
            FIXTURE.replace("Confidentiality: internal", "Confidentiality: restricted"),
        ):
            with self.subTest(change=updated != FIXTURE):
                self.assertNotEqual(FIXTURE, updated)
                _, after = self.package_pair(updated)
                self.assertEqual(len(after["slides"]), len(after["change_set"]["changed_slide_ids"]))

    def test_missing_previous_global_context_forces_full_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outline.md"
            previous = Path(directory) / "previous.json"
            current = Path(directory) / "current.json"
            source.write_text(FIXTURE, encoding="utf-8")
            self.assertEqual(0, run_script("build-deck.py", source, "-o", previous).returncode)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            del payload["style_instructions"]
            previous.write_text(json.dumps(payload), encoding="utf-8")
            result = run_script("build-deck.py", source, "-o", current, "--previous", previous)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            change = json.loads(current.read_text(encoding="utf-8"))["change_set"]
            self.assertTrue(change["requires_full_rebuild"])
            self.assertEqual(["style_instructions"], change["global_changed_sections"])
            self.assertEqual(len(payload["slides"]), len(change["changed_slide_ids"]))

    def test_invalid_previous_global_context_blocks_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outline.md"
            previous = Path(directory) / "previous.json"
            current = Path(directory) / "current.json"
            source.write_text(FIXTURE, encoding="utf-8")
            self.assertEqual(0, run_script("build-deck.py", source, "-o", previous).returncode)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            payload["metadata"] = "invalid-context"
            previous.write_text(json.dumps(payload), encoding="utf-8")
            result = run_script("build-deck.py", source, "-o", current, "--previous", previous)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("E_PREVIOUS_SCHEMA", json.loads(result.stdout)["errors"][0]["code"])
            self.assertFalse(current.exists())

    def test_identical_bundle_has_empty_change_set(self):
        _, after = self.package_pair(FIXTURE)
        self.assertEqual([], after["change_set"]["changed_slide_ids"])
        self.assertEqual([], after["change_set"]["removed_slide_ids"])


class PlaceholderAndScaffoldTests(unittest.TestCase):
    def test_literal_keyword_in_exact_inline_code_is_not_a_placeholder(self):
        original = "Centered title with a small schema-version label."
        for token in ("TODO", "TBD", "待补", "待确认", "待核验"):
            with self.subTest(token=token):
                content = FIXTURE.replace(original, f"Explain the literal `{token}` token; it is not missing deck content.")
                report, _ = audit_outline(content)
                self.assertFalse(report["errors"], report["errors"])

    def test_inline_code_does_not_hide_template_placeholders(self):
        original = "Centered title with a small schema-version label."
        for token in ("{{BUDGET}}", "[INSERT VALUE]", "[BASELINE]", "TODO add a budget"):
            with self.subTest(token=token):
                report, _ = audit_outline(FIXTURE.replace(original, f"`{token}`"))
                self.assertIn("E_UNRESOLVED_PLACEHOLDER", {item["code"] for item in report["errors"]})

    def test_literal_exemption_does_not_hide_another_unresolved_keyword(self):
        content = FIXTURE.replace("Centered title with a small schema-version label.", "Explain `TODO`; budget: TBD.")
        report, _ = audit_outline(content)
        instances = [item for error in report["errors"] for item in error.get("instances", [])]
        self.assertEqual(["TBD"], [item["value"] for item in instances])

    def test_literal_keywords_in_records_and_review_metadata_still_block(self):
        for content in (
            FIXTURE.replace("Reviewed_By: Test suite", "Reviewed_By: `TODO`"),
            FIXTURE.replace("Skill maintainer | 2026-08-26", "`待确认` | 2026-08-26"),
        ):
            with self.subTest(content=content != FIXTURE):
                self.assertNotEqual(FIXTURE, content)
                report, _ = audit_outline(content)
                self.assertIn("E_UNRESOLVED_PLACEHOLDER", {item["code"] for item in report["errors"]})

    def test_scaffold_keeps_business_fields_detectably_open(self):
        args = scaffold.parse_args(["--mode", "full", "--slides", "8"])
        content = scaffold.render_scaffold(args)
        report, document = audit_outline(content)
        self.assertFalse(report["errors"])
        self.assertEqual("{{DURATION_MINUTES}}", document["metadata"]["Duration_Minutes"])
        self.assertEqual("{{SOURCE_CUTOFF}}", document["metadata"]["Source_Cutoff"])
        self.assertTrue(all("{{" in slide["narrative"]["Title"] for slide in document["slides"]))
        self.assertNotIn("Draft title for slide", content)

    def test_unedited_scaffold_cannot_be_promoted_to_final(self):
        args = scaffold.parse_args(["--mode", "one_pager", "--slides", "1", "--language", "zh-CN"])
        content = scaffold.render_scaffold(args)
        draft, _ = audit_outline(content)
        self.assertFalse(draft["errors"])
        final, _ = audit_outline(content.replace("Status: draft", "Status: final"))
        self.assertIn("E_UNRESOLVED_PLACEHOLDER", {item["code"] for item in final["errors"]})


class UnicodeInputTests(unittest.TestCase):
    def test_direct_utf8_file_input_preserves_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outline.md"
            bundle = Path(directory) / "bundle.json"
            original = "Centered title with a small schema-version label."
            source.write_text(FIXTURE.replace(original, "中文材料：保密标签与来源定位"), encoding="utf-8")
            validation = run_script("validator.py", source)
            self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)
            result = run_script("build-deck.py", source, "-o", bundle)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(bundle.read_text(encoding="utf-8"))
            self.assertEqual("中文材料：保密标签与来源定位", payload["slides"][0]["visual"]["visual_description"])

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell unavailable")
    def test_powershell_direct_file_path_preserves_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "outline.md"
            source.write_text(FIXTURE.replace("Topic: Canonical schema validation", "Topic: 中文测试"), encoding="utf-8")
            command = "& '{}' -B '{}' '{}'".format(
                sys.executable.replace("'", "''"),
                str(SCRIPTS / "validator.py").replace("'", "''"),
                str(source).replace("'", "''"),
            )
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, env=env)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("pass", json.loads(result.stdout.decode("utf-8"))["status"])
            content = source.read_text(encoding="utf-8")
            _, document = audit_outline(content)
            self.assertEqual("中文测试", document["metadata"]["Topic"])


if __name__ == "__main__":
    unittest.main()
