"""Contract tests for the A-share fundamentals channel (P0-5).

Regression target: akshare's default ``start_year='1900'`` returns an empty frame for
these symbols, so the screen reported "A-share financial indicators unavailable" with
zero metrics while the endpoint answered for an explicit window.  The fallback channel
and its provenance reporting are covered here as well.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import quality_screener as qs  # noqa: E402


def indicator_frame(gross_margin_values=None) -> pd.DataFrame:
    """Annual indicator rows shaped like akshare's real response."""
    return pd.DataFrame({
        "日期": ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31"],
        "净资产收益率(%)": [27.91, 22.93, 19.64, 22.58, 22.06],
        "销售净利率(%)": [18.283, 12.9735, 9.0454, 9.1619, 8.707],
        "销售毛利率(%)": gross_margin_values or [None] * 5,
    })


def abstract_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "选项": ["盈利能力", "盈利能力"],
        "指标": ["毛利率", "毛利率(单季度)"],
        "20260630": [20.1, 19.0],
        "20251231": [19.5, 18.0],
        "20241231": ["18.5", None],
        "20231231": [17.5, 16.0],
    })


class StartYearTests(unittest.TestCase):
    def test_window_derives_from_as_of_date(self):
        self.assertEqual(qs._a_share_start_year("2026-09-27"), 2021)
        self.assertEqual(qs._a_share_start_year("2030-01-01"), 2025)

    def test_window_never_precedes_1991(self):
        self.assertEqual(qs._a_share_start_year("1995-06-30"), 1991)
        self.assertEqual(qs._a_share_start_year(None) >= 1991, True)

    def test_provider_passes_an_explicit_start_year(self):
        captured: dict = {}

        class FakeAkshare:
            @staticmethod
            def stock_financial_analysis_indicator(symbol, start_year):
                captured["symbol"] = symbol
                captured["start_year"] = start_year
                return indicator_frame()

        original = sys.modules.get("akshare")
        sys.modules["akshare"] = FakeAkshare
        try:
            frame = qs._a_share_financial_provider("601899", 2021)
        finally:
            if original is not None:
                sys.modules["akshare"] = original
            else:
                sys.modules.pop("akshare", None)
        self.assertEqual(captured, {"symbol": "601899", "start_year": "2021"})
        self.assertEqual(len(frame), 5)


class AbstractChannelTests(unittest.TestCase):
    def test_annual_series_uses_only_december_columns_at_or_before_cutoff(self):
        series = qs._abstract_annual_series(abstract_frame(), "毛利率", "2026-09-27")
        self.assertEqual(series.tolist(), [19.5, 18.5, 17.5])

    def test_cutoff_excludes_later_annual_columns(self):
        series = qs._abstract_annual_series(abstract_frame(), "毛利率", "2023-12-31")
        self.assertEqual(series.tolist(), [17.5])

    def test_unknown_label_returns_empty(self):
        self.assertTrue(qs._abstract_annual_series(abstract_frame(), "不存在", None).empty)
        self.assertTrue(qs._abstract_annual_series(None, "毛利率", None).empty)

    def test_non_numeric_values_are_dropped_not_zeroed(self):
        frame = pd.DataFrame({"指标": ["毛利率"], "20251231": ["n/a"], "20241231": [12.0]})
        series = qs._abstract_annual_series(frame, "毛利率", None)
        self.assertEqual(series.tolist(), [12.0])


class ExtractionTests(unittest.TestCase):
    def test_gross_margin_falls_back_to_the_abstract_channel_with_provenance(self):
        # This channel test must not depend on a live AkShare response.
        with patch.object(qs, "run_provider", return_value=indicator_frame()), patch.object(qs, "require_data", side_effect=lambda outcome: outcome):
            metrics, evidence = qs.extract_a_share_metrics(
                "601899.SS", "2026-09-27", abstract_frame=abstract_frame())
        # mean of the three qualifying annual values 19.5 / 18.5 / 17.5
        self.assertAlmostEqual(metrics["gross_margin_avg"], 0.185, places=6)
        self.assertEqual(evidence["metric_channels"]["gross_margin_avg"],
                         "akshare_financial_abstract:毛利率")
        self.assertEqual(evidence["start_year"], 2021)

    def test_indicator_channel_wins_when_it_is_populated(self):
        original_provider = qs.run_provider
        original_require = qs.require_data
        qs.run_provider = lambda function, *a, **k: indicator_frame([25.0, 24.0, 23.0, 22.0, 21.0])
        qs.require_data = lambda outcome: outcome
        try:
            metrics, evidence = qs.extract_a_share_metrics(
                "601899.SS", "2026-09-27", abstract_frame=abstract_frame())
        finally:
            qs.run_provider = original_provider
            qs.require_data = original_require
        self.assertAlmostEqual(metrics["gross_margin_avg"], 0.23, places=6)
        self.assertEqual(evidence["metric_channels"]["gross_margin_avg"],
                         "akshare_financial_analysis_indicator")

    def test_unavailable_metric_names_the_reason(self):
        original_provider = qs.run_provider
        original_require = qs.require_data
        qs.run_provider = lambda function, *a, **k: indicator_frame()
        qs.require_data = lambda outcome: outcome
        try:
            metrics, evidence = qs.extract_a_share_metrics(
                "601899.SS", "2026-09-27", abstract_frame=abstract_frame())
        finally:
            qs.run_provider = original_provider
            qs.require_data = original_require
        self.assertIsNone(metrics["dilution"])
        self.assertIn("dilution", evidence["unavailable_metrics"])
        self.assertNotIn("dilution", evidence["metric_channels"])
        self.assertIn("share-count", evidence["unavailable_metrics"]["dilution"])

    def test_empty_indicator_frame_still_fails_closed(self):
        original_provider = qs.run_provider
        original_require = qs.require_data
        qs.run_provider = lambda function, *a, **k: pd.DataFrame()
        qs.require_data = lambda outcome: outcome
        try:
            with self.assertRaises(qs.FinancialDataUnavailable) as ctx:
                qs.extract_a_share_metrics("601899.SS", "2026-09-27")
        finally:
            qs.run_provider = original_provider
            qs.require_data = original_require
        self.assertIn("start_year=2021", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
