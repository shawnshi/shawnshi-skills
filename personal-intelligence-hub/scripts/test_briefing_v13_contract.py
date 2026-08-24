import unittest
from copy import deepcopy

from briefing_gate import validate_briefing_data
from history_manager import generate_event_id
from mix_policy import select_candidates_with_mix
from run_contract import candidate_ref, item_hash
from test_contract_fixtures import cloned_v12_payload, cloned_v13_payload


class BriefingV13ContractTests(unittest.TestCase):
    def test_valid_v13_payload_passes(self):
        errors, _ = validate_briefing_data(cloned_v13_payload())

        self.assertEqual(errors, [])

    def test_publication_date_requires_canonical_calendar_form(self):
        for invalid in ("20260809", "2026-W32-7", "2026-08-09T09:00:00+08:00"):
            with self.subTest(invalid=invalid):
                payload = cloned_v13_payload()
                payload["top_10"][0]["published_at"] = invalid

                errors, _ = validate_briefing_data(payload)

                self.assertTrue(any("published_at" in error for error in errors))

    def test_frozen_v12_payload_still_passes(self):
        errors, _ = validate_briefing_data(cloned_v12_payload())

        self.assertEqual(errors, [])

    def test_v13_rejects_the_previous_default_ratio(self):
        payload = cloned_v13_payload()
        payload["mix"]["default_ratio"] = {
            "technology": 0.4,
            "healthcare_digital": 0.6,
        }

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("schema default" in error for error in errors))

    def test_user_can_explicitly_request_the_previous_four_to_six_ratio(self):
        payload = cloned_v13_payload()
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

    def test_healthcare_major_signal_shifts_v13_ratio_toward_healthcare(self):
        payload = cloned_v13_payload()
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
        payload = cloned_v13_payload()
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
        payload = cloned_v13_payload()
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
