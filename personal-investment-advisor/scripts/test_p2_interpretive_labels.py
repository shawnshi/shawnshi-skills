"""Contract tests for the interpretive label vocabulary (P1-4).

Labels must be traceable (as_of + rationale), strong claims must carry trigger
evidence, and drift between two assignment files must be measurable.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_labels  # noqa: E402


class LabelVocabularyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, payload) -> Path:
        path = self.root / name
        path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return path

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_labels.main(argv)
        return code, json.loads(buffer.getvalue())

    def assignment(self, axis: str, rows) -> Path:
        return self.write(f"{axis}.json", {"axis": axis, "as_of": "2026-09-27",
                                           "assignments": rows})

    def test_shipped_vocabulary_defines_both_axes(self):
        vocabulary = pia_labels.load_vocabulary()
        self.assertEqual(sorted(vocabulary["axes"]), ["financial_product", "thesis"])
        for axis in ("financial_product", "thesis"):
            labels = pia_labels.axis_labels(vocabulary, axis)
            self.assertIn("insufficient_evidence", labels)
            for rule in labels.values():
                self.assertTrue(rule["definition"])
                self.assertTrue(rule["must_not_imply"])

    def test_vocab_command_lists_labels(self):
        code, payload = self.run_cli(["vocab", "--axis", "thesis"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(payload["labels"]),
                         ["fatal_breach", "insufficient_evidence", "intact_with_risks",
                          "materially_weakened"])

    def test_unknown_axis_is_refused(self):
        code, payload = self.run_cli(["vocab", "--axis", "nope"])
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "label_check_input_invalid")

    def test_valid_assignment_file_passes(self):
        path = self.assignment("financial_product", [
            {"symbol": "601899.SS", "label": "watch", "rationale": "capital allocation flag",
             "evidence_ids": ["ex-601899-window"]},
            {"symbol": "QQQ", "label": "insufficient_evidence",
             "rationale": "no per-share NAV channel"},
        ])
        code, payload = self.run_cli(["check", "--file", str(path)])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["label_counts"], {"watch": 1, "insufficient_evidence": 1})

    def test_label_outside_the_vocabulary_is_refused(self):
        path = self.assignment("financial_product", [
            {"symbol": "601899.SS", "label": "bullish", "rationale": "x",
             "evidence_ids": ["e"]}])
        code, payload = self.run_cli(["check", "--file", str(path)])
        self.assertEqual(code, 3)
        self.assertIn("not in the financial_product vocabulary", payload["errors"][0])

    def test_rationale_and_evidence_are_required(self):
        path = self.assignment("financial_product", [
            {"symbol": "601899.SS", "label": "watch", "rationale": "  "}])
        _code, payload = self.run_cli(["check", "--file", str(path)])
        self.assertTrue(any("rationale is required" in error for error in payload["errors"]))
        self.assertTrue(any("evidence_ids is required" in error for error in payload["errors"]))

    def test_strong_thesis_label_needs_trigger_evidence(self):
        path = self.assignment("thesis", [
            {"symbol": "300253.SZ", "label": "materially_weakened", "rationale": "why",
             "evidence_ids": ["h1"]}])
        code, payload = self.run_cli(["check", "--file", str(path)])
        self.assertEqual(code, 3)
        self.assertTrue(any("trigger_evidence is required" in error for error in payload["errors"]))
        path = self.assignment("thesis", [
            {"symbol": "300253.SZ", "label": "materially_weakened", "rationale": "why",
             "evidence_ids": ["h1"], "trigger_evidence": ["h1"]}])
        self.assertEqual(self.run_cli(["check", "--file", str(path)])[0], 0)

    def test_duplicate_symbol_and_bad_as_of_are_refused(self):
        path = self.assignment("financial_product", [
            {"symbol": "A", "label": "stable", "rationale": "r", "evidence_ids": ["e"]},
            {"symbol": "A", "label": "watch", "rationale": "r", "evidence_ids": ["e"]}])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["as_of"] = "2026-13-45"
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        code, report = self.run_cli(["check", "--file", str(path)])
        self.assertEqual(code, 3)
        self.assertTrue(any("duplicated" in error for error in report["errors"]))
        self.assertTrue(any("as_of is not a real date" in error for error in report["errors"]))

    def test_drift_is_measurable_between_two_files(self):
        first = self.assignment("financial_product", [
            {"symbol": "601899.SS", "label": "stable", "rationale": "r", "evidence_ids": ["e"]},
            {"symbol": "300253.SZ", "label": "watch", "rationale": "r", "evidence_ids": ["e"]}])
        second = self.write("second.json", {
            "axis": "financial_product", "as_of": "2026-10-04",
            "assignments": [
                {"symbol": "601899.SS", "label": "watch", "rationale": "r", "evidence_ids": ["e"]},
                {"symbol": "GOOG", "label": "stable", "rationale": "r", "evidence_ids": ["e"]}],
        })
        code, payload = self.run_cli(["check", "--file", str(second), "--previous", str(first)])
        self.assertEqual(code, 0)
        drift = payload["label_drift"]
        self.assertEqual(drift["changed"], {"601899.SS": {"from": "stable", "to": "watch"}})
        self.assertEqual(drift["added"], ["GOOG"])
        self.assertEqual(drift["removed"], ["300253.SZ"])


if __name__ == "__main__":
    unittest.main()
