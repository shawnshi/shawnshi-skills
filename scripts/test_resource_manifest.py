import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import cast

import resource_manifest as manifest


WRAPPER = Path(__file__).with_name("generate_resource_manifests.ps1")
POWERSHELL = os.environ.get("RESOURCE_MANIFEST_TEST_POWERSHELL", "pwsh")


class ResourceManifestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="manifest root "))
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
                POWERSHELL,
                "-NoProfile",
                "-File",
                str(WRAPPER),
                "-Root",
                str(self.root),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((skill_dir / "resource-manifest.json").is_file())


class ResourceManifestWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wrapper fixtures ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "synthetic root"
        self.root.mkdir()
        self.cwd = self.base / "unrelated non Git cwd"
        self.cwd.mkdir()
        self.scripts = self.base / "copied scripts"
        self.scripts.mkdir()
        self.wrapper = self.scripts / WRAPPER.name
        shutil.copy2(WRAPPER, self.wrapper)
        self.worker = self.scripts / "resource_manifest.py"
        shutil.copy2(WRAPPER.with_name("resource_manifest.py"), self.worker)
        self.marker = self.scripts / "main-called"
        self.pwsh = shutil.which(POWERSHELL)
        if not self.pwsh:
            self.skipTest(f"{POWERSHELL} is unavailable")

    def run_wrapper(self, *args, root=None, env=None):
        assert self.pwsh is not None
        result = subprocess.run(
            [self.pwsh, "-NoProfile", "-File", str(self.wrapper),
             "-Root", str(self.root if root is None else root), *args],
            cwd=self.cwd, capture_output=True, text=True, encoding="utf-8",
            timeout=20, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(env or {})},
        )
        return result

    def fixture_worker(self, main, probe=None):
        # A copied adjacent worker only; never replace the installed interpreter.
        self.worker.write_text(
            "import argparse, pathlib, sys, time\n"
            "if '--help' in sys.argv:\n"
            + ("    " + probe.replace("\n", "\n    ") + "\n" if probe else
               "    parser = argparse.ArgumentParser()\n"
               "    parser.add_argument('mode', choices=('generate', 'check'))\n"
               "    for flag in ('--root', '--json', '--include-skill', '--exclude-skill'):\n"
               "        parser.add_argument(flag)\n"
               "    parser.parse_args()\n")
            + "pathlib.Path(__file__).with_name('main-called').write_text('main')\n"
            + main + "\n", encoding="utf-8",
        )

    def test_generate_check_whatif_spaces_and_scopes(self):
        for name in ("first skill", "other skill"):
            skill = self.root / name
            skill.mkdir()
            (skill / "SKILL.md").write_text("# Synthetic skill\n", encoding="utf-8")
        manifest_path = self.root / "first skill" / "resource-manifest.json"
        result = self.run_wrapper("-WhatIf")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stale: 2", result.stdout)
        self.assertFalse(manifest_path.exists())
        self.assertFalse((self.root / "other skill" / "resource-manifest.json").exists())
        result = self.run_wrapper("-IncludeSkills", "first skill")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        before = manifest_path.read_bytes()
        self.assertFalse((self.root / "other skill" / "resource-manifest.json").exists())
        for args in (("-Check", "-ExcludeSkills", "other skill"),
                     ("-WhatIf", "-IncludeSkills", "first skill")):
            result = self.run_wrapper(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_empty_root_and_invalid_selector(self):
        result = self.run_wrapper("-Check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checked: 0; stale: 0", result.stdout)
        for args in (("-Check",), ()):
            result = self.run_wrapper(*args, "-IncludeSkills", "missing")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("unknown included skills: missing", result.stdout)

    def test_bad_roots_and_missing_worker_stop_before_main(self):
        self.fixture_worker("raise SystemExit(91)")
        file_root = self.base / "file root"
        file_root.write_text("fixture", encoding="utf-8")
        for root in (self.base / "missing root", file_root):
            result = self.run_wrapper(root=root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr)
            self.assertFalse(self.marker.exists())
        self.worker.unlink()
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        # Windows PowerShell's error formatter can wrap inside a filename.
        self.assertIn("resource_manifest.py", "".join(result.stderr.split()))
        self.assertFalse(self.marker.exists())

    def test_python_function_cannot_shadow_application(self):
        assert self.pwsh is not None
        wrapper = str(self.wrapper).replace("'", "''")
        root = str(self.root).replace("'", "''")
        result = subprocess.run(
            [self.pwsh, "-NoProfile", "-Command",
             "function python { throw 'function must not run' }; "
             f"& '{wrapper}' -Root '{root}' -Check"],
            cwd=self.cwd, capture_output=True, text=True, encoding="utf-8", timeout=20,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checked: 0; stale: 0", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows sharing-mode readability fixture")
    def test_worker_read_lock_fails_before_main(self):
        import ctypes
        from ctypes import wintypes

        self.fixture_worker("raise SystemExit(91)")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(self.worker), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value, ctypes.get_last_error())
        try:
            result = self.run_wrapper()
        finally:
            kernel.CloseHandle(handle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resource_manifest.py", "".join(result.stderr.split()))
        self.assertFalse(self.marker.exists())

    def test_missing_application_and_unlaunchable_application(self):
        self.fixture_worker("raise SystemExit(91)")
        bin_dir = self.base / "isolated bin"
        bin_dir.mkdir()
        result = self.run_wrapper(env={"PATH": str(bin_dir)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python application is required", result.stderr)
        self.assertFalse(self.marker.exists())
        if os.name == "nt":
            (bin_dir / "python.exe").write_bytes(b"not an executable fixture")
            result = self.run_wrapper(env={"PATH": str(bin_dir)})
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr)
            self.assertFalse(self.marker.exists())

    def test_probe_nonzero_bad_interface_and_timeout(self):
        for probe, code, diagnostic in (
            ("sys.stderr.write('probe-native-error\\n'); raise SystemExit(37)", 37, "probe-native-error"),
            ("print('wrong interface'); raise SystemExit(0)", 1, "help interface missing"),
            ("sys.stderr.write('probe-waiting\\n'); sys.stderr.flush(); time.sleep(60)", 1, "timed out"),
        ):
            with self.subTest(probe=probe):
                self.fixture_worker("raise SystemExit(91)", probe)
                start = time.monotonic()
                result = self.run_wrapper()
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertLess(time.monotonic() - start, 15)
                self.assertFalse(self.marker.exists())

    def test_native_nonzero_preserves_empty_malformed_stdout_and_stderr(self):
        for output in ("", "not JSON"):
            with self.subTest(output=output):
                self.fixture_worker(
                    f"sys.stdout.write({output!r}); sys.stderr.write('native failure 演示\\n'); raise SystemExit(37)"
                )
                result = self.run_wrapper()
                self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
                self.assertIn("native failure 演示", result.stderr)
                self.assertNotIn("Resource manifests checked", result.stdout)

    def test_zero_exit_rejects_invalid_protocol_and_failure_counts(self):
        generate = {"checked": 0, "written": 0, "unchanged": 0, "failed": 0, "issues": []}
        check = {"checked": 0, "stale": 0, "stale_skills": [], "issues": []}
        cases = [(False, text) for text in ("", "not JSON", "null", "[]", "{}", "1")]
        cases += [(False, json.dumps({**generate, **change})) for change in (
            {"checked": "0"}, {"checked": True}, {"written": -1}, {"failed": 1},
            {"issues": {}}, {"issues": None}, {"checked": 1},
            {"issues": [{"skill": "x", "detail": "failure"}]},
        )]
        cases += [(True, json.dumps({**check, **change})) for change in (
            {"stale": 1}, {"stale_skills": ["x"]}, {"stale_skills": "x"},
            {"issues": [{"skill": "x", "detail": "bad", "code": 1}]},
        )]
        cases += [(True, json.dumps({k: v for k, v in check.items() if k != "stale_skills"}))]
        for is_check, output in cases:
            with self.subTest(check=is_check, output=output):
                self.fixture_worker(f"sys.stdout.write({output!r})")
                result = self.run_wrapper(*(["-Check"] if is_check else []))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("invalid protocol", result.stderr)
                self.assertNotIn("Resource manifests checked", result.stdout)

    def test_success_stderr_remains_separate(self):
        self.fixture_worker(
            "sys.stderr.write('worker advisory 演示\\n')\n"
            "print('{\"checked\":0,\"written\":0,\"unchanged\":0,\"failed\":0,\"issues\":[]}')"
        )
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("worker advisory 演示", result.stderr)
        self.assertNotIn("worker advisory", result.stdout)
        self.assertIn("checked: 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
