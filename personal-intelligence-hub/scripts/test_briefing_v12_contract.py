import unittest

from briefing_gate import validate_briefing_data
from run_contract import item_hash
from test_contract_fixtures import cloned_v12_payload


class BriefingV12ContractTests(unittest.TestCase):
    def test_valid_v12_payload_passes(self):
        errors, _ = validate_briefing_data(cloned_v12_payload())
        self.assertEqual(errors, [])

    def test_extra_corroboration_cannot_inflate_retained_item_access_count(self):
        payload = cloned_v12_payload()
        payload["pipeline"]["semantic_review"]["verified_access_count"] = 2

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("distinct retained-item access mappings" in error for error in errors))

    def test_requested_url_must_match_the_retained_item(self):
        payload = cloned_v12_payload()
        payload["top_10"][0]["access_check"]["requested_url"] = (
            "https://unrelated.invalid/proof"
        )
        reviewed_hash = item_hash(payload["top_10"][0])
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [reviewed_hash]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = reviewed_hash

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("requested_url must match item url" in error for error in errors))

    def test_unknown_or_out_of_window_published_date_is_rejected(self):
        for value in ("unknown", "2026-07-01"):
            with self.subTest(value=value):
                payload = cloned_v12_payload()
                payload["top_10"][0]["published_at"] = value
                payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
                    item_hash(payload["top_10"][0])
                ]
                errors, _ = validate_briefing_data(payload)
                self.assertTrue(any("published_at" in error for error in errors))

    def test_verified_access_record_is_required(self):
        payload = cloned_v12_payload()
        payload["top_10"][0]["access_check"]["status"] = "failed"
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [
            item_hash(payload["top_10"][0])
        ]

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("access_check" in error for error in errors))

    def test_review_receipt_hashes_must_cover_final_items(self):
        payload = cloned_v12_payload()
        payload["top_10"][0]["fact"] = "评估事实被评估后修改。"

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("reviewed_item_hashes" in error for error in errors))

    def test_user_requested_ratio_is_accepted_and_shift_is_measured_from_it(self):
        payload = cloned_v12_payload()
        payload["mix"]["requested_ratio"] = {"technology": 0.5, "healthcare_digital": 0.5}
        payload["mix"]["ratio_source"] = "user"
        payload["mix"]["ratio_reason"] = "用户明确指定"
        payload["mix"]["effective_ratio"] = {"technology": 0.5, "healthcare_digital": 0.5}
        payload["mix"]["target_counts"] = {"technology": 1, "healthcare_digital": 0}
        payload["mix"]["supply_exception"] = {
            "applied": True,
            "reason": "合格候选不足：technology",
            "missing_domains": ["technology"],
        }

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_candidate_funnel_must_conserve_observed_items(self):
        payload = cloned_v12_payload()
        payload["candidate_funnel"]["terminal_dispositions"]["below_quality_gate"] = 1

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("candidate_funnel" in error for error in errors))

    def test_provisional_event_id_must_be_derived_from_content(self):
        payload = cloned_v12_payload()
        item = payload["top_10"][0]
        item["identity_quality"] = "provisional"
        item["event_id"] = "arbitrary-id"
        reviewed_hash = item_hash(item)
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [reviewed_hash]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = reviewed_hash

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("provisional content identity" in error for error in errors))

    def test_weak_major_signal_cannot_change_mix(self):
        payload = cloned_v12_payload()
        item = payload["top_10"][0]
        item["major_signal"] = True
        item["major_signal_reason"] = "标题很重要"
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [item_hash(item)]

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("major_signal eligibility" in error for error in errors))

    def test_healthcare_major_signal_recomputes_shift_toward_healthcare(self):
        payload = cloned_v12_payload()
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
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [reviewed_hash]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = reviewed_hash
        payload["mix"]["effective_ratio"] = {
            "technology": 0.2,
            "healthcare_digital": 0.8,
        }
        payload["mix"]["adjustment"] = {
            "applied": True,
            "favored_domain": "healthcare_digital",
            "reason": "将影响近期部署决策",
            "trigger_urls": [item["url"]],
        }

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_major_signal_cannot_shift_ratio_toward_the_other_domain(self):
        payload = cloned_v12_payload()
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
        payload["pipeline"]["semantic_review"]["reviewed_item_hashes"] = [reviewed_hash]
        payload["pipeline"]["semantic_review"]["lineage_bindings"][0][
            "output_item_sha256"
        ] = reviewed_hash
        payload["mix"]["effective_ratio"] = {
            "technology": 0.6,
            "healthcare_digital": 0.4,
        }
        payload["mix"]["target_counts"] = {
            "technology": 1,
            "healthcare_digital": 0,
        }
        payload["mix"]["adjustment"] = {
            "applied": True,
            "favored_domain": "technology",
            "reason": "将影响近期部署决策",
            "trigger_urls": [item["url"]],
        }
        payload["mix"]["supply_exception"] = {
            "applied": True,
            "reason": "合格候选不足：technology",
            "missing_domains": ["technology"],
        }

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("recomputed major-signal policy" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
