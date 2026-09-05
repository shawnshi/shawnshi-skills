import json
import unittest
from pathlib import Path

from mix_policy import allocate_target_counts, major_signal_eligible, select_candidates_with_mix
from refine import post_process_entities, score_item


DEFAULT_POLICY = {
    "default_ratio": {"technology": 0.6, "healthcare_digital": 0.4},
    "max_ratio_shift": 0.2,
}


def candidate(domain: str, score: int, suffix: str, *, major: bool = False) -> dict:
    return {
        "title": f"{domain}-{suffix}",
        "url": f"https://example.org/{domain}/{suffix}",
        "primary_domain": domain,
        "strategic_score": score,
        "major_signal": major,
        "major_signal_reason": "通过高影响门槛" if major else "none",
        "intelligence_level": "L3" if major else "L2",
        "confidence": "high" if major else "medium",
        "source_type": "primary",
        "access_check": {"status": "verified"},
        "near_term_decision_impact": major,
    }


class MixPolicyTests(unittest.TestCase):
    def test_short_ascii_acronym_does_not_match_inside_another_word(self):
        focus = {
            "domains": {
                "technology": {"keywords": [], "priority_sources": {}},
                "healthcare_digital": {
                    "keywords": [{"keyword": "DIP", "weight": 8}],
                    "priority_sources": {},
                },
            }
        }
        item = {
            "title": "Microcode inside the Intel 8087 floating-point chip",
            "raw_desc": "Register exchange and floating-point implementation.",
            "source": "righto.com",
        }

        _, _, _, domain_scores = score_item(item, focus)

        self.assertEqual(domain_scores["healthcare_digital"], 0)

    def test_oncology_guideline_research_is_classified_as_healthcare(self):
        focus_path = Path(__file__).resolve().parent.parent / "references" / "strategic_focus.json"
        focus = json.loads(focus_path.read_text(encoding="utf-8"))
        item = {
            "title": (
                "A collective capability boundary in frontier large language models "
                "on guideline-conformant and case-specific oncology decision-making"
            ),
            "raw_desc": "Evaluation of LLMs for oncology clinical decisions.",
            "source": "arXiv (cs.AI)",
        }

        _, _, primary_domain, scores = score_item(item, focus)

        self.assertEqual(primary_domain, "healthcare_digital")
        self.assertGreater(scores["healthcare_digital"], scores["technology"])

    def test_entity_linking_does_not_corrupt_markdown_link_titles(self):
        output = {
            "top_10": [
                {
                    "title_zh": "GPU inference stack",
                    "summary_zh": "GPU inference improves throughput.",
                    "deduction": "GPU capacity remains constrained.",
                }
            ]
        }
        focus = {
            "competitors": [],
            "domains": {
                "technology": {
                    "keywords": [
                        {"keyword": "GPU", "weight": 6},
                        {"keyword": "inference", "weight": 6},
                    ]
                },
                "healthcare_digital": {"keywords": []},
            },
        }

        processed = post_process_entities(output, focus)

        self.assertEqual(processed["top_10"][0]["title_zh"], "GPU inference stack")
        self.assertIn("[[GPU]]", processed["top_10"][0]["summary_zh"])
    def test_largest_remainder_default_allocations(self):
        ratio = DEFAULT_POLICY["default_ratio"]
        self.assertEqual(
            allocate_target_counts(10, ratio),
            {"technology": 6, "healthcare_digital": 4},
        )
        self.assertEqual(
            allocate_target_counts(7, ratio),
            {"technology": 4, "healthcare_digital": 3},
        )
        self.assertEqual(
            allocate_target_counts(5, ratio),
            {"technology": 3, "healthcare_digital": 2},
        )
        self.assertEqual(
            allocate_target_counts(3, ratio),
            {"technology": 2, "healthcare_digital": 1},
        )

    def test_default_mix_selects_three_technology_and_two_healthcare(self):
        candidates = [
            candidate("technology", 90 - index, f"t{index}") for index in range(5)
        ] + [
            candidate("healthcare_digital", 89 - index, f"h{index}")
            for index in range(5)
        ]

        selected, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(len(selected), 5)
        self.assertEqual(
            mix["actual_counts"],
            {"technology": 3, "healthcare_digital": 2},
        )
        self.assertFalse(mix["adjustment"]["applied"])
        self.assertFalse(mix["supply_exception"]["applied"])

    def test_shortage_does_not_pad_with_weak_or_missing_candidates(self):
        candidates = [candidate("technology", 90, "only")] + [
            candidate("healthcare_digital", 89 - index, f"h{index}")
            for index in range(6)
        ]

        selected, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(len(selected), 5)
        self.assertEqual(
            mix["actual_counts"],
            {"technology": 1, "healthcare_digital": 4},
        )
        self.assertTrue(mix["supply_exception"]["applied"])
        self.assertIn("technology", mix["supply_exception"]["missing_domains"])

    def test_major_technology_signal_can_shift_mix_by_twenty_points(self):
        candidates = [
            candidate("technology", 99, "major", major=True),
            candidate("technology", 90, "t1"),
            candidate("technology", 89, "t2"),
            candidate("technology", 88, "t3"),
        ] + [
            candidate("healthcare_digital", 87 - index, f"h{index}")
            for index in range(5)
        ]

        selected, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(len(selected), 5)
        self.assertEqual(
            mix["actual_counts"],
            {"technology": 4, "healthcare_digital": 1},
        )
        self.assertAlmostEqual(mix["effective_ratio"]["technology"], 0.8)
        self.assertAlmostEqual(mix["effective_ratio"]["healthcare_digital"], 0.2)
        self.assertTrue(mix["adjustment"]["applied"])
        self.assertEqual(mix["adjustment"]["favored_domain"], "technology")
        self.assertEqual(len(mix["adjustment"]["trigger_urls"]), 1)

    def test_major_healthcare_signal_can_shift_mix_to_two_and_three(self):
        candidates = [
            candidate("technology", 90 - index, f"t{index}") for index in range(4)
        ] + [
            candidate("healthcare_digital", 99, "major", major=True),
            candidate("healthcare_digital", 89, "h1"),
            candidate("healthcare_digital", 88, "h2"),
            candidate("healthcare_digital", 87, "h3"),
        ]

        selected, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(
            mix["actual_counts"],
            {"technology": 2, "healthcare_digital": 3},
        )
        self.assertAlmostEqual(mix["effective_ratio"]["technology"], 0.4)
        self.assertAlmostEqual(mix["effective_ratio"]["healthcare_digital"], 0.6)

    def test_major_signals_in_both_domains_keep_default_mix(self):
        candidates = [
            candidate("technology", 99, "major-tech", major=True),
            candidate("technology", 90, "t1"),
            candidate("technology", 89, "t2"),
            candidate("healthcare_digital", 98, "major-health", major=True),
            candidate("healthcare_digital", 89, "h1"),
            candidate("healthcare_digital", 88, "h2"),
        ]

        _, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(
            mix["actual_counts"],
            {"technology": 3, "healthcare_digital": 2},
        )
        self.assertFalse(mix["adjustment"]["applied"])

    def test_zero_item_brief_does_not_apply_adjustment(self):
        _, mix = select_candidates_with_mix(
            [candidate("technology", 99, "major", major=True)],
            0,
            DEFAULT_POLICY,
        )

        self.assertEqual(
            mix["actual_counts"],
            {"technology": 0, "healthcare_digital": 0},
        )
        self.assertFalse(mix["adjustment"]["applied"])

    def test_max_items_one_recomputes_mix_from_retained_major_signals(self):
        policy = {
            **DEFAULT_POLICY,
            "requested_ratio": {"technology": 0.9, "healthcare_digital": 0.1},
            "ratio_source": "user",
            "ratio_reason": "极端比例回归",
        }
        retained = candidate("technology", 90, "retained")
        dropped_major = candidate(
            "healthcare_digital", 99, "dropped-major", major=True
        )

        selected, mix = select_candidates_with_mix(
            [retained, dropped_major], 1, policy
        )

        self.assertEqual([item["url"] for item in selected], [retained["url"]])
        self.assertEqual(mix["effective_ratio"], policy["requested_ratio"])
        self.assertEqual(
            mix["target_counts"],
            {"technology": 1, "healthcare_digital": 0},
        )
        self.assertFalse(mix["adjustment"]["applied"])
        self.assertEqual(mix["adjustment"]["favored_domain"], "none")
        self.assertEqual(mix["adjustment"]["reason"], "none")
        self.assertEqual(mix["adjustment"]["trigger_urls"], [])

    def test_max_items_two_recomputes_mix_from_retained_major_signals(self):
        policy = {
            **DEFAULT_POLICY,
            "requested_ratio": {"technology": 0.95, "healthcare_digital": 0.05},
            "ratio_source": "user",
            "ratio_reason": "极端比例回归",
        }
        retained = [
            candidate("technology", 90 - index, f"retained-{index}")
            for index in range(2)
        ]
        dropped_major = candidate(
            "healthcare_digital", 99, "dropped-major", major=True
        )

        selected, mix = select_candidates_with_mix(
            retained + [dropped_major], 2, policy
        )

        self.assertEqual(
            {item["url"] for item in selected},
            {item["url"] for item in retained},
        )
        self.assertEqual(mix["effective_ratio"], policy["requested_ratio"])
        self.assertEqual(
            mix["target_counts"],
            {"technology": 2, "healthcare_digital": 0},
        )
        self.assertFalse(mix["adjustment"]["applied"])
        self.assertEqual(mix["adjustment"]["trigger_urls"], [])

    def test_l4_major_uses_schema_level_before_registered_red_team_review(self):
        l4_major = candidate("healthcare_digital", 99, "l4-major", major=True)
        l4_major["intelligence_level"] = "L4"
        retained_technology = candidate("technology", 90, "technology")

        self.assertNotIn("red_team_status", l4_major)
        self.assertTrue(major_signal_eligible(l4_major))

        selected, mix = select_candidates_with_mix(
            [retained_technology, l4_major], 2, DEFAULT_POLICY
        )

        self.assertEqual(len(selected), 2)
        self.assertTrue(mix["adjustment"]["applied"])
        self.assertEqual(
            mix["adjustment"]["favored_domain"], "healthcare_digital"
        )
        self.assertEqual(mix["adjustment"]["trigger_urls"], [l4_major["url"]])

    def test_claimed_major_without_eligibility_cannot_shift_mix(self):
        weak = candidate("technology", 99, "weak", major=True)
        weak["intelligence_level"] = "L2"
        weak["confidence"] = "low"
        weak["source_type"] = "secondary"
        weak["near_term_decision_impact"] = False
        candidates = [weak, candidate("technology", 90, "t1")] + [
            candidate("healthcare_digital", 89 - index, f"h{index}")
            for index in range(3)
        ]

        _, mix = select_candidates_with_mix(candidates, 4, DEFAULT_POLICY)

        self.assertFalse(major_signal_eligible(weak))
        self.assertFalse(mix["adjustment"]["applied"])
        self.assertEqual(mix["effective_ratio"], mix["requested_ratio"])

    def test_user_requested_ratio_is_the_adjustment_baseline(self):
        policy = {
            **DEFAULT_POLICY,
            "requested_ratio": {"technology": 0.5, "healthcare_digital": 0.5},
            "ratio_source": "user",
            "ratio_reason": "用户明确指定",
        }
        candidates = [
            candidate("technology", 90 - index, f"t{index}") for index in range(3)
        ] + [
            candidate("healthcare_digital", 89 - index, f"h{index}")
            for index in range(3)
        ]

        _, mix = select_candidates_with_mix(candidates, 4, policy)

        self.assertEqual(mix["default_ratio"], DEFAULT_POLICY["default_ratio"])
        self.assertEqual(
            mix["requested_ratio"],
            {"technology": 0.5, "healthcare_digital": 0.5},
        )
        self.assertEqual(mix["effective_ratio"], mix["requested_ratio"])
        self.assertEqual(mix["ratio_source"], "user")

    def test_user_can_still_request_the_previous_four_to_six_ratio(self):
        policy = {
            **DEFAULT_POLICY,
            "requested_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "ratio_source": "user",
            "ratio_reason": "用户明确指定",
        }
        candidates = [
            candidate("technology", 90 - index, f"t{index}") for index in range(3)
        ] + [
            candidate("healthcare_digital", 89 - index, f"h{index}")
            for index in range(4)
        ]

        _, mix = select_candidates_with_mix(candidates, 5, policy)

        self.assertEqual(
            mix["actual_counts"],
            {"technology": 2, "healthcare_digital": 3},
        )
        self.assertEqual(mix["requested_ratio"], policy["requested_ratio"])
        self.assertEqual(mix["ratio_source"], "user")

    def test_qualified_major_shift_is_measured_from_requested_ratio(self):
        policy = {
            **DEFAULT_POLICY,
            "requested_ratio": {"technology": 0.5, "healthcare_digital": 0.5},
            "ratio_source": "user",
            "ratio_reason": "用户明确指定",
        }
        candidates = [candidate("technology", 99, "major", major=True)] + [
            candidate("technology", 90, "t1"),
            candidate("technology", 89, "t2"),
            candidate("healthcare_digital", 88, "h1"),
            candidate("healthcare_digital", 87, "h2"),
        ]

        _, mix = select_candidates_with_mix(candidates, 5, policy)

        self.assertEqual(
            mix["effective_ratio"],
            {"technology": 0.7, "healthcare_digital": 0.3},
        )


if __name__ == "__main__":
    unittest.main()
