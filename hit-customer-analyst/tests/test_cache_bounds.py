from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import SCRIPTS, load_module

rp = load_module("cache_bounds_plan", SCRIPTS / "research_plan.py")
NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


class CacheBoundsTests(unittest.TestCase):
    def test_batch_snapshot_freshness_hash_and_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = rp.SourceCache(
                Path(temp) / "cache.json", {"institution": 1}, clock=lambda: NOW
            )
            saved = cache.put(
                "https://example.test/a",
                "body",
                ttl_class="institution",
                metadata={"a": [1]},
            )
            with patch.object(cache, "load", wraps=cache.load) as load:
                hits = cache.lookup_many(["https://example.test/a"] * 100)
                self.assertEqual(load.call_count, 1)
            hits[0]["metadata"]["a"].append(2)
            self.assertEqual(hits[1]["metadata"]["a"], [1])
            self.assertIsNone(
                cache.lookup_many(
                    ["https://example.test/a"], expected_content_sha256="wrong"
                )[0]
            )
            self.assertIsNone(
                cache.lookup_many(
                    ["https://example.test/a"], at=NOW + timedelta(days=1)
                )[0]
            )
            self.assertEqual(
                cache.lookup("https://example.test/a")["content_sha256"],
                saved["content_sha256"],
            )
            cache.path.write_text("[]", encoding="utf-8")
            with self.assertRaises(rp.PlanError):
                cache.lookup_many(["https://example.test/a"])

    def test_put_prunes_expired_and_bounds_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = rp.SourceCache(
                Path(temp) / "cache.json",
                {"institution": 1},
                clock=lambda: NOW,
                max_entries=2,
            )
            cache.put(
                "https://example.test/old",
                "old",
                ttl_class="institution",
                fetched_at=NOW - timedelta(days=2),
            )
            cache.put("https://example.test/a", "a", ttl_class="institution")
            self.assertEqual(len(cache.load()["entries"]), 1)
            for letter in "bc":
                cache.put(
                    "https://example.test/" + letter, letter, ttl_class="institution"
                )
            self.assertEqual(len(cache.load()["entries"]), 2)
            self.assertIsNotNone(cache.lookup("https://example.test/c"))

    def test_byte_entry_and_batch_limits_preserve_file(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = rp.SourceCache(
                Path(temp) / "cache.json",
                {"institution": 1},
                clock=lambda: NOW,
                max_bytes=2048,
                max_entries=2,
            )
            cache.put("https://example.test/a", "a", ttl_class="institution")
            before = cache.path.read_bytes()
            with self.assertRaises(rp.PlanError):
                cache.put(
                    "https://example.test/b",
                    "b",
                    ttl_class="institution",
                    metadata={"huge": "x" * 3000},
                )
            with self.assertRaises(rp.PlanError):
                cache.lookup_many(["https://example.test/a"] * 257)
            self.assertEqual(cache.path.read_bytes(), before)
            cache.path.write_bytes(b" " * 2049)
            with self.assertRaises(rp.PlanError):
                cache.load()
            cache.path.write_text(
                json.dumps(
                    {
                        "schema": "discovery-call-source-cache/v1",
                        "entries": {
                            str(i): {"expires_at": "2099-01-01T00:00:00Z"}
                            for i in range(3)
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(rp.PlanError):
                cache.load()

    def test_exact_persisted_byte_limit_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "cache.json"
            value = {"schema": "discovery-call-source-cache/v1", "entries": {}}
            size = len(
                (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                .replace("\n", os.linesep)
                .encode("utf-8")
            )
            cache = rp.SourceCache(p, {}, max_bytes=size)
            cache.save(value)
            self.assertEqual(p.stat().st_size, size)
            self.assertEqual(cache.load(), value)
            before = p.read_bytes()
            cache.max_bytes = size - 1
            with self.assertRaises(rp.PlanError):
                cache.save(value)
            self.assertEqual(p.read_bytes(), before)

    def test_invalid_limits_and_naive_time_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "cache.json"
            with self.assertRaises(rp.PlanError):
                rp.SourceCache(p, {}, max_bytes=0)
            cache = rp.SourceCache(p, {})
            with self.assertRaises(rp.PlanError):
                cache.lookup_many([], at=datetime(2026, 9, 7))


if __name__ == "__main__":
    unittest.main()
