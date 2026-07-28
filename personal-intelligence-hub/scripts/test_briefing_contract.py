import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from briefing_gate import validate_briefing_data


SCRIPT_DIR = Path(__file__).resolve().parent


def valid_payload():
    return {
        "schema_version": "1.0",
        "generated_at": "2026-07-28T12:00:00+08:00",
        "topic": "医疗 AI",
        "region": "中国",
        "window": {"start": "2026-07-21", "end": "2026-07-28", "timezone": "Asia/Shanghai"},
        "punchline": "当前窗口有一条待持续核验的信号。",
        "insights": "尚不足以形成确定判断。",
        "digest": "保留观察。",
        "market": "数据有限。",
        "action_levers": [],
        "top_10": [
            {
                "title": "Source title",
                "title_zh": "来源标题",
                "url": "https://example.org/source",
                "source": "Example Journal",
                "event_date": "unknown",
                "published_at": "2026-07-27",
                "retrieved_at": "2026-07-28T12:00:00+08:00",
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


if __name__ == "__main__":
    unittest.main()
