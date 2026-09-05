# pyright: reportMissingImports=false
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from run_contract import (  # pyright: ignore[reportMissingImports]
    RunContractError,
    candidate_object_hash,
    candidate_ref,
)
from semantic_agent import (  # pyright: ignore[reportMissingImports]
    _candidate_assessment,
    _candidate_funnel,
    _date_failure_disqualifies,
    assemble_and_finalize,
)


def _candidate(
    url: str,
    *,
    source: str = "Example",
    source_type: str = "primary",
    event_identity: dict | None = None,
) -> dict:
    value: dict[str, Any] = {
        "candidate_id": candidate_ref(url),
        "title": "Clinical evidence update",
        "url": url,
        "source": source,
        "published_at": "2026-08-31",
        "published_at_source": "source page",
        "primary_domain": "healthcare_digital",
        "source_type": source_type,
        "summary": "New evidence was published.",
    }
    if event_identity is not None:
        value["event_identity"] = event_identity
    value["candidate_object_sha256"] = candidate_object_hash(value)
    return value


def _access(url: str) -> dict:
    return {
        "status": "verified",
        "checked_at": "2026-08-31T01:00:00+00:00",
        "method": "http_get",
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
    }


class SemanticAgentCandidateTests(unittest.TestCase):
    manifest = {
        "report_date": "2026-08-31",
        "timezone": "Asia/Shanghai",
        "artifacts": {"history_snapshot": {"metadata": {"dedupe_days": 7}}},
    }

    def _assess(self, pool: dict, supplement: dict):
        artifacts = {
            "candidate_pool": (Path("candidate_pool.json"), pool),
            "supplement": (Path("supplement.json"), supplement),
            "history_snapshot": (Path("history.json"), {}),
        }
        with (
            patch(
                "semantic_agent._bound_artifact",
                side_effect=lambda _request, name: artifacts[name],
            ),
            patch("semantic_agent.load_recent_history", return_value=[]),
            patch("semantic_agent.match_history", return_value={"redundant": False}),
        ):
            return _candidate_assessment({}, self.manifest)

    def test_assessment_distinguishes_missing_access_from_eligible(self) -> None:
        verified = _candidate("https://example.org/verified")
        unverified = _candidate("https://example.org/unverified")
        pool = {"items": [verified, unverified]}
        supplement = {
            "results": [
                {
                    "failure_kind": None,
                    "access_log": [_access(verified["url"])],
                    "candidates": [],
                }
            ]
        }

        eligible, dispositions = self._assess(pool, supplement)

        self.assertEqual([item["candidate_id"] for item in eligible], [verified["candidate_id"]])
        self.assertEqual(
            {item["candidate_id"]: item["reason"] for item in dispositions},
            {
                verified["candidate_id"]: "eligible",
                unverified["candidate_id"]: "missing_verified_access",
            },
        )

    def test_article_level_projection_wins_over_matching_heuristic_record(self) -> None:
        url = "https://vendor.example/official-release"
        heuristic = _candidate(url, source="Vendor blog")
        heuristic.pop("source_type")
        heuristic["candidate_object_sha256"] = candidate_object_hash(heuristic)
        enriched = _candidate(url, source="Vendor", source_type="primary")
        enriched["access_check"] = _access(url)
        enriched["candidate_object_sha256"] = candidate_object_hash(enriched)
        supplement = {
            "results": [
                {
                    "failure_kind": None,
                    "access_log": [enriched["access_check"]],
                    "candidates": [enriched],
                }
            ]
        }

        eligible, dispositions = self._assess({"items": [heuristic]}, supplement)

        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["source_type"], "primary")
        self.assertEqual(
            [record["reason"] for record in dispositions],
            ["eligible", "duplicate_candidate_id"],
        )

    def test_two_independent_secondary_sources_form_one_eligible_group(self) -> None:
        identity = {
            "key_version": "1",
            "primary_domain": "healthcare_digital",
            "actor": "Hospital",
            "action": "reported",
            "object": "clinical evidence update",
            "event_date": "2026-08-31",
        }
        first = _candidate(
            "https://news-a.example/report",
            source="News A",
            source_type="secondary",
            event_identity=identity,
        )
        second = _candidate(
            "https://news-b.example/report",
            source="News B",
            source_type="secondary",
            event_identity=identity,
        )
        for candidate in (first, second):
            candidate["access_check"] = _access(candidate["url"])
            candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        supplement = {
            "results": [
                {
                    "failure_kind": None,
                    "access_log": [first["access_check"], second["access_check"]],
                    "candidates": [first, second],
                }
            ]
        }

        eligible, dispositions = self._assess({"items": []}, supplement)

        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["source_type"], "secondary")
        self.assertEqual(eligible[0]["corroboration_status"], "multi_independent")
        self.assertEqual(
            eligible[0]["candidate_refs"],
            [first["candidate_id"], second["candidate_id"]],
        )
        self.assertEqual({item["reason"] for item in dispositions}, {"eligible"})

    def test_funnel_preserves_per_candidate_terminal_reasons(self) -> None:
        eligible = [
            {
                "candidate_id": "candidate-primary",
                "candidate_refs": ["candidate-primary", "candidate-corroborating"],
            }
        ]
        dispositions = [
            {"candidate_id": "candidate-primary", "url": "a", "source_type": "secondary", "reason": "eligible"},
            {"candidate_id": "candidate-corroborating", "url": "b", "source_type": "secondary", "reason": "eligible"},
            {"candidate_id": "candidate-unverified", "url": "c", "source_type": "primary", "reason": "missing_verified_access"},
        ]
        pool = {
            "candidate_funnel": {
                "observed": 10,
                "retained_for_review": 2,
                "terminal_dispositions": {
                    "invalid_date": 8,
                    "retained_for_review": 2,
                },
            }
        }

        funnel = _candidate_funnel(
            pool,
            supplemental_count=1,
            eligible=eligible,
            selected_candidate_ids={"candidate-primary"},
            dispositions=dispositions,
        )

        self.assertEqual(funnel["terminal_dispositions"]["retained"], 1)
        self.assertEqual(funnel["terminal_dispositions"]["semantic_duplicate"], 1)
        self.assertEqual(funnel["terminal_dispositions"]["below_quality_gate"], 1)
        self.assertEqual(
            funnel["quality_gate_reasons"],
            {"missing_verified_access": 1},
        )
        self.assertEqual(
            [item["reason"] for item in funnel["candidate_dispositions"]],
            ["retained", "semantic_duplicate", "missing_verified_access"],
        )


class SemanticAgentFinalizeTests(unittest.TestCase):
    def test_empty_selection_produces_zero_item_core(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core_path = root / "refined.json"
            decision_path = root / "decision.json"
            request = {"max_turns": 2}
            packet = {
                "draft_paths": {
                    "refined_core": str(core_path),
                    "decision": str(decision_path),
                },
                "run_manifest_path": str(root / "manifest.json"),
            }
            manifest = {
                "run_id": "run-empty",
                "report_date": "2026-09-05",
                "timezone": "Asia/Shanghai",
                "topic": "技术与医疗数字化",
                "region": "中国、美国与全球",
                "window": {
                    "mode": "calendar",
                    "days": 7,
                    "start": "2026-08-30",
                    "end": "2026-09-05",
                    "timezone": "Asia/Shanghai",
                },
                "mix_request": {
                    "schema_default_ratio": {
                        "technology": 0.6,
                        "healthcare_digital": 0.4,
                    },
                    "requested_ratio": {
                        "technology": 0.6,
                        "healthcare_digital": 0.4,
                    },
                    "ratio_source": "schema_default",
                    "ratio_reason": "none",
                    "max_ratio_shift": 0.2,
                },
                "stages": {
                    "baseline": {
                        "status": "degraded",
                        "metadata": {
                            "coverage": {
                                "source_attempted": 1,
                                "source_succeeded": 0,
                                "source_failed": 1,
                                "raw_candidates": 0,
                                "dated_candidates": 0,
                                "reasons": ["source unavailable"],
                            }
                        },
                    },
                    "supplemental": {"status": "degraded"},
                },
            }
            pool = {
                "candidate_funnel": {
                    "observed": 0,
                    "retained_for_review": 0,
                    "terminal_dispositions": {"retained_for_review": 0},
                }
            }
            supplement = {
                "coverage": {"attempted": 0, "succeeded": 0, "failed": 0},
                "results": [],
            }
            dynamic = {
                "contract_version": "semantic-dynamic/1.0",
                "status": "passed",
                "turns_used": 1,
                "halt_condition_met": True,
                "punchline": "本窗口没有证据充分的正式条目。",
                "insights": "补检失败导致可核验供给为空。",
                "digest": "不使用弱信号补数。",
                "market": "当前无法形成可靠市场判断。",
                "action_levers": [
                    {
                        "domain": "coverage",
                        "task": "恢复来源核验后重跑",
                        "owner_type": "情报运营",
                        "trigger": "补检通路恢复",
                        "indicator": "至少一条候选通过访问和日期门禁",
                    }
                ],
                "selected_items": [],
            }
            artifacts = {
                "candidate_pool": (root / "pool.json", pool),
                "supplement": (root / "supplement.json", supplement),
            }
            with (
                patch(
                    "semantic_agent._load_packet",
                    return_value=(root / "request.json", request, packet, manifest),
                ),
                patch("semantic_agent._candidate_assessment", return_value=([], [])),
                patch(
                    "semantic_agent._bound_artifact",
                    side_effect=lambda _request, name: artifacts[name],
                ),
                patch(
                    "semantic_agent.finalize_semantic_decision",
                    return_value=(core_path, decision_path),
                ),
            ):
                result = assemble_and_finalize(root / "request.json", dynamic)

            core = json.loads(core_path.read_text(encoding="utf-8"))
            self.assertEqual(result, (core_path, decision_path))
            self.assertEqual(core["top_10"], [])
            self.assertEqual(core["candidate_funnel"]["terminal_dispositions"]["retained"], 0)


class SemanticAgentDateFailureTests(unittest.TestCase):
    def test_date_conflict_failure_kind_variants_disqualify(self) -> None:
        for failure_kind in (
            "published_at_conflict",
            "publication_date_conflict",
        ):
            with self.subTest(failure_kind=failure_kind):
                self.assertTrue(
                    _date_failure_disqualifies({"failure_kind": failure_kind})
                )

    def test_unknown_failure_kind_is_rejected_without_reason_inference(self) -> None:
        with self.assertRaisesRegex(RunContractError, "failure_kind is invalid"):
            _date_failure_disqualifies(
                {
                    "failure_kind": "source_metadata_mismatch",
                    "failure_reason": (
                        "The authoritative published date is outside the requested window."
                    ),
                }
            )

    def test_non_date_failure_does_not_disqualify(self) -> None:
        self.assertFalse(
            _date_failure_disqualifies(
                {
                    "failure_kind": "infrastructure",
                    "failure_reason": "The upstream source returned HTTP 503.",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
