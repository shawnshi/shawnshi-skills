import shutil
import tempfile
import unittest
from pathlib import Path

import validate_openai_yaml as validator


class OpenAiYamlValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.skill_dir = self.root / "example-skill"
        (self.skill_dir / "agents").mkdir(parents=True)
        (self.skill_dir / "SKILL.md").write_text(
            "---\nname: example-skill\ndescription: 用于测试界面元数据的示例技能。\n---\n",
            encoding="utf-8",
        )

    def write_yaml(self, text: str) -> None:
        (self.skill_dir / "agents" / "openai.yaml").write_text(text, encoding="utf-8")

    def test_valid_metadata_passes(self):
        self.write_yaml(
            'interface:\n'
            '  display_name: "Example Skill"\n'
            '  short_description: "Validate deterministic local skill metadata"\n'
            '  default_prompt: "Use $example-skill to validate this skill."\n'
            'policy:\n'
            '  allow_implicit_invocation: false\n'
        )

        result = validator.validate_root(self.root)

        self.assertEqual(result["failures"], 0, result["issues"])

    def test_malformed_yaml_fails(self):
        self.write_yaml("interface: [\n")

        result = validator.validate_root(self.root)

        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["issues"][0]["code"], "openai_yaml_parse_error")

    def test_duplicate_yaml_key_fails(self):
        self.write_yaml(
            "interface:\n"
            "  display_name: Example\n"
            "  display_name: Override\n"
            "  short_description: 这是一个用于验证技能界面元数据结构规则的测试说明。\n"
            "  default_prompt: Use $example-skill to perform the task.\n"
        )

        result = validator.validate_root(self.root)

        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["issues"][0]["code"], "openai_yaml_parse_error")

    def test_wrong_skill_token_fails(self):
        self.write_yaml(
            'interface:\n'
            '  display_name: "Example Skill"\n'
            '  short_description: "Validate deterministic local skill metadata"\n'
            '  default_prompt: "Use $other-skill to validate this skill."\n'
        )

        codes = {issue["code"] for issue in validator.validate_root(self.root)["issues"]}

        self.assertIn("openai_default_prompt_invalid", codes)

    def test_longer_skill_token_does_not_satisfy_exact_match(self):
        for token in ("$example-skill-evil", "x$example-skill"):
            with self.subTest(token=token):
                self.write_yaml(
                    'interface:\n'
                    '  display_name: "Example Skill"\n'
                    '  short_description: "Validate deterministic local skill metadata"\n'
                    f'  default_prompt: "Use {token} to validate this skill."\n'
                )

                codes = {issue["code"] for issue in validator.validate_root(self.root)["issues"]}

                self.assertIn("openai_default_prompt_invalid", codes)

    def test_policy_must_be_boolean(self):
        self.write_yaml(
            'interface:\n'
            '  display_name: "Example Skill"\n'
            '  short_description: "Validate deterministic local skill metadata"\n'
            '  default_prompt: "Use $example-skill to validate this skill."\n'
            'policy:\n'
            '  allow_implicit_invocation: "false"\n'
        )

        codes = {issue["code"] for issue in validator.validate_root(self.root)["issues"]}

        self.assertIn("openai_policy_invalid", codes)

    def test_icon_must_resolve_inside_skill(self):
        self.write_yaml(
            'interface:\n'
            '  display_name: "Example Skill"\n'
            '  short_description: "Validate deterministic local skill metadata"\n'
            '  default_prompt: "Use $example-skill to validate this skill."\n'
            '  icon_small: "../outside.svg"\n'
        )

        codes = {issue["code"] for issue in validator.validate_root(self.root)["issues"]}

        self.assertIn("openai_icon_invalid", codes)

    def test_contradictory_invocation_policy_fails(self):
        for frontmatter_flag, policy_flag in ((True, True), (False, False)):
            with self.subTest(frontmatter=frontmatter_flag, policy=policy_flag):
                (self.skill_dir / "SKILL.md").write_text(
                    "---\nname: example-skill\ndescription: 用于测试界面元数据的示例技能。\n"
                    f"disable-model-invocation: {'true' if frontmatter_flag else 'false'}\n---\n",
                    encoding="utf-8",
                )
                self.write_yaml(
                    'interface:\n'
                    '  display_name: "Example Skill"\n'
                    '  short_description: "Validate deterministic local skill metadata"\n'
                    '  default_prompt: "Use $example-skill to validate this skill."\n'
                    'policy:\n'
                    f'  allow_implicit_invocation: {"true" if policy_flag else "false"}\n'
                )

                result = validator.validate_root(self.root)

                codes = {issue["code"] for issue in result["issues"]}
                self.assertIn("openai_policy_contradiction", codes)

    def test_inverse_invocation_policy_passes(self):
        (self.skill_dir / "SKILL.md").write_text(
            "---\nname: example-skill\ndescription: 用于测试界面元数据的示例技能。\n"
            "disable-model-invocation: true\n---\n",
            encoding="utf-8",
        )
        self.write_yaml(
            'interface:\n'
            '  display_name: "Example Skill"\n'
            '  short_description: "Validate deterministic local skill metadata"\n'
            '  default_prompt: "Use $example-skill to validate this skill."\n'
            'policy:\n'
            '  allow_implicit_invocation: false\n'
        )

        result = validator.validate_root(self.root)

        self.assertEqual(result["failures"], 0, result["issues"])
        self.assertEqual(result["warnings"], [])

    def test_unpaired_invocation_policy_warns_without_failing(self):
        self.write_yaml(
            'interface:\n'
            '  display_name: "Example Skill"\n'
            '  short_description: "Validate deterministic local skill metadata"\n'
            '  default_prompt: "Use $example-skill to validate this skill."\n'
            'policy:\n'
            '  allow_implicit_invocation: false\n'
        )

        result = validator.validate_root(self.root)

        self.assertEqual(result["failures"], 0, result["issues"])
        self.assertEqual(
            [warning["code"] for warning in result["warnings"]],
            ["openai_policy_unpaired"],
        )

    def test_skill_without_openai_yaml_reports_no_warnings(self):
        result = validator.validate_root(self.root)

        self.assertEqual(result, {"checked": 0, "failures": 0, "issues": [], "warnings": []})

    def test_frontmatter_accepts_yaml_blocks_quotes_and_comments(self):
        path = self.skill_dir / "SKILL.md"
        for description in (
            'description: >\n  Review skill governance: routes and resources.',
            'description: "Review skill governance: routes and resources."',
        ):
            with self.subTest(description=description):
                path.write_text(
                    f"---\nname: example-skill\n{description}\n"
                    "disable-model-invocation: true # manual entry\n"
                    "metadata:\n  version: '1'\n---\n",
                    encoding="utf-8",
                )
                result = validator.validate_frontmatter_root(self.root)
                self.assertEqual(result["checked"], 1)
                self.assertEqual(result["failures"], 0, result["issues"])
                self.assertIsNone(result["records"][0]["description_has_trigger_context"])
                self.assertIs(validator.frontmatter_disable_model_invocation(self.skill_dir), True)

    def test_frontmatter_rejects_malformed_or_duplicate_yaml(self):
        for extra in ("metadata: [", "name: override", "? [a, b]\n: value"):
            with self.subTest(extra=extra):
                (self.skill_dir / "SKILL.md").write_text(
                    "---\nname: example-skill\ndescription: Review skill governance.\n"
                    f"{extra}\n---\n",
                    encoding="utf-8",
                )
                result = validator.validate_frontmatter_root(self.root)
                self.assertFalse(result["records"][0]["valid"])
                self.assertEqual(result["issues"][0]["code"], "frontmatter_parse_error")

    def test_frontmatter_rejects_invalid_types_and_unknown_fields(self):
        for extra in (
            'disable-model-invocation: "false"',
            "disable-model-invocation: on",
            "disable-model-invocation: yes",
            "metadata: [not, a, mapping]",
            "compatibility: false",
            "unknown-field: value",
        ):
            with self.subTest(extra=extra):
                (self.skill_dir / "SKILL.md").write_text(
                    "---\nname: example-skill\ndescription: Review skill governance.\n"
                    f"{extra}\n---\n",
                    encoding="utf-8",
                )
                result = validator.validate_frontmatter_root(self.root)
                self.assertGreater(result["failures"], 0)
                self.assertFalse(result["records"][0]["valid"])

    def test_frontmatter_read_failure_is_not_missing_policy(self):
        (self.skill_dir / "SKILL.md").write_bytes(b"\xff\xfe\xfd")
        result = validator.validate_frontmatter_root(self.root)
        self.assertEqual(result["issues"][0]["code"], "frontmatter_parse_error")
        with self.assertRaises(UnicodeError):
            validator.frontmatter_disable_model_invocation(self.skill_dir)


if __name__ == "__main__":
    unittest.main()
