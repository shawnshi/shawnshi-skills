"""基金净值观测点台账的合约测试（合成 HTML，不联网）。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import fund_nav_ledger as ledger  # noqa: E402

SSR_OK = (
    '<div class="item"><p>单位净值(2026-09-30)</p><div class="num ared">'
    '<strong>1.0457</strong></div></div><div class="item"><p>累计净值</p>'
    '<div class="num ared"><strong>1.0457</strong></div></div>'
)
SSR_NOT_FOUND = '<div class="error_box_404" catalogno="404">您访问的页面不见了</div>'
SSR_JS_ONLY = '<div id="app"></div><script src="/ws6/entry.js"></script>'


class FundNavLedgerTest(unittest.TestCase):
    def test_parses_server_rendered_nav(self):
        point = ledger.parse_nav_points(SSR_OK)
        self.assertEqual(point["nav_date"], "2026-09-30")
        self.assertAlmostEqual(point["unit_nav"], 1.0457)
        self.assertAlmostEqual(point["cumulative_nav"], 1.0457)

    def test_not_found_shell_fails_closed(self):
        with self.assertRaises(ledger.NavLedgerError) as ctx:
            ledger.parse_nav_points(SSR_NOT_FOUND)
        self.assertEqual(ctx.exception.code, "page_not_found")

    def test_js_only_shell_fails_closed(self):
        with self.assertRaises(ledger.NavLedgerError) as ctx:
            ledger.parse_nav_points(SSR_JS_ONLY)
        self.assertEqual(ctx.exception.code, "nav_not_rendered")

    def test_append_is_idempotent_and_series_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            older = ledger.build_point("515650", "fullgoal", SSR_OK, source_locator="https://x/1")
            newer_src = SSR_OK.replace("2026-09-30", "2026-10-08").replace("1.0457", "1.0612")
            newer = ledger.build_point("515650", "fullgoal", newer_src, source_locator="https://x/2")
            self.assertTrue(ledger.append_point(path, newer))
            self.assertTrue(ledger.append_point(path, older))
            self.assertFalse(ledger.append_point(path, newer))
            rows = ledger.series(path, "515650")
            self.assertEqual([r["nav_date"] for r in rows], ["2026-09-30", "2026-10-08"])
            self.assertEqual(len(path.read_text(encoding="utf-8").strip().splitlines()), 2)
            self.assertEqual(ledger.series(path, "510050"), [])

    def test_requires_network_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            code = ledger.main(["--code", "515650", "--ledger", str(path)])
            self.assertEqual(code, 3)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
