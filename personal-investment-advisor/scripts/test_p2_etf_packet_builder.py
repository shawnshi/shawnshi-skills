"""Contract tests for the ETF history-integrity packet assembler (P0-4).

The assembler must hash the operator's evidence, run the real gate, and refuse to
publish a packet the gate did not verify — while never inventing a corporate action.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_etf_packet  # noqa: E402

AS_OF = "2026-09-27"


class PacketBuilderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.task_dir = self.root / "task"
        (self.task_dir / "raw").mkdir(parents=True)
        self.evidence_doc = self.task_dir / "raw" / "official_notice.html"
        self.evidence_doc.write_bytes(b"official fund notice body\n")
        self.evidence = self.root / "evidence.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write_evidence(self, **overrides) -> Path:
        payload = {
            "symbol": "159934.SZ",
            "as_of_date": AS_OF,
            "provider_source": "Yahoo Finance",
            "provider_source_locator": "yfinance:159934.SZ:history",
            "provider_adjustment": "provider_default",
            "official_coverage": {
                "source_locator": "https://www.efunds.com.cn/fund/159934.shtml",
                "retrieved_at": "2026-09-27T00:00:00+00:00",
                "control_query_count": 3,
                "control_query": {
                    "symbol": "510300.SS",
                    "channel_scope": "fund manager announcement channel covering listed funds",
                },
            },
            "official_events": [],
            "provider_events": [],
        }
        payload.update(overrides)
        self.evidence.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return self.evidence

    def run_builder(self, *extra: str) -> tuple[int, dict]:
        argv = ["--evidence-file", str(self.evidence), "--task-dir", str(self.task_dir), *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_etf_packet.main(argv)
        return code, json.loads(buffer.getvalue())

    def packet_path(self) -> Path:
        return self.task_dir / "inputs" / "history_integrity_159934_SZ.json"

    def test_zero_event_packet_with_control_query_is_verified(self):
        self.write_evidence()
        code, receipt = self.run_builder()
        self.assertEqual(code, 0, receipt)
        self.assertEqual(receipt["status"], "complete")
        self.assertTrue(receipt["packet_verified"])
        self.assertEqual(receipt["gate_detail_status"], "packet_verified")
        packet = json.loads(self.packet_path().read_text(encoding="utf-8"))
        self.assertEqual(packet["asset_type"], "etf")
        self.assertEqual(packet["official_coverage"]["result_count"], 0)
        self.assertEqual(receipt["packet_sha256"],
                         hashlib.sha256(self.packet_path().read_bytes()).hexdigest())

    def test_zero_events_without_a_control_query_is_rejected(self):
        self.write_evidence()
        payload = json.loads(self.evidence.read_text(encoding="utf-8"))
        payload["official_coverage"]["control_query_count"] = 0
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))
        code, receipt = self.run_builder()
        self.assertEqual(code, 2)
        self.assertFalse(receipt["packet_verified"])
        self.assertIn("zero_result_control_missing", receipt["gate_errors"])
        self.assertFalse(self.packet_path().exists())

    def test_provider_mismatch_is_reported_and_not_published(self):
        self.write_evidence(official_events=[{
            "event_type": "distribution", "effective_date": "2026-06-30", "factor": "0.05",
            "evidence_file": "raw/official_notice.html"}])
        code, receipt = self.run_builder()
        self.assertEqual(code, 2)
        self.assertFalse(receipt["packet_verified"])
        self.assertEqual(receipt["gate_detail_status"], "corporate_action_conflict")
        self.assertTrue(receipt["event_mismatches"]["missing_from_provider"])
        self.assertFalse(self.packet_path().exists())

    def test_allow_unverified_keeps_a_diagnostic_artifact(self):
        self.write_evidence(official_events=[{
            "event_type": "distribution", "effective_date": "2026-06-30", "factor": "0.05",
            "evidence_file": "raw/official_notice.html"}])
        code, receipt = self.run_builder("--allow-unverified")
        self.assertEqual(code, 2)
        self.assertTrue(self.packet_path().is_file())
        self.assertFalse(receipt["packet_verified"])

    def test_event_without_evidence_is_refused(self):
        self.write_evidence(official_events=[{
            "event_type": "distribution", "effective_date": "2026-06-30", "factor": "0.05"}])
        code, payload = self.run_builder()
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "packet_input_invalid")
        self.assertIn("evidence_file or evidence_locator", payload["errors"][0])

    def test_event_after_as_of_date_is_refused(self):
        self.write_evidence(official_events=[{
            "event_type": "distribution", "effective_date": "2026-10-01", "factor": "0.05",
            "evidence_locator": "https://www.efunds.com.cn/fund/159934.shtml"}])
        code, payload = self.run_builder()
        self.assertEqual(code, 3)
        self.assertIn("after as_of_date", payload["errors"][0])

    def test_reserved_test_locator_is_not_verified(self):
        self.write_evidence()
        payload = json.loads(self.evidence.read_text(encoding="utf-8"))
        payload["official_coverage"]["source_locator"] = "https://example.test/fund"
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))
        code, receipt = self.run_builder()
        self.assertEqual(code, 2)
        self.assertIn("reserved test locator", " ".join(receipt["gate_errors"]))

    def test_control_query_scope_is_required_for_auditability(self):
        self.write_evidence()
        payload = json.loads(self.evidence.read_text(encoding="utf-8"))
        payload["official_coverage"].pop("control_query")
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))
        code, result = self.run_builder()
        self.assertEqual(code, 3)
        self.assertIn("control_query must name the control symbol", result["errors"][0])

        payload["official_coverage"]["control_query"] = {
            "symbol": "159934.SZ", "channel_scope": "same instrument is not a control"}
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))
        code, result = self.run_builder()
        self.assertEqual(code, 3)
        self.assertIn("must differ from the target symbol", result["errors"][0])

        payload["official_coverage"]["control_query"] = {"symbol": "510300.SS"}
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))
        code, result = self.run_builder()
        self.assertEqual(code, 3)
        self.assertIn("channel_scope must state what the channel covers", result["errors"][0])

    def test_naive_retrieved_at_is_refused(self):
        self.write_evidence()
        payload = json.loads(self.evidence.read_text(encoding="utf-8"))
        payload["official_coverage"]["retrieved_at"] = "2026-09-27T00:00:00"
        self.evidence.write_bytes(json.dumps(payload).encode("utf-8"))
        code, result = self.run_builder()
        self.assertEqual(code, 3)
        self.assertIn("timezone-aware", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
