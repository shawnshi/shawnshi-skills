import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from garmin_capabilities import issue_capability


SYNC_REQUEST = {"window": {"start": "2026-08-01", "end": "2026-08-07"}}


SCRIPT_PATH = Path(__file__).with_name("sync_health_data.py")


def synthetic_bindings(seed="a"):
    digest = (seed * 64)[:64]
    alternate = ("b" if seed != "b" else "c") * 64
    file_identity = {
        "filename": "python.exe",
        "sha256": digest,
        "size_bytes": 1,
        "path_sha256": alternate,
        "file_identity_sha256": "c" * 64,
    }
    return {
        "config": {
            "filename": "GarminConnectConfig.json",
            "sha256": "d" * 64,
        },
        "runner": {
            "interpreter": file_identity,
            "cli": {
                **file_identity,
                "filename": "garmindb_cli.py",
                "sha256": "e" * 64,
                "path_sha256": "f" * 64,
                "file_identity_sha256": "0" * 64,
            },
            "environment": {
                "evidence_method": "isolated_venv_filesystem_read_only",
                "review_status": (
                    "filesystem_evidence_bound_external_security_review_required"
                ),
                "pyvenv_cfg_sha256": "1" * 64,
                "site_packages_tree_sha256": "2" * 64,
                "site_packages_file_count": 2,
                "packages": [
                    {
                        "name": "garmindb",
                        "version": "3.8.0",
                        "metadata_sha256": "3" * 64,
                    },
                    {
                        "name": "garminconnect",
                        "version": "0.3.9",
                        "metadata_sha256": "4" * 64,
                    },
                ],
            },
        },
    }


def load_module():
    spec = importlib.util.spec_from_file_location("sync_health_data_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyncHealthDataCliTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.bindings = synthetic_bindings()

    def make_bound_environment(self, root):
        root = Path(root)
        config_dir = root / "config"
        config_dir.mkdir()
        config_file = config_dir / self.module.CONFIG_NAME
        config_file.write_text(
            json.dumps(
                {"username": "private@example.test", "data": {}},
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        venv_root = root / "runner-venv"
        scripts_dir = venv_root / "Scripts"
        site_packages = venv_root / "Lib" / "site-packages"
        scripts_dir.mkdir(parents=True)
        site_packages.mkdir(parents=True)
        (venv_root / "pyvenv.cfg").write_text(
            "home = C:/synthetic-python\nversion = 3.12.0\n", encoding="utf-8"
        )
        interpreter = scripts_dir / "python.exe"
        cli = scripts_dir / "garmindb_cli.py"
        interpreter.write_bytes(b"synthetic isolated interpreter")
        cli.write_text("# synthetic trusted CLI\n", encoding="utf-8")
        for directory, name, version in (
            ("GarminDB-3.8.0.dist-info", "garmindb", "3.8.0"),
            ("garminconnect-0.3.9.dist-info", "garminconnect", "0.3.9"),
        ):
            metadata_dir = site_packages / directory
            metadata_dir.mkdir()
            (metadata_dir / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
                encoding="utf-8",
            )
        return config_dir, config_file, interpreter, cli

    def run_main(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = self.module.main(argv)
        return exit_code, json.loads(stdout.getvalue())

    def test_help_is_zero_side_effect(self):
        with (
            patch.object(self.module.subprocess, "run") as runner,
            patch.object(self.module, "execute_sync") as execute,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as raised:
                self.module.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        runner.assert_not_called()
        execute.assert_not_called()

    def test_no_subcommand_is_machine_readable_and_zero_side_effect(self):
        with patch.object(self.module, "execute_sync") as execute:
            exit_code, payload = self.run_main([])
        self.assertEqual(exit_code, self.module.EXIT_USAGE)
        self.assertEqual(payload["status"], "usage_error")
        execute.assert_not_called()

    def test_dry_run_with_explicit_window_has_no_side_effect(self):
        with (
            patch.object(self.module, "execute_sync") as execute,
            patch.object(self.module, "write_sync_plan_atomic") as write_plan,
        ):
            exit_code, payload = self.run_main(
                [
                    "sync",
                    "--start",
                    "2026-08-01",
                    "--end",
                    "2026-08-07",
                    "--dry-run",
                ]
            )
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["requested_window"]["start"], "2026-08-01")
        self.assertEqual(payload["requested_window"]["end"], "2026-08-07")
        execute.assert_not_called()
        write_plan.assert_not_called()

    def test_plan_output_requires_explicit_config_and_runner(self):
        for extra_args in (
            [],
            ["--config-dir", "C:/explicit-config"],
            ["--garmindb-python", "C:/runner/Scripts/python.exe"],
        ):
            with self.subTest(extra_args=extra_args), tempfile.TemporaryDirectory() as root:
                plan_path = Path(root) / "plan.json"
                with patch.object(self.module, "build_sync_bindings") as build_bindings:
                    exit_code, payload = self.run_main(
                        [
                            "sync",
                            "--start",
                            "2026-08-01",
                            "--end",
                            "2026-08-07",
                            "--dry-run",
                            "--plan-output",
                            str(plan_path),
                            *extra_args,
                        ]
                    )
                self.assertEqual(exit_code, self.module.EXIT_USAGE)
                self.assertEqual(
                    payload["error"],
                    "plan_output_requires_explicit_config_and_runner",
                )
                self.assertFalse(plan_path.exists())
                build_bindings.assert_not_called()

    def test_dry_run_can_atomically_write_a_versioned_plan(self):
        with tempfile.TemporaryDirectory() as temp_root:
            plan_path = Path(temp_root) / "sync-plan.json"
            config_dir, _, interpreter, _ = self.make_bound_environment(temp_root)
            exit_code, payload = self.run_main(
                [
                    "sync",
                    "--start",
                    "2026-08-01",
                    "--end",
                    "2026-08-07",
                    "--dry-run",
                    "--plan-output",
                    str(plan_path),
                    "--config-dir",
                    str(config_dir),
                    "--garmindb-python",
                    str(interpreter),
                ]
            )

            self.assertEqual(exit_code, self.module.EXIT_OK)
            self.assertTrue(payload["plan_written"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["version"], self.module.SYNC_PLAN_VERSION)
            self.assertEqual(
                plan["window"], {"start": "2026-08-01", "end": "2026-08-07"}
            )
            self.assertRegex(plan["nonce"], r"^[0-9a-f]{32}$")
            self.assertIn("expires_at", plan)
            self.assertEqual(
                set(plan["bindings"]["config"]), {"filename", "sha256"}
            )
            serialized = json.dumps(plan, sort_keys=True)
            self.assertNotIn("private@example.test", serialized)
            self.assertNotIn(str(config_dir), serialized)
            self.assertEqual(
                plan["bindings"]["runner"]["environment"]["review_status"],
                "filesystem_evidence_bound_external_security_review_required",
            )
            package_versions = {
                package["name"]: package["version"]
                for package in plan["bindings"]["runner"]["environment"]["packages"]
            }
            self.assertEqual(
                package_versions, {"garmindb": "3.8.0", "garminconnect": "0.3.9"}
            )
            self.assertEqual(len(plan["payload_sha256"]), 64)
            self.module.load_and_validate_sync_plan(
                plan_path,
                expected_start=self.module.date(2026, 8, 1),
                expected_end=self.module.date(2026, 8, 7),
            )
            self.assertEqual(list(plan_path.parent.glob(".sync-plan.json.*.tmp")), [])

    def test_plan_tampering_expiry_and_window_mismatch_fail_closed(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        fixed_now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_root:
            plan_path = Path(temp_root) / "sync-plan.json"
            plan = self.module.build_sync_plan(
                start,
                end,
                ttl_seconds=60,
                now=fixed_now,
                bindings=self.bindings,
            )
            self.module.write_sync_plan_atomic(plan_path, plan)

            tampered = dict(plan)
            tampered["window"] = {"start": "2026-08-02", "end": "2026-08-07"}
            plan_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(self.module.SyncPlanError, "plan_digest_mismatch"):
                self.module.load_and_validate_sync_plan(
                    plan_path,
                    expected_start=start,
                    expected_end=end,
                    now=fixed_now,
                )

            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(self.module.SyncPlanError, "plan_expired"):
                self.module.load_and_validate_sync_plan(
                    plan_path,
                    expected_start=start,
                    expected_end=end,
                    now=fixed_now + timedelta(seconds=61),
                )

            with self.assertRaisesRegex(self.module.SyncPlanError, "plan_window_mismatch"):
                self.module.load_and_validate_sync_plan(
                    plan_path,
                    expected_start=self.module.date(2026, 8, 2),
                    expected_end=end,
                    now=fixed_now,
                )

    def test_plan_missing_bindings_is_rejected(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            plan_path = Path(temp_root) / "sync-plan.json"
            plan = self.module.build_sync_plan(start, end, bindings=self.bindings)
            plan.pop("bindings")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(
                self.module.SyncPlanError, "sync_plan_schema_invalid"
            ):
                self.module.load_and_validate_sync_plan(
                    plan_path,
                    expected_start=start,
                    expected_end=end,
                )

    def test_build_plan_requires_complete_bindings(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        for bindings in (None, {}, {"config": self.bindings["config"]}):
            with self.subTest(bindings=bindings), self.assertRaisesRegex(
                self.module.SyncPlanError, "plan_bindings_required"
            ):
                self.module.build_sync_plan(start, end, bindings=bindings)

    def test_live_sync_requires_explicit_network_authorization(self):
        with patch.object(self.module, "execute_sync") as execute:
            exit_code, payload = self.run_main(
                ["sync", "--start", "2026-08-01", "--end", "2026-08-07"]
            )
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["status"], "network_authorization_required")
        execute.assert_not_called()

    def test_live_sync_requires_separate_sync_authorization(self):
        with patch.object(self.module, "execute_sync") as execute:
            exit_code, payload = self.run_main(
                [
                    "sync",
                    "--allow-network",
                    "--start",
                    "2026-08-01",
                    "--end",
                    "2026-08-07",
                ]
            )
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["status"], "sync_authorization_required")
        execute.assert_not_called()

    def test_live_sync_requires_plan_after_both_cli_grants(self):
        with patch.object(self.module, "execute_sync") as execute:
            exit_code, payload = self.run_main(
                [
                    "sync",
                    "--allow-network",
                    "--allow-sync",
                    "--start",
                    "2026-08-01",
                    "--end",
                    "2026-08-07",
                ]
            )
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["status"], "sync_plan_required")
        execute.assert_not_called()

    def test_direct_execute_sync_requires_both_capabilities_before_side_effects(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        runner = unittest.mock.Mock()
        with patch.object(self.module, "locate_garmindb_cli") as locate:
            exit_code, payload = self.module.execute_sync(
                start,
                end,
                runner=runner,
            )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "network_authorization_required")

            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=issue_capability(
                    scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                runner=runner,
            )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "sync_authorization_required")

            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=True,
                sync_capability=True,
                plan_file=Path("missing-plan.json"),
                runner=runner,
            )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "network_authorization_required")
        locate.assert_not_called()
        runner.assert_not_called()

    def test_direct_execute_rejects_wrong_scope_operation_and_missing_plan(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        valid_network = issue_capability(
            scope="network", operation="garmindb_sync", request=SYNC_REQUEST
        )
        valid_sync = issue_capability(scope="sync", operation="garmindb_sync", request=SYNC_REQUEST)
        cases = (
            (
                issue_capability(scope="download", operation="garmindb_sync", request=SYNC_REQUEST),
                valid_sync,
                "network_authorization_required",
            ),
            (
                valid_network,
                issue_capability(scope="sync", operation="activity_download", request=SYNC_REQUEST),
                "sync_authorization_required",
            ),
            (valid_network, valid_sync, "sync_plan_required"),
        )
        for network_capability, sync_capability, expected in cases:
            with self.subTest(expected=expected), patch.object(
                self.module, "locate_garmindb_cli"
            ) as locate:
                exit_code, payload = self.module.execute_sync(
                    start,
                    end,
                    network_capability=network_capability,
                    sync_capability=sync_capability,
                )
                self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
                self.assertEqual(payload["status"], expected)
                locate.assert_not_called()

    def test_direct_execute_rejects_expired_capability_and_tampered_plan(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        issued_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        expired_network = issue_capability(
            scope="network",
            operation="garmindb_sync",
            request=SYNC_REQUEST,
            ttl_seconds=1,
            now=issued_at,
        )
        valid_sync = issue_capability(scope="sync", operation="garmindb_sync", request=SYNC_REQUEST)
        with patch.object(self.module, "locate_garmindb_cli") as locate:
            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=expired_network,
                sync_capability=valid_sync,
                plan_file=Path("unused.json"),
            )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "network_authorization_required")
            locate.assert_not_called()

        with tempfile.TemporaryDirectory() as temp_root:
            plan_path = Path(temp_root) / "sync-plan.json"
            plan = self.module.build_sync_plan(start, end, bindings=self.bindings)
            plan["window"] = {"start": "2026-08-02", "end": "2026-08-07"}
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(self.module, "locate_garmindb_cli") as locate:
                exit_code, payload = self.module.execute_sync(
                    start,
                    end,
                    network_capability=issue_capability(
                        scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                    ),
                    sync_capability=issue_capability(
                        scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                    ),
                    plan_file=plan_path,
                )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "sync_plan_invalid")
            self.assertEqual(payload["error"], "plan_digest_mismatch")
            locate.assert_not_called()

    def test_missing_or_reversed_window_is_rejected_before_execution(self):
        for argv, expected_error in (
            (["sync", "--allow-network"], "explicit_start_and_end_required"),
            (
                [
                    "sync",
                    "--allow-network",
                    "--allow-sync",
                    "--start",
                    "2026-08-08",
                    "--end",
                    "2026-08-01",
                ],
                "start_after_end",
            ),
        ):
            with self.subTest(argv=argv), patch.object(
                self.module, "execute_sync"
            ) as execute:
                exit_code, payload = self.run_main(argv)
                self.assertEqual(exit_code, self.module.EXIT_USAGE)
                self.assertEqual(payload["error"], expected_error)
                execute.assert_not_called()

    def test_authorized_sync_returns_only_structured_status(self):
        result = {
            "ok": True,
            "status": "sync_completed",
            "requested_window": {"start": "2026-08-01", "end": "2026-08-07"},
        }
        with tempfile.TemporaryDirectory() as temp_root:
            plan_path = Path(temp_root) / "sync-plan.json"
            plan = self.module.build_sync_plan(
                self.module.date(2026, 8, 1),
                self.module.date(2026, 8, 7),
                bindings=self.bindings,
            )
            self.module.write_sync_plan_atomic(plan_path, plan)
            with patch.object(
                self.module, "execute_sync", return_value=(0, result)
            ) as execute:
                exit_code, payload = self.run_main(
                    [
                        "sync",
                        "--allow-network",
                        "--allow-sync",
                        "--start",
                        "2026-08-01",
                        "--end",
                        "2026-08-07",
                        "--plan-file",
                        str(plan_path),
                        "--config-dir",
                        "C:/explicit-garmin-config",
                        "--garmindb-python",
                        "C:/trusted-garmindb/Scripts/python.exe",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, result)
        execute.assert_called_once()
        self.module.require_capability(
            execute.call_args.kwargs["network_capability"],
            scope="network",
            operation="garmindb_sync",
            request=SYNC_REQUEST,
        )
        self.module.require_capability(
            execute.call_args.kwargs["sync_capability"],
            scope="sync",
            operation="garmindb_sync",
            request=SYNC_REQUEST,
        )
        self.assertEqual(execute.call_args.kwargs["plan_file"], plan_path)
        self.assertEqual(
            execute.call_args.kwargs["config_dir"],
            Path("C:/explicit-garmin-config"),
        )
        self.assertEqual(
            execute.call_args.kwargs["garmindb_python"],
            Path("C:/trusted-garmindb/Scripts/python.exe"),
        )

    def test_runner_discovery_requires_an_explicit_adjacent_environment(self):
        with self.assertRaisesRegex(
            self.module.SyncConfigurationError,
            "trusted_garmindb_python_required",
        ):
            self.module.locate_garmindb_cli(None)

        with tempfile.TemporaryDirectory() as temp_root:
            venv_root = Path(temp_root)
            scripts_dir = venv_root / "Scripts"
            scripts_dir.mkdir()
            (venv_root / "pyvenv.cfg").write_text(
                "home = C:/synthetic-python\n", encoding="utf-8"
            )
            interpreter = scripts_dir / "python.exe"
            cli = scripts_dir / "garmindb_cli.py"
            interpreter.write_bytes(b"synthetic interpreter")
            cli.write_text("# synthetic trusted CLI\n", encoding="utf-8")

            resolved_interpreter, resolved_cli = self.module.locate_garmindb_cli(
                interpreter
            )

        self.assertEqual(resolved_interpreter, interpreter.resolve())
        self.assertEqual(resolved_cli, cli.resolve())
        self.assertNotIn("shutil.which", SCRIPT_PATH.read_text(encoding="utf-8"))

    def test_runner_discovery_rejects_a_non_venv_interpreter(self):
        with tempfile.TemporaryDirectory() as temp_root:
            scripts_dir = Path(temp_root) / "Scripts"
            scripts_dir.mkdir()
            interpreter = scripts_dir / "python.exe"
            (scripts_dir / "garmindb_cli.py").write_text("# cli\n", encoding="utf-8")
            interpreter.write_bytes(b"not an isolated environment")
            with self.assertRaisesRegex(
                self.module.SyncConfigurationError,
                "isolated_runner_venv_required",
            ):
                self.module.locate_garmindb_cli(interpreter)

    def test_runner_binding_requires_exact_unique_package_evidence(self):
        for mutation, expected_error in (
            ("missing", "runner_package_evidence_incomplete"),
            ("wrong_version", "runner_package_version_unsupported"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                config_dir, _, interpreter, _ = self.make_bound_environment(root)
                site_packages = Path(root) / "runner-venv" / "Lib" / "site-packages"
                metadata = (
                    site_packages / "GarminDB-3.8.0.dist-info" / "METADATA"
                )
                if mutation == "missing":
                    metadata.unlink()
                else:
                    metadata.write_text(
                        "Metadata-Version: 2.1\nName: garmindb\nVersion: 3.7.0\n\n",
                        encoding="utf-8",
                    )
                with self.assertRaisesRegex(
                    self.module.SyncConfigurationError, expected_error
                ):
                    self.module.build_sync_bindings(config_dir, interpreter)

    def test_site_packages_tree_binding_includes_runtime_bytecode(self):
        with tempfile.TemporaryDirectory() as root:
            config_dir, _, interpreter, _ = self.make_bound_environment(root)
            before = self.module.build_sync_bindings(config_dir, interpreter)
            bytecode_dir = (
                Path(root)
                / "runner-venv"
                / "Lib"
                / "site-packages"
                / "__pycache__"
            )
            bytecode_dir.mkdir()
            (bytecode_dir / "sitecustomize.cpython-312.pyc").write_bytes(
                b"synthetic executable bytecode"
            )
            after = self.module.build_sync_bindings(config_dir, interpreter)
        self.assertNotEqual(
            before["runner"]["environment"]["site_packages_tree_sha256"],
            after["runner"]["environment"]["site_packages_tree_sha256"],
        )
        self.assertEqual(
            after["runner"]["environment"]["site_packages_file_count"],
            before["runner"]["environment"]["site_packages_file_count"] + 1,
        )

    def test_valid_plan_still_fails_closed_without_a_trusted_runner(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            plan_path = Path(temp_root) / "sync-plan.json"
            self.module.write_sync_plan_atomic(
                plan_path,
                self.module.build_sync_plan(start, end, bindings=self.bindings),
            )
            runner = unittest.mock.Mock()
            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=issue_capability(
                    scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                sync_capability=issue_capability(
                    scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                plan_file=plan_path,
                config_dir=Path(temp_root) / "explicit-config",
                runner=runner,
            )

        self.assertEqual(exit_code, self.module.EXIT_CONFIGURATION)
        self.assertEqual(payload["status"], "configuration_error")
        self.assertEqual(payload["error"], "trusted_garmindb_python_required")
        runner.assert_not_called()

    def test_sanitized_environment_drops_python_pip_and_tls_trust_overrides(self):
        inherited = {
            "SYSTEMROOT": r"C:\Windows",
            "TEMP": r"C:\Temp",
            "PYTHONPATH": r"C:\injected-python",
            "PIP_TARGET": r"C:\injected-pip",
            "SSL_CERT_FILE": r"C:\untrusted-cert.pem",
            "SSL_CERT_DIR": r"C:\untrusted-certs",
            "REQUESTS_CA_BUNDLE": r"C:\untrusted-ca.pem",
        }
        with patch.dict(os.environ, inherited, clear=True):
            environment = self.module._sanitized_runner_environment()

        self.assertEqual(
            environment,
            {"SYSTEMROOT": r"C:\Windows", "TEMP": r"C:\Temp"},
        )

    def test_bound_plan_executes_only_with_the_same_config_and_runner(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            config_dir, _, interpreter, cli = self.make_bound_environment(temp_root)
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            plan_path = Path(temp_root) / "sync-plan.json"
            self.module.write_sync_plan_atomic(
                plan_path,
                self.module.build_sync_plan(start, end, bindings=bindings),
            )
            runner = unittest.mock.Mock(
                return_value=unittest.mock.Mock(returncode=0, stdout="ok")
            )
            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=issue_capability(
                    scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                sync_capability=issue_capability(
                    scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                plan_file=plan_path,
                config_dir=config_dir,
                garmindb_python=interpreter,
                runner=runner,
            )

        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["status"], "sync_completed")
        runner.assert_called_once()
        command = runner.call_args.args[0]
        self.assertEqual(command[0], str(interpreter))
        self.assertEqual(command[1:3], ["-I", "-B"])
        self.assertEqual(command[3], str(cli))
        self.assertEqual(runner.call_args.kwargs["stdin"], self.module.subprocess.DEVNULL)
        self.assertNotIn("PYTHONPATH", runner.call_args.kwargs["env"])

    def test_changed_config_interpreter_or_cli_invalidates_bound_plan(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        for changed_target in ("config", "interpreter", "cli"):
            with self.subTest(changed_target=changed_target), tempfile.TemporaryDirectory() as root:
                config_dir, config_file, interpreter, cli = self.make_bound_environment(root)
                bindings = self.module.build_sync_bindings(config_dir, interpreter)
                plan_path = Path(root) / "sync-plan.json"
                self.module.write_sync_plan_atomic(
                    plan_path,
                    self.module.build_sync_plan(start, end, bindings=bindings),
                )
                if changed_target == "config":
                    config_file.write_text(
                        json.dumps({"username": "changed@example.test", "data": {}}),
                        encoding="utf-8",
                    )
                elif changed_target == "interpreter":
                    interpreter.write_bytes(b"replaced interpreter bytes")
                else:
                    cli.write_text("# replaced CLI bytes\n", encoding="utf-8")
                runner = unittest.mock.Mock()
                with patch.object(self.module, "prepare_windowed_config") as prepare:
                    exit_code, payload = self.module.execute_sync(
                        start,
                        end,
                        network_capability=issue_capability(
                            scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                        ),
                        sync_capability=issue_capability(
                            scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                        ),
                        plan_file=plan_path,
                        config_dir=config_dir,
                        garmindb_python=interpreter,
                        runner=runner,
                    )
                self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
                self.assertEqual(payload["status"], "sync_plan_invalid")
                self.assertEqual(payload["error"], "plan_bindings_mismatch")
                prepare.assert_not_called()
                runner.assert_not_called()

    def test_runner_path_replacement_invalidates_bound_plan_even_with_same_bytes(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            primary_root = Path(temp_root) / "primary"
            alternate_root = Path(temp_root) / "alternate"
            primary_root.mkdir()
            alternate_root.mkdir()
            config_dir, _, interpreter, _ = self.make_bound_environment(primary_root)
            _, _, alternate_interpreter, _ = self.make_bound_environment(alternate_root)
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            plan_path = Path(temp_root) / "sync-plan.json"
            self.module.write_sync_plan_atomic(
                plan_path,
                self.module.build_sync_plan(start, end, bindings=bindings),
            )
            runner = unittest.mock.Mock()
            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=issue_capability(
                    scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                sync_capability=issue_capability(
                    scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                plan_file=plan_path,
                config_dir=config_dir,
                garmindb_python=alternate_interpreter,
                runner=runner,
            )
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["error"], "plan_bindings_mismatch")
        runner.assert_not_called()

    def test_recomputed_plan_digest_cannot_hide_a_binding_tamper(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            config_dir, _, interpreter, _ = self.make_bound_environment(temp_root)
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            plan = self.module.build_sync_plan(start, end, bindings=bindings)
            plan["bindings"]["runner"]["cli"]["sha256"] = "0" * 64
            plan["payload_sha256"] = self.module._payload_sha256(
                self.module._plan_payload(plan)
            )
            plan_path = Path(temp_root) / "sync-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            runner = unittest.mock.Mock()
            exit_code, payload = self.module.execute_sync(
                start,
                end,
                network_capability=issue_capability(
                    scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                sync_capability=issue_capability(
                    scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                ),
                plan_file=plan_path,
                config_dir=config_dir,
                garmindb_python=interpreter,
                runner=runner,
            )
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["status"], "sync_plan_invalid")
        self.assertEqual(payload["error"], "plan_bindings_mismatch")
        runner.assert_not_called()

    def test_runner_is_rechecked_after_temporary_config_creation(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            config_dir, _, interpreter, cli = self.make_bound_environment(temp_root)
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            plan_path = Path(temp_root) / "sync-plan.json"
            self.module.write_sync_plan_atomic(
                plan_path,
                self.module.build_sync_plan(start, end, bindings=bindings),
            )
            original_prepare = self.module.prepare_windowed_config

            @contextlib.contextmanager
            def replace_runner_after_temp_config(*args, **kwargs):
                with original_prepare(*args, **kwargs) as temp_config:
                    cli.write_text("# replaced after first verification\n", encoding="utf-8")
                    yield temp_config

            runner = unittest.mock.Mock()
            with patch.object(
                self.module,
                "prepare_windowed_config",
                replace_runner_after_temp_config,
            ):
                exit_code, payload = self.module.execute_sync(
                    start,
                    end,
                    network_capability=issue_capability(
                        scope="network", operation="garmindb_sync", request=SYNC_REQUEST
                    ),
                    sync_capability=issue_capability(
                        scope="sync", operation="garmindb_sync", request=SYNC_REQUEST
                    ),
                    plan_file=plan_path,
                    config_dir=config_dir,
                    garmindb_python=interpreter,
                    runner=runner,
                )
        self.assertEqual(exit_code, self.module.EXIT_CONFIGURATION)
        self.assertEqual(payload["error"], "bound_runner_changed")
        runner.assert_not_called()

    def test_rate_limit_is_terminal_and_no_fallback_exists(self):
        self.assertFalse(hasattr(self.module, "trigger_fallback"))
        status = self.module.classify_process_result(
            returncode=1, output="HTTP 429 Too Many Requests"
        )
        self.assertEqual(status[0], self.module.EXIT_RATE_LIMIT)
        self.assertEqual(status[1]["status"], "rate_limited")

    def test_command_is_bounded_and_never_uses_all_or_latest(self):
        command = self.module.build_garmindb_command(
            Path("C:/Python/python.exe"),
            Path("C:/Python/Scripts/garmindb_cli.py"),
            Path("C:/safe/window-config"),
        )
        self.assertNotIn("--all", command)
        self.assertNotIn("--latest", command)
        self.assertEqual(command[1:3], ["-I", "-B"])
        self.assertIn("--monitoring", command)
        self.assertIn("--sleep", command)
        self.assertIn("--rhr", command)
        self.assertIn("--hrv", command)
        self.assertIn("--weight", command)


if __name__ == "__main__":
    unittest.main()
