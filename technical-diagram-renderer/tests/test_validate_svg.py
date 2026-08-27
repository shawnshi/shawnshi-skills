from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts" / "validate-svg.py"


class ValidateSvgTests(unittest.TestCase):
    def validate(self, svg: str | bytes) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.svg"
            if isinstance(svg, bytes):
                path.write_bytes(svg)
            else:
                path.write_text(svg, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return result, json.loads(result.stdout)

    def test_valid_static_svg_with_marker(self) -> None:
        result, report = self.validate(
            """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
            <defs><marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7"/></marker></defs>
            <rect x="10" y="10" width="50" height="30"/>
            <path d="M 60 25 L 180 25" marker-end="url(#arrow)"/>
            <text x="20" y="80">安全 &amp; valid</text>
            </svg>"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["valid"])
        self.assertTrue(report["checks"]["references_resolve"])
        self.assertEqual(report["stats"]["marker_references"], 1)

    def test_valid_utf8_xml_declaration_is_supported(self) -> None:
        result, report = self.validate(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<text x="2" y="10">中文</text></svg>'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["valid"])

    def test_malformed_xml_fails(self) -> None:
        result, report = self.validate('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect></svg>')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report["valid"])
        self.assertIn("xml_not_well_formed", {issue["code"] for issue in report["errors"]})

    def test_duplicate_ids_fail(self) -> None:
        result, report = self.validate(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><rect id="x" width="5" height="5"/><circle id="x" cx="10" cy="10" r="2"/></svg>'
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate_id", {issue["code"] for issue in report["errors"]})

    def test_missing_and_wrong_marker_targets_fail(self) -> None:
        cases = {
            "missing": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M 1 1 L 10 10" marker-end="url(#none)"/></svg>',
            "wrong-type": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><defs><path id="not-marker" d="M0 0"/></defs><path d="M 1 1 L 10 10" marker-end="url(#not-marker)"/></svg>',
        }
        for name, svg in cases.items():
            with self.subTest(name=name):
                result, report = self.validate(svg)
                self.assertEqual(result.returncode, 1)
                codes = {issue["code"] for issue in report["errors"]}
                self.assertTrue(codes & {"missing_marker", "wrong_marker_target"})

    def test_active_content_and_external_urls_fail(self) -> None:
        cases = {
            "script": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><script>alert(1)</script></svg>',
            "event": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><rect width="5" height="5" onload="alert(1)"/></svg>',
            "external-url": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><rect width="5" height="5" fill="url(https://example.com/a.svg#x)"/></svg>',
            "href": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><textPath href="https://example.com/x">x</textPath></svg>',
            "css-import": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><style>@import url(https://example.com/x.css);</style></svg>',
            "foreign-object": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><foreignObject width="10" height="10"/></svg>',
        }
        for name, svg in cases.items():
            with self.subTest(name=name):
                result, report = self.validate(svg)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(report["valid"])

    def test_doctype_is_rejected_before_entity_expansion(self) -> None:
        result, report = self.validate(
            '<!DOCTYPE svg [<!ENTITY x "unsafe">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><text x="1" y="2">&x;</text></svg>'
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("doctype_forbidden", {issue["code"] for issue in report["errors"]})

    def test_delayed_mixed_case_doctype_is_rejected_across_full_file(self) -> None:
        svg = (
            " " * 5000
            + '<!DoCtYpE svg [<!EnTiTy x "unsafe">]>'
            + '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            + '<text x="1" y="2">&x;</text></svg>'
        )
        result, report = self.validate(svg)
        self.assertEqual(result.returncode, 1)
        self.assertIn("doctype_forbidden", {issue["code"] for issue in report["errors"]})

    def test_utf16_doctype_cannot_bypass_utf8_contract(self) -> None:
        svg = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE svg [<!ENTITY x "unsafe">]>'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            '<text x="1" y="2">&x;</text></svg>'
        ).encode("utf-16")
        result, report = self.validate(svg)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report["valid"])
        self.assertIn("invalid_encoding", {issue["code"] for issue in report["errors"]})

    def test_visible_element_outside_viewbox_fails(self) -> None:
        result, report = self.validate(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="90" y="20" width="30" height="20"/></svg>'
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("visible_element_outside_viewbox", {issue["code"] for issue in report["errors"]})
        self.assertEqual(report["stats"]["out_of_bounds"], 1)


if __name__ == "__main__":
    unittest.main()
