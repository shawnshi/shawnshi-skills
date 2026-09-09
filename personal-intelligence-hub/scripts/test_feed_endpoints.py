import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fetch_news


class FeedEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.feeds = json.loads(
            (Path(__file__).resolve().parents[1] / "references" / "karpathy_feeds.json")
            .read_text(encoding="utf-8")
        )

    def test_nvidia_healthcare_endpoint(self):
        self.assertEqual(
            [feed["url"] for feed in self.feeds if feed["name"] == "NVIDIA Healthcare"],
            ["https://blogs.nvidia.com/blog/tag/healthcare-life-sciences/feed/"],
        )

    def test_google_deepmind_endpoint(self):
        self.assertEqual(
            [feed["url"] for feed in self.feeds if feed["name"] == "Google DeepMind"],
            ["https://deepmind.google/blog/rss.xml"],
        )

    async def test_repaired_feeds_use_publication_not_observation_for_window(self):
        observed = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        window = fetch_news.build_calendar_window(
            report_date=date(2026, 9, 8),
            window_days=7,
            timezone_name="Asia/Shanghai",
        )
        cases = [
            ("NVIDIA Healthcare", "Wed, 05 Aug 2026 14:00:00 +0000",
             "2026-08-05T14:00:00+00:00", False),
            ("Google DeepMind", "Thu, 03 Sep 2026 16:00:00 +0000",
             "2026-09-03T16:00:00+00:00", True),
        ]
        for name, published, expected, in_window in cases:
            with self.subTest(source=name):
                url = next(feed["url"] for feed in self.feeds if feed["name"] == name)
                # Synthetic RSS body: exercise real feedparser and parse_rss, not a parser mock.
                article_url = "https://example.org/original-article"
                body = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{name}</title>
<link>https://example.org/</link><description>Publication fixture</description>
<item><title>Publication fixture</title><link>{article_url}</link>
<guid isPermaLink="true">{article_url}</guid><pubDate>{published}</pubDate>
<description>Original article</description></item></channel></rss>'''
                with (
                    patch("fetch_news.fetch_with_retry", AsyncMock(return_value=body)),
                    patch("fetch_news._utc_now", return_value=observed),
                ):
                    items, status = await fetch_news.parse_rss(object(), url, name, {})

                self.assertEqual(status, "OK")
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["url"], article_url)
                self.assertEqual(items[0]["source"], name)
                self.assertEqual(items[0]["published_at"], expected)
                self.assertEqual(items[0]["time"], expected)
                self.assertEqual(items[0]["published_at_source"], "rss_published")
                self.assertEqual(items[0]["retrieved_at"], observed.isoformat())
                kept, quarantine, funnel = fetch_news.apply_window_contract(
                    items, window=window, exclude_terms=[]
                )
                self.assertEqual(len(kept), int(in_window))
                self.assertEqual(quarantine, [])
                self.assertEqual(funnel["outside_window"], int(not in_window))


if __name__ == "__main__":
    unittest.main()
