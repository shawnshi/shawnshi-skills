"""Contract tests for the share-count change (dilution/accretion) assessment.

The assessment must be signed (a buyback is accretion), point-in-time (selected by
announcement date, reported with its effective date), and fail closed when the channel
returns nothing — a missing ledger is never a zero change.
"""
from __future__ import annotations

import contextlib
import datetime
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

import pia_dilution as dilution  # noqa: E402

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas ships with the channel dependency
    pd = None

AS_OF = "2026-09-27"


def frame(rows: list[tuple[str, str, float, float | None, str]]):
    """(变动日期, 公告日期, 总股本[万股], 已流通股份[万股], 变动原因) -> payload table."""

    return pd.DataFrame([
        {"变动日期": effective, "公告日期": announced, "总股本": total,
         "已流通股份": listed, "变动原因": reason}
        for effective, announced, total, listed, reason in rows
    ])


class SymbolClassificationTests(unittest.TestCase):
    def test_a_share_codes_map_and_others_do_not(self):
        for symbol, expected in (("601899.SS", "601899"), ("300253.SZ", "300253"),
                                 ("688002.SS", "688002"), ("159934.SZ", "159934"),
                                 ("QQQ", None), ("GOOG", None), ("ABC.SS", None)):
            with self.subTest(symbol=symbol):
                self.assertEqual(dilution.cninfo_code(symbol), expected)

    def test_open_ended_funds_are_not_applicable_not_zero_dilution(self):
        for symbol in ("515650.SS", "159934.SZ", "159072.SZ", "510300.SS"):
            with self.subTest(symbol=symbol):
                kind, reason = dilution.classify(symbol)
                self.assertEqual(kind, "fund")
                self.assertIn("creation_redemption", reason)

    def test_non_a_share_and_overrides(self):
        self.assertEqual(dilution.classify("QQQ")[0], "not_applicable")
        self.assertEqual(dilution.classify("515650.SS", {"515650.SS": "stock"})[0], "stock")
        self.assertEqual(dilution.classify("601899.SS", {"601899.SS": "fund"})[0], "fund")
        with self.assertRaises(dilution.ShareChangeError):
            dilution.parse_class_overrides(["601899.SS=etf"])


class NormalisationTests(unittest.TestCase):
    def test_units_are_converted_to_shares_and_rows_are_sorted(self):
        rows = dilution.normalise_rows(frame([
            ("2026-04-02", "2026-04-03", 220127.2551, 181050.0480, "股份回购"),
            ("2025-10-10", "2025-10-13", 220127.0, None, "可转债转股"),
        ]))
        self.assertEqual([row["effective_date"] for row in rows],
                         ["2025-10-10", "2026-04-02"])
        self.assertAlmostEqual(rows[0]["total_shares"], 220127.0 * 10_000)
        self.assertEqual(rows[0]["listed_shares"], None)

    def test_missing_columns_and_garbage_rows(self):
        with self.assertRaises(dilution.ShareChangeError):
            dilution.normalise_rows(pd.DataFrame([{"变动日期": "2026-01-01"}]))
        with self.assertRaises(dilution.ShareChangeError):
            dilution.normalise_rows(["not a table"])
        rows = dilution.normalise_rows(frame([
            ("2026-01-01", "2026-01-02", "not-a-number", None, "x"),
            ("", "2026-01-02", 100.0, None, "blank date"),
            ("2026-01-03", "2026-01-04", 100.0, 90.0, None),
        ]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], None)


class AssessmentTests(unittest.TestCase):
    def rows(self, *spec):
        return dilution.normalise_rows(frame(list(spec)))

    def test_signed_direction_materiality_and_largest_event(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "期权行权"),
            ("2026-04-02", "2026-04-03", 1500.0, 1400.0, "增发新股上市"),
            ("2026-05-10", "2026-05-11", 1400.0, 1300.0, "股份回购"),
        )
        result = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["direction"], "dilution")
        self.assertAlmostEqual(result["net_change_ratio"], 0.4, places=6)
        self.assertAlmostEqual(result["net_delta_shares"], 400.0 * 10_000, places=6)
        self.assertTrue(result["material_change"])
        self.assertEqual(result["largest_event"]["reason"], "增发新股上市")
        self.assertEqual([event["reason"] for event in result["material_events"]],
                         ["增发新股上市", "股份回购"])
        self.assertIsNone(result["events"][0]["delta_ratio"])  # no baseline before the first row

    def test_buyback_is_accretion(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-04-02", "2026-04-03", 998.0, 900.0, "股份回购"),
        )
        result = dilution.assess("300253.SZ", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertEqual(result["direction"], "accretion")
        self.assertAlmostEqual(result["net_change_ratio"], -0.002, places=6)
        self.assertFalse(result["material_change"])

    def test_threshold_boundary_counts_as_material(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-04-02", "2026-04-03", 1010.0, 900.0, "期权行权"),
        )
        result = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertAlmostEqual(result["events"][1]["delta_ratio"], 0.01, places=6)
        self.assertTrue(result["material_change"])

    def test_announcement_date_governs_visibility_but_not_reporting(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-06-30", "2026-08-26", 1200.0, 900.0, "可转债转股,定期报告"),
        )
        early = dilution.assess("601899.SS", rows, as_of_date="2026-07-01", lookback_days=400,
                                threshold=0.01)
        self.assertEqual(early["row_count"], 1)  # the June row was announced in August
        late = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                               threshold=0.01)
        self.assertEqual(late["row_count"], 2)
        self.assertEqual(late["events"][1]["effective_date"], "2026-06-30")
        self.assertEqual(late["events"][1]["announcement_date"], "2026-08-26")

    def test_window_and_empty_result_fail_closed(self):
        rows = self.rows(("2024-01-05", "2024-01-06", 1000.0, 900.0, "定期报告"))
        result = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["detail_status"], "no_share_change_rows_in_window")
        self.assertIn("no share-change rows", result["errors"][0])

    def test_zero_change_rows_are_kept_as_evidence(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-06-30", "2026-08-22", 1000.0, 900.0, "定期报告"),
        )
        result = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertEqual(result["direction"], "unchanged")
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["material_events"], [])

    def test_assessment_is_deterministic(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-04-02", "2026-04-03", 1500.0, 1400.0, "增发新股上市"),
        )
        first = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                                threshold=0.01)
        second = dilution.assess("601899.SS", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertEqual(first, second)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = dilution.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_argument_validation(self):
        for argv, expected in (
            (["--as-of-date", AS_OF], "at least one --symbol"),
            (["--symbol", "601899.SS", "--as-of-date", "not-a-date"], "Invalid isoformat"),
            (["--symbol", "601899.SS", "--as-of-date", AS_OF, "--lookback-days", "0"],
             "--lookback-days must be positive"),
            (["--symbol", "601899.SS", "--as-of-date", AS_OF, "--threshold", "-0.5"],
             "--threshold must not be negative"),
        ):
            with self.subTest(argv=argv):
                code, payload = self.run_cli(argv)
                self.assertEqual(code, 3)
                self.assertEqual(payload["detail_status"], "share_change_input_invalid")
                self.assertIn(expected, payload["errors"][0])

    def test_channel_failure_is_reported_not_zeroed(self):
        with mock.patch.object(dilution, "fetch_share_changes",
                               side_effect=RuntimeError("channel offline")):
            code, payload = self.run_cli(["--symbol", "601899.SS", "--as-of-date", AS_OF])
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "insufficient_data")
        row = payload["symbols"][0]
        self.assertEqual(row["detail_status"], "share_change_channel_failed")
        self.assertIn("RuntimeError: channel offline", row["errors"][0])

    def test_funds_and_foreign_symbols_need_no_channel_call(self):
        with mock.patch.object(dilution, "fetch_share_changes") as fetch:
            code, payload = self.run_cli(["--symbol", "515650.SS", "--symbol", "QQQ",
                                          "--as-of-date", AS_OF])
        fetch.assert_not_called()
        self.assertEqual(code, 2)  # nothing assessed -> not a complete run
        self.assertEqual(payload["status"], "insufficient_data")
        kinds = {row["symbol"]: (row["status"], row["detail_status"])
                 for row in payload["symbols"]}
        self.assertEqual(kinds["515650.SS"][0], "not_applicable")
        self.assertEqual(kinds["QQQ"][1], "not_an_a_share_issuer")

    def test_out_writes_the_payload_and_reports_partial_coverage(self):
        payload_frame = frame([
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-04-02", "2026-04-03", 1500.0, 1400.0, "增发新股上市"),
        ])
        target = self.root / "out" / "share_change.json"

        def fake_fetch(code, *, start_date, end_date):
            if code == "300253":
                raise RuntimeError("throttled")
            return payload_frame

        with mock.patch.object(dilution, "fetch_share_changes", side_effect=fake_fetch):
            code, payload = self.run_cli(["--symbol", "601899.SS", "--symbol", "300253.SZ",
                                          "--symbol", "159934.SZ", "--as-of-date", AS_OF,
                                          "--out", str(target)])
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "incomplete")
        self.assertEqual(payload["detail_status"], "share_change_partially_assessed")
        self.assertEqual(payload["errors"], ["300253.SZ: share-change assessment unavailable"])
        written = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "incomplete")
        assessed = next(row for row in payload["symbols"] if row["symbol"] == "601899.SS")
        self.assertEqual(assessed["cninfo_code"], "601899")
        self.assertIn("announcement_date", payload["data_basis"]["as_of_basis"])


class EventNatureTests(unittest.TestCase):
    """A bonus issue moves the share count, not per-share economics."""

    def rows(self, *spec):
        return dilution.normalise_rows(frame(list(spec)))

    def test_bonus_issue_is_mechanical_and_excluded_from_economic_change(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-06-11", "2026-06-12", 1400.0, 1400.0, "转增"),
        )
        result = dilution.assess("300502.SZ", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertAlmostEqual(result["net_change_ratio"], 0.40, places=6)
        self.assertAlmostEqual(result["economic_change_ratio"], 0.0, places=6)
        self.assertEqual(result["direction"], "dilution")
        self.assertEqual(result["economic_direction"], "unchanged")
        self.assertFalse(result["material_change"])
        self.assertTrue(result["events"][1]["mechanical"])
        self.assertEqual(result["events"][1]["nature"], "share_split_equivalent")
        self.assertIn("转增/送股", result["notes"])

    def test_issuance_beats_other_keywords_and_is_material(self):
        self.assertEqual(dilution.classify_event("增发新股上市,可转债转股,股权激励", 100.0),
                         "capital_issuance")
        self.assertEqual(dilution.classify_event("可转债转股,股份回购", -100.0),
                         "buyback_or_cancellation")
        self.assertEqual(dilution.classify_event("可转债转股,定期报告", 100.0),
                         "conversion_or_exercise")
        self.assertEqual(dilution.classify_event("定期报告", 0.0), "restatement_no_change")
        self.assertEqual(dilution.classify_event("转增", -500.0), "other_share_count_change")
        self.assertEqual(dilution.classify_event(None, 100.0), "other_share_count_change")

    def test_mixed_bonus_and_issuance_economic_ratio_keeps_only_the_issuance(self):
        rows = self.rows(
            ("2025-10-01", "2025-10-02", 1000.0, 900.0, "定期报告"),
            ("2026-03-01", "2026-03-02", 2000.0, 2000.0, "转增"),
            ("2026-06-01", "2026-06-02", 2100.0, 2100.0, "增发新股上市"),
        )
        result = dilution.assess("300502.SZ", rows, as_of_date=AS_OF, lookback_days=400,
                                 threshold=0.01)
        self.assertAlmostEqual(result["net_change_ratio"], 1.10, places=6)
        # 1000 -> 2000 is mechanical; the 100 issued on top of 2000 is real dilution
        self.assertAlmostEqual(result["economic_change_ratio"], 0.10, places=6)
        self.assertEqual(result["largest_economic_event"]["reason"], "增发新股上市")
        self.assertEqual([event["nature"] for event in result["material_events"]],
                         ["capital_issuance"])



if __name__ == "__main__":
    unittest.main()
