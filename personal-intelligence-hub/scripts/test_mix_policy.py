import unittest

from mix_policy import allocate_target_counts, select_candidates_with_mix
from refine import post_process_entities, score_item


DEFAULT_POLICY = {
    "default_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
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
            {"technology": 4, "healthcare_digital": 6},
        )
        self.assertEqual(
            allocate_target_counts(7, ratio),
            {"technology": 3, "healthcare_digital": 4},
        )
        self.assertEqual(
            allocate_target_counts(5, ratio),
            {"technology": 2, "healthcare_digital": 3},
        )
        self.assertEqual(
            allocate_target_counts(3, ratio),
            {"technology": 1, "healthcare_digital": 2},
        )

    def test_default_mix_selects_two_technology_and_three_healthcare(self):
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
            {"technology": 2, "healthcare_digital": 3},
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
        ] + [
            candidate("healthcare_digital", 88 - index, f"h{index}")
            for index in range(5)
        ]

        selected, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(len(selected), 5)
        self.assertEqual(
            mix["actual_counts"],
            {"technology": 3, "healthcare_digital": 2},
        )
        self.assertTrue(mix["adjustment"]["applied"])
        self.assertEqual(mix["adjustment"]["favored_domain"], "technology")
        self.assertEqual(len(mix["adjustment"]["trigger_urls"]), 1)

    def test_major_healthcare_signal_can_shift_mix_to_one_and_four(self):
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
            {"technology": 1, "healthcare_digital": 4},
        )
        self.assertEqual(
            mix["effective_ratio"],
            {"technology": 0.2, "healthcare_digital": 0.8},
        )

    def test_major_signals_in_both_domains_keep_default_mix(self):
        candidates = [
            candidate("technology", 99, "major-tech", major=True),
            candidate("technology", 90, "t1"),
            candidate("healthcare_digital", 98, "major-health", major=True),
            candidate("healthcare_digital", 89, "h1"),
            candidate("healthcare_digital", 88, "h2"),
        ]

        _, mix = select_candidates_with_mix(candidates, 5, DEFAULT_POLICY)

        self.assertEqual(
            mix["actual_counts"],
            {"technology": 2, "healthcare_digital": 3},
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


if __name__ == "__main__":
    unittest.main()
