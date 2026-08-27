import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURE = (ROOT / "evals" / "valid-outline.md").read_text(encoding="utf-8")


def run_script(name, *args, input_text=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *map(str, args)],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def legacy_fixture():
    return """<DECK_METADATA>
Topic: Legacy fixture
Audience: Maintainers
Objective: Test migration
Language: English
Slide_Count: 1
Generated: 2026-08-26
</DECK_METADATA>

<STYLE_INSTRUCTIONS>
Design_Aesthetic: Restrained
Background: White
Typography: Sans serif
Color_Palette: Gray and blue
</STYLE_INSTRUCTIONS>

---
Type: Content
Page: 1
---

// NARRATIVE GOAL
Explain the legacy slide.

// KEY CONTENT
[Title]: Legacy evidence must remain unverified
[Arc Logic]: Test migration boundaries.
[Sub-headline]: Preserve the old text.
[Key Insight]: Migration does not verify evidence.
[Content / Data]: One legacy claim.
[Evidence / Trust Anchor]: Legacy local note dated 2026-08-26.

// VISUAL DIRECTIVE
[Layout]: one-column
[Visual Description]: One evidence card.
[Chart Suggestion]: none

// SCRIPT
[Speaker Notes]: State the migration boundary.
[Delivery Notes]: Require human review.
"""


class PackagingSafetyTests(unittest.TestCase):
    def test_build_outputs_hashes_and_structured_arrays(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            output = root / "bundle.json"
            source.write_text(FIXTURE, encoding="utf-8")
            result = run_script("build-deck.py", source, "-o", output)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            bundle = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("structural", bundle["validation_scope"])
            self.assertRegex(bundle["deck_hash"], r"^[0-9a-f]{64}$")
            self.assertRegex(bundle["slides"][0]["content_hash"], r"^[0-9a-f]{64}$")
            self.assertIsInstance(bundle["slides"][1]["evidence"]["claims"], list)
            self.assertNotIn("raw", bundle["slides"][1]["evidence"])
            self.assertEqual("owned", bundle["slides"][0]["visual"]["assets"][0]["rights"])
            self.assertTrue(Path(bundle["source_files"][0]).is_absolute())

    def test_default_no_overwrite_and_force_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            output = root / "bundle.json"
            source.write_text(FIXTURE, encoding="utf-8")
            self.assertEqual(0, run_script("build-deck.py", source, "-o", output).returncode)
            blocked = run_script("build-deck.py", source, "-o", output)
            self.assertNotEqual(0, blocked.returncode)
            self.assertEqual("E_OUTPUT_EXISTS", json.loads(blocked.stdout)["errors"][0]["code"])
            self.assertEqual(0, run_script("build-deck.py", source, "-o", output, "--force").returncode)

    def test_output_requires_json_and_cannot_alias_input(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            source.write_text(FIXTURE, encoding="utf-8")
            wrong = run_script("build-deck.py", source, "-o", root / "bundle.txt")
            self.assertEqual("E_OUTPUT_EXTENSION", json.loads(wrong.stdout)["errors"][0]["code"])

            json_source = root / "outline.json"
            json_source.write_text(FIXTURE, encoding="utf-8")
            alias = run_script("build-deck.py", json_source, "-o", json_source, "--force")
            self.assertEqual("E_INPUT_OUTPUT_ALIAS", json.loads(alias.stdout)["errors"][0]["code"])
            self.assertEqual(FIXTURE, json_source.read_text(encoding="utf-8"))

    @unittest.skipUnless(hasattr(os, "link"), "hard links unavailable")
    def test_output_hardlink_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            alias = root / "bundle.json"
            source.write_text(FIXTURE, encoding="utf-8")
            try:
                os.link(source, alias)
            except OSError:
                self.skipTest("hard-link creation denied")
            result = run_script("build-deck.py", source, "-o", alias, "--force")
            self.assertEqual("E_INPUT_OUTPUT_ALIAS", json.loads(result.stdout)["errors"][0]["code"])
            self.assertEqual(FIXTURE, source.read_text(encoding="utf-8"))

    def test_lock_and_fixed_temp_symlink_attack_are_safe(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            output = root / "bundle.json"
            victim = root / "victim.txt"
            source.write_text(FIXTURE, encoding="utf-8")
            victim.write_text("unchanged", encoding="utf-8")
            try:
                (root / ".bundle.json.tmp").symlink_to(victim)
            except (OSError, NotImplementedError):
                pass
            result = run_script("build-deck.py", source, "-o", output)
            self.assertEqual(0, result.returncode, result.stdout)
            self.assertEqual("unchanged", victim.read_text(encoding="utf-8"))

            output.unlink()
            (root / ".bundle.json.lock").write_text("held", encoding="utf-8")
            locked = run_script("build-deck.py", source, "-o", output)
            self.assertEqual("E_OUTPUT_LOCKED", json.loads(locked.stdout)["errors"][0]["code"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_output_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            victim = root / "victim.json"
            link = root / "bundle.json"
            source.write_text(FIXTURE, encoding="utf-8")
            victim.write_text("{}", encoding="utf-8")
            try:
                link.symlink_to(victim)
            except OSError:
                self.skipTest("symlink creation denied")
            result = run_script("build-deck.py", source, "-o", link, "--force")
            self.assertEqual("E_SYMLINK_PATH", json.loads(result.stdout)["errors"][0]["code"])
            self.assertEqual("{}", victim.read_text(encoding="utf-8"))

    def test_previous_reports_changed_slide_ids(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            previous = root / "previous.json"
            current = root / "current.json"
            source.write_text(FIXTURE, encoding="utf-8")
            self.assertEqual(0, run_script("build-deck.py", source, "-o", previous).returncode)
            source.write_text(FIXTURE.replace("Validate one canonical blueprint contract", "Validate the canonical v2 blueprint contract"), encoding="utf-8")
            result = run_script("build-deck.py", source, "-o", current, "--previous", previous)
            self.assertEqual(0, result.returncode, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(["SLD-fixture-cover"], payload["changed_slide_ids"])
            bundle = json.loads(current.read_text(encoding="utf-8"))
            self.assertEqual(["SLD-fixture-cover"], bundle["change_set"]["changed_slide_ids"])

    def test_previous_separates_removed_ids_and_rejects_corrupt_bundles(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "outline.md"
            previous = root / "previous.json"
            current = root / "current.json"
            source.write_text(FIXTURE, encoding="utf-8")
            self.assertEqual(0, run_script("build-deck.py", source, "-o", previous).returncode)

            start = FIXTURE.index("---\nSlide_ID: SLD-fixture-evidence")
            end = FIXTURE.index("---\nSlide_ID: SLD-fixture-decision")
            reduced = (FIXTURE[:start] + FIXTURE[end:]).replace("Slide_Count: 3", "Slide_Count: 2").replace("Page: 3", "Page: 2")
            source.write_text(reduced, encoding="utf-8")
            result = run_script("build-deck.py", source, "-o", current, "--previous", previous)
            self.assertEqual(0, result.returncode, result.stdout)
            change_set = json.loads(current.read_text(encoding="utf-8"))["change_set"]
            self.assertNotIn("SLD-fixture-evidence", change_set["changed_slide_ids"])
            self.assertEqual(["SLD-fixture-evidence"], change_set["removed_slide_ids"])

            corrupt_payload = json.loads(previous.read_text(encoding="utf-8"))
            corrupt_payload["slides"].append(dict(corrupt_payload["slides"][0]))
            previous.write_text(json.dumps(corrupt_payload), encoding="utf-8")
            corrupt = run_script("build-deck.py", source, "-o", root / "corrupt-test.json", "--previous", previous)
            self.assertEqual("E_PREVIOUS_SCHEMA", json.loads(corrupt.stdout)["errors"][0]["code"])


class WorkflowToolTests(unittest.TestCase):
    def test_scaffold_is_valid_and_ids_are_deterministic(self):
        first = run_script("scaffold.py", "--mode", "full", "--slides", "5", "--topic", "Stable test")
        second = run_script("scaffold.py", "--mode", "full", "--slides", "5", "--topic", "Stable test")
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        with tempfile.TemporaryDirectory() as temp_root:
            path = Path(temp_root) / "outline.md"
            path.write_text(first.stdout, encoding="utf-8")
            validation = run_script("validator.py", path)
            self.assertEqual(0, validation.returncode, validation.stdout)

    def test_renumber_preserves_slide_ids_and_defaults_to_stdout(self):
        with tempfile.TemporaryDirectory() as temp_root:
            path = Path(temp_root) / "outline.md"
            broken = FIXTURE.replace("Page: 2", "Page: 8").replace("Page: 3", "Page: 11")
            path.write_text(broken, encoding="utf-8")
            before_ids = [line for line in broken.splitlines() if line.startswith("Slide_ID:")]
            result = run_script("renumber.py", path)
            self.assertEqual(0, result.returncode, result.stderr)
            after_ids = [line for line in result.stdout.splitlines() if line.startswith("Slide_ID:")]
            self.assertEqual(before_ids, after_ids)
            self.assertIn("Page: 2", result.stdout)
            self.assertEqual(broken, path.read_text(encoding="utf-8"))

            written = run_script("renumber.py", path, "--write")
            self.assertEqual(0, written.returncode, written.stderr)
            self.assertIn("Page: 2", path.read_text(encoding="utf-8"))

    def test_v1_migration_creates_new_draft_and_preserves_unverified_boundary(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "legacy.md"
            source.write_text(legacy_fixture(), encoding="utf-8")
            result = run_script("migrate_v1.py", source)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            output = root / "legacy.v2.md"
            migrated = output.read_text(encoding="utf-8")
            self.assertIn("Status: draft", migrated)
            self.assertIn("| unverified |", migrated)
            self.assertIn("Legacy local note dated 2026-08-26", migrated)
            self.assertIn("[Layout]: custom:one-column", migrated)
            self.assertEqual(0, run_script("validator.py", output).returncode)
            second = run_script("migrate_v1.py", source)
            self.assertNotEqual(0, second.returncode)
            self.assertEqual("E_OUTPUT_EXISTS", json.loads(second.stdout)["errors"][0]["code"])


if __name__ == "__main__":
    unittest.main()
