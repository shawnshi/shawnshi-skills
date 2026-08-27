import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).parent))
import validator
from validator import audit_outline, load_source


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = (ROOT / "evals" / "valid-outline.md").read_text(encoding="utf-8")
SINGLE = (ROOT / "evals" / "single-slide-outline.md").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "references" / "outline-template.md").read_text(encoding="utf-8")


def codes(items):
    return {item["code"] for item in items}


class BlueprintValidatorTests(unittest.TestCase):
    def test_canonical_template_remains_structurally_valid(self):
        match = re.search(r"(?s)```markdown\n(.*?)\n```", TEMPLATE)
        self.assertIsNotNone(match)
        report, _ = audit_outline(match.group(1))
        self.assertFalse(report["errors"])

    def test_style_index_ids_and_files_are_unique_and_resolvable(self):
        index = json.loads((ROOT / "references" / "styles" / "index.json").read_text(encoding="utf-8"))
        identifiers = [item["id"] for item in index["styles"]]
        files = [item["file"] for item in index["styles"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(len(files), len(set(files)))
        self.assertTrue(all((ROOT / "references" / "styles" / name).is_file() for name in files))

    def test_valid_full_fixture_passes_structural_scope(self):
        report, document = audit_outline(FIXTURE)
        self.assertEqual("pass", report["status"])
        self.assertEqual("structural", report["validation_scope"])
        self.assertEqual(2, report["source_schema_version"])
        self.assertEqual(3, len(document["slides"]))
        self.assertEqual("A1", document["slides"][0]["records"]["assets"][0][0])

    def test_style_id_must_come_from_index_or_custom(self):
        indexed, _ = audit_outline(FIXTURE.replace("Style_ID: custom", "Style_ID: corporate"))
        self.assertNotIn("E_STYLE_ID", codes(indexed["errors"]))
        unknown, _ = audit_outline(FIXTURE.replace("Style_ID: custom", "Style_ID: missing-style"))
        self.assertIn("E_STYLE_ID", codes(unknown["errors"]))

    def test_one_pager_may_be_a_decision_without_cover(self):
        report, _ = audit_outline(SINGLE)
        self.assertFalse(report["errors"])

    def test_uppercase_markdown_fence_is_supported(self):
        report, _ = audit_outline(f"```Markdown\n{FIXTURE.rstrip()}\n```\n")
        self.assertFalse(report["errors"])

    def test_text_outside_fence_is_rejected(self):
        report, _ = audit_outline(f"preface\n```MD\n{FIXTURE.rstrip()}\n```\n")
        self.assertIn("E_EXTERNAL_TEXT", codes(report["errors"]))

    def test_unresolved_text_after_deck_is_rejected(self):
        report, _ = audit_outline(FIXTURE + "unparsed trailer\n")
        self.assertIn("E_UNRESOLVED_TEXT", codes(report["errors"]))

    def test_literal_script_and_owner_lines_in_notes_are_prose(self):
        content = FIXTURE.replace(
            "Explain that this fixture tests structural behavior rather than release readiness.",
            "Explain the parser boundary.\n// SCRIPT\n[Owner]: this line remains speaker-note prose.",
        )
        report, document = audit_outline(content)
        self.assertFalse(report["errors"])
        notes = document["slides"][0]["delivery"]["Speaker Notes"]
        self.assertIn("// SCRIPT", notes)
        self.assertIn("[Owner]:", notes)

    def test_final_rejects_each_placeholder_family(self):
        for placeholder in ("{{VALUE}}", "TBD", "TODO", "待补", "待确认", "待核验", "[INSERT VALUE]", "[BASELINE]"):
            with self.subTest(placeholder=placeholder):
                content = FIXTURE.replace("Centered title with a small schema-version label.", f"Centered title {placeholder}.")
                report, _ = audit_outline(content)
                self.assertIn("E_UNRESOLVED_PLACEHOLDER", codes(report["errors"]))

    def test_draft_warns_for_placeholder(self):
        content = FIXTURE.replace("Status: final", "Status: draft").replace(
            "Centered title with a small schema-version label.", "Centered title {{LAYOUT}}."
        )
        report, _ = audit_outline(content)
        self.assertNotIn("E_UNRESOLVED_PLACEHOLDER", codes(report["errors"]))
        self.assertIn("W_UNRESOLVED_PLACEHOLDER", codes(report["warnings"]))

    def test_draft_typed_moustache_values_warn_without_type_errors(self):
        content = (
            FIXTURE.replace("Status: final", "Status: draft")
            .replace("Duration_Minutes: 8", "Duration_Minutes: {{DURATION}}")
            .replace("Confidentiality: internal", "Confidentiality: {{CONFIDENTIALITY}}")
            .replace("Slide_Count: 3", "Slide_Count: {{SLIDE_COUNT}}")
            .replace("Generated: 2026-08-26", "Generated: {{GENERATED}}")
            .replace("Source_Cutoff: 2026-08-26", "Source_Cutoff: {{SOURCE_CUTOFF}}")
            .replace("Style_ID: custom", "Style_ID: {{STYLE_ID}}")
            .replace("Density: balanced", "Density: {{DENSITY}}")
            .replace("Citation_Treatment: visible-footer", "Citation_Treatment: {{CITATION}}")
        )
        report, _ = audit_outline(content)
        self.assertFalse(report["errors"])
        self.assertIn("W_UNRESOLVED_PLACEHOLDER", codes(report["warnings"]))

    def test_draft_typed_named_placeholders_warn_without_type_errors(self):
        content = (
            FIXTURE.replace("Status: final", "Status: draft")
            .replace("Duration_Minutes: 8", "Duration_Minutes: TBD")
            .replace("Confidentiality: internal", "Confidentiality: 待确认")
            .replace("Slide_Count: 3", "Slide_Count: TODO")
            .replace("Generated: 2026-08-26", "Generated: [INSERT DATE]")
            .replace("Density: balanced", "Density: [BASELINE]")
        )
        report, _ = audit_outline(content)
        self.assertFalse(report["errors"])
        self.assertIn("W_UNRESOLVED_PLACEHOLDER", codes(report["warnings"]))

    def test_structured_unverified_claim_and_open_item_are_allowed_in_final(self):
        content = FIXTURE.replace(
            "- C1 | fact | verified | The fixture uses Schema Version 2 | E1",
            "- C1 | assumption | unverified | The downstream renderer contract has not been tested | none",
        ).replace("[Open Items]:\nnone", "[Open Items]:\n- O1 | data | Verify renderer behavior | maintainer | unscheduled", 1)
        report, _ = audit_outline(content)
        self.assertFalse(report["errors"])
        self.assertIn("W_UNVERIFIED_CLAIM", codes(report["warnings"]))

    def test_field_order_is_warning_not_error(self):
        content = FIXTURE.replace(
            "[Goal]: Introduce the v2 structural validation task.\n[Title]: Validate one canonical blueprint contract",
            "[Title]: Validate one canonical blueprint contract\n[Goal]: Introduce the v2 structural validation task.",
        )
        report, _ = audit_outline(content)
        self.assertFalse(report["errors"])
        self.assertIn("W_FIELD_ORDER", codes(report["warnings"]))

    def test_block_order_is_error(self):
        original = "// VISUAL\n[Layout]: title-hero\n[Visual Description]: Centered title with a small schema-version label.\n[Chart]: none\n[Assets]:\n- A1 | generated geometric rule | owned | not-required\n\n// DELIVERY"
        replacement = "// DELIVERY"
        content = FIXTURE.replace(original, replacement, 1).replace(
            "// END SLIDE\n\n---\nSlide_ID: SLD-fixture-evidence",
            "// VISUAL\n[Layout]: title-hero\n[Visual Description]: Centered title with a small schema-version label.\n[Chart]: none\n[Assets]:\n- A1 | generated geometric rule | owned | not-required\n\n// END SLIDE\n\n---\nSlide_ID: SLD-fixture-evidence",
            1,
        )
        report, _ = audit_outline(content)
        self.assertIn("E_BLOCK_ORDER", codes(report["errors"]))

    def test_missing_evidence_reference_is_rejected(self):
        content = FIXTURE.replace("| E1\n[Evidence]:", "| E9\n[Evidence]:", 1)
        report, _ = audit_outline(content)
        self.assertIn("E_EVIDENCE_REFERENCE", codes(report["errors"]))

    def test_invalid_dates_are_rejected(self):
        content = FIXTURE.replace("Generated: 2026-08-26", "Generated: 2026-02-30")
        report, _ = audit_outline(content)
        self.assertIn("E_GENERATED_DATE", codes(report["errors"]))

    def test_layout_uses_library_id_or_custom_slug(self):
        unknown, _ = audit_outline(FIXTURE.replace("[Layout]: title-hero", "[Layout]: one page canvas", 1))
        self.assertIn("E_LAYOUT_ID", codes(unknown["errors"]))
        custom, _ = audit_outline(FIXTURE.replace("[Layout]: title-hero", "[Layout]: custom:one-page-canvas", 1))
        self.assertNotIn("E_LAYOUT_ID", codes(custom["errors"]))

    def test_evidence_requires_visible_citation_treatment(self):
        report, _ = audit_outline(FIXTURE.replace("Citation_Treatment: visible-footer", "Citation_Treatment: not-applicable"))
        self.assertIn("E_CITATION_REQUIRED", codes(report["errors"]))

    def test_pending_asset_warns_in_draft_and_blocks_final(self):
        pending = FIXTURE.replace("owned | not-required", "permission-pending | pending", 1)
        final_report, _ = audit_outline(pending)
        self.assertIn("E_ASSET_NOT_READY", codes(final_report["errors"]))

        draft_report, _ = audit_outline(pending.replace("Status: final", "Status: draft"))
        self.assertNotIn("E_ASSET_NOT_READY", codes(draft_report["errors"]))
        self.assertIn("W_ASSET_NOT_READY", codes(draft_report["warnings"]))

    def test_duplicate_slide_id_is_rejected(self):
        content = FIXTURE.replace("SLD-fixture-evidence", "SLD-fixture-cover")
        report, _ = audit_outline(content)
        self.assertIn("E_DUPLICATE_SLIDE_ID", codes(report["errors"]))

    def test_full_mode_requires_terminal_but_section_mode_does_not(self):
        no_terminal = FIXTURE.replace("Type: Decision\nPage: 3", "Type: Content\nPage: 3").replace(
            "[Decision]:\n- D1 | approve | Use v2 for subsequent blueprint fixtures | Skill maintainer | 2026-08-26\n", ""
        )
        report, _ = audit_outline(no_terminal)
        self.assertIn("E_TERMINAL_SLIDE", codes(report["errors"]))
        section = no_terminal.replace("Deck_Mode: full", "Deck_Mode: section")
        report, _ = audit_outline(section)
        self.assertNotIn("E_TERMINAL_SLIDE", codes(report["errors"]))

    def test_full_mode_uses_last_terminal_so_intermediate_decision_is_valid(self):
        content = FIXTURE.replace("Type: Data\nPage: 2", "Type: Decision\nPage: 2").replace(
            "[Action]: Preserve the identifiers when revising prose.",
            "[Decision]:\n- D1 | approve | Continue to the final contract decision | Skill maintainer | 2026-08-26\n[Action]: Preserve the identifiers when revising prose.",
            1,
        )
        report, _ = audit_outline(content)
        self.assertFalse(report["errors"])

    def test_v1_reports_migration_command(self):
        content = FIXTURE.replace("Schema_Version: 2\n", "")
        report, _ = audit_outline(content)
        unsupported = [item for item in report["errors"] if item["code"] == "E_SCHEMA_VERSION_UNSUPPORTED"]
        self.assertTrue(unsupported)
        self.assertIn("migrate_v1.py", unsupported[0]["migration_command"])

    def test_directory_requires_canonical_outline_file(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            (root / "chunk_1.md").write_text(FIXTURE, encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                load_source(root)

    def test_cli_accepts_stdin_and_batch_paths(self):
        with tempfile.TemporaryDirectory() as temp_root:
            first = Path(temp_root) / "first.md"
            second = Path(temp_root) / "second.md"
            first.write_text(FIXTURE, encoding="utf-8")
            second.write_text(SINGLE, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = validator.main([str(first), str(second)])
            payload = json.loads(output.getvalue())
            self.assertEqual(0, result)
            self.assertEqual(2, payload["summary"]["source_count"])

        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(SINGLE)), redirect_stdout(output):
            result = validator.main(["-"])
        self.assertEqual(0, result)
        self.assertEqual(["<stdin>"], json.loads(output.getvalue())["source_files"])


if __name__ == "__main__":
    unittest.main()
