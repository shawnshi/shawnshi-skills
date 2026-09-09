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
    _candidate_projection,
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

    def test_legacy_URL_access_does_not_authorize_bare_pool(self) -> None:
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

        self.assertEqual(eligible, [])
        self.assertEqual(
            {item["candidate_id"]: item["reason"] for item in dispositions},
            {
                verified["candidate_id"]: "missing_verified_access",
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
    def _assemble(self, candidate: dict | None = None, identity: dict | None = None, dynamic_overrides: dict | None = None) -> dict:
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
            pool: dict[str, Any] = {
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
            eligible = []
            dispositions = []
            if candidate is not None:
                pool["items"] = [candidate]
                pool["candidate_funnel"].update(observed=1, retained_for_review=1)
                pool["candidate_funnel"]["terminal_dispositions"]["retained_for_review"] = 1
                dispositions = [{
                    "candidate_id": candidate["candidate_id"], "url": candidate["url"],
                    "source_type": "primary", "reason": "eligible",
                }]
                eligible = [_candidate_projection(
                    {"candidate": candidate, "access_check": _access(candidate["url"])},
                    candidate_refs=[candidate["candidate_id"]],
                    corroboration_status="single_primary",
                )]
                dynamic["selected_items"] = [{
                    "candidate_id": candidate["candidate_id"],
                    "event_identity": identity,
                    "title_zh": "已核验政策通知",
                    "fact": "文件早于网页发布。",
                    "connection": "支付系统适配要求。",
                    "deduction": "核对本地适用范围。",
                    "actionability": "由医保部门核对实施期限。",
                    "intelligence_level": "L2",
                    "confidence": "high",
                    "summary_zh": "保留原始事件日期与发布日期。",
                    "major_signal": False,
                    "major_signal_reason": "none",
                    "near_term_decision_impact": False,
                    "decision_impact_reason": "none",
                }]
            if dynamic_overrides:
                dynamic.update(dynamic_overrides)
            artifacts = {
                "candidate_pool": (root / "pool.json", pool),
                "supplement": (root / "supplement.json", supplement),
            }
            with (
                patch(
                    "semantic_agent._load_packet",
                    return_value=(root / "request.json", request, packet, manifest),
                ),
                patch("semantic_agent._candidate_assessment", return_value=(eligible, dispositions)),
                patch("semantic_agent.registered_coverage_diagnostics", side_effect=lambda value:
                      __import__("semantic_agent")._coverage_diagnostics(value, pool, supplement, dispositions, {})),
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
            return core

    def test_empty_selection_produces_zero_item_core(self) -> None:
        from zero_report import zero_report_fields, zero_supply_gap

        malicious: dict[str, Any] = dict.fromkeys(zero_report_fields(), "Market silence; no innovations")
        malicious["action_levers"] = []
        core = self._assemble(dynamic_overrides=malicious)
        for field, expected in zero_report_fields().items():
            self.assertEqual(core[field], expected)
        self.assertIn(zero_supply_gap(), core["data_gaps"])
        self.assertTrue(any(gap["description"] == "source unavailable" for gap in core["data_gaps"]))
        self.assertEqual(core["top_10"], [])
        self.assertEqual(core["candidate_funnel"]["terminal_dispositions"]["retained"], 0)

    def _dated_candidate(self, event_day: str | int = "2026-08-31") -> tuple[dict, dict]:
        identity = {
            "key_version": "v1", "primary_domain": "healthcare_digital",
            "actor": "国家医疗保障局", "action": "印发",
            "object": "分组方案实施通知", "event_date": event_day,
        }
        candidate = _candidate("https://example.org/policy", event_identity=identity)
        candidate["published_at"] = "2026-09-02"
        return candidate, identity

    def test_registered_event_date_precedes_publication_and_is_preserved(self) -> None:
        candidate, identity = self._dated_candidate()
        item = self._assemble(candidate, identity)["top_10"][0]
        self.assertEqual(item["published_at"], "2026-09-02")
        self.assertEqual(item["event_date"], "2026-08-31")
        self.assertEqual(item["event_date"], item["event_identity"]["event_date"])
        self.assertEqual(item["event_date_source"], "event_identity.event_date")

    def test_explicit_event_date_and_provenance_are_preserved(self) -> None:
        candidate, identity = self._dated_candidate()
        candidate.pop("event_identity")
        candidate.update(event_date="2026-08-31", event_date_source="signed notice")
        item = self._assemble(candidate, identity)["top_10"][0]
        self.assertEqual(item["event_date"], "2026-08-31")
        self.assertEqual(item["event_date_source"], "signed notice")

    def test_missing_event_evidence_keeps_publication_fallback(self) -> None:
        candidate, identity = self._dated_candidate("2026-09-02")
        candidate.pop("event_identity")
        item = self._assemble(candidate, identity)["top_10"][0]
        self.assertEqual(item["event_date"], "2026-09-02")
        self.assertEqual(item["event_date_source"], "published_at")

    def test_model_cannot_replace_registered_event_date_with_publication(self) -> None:
        candidate, identity = self._dated_candidate()
        with self.assertRaisesRegex(RunContractError, "identity does not match evidence"):
            self._assemble(candidate, {**identity, "event_date": "2026-09-02"})

    def test_future_or_invalid_registered_event_dates_are_rejected(self) -> None:
        for event_day in ("2026-09-03", "2026-02-30", "20260831", "unknown", "", 20260831):
            with self.subTest(event_day=event_day):
                candidate, identity = self._dated_candidate(event_day)
                with self.assertRaises(RunContractError):
                    self._assemble(candidate, identity)

    def test_conflicting_registered_event_dates_are_rejected(self) -> None:
        candidate, identity = self._dated_candidate()
        candidate.update(event_date="2026-09-01", event_date_source="source page")
        with self.assertRaisesRegex(RunContractError, "conflicting event dates"):
            self._assemble(candidate, identity)


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


class CoverageDiagnosticsTests(unittest.TestCase):
    def fixture(self):
        from semantic_agent import _coverage_diagnostics

        manifest: dict[str, Any] = {"stages": {"baseline": {"metadata": {"coverage": {
            "source_attempted": 123, "source_succeeded": 88, "source_failed": 35,
        }}}}}
        pool: dict[str, Any] = {"items": [{"url": f"https://example.org/{index}"} for index in range(17)]}
        logs = [{"requested_url": f"https://example.org/{index}",
                 "status": "verified" if index < 2 else "blocked"}
                for index in [0, 1, 2, 3, 4, 4, 4]]
        supplement = {"results": [{"gap_id": "tech", "access_log": logs,
            "executed_queries": ["actual query"], "coverage": {"succeeded": 999},
            "bound_candidate_decisions": [{"decision": "source_quality_rejected"},
                {"decision": "access_blocked"}, {"decision": "date_disqualified"}]}]}
        dispositions = [{"reason": "missing_verified_access"}] * 16 + [{"reason": "duplicate_candidate_id"}]
        request = {"gaps": [{"gap_id": "tech", "max_queries": 2, "max_urls": 8}]}
        return _coverage_diagnostics, manifest, pool, supplement, dispositions, request

    def test_feed_article_pool_and_quality_are_distinct(self):
        helper, *inputs = self.fixture()
        reasons = "\n".join(helper(*inputs))
        self.assertIn("feed: attempts=123; succeeded=88; failed=35", reasons)
        self.assertIn("article: attempts=7; completed=7; verified=2; blocked=5; pending=0", reasons)
        self.assertIn("pool-urls: unique=17; attempted=5; unattempted=12", reasons)
        self.assertIn("source_quality_rejected=1; access_blocked=1; date_disqualified=1", reasons)
        self.assertIn("access_or_ownership_excluded=16; date_excluded=0; duplicate_records=1", reasons)
        self.assertIn("unused_queries=1; unused_urls=1", reasons)
        self.assertNotIn("999", reasons)
        from forge import render_briefing
        from test_contract_fixtures import cloned_v14_payload

        payload = cloned_v14_payload()
        payload["coverage"].update(source_attempted=130, source_succeeded=90, source_failed=40,
                                   source_success_rate=90 / 130, reasons=reasons.splitlines())
        markdown = render_briefing(payload)
        self.assertIn("非已核验文章数）：尝试 130 / 成功 90 / 失败 40", markdown)
        self.assertIn("diagnostic/feed: attempts=123; succeeded=88", markdown)
        self.assertIn("diagnostic/article: attempts=7; completed=7; verified=2", markdown)
        self.assertNotIn("verified=90", markdown)

    def test_owned_metadata_exclusion_is_not_missing_access_or_quality(self):
        helper, manifest, pool, supplement, dispositions, request = self.fixture()
        pool["items"][0]["access_check"] = {"status": "verified"}
        reasons = "\n".join(helper(manifest, pool, supplement, dispositions, request))
        self.assertIn("missing_access_evidence=15; ownership_excluded=1", reasons)
        self.assertIn("source_quality_rejected=1", reasons)

    def test_broker_reservations_count_pending_and_unused_budgets(self):
        helper, manifest, pool, _, dispositions, _ = self.fixture()
        manifest["article_broker_evidence"] = {"medical": {"events": [
            {"kind": "query_reserved", "query": "hospital policy"},
            {"kind": "query_recorded"},
            {"kind": "http_reserved", "url": "https://example.org/0"},
        ]}}
        reasons = "\n".join(helper(manifest, pool, {"results": []}, dispositions,
            {"gaps": [{"gap_id": "medical", "max_queries": 2, "max_urls": 4}]}))
        self.assertIn("attempts=1; completed=0; verified=0; blocked=0; pending=1", reasons)
        self.assertIn("unique=17; attempted=1; unattempted=16", reasons)
        self.assertIn("unused_queries=1; unused_urls=3", reasons)

    def test_diagnostics_do_not_reclassify_conserved_v14_funnel(self):
        pool = {"candidate_funnel": {"observed": 17, "retained_for_review": 17,
            "terminal_dispositions": {"retained_for_review": 17}}}
        dispositions = [{"candidate_id": str(index), "reason": "missing_verified_access"}
                        for index in range(16)] + [{"candidate_id": "dup", "reason": "duplicate_candidate_id"}]
        funnel = _candidate_funnel(pool, 0, [], set(), dispositions)
        self.assertEqual(funnel["terminal_dispositions"]["below_quality_gate"], 17)
        self.assertEqual(sum(funnel["terminal_dispositions"].values()), 17)
        self.assertEqual(funnel["quality_gate_reasons"], {"missing_verified_access": 16, "duplicate_candidate_id": 1})

    def test_supplied_diagnostics_must_be_complete_exact_and_unique(self):
        from semantic_agent import validate_coverage_reasons

        helper, manifest, pool, supplement, dispositions, request = self.fixture()
        canonical = helper(manifest, pool, supplement, dispositions, request)
        with patch("semantic_agent.registered_coverage_diagnostics", return_value=canonical):
            validate_coverage_reasons(["legacy"], ["legacy"], {})
            validate_coverage_reasons(["legacy"] + canonical, ["legacy"], {})
            for supplied in (canonical[:-1], canonical + canonical[:1],
                             [canonical[0].replace("88", "90")] + canonical[1:],
                             ["diagnostic/spoof: verified=90"], [" diagnostic/feed: malformed"]):
                with self.subTest(supplied=supplied), self.assertRaisesRegex(RunContractError, "coverage.reasons"):
                    validate_coverage_reasons(["legacy"] + supplied, ["legacy"], {})


if __name__ == "__main__":
    unittest.main()
