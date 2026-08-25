import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from history_manager import load_recent_history
from run_contract import item_hash
from test_contract_fixtures import (
    valid_v12_payload,
    valid_v13_payload,
    valid_v14_payload,
)
from update_index import rebuild_history


def _write_verified_triplet(news: Path, payload: dict) -> tuple[Path, Path, Path]:
    compact_date = str(payload["report_date"]).replace("-", "")
    stem = news / f"intelligence_{compact_date}_briefing"
    json_path = stem.with_suffix(".json")
    markdown_path = stem.with_suffix(".md")
    manifest_path = news / f"{stem.name}.manifest.json"
    news.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text("# Verified briefing\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "contract_version": "1.0",
                "run_id": payload["run_id"],
                "report_date": payload["report_date"],
                "schema_version": payload["schema_version"],
                "json_file": json_path.name,
                "markdown_file": markdown_path.name,
                "json_sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
                "markdown_sha256": hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
                "item_count": len(payload["top_10"]),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return json_path, markdown_path, manifest_path


class UpdateIndexTests(unittest.TestCase):
    def test_history_rebuild_ignores_uncommitted_archive_staging(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            staging = news / ".pih-stage-interrupted"
            staging.mkdir(parents=True)
            history = root / "history.json"
            staged_archive = staging / "intelligence_20260811_briefing.json"
            staged_archive.write_text(
                json.dumps(
                    {
                        "schema_version": "1.3",
                        "report_date": "2026-08-11",
                        "generated_at": "2026-08-11T09:00:00+08:00",
                        "top_10": [
                            {
                                "url": "https://uncommitted.example/event",
                                "title": "Uncommitted staged event",
                                "source": "Staging",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = rebuild_history(news_dir=news, history_file=history, now=now)

        self.assertEqual(payload["entries"], [])

    def test_history_rebuild_accepts_gate_valid_v13_commit_triplet(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            history = news / ".pih_history_v2.json"
            payload = valid_v13_payload()
            _write_verified_triplet(news, payload)

            rebuilt = rebuild_history(news_dir=news, history_file=history, now=now)

        self.assertEqual(len(rebuilt["entries"]), 1)
        self.assertEqual(rebuilt["entries"][0]["event_id"], payload["top_10"][0]["event_id"])

    def test_history_rebuild_accepts_gate_valid_v14_commit_triplet(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            history = news / ".pih_history_v2.json"
            payload = valid_v14_payload()
            _write_verified_triplet(news, payload)

            rebuilt = rebuild_history(news_dir=news, history_file=history, now=now)

        self.assertEqual(len(rebuilt["entries"]), 1)
        self.assertEqual(rebuilt["entries"][0]["event_id"], payload["top_10"][0]["event_id"])

    def test_history_rebuild_rejects_v14_boolean_funnel_count_with_gate_error(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            history = news / ".pih_history_v2.json"
            payload = valid_v14_payload()
            payload["candidate_funnel"]["terminal_dispositions"]["retained"] = True
            _write_verified_triplet(news, payload)

            with self.assertRaisesRegex(
                RuntimeError,
                "candidate_funnel\\.terminal_dispositions must contain "
                "non-negative integers",
            ):
                rebuild_history(news_dir=news, history_file=history, now=now)

            self.assertFalse(history.exists())

    def test_history_rebuild_accepts_legacy_v10_json_and_markdown_without_sidecar(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = news / ".pih_history_v2.json"
            payload = valid_v12_payload()
            payload["schema_version"] = "1.0"
            archive = news / "intelligence_20260810_briefing.json"
            archive.write_text(json.dumps(payload), encoding="utf-8")
            archive.with_suffix(".md").write_text(
                "# Legacy briefing\n\nhttps://example.org/source\n",
                encoding="utf-8",
            )

            rebuilt = rebuild_history(news_dir=news, history_file=history, now=now)

        self.assertEqual(len(rebuilt["entries"]), 1)
        self.assertEqual(rebuilt["entries"][0]["event_id"], payload["top_10"][0]["event_id"])

    def test_history_rebuild_accepts_legacy_v10_without_report_identity_fields(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = news / ".pih_history_v2.json"
            payload = valid_v12_payload()
            payload["schema_version"] = "1.0"
            del payload["report_date"]
            del payload["run_id"]
            archive = news / "intelligence_20260810_briefing.json"
            archive.write_text(json.dumps(payload), encoding="utf-8")
            archive.with_suffix(".md").write_text(
                "# Legacy briefing without report identity\n",
                encoding="utf-8",
            )

            rebuilt = rebuild_history(news_dir=news, history_file=history, now=now)

        self.assertEqual(len(rebuilt["entries"]), 1)
        self.assertEqual(rebuilt["entries"][0]["event_id"], payload["top_10"][0]["event_id"])
        self.assertEqual(rebuilt["entries"][0]["last_seen_at"], payload["generated_at"])

    def test_legacy_without_report_date_requires_a_canonical_filename_date(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = news / ".pih_history_v2.json"
            payload = valid_v12_payload()
            payload["schema_version"] = "1.0"
            del payload["report_date"]
            del payload["run_id"]
            archive = news / "intelligence_20261340_briefing.json"
            archive.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "canonical filename date"):
                rebuild_history(news_dir=news, history_file=history, now=now)

            self.assertFalse(history.exists())

    def test_history_rebuild_rejects_v13_without_formal_triplet(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = news / ".pih_history_v2.json"
            payload = valid_v13_payload()
            archive = news / "intelligence_20260810_briefing.json"
            archive.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "formal triplet is incomplete"):
                rebuild_history(news_dir=news, history_file=history, now=now)

        self.assertFalse(history.exists())

    def test_history_rebuild_rejects_v14_without_formal_triplet(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = news / ".pih_history_v2.json"
            payload = valid_v14_payload()
            archive = news / "intelligence_20260810_briefing.json"
            archive.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "formal triplet is incomplete"):
                rebuild_history(news_dir=news, history_file=history, now=now)

            self.assertFalse(history.exists())

    def test_history_rebuild_rejects_sidecar_hash_mismatch(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            history = news / ".pih_history_v2.json"
            _, _, manifest_path = _write_verified_triplet(news, valid_v13_payload())
            sidecar = json.loads(manifest_path.read_text(encoding="utf-8"))
            sidecar["json_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(sidecar), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "JSON hash"):
                rebuild_history(news_dir=news, history_file=history, now=now)

            self.assertFalse(history.exists())

    def test_history_rebuild_rejects_corrupt_or_gate_invalid_formal_json(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        cases = (
            ("{not-json", "cannot read formal archive"),
            (json.dumps({"schema_version": "1.2", "top_10": []}), "briefing gate failed"),
        )
        for content, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                news = root / "news"
                news.mkdir()
                history = news / ".pih_history_v2.json"
                archive = news / "intelligence_20260810_briefing.json"
                archive.write_text(content, encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, expected):
                    rebuild_history(news_dir=news, history_file=history, now=now)

                self.assertFalse(history.exists())

    def test_history_rebuild_avoids_temporary_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            news.mkdir()
            history = root / "state" / "history.json"
            with patch(
                "tempfile.TemporaryDirectory",
                side_effect=AssertionError("temporary directories are sandbox-hostile"),
            ):
                rebuild_history(news_dir=news, history_file=history)

            self.assertTrue(history.is_file())
            self.assertEqual(list(history.parent.glob(".*.rebuild")), [])

    def test_json_archives_rebuild_v2_history_idempotently_without_rewrite(self):
        now = datetime(2026, 8, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            news = root / "news"
            nested = news / "archive"
            nested.mkdir(parents=True)
            history = root / "history.json"
            first = news / "intelligence_20260809_briefing.json"
            second = nested / "intelligence_20260810_briefing.json"
            first_payload = valid_v12_payload()
            event_id = first_payload["top_10"][0]["event_id"]
            first_payload["report_date"] = "2026-08-09"
            first_payload["generated_at"] = "2026-08-09T09:00:00+08:00"
            first_payload["window"].update({"start": "2026-08-03", "end": "2026-08-09"})
            first_item = first_payload["top_10"][0]
            first_item["observed_at"] = "2026-08-09T09:00:00+08:00"
            first_item["retrieved_at"] = "2026-08-09T09:00:00+08:00"
            first_item["access_check"]["checked_at"] = "2026-08-09T09:00:00+08:00"
            first_hash = item_hash(first_item)
            first_payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
                first_hash
            ]
            first_payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
                "output_item_sha256"
            ] = first_hash
            second_payload = deepcopy(first_payload)
            second_payload["report_date"] = "2026-08-10"
            second_payload["generated_at"] = "2026-08-10T09:00:00+08:00"
            second_payload["window"].update({"start": "2026-08-04", "end": "2026-08-10"})
            first.write_text(json.dumps(first_payload), encoding="utf-8")
            second.write_text(json.dumps(second_payload), encoding="utf-8")
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
        self.assertEqual(len(entries[0]["urls"]), 1)
        self.assertEqual(entries[0]["first_seen_at"], "2026-08-09T09:00:00+08:00")
        self.assertEqual(entries[0]["last_seen_at"], "2026-08-10T09:00:00+08:00")
        self.assertIn('"generated_at": "2026-08-12T10:00:00+08:00"', once.decode("utf-8"))

    def test_legacy_archive_without_contract_fields_is_rejected_not_redated(self):
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

            with self.assertRaisesRegex(RuntimeError, "briefing gate failed"):
                rebuild_history(news_dir=news, history_file=history, now=now)

            self.assertFalse(history.exists())


if __name__ == "__main__":
    unittest.main()
