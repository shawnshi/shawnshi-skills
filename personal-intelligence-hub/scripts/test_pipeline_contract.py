import json
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import refine
from run_contract import create_run, record_run_artifact, record_stage


class PipelineContractTests(unittest.TestCase):
    def test_refine_funnel_preserves_baseline_quarantine_and_conserves_raw(self):
        scan = {
            "items": [
                {"title": "AI agent", "url": "https://example.org/1", "source": "Example", "raw_desc": "AI agent"},
                {"title": "unrelated", "url": "https://example.org/2", "source": "Example", "raw_desc": "none"},
            ],
            "candidate_funnel": {
                "raw": 5,
                "dated": 4,
                "quarantined": 1,
                "within_window": 3,
                "outside_window": 1,
                "excluded": 1,
                "retained": 2,
            },
        }
        focus = {
            "domains": {
                "technology": {"keywords": [{"keyword": "AI agent", "weight": 8}], "priority_sources": {}},
                "healthcare_digital": {"keywords": [], "priority_sources": {}},
            },
            "filters": {"min_score_for_top10": 4, "max_candidates": 10, "dedupe_days": 7},
        }

        output = refine.heuristics(scan, focus, history_entries=[])

        funnel = output["candidate_funnel"]
        self.assertEqual(funnel["observed"], 5)
        self.assertEqual(funnel["retained_for_review"], 1)
        self.assertEqual(sum(funnel["terminal_dispositions"].values()), 5)
        self.assertEqual(funnel["terminal_dispositions"]["invalid_or_unknown_date"], 1)
        self.assertEqual(funnel["terminal_dispositions"]["outside_window"], 1)

    def test_refine_emits_candidates_only_and_never_writes_refined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_file = root / "SKILL.md"
            skill_file.write_text("skill", encoding="utf-8")
            (root / "resource-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "skill": root.name,
                        "skill_md": "SKILL.md",
                        "skill_md_sha256": hashlib.sha256(b"skill").hexdigest(),
                        "top_level_file_hashes": [],
                        "declared_local_dependencies": [],
                        "missing_declared_dependencies": [],
                    }
                ),
                encoding="utf-8",
            )
            latest_scan = root / "latest_scan.json"
            latest_scan.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-08-10T09:00:00+08:00",
                        "items": [
                            {
                                "title": "AI agent runtime released",
                                "url": "https://example.org/release",
                                "source": "Example",
                                "time": "2026-08-09T08:00:00+00:00",
                                "published_at_source": "rss_published",
                                "retrieved_at": "2026-08-10T09:00:00+08:00",
                                "raw_desc": "agent infrastructure",
                            }
                        ],
                        "metadata": {
                            "topic": "技术与医疗数字化",
                            "region": "中国、美国与全球",
                            "window": {
                                "start": "2026-08-04",
                                "end": "2026-08-10",
                                "timezone": "Asia/Shanghai",
                                "days": 7,
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            focus = root / "focus.json"
            focus.write_text(
                json.dumps(
                    {
                        "domains": {
                            "technology": {
                                "keywords": [{"keyword": "AI agent", "weight": 8}],
                                "priority_sources": {},
                            },
                            "healthcare_digital": {"keywords": [], "priority_sources": {}},
                        },
                        "filters": {"min_score_for_top10": 0, "max_top10": 10, "dedupe_days": 7},
                    }
                ),
                encoding="utf-8",
            )
            candidates = root / "candidates.json"
            refined = root / "refined.json"
            now = datetime(2026, 8, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            manifest_path, _ = create_run(
                runtime_dir=root,
                skill_path=skill_file,
                report_date="2026-08-10",
                now=now,
                run_id="run-refine",
            )
            record_stage(manifest_path, "baseline", "completed", artifact_path=latest_scan, now=now)
            history = root / "history.json"
            history.write_text(
                json.dumps(
                    {
                        "resource_kind": "pih_history_index",
                        "schema_version": "2.0",
                        "generated_at": now.isoformat(),
                        "entries": [],
                    }
                ),
                encoding="utf-8",
            )
            record_run_artifact(
                manifest_path, "history_snapshot", history, now=now
            )

            with (
                patch.object(refine, "LATEST_SCAN_PATH", latest_scan),
                patch.object(refine, "CANDIDATES_PATH", candidates),
                patch.object(refine, "REFINED_PATH", refined),
                patch.object(refine, "update_phase"),
                patch.object(refine, "ensure_runtime_dirs"),
            ):
                refine.refine(focus_path=focus, min_score=0, manifest_path=manifest_path)

            output = json.loads(candidates.read_text(encoding="utf-8"))

        self.assertEqual(output["artifact_kind"], "candidates_only")
        self.assertEqual(output["review_status"], "unreviewed")
        self.assertEqual(output["model_used"], "heuristic")
        self.assertEqual(output["run_id"], "run-refine")
        self.assertNotIn("intelligence_level", output["items"][0])
        self.assertFalse(refined.exists())


if __name__ == "__main__":
    unittest.main()
