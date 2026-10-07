"""Contract tests for the primary-source evidence channels (``evidence_channels.py``).

The two behaviours that must never regress: (a) a channel that answers HTTP 200
with a structurally impossible payload is ``broken``, not "no announcements";
(b) cached bytes are reused only within their declared age and always carry the
reuse label.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evidence_channels as ec  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int, body: bytes, content_type: str = "application/json"):
        self.status_code = status_code
        self.content = body
        self.headers = {"Content-Type": content_type}


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | Exception):
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str, url: str):
        self.calls.append((method, url))
        item = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=None):  # noqa: ANN001 - test double
        return self._next("GET", url)

    def post(self, url, data=None, headers=None, timeout=None):  # noqa: ANN001 - test double
        return self._next("POST", url)


def broken_cninfo_payload() -> dict:
    """The exact shape the live cninfo query endpoint returned on 2026-09-29."""
    return {"classifiedAnnouncements": None, "totalSecurities": 0, "totalAnnouncement": 0,
            "totalRecordNum": 0, "announcements": None, "categoryList": None,
            "hasMore": False, "totalpages": 0}


class ClassifierTests(unittest.TestCase):
    def test_cninfo_null_announcements_is_a_broken_channel_not_an_empty_result(self):
        health, records = ec.classify_cninfo_fulltext(broken_cninfo_payload())
        self.assertEqual(health, ec.HEALTH_BROKEN)
        self.assertEqual(records, [])

    def test_cninfo_genuine_empty_window_is_empty_not_broken(self):
        payload = {"totalAnnouncement": 0, "announcements": [], "totalRecordNum": 0}
        self.assertEqual(ec.classify_cninfo_fulltext(payload), (ec.HEALTH_EMPTY, []))

    def test_cninfo_records_normalize_to_http_document_locators(self):
        payload = {
            "totalAnnouncement": 1,
            "announcements": [{
                "secCode": "002487", "announcementTitle": "<em>大金重工</em>：注销公告",
                "announcementTime": 1790006400000, "adjunctUrl": "finalpage/2026-09-22/1225575461.PDF",
            }],
        }
        health, records = ec.classify_cninfo_fulltext(payload)
        self.assertEqual(health, ec.HEALTH_OK)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "大金重工：注销公告")
        self.assertTrue(records[0]["document_url"].startswith("http://static.cninfo.com.cn/"))
        self.assertIn("+08:00", records[0]["published_at"])

    def test_szse_requires_count_and_list(self):
        self.assertEqual(ec.classify_szse_announcements({"data": []}),
                         (ec.HEALTH_BROKEN, []))
        self.assertEqual(ec.classify_szse_announcements({"announceCount": 0, "data": []}),
                         (ec.HEALTH_EMPTY, []))
        health, records = ec.classify_szse_announcements({"announceCount": 1, "data": [{
            "title": "大金重工：关于注销募集资金专户的公告", "publishTime": "2026-09-22 00:00:00",
            "attachPath": "/disc/disk03/finalpage/2026-09-22/415eceba.PDF", "secCode": ["002487"]}]})
        self.assertEqual(health, ec.HEALTH_OK)
        self.assertEqual(records[0]["document_url"], None)
        self.assertEqual(records[0]["document_blocked_reason"], "szse_attachment_pdf")

    def test_hkex_jsonp_parsing(self):
        self.assertEqual(ec.classify_hkex_prefix("callback({\"more\":\"0\"})"),
                         (ec.HEALTH_BROKEN, []))
        self.assertEqual(ec.classify_hkex_prefix("callback({\"stockInfo\":[]})"),
                         (ec.HEALTH_EMPTY, []))
        health, stocks = ec.classify_hkex_prefix(
            "callback({\"more\":\"1\",\"stockInfo\":[{\"stockId\":6898,\"code\":\"02899\","
            "\"name\":\"紫金礦業\"}]})")
        self.assertEqual(health, ec.HEALTH_OK)
        self.assertEqual(stocks[0]["stockId"], 6898)

    def test_hkex_news_accepts_the_stringified_result_envelope(self):
        inner = json.dumps([{"TITLE": "公告及通告", "DATE_TIME": "28/09/2026 19:22",
                             "FILE_LINK": "/listedco/listconews/sehk/2026/0928/a.pdf"}])
        health, records = ec.classify_hkex_news(json.dumps({"result": inner}))
        self.assertEqual(health, ec.HEALTH_OK)
        self.assertEqual(records[0]["title"], "公告及通告")
        self.assertIn("+08:00", records[0]["published_at"])
        self.assertEqual(ec.classify_hkex_news(json.dumps({"result": "not json"})),
                         (ec.HEALTH_BROKEN, []))
        self.assertEqual(ec.classify_hkex_news(json.dumps({"result": ""})),
                         (ec.HEALTH_EMPTY, []))

    def test_sec_submissions_builds_archive_urls_from_acceptance_time(self):
        payload = {"cik": "0001652044", "filings": {"recent": {
            "accessionNumber": ["0001193125-26-342390"], "form": ["8-K"],
            "filingDate": ["2026-08-10"], "acceptanceDateTime": ["2026-08-10T20:10:48.000Z"],
            "primaryDocument": ["d171253d8k.htm"]}}}
        health, records = ec.classify_sec_submissions(payload)
        self.assertEqual(health, ec.HEALTH_OK)
        self.assertEqual(records[0]["published_at"], "2026-08-10T20:10:48.000Z")
        self.assertIn("/Archives/edgar/data/1652044/000119312526342390/d171253d8k.htm",
                      records[0]["document_url"])
        self.assertEqual(ec.classify_sec_submissions({"filings": {}}), (ec.HEALTH_BROKEN, []))


class FetcherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "cache"
        self.now = 1_800_000_000.0

    def tearDown(self):
        self._tmp.cleanup()

    def fetcher(self, responses, *, max_age=3600.0, clock=None):
        self.session = FakeSession(responses)
        return ec.ChannelFetcher(session=self.session, cache_dir=self.cache,
                                 max_cache_age_seconds=max_age,
                                 clock=clock or (lambda: self.now))

    def test_cache_is_reused_within_its_age_and_refetched_after_expiry(self):
        payload = {"totalAnnouncement": 0, "announcements": [], "totalRecordNum": 0}
        fetcher = self.fetcher([FakeResponse(200, json.dumps(payload).encode())])
        first = ec.cninfo_fulltext(fetcher, code="002487", date_from="2026-09-01",
                                   date_to="2026-09-29")
        self.assertEqual(first["health"], ec.HEALTH_EMPTY)
        self.assertFalse(first["meta"]["reused"])
        second = ec.cninfo_fulltext(fetcher, code="002487", date_from="2026-09-01",
                                    date_to="2026-09-29")
        self.assertTrue(second["meta"]["reused"])
        self.assertEqual(len(self.session.calls), 1)

        expired = self.fetcher([FakeResponse(200, json.dumps(payload).encode())],
                               max_age=10.0, clock=lambda: self.now + 100.0)
        third = ec.cninfo_fulltext(expired, code="002487", date_from="2026-09-01",
                                   date_to="2026-09-29")
        self.assertFalse(third["meta"]["reused"])
        self.assertEqual(third["meta"]["cache_age_seconds"], 0.0)

    def test_transport_failure_is_reported_not_hidden_as_empty(self):
        fetcher = self.fetcher(RuntimeError("connection reset"))
        result = ec.cninfo_fulltext(fetcher, code="300253", date_from="2026-09-01",
                                    date_to="2026-09-29")
        self.assertEqual(result["health"], ec.HEALTH_BROKEN)
        self.assertIn("RuntimeError", result["error"])

    def test_non_200_status_is_broken(self):
        fetcher = self.fetcher([FakeResponse(503, b"<html>busy</html>", "text/html")])
        result = ec.szse_announcements(fetcher, code="002487", date_from="2026-09-01",
                                       date_to="2026-09-29")
        self.assertEqual(result["health"], ec.HEALTH_BROKEN)
        self.assertIn("http_status=503", result["error"])

    def test_document_fetch_rejects_waf_pages_and_blocked_statuses(self):
        fetcher = self.fetcher([FakeResponse(403, b"<!DOCTYPE html><html>WAF block</html>",
                                             "text/html")])
        blocked = ec.fetch_document(fetcher, url="http://example.test/a.pdf", key="blocked")
        self.assertEqual(blocked["health"], ec.HEALTH_BROKEN)

        good = ec.fetch_document(
            self.fetcher([FakeResponse(200, b"%PDF-1.4 payload", "application/pdf")]),
            url="http://example.test/b.pdf", key="good")
        self.assertEqual(good["health"], ec.HEALTH_OK)
        self.assertEqual(good["bytes"], 16)
        self.assertEqual(good["content_sha256"],
                         ec.sha256_bytes(b"%PDF-1.4 payload"))

    def test_hkex_stock_id_requires_the_padded_code_match(self):
        body = ("cb({\"more\":\"1\",\"stockInfo\":[{\"stockId\":1000302580,\"code\":\"28990\","
                "\"name\":\"其他\"},{\"stockId\":6898,\"code\":\"02899\",\"name\":\"紫金礦業\"}]})")
        fetcher = self.fetcher([FakeResponse(200, body.encode())])
        result = ec.hkex_stock_id(fetcher, code="2899")
        self.assertEqual(result["health"], ec.HEALTH_OK)
        self.assertEqual(result["stock_id"], 6898)

    def test_sec_ticker_lookup_maps_to_a_zero_padded_cik(self):
        payload = {"0": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."}}
        fetcher = self.fetcher([FakeResponse(200, json.dumps(payload).encode())])
        result = ec.sec_ticker_cik(fetcher, ticker="goog")
        self.assertEqual(result["health"], ec.HEALTH_OK)
        self.assertEqual(result["cik"], "0001652044")
        missing = ec.sec_ticker_cik(self.fetcher([FakeResponse(200, json.dumps(payload).encode())]),
                                    ticker="ZZZZ")
        self.assertEqual(missing["health"], ec.HEALTH_EMPTY)


class BrokenChannelRegistryTests(unittest.TestCase):
    def test_known_broken_channels_are_documented_with_a_reason(self):
        for name in ("sse_bulletin_query", "cninfo_announcement_query", "szse_attachment_pdf"):
            with self.subTest(name=name):
                self.assertIn(name, ec.KNOWN_BROKEN_CHANNELS)
                self.assertGreater(len(ec.KNOWN_BROKEN_CHANNELS[name]), 20)


if __name__ == "__main__":
    unittest.main()
