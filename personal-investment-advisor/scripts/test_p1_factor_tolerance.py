"""Contract tests for the optional, self-documenting factor tolerance.

Provider action series are approximations of the manager's announced ratios (the
159934 share merger is 0.948126035 while the provider publishes 0.948128). Some way
to express that difference is needed, but it must never be silent or fitted per
packet: the default stays exact equality, and a declared tolerance must state its
basis, magnitude, justification and source, and every pair matched only within
tolerance is echoed in the result.
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

import pia_etf_packet as packet  # noqa: E402
from history_integrity_gate import evaluate_history_integrity  # noqa: E402

OFFICIAL_SPLIT = {"event_type": "split", "effective_date": "2025-09-22",
                  "factor": "1:1.054712"}
PROVIDER_SPLIT = {"event_type": "split", "effective_date": "2025-09-22",
                  "factor": "1:1.054710"}


def make_packet(*, official=None, provider=None, tolerance=None) -> dict:
    payload = {
        "symbol": "159934.SZ",
        "asset_type": "etf",
        "as_of_date": "2026-09-27",
        "provider_source": "Yahoo Finance",
        "provider_source_locator": "yfinance:159934.SZ:history",
        "provider_adjustment": "provider_default",
        "official_coverage": {
            "source_locator": "https://www.efunds.com.cn/fund/159934.shtml",
            "retrieved_at": "2026-09-27T05:55:00+00:00",
            "coverage_status": "complete",
            "result_count": len(official if official is not None else [OFFICIAL_SPLIT]),
            "control_query_count": 0,
        },
        "official_events": [OFFICIAL_SPLIT] if official is None else official,
        "provider_events": [PROVIDER_SPLIT] if provider is None else provider,
    }
    if tolerance is not None:
        payload["factor_tolerance"] = tolerance
    return payload


def valid_tolerance(**overrides) -> dict:
    payload = {"basis": "relative", "value": 1e-4,
               "justification": "provider publishes 6 decimals, the manager ratio has 9",
               "source_locator": "https://manager.example.org/notice"}
    payload.update(overrides)
    return payload


class FactorParsingTests(unittest.TestCase):
    def test_ratio_and_plain_factors_parse(self):
        self.assertAlmostEqual(packet_main_parse("1:1.054712"), 1 / 1.054712, places=12)
        self.assertAlmostEqual(packet_main_parse("0.751"), 0.751, places=12)

    def test_unparsable_factors_return_none(self):
        for value in ("", "abc", "1:0", "1:2:3"):
            self.assertIsNone(packet_main_parse(value))


def packet_main_parse(value: str):
    from history_integrity_gate import _factor_numeric
    return _factor_numeric(value)


class GateToleranceTests(unittest.TestCase):
    def test_exact_match_needs_no_tolerance(self):
        report = evaluate_history_integrity(make_packet(official=[PROVIDER_SPLIT]))
        self.assertTrue(report["packet_verified"])
        self.assertFalse(report["tolerance_used"])
        self.assertEqual(report["event_mismatches"]["within_tolerance"], [])

    def test_default_is_still_exact_equality(self):
        report = evaluate_history_integrity(make_packet())
        self.assertFalse(report["packet_verified"])
        self.assertEqual(report["detail_status"], "corporate_action_conflict")
        # in-process the mismatch sets hold tuples; they serialise as arrays
        self.assertIn(("split", "2025-09-22", "1:1.054712"),
                      report["event_mismatches"]["missing_from_provider"])

    def test_declared_tolerance_verifies_and_discloses_the_pair(self):
        report = evaluate_history_integrity(make_packet(tolerance=valid_tolerance()))
        self.assertTrue(report["packet_verified"], report)
        self.assertTrue(report["tolerance_used"])
        self.assertEqual(report["event_mismatches"]["within_tolerance"],
                         [{"official": ["split", "2025-09-22", "1:1.054712"],
                           "provider": ["split", "2025-09-22", "1:1.054710"]}])
        self.assertEqual(report["factor_tolerance"]["basis"], "relative")

    def test_tolerance_that_does_not_cover_the_gap_still_fails(self):
        report = evaluate_history_integrity(make_packet(tolerance=valid_tolerance(value=1e-9)))
        self.assertFalse(report["packet_verified"])
        self.assertEqual(report["detail_status"], "corporate_action_conflict")

    def test_absolute_basis_is_supported(self):
        report = evaluate_history_integrity(make_packet(tolerance=valid_tolerance(
            basis="absolute", value=1e-5)))
        self.assertTrue(report["packet_verified"], report)

    def test_date_and_type_mismatches_are_never_tolerated(self):
        moved = dict(PROVIDER_SPLIT, effective_date="2025-09-23")
        report = evaluate_history_integrity(make_packet(provider=[moved],
                                                        tolerance=valid_tolerance()))
        self.assertFalse(report["packet_verified"])
        retyped = dict(PROVIDER_SPLIT, event_type="dividend")
        report = evaluate_history_integrity(make_packet(provider=[retyped],
                                                        tolerance=valid_tolerance()))
        self.assertFalse(report["packet_verified"])

    def test_an_undocumented_tolerance_is_rejected(self):
        for broken in (valid_tolerance(justification=""), valid_tolerance(source_locator=""),
                       valid_tolerance(basis="fuzzy"), valid_tolerance(value=0),
                       "not-an-object"):
            with self.subTest(broken=broken):
                report = evaluate_history_integrity(make_packet(tolerance=broken))
                self.assertFalse(report["packet_verified"])
                self.assertEqual(report["detail_status"], "coverage_incomplete")
                self.assertTrue(any("factor_tolerance" in error for error in report["errors"]))


class AssemblerToleranceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = Path(self._tmp.name) / "task"
        (self.task_dir / "raw").mkdir(parents=True)
        self.evidence = self.task_dir / "inputs" / "evidence.json"
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        payload = make_packet()
        payload.pop("factor_tolerance", None)
        for event in payload["official_events"]:
            event["evidence_locator"] = "https://manager.example.org/notice"
        for event in payload["provider_events"]:
            event["evidence_locator"] = "https://provider.example.org/actions"
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *extra: str) -> tuple[int, dict]:
        argv = ["assemble", "--evidence-file", str(self.evidence),
                "--task-dir", str(self.task_dir), "--force", *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = packet.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_assembler_refuses_an_incomplete_tolerance(self):
        code, payload = self.run_cli("--factor-tolerance", "0.0001", "--tolerance-basis",
                                     "relative")
        self.assertEqual(code, 3)
        self.assertIn("--tolerance-justification is required", payload["errors"][0])

    def test_assembler_records_a_complete_tolerance(self):
        code, receipt = self.run_cli(
            "--factor-tolerance", "0.0001", "--tolerance-basis", "relative",
            "--tolerance-justification", "provider precision",
            "--tolerance-source", "https://manager.example.org/notice")
        self.assertEqual(code, 0, receipt)
        self.assertTrue(receipt["packet_verified"])
        self.assertTrue(receipt["tolerance_used"])
        written = json.loads(Path(receipt["packet_file"]).read_text(encoding="utf-8"))
        self.assertEqual(written["factor_tolerance"]["value"], 0.0001)
        self.assertEqual(written["factor_tolerance"]["basis"], "relative")

    def test_no_tolerance_flags_keeps_the_packet_exact(self):
        code, receipt = self.run_cli()
        self.assertEqual(code, 2)
        self.assertFalse(receipt["packet_verified"])
        self.assertIsNone(receipt["factor_tolerance"])


if __name__ == "__main__":
    unittest.main()
