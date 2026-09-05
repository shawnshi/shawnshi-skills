import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("repair_skills.ps1")
RESOURCE_MANIFEST_SCRIPT = Path(__file__).with_name("resource_manifest.py")
OPENAI_YAML_SCRIPT = Path(__file__).with_name("validate_openai_yaml.py")


class RepairSkillsPersistenceTests(unittest.TestCase):
    def regenerate_manifests(self, root: Path) -> None:
        generated = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(root / "scripts" / RESOURCE_MANIFEST_SCRIPT.name),
                "generate",
                "--root",
                str(root),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)

    def build_fixture(
        self,
        *,
        declared: bool,
        has_opt_out: bool = True,
        contract_line: str = "正式结果自动保存到权威档案。",
        table_row: str | None = None,
        duplicate_row: bool = False,
        script_fixture: str | None = None,
        skill_name: str = "example-skill",
    ) -> Path:
        temp_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp_root, ignore_errors=True)

        scripts_dir = temp_root / "scripts"
        scripts_dir.mkdir()
        shutil.copy2(SCRIPT_PATH, scripts_dir / SCRIPT_PATH.name)
        shutil.copy2(RESOURCE_MANIFEST_SCRIPT, scripts_dir / RESOURCE_MANIFEST_SCRIPT.name)
        shutil.copy2(OPENAI_YAML_SCRIPT, scripts_dir / OPENAI_YAML_SCRIPT.name)

        exception_block = ""
        if declared:
            row = table_row or f"| `{skill_name}` | generate | archive | preview |"
            duplicate = f"\n{row}" if duplicate_row else ""
            exception_block = """
<!-- automatic-persistence-exceptions:start -->
| Skill | Request | Target | Opt-out |
|---|---|---|---|
{row}{duplicate}
<!-- automatic-persistence-exceptions:end -->
""".format(row=row, duplicate=duplicate)
        (temp_root / "README.md").write_text(
            "当前库存为 1 个用户技能。\n" + exception_block,
            encoding="utf-8",
        )

        shared_dir = temp_root / "shared"
        shared_dir.mkdir()
        (shared_dir / "trigger-ownership-matrix.json").write_text(
            json.dumps({"domains": []}),
            encoding="utf-8",
        )

        skill_dir = temp_root / skill_name
        skill_dir.mkdir()
        opt_out = "\n用户要求预览或不保存时保持只读。" if has_opt_out else ""
        (skill_dir / "SKILL.md").write_text(
            """---
name: example-skill
description: 用于测试根门禁的示例技能。
---

"""
            + contract_line
            + opt_out,
            encoding="utf-8",
        )
        if script_fixture is not None:
            fixture_dir = skill_dir / "scripts"
            fixture_dir.mkdir()
            (fixture_dir / "test_contract.py").write_text(
                script_fixture,
                encoding="utf-8",
            )
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8").replace(
            "name: example-skill", f"name: {skill_name}", 1
        )
        (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
        self.regenerate_manifests(temp_root)
        return temp_root

    def run_gate(
        self,
        root: Path,
        include_skills: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        command = [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "scripts" / SCRIPT_PATH.name),
                "-Mode",
                "Gate",
                "-Root",
                str(root),
            ]
        if include_skills:
            command.extend(["-IncludeSkills", *include_skills])
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_gate_rejects_undeclared_automatic_persistence(self):
        result = self.run_gate(self.build_fixture(declared=False))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared_automatic_persistence_skills=1", result.stderr)

    def test_gate_accepts_declared_automatic_persistence_with_opt_out(self):
        result = self.run_gate(self.build_fixture(declared=True))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Skill audit gate passed.", result.stdout)

    def test_gate_accepts_supported_optional_frontmatter(self):
        root = self.build_fixture(declared=True)
        skill_path = root / "example-skill" / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        skill_path.write_text(
            text.replace(
                "description: 用于测试根门禁的示例技能。\n",
                "description: 用于测试根门禁的示例技能。\n"
                "disable-model-invocation: true\n"
                "metadata:\n"
                "  version: test\n",
            ),
            encoding="utf-8",
        )
        self.regenerate_manifests(root)

        result = self.run_gate(root)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gate_rejects_declared_contract_without_opt_out(self):
        result = self.run_gate(
            self.build_fixture(declared=True, has_opt_out=False)
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic_persistence_opt_out_failures=1", result.stderr)

    def test_gate_rejects_default_atomic_archive_when_undeclared(self):
        result = self.run_gate(
            self.build_fixture(
                declared=False,
                contract_line="正式结果默认原子保存到权威档案。",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared_automatic_persistence_skills=1", result.stderr)

    def test_gate_rejects_direct_archive_without_separate_confirmation(self):
        result = self.run_gate(
            self.build_fixture(
                declared=False,
                contract_line="正式结果无需再次确认，直接写入 canonical archive。",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared_automatic_persistence_skills=1", result.stderr)

    def test_gate_does_not_treat_direct_save_negation_as_persistence(self):
        result = self.run_gate(
            self.build_fixture(
                declared=False,
                has_opt_out=False,
                contract_line="正式结果不自动保存到档案；明确保存后才写入。",
            )
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gate_rejects_preview_word_without_read_only_exit(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                has_opt_out=False,
                contract_line="正式结果自动保存到权威档案，预览图也自动保存。",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic_persistence_opt_out_failures=1", result.stderr)

    def test_gate_rejects_malformed_contract_table_row(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                table_row="| `example-skill` | generate |  | preview |",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic_persistence_table_malformed_rows=1", result.stderr)

    def test_gate_rejects_unquoted_persistence_table_skill(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                table_row="| example-skill | generate | archive | preview |",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic_persistence_table_malformed_rows=1", result.stderr)

    def test_gate_rejects_duplicate_contract_table_row(self):
        result = self.run_gate(
            self.build_fixture(declared=True, duplicate_row=True)
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic_persistence_table_duplicate_skills=1", result.stderr)

    def test_test_fixture_cannot_keep_a_stale_declaration_green(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                has_opt_out=False,
                contract_line="只生成草稿；明确要求保存后才写入。",
                script_fixture='CONTRACT = "正式结果自动保存到权威档案。"',
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale_automatic_persistence_exceptions=1", result.stderr)

    def test_gate_rejects_undeclared_default_personal_log_write(self):
        result = self.run_gate(
            self.build_fixture(
                declared=False,
                contract_line="正式日志默认写入个人日志文件。",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared_automatic_persistence_skills=1", result.stderr)

    def test_gate_rejects_undeclared_direct_local_log_file_write(self):
        result = self.run_gate(
            self.build_fixture(
                declared=False,
                contract_line="生成日志后直接落盘到本地文件。",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared_automatic_persistence_skills=1", result.stderr)

    def test_gate_rejects_additional_affirmative_archive_phrasings(self):
        contracts = (
            "默认将内容保存到权威档案。",
            "生成请求本身就是保存许可，结果写入权威档案。",
            "完成后会将结果存入长期状态数据库。",
            "默认把结果写进知识库。",
            "Results are automatically stored in canonical store.",
            "Results are archived by default.",
            "No additional confirmation is required before writing to archive.",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                result = self.run_gate(
                    self.build_fixture(declared=False, contract_line=contract)
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "undeclared_automatic_persistence_skills=1",
                    result.stderr,
                )

    def test_gate_allows_explicit_archive_prohibitions(self):
        contracts = (
            "禁止把正式结果自动保存到权威档案。",
            "Results must not automatically save to archive.",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                result = self.run_gate(
                    self.build_fixture(
                        declared=False,
                        has_opt_out=False,
                        contract_line=contract,
                    )
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )

    def test_gate_rejects_schema_v1_manifest(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        manifest_path = root / "example-skill" / "resource-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid_resource_manifests=1", result.stderr)

    def test_gate_rejects_validator_checked_count_mismatch(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        (root / "scripts" / RESOURCE_MANIFEST_SCRIPT.name).write_text(
            'import json\nprint(json.dumps({"checked": 0, "stale": 0, "issues": []}))\n',
            encoding="utf-8",
        )

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validator_integration_failures=1", result.stderr)

    def test_gate_rejects_stale_skill_hash(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        skill_path = root / "example-skill" / "SKILL.md"
        skill_path.write_text(
            skill_path.read_text(encoding="utf-8") + "\n新增未索引内容。\n",
            encoding="utf-8",
        )

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid_resource_manifests=1", result.stderr)

    def test_gate_rejects_malformed_openai_yaml(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        agents = root / "example-skill" / "agents"
        agents.mkdir()
        (agents / "openai.yaml").write_text("interface: [\n", encoding="utf-8")
        self.regenerate_manifests(root)

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("openai_metadata_failures=1", result.stderr)

    def test_gate_rejects_wrong_default_prompt_skill_token(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        agents = root / "example-skill" / "agents"
        agents.mkdir()
        (agents / "openai.yaml").write_text(
            "interface:\n"
            "  display_name: Example Skill\n"
            "  short_description: 这是一个用于验证界面元数据门禁行为的示例技能描述。\n"
            "  default_prompt: Use $wrong-skill for this request.\n",
            encoding="utf-8",
        )
        self.regenerate_manifests(root)

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("openai_metadata_failures=1", result.stderr)

    def test_selection_gate_does_not_compare_inventory_to_selection(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")

        result = self.run_gate(root, ("example-skill",))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Selection", result.stdout)

    def test_gate_rejects_unknown_include_skill(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")

        result = self.run_gate(root, ("missing-skill",))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown_include_skills=1", result.stderr)

    def test_gate_rejects_unknown_exclude_skill(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "scripts" / SCRIPT_PATH.name),
                "-Mode",
                "Gate",
                "-Root",
                str(root),
                "-ExcludeSkills",
                "missing-skill",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown_exclude_skills=1", result.stderr)

    def test_gate_rejects_empty_selection(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "scripts" / SCRIPT_PATH.name),
                "-Mode",
                "Gate",
                "-Root",
                str(root),
                "-IncludeSkills",
                "example-skill",
                "-ExcludeSkills",
                "example-skill",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty_selection=1", result.stderr)
        self.assertIn("scope_overlap_skills=1", result.stderr)

    def test_gate_honors_validator_nonzero_exit_even_with_green_json(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        (root / "scripts" / RESOURCE_MANIFEST_SCRIPT.name).write_text(
            'import json\nprint(json.dumps({"checked": 1, "stale": 0, "issues": []}))\nraise SystemExit(2)\n',
            encoding="utf-8",
        )

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validator_integration_failures=1", result.stderr)

    def test_selection_gate_filters_unrelated_trigger_noise_but_keeps_related_errors(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        matrix_path = root / "shared" / "trigger-ownership-matrix.json"
        matrix = {
            "domains": [
                {
                    "domain": "unrelated",
                    "classes": [
                        {
                            "id": "unrelated_bad_owner",
                            "primary_skill": "missing-unrelated-skill",
                            "secondary_skills": [],
                            "request_signals": ["unrelated signal"],
                        }
                    ],
                },
                {
                    "domain": "selected",
                    "classes": [
                        {
                            "id": "selected_contract",
                            "primary_skill": "example-skill",
                            "secondary_skills": [],
                            "request_signals": ["selected signal"],
                        }
                    ],
                },
            ]
        }
        matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

        unrelated_only = self.run_gate(root, ("example-skill",))
        self.assertEqual(
            unrelated_only.returncode,
            0,
            unrelated_only.stdout + unrelated_only.stderr,
        )

        matrix["domains"][1]["classes"][0]["secondary_skills"] = [
            "missing-related-skill"
        ]
        matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
        related_error = self.run_gate(root, ("example-skill",))
        self.assertNotEqual(related_error.returncode, 0)
        self.assertIn("trigger_ownership_conflicts=1", related_error.stderr)

    def test_selection_gate_ignores_unrelated_hygiene_and_table_failures(self):
        root = self.build_fixture(declared=False, contract_line="只生成草稿。")
        unrelated = root / "other-skill"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_text(
            "---\nname: other-skill\ndescription: 用于局部门禁噪声隔离的其他技能。\n---\n",
            encoding="utf-8",
        )
        (unrelated / "skill.json").write_text("{}", encoding="utf-8")
        (root / "README.md").write_text(
            "当前库存为 2 个用户技能。\n"
            "<!-- automatic-persistence-exceptions:start -->\n"
            "| Skill | Request | Target | Opt-out |\n"
            "|---|---|---|---|\n"
            "| `other-skill` | anything | 任意位置 | maybe |\n"
            "<!-- automatic-persistence-exceptions:end -->\n",
            encoding="utf-8",
        )

        result = self.run_gate(root, ("example-skill",))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_named_skill_does_not_bypass_persistence_gate(self):
        root = self.build_fixture(
            declared=False,
            skill_name="personal-cognitive-auditor",
        )

        result = self.run_gate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared_automatic_persistence_skills=1", result.stderr)

    def test_default_authorization_exclusion_is_not_persistence(self):
        result = self.run_gate(
            self.build_fixture(
                declared=False,
                has_opt_out=False,
                contract_line=(
                    "默认授权不包含令牌持久化、本地数据库同步或任何第二处持久化。"
                ),
            )
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gate_rejects_unrelated_preview_read_only_phrase_as_opt_out(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                has_opt_out=False,
                contract_line=(
                    "预览图保持只读；正式结果自动保存到权威档案。"
                ),
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("automatic_persistence_opt_out_failures=1", result.stderr)

    def test_gate_rejects_semantically_open_contract_table(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                table_row=(
                    "| `example-skill` | anything | 任意位置，包括外部系统 | maybe |"
                ),
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "automatic_persistence_table_semantic_failures=1",
            result.stderr,
        )

    def test_gate_rejects_unknown_contract_skill(self):
        result = self.run_gate(
            self.build_fixture(
                declared=True,
                table_row="| `unknown-skill` | generate | archive | preview |",
            )
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown_automatic_persistence_exceptions=1", result.stderr)

    def test_gate_rejects_common_automatic_persistence_verbs(self):
        contracts = (
            "结果会自动持久化到数据库。",
            "生成日志后会自动追加到日记中。",
            "每次执行都会自动同步到历史数据库。",
            "The result is persisted to the database automatically.",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                result = self.run_gate(
                    self.build_fixture(declared=False, contract_line=contract)
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "undeclared_automatic_persistence_skills=1",
                    result.stderr,
                )

    def test_gate_allows_explicit_authorization_negation(self):
        contracts = (
            "生成请求不构成保存授权，不写入权威档案。",
            "The request is not authorization to write to the archive.",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                result = self.run_gate(
                    self.build_fixture(
                        declared=False,
                        has_opt_out=False,
                        contract_line=contract,
                    )
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + result.stderr,
                )


if __name__ == "__main__":
    unittest.main()
