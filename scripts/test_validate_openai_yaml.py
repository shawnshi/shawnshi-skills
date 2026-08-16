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


if __name__ == "__main__":
    unittest.main()
