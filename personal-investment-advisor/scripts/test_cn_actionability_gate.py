import copy
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from cn_actionability_gate import VERSION, evaluate


class ActionabilityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.data = {
            "schema_version": VERSION, "instrument": {"symbol": "600000.SS", "market": "CN", "asset_type": "stock", "currency": "CNY", "exchange": "SSE"},
            "quote": {"symbol": "600000.SS", "market_state": "REGULAR", "price_cny": 10, "volume_shares": 1000000, "as_of": (self.now - timedelta(seconds=30)).isoformat(), "retrieved_at": (self.now - timedelta(seconds=10)).isoformat(), "source_locator": "https://www.sse.com.cn/synthetic-quote", "content_sha256": "b" * 64},
            "rules": {"symbol": "600000.SS", "exchange": "SSE", "source_locator": "https://www.sse.com.cn/synthetic-rule", "content_sha256": "a" * 64, "retrieved_at": (self.now - timedelta(hours=1)).isoformat(), "trading_date": "2026-09-23", "trading_allowed": True, "lower_limit_cny": 9, "upper_limit_cny": 11, "minimum_buy_lot": 100, "buy_increment": 100},
            "terms": {"side": "buy", "quantity": 200, "price_cny": 10}, "available_cash_cny": 3000, "available_sell_quantity": 0, "max_volume_participation": 0.01,
            "cost_bps": {"commission": 3, "spread": 5, "impact": 7, "sell_tax": 10},
        }

    def test_buy_and_sell_feasible_not_order(self):
        result = evaluate(self.data, now=self.now)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["actionability"], "human_review_required_no_order")
        self.data["terms"] = {"side": "sell", "quantity": 150, "price_cny": 10}
        self.data["available_sell_quantity"] = 150
        self.assertEqual(evaluate(self.data, now=self.now)["estimated_cost_bps"], 25)

    def test_suspension_stale_and_mismatched_identity_fail(self):
        self.data["rules"]["trading_allowed"] = False
        self.assertNotEqual(evaluate(self.data, now=self.now)["status"], "complete")
        self.data["rules"]["trading_allowed"] = True
        self.data["quote"]["as_of"] = (self.now - timedelta(hours=2)).isoformat()
        self.assertNotEqual(evaluate(self.data, now=self.now)["status"], "complete")
        self.data["quote"]["as_of"] = (self.now - timedelta(seconds=30)).isoformat()
        self.data["quote"]["symbol"] = "000001.SZ"
        self.assertNotEqual(evaluate(self.data, now=self.now)["status"], "complete")

    def test_lot_limit_cash_liquidity_and_t1_fail(self):
        for section, field, bad in (("terms", "quantity", 101), ("terms", "price_cny", 12), ("available_cash_cny", None, 1), ("max_volume_participation", None, 0.0001)):
            candidate = copy.deepcopy(self.data)
            if field is None:
                candidate[section] = bad
            else:
                candidate[section][field] = bad
            self.assertNotEqual(evaluate(candidate, now=self.now)["status"], "complete")
        self.data["terms"]["side"] = "sell"
        self.assertNotEqual(evaluate(self.data, now=self.now)["status"], "complete")

    def test_malformed_nested_identity_returns_failure_not_exception(self):
        self.data["instrument"] = {}
        self.assertEqual(evaluate(self.data, now=self.now)["status"], "invalid_input")

    def test_official_closed_day_is_explicitly_not_actionable(self):
        calendar = HERE.parent / "references" / "market_holidays_sse_szse_2026.json"
        sunday = datetime(2026, 9, 27, 21, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
        assessment = {"schema_version": VERSION, "instrument": self.data["instrument"]}
        closed = evaluate(assessment, now=sunday, holiday_calendar_file=calendar)
        self.assertEqual(closed["status"], "market_closed", closed)
        self.assertEqual(closed["actionability"], "not_actionable")
        open_day = evaluate(assessment, now=datetime(2026, 9, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")), holiday_calendar_file=calendar)
        self.assertNotEqual(open_day["status"], "complete")
        government_only = HERE.parent / "references" / "market_holidays.json"
        self.assertEqual(evaluate(assessment, now=sunday, holiday_calendar_file=government_only)["status"], "invalid_input")

    def test_missing_rules_and_sunday_fail(self):
        self.data["rules"].pop("buy_increment")
        self.assertNotEqual(evaluate(self.data, now=self.now)["status"], "complete")
        self.data["rules"]["buy_increment"] = 100
        sunday = datetime(2026, 9, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertNotEqual(evaluate(self.data, now=sunday)["status"], "complete")


if __name__ == "__main__":
    unittest.main()
