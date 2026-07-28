import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from paper_audit_gate import validate_paper_draft


class PaperAuditGateTests(unittest.TestCase):
    def test_literal_template_syntax_not_owned_by_template_is_allowed(self):
        errors, _ = validate_paper_draft(
            "论文附录记录接口示例 {{patient_id}} 与代码片段 {custom_field}。"
        )

        self.assertEqual(errors, [])

    def test_known_template_token_is_rejected(self):
        errors, _ = validate_paper_draft("目标仍是 {Target Paper}。")

        self.assertTrue(any("unresolved template placeholders" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
