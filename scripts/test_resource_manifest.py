import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import cast

import resource_manifest as manifest


WRAPPER = Path(__file__).with_name("generate_resource_manifests.ps1")


class ResourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    @staticmethod
    def issues(result: dict[str, object]) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], result["issues"])

    def create_skill(self, name: str, body: str = "") -> Path:
        skill_dir = self.root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            "description: 用于测试资源清单生成和校验的示例技能。\n"
            "---\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return skill_dir

    def test_generate_v3_manifest_with_portable_hashes(self):
        skill_dir = self.create_skill("example-skill", "读取 `agents/openai.yaml`。")
        agents_dir = skill_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "openai.yaml").write_text(
            'interface:\n  display_name: "Example"\n', encoding="utf-8"
        )

        result = manifest.generate_manifests(self.root)
        document = json.loads(
            (skill_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(result["written"], 1)
        self.assertEqual(document["schema_version"], 3)
        self.assertEqual(document["skill_md_sha256"], manifest.canonical_sha256(skill_dir / "SKILL.md"))
        dependency = document["declared_local_dependencies"][0]
        self.assertEqual(dependency["resolved_path"], "example-skill/agents/openai.yaml")
        self.assertNotRegex(dependency["resolved_path"], r"^[A-Za-z]:")
        self.assertEqual(
            document["resource_file_hashes"],
            [
                {
                    "path": "agents/openai.yaml",
                    "sha256": manifest.canonical_sha256(agents_dir / "openai.yaml"),
                }
            ],
        )

    def test_timestamped_backup_file_is_ignored(self):
        skill_dir = self.create_skill("example-skill")
        (skill_dir / "SKILL.md.bak_20260829_193004").write_text(
            "stale backup", encoding="utf-8"
        )

        manifest.generate_manifests(self.root)
        document = json.loads(
            (skill_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )

        self.assertNotIn("SKILL.md.bak_20260829_193004", document["top_level_files"])

    def test_explicit_cross_skill_json_reference_is_hashed(self):
        skill_dir = self.create_skill(
            "example-skill",
            "兼容元数据 `example-skill/skill.json` 必须保持一致。",
        )
        legacy_contract = skill_dir / "skill.json"
        legacy_contract.write_text('{"version":"1.0.0"}\n', encoding="utf-8")

        manifest.generate_manifests(self.root)
        document = json.loads(
            (skill_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )

        dependency = document["declared_local_dependencies"][0]
        self.assertEqual(dependency["path"], "example-skill/skill.json")
        self.assertEqual(dependency["resolved_path"], "example-skill/skill.json")
        self.assertEqual(
            dependency["sha256"],
            manifest.canonical_sha256(legacy_contract),
        )

        legacy_contract.write_text('{"version":"2.0.0"}\n', encoding="utf-8")
        result = manifest.check_manifests(self.root)
        codes = {issue["code"] for issue in self.issues(result)}
        self.assertEqual(result["stale"], 1)
        self.assertIn("declared_local_dependencies_mismatch", codes)

    def test_unchanged_manifest_is_byte_stable(self):
        skill_dir = self.create_skill("example-skill")
        first = manifest.generate_manifests(self.root)
        manifest_path = skill_dir / "resource-manifest.json"
        before = manifest_path.read_bytes()

        second = manifest.generate_manifests(self.root)

        self.assertEqual(first["written"], 1)
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_invalid_generated_at_is_rewritten(self):
        skill_dir = self.create_skill("example-skill")
        manifest.generate_manifests(self.root)
        manifest_path = skill_dir / "resource-manifest.json"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["generated_at"] = ""
        manifest_path.write_text(json.dumps(document), encoding="utf-8")

        result = manifest.generate_manifests(self.root)
        refreshed = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result["written"], 1)
        self.assertTrue(refreshed["generated_at"])

    def test_include_scope_does_not_touch_other_skill(self):
        first_dir = self.create_skill("first-skill")
        second_dir = self.create_skill("second-skill")
        manifest.generate_manifests(self.root)
        second_manifest = second_dir / "resource-manifest.json"
        before = second_manifest.read_bytes()
        (first_dir / "SKILL.md").write_text(
            (first_dir / "SKILL.md").read_text(encoding="utf-8") + "changed\n",
            encoding="utf-8",
        )
        (second_dir / "SKILL.md").write_text(
            (second_dir / "SKILL.md").read_text(encoding="utf-8") + "also changed\n",
            encoding="utf-8",
        )

        result = manifest.generate_manifests(self.root, ["first-skill"])

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["written"], 1)
        self.assertEqual(second_manifest.read_bytes(), before)

    def test_check_rejects_schema_v1_and_stale_hash(self):
        skill_dir = self.create_skill("example-skill")
        manifest.generate_manifests(self.root)
        manifest_path = skill_dir / "resource-manifest.json"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["schema_version"] = 1
        document["skill_md_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(document), encoding="utf-8")

        result = manifest.check_manifests(self.root)
        codes = {issue["code"] for issue in self.issues(result)}

        self.assertEqual(result["stale"], 1)
        self.assertIn("schema_version_mismatch", codes)
        self.assertIn("skill_md_sha256_mismatch", codes)

    def test_check_rejects_duplicate_json_keys(self):
        skill_dir = self.create_skill("example-skill")
        manifest.generate_manifests(self.root)
        manifest_path = skill_dir / "resource-manifest.json"
        manifest_path.write_text(
            '{"schema_version":3,"schema_version":2}', encoding="utf-8"
        )

        result = manifest.check_manifests(self.root)

        self.assertEqual(result["stale"], 1)
        self.assertEqual(self.issues(result)[0]["code"], "manifest_parse_error")

    def test_nonportable_dependency_fails_without_overwriting_manifest(self):
        skill_dir = self.create_skill("example-skill")
        manifest.generate_manifests(self.root)
        manifest_path = skill_dir / "resource-manifest.json"
        before = manifest_path.read_bytes()
        (skill_dir / "SKILL.md").write_text(
            (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            + "读取 `references/../../../outside.md`。\n",
            encoding="utf-8",
        )

        result = manifest.generate_manifests(self.root)

        self.assertEqual(result["failed"], 1)
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_missing_dependency_leaves_previous_manifest_intact(self):
        skill_dir = self.create_skill("example-skill")
        manifest.generate_manifests(self.root)
        manifest_path = skill_dir / "resource-manifest.json"
        before = manifest_path.read_bytes()
        (skill_dir / "SKILL.md").write_text(
            (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            + "读取 `references/missing.md`。\n",
            encoding="utf-8",
        )

        result = manifest.generate_manifests(self.root)

        self.assertEqual(result["failed"], 1)
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_crlf_and_lf_have_the_same_text_hash(self):
        lf_path = self.root / "lf.md"
        crlf_path = self.root / "crlf.md"
        lf_path.write_bytes(b"one\ntwo\n")
        crlf_path.write_bytes(b"one\r\ntwo\r\n")

        self.assertEqual(
            manifest.canonical_sha256(lf_path),
            manifest.canonical_sha256(crlf_path),
        )

    def test_env_example_crlf_and_lf_have_the_same_text_hash(self):
        lf_path = self.root / ".env.example"
        crlf_path = self.root / ".env.local"
        lf_path.write_bytes(b"TOKEN=placeholder\n")
        crlf_path.write_bytes(b"TOKEN=placeholder\r\n")

        self.assertEqual(
            manifest.canonical_sha256(lf_path),
            manifest.canonical_sha256(crlf_path),
        )

    def test_unreferenced_resource_content_drift_is_detected(self):
        skill_dir = self.create_skill("example-skill")
        references = skill_dir / "references"
        references.mkdir()
        resource = references / "unreferenced.md"
        resource.write_text("before\n", encoding="utf-8")
        manifest.generate_manifests(self.root)
        resource.write_text("after\n", encoding="utf-8")

        result = manifest.check_manifests(self.root)
        codes = {issue["code"] for issue in self.issues(result)}

        self.assertEqual(result["stale"], 1)
        self.assertIn("resource_file_hashes_mismatch", codes)

    def test_top_level_config_is_hashed_and_content_drift_is_detected(self):
        skill_dir = self.create_skill("example-skill")
        config = skill_dir / "config.json"
        config.write_text('{"baseUrl":"before"}\n', encoding="utf-8")
        manifest.generate_manifests(self.root)
        document = json.loads(
            (skill_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )
        top_level_hashes = {
            entry["path"]: entry["sha256"]
            for entry in document["top_level_file_hashes"]
        }

        self.assertIn("config.json", document["top_level_files"])
        self.assertEqual(
            top_level_hashes["config.json"], manifest.canonical_sha256(config)
        )

        config.write_text('{"baseUrl":"after"}\n', encoding="utf-8")
        result = manifest.check_manifests(self.root)
        codes = {issue["code"] for issue in self.issues(result)}

        self.assertEqual(result["stale"], 1)
        self.assertIn("top_level_file_hashes_mismatch", codes)

    def test_unknown_top_level_directory_content_drift_is_detected(self):
        skill_dir = self.create_skill("example-skill")
        custom = skill_dir / "custom"
        custom.mkdir()
        resource = custom / "contract.dat"
        resource.write_text("before\n", encoding="utf-8")
        manifest.generate_manifests(self.root)
        resource.write_text("after\n", encoding="utf-8")

        result = manifest.check_manifests(self.root)
        codes = {issue["code"] for issue in self.issues(result)}

        self.assertEqual(result["stale"], 1)
        self.assertIn("resource_file_hashes_mismatch", codes)

    def test_conceptual_resource_namespace_without_file_suffix_is_ignored(self):
        skill_dir = self.create_skill(
            "example-skill",
            "将核验结果登记为 `references/verified` 条目。",
        )

        result = manifest.generate_manifests(self.root)

        self.assertEqual(result["failed"], 0)
        document = json.loads(
            (skill_dir / "resource-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["declared_local_dependencies"], [])

    def test_batch_preflight_failure_writes_no_other_manifest(self):
        valid_dir = self.create_skill("a-valid-skill")
        invalid_dir = self.create_skill(
            "z-invalid-skill", "读取 `references/missing.md`。"
        )

        result = manifest.generate_manifests(self.root)

        self.assertEqual(result["failed"], 1)
        self.assertFalse((valid_dir / "resource-manifest.json").exists())
        self.assertFalse((invalid_dir / "resource-manifest.json").exists())

    def test_powershell_wrapper_accepts_omitted_include_scope(self):
        skill_dir = self.create_skill("example-skill")

        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WRAPPER),
                "-Root",
                str(self.root),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((skill_dir / "resource-manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
