import unittest
from unittest.mock import patch

from history_manager import load_recent_history


class HistoryManagerTests(unittest.TestCase):
    def test_recent_history_accepts_timezone_aware_timestamp(self):
        entries = [
            {
                "url": "https://example.org/item",
                "timestamp": "2026-08-09T07:00:00+08:00",
            }
        ]

        with patch("history_manager._load_entries", return_value=entries):
            recent = load_recent_history(days=7)

        self.assertEqual(recent, entries)


if __name__ == "__main__":
    unittest.main()
