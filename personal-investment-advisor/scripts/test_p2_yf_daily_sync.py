import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import yf


class YfDailySyncContractTests(unittest.TestCase):
    def test_daily_sync_emits_one_batch_audit_and_no_derived_etf_history(self):
        positions = {
            "base_currency": "USD",
            "positions": [
                {
                    "symbol": "QQQ",
                    "name": "Invesco QQQ Trust",
                    "quantity": 5,
                    "avg_cost": 710.146,
                    "currency": "USD",
                    "market": "US",
                    "asset_type": "etf",
                }
            ],
        }
        info = {
            "symbol": "QQQ",
            "longName": "Invesco QQQ Trust",
            "regularMarketPrice": 600.1234,
            "exchange": "NGM",
            "currency": "USD",
            "quoteType": "ETF",
            "regularMarketTime": time.time() - 60,
            "marketState": "CLOSED",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path = Path(tmpdir) / "positions.json"
            positions_path.write_text(json.dumps(positions), encoding="utf-8")
            stdout = io.StringIO()
            argv = [
                "yf.py",
                "QQQ",
                "--daily-sync",
                "--positions-file",
                str(positions_path),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch(
                    "yf.resolve_symbol",
                    side_effect=AssertionError(
                        "Daily Sync must not re-resolve a validated portfolio symbol"
                    ),
                ),
                patch("yf.get_stock_data", return_value=(None, info, [], [])) as fetch,
                redirect_stdout(stdout),
                self.assertRaises(SystemExit) as raised,
            ):
                yf.main()

        self.assertEqual(raised.exception.code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(len(payload["records"]), 1)
        self.assertIn("portfolio_batch_audit", payload)
        binding = payload["portfolio_batch_audit"]["portfolio_snapshot_binding"]
        self.assertEqual(binding["active_position_count"], 1)
        self.assertEqual(binding["active_positions"][0]["quantity"], "5")
        self.assertEqual(len(binding["sha256"]), 64)
        record = payload["records"][0]
        self.assertNotIn("portfolio_batch_audit", record)
        self.assertNotIn("history", record)
        self.assertNotIn("summary", record)
        self.assertNotIn("news", record)
        self.assertEqual(record["portfolio_context"]["current_price"], 600.1234)
        self.assertEqual(record["data_sources"]["price"], "Yahoo Finance")
        self.assertEqual(record["data_sources"]["price_locator"], "yfinance:QQQ:quote")
        self.assertEqual(record["history_integrity"]["status"], "not_applicable")
        _, kwargs = fetch.call_args
        self.assertFalse(kwargs["fetch_price"])
        self.assertFalse(kwargs["fetch_news"])
        self.assertTrue(kwargs["fetch_info"])


if __name__ == "__main__":
    unittest.main()
