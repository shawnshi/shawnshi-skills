import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import test_investment_controls as fixtures
from watchlist_gate import evaluate_watchlist


NOW = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)


def dashboard_with_boundaries():
    dashboard = fixtures.valid_dashboard()
    dashboard["monitoring_boundaries"] = fixtures.valid_monitoring_boundaries()
    return dashboard


def runtime_quote(**overrides):
    quote = fixtures.valid_runtime_quote()
    quote.update(overrides)
    return quote


class RuntimeQuoteWatchlistTests(unittest.TestCase):
    def test_boundaries_require_runtime_quote_but_undefined_thresholds_do_not(self):
        missing_quote = evaluate_watchlist(dashboard_with_boundaries(), now=NOW)
        self.assertEqual(missing_quote["evaluation_status"], "insufficient_data")
        self.assertEqual(
            missing_quote["quote_validation_errors"], ["runtime_quote_missing"]
        )

        undefined = evaluate_watchlist(fixtures.valid_dashboard(), now=NOW)
        self.assertEqual(undefined["evaluation_status"], "thresholds_undefined")
        self.assertEqual(undefined["quote_validation_errors"], [])

    def test_runtime_quote_replaces_archived_price_and_freshness_flag(self):
        dashboard = dashboard_with_boundaries()
        dashboard["freshness_flags"]["price_data_fresh"] = False
        dashboard["dashboard"]["data_perspective"]["price_position"][
            "current_price"
        ] = 1

        report = evaluate_watchlist(
            dashboard,
            runtime_quote(current_price=125),
            now=NOW,
        )

        self.assertEqual(report["evaluation_status"], "complete")
        self.assertEqual(report["categories"]["upside_boundary_crossed"], ["upper-001"])
        self.assertTrue(
            all(item["current_price"] == 125 for item in report["evaluations"])
        )

    def test_rejects_each_required_runtime_quote_field(self):
        cases = {
            "symbol": ("MSFT", "runtime_quote_symbol_mismatch"),
            "current_price": (False, "runtime_quote_price_invalid"),
            "currency": ("CNY", "runtime_quote_currency_mismatch"),
            "as_of": ("2026-07-30 20:00:00", "runtime_quote_as_of_invalid"),
            "source": ("", "runtime_quote_source_invalid"),
            "market_state": ("UNKNOWN", "runtime_quote_market_state_unknown"),
            "unrecognized_market_state": (
                "NOT_A_MARKET_STATE",
                "runtime_quote_market_state_unknown",
            ),
        }
        for field, (value, expected_error) in cases.items():
            with self.subTest(field=field):
                quote_field = "market_state" if field == "unrecognized_market_state" else field
                quote = runtime_quote(**{quote_field: value})
                report = evaluate_watchlist(dashboard_with_boundaries(), quote, now=NOW)
                self.assertEqual(report["evaluation_status"], "insufficient_data")
                self.assertIn(expected_error, report["quote_validation_errors"])
                self.assertEqual(report["evaluations"], [])

    def test_now_and_max_age_are_deterministic_and_fail_stale_closed_quote(self):
        report = evaluate_watchlist(
            dashboard_with_boundaries(),
            runtime_quote(as_of="2026-07-30T19:59:59+00:00", market_state="CLOSED"),
            now=NOW,
            max_age_seconds=3600,
        )
        self.assertEqual(report["evaluation_status"], "insufficient_data")
        self.assertEqual(report["quote_validation_errors"], ["runtime_quote_stale"])

    def test_closed_market_is_not_treated_as_halted(self):
        closed = evaluate_watchlist(
            dashboard_with_boundaries(),
            runtime_quote(as_of="2026-07-27T22:00:00+00:00", market_state="CLOSED"),
            now=NOW,
        )
        self.assertEqual(closed["evaluation_status"], "complete")
        self.assertEqual(closed["runtime_quote"]["market_state"], "CLOSED")

        halted = evaluate_watchlist(
            dashboard_with_boundaries(),
            runtime_quote(market_state="HALTED"),
            now=NOW,
        )
        self.assertEqual(halted["evaluation_status"], "insufficient_data")
        self.assertIn("runtime_quote_market_halted", halted["quote_validation_errors"])

    def test_future_quote_and_invalid_evaluation_clock_fail_closed(self):
        future = evaluate_watchlist(
            dashboard_with_boundaries(),
            runtime_quote(as_of="2026-07-30T21:06:00+00:00"),
            now=NOW,
        )
        self.assertIn("runtime_quote_from_future", future["quote_validation_errors"])

        invalid_clock = evaluate_watchlist(
            dashboard_with_boundaries(),
            runtime_quote(),
            now=datetime(2026, 7, 30, 21, 0),
        )
        self.assertEqual(invalid_clock["evaluation_status"], "insufficient_data")
        self.assertEqual(
            invalid_clock["quote_validation_errors"], ["evaluation_clock_invalid"]
        )

    def test_cli_without_runtime_quote_returns_structured_insufficient_data(self):
        dashboard = dashboard_with_boundaries()
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            dashboard_path = Path(tmpdir) / "dashboard.json"
            dashboard_path.write_text(
                json.dumps(dashboard, ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "watchlist_gate.py"),
                    str(dashboard_path),
                    "--now",
                    "2026-07-30T21:00:00+00:00",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["evaluation_status"], "insufficient_data")
        self.assertEqual(report["quote_validation_errors"], ["runtime_quote_missing"])

    def test_cli_unreadable_quote_is_not_mislabeled_as_dashboard_failure(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            dashboard_path = Path(tmpdir) / "dashboard.json"
            quote_path = Path(tmpdir) / "quote.json"
            dashboard_path.write_text(
                json.dumps(dashboard_with_boundaries(), ensure_ascii=False),
                encoding="utf-8",
            )
            quote_path.write_text("{", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "watchlist_gate.py"),
                    str(dashboard_path),
                    "--quote-snapshot",
                    str(quote_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(
            report["categories"]["insufficient_data"],
            ["runtime_quote_unreadable"],
        )
        self.assertEqual(
            report["quote_validation_errors"], ["runtime_quote_unreadable"]
        )
        self.assertEqual(report["validation_errors"], [])


if __name__ == "__main__":
    unittest.main()
