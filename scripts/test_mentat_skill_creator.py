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


# Contract-text regression for the mentat-skill-creator governance skill.
#
# These tests assert that SKILL.md, agents/openai.yaml and the trigger fixtures
# stay mutually consistent. They do NOT prove model behaviour: passing here says
# nothing about whether an agent honours the declared boundaries. Host routing and
# tier behaviour are defined in mentat-skill-creator/references/host-routing-eval.md
# and are executed by the operator. Read a green run here as "the contract is
# intact", never as "the skill was validated".
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
        self.assertEqual(self.evals["schema_version"], 2)
        cases = self.evals["cases"]
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(len(by_id), len(cases), "duplicate case id")
        required = {
            "explicit_audit_only", "plan_is_not_implementation",
            "explicit_repository_update", "generic_new_skill",
            "installable_plugin_distribution", "local_skill_installation",
            "github_source_publication", "pi_explicit_audit_only",
            "pi_plan_is_not_implementation", "pi_repository_update",
            "pi_unrelated_request_does_not_load_governance_skill",
            "pi_package_distribution", "pi_local_package_installation",
            "pi_publication_preflight_only", "pi_github_source_publication",
            "pi_skill_maintenance_exemption",
        }
        self.assertTrue(required <= set(by_id))
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertIn(case["host_surface"], {"pi", "codex-openai"})
                self.assertIsInstance(case["external_action"], bool)
                self.assertIsInstance(case["prompt"], str)
                self.assertTrue(case["prompt"].strip())
                for field in ("mentat_allowed_mutations", "handoff_allowed_mutations", "required_stop_before"):
                    self.assertIsInstance(case[field], list)
                    self.assertTrue(all(isinstance(value, str) and value for value in case[field]))
                if case["expected_mode"] == "read_only":
                    self.assertEqual(case["mutation_actor"], "none")
                    self.assertEqual(case["mentat_allowed_mutations"], [])
                    self.assertEqual(case["handoff_allowed_mutations"], [])
                    self.assertFalse(case["external_action"])
                if case["mutation_actor"] != "mentat-skill-creator":
                    self.assertEqual(case["mentat_allowed_mutations"], [])
                if case["host_surface"] == "pi":
                    self.assertNotIn("$mentat-skill-creator", case["prompt"])
                    if case["expected_route"] == "mentat-skill-creator":
                        self.assertTrue(case["prompt"].startswith("/skill:mentat-skill-creator"))
                else:
                    self.assertNotIn("/skill:", case["prompt"])
                for condition in case.get("capability_cases", []):
                    self.assertTrue(condition["when"])
                    self.assertTrue(all(isinstance(value, bool) for value in condition["when"].values()))
                    self.assertIsInstance(condition["expected_outcome"], str)
                    if condition["when"].get("handoff_available") is False:
                        self.assertIsNone(condition["expected_handoff"])
                    if condition["expected_outcome"].startswith("blocked"):
                        self.assertEqual(condition["mutation_actor"], "none")
                        self.assertEqual(condition["mentat_allowed_mutations"], [])
                        self.assertEqual(condition["handoff_allowed_mutations"], [])
        for case_id in ("pi_local_package_installation", "pi_github_source_publication"):
            self.assertTrue(by_id[case_id]["required_preconditions"])
            self.assertTrue(any(
                condition["expected_outcome"] == "blocked_missing_required_capability_or_contract"
                for condition in by_id[case_id]["capability_cases"]
            ))
        closed = by_id["pi_skill_maintenance_exemption"]
        self.assertEqual(closed["mentat_allowed_mutations"], ["mentat-skill-creator/SKILL.md"])
        self.assertTrue({"manifest_refresh", "implicit_gate", "implicit_tests"} <= set(closed["required_stop_before"]))

    def test_skill_points_to_host_routing_protocol(self):
        # The protocol carries the only statement of who runs the behavioural
        # eval; dropping the pointer would silently turn static fixtures into
        # the whole verification story again.
        self.assertIn("references/host-routing-eval.md", self.skill_text)
        self.assertIn("references/host-routing-eval.md", self.evals["note"])
        protocol = (SKILL_DIR / "references" / "host-routing-eval.md").read_text(
            encoding="utf-8"
        )
        for marker in (
            "pass|fail",
            "host_surface",
            "reasoning_effort",
            "fresh_loader",
            "model_behavior",
            "skill_sha256",
            "capability_cases",
            "操作者",
            "test_mentat_skill_creator.py",
        ):
            self.assertIn(marker, protocol)

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
        self.assertIn("../scripts/test_mentat_skill_creator.py", self.skill_text)
        self.assertIn("PyYAML", self.skill_text)

    def test_shared_paths_are_explicit_and_within_the_library(self):
        references = set(re.findall(r"\.\./scripts/[A-Za-z0-9_.-]+", self.skill_text))
        self.assertTrue(references)
        for reference in references:
            with self.subTest(reference=reference):
                resolved = (SKILL_DIR / reference).resolve()
                self.assertTrue(resolved.is_relative_to(SKILLS_ROOT.resolve()))
                self.assertTrue(resolved.is_file())

    def test_maintenance_does_not_require_every_gate_or_model(self):
        self.assertIn("维护豁免", self.skill_text)
        self.assertIn("--tests", self.skill_text)
        self.assertIn("启发式告警", self.skill_text)
        self.assertIn("不保证实际触发", self.skill_text)
        self.assertIn("Pi package", self.skill_text)
        self.assertNotIn("每轮取宿主当前可用的最弱档", self.skill_text)


if __name__ == "__main__":
    unittest.main()
