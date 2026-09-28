"""Contract tests for the verified market holiday calendar and its wiring (P0-7).

Two failure modes are covered: a shared regex over two different official documents
produced a silently incomplete table (the Spring Festival collapsed to one day), and
a long holiday makes a healthy run fail closed against a fixed 72-hour CLOSED ceiling.
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

import market_calendar  # noqa: E402
import yf  # noqa: E402
import daily_sync  # noqa: E402
from portfolio_loader import load_positions  # noqa: E402
from quote_evidence_contract import build_portfolio_snapshot_binding, quote_freshness_policy  # noqa: E402

CN_FIXTURE = """
<p>国办发明电〔2025〕7号 经国务院批准，现将2026年元旦、春节、清明节、劳动节、端午节、
中秋节和国庆节放假调休日期的具体安排通知如下。</p>
<p>一、元旦：1月1日（周四）至3日（周六）放假调休，共3天。1月4日（周日）上班。</p>
<p>二、春节：2月15日（农历腊月二十八、周日）至23日（农历正月初七、周一）放假调休，共9天。
2月14日（周六）、2月28日（周六）上班。</p>
<p>三、清明节：4月4日（周六）至4月6日（周一）放假，共3天。</p>
<p>四、劳动节：5月1日（周五）至5日（周二）放假调休，共5天。</p>
<p>五、端午节：6月19日（周五）至6月21日（周日）放假，共3天。</p>
<p>六、中秋节：9月25日（周五）至9月27日（周日）放假，共3天。</p>
<p>七、国庆节：10月1日（周四）至10月7日（周三）放假调休，共7天。</p>
"""

US_FIXTURE = """
<table>
<tr><th>Holiday</th><th>2026</th><th>2027</th></tr>
<tr><td>New Year's Day</td><td>Thursday, January 1</td><td>Friday, January 1</td></tr>
<tr><td>Martin Luther King, Jr. Day</td><td>Monday, January 19</td><td>Monday, January 18</td></tr>
<tr><td>Washington's Birthday</td><td>Monday, February 16</td><td>Monday, February 15</td></tr>
<tr><td>Good Friday</td><td>Friday, April 3</td><td>Friday, March 26</td></tr>
<tr><td>Memorial Day</td><td>Monday, May 25</td><td>Monday, May 31</td></tr>
<tr><td>Juneteenth National Independence Day</td><td>Friday, June 19</td><td>Friday, June 18</td></tr>
<tr><td>Independence Day</td><td>Friday, July 3</td><td>Monday, July 5</td></tr>
<tr><td>Labor Day</td><td>Monday, September 7</td><td>Monday, September 6</td></tr>
<tr><td>Thanksgiving Day</td><td>Thursday, November 26</td><td>Thursday, November 25</td></tr>
<tr><td>Christmas Day</td><td>Friday, December 25</td><td>&mdash;</td></tr>
</table>
"""


class CnParserTests(unittest.TestCase):
    def test_chinese_numeral_inside_a_section_does_not_split_it(self):
        parsed = market_calendar.parse_cn_notice(CN_FIXTURE)
        self.assertEqual(parsed["year"], 2026)
        self.assertEqual(len(parsed["holidays"]), 7)
        self.assertEqual(len(parsed["holidays"]["春节"]["days"]), 9)
        self.assertEqual(parsed["total_days"], 33)

    def test_missing_section_is_rejected(self):
        broken = CN_FIXTURE.replace("六、中秋节：9月25日（周五）至9月27日（周日）放假，共3天。", "")
        with self.assertRaises(market_calendar.CalendarError) as ctx:
            market_calendar.parse_cn_notice(broken)
        self.assertIn("中秋节", str(ctx.exception))

    def test_declared_day_count_mismatch_is_rejected(self):
        broken = CN_FIXTURE.replace("共9天", "共8天")
        with self.assertRaises(market_calendar.CalendarError) as ctx:
            market_calendar.parse_cn_notice(broken)
        self.assertIn("共8天", str(ctx.exception))

    def test_missing_declared_count_is_rejected(self):
        broken = CN_FIXTURE.replace("放假调休，共9天。", "放假调休。")
        with self.assertRaises(market_calendar.CalendarError) as ctx:
            market_calendar.parse_cn_notice(broken)
        self.assertIn("does not declare", str(ctx.exception))


class UsParserTests(unittest.TestCase):
    def test_three_column_table_parses_both_years(self):
        parsed = market_calendar.parse_nyse_table(US_FIXTURE)
        self.assertEqual(parsed["years"], [2026, 2027])
        self.assertEqual(len(parsed["closures"]["2026"]), 10)
        self.assertEqual(len(parsed["closures"]["2027"]), 9)  # Christmas Day is a dash
        self.assertNotIn("2027-12-25", parsed["closures"]["2027"])

    def test_missing_row_label_is_rejected(self):
        broken = US_FIXTURE.replace("Good Friday", "Some Other Day")
        with self.assertRaises(market_calendar.CalendarError) as ctx:
            market_calendar.parse_nyse_table(broken)
        self.assertIn("Good Friday", str(ctx.exception))


class ShippedTableTests(unittest.TestCase):
    def setUp(self):
        self.table = market_calendar.load_table(market_calendar.SKILL_HOLIDAY_TABLE
                                                if hasattr(market_calendar, "SKILL_HOLIDAY_TABLE")
                                                else Path(SCRIPT_DIR).parent
                                                / "references" / "market_holidays.json")

    def test_shipped_table_covers_the_observed_holiday(self):
        cn = market_calendar.holiday_dates(self.table, "CN", 2026)
        self.assertEqual(len(cn), 33)
        for day in ("2026-09-25", "2026-09-26", "2026-09-27", "2026-02-15", "2026-02-23"):
            self.assertIn(datetime.date.fromisoformat(day), cn)
        self.assertEqual(len(market_calendar.holiday_dates(self.table, "US", 2026)), 10)

    def test_sources_carry_locators_and_hashes(self):
        for source in self.table["sources"]:
            self.assertTrue(source["locator"].startswith("https://"))
            self.assertRegex(source["content_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(source["retrieved_at"])

    def test_closed_days_between_counts_the_holiday_gap(self):
        count, days = market_calendar.closed_days_between(
            self.table, "CN", datetime.date(2026, 9, 24), datetime.date(2026, 9, 28))
        self.assertEqual(count, 3)
        self.assertEqual(days, ["2026-09-25", "2026-09-26", "2026-09-27"])

    def test_unknown_year_is_refused(self):
        with self.assertRaises(market_calendar.CalendarError):
            market_calendar.holiday_dates(self.table, "CN", 2035)


class FreshnessWiringTests(unittest.TestCase):
    def test_zero_extension_reproduces_the_original_policy(self):
        base = quote_freshness_policy("CLOSED", upper_bound_cap_seconds=259200)
        self.assertFalse(base["calendar_aware"])
        self.assertEqual(base["applied_max_age_seconds"], 259200)
        self.assertEqual(base["long_holiday_behavior"], "fail_closed_after_state_threshold")

    def test_extension_widens_the_ceiling_and_records_the_basis(self):
        widened = quote_freshness_policy("CLOSED", upper_bound_cap_seconds=259200,
                                         holiday_extension_seconds=172800)
        self.assertTrue(widened["calendar_aware"])
        self.assertEqual(widened["holiday_extension_seconds"], 172800)
        self.assertEqual(widened["applied_max_age_seconds"], 259200 + 172800)
        self.assertEqual(widened["extension_basis"], "verified_exchange_closures")
        self.assertEqual(widened["long_holiday_behavior"],
                         "fail_closed_after_state_threshold_plus_verified_closures")

    def _table(self) -> dict:
        return market_calendar.load_table(Path(SCRIPT_DIR).parent / "references"
                                          / "market_holidays.json")

    def _report(self, *, age_days: float, table, day: int = 28) -> dict:
        now = datetime.datetime(2026, 9, day, 8, 0, tzinfo=datetime.timezone.utc).timestamp()
        quote_time = now - age_days * 86400
        result = {"symbol": "601899.SS",
                  "info": {"quoteType": "EQUITY", "currency": "CNY", "exchange": "SHH",
                           "exchangeTimezoneName": "Asia/Shanghai", "marketState": "CLOSED",
                           "regularMarketTime": quote_time, "symbol": "601899.SS",
                           "currentPrice": 30.01, "regularMarketPrice": 30.01}}
        position = {"symbol": "601899.SS", "market": "CN", "asset_type": "stock",
                    "currency": "CNY"}
        return yf._quote_contract_report(result, position, now_epoch=now,
                                        max_quote_age_seconds=259200, holiday_table=table)

    def test_official_sse_capture_restores_only_sse_holiday_freshness(self):
        source = Path(SCRIPT_DIR).parent / "references" / "official_sources" / "sse_2026_holidays.html"
        raw = source.read_bytes()
        table = market_calendar.augment_sse_table(
            self._table(), raw,
            locator="https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml",
            retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        self.assertEqual(table["sources"][-1]["content_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(table["markets"]["SSE"]["2026"]), 33)
        result = self._report(age_days=3.2, table=table, day=27)
        self.assertEqual(result["status"], "matched", result["errors"])
        after_open = self._report(age_days=4.0, table=table, day=28)
        self.assertEqual(after_open["status"], "failed")
        self.assertEqual(after_open["holiday_extension"]["reason"], "intervening_open_day")
        self.assertEqual(result["holiday_extension"]["calendar_market"], "SSE")
        sz = {"symbol": "000001.SZ", "market": "CN", "asset_type": "stock", "currency": "CNY"}
        sh_info = {"exchangeTimezoneName": "Asia/Shanghai", "exchange": "SZSE", "regularMarketTime": datetime.datetime(2026, 9, 24, tzinfo=datetime.timezone.utc).timestamp()}
        denial, seconds = yf._holiday_extension(table, sz, sh_info, datetime.datetime(2026, 9, 28, tzinfo=datetime.timezone.utc).timestamp())
        self.assertEqual(seconds, 0)
        self.assertEqual(denial["reason"], "cn_exchange_closure_source_unverified")

    def test_offline_replay_recomputes_holiday_extension_not_provider_claim(self):
        root = Path(SCRIPT_DIR).parent / "references"
        calendar_file = root / "market_holidays_sse_szse_2026.json"
        table = market_calendar.load_table(calendar_file)
        now = datetime.datetime(2026, 9, 27, 8, tzinfo=datetime.timezone.utc).timestamp()
        symbol = "601899.SS"
        portfolio = {"base_currency": "CNY", "positions": [{"symbol": symbol, "quantity": 1, "avg_cost": 10, "currency": "CNY", "market": "CN", "asset_type": "stock"}]}
        record = {"query": symbol, "symbol": symbol, "summary": {"last_close": 30.01},
                  "info": {"symbol": symbol, "quoteType": "EQUITY", "currency": "CNY", "exchange": "SHH", "exchangeTimezoneName": "Asia/Shanghai", "marketState": "CLOSED", "regularMarketTime": now - 3.2 * 86400, "regularMarketPrice": 30.01, "currentPrice": 30.01},
                  "data_sources": {"price": "Yahoo Finance", "price_locator": f"yfinance:{symbol}:quote"},
                  "portfolio_context": {"position_status": "matched", "current_price": 30.01, "currency": "CNY"}}
        with tempfile.TemporaryDirectory() as temp:
            positions = Path(temp) / "positions.json"
            quotes = Path(temp) / "quotes.json"
            positions.write_text(json.dumps(portfolio), encoding="utf-8")
            loaded = load_positions(str(positions))
            audit = yf.build_portfolio_batch_audit([record], requested_count=1, expected_symbols=[symbol], portfolio_load_status=loaded.get("_status"), expected_position_metadata=yf._expected_position_metadata(loaded), now_epoch=now, portfolio_snapshot_binding=build_portfolio_snapshot_binding(loaded), holiday_table=table)
            self.assertTrue(audit["complete"], audit)
            quotes.write_text(json.dumps({"records": [record], "portfolio_batch_audit": audit}), encoding="utf-8")
            without = daily_sync.evaluate_daily_sync(positions_file=str(positions), quotes_file=str(quotes), now_epoch=now)
            self.assertFalse(without["completeness"]["identity_complete"])
            with_calendar = daily_sync.evaluate_daily_sync(positions_file=str(positions), quotes_file=str(quotes), now_epoch=now, holiday_calendar_file=str(calendar_file))
            self.assertTrue(with_calendar["completeness"]["identity_complete"], with_calendar["errors"])
            self.assertTrue(with_calendar["completeness"]["recomputed_audit_complete"])
            self.assertFalse(with_calendar["completeness"]["thesis_assessment_complete"])
            invalid = daily_sync.evaluate_daily_sync(positions_file=str(positions), quotes_file=str(quotes), now_epoch=now, holiday_calendar_file=str(Path(temp) / "missing.json"))
            self.assertEqual(invalid["status"], "invalid_input")
            self.assertIn("holiday_calendar_source_invalid", invalid["errors"][0])

    def test_shipped_sse_table_is_bound_to_captured_official_bytes(self):
        root = Path(SCRIPT_DIR).parent / "references"
        table = market_calendar.load_table(root / "market_holidays_sse_2026.json")
        raw = (root / "official_sources" / "sse_2026_holidays.html").read_bytes()
        self.assertEqual(table["sources"][-1]["content_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(table["markets"]["SSE"]["2026"], self._table()["markets"]["CN"]["2026"])

    def test_official_szse_capture_restores_only_szse_freshness(self):
        root = Path(SCRIPT_DIR).parent / "references"
        table = market_calendar.load_table(root / "market_holidays_sse_szse_2026.json")
        raw = (root / "official_sources" / "szse_2026_holidays.html").read_bytes()
        self.assertEqual(table["sources"][-1]["content_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(table["markets"]["SZSE"]["2026"]), 33)
        position = {"symbol": "000001.SZ", "market": "CN", "asset_type": "stock", "currency": "CNY"}
        now = datetime.datetime(2026, 9, 27, 8, tzinfo=datetime.timezone.utc).timestamp()
        info = {"exchange": "SHZ", "exchangeTimezoneName": "Asia/Shanghai", "regularMarketTime": now - 3.2 * 86400}
        applied, seconds = yf._holiday_extension(table, position, info, now)
        self.assertGreaterEqual(seconds, 2 * 86400)
        self.assertEqual(applied["calendar_market"], "SZSE")
        with self.assertRaises(market_calendar.CalendarError):
            market_calendar.augment_cn_exchange_table(self._table(), raw.replace("中秋节".encode(), b""), exchange="SZSE", locator="https://www.szse.cn/disclosure/notice/t20251222_618087.html", retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat())

    def test_loaded_exchange_table_revalidates_capture_and_dates(self):
        root = Path(SCRIPT_DIR).parent / "references"
        table = market_calendar.load_table(root / "market_holidays_sse_szse_2026.json")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "table.json"
            table["markets"]["SZSE"]["2026"].remove("2026-09-25")
            path.write_text(json.dumps(table), encoding="utf-8")
            with self.assertRaises(market_calendar.CalendarError):
                market_calendar.load_table(path)
            table["markets"]["SZSE"]["2026"].append("2026-09-25")
            table["sources"][-1]["content_sha256"] = "0" * 64
            path.write_text(json.dumps(table), encoding="utf-8")
            with self.assertRaises(market_calendar.CalendarError):
                market_calendar.load_table(path)

    def test_sse_malformed_notice_and_conflicting_government_dates_fail_closed(self):
        raw = (Path(SCRIPT_DIR).parent / "references" / "official_sources" / "sse_2026_holidays.html").read_bytes()
        kwargs = {"locator": "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml", "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        for broken in (raw.replace("（六）中秋节".encode(), b""), raw.replace("9月28日".encode(), "9月24日".encode())):
            with self.assertRaises(market_calendar.CalendarError):
                market_calendar.augment_sse_table(self._table(), broken, **kwargs)
        baseline = self._table()
        baseline["markets"]["CN"]["2026"].remove("2026-09-25")
        with self.assertRaises(market_calendar.CalendarError):
            market_calendar.augment_sse_table(baseline, raw, **kwargs)

    def test_cn_government_calendar_does_not_assert_exchange_quote_freshness(self):
        without = self._report(age_days=4.0, table=None)
        self.assertEqual(without["status"], "failed")
        self.assertIn("stale_info.regularMarketTime", without["errors"])

        with_calendar = self._report(age_days=4.0, table=self._table())
        self.assertEqual(with_calendar["status"], "failed")
        self.assertIn("stale_info.regularMarketTime", with_calendar["errors"])
        self.assertEqual(with_calendar["holiday_extension"]["reason"], "cn_exchange_closure_source_unverified")
        self.assertFalse(with_calendar["freshness_policy"]["calendar_aware"])

    def test_uncovered_market_is_reported_not_silently_widened(self):
        now = datetime.datetime(2026, 9, 28, 8, 0, tzinfo=datetime.timezone.utc).timestamp()
        result = {"symbol": "XYZ", "info": {"quoteType": "EQUITY", "currency": "HKD",
                                            "exchange": "HKG", "marketState": "CLOSED",
                                            "exchangeTimezoneName": "Asia/Hong_Kong",
                                            "currentPrice": 10.0, "regularMarketPrice": 10.0,
                                            "regularMarketTime": now - 4 * 86400}}
        position = {"symbol": "XYZ", "market": "HK", "asset_type": "stock",
                    "currency": "HKD"}
        report = yf._quote_contract_report(result, position, now_epoch=now,
                                          max_quote_age_seconds=259200,
                                          holiday_table=self._table())
        self.assertFalse(report["holiday_extension"]["applied"])
        self.assertEqual(report["holiday_extension"]["reason"], "market_not_covered")
        self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
