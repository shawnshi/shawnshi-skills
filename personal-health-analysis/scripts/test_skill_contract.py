import hashlib
import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parent
CANONICAL_TEXT_HASH_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".ps1",
    ".sh",
    ".csx",
    ".cs",
    ".svg",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
    ".html",
    ".css",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
}
CANONICAL_TEXT_HASH_NAMES = {".gitignore", ".gitattributes", ".editorconfig"}


def sha256(path: Path) -> str:
    payload = path.read_bytes()
    if (
        path.suffix.lower() in CANONICAL_TEXT_HASH_SUFFIXES
        or path.name.lower() in CANONICAL_TEXT_HASH_NAMES
    ):
        text = payload.decode("utf-8")
        payload = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SkillContractTests(unittest.TestCase):
    def test_default_dependencies_are_isolated_and_exclude_unsafe_sync_pair(self):
        requirements = (SKILL_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("garminconnect==0.3.9", requirements)
        self.assertNotRegex(requirements, r"(?m)^garmindb(?:[<=> @]|$)")

        locked = {
            line.strip()
            for line in (SKILL_ROOT / "requirements.lock.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(
            locked,
            {
                "certifi==2026.7.22",
                "cffi==2.1.1",
                "charset-normalizer==3.4.9",
                "curl-cffi==0.16.0",
                "fitparse==1.2.0",
                "garminconnect==0.3.9",
                "gpxpy==1.6.2",
                "idna==3.18",
                "numpy==2.5.1",
                "pandas==3.0.3",
                "pycparser==3.0",
                "python-dateutil==2.9.0.post0",
                "requests==2.34.2",
                "six==1.17.0",
                "tzdata==2026.3",
                "ua-generator==2.1.3",
                "urllib3==2.7.0",
            },
        )
        self.assertFalse(any(item.startswith("garmindb==") for item in locked))

        for installer_name in ("install.ps1", "install.sh"):
            installer = (SKILL_ROOT / installer_name).read_text(encoding="utf-8")
            self.assertNotIn("--user", installer)
            self.assertIn("venv", installer.lower())
            self.assertIn("requirements.lock.txt", installer)
            self.assertIn("wheelhouse-manifest.json", installer)
            self.assertIn("wheelhouse_integrity.py", installer)
            self.assertIn("generate-hash-requirements", installer)
            self.assertIn("--require-hashes", installer)
            self.assertIn("--only-binary=:all:", installer)
            self.assertIn("--no-index", installer)
            self.assertIn("--isolated", installer)
            self.assertIn("installed_environment_gate.py", installer)
            self.assertIn("pip --isolated check", installer)
            self.assertIn("publish_directory_no_replace.py", installer)
            self.assertIn("already exists", installer)

    def test_documented_commands_use_a_verified_current_interpreter(self):
        documents = [
            SKILL_ROOT / "SKILL.md",
            SKILL_ROOT / "references" / "api.md",
            SKILL_ROOT / "references" / "advanced_tools.md",
            SKILL_ROOT / "references" / "external_acceptance.md",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in documents)
        self.assertIn("<SKILL_PYTHON> scripts/garmin_data.py", combined)
        self.assertIn("<SKILL_PYTHON> scripts/runtime_preflight.py --mode local", combined)
        self.assertNotIn("必须解析为该隔离环境的解释器", combined)
        self.assertNotIn("必须是技能隔离 `.venv` 中的解释器", combined)
        self.assertNotRegex(combined, r"(?m)(?:^|\s)python3?\s+scripts/")
        self.assertNotRegex(combined, r"(?m)(?:^|\s)python\.exe\s+scripts/")
        self.assertNotIn("from garminconnect import Garmin", combined)
        for flag in ("--allow-health-data", "--allow-token-write", "--allow-download"):
            self.assertIn(flag, combined)

    def test_skill_commands_preserve_cli_permission_and_no_implicit_trigger(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("RUNTIME_DEPENDENCY_UNAVAILABLE", skill_text)
        for script_name in ("garmin_data.py", "garmin_intelligence.py", "garmin_chart.py"):
            self.assertRegex(
                skill_text,
                rf"{script_name}[^\n]*--source local[^\n]*--allow-health-data",
            )
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_live_fallback_is_bound_to_no_data_network_and_exact_components(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        api_text = (SKILL_ROOT / "references" / "api.md").read_text(
            encoding="utf-8"
        )
        combined = skill_text + "\n" + api_text
        self.assertIn("--fallback-live", combined)
        self.assertIn("--components", combined)
        self.assertIn("no_data", combined)
        self.assertIn("--allow-network", combined)
        self.assertIn("一次实时只读回退", combined)
        self.assertIn("同一窗口和组件", combined)
        self.assertNotIn("本地读取失败不得自动切换到实时接口", combined)

    def test_explicit_skill_invocation_defaults_health_read_but_not_side_effects(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        api_text = (SKILL_ROOT / "references" / "api.md").read_text(
            encoding="utf-8"
        )
        advanced_text = (SKILL_ROOT / "references" / "advanced_tools.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((skill_text, api_text, advanced_text))
        self.assertIn("显式调用本技能即授权", combined)
        self.assertIn("默认最近 7 天", combined)
        self.assertIn(
            "sleep,hrv,body_battery,heart_rate,stress",
            combined,
        )
        self.assertIn("`activities` 与 `training_load_series`", combined)
        self.assertIn("明确请求", combined)
        self.assertIn("自动附加 `--allow-health-data`", combined)
        self.assertIn("自动附加 `--allow-network`", combined)
        self.assertIn("本地 `no_data` 后、同窗口、同组件", skill_text)
        for independent_grant in (
            "--allow-token-write",
            "--allow-sync",
            "--allow-download",
        ):
            self.assertIn(independent_grant, combined)
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("after explicit local no_data automatically use one bounded live read-only fallback", metadata)
        self.assertIn("Ask separately before login, token writes, sync, downloads", metadata)
        self.assertNotIn("ask separately before network", metadata)
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_sync_contract_requires_plan_and_explicit_runner(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        sync_source = (SKILL_ROOT / "scripts" / "sync_health_data.py").read_text(
            encoding="utf-8"
        )
        for flag in (
            "--plan-output",
            "--plan-file",
            "--config-dir",
            "--garmindb-python",
        ):
            self.assertIn(flag, skill_text)
        self.assertNotIn("shutil.which", sync_source)
        self.assertIn("trusted_garmindb_python_required", sync_source)
        self.assertIn("SYNC_PLAN_VERSION = 2", sync_source)
        self.assertIn('"garmindb": "3.8.0"', sync_source)
        self.assertIn('"garminconnect": "0.3.9"', sync_source)
        self.assertIn("site_packages_tree_sha256", sync_source)
        self.assertIn("plan_bindings_mismatch", sync_source)

    def test_manifest_hashes_all_declared_dependencies(self):
        manifest = json.loads(
            (SKILL_ROOT / "resource-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["schema_version"], 3)
        self.assertEqual(manifest["hash_algorithm"], "SHA-256")
        self.assertEqual(manifest["text_hash_normalization"], "LF")
        self.assertEqual(manifest["skill_md_sha256"], sha256(SKILL_ROOT / "SKILL.md"))
        self.assertEqual(manifest["missing_declared_dependencies"], [])
        self.assertNotIn(".jules", manifest["top_level_directories"])

        top_hashes = {
            item["path"]: item["sha256"]
            for item in manifest["top_level_file_hashes"]
        }
        self.assertEqual(set(top_hashes), set(manifest["top_level_files"]))
        for relative, digest in top_hashes.items():
            with self.subTest(top_level_file=relative):
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
                self.assertEqual(digest, sha256(SKILL_ROOT / relative))

        for dependency in manifest["declared_local_dependencies"]:
            with self.subTest(path=dependency["path"]):
                self.assertTrue(dependency["exists"])
                relative = dependency["resolved_path"]
                self.assertIsInstance(relative, str)
                self.assertNotRegex(relative, r"^[A-Za-z]:|^[/\\]")
                resolved = REPO_ROOT.joinpath(*relative.split("/"))
                self.assertTrue(resolved.is_file())
                self.assertRegex(dependency["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(dependency["sha256"], sha256(resolved))

    def test_trigger_matrix_owns_health_integrity_signals(self):
        matrix = json.loads(
            (REPO_ROOT / "shared" / "trigger-ownership-matrix.json").read_text(
                encoding="utf-8"
            )
        )
        classes = [
            item
            for domain in matrix["domains"]
            for item in domain["classes"]
            if item["id"] == "personal_wearable_health_analysis"
        ]
        self.assertEqual(len(classes), 1)
        contract = classes[0]
        self.assertEqual(contract["primary_skill"], "personal-health-analysis")
        self.assertIn(
            "verify local garmin database snapshot integrity",
            contract["request_signals"],
        )
        self.assertIn(
            "audit garmin device firmware epochs",
            contract["request_signals"],
        )

    def test_removed_runtime_artifacts_are_not_part_of_the_skill(self):
        self.assertFalse((SKILL_ROOT / ".jules").exists())
        self.assertFalse((SKILL_ROOT / "garmindb.log").exists())
        ignore = (SKILL_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", ignore)
        self.assertIn("*.log", ignore)


if __name__ == "__main__":
    unittest.main()
