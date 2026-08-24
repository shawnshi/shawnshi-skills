import asyncio
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

import fetch_news


class FetchContractTests(unittest.IsolatedAsyncioTestCase):
    def test_seven_day_calendar_window_is_inclusive(self):
        window = fetch_news.build_calendar_window(
            report_date=date(2026, 8, 10),
            window_days=7,
            timezone_name="Asia/Shanghai",
        )

        self.assertEqual(window["start"], "2026-08-04")
        self.assertEqual(window["end"], "2026-08-10")
        self.assertEqual(window["days"], 7)
        self.assertEqual(window["mode"], "calendar_days")

    def test_window_uses_publication_datetime_own_timezone_date(self):
        window = fetch_news.build_calendar_window(
            report_date=date(2026, 8, 20),
            window_days=1,
            timezone_name="Asia/Shanghai",
        )

        kept, quarantine, funnel = fetch_news.apply_window_contract(
            [
                {
                    "title": "source-local boundary",
                    "published_at": "2026-08-20T23:30:00-07:00",
                }
            ],
            window=window,
            exclude_terms=[],
        )

        self.assertEqual([item["title"] for item in kept], ["source-local boundary"])
        self.assertEqual(quarantine, [])
        self.assertEqual(funnel["within_window"], 1)

    def test_unknown_and_invalid_dates_are_quarantined_and_counts_conserve(self):
        window = fetch_news.build_calendar_window(
            report_date=date(2026, 8, 10),
            window_days=7,
            timezone_name="Asia/Shanghai",
        )
        items = [
            {"title": "kept", "published_at": "2026-08-10T01:00:00+00:00"},
            {"title": "unknown", "published_at": "unknown"},
            {"title": "invalid", "published_at": "not-a-date"},
            {"title": "old", "published_at": "2026-08-01T01:00:00+00:00"},
            {"title": "excluded", "published_at": "2026-08-09", "raw_desc": "noise"},
        ]

        kept, quarantine, funnel = fetch_news.apply_window_contract(
            items,
            window=window,
            exclude_terms=["noise"],
        )

        self.assertEqual([item["title"] for item in kept], ["kept"])
        self.assertEqual(
            {entry["reason"] for entry in quarantine},
            {"unknown_published_at", "invalid_published_at"},
        )
        self.assertEqual(funnel["raw"], 5)
        self.assertEqual(funnel["dated"], 3)
        self.assertEqual(funnel["quarantined"], 2)
        self.assertEqual(funnel["within_window"], 2)
        self.assertEqual(funnel["outside_window"], 1)
        self.assertEqual(funnel["excluded"], 1)
        self.assertEqual(funnel["retained"], 1)
        self.assertEqual(funnel["raw"], funnel["dated"] + funnel["quarantined"])
        self.assertEqual(
            funnel["dated"],
            funnel["within_window"] + funnel["outside_window"],
        )
        self.assertEqual(
            funnel["within_window"],
            funnel["excluded"] + funnel["retained"],
        )

    def test_observation_time_is_not_fabricated_as_github_or_v2ex_publication(self):
        retrieved_at = "2026-08-10T02:00:00+00:00"

        github = fetch_news._build_github_item(
            title="owner/repo",
            url="https://github.com/owner/repo",
            description="description",
            retrieved_at=retrieved_at,
        )
        v2ex = fetch_news._build_v2ex_item(
            {"title": "topic", "url": "https://www.v2ex.com/t/1", "content": "body"},
            retrieved_at=retrieved_at,
        )

        for item in (github, v2ex):
            self.assertEqual(item["published_at"], "unknown")
            self.assertEqual(item["published_at_source"], "unknown")
            self.assertEqual(item["time"], "unknown")
            self.assertEqual(item["retrieved_at"], retrieved_at)

    def test_hackernews_created_time_is_utc_aware_and_retrieval_is_explicit(self):
        retrieved_at = "2026-08-10T02:00:00+00:00"
        item = fetch_news._build_hackernews_item(
            {"title": "story", "url": "https://example.org/story", "time": 1786320000},
            story_id=42,
            retrieved_at=retrieved_at,
        )

        self.assertTrue(item["published_at"].endswith("+00:00"))
        self.assertEqual(item["published_at_source"], "api_created")
        self.assertEqual(item["retrieved_at"], retrieved_at)

    def test_coverage_distinguishes_degraded_and_failed_runs(self):
        funnel = {
            "raw": 2,
            "dated": 1,
            "quarantined": 1,
            "within_window": 1,
            "outside_window": 0,
            "excluded": 0,
            "retained": 1,
            "quarantine_reasons": {"unknown_published_at": 1, "invalid_published_at": 0},
        }

        degraded = fetch_news.build_coverage({"one": "OK", "two": "timeout"}, funnel)
        failed = fetch_news.build_coverage({"one": "timeout"}, funnel)

        self.assertEqual(degraded["run_status"], "degraded")
        self.assertEqual(failed["run_status"], "failed")
        self.assertEqual(degraded["baseline_status"], "degraded")
        self.assertEqual(degraded["source_attempted"], 2)
        self.assertEqual(degraded["dated_candidate_rate"], 0.5)
        self.assertEqual(degraded["required_lane_failures"], [])

    def test_successful_sources_with_zero_candidates_are_degraded(self):
        coverage = fetch_news.build_coverage(
            {"one": "OK", "two": "OK"},
            {"raw": 0, "dated": 0, "quarantined": 0},
        )

        self.assertEqual(coverage["run_status"], "degraded")
        self.assertEqual(coverage["coverage_confidence"], "medium")
        self.assertIn("no candidates", " ".join(coverage["reasons"]))


class BoundedConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_200_body_is_not_counted_as_successful_rss(self):
        with patch.object(
            fetch_news,
            "fetch_with_retry",
            new=AsyncMock(return_value="<html><title>Access denied</title></html>"),
        ):
            items, status = await fetch_news.parse_rss(
                object(),
                "https://example.org/feed",
                "Example",
                {},
            )

        self.assertEqual(items, [])
        self.assertNotEqual(status, "OK")
        self.assertIn("recognized RSS", status)

    async def test_rss_updated_time_is_not_used_as_publication_time(self):
        feed = type(
            "Feed",
            (),
            {
                "version": "rss20",
                "bozo": False,
                "feed": {"title": "Example"},
                "entries": [
                    {
                        "title": "updated-only",
                        "link": "https://example.org/updated-only",
                        "updated": "Sun, 09 Aug 2026 10:00:00 GMT",
                    }
                ]
            },
        )()
        with (
            patch("fetch_news.fetch_with_retry", AsyncMock(return_value="feed")),
            patch("feedparser.parse", return_value=feed),
        ):
            items, status = await fetch_news.parse_rss(
                object(),
                "https://example.org/feed",
                "Example",
                {},
            )

        self.assertEqual(status, "OK")
        self.assertEqual(items[0]["published_at"], "unknown")
        self.assertEqual(items[0]["published_at_source"], "unknown")

    async def test_fetch_requests_respect_semaphore_bound(self):
        tracker = {"active": 0, "maximum": 0}

        class Response:
            async def __aenter__(self):
                tracker["active"] += 1
                tracker["maximum"] = max(tracker["maximum"], tracker["active"])
                await asyncio.sleep(0.01)
                return self

            async def __aexit__(self, exc_type, exc, tb):
                tracker["active"] -= 1

            def raise_for_status(self):
                return None

            async def text(self):
                return "ok"

        class Session:
            def get(self, *args, **kwargs):
                return Response()

        semaphore = asyncio.Semaphore(2)
        results = await asyncio.gather(
            *[
                fetch_news.fetch_with_retry(
                    Session(),
                    f"https://example.org/{index}",
                    semaphore=semaphore,
                )
                for index in range(6)
            ]
        )

        self.assertEqual(results, ["ok"] * 6)
        self.assertLessEqual(tracker["maximum"], 2)

    async def test_fetch_does_not_retry_permanent_http_error(self):
        class PermanentHttpError(Exception):
            pass

        class Response:
            def __init__(self, status, tracker):
                self.status = status
                self.tracker = tracker

            async def __aenter__(self):
                self.tracker["attempts"] += 1
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            def raise_for_status(self):
                error = PermanentHttpError("permanent client response")
                error.status = self.status
                raise error

        class Session:
            def __init__(self, status, tracker):
                self.status = status
                self.tracker = tracker

            def get(self, *args, **kwargs):
                return Response(self.status, self.tracker)

        for status in (403, 404, 406):
            with self.subTest(status=status):
                tracker = {"attempts": 0}
                with self.assertRaises(PermanentHttpError):
                    await fetch_news.fetch_with_retry(
                        Session(status, tracker), "https://example.org/missing"
                    )

                self.assertEqual(tracker["attempts"], 1)

    async def test_fetch_retries_transient_http_error(self):
        tracker = {"attempts": 0}

        class TransientHttpError(Exception):
            status = 429

        class Response:
            async def __aenter__(self):
                tracker["attempts"] += 1
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            def raise_for_status(self):
                if tracker["attempts"] == 1:
                    raise TransientHttpError("unavailable")

            async def text(self):
                return "ok"

        class Session:
            def get(self, *args, **kwargs):
                return Response()

        with patch.object(fetch_news.asyncio, "sleep", new=AsyncMock()):
            result = await fetch_news.fetch_with_retry(
                Session(), "https://example.org/transient"
            )

        self.assertEqual(result, "ok")
        self.assertEqual(tracker["attempts"], 2)

    async def test_fetch_does_not_retry_permanent_transport_error(self):
        tracker = {"attempts": 0}

        class Response:
            async def __aenter__(self):
                tracker["attempts"] += 1
                raise RuntimeError("curl: (35) OPENSSL_internal: invalid library (0)")

            async def __aexit__(self, exc_type, exc, tb):
                return None

        class Session:
            def get(self, *args, **kwargs):
                return Response()

        with patch.object(fetch_news.asyncio, "sleep", new=AsyncMock()) as sleep:
            with self.assertRaisesRegex(RuntimeError, "invalid library"):
                await fetch_news.fetch_with_retry(
                    Session(), "https://example.org/permanent"
                )

        self.assertEqual(tracker["attempts"], 1)
        sleep.assert_not_called()

    async def test_scan_rejects_excessive_concurrency_before_runtime_writes(self):
        with patch("fetch_news.ensure_runtime_dirs") as ensure_runtime_dirs:
            with self.assertRaisesRegex(ValueError, "between 1 and"):
                await fetch_news.scan_all(max_concurrency=fetch_news.MAX_CONCURRENCY + 1)

        ensure_runtime_dirs.assert_not_called()

    async def test_hackernews_fetches_details_concurrently_and_keeps_partial_success(self):
        tracker = {"active": 0, "maximum": 0}

        async def fake_fetch(session, url, **kwargs):
            if url.endswith("topstories.json"):
                return [1, 2, 3]
            tracker["active"] += 1
            tracker["maximum"] = max(tracker["maximum"], tracker["active"])
            try:
                await asyncio.sleep(0.01)
                if url.endswith("/2.json"):
                    raise RuntimeError("detail unavailable")
                story_id = int(url.rsplit("/", 1)[-1].split(".", 1)[0])
                return {"title": f"story {story_id}", "time": 1786320000}
            finally:
                tracker["active"] -= 1

        cache = {}
        with patch.object(fetch_news, "fetch_with_retry", side_effect=fake_fetch):
            items, status = await fetch_news.fetch_hackernews(object(), cache)

        self.assertGreater(tracker["maximum"], 1)
        self.assertEqual([item["title"] for item in items], ["story 1", "story 3"])
        self.assertEqual(status, "partial: 1/3 item requests failed")
        self.assertEqual(
            set(cache),
            {
                "https://news.ycombinator.com/item?id=1",
                "https://news.ycombinator.com/item?id=3",
            },
        )

    async def test_scan_failure_updates_blackboard_state(self):
        with (
            patch("fetch_news.ensure_runtime_dirs"),
            patch("fetch_news.init_blackboard"),
            patch("fetch_news.update_phase") as update_phase,
            patch("fetch_news._scan_all_impl", side_effect=RuntimeError("boom")),
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await fetch_news.scan_all(max_concurrency=2)

        self.assertEqual(
            [call.args for call in update_phase.call_args_list],
            [("scan", "running"), ("scan", "failed")],
        )

    async def test_scan_deadline_preserves_completed_sources_and_marks_pending(self):
        fast_item = {
            "title": "fast source item",
            "url": "https://example.org/fast",
            "published_at": "2026-08-10T00:00:00+00:00",
            "published_at_source": "feed_entry",
            "time": "2026-08-10T00:00:00+00:00",
            "retrieved_at": "2026-08-10T02:00:00+00:00",
            "raw_desc": "",
        }

        class Session:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        async def never_finishes(*args, **kwargs):
            await asyncio.Event().wait()

        saved = []
        with (
            patch("fetch_news.ensure_runtime_dirs"),
            patch("fetch_news.init_blackboard"),
            patch("fetch_news.update_phase"),
            patch("fetch_news.record_scan_stats"),
            patch("fetch_news.load_cache", return_value={}),
            patch("fetch_news.save_cache"),
            patch("fetch_news.load_config", return_value=({"filters": {}}, [])),
            patch("aiohttp.TCPConnector", return_value=object()),
            patch("aiohttp.ClientSession", Session),
            patch("fetch_news.fetch_hackernews", side_effect=never_finishes),
            patch(
                "fetch_news.fetch_github_trending",
                AsyncMock(return_value=([fast_item], "OK")),
            ),
            patch("fetch_news.fetch_v2ex", AsyncMock(return_value=([], "OK"))),
            patch("fetch_news.atomic_dump_json", side_effect=lambda path, data: saved.append(data)),
        ):
            await fetch_news.scan_all(
                report_date=date(2026, 8, 10),
                max_concurrency=2,
                scan_deadline_seconds=0.02,
            )

        payload = saved[0]
        self.assertEqual(payload["coverage"]["source_attempted"], 3)
        self.assertEqual(payload["coverage"]["source_succeeded"], 2)
        self.assertEqual(payload["coverage"]["source_failed"], 1)
        self.assertEqual(
            [item["title"] for item in payload["items"]],
            ["fast source item"],
        )
        self.assertEqual(payload["metadata"]["timed_out_sources"], 1)
        self.assertEqual(payload["metadata"]["cancellation_pending_sources"], 0)
        self.assertEqual(
            payload["metadata"]["sources"]["Hacker News"]["reason"],
            "scan_deadline_exceeded",
        )

    async def test_scan_rejects_invalid_deadline_before_runtime_writes(self):
        with patch("fetch_news.ensure_runtime_dirs") as ensure_runtime_dirs:
            with self.assertRaisesRegex(ValueError, "scan_deadline_seconds"):
                await fetch_news.scan_all(scan_deadline_seconds=0)

        ensure_runtime_dirs.assert_not_called()

    async def test_scan_cancellation_cleanup_has_a_bounded_grace_period(self):
        class Session:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        async def delays_first_cancellation(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(1)

        saved = []
        loop = asyncio.get_running_loop()
        with (
            patch("fetch_news.ensure_runtime_dirs"),
            patch("fetch_news.init_blackboard"),
            patch("fetch_news.update_phase"),
            patch("fetch_news.record_scan_stats"),
            patch("fetch_news.load_cache", return_value={}),
            patch("fetch_news.save_cache"),
            patch("fetch_news.load_config", return_value=({"filters": {}}, [])),
            patch("aiohttp.TCPConnector", return_value=object()),
            patch("aiohttp.ClientSession", Session),
            patch("fetch_news.fetch_hackernews", side_effect=delays_first_cancellation),
            patch("fetch_news.fetch_github_trending", AsyncMock(return_value=([], "OK"))),
            patch("fetch_news.fetch_v2ex", AsyncMock(return_value=([], "OK"))),
            patch("fetch_news.atomic_dump_json", side_effect=lambda path, data: saved.append(data)),
        ):
            started = loop.time()
            await fetch_news.scan_all(
                report_date=date(2026, 8, 10),
                max_concurrency=2,
                scan_deadline_seconds=0.02,
                cancellation_grace_seconds=0.02,
            )

        self.assertLess(loop.time() - started, 0.5)
        self.assertEqual(saved[0]["metadata"]["cancellation_pending_sources"], 1)

    async def test_scan_output_exposes_coverage_quarantine_and_conserved_funnel(self):
        valid = {
            "title": "valid",
            "url": "https://example.org/valid",
            "published_at": "2026-08-10T00:00:00+00:00",
            "published_at_source": "api_created",
            "time": "2026-08-10T00:00:00+00:00",
            "retrieved_at": "2026-08-10T02:00:00+00:00",
            "raw_desc": "",
        }
        undated = {
            "title": "undated",
            "url": "https://example.org/undated",
            "published_at": "unknown",
            "published_at_source": "unknown",
            "time": "unknown",
            "retrieved_at": "2026-08-10T02:00:00+00:00",
            "raw_desc": "",
        }

        class Session:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        saved = []
        with (
            patch("fetch_news.ensure_runtime_dirs"),
            patch("fetch_news.init_blackboard"),
            patch("fetch_news.update_phase"),
            patch("fetch_news.record_scan_stats"),
            patch("fetch_news.load_cache", return_value={}),
            patch("fetch_news.save_cache"),
            patch("fetch_news.load_config", return_value=({"filters": {}}, [])),
            patch("aiohttp.TCPConnector", return_value=object()) as connector,
            patch("aiohttp.ClientSession", Session),
            patch("fetch_news.fetch_hackernews", AsyncMock(return_value=([valid, undated], "OK"))),
            patch("fetch_news.fetch_github_trending", AsyncMock(return_value=([], "OK"))),
            patch("fetch_news.fetch_v2ex", AsyncMock(return_value=([], "OK"))),
            patch("fetch_news.atomic_dump_json", side_effect=lambda path, data: saved.append(data)),
        ):
            await fetch_news.scan_all(
                report_date=date(2026, 8, 10),
                window_days=7,
                timezone_name="Asia/Shanghai",
                max_concurrency=2,
            )

        payload = saved[0]
        self.assertEqual(payload["candidate_funnel"]["raw"], 2)
        self.assertEqual(payload["candidate_funnel"]["retained"], 1)
        self.assertEqual(payload["candidate_funnel"]["quarantined"], 1)
        self.assertEqual(len(payload["quarantine"]), 1)
        self.assertEqual(payload["coverage"]["run_status"], "degraded")
        self.assertEqual(payload["metadata"]["window"]["start"], "2026-08-04")
        self.assertGreaterEqual(payload["metadata"]["elapsed_seconds"], 0)
        connector.assert_called_once_with(
            limit=2,
            limit_per_host=2,
            ttl_dns_cache=300,
        )


if __name__ == "__main__":
    unittest.main()
