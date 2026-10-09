"""Contract tests for the channel coverage probe (zero-result control protocol).

A zero result is only acceptable when a *same-class* control proved the channel
answers for that class. The probe must also refuse to count a throttled empty-shell or
an unparseable response as zero, and must not emit an ``official_coverage`` block
unless coverage was actually proven.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_etf_packet as packet  # noqa: E402


class VerdictTests(unittest.TestCase):
    def test_zero_is_accepted_only_with_a_same_class_control(self):
        self.assertEqual(
            packet.channel_probe_verdict(0, 7, same_class_control=True, channel_available=True),
            ("covered_zero_events", "same_instrument_class_control"))
        self.assertEqual(
            packet.channel_probe_verdict(0, 7, same_class_control=False, channel_available=True),
            ("coverage_unproven", "cross_class_control_weak"))
        self.assertEqual(
            packet.channel_probe_verdict(0, 0, same_class_control=True, channel_available=True),
            ("coverage_unproven", "same_instrument_class_control"))

    def test_events_are_reported_as_covered(self):
        self.assertEqual(
            packet.channel_probe_verdict(3, 0, same_class_control=True, channel_available=True),
            ("covered_with_events", "same_instrument_class_control"))

    def test_unavailable_channel_never_yields_a_verdict(self):
        for target, control in ((None, 5), (5, None), (None, None)):
            with self.subTest(target=target, control=control):
                self.assertEqual(
                    packet.channel_probe_verdict(target, control, same_class_control=True,
                                                 channel_available=False),
                    ("channel_unavailable", "none"))


class ProbeCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = Path(self._tmp.name) / "task"
        self.task_dir.mkdir(parents=True)
        self.task_dir = Path(self._tmp.name) / "task"
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, fetcher, *, channel="cninfo", target="A", control="B",
                target_class="stock", control_class="stock") -> tuple[int, dict]:
        argv = ["coverage-probe", "--channel", channel, "--target", target,
                "--control", control, "--target-class", target_class,
                "--control-class", control_class,
                "--channel-scope", "test scope", "--as-of-date", "2026-09-27",
                "--task-dir", str(self.task_dir), "--window-days", "60"]
        buffer = io.StringIO()
        with mock.patch.object(packet, "_fetch_cninfo", side_effect=fetcher), \
             mock.patch.object(packet, "_fetch_nasdaq", side_effect=fetcher):
            with contextlib.redirect_stdout(buffer):
                code = packet.main(argv)
        return code, json.loads(buffer.getvalue())

    @staticmethod
    def response(count: int, *, details=None):
        raw = json.dumps({"totalRecordNum": count}).encode("utf-8")
        base = {"organization_id": "9900000000", "query_scope": "code_and_organization",
                "rows_parsed": True, "empty_shell": False}
        base.update(details or {})
        return raw, count, base

    def test_same_class_control_proves_a_zero_result(self):
        def fetcher(code, task_dir, window):
            return self.response(0 if code == "A" else 6)

        code, receipt = self.run_cli(fetcher)
        self.assertEqual(code, 0, receipt)
        self.assertEqual(receipt["detail_status"], "covered_zero_events")
        self.assertIsNotNone(receipt["official_coverage"])
        self.assertEqual(receipt["official_coverage"]["control_query_count"], 6)
        self.assertEqual(receipt["official_coverage"]["control_query"]["symbol"], "B")
        for capture in receipt["captures"]:
            self.assertTrue(capture["sha256"])
            self.assertTrue((self.task_dir / capture["file"]).is_file())

    def test_zero_control_cannot_be_used_as_evidence(self):
        def fetcher(code, task_dir, window):
            return self.response(0)

        code, receipt = self.run_cli(fetcher)
        self.assertEqual(code, 2)
        self.assertEqual(receipt["detail_status"], "coverage_unproven")
        self.assertIsNone(receipt["official_coverage"])

    def test_cross_class_control_is_weak_and_cannot_prove_coverage(self):
        def fetcher(code, task_dir, window):
            return self.response(0 if code == "A" else 6)

        code, receipt = self.run_cli(fetcher, target_class="etf", control_class="stock")
        self.assertEqual(code, 2)
        self.assertEqual(receipt["coverage_basis"], "cross_class_control_weak")
        self.assertIsNone(receipt["official_coverage"])

    def test_empty_shell_is_inconclusive_not_zero(self):
        def fetcher(code, task_dir, window):
            return self.response(0, details={"empty_shell": True, "attempts": 2})

        code, receipt = self.run_cli(fetcher)
        self.assertEqual(code, 2)
        self.assertEqual(receipt["detail_status"], "channel_unavailable")
        self.assertTrue(any("empty shell" in note for note in receipt["query_quality_notes"]))

    def test_unparseable_rows_are_a_channel_failure(self):
        def fetcher(code, task_dir, window):
            return self.response(0, details={"rows_parsed": False})

        code, receipt = self.run_cli(fetcher)
        self.assertEqual(code, 3)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["detail_status"], "channel_probe_failed")
        self.assertIn("not parseable", receipt["errors"][0])
        self.assertIsNone(receipt["official_coverage"])

    def test_transport_error_is_recorded_per_role(self):
        def fetcher(code, task_dir, window):
            if code == "A":
                raise TimeoutError("no answer")
            return self.response(4)

        code, receipt = self.run_cli(fetcher)
        self.assertEqual(code, 3)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["detail_status"], "channel_probe_failed")
        self.assertIn("TimeoutError: no answer", receipt["errors"][0])
        self.assertIn("no answer", json.dumps(receipt["captures"], ensure_ascii=False))
        self.assertIsNone(receipt["official_coverage"])

    def test_code_only_zero_adds_a_quality_note(self):
        def fetcher(code, task_dir, window):
            return self.response(0, details={"organization_id": None, "query_scope": "code_only"})

        _code, receipt = self.run_cli(fetcher)
        self.assertTrue(any("code only" in note for note in receipt["query_quality_notes"]))

    def test_unknown_channel_is_refused(self):
        code, payload = self.run_cli(lambda *a: self.response(1), channel="nope")
        self.assertEqual(code, 3)
        self.assertIn("unknown channel", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
