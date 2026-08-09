import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from briefing_gate import validate_briefing_data
from mix_policy import select_candidates_with_mix


SCRIPT_DIR = Path(__file__).resolve().parent


def valid_payload():
    return {
        "schema_version": "1.1",
        "generated_at": "2026-07-28T12:00:00+08:00",
        "topic": "医疗 AI",
        "region": "中国",
        "window": {"start": "2026-07-21", "end": "2026-07-28", "timezone": "Asia/Shanghai"},
        "punchline": "当前窗口有一条待持续核验的信号。",
        "insights": "尚不足以形成确定判断。",
        "digest": "保留观察。",
        "market": "数据有限。",
        "action_levers": [],
        "mix": {
            "default_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "effective_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "target_counts": {"technology": 0, "healthcare_digital": 1},
            "actual_counts": {"technology": 0, "healthcare_digital": 1},
            "adjustment": {
                "applied": False,
                "favored_domain": "none",
                "reason": "none",
                "trigger_urls": [],
            },
            "supply_exception": {
                "applied": False,
                "reason": "none",
                "missing_domains": [],
            },
        },
        "top_10": [
            {
                "title": "Source title",
                "title_zh": "来源标题",
                "url": "https://example.org/source",
                "source": "Example Journal",
                "event_date": "unknown",
                "published_at": "2026-07-27",
                "retrieved_at": "2026-07-28T12:00:00+08:00",
                "primary_domain": "healthcare_digital",
                "secondary_domains": [],
                "major_signal": False,
                "major_signal_reason": "none",
                "fact": "来源发布了一项公告。",
                "connection": "与主题相关。",
                "deduction": "影响仍需后续证据。",
                "actionability": "继续观察。",
                "intelligence_level": "L2",
                "confidence": "medium",
                "summary_zh": "公告摘要。",
            }
        ],
        "data_gaps": ["尚无第二独立来源"],
    }


class BriefingContractTests(unittest.TestCase):
    def test_valid_payload_has_only_soft_warnings(self):
        errors, warnings = validate_briefing_data(valid_payload())
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_missing_schema_field_blocks(self):
        payload = valid_payload()
        del payload["top_10"][0]["retrieved_at"]
        errors, _ = validate_briefing_data(payload)
        self.assertTrue(any("retrieved_at" in item for item in errors))

    def test_validator_cli_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brief.json"
            original = json.dumps(valid_payload(), ensure_ascii=False, separators=(",", ":"))
            path.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "validate_refined_json.py"), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_l4_requires_structured_audit(self):
        payload = copy.deepcopy(valid_payload())
        payload["top_10"][0]["intelligence_level"] = "L4"
        errors, _ = validate_briefing_data(payload)
        self.assertIn("L4 items require adversarial_audit", errors)

    def test_literal_template_syntax_not_owned_by_template_is_allowed(self):
        payload = valid_payload()
        payload["insights"] = "接口示例保留 {{patient_id}} 字面量。"

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])

    def test_known_template_token_is_rejected(self):
        payload = valid_payload()
        payload["insights"] = "尚未替换 {{ topic }}。"

        errors, _ = validate_briefing_data(payload)

        self.assertTrue(any("unresolved template value" in item for item in errors))

    def test_mix_actual_counts_must_match_items(self):
        payload = valid_payload()
        payload["mix"]["actual_counts"] = {"technology": 1, "healthcare_digital": 0}

        errors, _ = validate_briefing_data(payload)

        self.assertIn("mix.actual_counts does not match retained items", errors)

    def test_mix_deviation_requires_supply_exception(self):
        payload = valid_payload()
        payload["top_10"].append(
            {
                **copy.deepcopy(payload["top_10"][0]),
                "title": "Second source",
                "title_zh": "第二条来源",
                "url": "https://example.org/second",
            }
        )
        payload["mix"]["target_counts"] = {"technology": 1, "healthcare_digital": 1}
        payload["mix"]["actual_counts"] = {"technology": 0, "healthcare_digital": 2}

        errors, _ = validate_briefing_data(payload)

        self.assertIn("mix deviation requires supply_exception", errors)

    def test_effective_ratio_change_requires_adjustment(self):
        payload = valid_payload()
        payload["mix"]["effective_ratio"] = {
            "technology": 0.6,
            "healthcare_digital": 0.4,
        }
        payload["mix"]["target_counts"] = {"technology": 1, "healthcare_digital": 0}

        errors, _ = validate_briefing_data(payload)

        self.assertIn(
            "mix adjustment is required when effective_ratio changes",
            errors,
        )

    def test_major_signal_mix_from_selector_passes_gate(self):
        payload = valid_payload()
        base = payload["top_10"][0]
        candidates = []
        for index, domain in enumerate(
            [
                "technology",
                "technology",
                "technology",
                "healthcare_digital",
                "healthcare_digital",
                "healthcare_digital",
            ]
        ):
            item = copy.deepcopy(base)
            item["title"] = f"source-{index}"
            item["title_zh"] = f"来源-{index}"
            item["url"] = f"https://example.org/source-{index}"
            item["primary_domain"] = domain
            item["strategic_score"] = 100 - index
            item["major_signal"] = index == 0
            item["major_signal_reason"] = "高可信L3改变近期决策" if index == 0 else "none"
            candidates.append(item)
        selected, mix = select_candidates_with_mix(
            candidates,
            5,
            {
                "default_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
                "max_ratio_shift": 0.2,
            },
        )
        payload["top_10"] = selected
        payload["mix"] = mix

        errors, _ = validate_briefing_data(payload)

        self.assertEqual(errors, [])
        self.assertEqual(
            payload["mix"]["actual_counts"],
            {"technology": 3, "healthcare_digital": 2},
        )


if __name__ == "__main__":
    unittest.main()
