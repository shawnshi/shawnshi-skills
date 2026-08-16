import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from report_pair import (
    ReportPairError,
    parse_html_recommendations,
    parse_markdown_recommendations,
    render_report_pair,
    validate_manifest,
    validate_pair,
    write_report_pair,
)


def make_recommendation(index):
    return {
        "id": f"R-{index:02d}",
        "finding_ids": [f"F-{index:02d}"],
        "action": f"Action {index}",
        "implementation_layer": "audit-skill",
        "owner": "skill-maintainer",
        "status": "not_started",
        "authorization": "required",
        "validation": {
            "criterion": f"Criterion {index}",
            "result": "not_run",
            "evidence": [],
        },
    }


def make_manifest(report_id="report-v1"):
    return {
        "report_id": report_id,
        "title": "Collaboration audit",
        "recommendations": [make_recommendation(index) for index in range(1, 7)],
    }


def make_successor(previous):
    current = copy.deepcopy(previous)
    current["report_id"] = "report-v2"
    current["previous_report_id"] = previous["report_id"]
    return current


class ReportPairTests(unittest.TestCase):
    def test_six_item_round_trip(self):
        manifest = make_manifest()

        rendered = render_report_pair(manifest)
        markdown_rows = parse_markdown_recommendations(rendered["markdown"])
        html_rows = parse_html_recommendations(rendered["html"])

        expected_ids = [f"R-{index:02d}" for index in range(1, 7)]
        self.assertEqual([row["id"] for row in markdown_rows], expected_ids)
        self.assertEqual([row["id"] for row in html_rows], expected_ids)
        self.assertEqual(rendered["validation"]["recommendation_count"], 6)
        self.assertIn('data-recommendation-id="R-06"', rendered["html"])
        self.assertNotIn("http://", rendered["html"])
        self.assertNotIn("https://", rendered["html"])

    def test_missing_old_id_is_fatal(self):
        previous = make_manifest()
        current = make_successor(previous)
        current["recommendations"] = [
            item for item in current["recommendations"] if item["id"] != "R-05"
        ]

        with self.assertRaisesRegex(
            ReportPairError, "previous recommendation IDs disappeared: R-05"
        ):
            validate_manifest(current, previous)

    def test_renumbering_or_semantic_drift_is_fatal(self):
        previous = make_manifest()
        current = make_successor(previous)
        old_r06 = previous["recommendations"][5]
        current_r05 = current["recommendations"][4]
        for field in ("finding_ids", "action", "implementation_layer", "owner"):
            current_r05[field] = copy.deepcopy(old_r06[field])

        with self.assertRaisesRegex(
            ReportPairError, "semantic drift for stable recommendation ID R-05"
        ):
            validate_manifest(current, previous)

    def test_missing_html_section_is_fatal(self):
        manifest = make_manifest()
        rendered = render_report_pair(manifest)
        broken_html = rendered["html"].replace(
            'id="recommendations"', 'id="missing-recommendations"', 1
        )

        with self.assertRaisesRegex(
            ReportPairError, "HTML recommendation section is missing"
        ):
            validate_pair(manifest, rendered["markdown"], broken_html)

    def test_status_mismatch_is_fatal(self):
        manifest = make_manifest()
        rendered = render_report_pair(manifest)
        broken_html = rendered["html"].replace(
            'data-status="not_started"', 'data-status="implemented"', 1
        )

        with self.assertRaisesRegex(ReportPairError, "data-status"):
            validate_pair(manifest, rendered["markdown"], broken_html)

    def test_validation_evidence_mismatch_is_fatal(self):
        manifest = make_manifest()
        manifest["recommendations"][0]["validation"] = {
            "criterion": "Replay fixture",
            "result": "pass",
            "evidence": ["fixture.jsonl:1"],
        }
        rendered = render_report_pair(manifest)
        broken_html = rendered["html"].replace("fixture.jsonl:1", "fixture.jsonl:2", 1)

        with self.assertRaisesRegex(
            ReportPairError, "HTML status or validation projection mismatch"
        ):
            validate_pair(manifest, rendered["markdown"], broken_html)

    def test_false_validation_green_is_fatal(self):
        manifest = make_manifest()
        manifest["recommendations"][0]["validation"]["result"] = "pass"

        with self.assertRaisesRegex(
            ReportPairError, "validation.evidence is required when result is pass"
        ):
            validate_manifest(manifest)

    def test_explicit_supersession_passes(self):
        previous = make_manifest()
        current = make_successor(previous)
        current_r05 = current["recommendations"][4]
        current_r05["status"] = "superseded"
        current_r05["closure_reason"] = "Replaced by an approved environment probe"
        current_r05["closure_evidence"] = ["decision.json:12"]

        rendered = render_report_pair(current, previous_manifest=previous)
        result = validate_pair(
            current,
            rendered["markdown"],
            rendered["html"],
            previous_manifest=previous,
        )

        self.assertEqual(result["status"], "pass")
        self.assertIn("R-05", result["recommendation_ids"])
        self.assertIn("superseded", rendered["markdown"])
        self.assertIn("decision.json:12", rendered["html"])

    def test_write_is_exclusive_and_receipt_hashes_the_pair(self):
        manifest = make_manifest()
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            manifest_path = root / "manifest.json"
            markdown_path = root / "report.md"
            html_path = root / "report.html"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )

            result = write_report_pair(
                manifest_path=manifest_path,
                markdown_path=markdown_path,
                html_path=html_path,
            )
            receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))

            self.assertEqual(receipt["recommendation_count"], 6)
            self.assertEqual(
                receipt["recommendation_ids"],
                [f"R-{index:02d}" for index in range(1, 7)],
            )
            for key in (
                "manifest_sha256",
                "markdown_sha256",
                "html_sha256",
                "validator_sha256",
            ):
                self.assertRegex(receipt[key], r"^[0-9A-F]{64}$")

            with self.assertRaisesRegex(ReportPairError, "refusing to overwrite"):
                write_report_pair(
                    manifest_path=manifest_path,
                    markdown_path=markdown_path,
                    html_path=html_path,
                )


if __name__ == "__main__":
    unittest.main()
