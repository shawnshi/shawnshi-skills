"""Contract tests for ``pia_refresh.py`` (isolated FX-refreshed snapshot).

Guarantees under test:
* the positions input is never modified (hash before == hash after);
* a currency whose dated observation is missing, stale or unusable fails the run
  instead of falling back to a default rate;
* the derived snapshot and the receipt are bound by SHA-256 and a dataset://
  locator that downstream builders can consume.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_refresh  # noqa: E402
from unittest import mock  # noqa: E402

TODAY = datetime.date.today()


def positions_payload() -> dict:
    return {
        "base_currency": "CNY",
        "positions": [
            {"symbol": "AAA", "name": "Test US equity", "quantity": 10, "avg_cost": 100.0,
             "currency": "USD", "market": "US", "asset_type": "stock"},
            {"symbol": "CASH_CNY", "name": "CNY cash", "quantity": 1000, "avg_cost": 1.0,
             "currency": "CNY", "market": "CASH", "asset_type": "cash"},
            {"symbol": "CASH_USD", "name": "USD cash", "quantity": 50, "avg_cost": 1.0,
             "currency": "USD", "market": "CASH", "asset_type": "cash"},
        ],
        "exchange_rates": {"CNY": 1.0, "USD": 6.6},
        "exchange_rate_metadata": {
            "USD": {"pair": "USD/CNY", "as_of": (TODAY - datetime.timedelta(days=11)).isoformat(),
                    "source": "stale fixture", "retrieved_at": "2026-09-16T00:00:00+00:00"}
        },
    }


def fx_capture(symbol: str = "CNY=X", *, days_old: int = 0, close: float = 6.7037,
               with_history: bool = True) -> bytes:
    observation_date = (TODAY - datetime.timedelta(days=days_old)).isoformat()
    record = {
        "symbol": symbol,
        "history": [{"Date": observation_date, "Close": close}] if with_history else [],
        "info": {"marketState": "CLOSED", "regularMarketTime": 1790458368},
    }
    return json.dumps([record]).encode("utf-8")


class RefreshSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.positions = self.root / "portfolio.json"
        self.positions.write_text(json.dumps(positions_payload()), encoding="utf-8")
        self.task_dir = self.root / "task"
        self.derived = self.task_dir / "inputs" / "positions_fx_snapshot.json"
        self.receipt = self.task_dir / "out" / "refresh_receipt.json"
        self.capture = self.root / "fx.json"
        self.capture.write_bytes(fx_capture())

    def tearDown(self):
        self._tmp.cleanup()

    def run_refresh(self, *extra: str) -> tuple[int, dict]:
        argv = ["--positions-file", str(self.positions), "--task-dir", str(self.task_dir),
                "--fx-observation-file", str(self.capture), *extra]
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = pia_refresh.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_successful_refresh_binds_inputs_and_derives_snapshot(self):
        before = hashlib.sha256(self.positions.read_bytes()).hexdigest()
        code, payload = self.run_refresh()
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertTrue(payload["original_unchanged"])
        self.assertEqual(payload["positions_sha256_before"], before)
        self.assertEqual(hashlib.sha256(self.positions.read_bytes()).hexdigest(), before)

        derived = json.loads(self.derived.read_text(encoding="utf-8"))
        self.assertEqual(derived["exchange_rates"]["USD"], 6.7037)
        self.assertEqual(derived["exchange_rates"]["CNY"], 1.0)
        metadata = derived["exchange_rate_metadata"]["USD"]
        self.assertEqual(metadata["pair"], "USD/CNY")
        self.assertEqual(metadata["observation_field"], "history[-1].Close")
        self.assertEqual(metadata["content_sha256"],
                         hashlib.sha256(self.capture.read_bytes()).hexdigest())
        self.assertEqual(derived["positions"], positions_payload()["positions"])

        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["derived_sha256"],
                         hashlib.sha256(self.derived.read_bytes()).hexdigest())
        self.assertTrue(receipt["dataset_manifest"][0]["locator"].startswith("dataset://pia/tasks/"))
        self.assertTrue((self.task_dir / receipt["dataset_manifest"][0]["file"]).is_file())

    def test_stale_observation_fails_instead_of_falling_back(self):
        self.capture.write_bytes(fx_capture(days_old=10))
        code, payload = self.run_refresh()
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "insufficient_data")
        self.assertTrue(any("over the 72.0h limit" in error for error in payload["errors"]))
        self.assertFalse(self.derived.exists())

    def test_missing_observation_for_currency_fails(self):
        self.capture.write_bytes(fx_capture(symbol="HKDCNY=X"))
        code, payload = self.run_refresh()
        self.assertEqual(code, 2)
        self.assertIn("fx_observation_unavailable", payload["detail_status"])
        self.assertFalse(self.derived.exists())

    def test_empty_history_is_not_a_zero_rate(self):
        self.capture.write_bytes(fx_capture(with_history=False))
        code, payload = self.run_refresh()
        self.assertEqual(code, 2)
        self.assertTrue(any("no usable Close observation" in error for error in payload["errors"]))

    def test_existing_derived_snapshot_requires_force(self):
        self.assertEqual(self.run_refresh()[0], 0)
        original = self.derived.read_bytes()
        code, payload = self.run_refresh()
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "derived_snapshot_exists")
        self.assertEqual(self.derived.read_bytes(), original)
        self.assertEqual(self.run_refresh("--force")[0], 0)

    def test_invalid_positions_contract_fails_closed(self):
        broken = positions_payload()
        broken["positions"][0].pop("avg_cost")
        self.positions.write_text(json.dumps(broken), encoding="utf-8")
        code, payload = self.run_refresh()
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "positions_contract_failed")
        self.assertFalse(self.derived.exists())

    def test_missing_capture_file_reports_gap(self):
        missing = self.root / "absent.json"
        argv = ["--positions-file", str(self.positions), "--task-dir", str(self.task_dir),
                "--fx-observation-file", str(missing)]
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = pia_refresh.main(argv)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["detail_status"], "fx_capture_missing")

    def test_derived_path_may_not_be_the_positions_file(self):
        collision = self.task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
        collision.parent.mkdir(parents=True, exist_ok=True)
        collision.write_text(json.dumps(positions_payload()), encoding="utf-8")
        before = hashlib.sha256(collision.read_bytes()).hexdigest()
        argv = ["--positions-file", str(collision), "--task-dir", str(self.task_dir),
                "--fx-observation-file", str(self.capture)]
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = pia_refresh.main(argv)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertTrue(any("overwrite" in error for error in payload["errors"]))
        self.assertEqual(hashlib.sha256(collision.read_bytes()).hexdigest(), before)

    def test_currency_mapping_matches_existing_snapshot_convention(self):
        self.assertEqual(pia_refresh.yahoo_fx_symbol("USD", "CNY"), "CNY=X")
        self.assertEqual(pia_refresh.yahoo_fx_symbol("HKD", "CNY"), "HKDCNY=X")
        self.assertEqual(pia_refresh.yahoo_fx_symbol("CNY", "CNY"), "")


if __name__ == "__main__":
    unittest.main()

class FxProbeResilienceTests(unittest.TestCase):
    """A transient provider hiccup must be retried once, but never silently."""

    def _completed(self, returncode, stdout=b"", stderr=b""):
        import subprocess
        return subprocess.CompletedProcess(args=["yf.py"], returncode=returncode,
                                           stdout=stdout, stderr=stderr)

    def test_structured_stdout_reason_is_recovered(self):
        payload = json.dumps({"status": "failed", "detail_status": "provider_error",
                              "errors": ["connection reset by peer"]}).encode("utf-8")
        reason, is_transient = pia_refresh._failure_reason(payload, b"", 2)
        self.assertIn("provider_error", reason)
        self.assertIn("connection reset", reason)
        self.assertTrue(is_transient)

    def test_contract_failure_is_not_transient(self):
        payload = json.dumps({"status": "failed", "detail_status": "invalid_input",
                              "errors": ["symbol must be a known FX pair"]}).encode("utf-8")
        reason, is_transient = pia_refresh._failure_reason(payload, b"", 2)
        self.assertFalse(is_transient)
        self.assertIn("invalid_input", reason)

    def test_missing_reason_is_reported_and_treated_as_transient(self):
        reason, is_transient = pia_refresh._failure_reason(b"", b"", 2)
        self.assertIn("no structured reason", reason)
        self.assertTrue(is_transient)

    def test_transient_failure_is_retried_once_then_succeeds(self):
        calls = {"count": 0}

        def fake_run(command, capture_output=True, timeout=None, check=False):
            calls["count"] += 1
            if calls["count"] == 1:
                return self._completed(2, b"", b"")
            return self._completed(0, fx_capture(), b"")

        with mock.patch.object(pia_refresh.subprocess, "run", side_effect=fake_run):
            raw, source = pia_refresh.fetch_fx_capture("CNY=X", None)
        self.assertEqual(calls["count"], 2)
        self.assertIn("attempts=2", source)
        self.assertIn(b"CNY=X", raw)

    def test_contract_failure_is_not_retried(self):
        calls = {"count": 0}

        def fake_run(command, capture_output=True, timeout=None, check=False):
            calls["count"] += 1
            payload = json.dumps({"status": "failed", "detail_status": "invalid_input",
                                  "errors": ["unknown symbol"]}).encode("utf-8")
            return self._completed(2, payload, b"")

        with mock.patch.object(pia_refresh.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                pia_refresh.fetch_fx_capture("CNY=X", None)
        self.assertEqual(calls["count"], 1)
        self.assertIn("invalid_input", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
