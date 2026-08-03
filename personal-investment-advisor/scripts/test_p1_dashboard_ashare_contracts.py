import contextlib
import io
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import akshare_fetcher
import test_investment_controls as fixtures
import yf as yf_module
from dashboard_gate import validate_dashboard
from dashboard_math_gate import validate_math_consistency


def valid_scenario_analysis():
    return {
        "valuation_method": "scenario-based operating evidence review",
        "base": {
            "assumptions": ["Current operating evidence remains stable"],
            "result": "Base operating case remains supported",
            "falsification_conditions": ["Core operating evidence weakens"],
        },
        "bull": {
            "assumptions": ["Key operating variables improve"],
            "result": "Upside operating case",
            "falsification_conditions": ["Expected improvement does not appear"],
        },
        "bear": {
            "assumptions": ["Demand and margins weaken"],
            "result": "Downside operating case",
            "falsification_conditions": ["Downside assumptions do not occur"],
        },
        "sensitivity": ["Demand", "Margin", "Capital intensity"],
    }


class DashboardStrictContractTests(unittest.TestCase):
    def test_new_dashboard_requires_explicit_scenarios_but_archive_read_is_compatible(self):
        dashboard = fixtures.valid_dashboard()
        dashboard.pop("scenario_analysis")
        self.assertEqual(validate_dashboard(dashboard), [])
        strict_errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertIn("scenario_analysis is required by the current strict contract", strict_errors)

        dashboard["scenario_analysis"] = valid_scenario_analysis()
        self.assertEqual(validate_dashboard(dashboard, require_scenarios=True), [])

    def test_math_gate_rejects_numeric_strings_and_material_value_error(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["portfolio_context"] = {
            "has_position": True,
            "quantity": "-2 shares",
            "avg_cost": 100,
            "current_price": 100,
            "market_value": 980,
            "cost_basis": 1000,
            "unrealized_pnl": -20,
            "unrealized_pnl_pct": 0,
            "fx_rate_to_base": 1,
        }
        errors = validate_math_consistency(dashboard)
        self.assertIn("portfolio_context.quantity must be a finite JSON number", errors)

        dashboard["portfolio_context"]["quantity"] = 10
        errors = validate_math_consistency(dashboard)
        self.assertIn(
            "portfolio_context.market_value is inconsistent with quantity * current_price * fx_rate_to_base",
            errors,
        )

    def test_evidence_must_obey_brief_cutoff_and_allowed_tiers(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["research_brief"]["as_of_date"] = "2026-07-22"
        dashboard["research_brief"]["source_policy"]["cutoff_date"] = "2026-07-22"
        dashboard["research_brief"]["source_policy"]["allowed_source_tiers"] = [
            "company_primary"
        ]
        dashboard["evidence_items"][0]["source_tier"] = "secondary"
        dashboard["evidence_items"][0]["published_at"] = "2026-08-01"
        dashboard["evidence_items"][0]["retrieved_at"] = "2026-08-01"
        dashboard["evidence_items"][0]["as_of_date"] = "2026-08-01"

        errors = validate_dashboard(dashboard)
        self.assertIn(
            "evidence_items[0].source_tier is not allowed by research_brief.source_policy",
            errors,
        )
        self.assertIn(
            "evidence_items[0].published_at cannot be after research_brief.source_policy.cutoff_date",
            errors,
        )
        self.assertIn(
            "evidence_items[0].as_of_date cannot be after research_brief.source_policy.cutoff_date",
            errors,
        )


class AShareFetcherContractTests(unittest.TestCase):
    def test_sector_placeholder_never_enters_metrics(self):
        fetcher = akshare_fetcher.StandaloneDataFetcher(sleep_min=0, sleep_max=0)
        self.assertIsNone(fetcher.get_sector_info("600519"))

    def test_isolated_provider_timeout_terminates_child_and_fails_closed(self):
        with patch.object(akshare_fetcher.multiprocessing, "get_context") as get_context:
            context = get_context.return_value
            receive_connection = MagicMock()
            send_connection = MagicMock()
            context.Pipe.return_value = (receive_connection, send_connection)
            receive_connection.poll.return_value = False
            process = context.Process.return_value
            process.is_alive.side_effect = [True, False]
            result = akshare_fetcher._run_isolated_provider(
                "akshare_chip_distribution",
                "600519",
                0.01,
            )

        self.assertTrue(result.empty)
        get_context.assert_called_once_with("spawn")
        context.Pipe.assert_called_once_with(duplex=False)
        process.start.assert_called_once_with()
        process.terminate.assert_called_once_with()
        process.join.assert_called_once_with(timeout=1.0)
        process.close.assert_called_once_with()
        receive_connection.close.assert_called_once_with()
        send_connection.close.assert_called_once_with()

    def test_isolated_provider_kill_fallback_and_start_failure_are_bounded(self):
        with patch.object(akshare_fetcher.multiprocessing, "get_context") as get_context:
            context = get_context.return_value
            receive_connection = MagicMock()
            send_connection = MagicMock()
            context.Pipe.return_value = (receive_connection, send_connection)
            receive_connection.poll.return_value = False
            process = context.Process.return_value
            process.is_alive.side_effect = [True, True, False]
            result = akshare_fetcher._run_isolated_provider(
                "efinance_quote", "600519", 0.01
            )

        self.assertTrue(result.empty)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.join.call_count, 2)
        process.close.assert_called_once_with()

        with patch.object(akshare_fetcher.multiprocessing, "get_context") as get_context:
            context = get_context.return_value
            receive_connection = MagicMock()
            send_connection = MagicMock()
            context.Pipe.return_value = (receive_connection, send_connection)
            process = context.Process.return_value
            process.start.side_effect = OSError("spawn blocked")
            result = akshare_fetcher._run_isolated_provider(
                "efinance_quote", "600519", 0.01
            )

        self.assertTrue(result.empty)
        receive_connection.close.assert_called_once_with()
        send_connection.close.assert_called_once_with()
        process.join.assert_not_called()

        with patch.object(akshare_fetcher.multiprocessing, "get_context") as get_context:
            context = get_context.return_value
            receive_connection = MagicMock()
            send_connection = MagicMock()
            context.Pipe.return_value = (receive_connection, send_connection)
            receive_connection.poll.return_value = True
            receive_connection.recv.side_effect = EOFError("truncated provider payload")
            process = context.Process.return_value
            process.is_alive.side_effect = [False, False]
            result = akshare_fetcher._run_isolated_provider(
                "efinance_quote", "600519", 0.01
            )

        self.assertTrue(result.empty)
        receive_connection.close.assert_called_once_with()
        process.join.assert_called_once_with(timeout=1.0)
        process.close.assert_called_once_with()

    def test_history_provider_failure_never_mutates_process_proxy(self):
        fetcher = akshare_fetcher.StandaloneDataFetcher(sleep_min=0, sleep_max=0)
        observed_proxy_values = []

        def fail_history(**kwargs):
            observed_proxy_values.append(
                (os.environ.get("http_proxy"), os.environ.get("https_proxy"))
            )
            raise ConnectionError("RemoteDisconnected")

        with (
            patch.dict(
                os.environ,
                {"http_proxy": "sentinel-http", "https_proxy": "sentinel-https"},
                clear=False,
            ),
            patch("akshare.stock_zh_a_hist", side_effect=fail_history),
            self.assertRaises(ConnectionError),
        ):
            akshare_fetcher.StandaloneDataFetcher.get_history.__wrapped__(
                fetcher,
                "600519",
                start_date="2026-07-01",
                end_date="2026-07-31",
            )

        self.assertEqual(
            observed_proxy_values,
            [("sentinel-http", "sentinel-https")],
        )

    def test_cli_emits_structured_provenance_and_gap_status(self):
        metrics = {
            "enhancement_status": "partial",
            "volume_ratio": 1.2,
            "turnover_rate": None,
            "profit_ratio": None,
            "avg_cost": None,
            "concentration": None,
            "amplitude": None,
            "chip_90_low": None,
            "chip_90_high": None,
            "chip_70_low": None,
            "chip_70_high": None,
            "belong_boards": None,
        }
        output = io.StringIO()
        argv = ["akshare_fetcher.py", "--symbol", "600519", "--mode", "enhanced"]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                akshare_fetcher.StandaloneDataFetcher,
                "get_enhanced_metrics",
                return_value=metrics,
            ),
            contextlib.redirect_stdout(output),
        ):
            exit_code = akshare_fetcher.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "insufficient_data")
        self.assertEqual(payload["symbol"], "600519")
        self.assertEqual(payload["as_of_date"], date.today().isoformat())
        self.assertTrue(payload["source_locator"])
        self.assertTrue(payload["retrieved_at"].endswith("+00:00"))
        self.assertIn("sector_info_unavailable", payload["data_gaps"])

    def test_yf_a_share_history_adapter_is_reachable_and_source_labelled(self):
        history_frame = pd.DataFrame(
            {
                "Open": [10.0, 10.1],
                "High": [10.2, 10.3],
                "Low": [9.9, 10.0],
                "Close": [10.1, 10.2],
                "Volume": [100, 120],
            },
            index=pd.to_datetime(["2026-07-29", "2026-07-30"]),
        )

        class DummyTicker:
            def history(self, **kwargs):
                raise AssertionError("Yahoo fallback should not be called")

        with (
            patch.object(yf_module.yf, "Ticker", return_value=DummyTicker()),
            patch.object(
                akshare_fetcher.StandaloneDataFetcher,
                "get_history",
                return_value=history_frame,
            ),
        ):
            history, _, _, errors = yf_module.get_stock_data(
                "600519.SS",
                fetch_info=False,
                fetch_news=False,
                a_share_history_source="akshare",
            )

        self.assertEqual(errors, [])
        self.assertEqual(history.attrs["pia_source"], "Akshare")
        self.assertEqual(history.attrs["pia_adjustment"], "qfq")


if __name__ == "__main__":
    unittest.main()
