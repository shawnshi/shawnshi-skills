import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from history_manager import generate_event_id, load_recent_history
from update_index import rebuild_history


class UpdateIndexTests(unittest.TestCase):
    def test_json_archives_rebuild_v2_history_idempotently_without_rewrite(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        identity = {
            "primary_domain": "technology",
            "actor": "Example",
            "action": "released",
            "object": "Agent Runtime",
            "event_date": "2026-08-09",
            "key_version": "1",
        }
        event_id = generate_event_id(identity)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            nested = news / "archive"
            nested.mkdir(parents=True)
            history = root / "history.json"
            first = news / "intelligence_20260809_briefing.json"
            second = nested / "intelligence_20260810_briefing.json"
            first.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3",
                        "report_date": "2026-08-09",
                        "generated_at": "2026-08-09T09:00:00+08:00",
                        "top_10": [
                            {
                                "event_id": event_id,
                                "event_identity": identity,
                                "identity_quality": "semantic",
                                "url": "https://first.example/release",
                                "title": "Agent Runtime released",
                                "source": "Example",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "schema_version": "1.2",
                        "report_date": "2026-08-10",
                        "generated_at": "2026-08-10T09:00:00+08:00",
                        "top_10": [
                            {
                                "event_id": event_id,
                                "event_identity": identity,
                                "identity_quality": "semantic",
                                "url": "https://second.example/news",
                                "title": "不同标题",
                                "source": "Second",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = hashlib.sha256(first.read_bytes()).hexdigest()

            rebuild_history(news_dir=news, history_file=history, now=now)
            once = history.read_bytes()
            rebuild_history(news_dir=news, history_file=history, now=now)
            twice = history.read_bytes()
            entries = load_recent_history(days=7, now=now, path=history)
            after = hashlib.sha256(first.read_bytes()).hexdigest()

        self.assertEqual(once, twice)
        self.assertEqual(after, before)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event_id"], event_id)
        self.assertEqual(len(entries[0]["urls"]), 2)
        self.assertEqual(entries[0]["first_seen_at"], "2026-08-09T09:00:00+08:00")
        self.assertEqual(entries[0]["last_seen_at"], "2026-08-10T09:00:00+08:00")
        self.assertIn('"generated_at": "2026-08-12T10:00:00+08:00"', once.decode("utf-8"))

    def test_old_filename_date_does_not_become_recent_at_rebuild_time(self):
        now = datetime(2026, 8, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = root / "history.json"
            archive = news / "intelligence_20200101_briefing.json"
            archive.write_text(
                json.dumps(
                    {
                        "schema_version": "1.2",
                        "top_10": [
                            {
                                "url": "https://old.example/event",
                                "title": "Old event",
                                "source": "Archive",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rebuild_history(news_dir=news, history_file=history, now=now)
            recent = load_recent_history(days=7, now=now, path=history)
            payload = json.loads(history.read_text(encoding="utf-8"))

        self.assertEqual(recent, [])
        self.assertTrue(payload["entries"][0]["last_seen_at"].startswith("2020-01-01"))


if __name__ == "__main__":
    unittest.main()
