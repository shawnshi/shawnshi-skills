import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from history_manager import (
    _coerce_history_entries,
    generate_content_id,
    generate_event_id,
    load_recent_history,
    match_history,
    normalize_url,
    save_history_items,
    save_history,
)


NOW = datetime(2026, 8, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def identity(event_date="2026-08-09"):
    return {
        "primary_domain": "technology",
        "actor": "Example",
        "action": "released",
        "object": "Agent Runtime",
        "event_date": event_date,
        "key_version": "1",
    }


class HistoryManagerTests(unittest.TestCase):
    def test_legacy_save_history_preserves_supplied_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            payload = save_history(
                ["https://example.org/item"],
                ["legacy-fingerprint"],
                ["Legacy title"],
                path=path,
                now=NOW,
            )

        self.assertEqual(payload["entries"][0]["fingerprints"], ["legacy-fingerprint"])

    def test_recent_history_accepts_timezone_aware_timestamp(self):
        entries = [
            {
                "canonical_url": "https://example.org/item",
                "last_seen_at": "2026-08-09T07:00:00+08:00",
            }
        ]

        with patch("history_manager._load_entries", return_value=entries):
            recent = load_recent_history(days=7, now=NOW)

        self.assertEqual(recent, entries)

    def test_recent_history_excludes_entries_after_report_clock(self):
        entries = [
            {
                "event_id": "future",
                "last_seen_at": "2026-08-20T09:00:00+08:00",
            },
            {
                "event_id": "current",
                "last_seen_at": "2026-08-10T09:00:00+08:00",
            },
        ]

        with patch("history_manager._load_entries", return_value=entries):
            recent = load_recent_history(days=7, now=NOW)

        self.assertEqual([entry["event_id"] for entry in recent], ["current"])

    def test_update_index_dictionary_is_not_silently_empty(self):
        legacy = {
            "urls": {"https://example.org/item?utm_source=x": "2026-08-09T07:00:00+08:00"},
            "fingerprints": {"abc": "2026-08-09T07:00:00+08:00"},
        }

        entries = _coerce_history_entries(legacy)

        self.assertEqual(len(entries), 2)
        self.assertTrue(any(entry.get("canonical_url") for entry in entries))
        self.assertTrue(any("abc" in entry.get("fingerprints", []) for entry in entries))

    def test_history_v2_round_trip(self):
        item = {
            "event_identity": identity(),
            "event_id": generate_event_id(identity()),
            "identity_quality": "semantic",
            "url": "https://example.org/release",
            "title": "Agent Runtime released",
            "source": "Example",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            save_history_items([item], archive_ref="intelligence_20260810_briefing.json", path=path, now=NOW)
            payload = json.loads(path.read_text(encoding="utf-8"))
            with patch("history_manager.HISTORY_PATH", path):
                recent = load_recent_history(days=7, now=NOW)

        self.assertEqual(payload["schema_version"], "2.0")
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["event_id"], item["event_id"])

    def test_same_event_with_different_url_matches_event_id(self):
        event_id = generate_event_id(identity())
        entries = [
            {
                "event_id": event_id,
                "canonical_url": "https://first.example/release",
                "urls": ["https://first.example/release"],
                "fingerprints": [],
                "title": "First headline",
                "last_seen_at": NOW.isoformat(),
            }
        ]
        candidate = {
            "event_id": event_id,
            "event_identity": identity(),
            "url": "https://second.example/news",
            "title": "完全不同的标题",
            "source": "Second",
        }

        result = match_history(candidate, entries=entries, now=NOW)

        self.assertTrue(result["redundant"])
        self.assertEqual(result["match_type"], "event_id")

    def test_unknown_event_identity_uses_provisional_content_id(self):
        identifier = generate_content_id(
            "https://example.org/item?utm_source=x",
            "A title",
            "Example",
        )

        self.assertTrue(identifier.startswith("cnt1_"))

    def test_different_semantic_events_on_stable_url_are_not_duplicates(self):
        first_identity = identity()
        second_identity = {**identity(), "object": "clinical AI evaluation version 2"}
        entries = [
            {
                "event_id": generate_event_id(first_identity),
                "identity_quality": "semantic",
                "canonical_url": "https://example.org/releases",
                "urls": ["https://example.org/releases"],
                "fingerprints": [],
                "title": "Release index",
                "last_seen_at": NOW.isoformat(),
            }
        ]
        candidate = {
            "event_id": generate_event_id(second_identity),
            "event_identity": second_identity,
            "identity_quality": "semantic",
            "url": "https://example.org/releases",
            "title": "Release index",
            "source": "Example",
        }

        result = match_history(candidate, entries=entries, now=NOW)

        self.assertFalse(result["redundant"])
        self.assertEqual(result["match_type"], "none")

    def test_provisional_candidate_still_uses_url_fallback(self):
        entries = [
            {
                "event_id": generate_event_id(identity()),
                "identity_quality": "semantic",
                "canonical_url": "https://example.org/releases",
                "urls": ["https://example.org/releases"],
                "fingerprints": [],
                "title": "Release index",
                "last_seen_at": NOW.isoformat(),
            }
        ]
        candidate = {
            "event_id": generate_content_id(
                "https://example.org/releases", "Release index", "Example"
            ),
            "identity_quality": "provisional",
            "url": "https://example.org/releases",
            "title": "Release index",
            "source": "Example",
        }

        result = match_history(candidate, entries=entries, now=NOW)

        self.assertTrue(result["redundant"])
        self.assertEqual(result["match_type"], "url")

    def test_url_normalization_removes_tracking_fragment_and_sorts_query(self):
        normalized = normalize_url(
            "HTTPS://Example.org/path?z=2&utm_source=x&a=1#section"
        )

        self.assertEqual(normalized, "https://example.org/path?a=1&z=2")


if __name__ == "__main__":
    unittest.main()
