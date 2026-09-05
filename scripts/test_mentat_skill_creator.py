import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml


SKILLS_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = SKILLS_ROOT / "mentat-skill-creator"


def governance_path(skills_root: Path) -> Path:
    """Prefer repository governance; support the installed Pi directory layout."""
    repository_path = skills_root / "AGENTS.md"
    if repository_path.is_file():
        return repository_path
    installed_path = skills_root.parent / "AGENTS.md"
    if skills_root.name == "skills" and installed_path.is_file():
        return installed_path
    raise FileNotFoundError(f"No governance file for skills root: {skills_root}")


class GovernancePathTests(unittest.TestCase):
    def test_repository_path_wins_over_host(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "skills"
            root.mkdir()
            (parent / "AGENTS.md").write_text("host", encoding="utf-8")
            (root / "AGENTS.md").write_text("repository", encoding="utf-8")
            self.assertEqual(governance_path(root), root / "AGENTS.md")

    def test_installed_layout_uses_host(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "skills"
            root.mkdir()
            (parent / "AGENTS.md").write_text("host", encoding="utf-8")
            self.assertEqual(governance_path(root), parent / "AGENTS.md")

    def test_standalone_checkout_does_not_consume_unrelated_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "checkout"
            root.mkdir()
            (parent / "AGENTS.md").write_text("unrelated", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                governance_path(root)

    def test_missing_governance_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skills"
            root.mkdir()
            with self.assertRaises(FileNotFoundError):
                governance_path(root)


class MentatSkillCreatorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.metadata = yaml.safe_load(
            (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        cls.evals = json.loads(
            (SKILL_DIR / "references" / "trigger-evals.json").read_text(
                encoding="utf-8"
            )
        )
        cls.readme_text = (SKILLS_ROOT / "README.md").read_text(encoding="utf-8")
        cls.trigger_matrix = json.loads(
            (SKILLS_ROOT / "shared" / "trigger-ownership-matrix.json").read_text(
                encoding="utf-8"
            )
        )

    def test_default_prompt_is_read_only_and_explicit(self):
        prompt = self.metadata["interface"]["default_prompt"]
        self.assertIn("$mentat-skill-creator", prompt)
        self.assertRegex(prompt, r"(?i)read-only")
        self.assertNotRegex(prompt, r"(?i)\b(update|modify|fix|implement)\b")
        self.assertIs(
            self.metadata["policy"]["allow_implicit_invocation"], False
        )

    def test_authority_contract_does_not_promote_readme(self):
        self.assertNotIn("以 README 为准", self.skill_text)
        self.assertIn("README、manifest、门禁和测试都视为受检制品", self.skill_text)
        self.assertIn("不得扩张权限", self.readme_text)

    def test_optional_host_governance_preserves_precedence(self):
        # Standalone source publication does not install a host runtime contract.
        try:
            path = governance_path(SKILLS_ROOT)
        except FileNotFoundError:
            self.skipTest("No host/repository AGENTS.md in standalone source checkout")
        self.assertRegex(
            path.read_text(encoding="utf-8"),
            r"System, developer, managed runtime, and explicit user instructions retain their normal precedence"
            r"|Follow system and developer rules first",
        )

    def test_readme_declares_personal_diary_autosave_exception(self):
        row = next(
            line
            for line in self.readme_text.splitlines()
            if line.startswith("| `personal-diary-writer` |")
        )
        self.assertIn("personal-diary-request-v1", row)
        self.assertNotIn("| 普通个人日记、", row)

    def test_release_routes_are_explicit(self):
        for marker in ("plugin-creator", "skill-installer", "GitHub", "本地安装"):
            self.assertIn(marker, self.skill_text)
        self.assertRegex(self.skill_text, r"(?i)commit|push|发布")

    def test_trigger_eval_matrix_covers_required_routes(self):
        cases = self.evals["cases"]
        by_id = {case["id"]: case for case in cases}
        expected = {
            "explicit_audit_only": (
                "mentat-skill-creator", None, "read_only", False, "none"
            ),
            "plan_is_not_implementation": (
                "mentat-skill-creator", None, "read_only", False, "none"
            ),
            "explicit_repository_update": (
                "mentat-skill-creator", None, "scoped_edit", False,
                "mentat-skill-creator",
            ),
            "generic_new_skill": (
                "skill-creator", "skill-creator", "handoff", False, "handoff"
            ),
            "unrelated_single_skill_copy_edit": (
                "skill-creator-or-domain-skill",
                "skill-creator-or-domain-skill",
                "handoff",
                False,
                "handoff",
            ),
            "installable_plugin_distribution": (
                "plugin-creator", "plugin-creator", "handoff", False, "handoff"
            ),
            "local_skill_installation": (
                "skill-installer", "skill-installer", "handoff", True, "handoff"
            ),
            "github_source_publication": (
                "mentat-skill-creator",
                "github:yeet",
                "read_only_preflight_then_separate_external_action",
                True,
                "handoff",
            ),
        }
        expected_prompts = {
            "explicit_audit_only": "使用 $mentat-skill-creator 只读审计当前 skills 库的触发边界，不要修改文件。",
            "plan_is_not_implementation": "使用 $mentat-skill-creator 分析资源清单问题并编制修改方案和计划。",
            "explicit_repository_update": "使用 $mentat-skill-creator 修复 skills 根 Gate 的局部校验；只修改 scripts/repair_skills.ps1 和 scripts/test_repair_skills.py，不要修改 manifest、README、AGENTS 或 shared 文件，并运行只读验证。",
            "generic_new_skill": "创建一个用于 CSV 清洗的新技能。",
            "unrelated_single_skill_copy_edit": "把 personal-health-analysis 的说明文字写得更清楚。",
            "installable_plugin_distribution": "把两个技能打包成其他人可安装的 Codex 插件，本轮只生成本地插件包。",
            "local_skill_installation": "从已指定的仓库安装一个 Codex skill 到本地技能目录。",
            "github_source_publication": "使用 $mentat-skill-creator 完成本库发布前验证，然后同步到 GitHub main。",
        }
        expected_handoff_mutations = {
            "explicit_audit_only": [],
            "plan_is_not_implementation": [],
            "explicit_repository_update": [],
            "generic_new_skill": ["user_selected_skill_directory"],
            "unrelated_single_skill_copy_edit": ["personal-health-analysis/SKILL.md"],
            "installable_plugin_distribution": ["user_selected_plugin_directory"],
            "local_skill_installation": ["approved_local_skill_install_target"],
            "github_source_publication": ["git_commit", "git_push:explicit-remote/main"],
        }
        expected_stops = {
            "explicit_audit_only": ["any_file_write", "any_external_action"],
            "plan_is_not_implementation": ["any_file_write", "any_external_action"],
            "explicit_repository_update": ["manifest_refresh", "root_governance_edit", "any_external_action"],
            "generic_new_skill": ["mentat_repository_edit"],
            "unrelated_single_skill_copy_edit": ["mentat_repository_edit"],
            "installable_plugin_distribution": ["mentat_source_edit", "plugin_publication"],
            "local_skill_installation": ["mentat_repository_edit", "install_without_explicit_request"],
            "github_source_publication": ["local_file_repair", "unscoped_stage", "push_to_unconfirmed_remote_or_branch"],
        }
        expected_preconditions = {
            "github_source_publication": [
                "git_worktree",
                "explicit_remote",
                "explicit_branch",
                "scoped_staged_diff",
                "clean_checkout_validation",
            ]
        }
        self.assertEqual(set(by_id), set(expected))
        for case in cases:
            self.assertEqual(case["prompt"], expected_prompts[case["id"]])
            self.assertEqual(
                (
                    case["expected_route"],
                    case["expected_handoff"],
                    case["expected_mode"],
                    case["external_action"],
                    case["mutation_actor"],
                ),
                expected[case["id"]],
            )
            self.assertEqual(case["mentat_allowed_mutations"], [] if case["mutation_actor"] != "mentat-skill-creator" else ["scripts/repair_skills.ps1", "scripts/test_repair_skills.py"])
            self.assertEqual(
                case["handoff_allowed_mutations"],
                expected_handoff_mutations[case["id"]],
            )
            self.assertEqual(
                case["required_stop_before"], expected_stops[case["id"]]
            )
            self.assertEqual(
                case.get("required_preconditions", []),
                expected_preconditions.get(case["id"], []),
            )

    def test_trigger_ownership_declares_handoffs_and_negative_signals(self):
        classes = [
            item
            for domain in self.trigger_matrix["domains"]
            if domain["domain"] == "skill_governance"
            for item in domain["classes"]
        ]
        contract = next(
            item
            for item in classes
            if item["primary_skill"] == "mentat-skill-creator"
        )
        self.assertEqual(
            set(contract["handoff_skills"]),
            {
                "system:skill-creator",
                "system:plugin-creator",
                "system:skill-installer",
                "plugin:github:yeet",
            },
        )
        self.assertEqual(
            contract["request_signals"],
            [
                "audit local codex skills library",
                "repair skill trigger conflicts",
                "update skills readme and gate",
                "validate skills library before publishing",
            ],
        )
        self.assertEqual(
            contract["should_not_trigger_signals"],
            [
                "create a generic new skill",
                "edit one skill without repository governance",
                "package skills as an installable plugin",
                "install a skill from another repository",
            ],
        )

    def test_skill_points_to_scoped_manifest_and_gate_checks(self):
        self.assertRegex(
            self.skill_text,
            re.compile(r"generate_resource_manifests\.ps1[^\n]+-IncludeSkills", re.I),
        )
        self.assertRegex(
            self.skill_text,
            re.compile(r"repair_skills\.ps1[^\n]+-IncludeSkills", re.I),
        )
        self.assertIn("scripts/test_mentat_skill_creator.py", self.skill_text)
        self.assertIn("PyYAML", self.skill_text)


if __name__ == "__main__":
    unittest.main()
