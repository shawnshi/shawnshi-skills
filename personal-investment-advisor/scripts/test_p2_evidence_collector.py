"""Contract tests for the automated evidence collector (``pia_evidence.py``).

These tests run fully offline: the channel adapters are stubbed, so what is under
test is the collector's own contract — routing, artifact hashing, refusal to emit
unverified symbols, and the completeness accounting that feeds the Thesis gate.
"""
from __future__ import annotations

import contextlib
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

import evidence_channels as ec  # noqa: E402
import pia_evidence  # noqa: E402

WINDOW_START = "2026-09-19T00:00:00+08:00"
WINDOW_END = "2026-09-29T21:20:00+08:00"


def listing(channel: str, records: list[dict], *, url: str, body: bytes,
            fetched_at: float, health: str = ec.HEALTH_OK, reused: bool = False) -> dict:
    return {"channel": channel, "health": health, "records": records,
            "meta": {"url": url, "body": body, "fetched_at": fetched_at, "reused": reused,
                     "cache_age_seconds": 12.0 if reused else 0.0}}


def record(title: str, published_at: str, document_url: str | None = None,
           form: str | None = None) -> dict:
    row = {"title": title, "published_at": published_at, "document_url": document_url}
    if form is not None:
        row["form"] = form
    return row
    return {"title": title, "published_at": published_at, "document_url": document_url}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task = Path(self._tmp.name)
        self.fetcher = ec.ChannelFetcher(session=mock.Mock(), cache_dir=self.task / "cache",
                                         clock=lambda: 1_800_000_000.0)

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_evidence.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_verified_symbol_and_scopes_produce_a_complete_collection(self):
        cninfo = listing("cninfo_fulltext",
                         [record("大金重工：注销募集资金专户的公告", "2026-09-22T00:00:00+08:00",
                                 "http://static.cninfo.com.cn/finalpage/2026-09-22/a.PDF")],
                         url="http://www.cninfo.com.cn/new/fulltextSearch/full?x",
                         body=b"{\"totalAnnouncement\":1}", fetched_at=1_799_000_000.0)
        document = {"health": ec.HEALTH_OK, "content_sha256": ec.sha256_bytes(b"%PDF-1.4 official"),
                    "bytes": 15, "content_type": "application/pdf",
                    "meta": {"url": "http://static.cninfo.com.cn/finalpage/2026-09-22/a.PDF",
                             "body": b"%PDF-1.4 official", "fetched_at": 1_799_000_050.0,
                             "http_status": 200, "reused": False}}
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext", return_value=cninfo), \
             mock.patch.object(pia_evidence.ec, "fetch_document", return_value=document):
            code, payload = self.run_main([
                "--task-dir", str(self.task), "--symbols", "002487.SZ",
                "--window-start", WINDOW_START, "--window-end", WINDOW_END,
                "--scope-source", "macro=https://www.stats.gov.cn/x.html@2026-09-28T00:00:00+08:00",
                "--scope-source", "sector=https://www.miit.gov.cn/y.html@2026-09-21T00:00:00+08:00",
                "--scope-source", "regulatory=http://www.pbc.gov.cn/z.html@2026-09-24T00:00:00+08:00",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["symbols_verified"], ["002487.SZ"])
        items = json.loads((self.task / "evidence/evidence_items.json").read_text(encoding="utf-8"))
        self.assertEqual(len(items["evidence_items"]), 4)
        holding = items["evidence_items"][0]
        self.assertEqual(holding["evidence_id"], "ev_cninfo_fulltext_002487_SZ")
        self.assertEqual(holding["source_tier"], "exchange")
        self.assertEqual(holding["content_sha256"], ec.sha256_bytes(b"%PDF-1.4 official"))
        self.assertEqual(holding["published_at"], "2026-09-22T00:00:00+08:00")
        self.assertIn("大金重工", holding["claim"])
        self.assertTrue(Path(holding["artifact"]).is_file())
        self.assertEqual(sorted(row["scope"] for row in payload["scope_sources"]),
                         ["macro", "regulatory", "sector"])
        self.assertEqual(payload["evidence_count"], 4)

    def test_broken_channel_is_reported_and_no_item_is_emitted(self):
        broken = listing("cninfo_fulltext", [], url="http://www.cninfo.com.cn/query",
                         body=b'{"announcements":null,"totalAnnouncement":0}',
                         fetched_at=1_799_000_000.0, health=ec.HEALTH_BROKEN)
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext", return_value=broken), \
             mock.patch.object(pia_evidence.ec, "szse_announcements",
                               return_value=listing("szse_announcements", [],
                                                    url="http://www.szse.cn/api",
                                                    body=b"{}", fetched_at=1_799_000_000.0,
                                                    health=ec.HEALTH_BROKEN)):
            code, payload = self.run_main([
                "--task-dir", str(self.task), "--symbols", "002487.SZ",
                "--window-start", WINDOW_START, "--window-end", WINDOW_END])
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "incomplete")
        self.assertEqual(payload["detail_status"], "evidence_incomplete")
        report = payload["channel_results"][0]
        self.assertEqual(report["health"], ec.HEALTH_BROKEN)
        self.assertEqual(report["reason"], "channel_broken")
        items = json.loads((self.task / "evidence/evidence_items.json").read_text(encoding="utf-8"))
        self.assertEqual(items["evidence_items"], [])
        self.assertIn("002487.SZ:channel_broken", payload["unverified"])
        self.assertIn("cninfo_announcement_query", payload["known_broken_channels"])

    def test_empty_window_is_distinguishable_from_a_broken_channel(self):
        empty = listing("cninfo_fulltext", [], url="http://www.cninfo.com.cn/query",
                        body=b'{"announcements":[],"totalAnnouncement":0}',
                        fetched_at=1_799_000_000.0, health=ec.HEALTH_EMPTY)
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext", return_value=empty), \
             mock.patch.object(pia_evidence.ec, "szse_announcements", return_value=empty):
            code, payload = self.run_main([
                "--task-dir", str(self.task), "--symbols", "002487.SZ",
                "--window-start", WINDOW_START, "--window-end", WINDOW_END])
        self.assertEqual(code, 1)
        self.assertEqual(payload["channel_results"][0]["reason"], "no_announcement_in_window")
        self.assertEqual(payload["channel_results"][0]["health"], ec.HEALTH_EMPTY)

    def test_declared_scopes_are_required_for_completeness(self):
        cninfo = listing("cninfo_fulltext",
                         [record("卫宁健康：回购股份进展公告", "2026-09-21T16:22:10+08:00",
                                 "http://static.cninfo.com.cn/finalpage/a.PDF")],
                         url="http://www.cninfo.com.cn/query", body=b"{}",
                         fetched_at=1_799_000_000.0)
        document = {"health": ec.HEALTH_OK, "content_sha256": ec.sha256_bytes(b"pdf"),
                    "bytes": 3, "content_type": "application/pdf",
                    "meta": {"url": "http://static.cninfo.com.cn/finalpage/a.PDF",
                             "body": b"pdf", "fetched_at": 1_799_000_000.0,
                             "http_status": 200, "reused": False}}
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext", return_value=cninfo), \
             mock.patch.object(pia_evidence.ec, "fetch_document", return_value=document):
            code, payload = self.run_main([
                "--task-dir", str(self.task), "--symbols", "300253.SZ",
                "--window-start", WINDOW_START, "--window-end", WINDOW_END,
                "--scope-source", "macro=https://www.stats.gov.cn/x.html@2026-09-28T00:00:00+08:00",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(payload["missing_scopes"], ["regulatory", "sector"])
        self.assertIn("missing_scopes:regulatory,sector", payload["errors"])

    def test_us_symbols_use_sec_and_ignore_ownership_forms(self):
        lookup = {"health": ec.HEALTH_OK, "cik": "0001652044", "meta": {"url": "sec", "body": b"{}",
                                                                       "fetched_at": 1_799_000_000.0}}
        submissions = listing("sec_edgar", [
            record("4 (2026-09-16)", "2026-09-16T20:00:00Z", "https://www.sec.gov/Archives/x.htm",
                   form="4"),
            record("8-K (2026-09-25)", "2026-09-25T20:10:48Z",
                   "https://www.sec.gov/Archives/edgar/data/1652044/000119312526342390/d8k.htm",
                   form="8-K"),
        ], url="https://data.sec.gov/submissions/CIK0001652044.json", body=b"{}",
            fetched_at=1_799_000_000.0)
        document = {"health": ec.HEALTH_OK, "content_sha256": ec.sha256_bytes(b"<html>8-K</html>"),
                    "bytes": 17, "content_type": "text/html",
                    "meta": {"url": "https://www.sec.gov/Archives/edgar/data/1652044/"
                                    "000119312526342390/d8k.htm",
                             "body": b"<html>8-K</html>", "fetched_at": 1_799_000_100.0,
                             "http_status": 200, "reused": False}}
        with mock.patch.object(pia_evidence.ec, "sec_ticker_cik", return_value=lookup), \
             mock.patch.object(pia_evidence.ec, "sec_submissions", return_value=submissions), \
             mock.patch.object(pia_evidence.ec, "fetch_document", return_value=document):
            code, payload = self.run_main([
                "--task-dir", str(self.task), "--symbols", "GOOG",
                "--window-start", WINDOW_START, "--window-end", WINDOW_END,
                "--scope-source", "macro=https://www.stats.gov.cn/x.html@2026-09-28T00:00:00+08:00",
                "--scope-source", "sector=https://www.miit.gov.cn/y.html@2026-09-21T00:00:00+08:00",
                "--scope-source", "regulatory=http://www.pbc.gov.cn/z.html@2026-09-24T00:00:00+08:00",
            ])
        self.assertEqual(code, 0)
        report = payload["channel_results"][0]
        self.assertEqual(report["chosen"]["form"], "8-K")
        self.assertEqual(report["chosen"]["published_at"], "2026-09-25T20:10:48Z")
        self.assertEqual(report["tier"], "regulator")
        items = json.loads((self.task / "evidence/evidence_items.json").read_text(encoding="utf-8"))
        self.assertEqual(items["evidence_items"][0]["evidence_id"], "ev_sec_edgar_GOOG")

    def test_cached_listing_payload_is_the_documented_fallback_artifact(self):
        cninfo = listing("cninfo_fulltext",
                         [record("兆易创新：公司章程", "2026-09-28T16:00:00+08:00",
                                 "http://static.cninfo.com.cn/finalpage/a.PDF")],
                         url="http://www.cninfo.com.cn/query",
                         body=b'{"totalAnnouncement":1,"announcements":[{"x":1}]}',
                         fetched_at=1_799_000_000.0, reused=True)
        blocked = {"health": ec.HEALTH_BROKEN, "content_sha256": None, "bytes": 0,
                   "content_type": "text/html",
                   "meta": {"url": "http://static.cninfo.com.cn/finalpage/a.PDF",
                            "body": b"", "fetched_at": 1_799_000_000.0, "http_status": 403,
                            "reused": False}}
        scope_document = {"health": ec.HEALTH_OK,
                          "content_sha256": ec.sha256_bytes(b"<html>policy</html>"),
                          "bytes": 18, "content_type": "text/html",
                          "meta": {"url": "https://example.test/policy.html",
                                   "body": b"<html>policy</html>",
                                   "fetched_at": 1_799_000_000.0, "http_status": 200,
                                   "reused": False}}

        def by_url(_fetcher, *, url, key, referer=None):
            return blocked if "static.cninfo.com.cn" in url else scope_document

        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext", return_value=cninfo), \
             mock.patch.object(pia_evidence.ec, "fetch_document", side_effect=by_url):
            code, payload = self.run_main([
                "--task-dir", str(self.task), "--symbols", "603986.SS",
                "--window-start", WINDOW_START, "--window-end", WINDOW_END,
                "--scope-source", "macro=https://www.stats.gov.cn/x.html@2026-09-28T00:00:00+08:00",
                "--scope-source", "sector=https://www.miit.gov.cn/y.html@2026-09-21T00:00:00+08:00",
                "--scope-source", "regulatory=http://www.pbc.gov.cn/z.html@2026-09-24T00:00:00+08:00",
            ])
        self.assertEqual(code, 0)
        report = payload["channel_results"][0]
        self.assertEqual(report["document_retrieval"]["fallback"], "listing_payload")
        self.assertTrue(report["artifact"].endswith("cninfo_fulltext_listing.json"))
        self.assertTrue(payload["channel_results"][0]["attempts"][0]["reused"])

    def test_invalid_specifications_fail_before_any_fetch(self):
        cases = [
            (["--task-dir", str(self.task), "--symbols", "002487.SZ",
              "--window-start", WINDOW_END, "--window-end", WINDOW_START], "window_start"),
            (["--task-dir", str(self.task), "--symbols", "002487.SZ",
              "--window-start", WINDOW_START, "--window-end", WINDOW_END,
              "--scope-source", "macro=https://example.test/a.html"], "scope source"),
            (["--task-dir", str(self.task), "--symbols", "002487.SZ", "002487.SZ",
              "--window-start", WINDOW_START, "--window-end", WINDOW_END], "unique"),
            (["--task-dir", str(self.task), "--symbols", "002487.SZ",
              "--window-start", WINDOW_START, "--window-end", WINDOW_END,
              "--scope-source", "macro=ftp://example.test/a.html@2026-09-28T00:00:00+08:00"],
             "public http"),
        ]
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext") as adapter:
            for argv, fragment in cases:
                with self.subTest(fragment=fragment):
                    code, payload = self.run_main(argv)
                    self.assertEqual(code, 2)
                    self.assertEqual(payload["status"], "invalid_input")
                    self.assertIn(fragment, payload["errors"][0])
            adapter.assert_not_called()


    def test_broken_channel_is_retried_once_without_reusing_the_cached_body(self):
        (self.task / "evidence").mkdir(parents=True, exist_ok=True)
        broken = listing("cninfo_fulltext", [], url="http://www.cninfo.com.cn/query",
                         body=b'{"announcements":null,"totalAnnouncement":0}',
                         fetched_at=1_799_000_000.0, health=ec.HEALTH_BROKEN)
        good = listing("cninfo_fulltext",
                       [record("大金重工：关于注销募集资金专户的公告",
                               "2026-09-22T00:00:00+08:00",
                               "http://static.cninfo.com.cn/finalpage/a.PDF")],
                       url="http://www.cninfo.com.cn/query",
                       body=b'{"totalAnnouncement":1}', fetched_at=1_799_000_010.0)
        document = {"health": ec.HEALTH_OK, "content_sha256": ec.sha256_bytes(b"pdf"),
                    "bytes": 3, "content_type": "application/pdf",
                    "meta": {"url": "http://static.cninfo.com.cn/finalpage/a.PDF",
                             "body": b"pdf", "fetched_at": 1_799_000_020.0,
                             "http_status": 200, "reused": False}}
        sleeps: list[float] = []
        szse_empty = listing("szse_announcements", [], url="http://www.szse.cn/api",
                             body=b'{"announceCount":0,"data":[]}',
                             fetched_at=1_799_000_000.0, health=ec.HEALTH_EMPTY)
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext",
                               side_effect=[broken, good]) as adapter,              mock.patch.object(pia_evidence.ec, "szse_announcements", return_value=szse_empty),              mock.patch.object(pia_evidence.ec, "fetch_document", return_value=document):
            report = pia_evidence.collect_symbol(
                self.fetcher, symbol="002487.SZ", window_start=1_790_000_000.0,
                window_end=1_800_000_000.0, evidence_dir=self.task / "evidence",
                retry_delay_seconds=0.0, sleep=sleeps.append)
        self.assertEqual(adapter.call_count, 2)
        self.assertEqual(report["health"], ec.HEALTH_OK)
        self.assertEqual(report["attempts"][0]["attempts_made"], 2)
        self.assertEqual(sleeps, [0.0])
        self.assertTrue(self.fetcher.bypass_cache)

    def test_persistently_broken_channel_stops_after_the_bounded_budget(self):
        (self.task / "evidence").mkdir(parents=True, exist_ok=True)
        broken = listing("cninfo_fulltext", [], url="http://www.cninfo.com.cn/query",
                         body=b'{"announcements":null}', fetched_at=1_799_000_000.0,
                         health=ec.HEALTH_BROKEN)
        with mock.patch.object(pia_evidence.ec, "cninfo_fulltext",
                               return_value=broken) as adapter:
            report = pia_evidence.collect_symbol(
                self.fetcher, symbol="603259.SS", window_start=1_790_000_000.0,
                window_end=1_800_000_000.0, evidence_dir=self.task / "evidence",
                max_attempts=2, retry_delay_seconds=0.0, sleep=lambda _: None)
        self.assertEqual(adapter.call_count, 2)
        self.assertEqual(report["health"], ec.HEALTH_BROKEN)
        self.assertEqual(report["reason"], "channel_broken")


if __name__ == "__main__":
    unittest.main()
