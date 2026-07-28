import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from audit_gate import validate


class AuditGateTests(unittest.TestCase):
    def test_literal_template_syntax_is_non_blocking_in_free_form(self):
        errors, warnings = validate("证据：原文把 [事件] 作为字段示例。")

        self.assertEqual(errors, [])
        self.assertTrue(any("possible unresolved template markers" in item for item in warnings))

    def test_template_mode_blocks_unresolved_template_fields(self):
        errors, _ = validate(
            "# [日期] Daily Audit\n\n证据：用户提供的日志。",
            enforce_template_fields=True,
        )

        self.assertTrue(any("possible unresolved template markers" in item for item in errors))

    def test_style_terms_remain_editorial_warnings(self):
        errors, warnings = validate("证据存在，但草稿写了冷酷判词。")

        self.assertEqual(errors, [])
        self.assertTrue(any("potentially shaming" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
