import unittest
from copy import deepcopy
from typing import Any

from briefing_gate import validate_briefing_data
from history_manager import generate_content_id, generate_event_id
from mix_policy import select_candidates_with_mix
from run_contract import candidate_ref, item_hash
from test_contract_fixtures import (
    cloned_v12_payload,
    cloned_v13_payload,
    cloned_v14_payload,
)


def _bind_two_item_payload(payload: dict, second: dict) -> None:
    payload["top_10"] = [payload["top_10"][0], second]
    hashes = [item_hash(item) for item in payload["top_10"]]
    payload["pipeline"]["semantic_review"].update(
        {
            "verified_access_count": 2,
            "reviewed_item_hashes": hashes,
            "lineage_bindings": [
                {
                    "output_item_sha256": item_hash(item),
                    "inputs": [
                        {
                            "candidate_ref": item["candidate_refs"][0],
                            "candidate_object_sha256": "e" * 64,
                        }
                    ],
                }
                for item in payload["top_10"]
            ],
        }
    )
    payload["candidate_funnel"]["terminal_dispositions"] = {
        "retained": 2,
        "below_quality_gate": 1,
    }
    payload["mix"].update(
        {
            "target_counts": {"technology": 1, "healthcare_digital": 1},
            "actual_counts": {"technology": 0, "healthcare_digital": 2},
            "supply_exception": {
                "applied": True,
                "reason": "合格候选不足：technology",
                "missing_domains": ["technology"],
            },
        }
    )


def _distinct_semantic_item(first: dict, *, url: str, title: str) -> dict:
    second = deepcopy(first)
    identity = dict(second["event_identity"])
    identity["action"] = "updated"
    second.update(
        {
            "event_identity": identity,
            "event_id": generate_event_id(identity),
            "url": url,
            "title": title,
            "title_zh": title,
            "candidate_refs": [candidate_ref(url)],
        }
    )
    second["access_check"].update({"requested_url": url, "final_url": url})
    return second


class BriefingV14ContractTests(unittest.TestCase):
    def test_valid_v13_payload_passes(self):
        errors, _ = validate_briefing_data(cloned_v13_payload())

        self.assertEqual(errors, [])

    def test_frozen_v13_does_not_apply_v14_pipeline_or_funnel_gates(self):
        payload = cloned_v13_payload()
        del payload["pipeline"]["red_team"]["covered_item_hashes"]
        payload["candidate_funnel"]["terminal_dispositions"] = {
            "retained": 1,
            "legacy_custom_disposition": 2,
        }

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_frozen_v13_preserves_boolean_integer_compatibility(self):
        payload = cloned_v13_payload()
        payload["pipeline"]["semantic_review"]["turns_used"] = True
        payload["pipeline"]["semantic_review"]["verified_access_count"] = True
        payload["pipeline"]["red_team"]["turns_used"] = True
        payload["candidate_funnel"] = {
            "observed": True,
            "terminal_dispositions": {"retained": True},
        }

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_v14_rejects_boolean_values_for_all_integer_contract_fields(self):
        cases = (
            (("window", "days"), "window.days must be a positive integer"),
            (
                ("pipeline", "semantic_review", "turns_used"),
                "pipeline.semantic_review.turns_used must be positive",
            ),
            (
                ("pipeline", "semantic_review", "verified_access_count"),
                "pipeline.semantic_review.verified_access_count is invalid",
            ),
            (
                ("pipeline", "red_team", "turns_used"),
                "pipeline.red_team.turns_used must be positive",
            ),
            (
                ("top_10", 0, "access_check", "http_status"),
                "top_10[0].access_check.http_status must show successful access",
            ),
            (
                ("mix", "target_counts", "technology"),
                "mix.target_counts must contain non-negative integers",
            ),
            (
                ("mix", "actual_counts", "healthcare_digital"),
                "mix.actual_counts must contain non-negative integers",
            ),
            (
                ("coverage", "source_attempted"),
                "coverage source counts must be non-negative integers",
            ),
            (
                ("coverage", "source_succeeded"),
                "coverage source counts must be non-negative integers",
            ),
            (
                ("coverage", "source_failed"),
                "coverage source counts must be non-negative integers",
            ),
            (
                ("candidate_funnel", "observed"),
                "candidate_funnel.observed must be a non-negative integer",
            ),
            (
                ("candidate_funnel", "terminal_dispositions", "retained"),
                "candidate_funnel.terminal_dispositions must contain non-negative integers",
            ),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                payload = cloned_v14_payload()
                target: Any = payload
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = True
                if path[0] == "top_10":
                    digest = item_hash(payload["top_10"][0])
                    payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
                        digest
                    ]
                    payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
                        "output_item_sha256"
                    ] = digest

                errors, _ = validate_briefing_data(payload)

                self.assertIn(expected, errors)

    def test_v14_integer_one_reaches_funnel_conservation_contract(self):
        payload = cloned_v14_payload()
        payload["candidate_funnel"]["observed"] = 1

        errors, _ = validate_briefing_data(payload)

        self.assertNotIn(
            "candidate_funnel.observed must be a non-negative integer",
            errors,
        )
        self.assertIn(
            "candidate_funnel terminal dispositions do not conserve observed items",
            errors,
        )

    def test_frozen_v13_accepts_archived_no_l4_passed_receipt_shape(self):
        payload = cloned_v13_payload()
        payload["pipeline"]["red_team"].update(
            {"status": "passed", "covered_item_hashes": []}
        )

        errors, warnings = validate_briefing_data(payload)

        self.assertEqual(errors, [])
        self.assertIn(
            "red-team status is passed but no item hashes are recorded",
            warnings,
        )

    def test_v14_rejects_archived_no_l4_passed_receipt_shape(self):
        payload = cloned_v13_payload()
        payload["schema_version"] = "1.4"
        payload["pipeline"]["red_team"].update(
            {"status": "passed", "covered_item_hashes": []}
        )

        errors, _ = validate_briefing_data(payload)

        self.assertIn(
            "targeted red-team review must record covered item hashes",
            errors,
        )

    def test_v14_requires_declared_red_team_coverage_field(self):
        payload = cloned_v14_payload()
        del payload["pipeline"]["red_team"]["covered_item_hashes"]

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("covered_item_hashes" in error for error in errors))

    def test_v14_requires_boolean_decision_impact(self):
        payload = cloned_v14_payload()
        item = payload["top_10"][0]
        item["near_term_decision_impact"] = "false"
        digest = item_hash(item)
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [digest]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = digest

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("near_term_decision_impact must be boolean" in error for error in errors))

    def test_v14_rejects_undefined_funnel_dispositions(self):
        payload = cloned_v14_payload()
        payload["candidate_funnel"]["terminal_dispositions"] = {
            "retained": 1,
            "noise_count": 2,
        }

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("unknown terminal dispositions" in error for error in errors))

    def test_v14_secondary_source_requires_two_candidate_references(self):
        payload = cloned_v14_payload()
        item = payload["top_10"][0]
        item["source_type"] = "secondary"
        item["corroboration_status"] = "multi_independent"
        digest = item_hash(item)
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [digest]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = digest

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("at least two candidate_refs" in error for error in errors))

    def test_v14_rejects_same_event_with_provisional_identity(self):
        payload = cloned_v14_payload()
        first = payload["top_10"][0]
        second = deepcopy(first)
        second.update(
            {
                "identity_quality": "provisional",
                "url": "https://mirror.example.org/second",
                "source": "Mirror Publisher",
                "candidate_refs": [candidate_ref("https://mirror.example.org/second")],
            }
        )
        second["access_check"].update(
            {
                "requested_url": second["url"],
                "final_url": second["url"],
            }
        )
        second["event_id"] = generate_content_id(
            second["url"], second["title"], second["source"]
        )
        payload["top_10"] = [first, second]
        hashes = [item_hash(item) for item in payload["top_10"]]
        payload["pipeline"]["semantic_review"].update(
            {
                "verified_access_count": 2,
                "reviewed_item_hashes": hashes,
                "lineage_bindings": [
                    {
                        "output_item_sha256": item_hash(item),
                        "inputs": [
                            {
                                "candidate_ref": item["candidate_refs"][0],
                                "candidate_object_sha256": "e" * 64,
                            }
                        ],
                    }
                    for item in payload["top_10"]
                ],
            }
        )
        payload["candidate_funnel"]["terminal_dispositions"] = {
            "retained": 2,
            "below_quality_gate": 1,
        }
        payload["mix"].update(
            {
                "target_counts": {"technology": 1, "healthcare_digital": 1},
                "actual_counts": {"technology": 0, "healthcare_digital": 2},
                "supply_exception": {
                    "applied": True,
                    "reason": "合格候选不足：technology",
                    "missing_domains": ["technology"],
                },
            }
        )

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("duplicate semantic event identities" in error for error in errors))

    def test_v14_allows_distinct_semantic_events_to_share_a_stable_url(self):
        payload = cloned_v14_payload()
        first = payload["top_10"][0]
        second = _distinct_semantic_item(
            first,
            url=first["url"],
            title="Clinical AI evaluation follow-up published",
        )
        _bind_two_item_payload(payload, second)

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_v14_allows_distinct_semantic_events_to_share_a_normalized_title(self):
        payload = cloned_v14_payload()
        first = payload["top_10"][0]
        second = _distinct_semantic_item(
            first,
            url="https://example.org/follow-up",
            title=first["title"],
        )
        _bind_two_item_payload(payload, second)

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_v14_uses_url_or_title_fallback_when_one_event_is_provisional(self):
        first_payload = cloned_v14_payload()
        first = first_payload["top_10"][0]
        cases = (
            (first["url"], "Different provisional title", "duplicate urls"),
            ("https://example.org/provisional", first["title"], "duplicate normalized titles"),
        )
        for url, title, expected in cases:
            with self.subTest(expected=expected):
                payload = cloned_v14_payload()
                first = payload["top_10"][0]
                second = _distinct_semantic_item(first, url=url, title=title)
                second["identity_quality"] = "provisional"
                second["event_id"] = generate_content_id(
                    second["url"], second["title"], second["source"]
                )
                _bind_two_item_payload(payload, second)

                errors, _ = validate_briefing_data(payload)

                self.assertTrue(any(expected in error for error in errors), errors)

    def test_v14_still_rejects_duplicate_event_ids_with_distinct_surfaces(self):
        payload = cloned_v14_payload()
        first = payload["top_10"][0]
        second = deepcopy(first)
        second_url = "https://example.org/distinct-surface"
        second.update(
            {
                "url": second_url,
                "title": "Distinct surface for the same event",
                "title_zh": "同一事件的不同页面",
                "candidate_refs": [candidate_ref(second_url)],
            }
        )
        second["access_check"].update(
            {"requested_url": second_url, "final_url": second_url}
        )
        _bind_two_item_payload(payload, second)

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("duplicate event_ids" in error for error in errors), errors)

    def test_publication_date_requires_canonical_calendar_form(self):
        for invalid in ("20260809", "2026-W32-7", "2026-08-09T09:00:00+08:00"):
            with self.subTest(invalid=invalid):
                payload = cloned_v14_payload()
                payload["top_10"][0]["published_at"] = invalid

                errors, _ = validate_briefing_data(payload)

                self.assertTrue(any("published_at" in error for error in errors))

    def test_frozen_v12_payload_still_passes(self):
        errors, _ = validate_briefing_data(cloned_v12_payload())

        self.assertEqual(errors, [])

    def test_v14_rejects_the_previous_default_ratio(self):
        payload = cloned_v14_payload()
        payload["mix"]["default_ratio"] = {
            "technology": 0.4,
            "healthcare_digital": 0.6,
        }

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("schema default" in error for error in errors))

    def test_user_can_explicitly_request_the_previous_four_to_six_ratio(self):
        payload = cloned_v14_payload()
        payload["mix"].update(
            {
                "requested_ratio": {
                    "technology": 0.4,
                    "healthcare_digital": 0.6,
                },
                "ratio_source": "user",
                "ratio_reason": "用户明确指定",
                "effective_ratio": {
                    "technology": 0.4,
                    "healthcare_digital": 0.6,
                },
                "target_counts": {"technology": 0, "healthcare_digital": 1},
                "supply_exception": {
                    "applied": False,
                    "reason": "none",
                    "missing_domains": [],
                },
            }
        )

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_healthcare_major_signal_shifts_v14_ratio_toward_healthcare(self):
        payload = cloned_v14_payload()
        item = payload["top_10"][0]
        item.update(
            {
                "major_signal": True,
                "major_signal_reason": "将影响近期部署决策",
                "near_term_decision_impact": True,
                "decision_impact_reason": "需要调整验证计划",
                "intelligence_level": "L3",
                "confidence": "high",
            }
        )
        reviewed_hash = item_hash(item)
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
            reviewed_hash
        ]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = reviewed_hash
        payload["mix"].update(
            {
                "effective_ratio": {
                    "technology": 0.4,
                    "healthcare_digital": 0.6,
                },
                "target_counts": {"technology": 0, "healthcare_digital": 1},
                "adjustment": {
                    "applied": True,
                    "favored_domain": "healthcare_digital",
                    "reason": "将影响近期部署决策",
                    "trigger_urls": [item["url"]],
                },
                "supply_exception": {
                    "applied": False,
                    "reason": "none",
                    "missing_domains": [],
                },
            }
        )

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_healthcare_major_signal_cannot_shift_toward_technology(self):
        payload = cloned_v14_payload()
        item = payload["top_10"][0]
        item.update(
            {
                "major_signal": True,
                "major_signal_reason": "将影响近期部署决策",
                "near_term_decision_impact": True,
                "decision_impact_reason": "需要调整验证计划",
                "intelligence_level": "L3",
                "confidence": "high",
            }
        )
        reviewed_hash = item_hash(item)
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
            reviewed_hash
        ]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = reviewed_hash
        payload["mix"].update(
            {
                "effective_ratio": {
                    "technology": 0.8,
                    "healthcare_digital": 0.2,
                },
                "target_counts": {"technology": 1, "healthcare_digital": 0},
                "adjustment": {
                    "applied": True,
                    "favored_domain": "technology",
                    "reason": "将影响近期部署决策",
                    "trigger_urls": [item["url"]],
                },
                "supply_exception": {
                    "applied": True,
                    "reason": "合格候选不足：technology",
                    "missing_domains": ["technology"],
                },
            }
        )

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("recomputed major-signal policy" in error for error in errors))

    def test_user_four_to_six_with_major_signals_in_both_domains_keeps_requested_mix(self):
        payload = cloned_v14_payload()
        healthcare = payload["top_10"][0]
        healthcare.update(
            {
                "major_signal": True,
                "major_signal_reason": "医疗数字化信号影响近期决策",
                "near_term_decision_impact": True,
                "decision_impact_reason": "需要调整医疗验证计划",
                "intelligence_level": "L3",
                "confidence": "high",
            }
        )
        technology = deepcopy(healthcare)
        technology_identity = {
            "primary_domain": "technology",
            "actor": "Example Technology Lab",
            "action": "published",
            "object": "agent runtime evaluation",
            "event_date": "2026-08-09",
            "key_version": "1",
        }
        technology.update(
            {
                "event_id": generate_event_id(technology_identity),
                "event_identity": technology_identity,
                "title": "Agent runtime evaluation published",
                "title_zh": "智能体运行时评估发布",
                "url": "https://example.org/technology-source",
                "candidate_refs": [candidate_ref("https://example.org/technology-source")],
                "source": "Example Technology Lab",
                "primary_domain": "technology",
                "major_signal_reason": "技术信号影响近期决策",
                "decision_impact_reason": "需要调整技术验证计划",
            }
        )
        technology["access_check"].update(
            {
                "requested_url": technology["url"],
                "final_url": technology["url"],
            }
        )
        policy = {
            "default_ratio": {"technology": 0.6, "healthcare_digital": 0.4},
            "requested_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "ratio_source": "user",
            "ratio_reason": "用户明确指定",
            "max_ratio_shift": 0.2,
        }
        selected, mix = select_candidates_with_mix(
            [technology, healthcare], 2, policy
        )
        hashes = [item_hash(item) for item in selected]
        payload["top_10"] = selected
        payload["mix"] = mix
        payload["candidate_funnel"]["terminal_dispositions"] = {
            "retained": 2,
            "below_quality_gate": 1,
        }
        payload["pipeline"]["semantic_review"].update(
            {
                "verified_access_count": 2,
                "reviewed_item_hashes": hashes,
                "lineage_bindings": [
                    {
                        "output_item_sha256": item_hash(item),
                        "inputs": [
                            {
                                "candidate_ref": item["candidate_refs"][0],
                                "candidate_object_sha256": "e" * 64,
                            }
                        ],
                    }
                    for item in selected
                ],
            }
        )

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(mix["effective_ratio"], policy["requested_ratio"])
        self.assertEqual(
            mix["adjustment"]["reason"],
            "两个领域均有高影响资讯，维持请求比例",
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
