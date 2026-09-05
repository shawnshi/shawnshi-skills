import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from garmin_capabilities import issue_capability


SYNC_REQUEST: dict[str, object] = {
    "window": {"start": "2026-08-01", "end": "2026-08-07"}
}


SCRIPT_PATH = Path(__file__).with_name("sync_health_data.py")

# AST-equivalent to the installed GarminDB 3.8.0 method, not a corrected mock.
UPSTREAM_DATE_METHOD = '''\
def __get_date_and_days(self, db, latest, table, col, stat_name):
    if latest:
        last_ts = table.latest_time(db, col)
        if last_ts is None:
            date, days = self.gc_config.stat_start_date(stat_name)
            logger.info('Recent %s data not found, using: %s : %s', stat_name, date, days)
        else:
            logger.info('Downloading latest %s data from: %s', stat_name, last_ts)
            last_ts_date_date = last_ts.date() if isinstance(last_ts, datetime.datetime) else last_ts
            date = last_ts_date_date - datetime.timedelta(days=1)
            days = (datetime.date.today() - date).days
    else:
        date, days = self.gc_config.stat_start_date(stat_name)
        days = min((datetime.date.today() - date).days, days)
        logger.info('Downloading all %s data from: %s [%d]', stat_name, date, days)
    if date is None or days is None:
        logger.error('Missing config: need %s_start_date and download_days. Edit GarminConnectConfig.py.', stat_name)
        sys.exit()
    return (date, days)
'''
SYNTHETIC_CLI = '''\
import datetime
import json
import logging
import pathlib
import sys
logger = logging.getLogger(__file__)
class GarminDbMain:
''' + textwrap.indent(UPSTREAM_DATE_METHOD, "    ") + '''
if __name__ == "__main__":
    assert sys.flags.isolated == 1 and sys.dont_write_bytecode
    # Neither imports nor execution may open the network in this fixture.
    import socket
    def no_network(*args, **kwargs):
        raise AssertionError("network_forbidden")
    socket.socket = no_network
    config_dir = pathlib.Path(sys.argv[sys.argv.index("--config") + 1])
    data = json.loads((config_dir / "GarminConnectConfig.json").read_text())["data"]
    class Config:
        def stat_start_date(self, stat):
            start = datetime.datetime.strptime(data[stat + "_start_date"], "%m/%d/%Y").date()
            end = datetime.datetime.strptime(data[stat + "_end_date"], "%m/%d/%Y").date()
            return start, (end - start).days
    dates = {}
    if "--download" in sys.argv:
        main = GarminDbMain()
        main.gc_config = Config()
        for stat in ("monitoring", "sleep", "rhr", "hrv", "weight"):
            start, days = main._GarminDbMain__get_date_and_days(None, False, None, None, stat)
            dates[stat] = [(start + datetime.timedelta(days=day)).isoformat() for day in range(0, days)]
    print(json.dumps({"dates": dates, "stage": "download" if "--download" in sys.argv else "import_analyze"}))
'''


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
            "token_store_filename": "garmin_tokens.json",
            "token_store_sha256": "9" * 64,
            "data_root_path_sha256": "7" * 64,
            "data_root_identity_sha256": "8" * 64,
            "db_dir_identity_sha256": "6" * 64,
        },
        "runner": {
            "interpreter": file_identity,
            "adapter": {**file_identity, "filename": "sync_health_data.py"},
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
    if spec is None or spec.loader is None:
        raise RuntimeError("sync_health_data_test_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyncHealthDataCliTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.bindings = synthetic_bindings()

    @staticmethod
    def complete_verification(end="2026-08-07"):
        components = ("sleep", "hrv", "heart_rate", "body_battery", "stress")
        return {
            "database_changed": True,
            "component_observation_counts": {name: 7 for name in components},
            "component_latest_observation_dates": {name: end for name in components},
            "stale_components": [],
            "no_source_data_components": [],
            "source_present_without_coverage_components": [],
        }

    def make_bound_environment(self, root):
        root = Path(root)
        config_dir = root / ".GarminDb"
        config_dir.mkdir()
        data_root = config_dir / "HealthData"
        (data_root / "DBs").mkdir(parents=True)
        config_file = config_dir / self.module.CONFIG_NAME
        config_file.write_text(
            json.dumps(
                {
                    "username": "private@example.test",
                    "data": {},
                    "directories": {
                        "relative_to_home": True,
                        "base_dir": ".GarminDb/HealthData",
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (config_dir / self.module.TOKEN_STORE_NAME).write_text(
            json.dumps({"oauth1": "synthetic", "oauth2": "synthetic"}),
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
        cli.write_text(SYNTHETIC_CLI, encoding="utf-8")
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

    def make_global_environment(self, root):
        root = Path(root)
        config_dir = root / ".GarminDb"
        config_dir.mkdir()
        data_root = config_dir / "HealthData"
        (data_root / "DBs").mkdir(parents=True)
        config_file = config_dir / self.module.CONFIG_NAME
        config_file.write_text(
            json.dumps(
                {
                    "username": "private@example.test",
                    "data": {},
                    "directories": {
                        "relative_to_home": True,
                        "base_dir": ".GarminDb/HealthData",
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (config_dir / self.module.TOKEN_STORE_NAME).write_text(
            json.dumps({"oauth1": "synthetic", "oauth2": "synthetic"}),
            encoding="utf-8",
        )

        python_root = root / "Python313"
        scripts_dir = python_root / "Scripts"
        site_packages = python_root / "Lib" / "site-packages"
        scripts_dir.mkdir(parents=True)
        site_packages.mkdir(parents=True)
        interpreter = python_root / "python.exe"
        cli = scripts_dir / "garmindb_cli.py"
        interpreter.write_bytes(b"synthetic global interpreter")
        cli.write_text(SYNTHETIC_CLI, encoding="utf-8")
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
                set(plan["bindings"]["config"]),
                {
                    "filename",
                    "sha256",
                    "token_store_filename",
                    "token_store_sha256",
                    "data_root_path_sha256",
                    "data_root_identity_sha256",
                    "db_dir_identity_sha256",
                },
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

    def test_runner_discovery_rejects_an_unsupported_layout(self):
        with tempfile.TemporaryDirectory() as temp_root:
            scripts_dir = Path(temp_root) / "Scripts"
            scripts_dir.mkdir()
            interpreter = scripts_dir / "python.exe"
            (scripts_dir / "garmindb_cli.py").write_text("# cli\n", encoding="utf-8")
            interpreter.write_bytes(b"not an isolated environment")
            with self.assertRaisesRegex(
                self.module.SyncConfigurationError,
                "runner_environment_layout_unsupported",
            ):
                self.module.locate_garmindb_cli(interpreter)

    def test_runner_discovery_and_binding_accept_explicit_global_python(self):
        with tempfile.TemporaryDirectory() as root:
            config_dir, _, interpreter, cli = self.make_global_environment(root)
            resolved_interpreter, resolved_cli = self.module.locate_garmindb_cli(
                interpreter
            )
            bindings = self.module.build_sync_bindings(config_dir, interpreter)

        self.assertEqual(resolved_interpreter, interpreter.resolve())
        self.assertEqual(resolved_cli, cli.resolve())
        environment = bindings["runner"]["environment"]
        self.assertEqual(
            environment["evidence_method"],
            "explicit_global_python_filesystem_read_only",
        )
        self.assertIsNone(environment["pyvenv_cfg_sha256"])

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

    def test_parallel_tree_digest_matches_sequential_contract(self):
        with tempfile.TemporaryDirectory() as root:
            _, _, interpreter, _ = self.make_bound_environment(root)
            site_packages = Path(root) / "runner-venv" / "Lib" / "site-packages"
            files = sorted(
                (item for item in site_packages.rglob("*") if item.is_file()),
                key=lambda item: item.relative_to(site_packages).as_posix(),
            )
            digest = hashlib.sha256()
            for item in files:
                relative = item.relative_to(site_packages).as_posix().encode("utf-8")
                digest.update(relative)
                digest.update(b"\0")
                digest.update(str(item.stat().st_size).encode("ascii"))
                digest.update(b"\0")
                digest.update(self.module._file_sha256(item).encode("ascii"))
                digest.update(b"\n")
            actual, count = self.module._site_packages_tree_evidence(site_packages)
        self.assertEqual(actual, digest.hexdigest())
        self.assertEqual(count, len(files))

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
                post_sync_verifier=lambda *_: self.complete_verification(),
            )

        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["status"], "sync_completed")
        self.assertTrue(payload["database_changed"])
        self.assertEqual(payload["stale_components"], [])
        self.assertEqual(runner.call_count, 2)
        for call in runner.call_args_list:
            command = call.args[0]
            self.assertEqual(command[0], str(interpreter))
            self.assertEqual(command[1:3], ["-I", "-B"])
            self.assertEqual(command[3], "-c")
            self.assertEqual(command[4], self.module._DATE_ADAPTER_CODE)
            self.assertEqual(command[5], str(cli))
            self.assertEqual(call.kwargs["stdin"], self.module.subprocess.DEVNULL)
            self.assertNotIn("PYTHONPATH", call.kwargs["env"])
        self.assertIn("--download", runner.call_args_list[0].args[0])
        self.assertNotIn("--latest", runner.call_args_list[0].args[0])
        self.assertIn("--import", runner.call_args_list[1].args[0])
        self.assertIn("--analyze", runner.call_args_list[1].args[0])
        self.assertIn("--latest", runner.call_args_list[1].args[0])

    def test_successful_runner_fails_when_post_sync_coverage_is_stale(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        verification = self.complete_verification()
        verification["component_latest_observation_dates"]["hrv"] = "2026-08-06"
        verification["stale_components"] = ["hrv"]
        with tempfile.TemporaryDirectory() as temp_root:
            config_dir, _, interpreter, _ = self.make_bound_environment(temp_root)
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
                post_sync_verifier=lambda *_: verification,
            )

        self.assertEqual(exit_code, self.module.EXIT_SYNC_FAILURE)
        self.assertEqual(payload["status"], "sync_incomplete")
        self.assertEqual(payload["stale_components"], ["hrv"])
        self.assertEqual(runner.call_count, 2)

    def test_sync_runner_receives_bound_token_store_only_in_temporary_config(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        observed = {}

        def inspect_runner(command, **kwargs):
            config_dir = Path(command[command.index("--config") + 1])
            observed["config_dir"] = config_dir
            config_file = config_dir / self.module.CONFIG_NAME
            observed["config_exists"] = config_file.is_file()
            observed["config_payload"] = json.loads(config_file.read_text("utf-8"))
            token_file = config_dir / self.module.TOKEN_STORE_NAME
            observed["token_exists"] = token_file.is_file()
            observed["token_payload"] = json.loads(token_file.read_text("utf-8"))
            return unittest.mock.Mock(returncode=0, stdout="ok")

        with tempfile.TemporaryDirectory() as temp_root:
            config_dir, _, interpreter, _ = self.make_bound_environment(temp_root)
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            plan_path = Path(temp_root) / "sync-plan.json"
            self.module.write_sync_plan_atomic(
                plan_path,
                self.module.build_sync_plan(start, end, bindings=bindings),
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
                runner=inspect_runner,
                post_sync_verifier=lambda *_: self.complete_verification(),
            )

        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["status"], "sync_completed")
        self.assertTrue(observed["config_exists"])
        self.assertTrue(observed["token_exists"])
        self.assertEqual(
            observed["token_payload"],
            {"oauth1": "synthetic", "oauth2": "synthetic"},
        )
        self.assertFalse(
            observed["config_payload"]["directories"]["relative_to_home"]
        )
        self.assertEqual(observed["config_payload"]["data"]["start_date"], "08/01/2026")
        self.assertEqual(observed["config_payload"]["data"]["end_date"], "08/08/2026")
        self.assertEqual(
            Path(observed["config_payload"]["directories"]["base_dir"]),
            Path(temp_root) / ".GarminDb" / "HealthData",
        )
        self.assertFalse(observed["config_dir"].exists())

    def test_changed_config_interpreter_or_cli_invalidates_bound_plan(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        for changed_target in ("config", "token_store", "interpreter", "cli"):
            with self.subTest(changed_target=changed_target), tempfile.TemporaryDirectory() as root:
                config_dir, config_file, interpreter, cli = self.make_bound_environment(root)
                bindings = self.module.build_sync_bindings(config_dir, interpreter)
                plan_path = Path(root) / "sync-plan.json"
                self.module.write_sync_plan_atomic(
                    plan_path,
                    self.module.build_sync_plan(start, end, bindings=bindings),
                )
                if changed_target == "config":
                    changed_config = json.loads(config_file.read_text("utf-8"))
                    changed_config["username"] = "changed@example.test"
                    config_file.write_text(
                        json.dumps(changed_config),
                        encoding="utf-8",
                    )
                elif changed_target == "token_store":
                    (config_dir / self.module.TOKEN_STORE_NAME).write_text(
                        json.dumps({"oauth1": "changed", "oauth2": "changed"}),
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

    def test_post_sync_verifier_requires_end_date_for_all_components(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as temp_root:
            config_dir, _, _, _ = self.make_bound_environment(temp_root)
            database = config_dir / "HealthData" / "DBs" / "garmin.db"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE sleep(day TEXT, total_sleep TEXT);
                    CREATE TABLE hrv(day TEXT, last_night_avg REAL);
                    CREATE TABLE daily_summary(
                        day TEXT, rhr REAL, bb_max REAL, stress_avg REAL
                    );
                    INSERT INTO sleep VALUES('2026-08-07', '07:00:00');
                    INSERT INTO hrv VALUES('2026-08-07', 40.0);
                    INSERT INTO daily_summary VALUES('2026-08-07', 55.0, 80.0, 20.0);
                    """
                )
                connection.commit()
            finally:
                connection.close()

            complete = self.module._verify_post_sync_state(
                config_dir, start, end, before_fingerprint={}
            )
            connection = sqlite3.connect(database)
            try:
                connection.execute("UPDATE hrv SET day = '2026-08-06'")
                connection.commit()
            finally:
                connection.close()
            rhr_dir = config_dir / "HealthData" / "RHR"
            rhr_dir.mkdir()
            (rhr_dir / "hrv_2026-08-07.json").write_text("{}", encoding="utf-8")
            stale = self.module._verify_post_sync_state(
                config_dir, start, end, before_fingerprint={}
            )

        self.assertEqual(complete["stale_components"], [])
        self.assertEqual(
            complete["component_latest_observation_dates"]["sleep"], "2026-08-07"
        )
        self.assertEqual(stale["stale_components"], ["hrv"])
        self.assertEqual(
            stale["source_present_without_coverage_components"], ["hrv"]
        )
        self.assertEqual(stale["no_source_data_components"], [])
        self.assertEqual(
            stale["component_latest_observation_dates"]["hrv"], "2026-08-06"
        )

    def test_importer_errors_fail_even_when_runner_returns_zero(self):
        status = self.module.classify_process_result(
            returncode=0, output="Failed to parse sleep_2026-08-07.json"
        )
        self.assertEqual(status[0], self.module.EXIT_SYNC_FAILURE)
        self.assertEqual(status[1]["status"], "import_failed")

    def test_rate_limit_is_terminal_and_no_fallback_exists(self):
        self.assertFalse(hasattr(self.module, "trigger_fallback"))
        status = self.module.classify_process_result(
            returncode=1, output="HTTP 429 Too Many Requests"
        )
        self.assertEqual(status[0], self.module.EXIT_RATE_LIMIT)
        self.assertEqual(status[1]["status"], "rate_limited")

    def run_synthetic_child(self, root, start, end, *, cli_text=SYNTHETIC_CLI,
                            config_start=None, config_end=None, mutate_command=None):
        root = Path(root)
        cli = root / "garmindb_cli.py"
        cli.write_text(cli_text, encoding="utf-8")
        data = {}
        for stat in ("", "monitoring_", "sleep_", "rhr_", "hrv_", "weight_"):
            data[stat + "start_date"] = (config_start or start).strftime("%m/%d/%Y")
            data[stat + "end_date"] = (
                (config_end or end) + timedelta(days=1)
            ).strftime("%m/%d/%Y")
        config = root / self.module.CONFIG_NAME
        config.write_text(json.dumps({"data": data}), encoding="utf-8")
        command, _ = self.module.build_garmindb_commands(
            Path(sys.executable), cli, root, start=start, end=end,
            cli_sha256=self.module._file_sha256(cli),
            config_sha256=self.module._file_sha256(config),
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
        if mutate_command:
            mutate_command(command, cli, config)
        return subprocess.run(
            command, cwd=root, env=self.module._sanitized_runner_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", check=False, timeout=20,
        )

    def test_actual_upstream_equivalent_clamp_excludes_today(self):
        method = ast.parse(UPSTREAM_DATE_METHOD).body[0]
        self.assertEqual(
            hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest(),
            self.module.UPSTREAM_DATE_METHOD_SHA256,
        )
        today = self.module.date.today()
        with tempfile.TemporaryDirectory() as root:
            def remove_adapter(command, cli, config):
                command[:] = [sys.executable, "-I", "-B", str(cli), "--config", root, "--download"]
            completed = self.run_synthetic_child(
                root, today - timedelta(days=2), today, mutate_command=remove_adapter,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        dates = json.loads(completed.stdout)["dates"]
        self.assertEqual(dates["sleep"], [(today - timedelta(days=i)).isoformat() for i in (2, 1)])

    def test_invoked_child_includes_today_single_day_and_historical_end(self):
        today = self.module.date.today()
        for start, end in ((today, today), (today - timedelta(days=2), today),
                           (today - timedelta(days=8), today - timedelta(days=3))):
            with self.subTest(start=start, end=end), tempfile.TemporaryDirectory() as root:
                completed = self.run_synthetic_child(root, start, end)
                self.assertEqual(completed.returncode, 0, completed.stdout)
                expected = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
                self.assertEqual(json.loads(completed.stdout)["dates"], dict.fromkeys(self.module.SYNC_STATS, expected))
                self.assertEqual(list(Path(root).rglob("*.pyc")), [])

    def test_child_rejects_future_reversed_and_out_of_bound_config_before_cli(self):
        today = self.module.date.today()
        for start, end, config_start, config_end in (
            (today, today + timedelta(days=1), None, None),
            (today, today - timedelta(days=1), None, None),
            (today, today, today - timedelta(days=1), None),
            (today - timedelta(days=2), today - timedelta(days=1), None, today),
        ):
            with self.subTest(start=start, end=end, config_end=config_end), tempfile.TemporaryDirectory() as root:
                # A top-level marker must not execute when preflight rejects.
                marker = Path(root) / "cli-executed"
                cli_text = "from pathlib import Path\nPath('cli-executed').touch()\n" + SYNTHETIC_CLI
                completed = self.run_synthetic_child(
                    root, start, end, cli_text=cli_text,
                    config_start=config_start, config_end=config_end,
                )
                self.assertEqual(completed.returncode, 4, completed.stdout)
                self.assertEqual(json.loads(completed.stdout)["status"], "date_adapter_rejected")
                self.assertFalse(marker.exists())

    def test_future_window_rejected_without_preflight_or_execution(self):
        tomorrow = (self.module.date.today() + timedelta(days=1)).isoformat()
        with patch.object(self.module, "build_sync_bindings") as bind, patch.object(self.module, "execute_sync") as execute:
            code, payload = self.run_main(["sync", "--start", tomorrow, "--end", tomorrow, "--dry-run"])
        self.assertEqual(code, self.module.EXIT_USAGE)
        self.assertEqual(payload["error"], "future_window_forbidden")
        bind.assert_not_called()
        execute.assert_not_called()

    def test_unsupported_upstream_shape_fails_in_preflight_and_child(self):
        changed = SYNTHETIC_CLI.replace(".days, days)", ".days + 1, days)")
        with tempfile.TemporaryDirectory() as root:
            config_dir, _, interpreter, cli = self.make_bound_environment(root)
            cli.write_text(changed, encoding="utf-8")
            with patch.object(self.module.subprocess, "run") as run, self.assertRaisesRegex(
                self.module.SyncConfigurationError, "runner_date_method_unsupported"
            ):
                self.module.build_sync_bindings(config_dir, interpreter)
            run.assert_not_called()
            child_root = Path(root) / "child"
            child_root.mkdir()
            completed = self.run_synthetic_child(child_root, self.module.date.today(), self.module.date.today(), cli_text=changed)
        self.assertEqual(completed.returncode, 4, completed.stdout)
        self.assertEqual(json.loads(completed.stdout)["error"], "runner_date_method_unsupported")

    def test_child_rechecks_cli_config_expiry_and_forbids_latest_download(self):
        for mutation in ("cli", "config", "expiry", "latest"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                def mutate(command, cli, config, mutation=mutation):
                    if mutation == "cli":
                        cli.write_text(SYNTHETIC_CLI + "\n# drift", encoding="utf-8")
                    elif mutation == "config":
                        config.write_text("{}", encoding="utf-8")
                    elif mutation == "expiry":
                        command[11] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                    else:
                        command.append("--latest")
                completed = self.run_synthetic_child(root, self.module.date.today(), self.module.date.today(), mutate_command=mutate)
                self.assertEqual(completed.returncode, 4, completed.stdout)
                self.assertEqual(json.loads(completed.stdout)["status"], "date_adapter_rejected")
                code, payload = self.module.classify_process_result(completed.returncode, completed.stdout)
                self.assertEqual(code, self.module.EXIT_CONFIGURATION)
                self.assertNotIn(root, json.dumps(payload))

    def test_child_rejects_upstream_config_result_outside_bound_window(self):
        changed = SYNTHETIC_CLI.replace("return start, (end - start).days", "return start - datetime.timedelta(days=1), (end - start).days")
        with tempfile.TemporaryDirectory() as root:
            completed = self.run_synthetic_child(root, self.module.date.today(), self.module.date.today(), cli_text=changed)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("adapter_date_range_mismatch", completed.stdout)
        self.assertNotIn('"dates":', completed.stdout)

    def test_bound_execute_allows_temporary_token_refresh_in_isolated_download(self):
        today = self.module.date.today()
        start = today - timedelta(days=2)
        request: dict[str, object] = {"window": {"start": start.isoformat(), "end": today.isoformat()}}
        observed = []
        temporary_dirs = []
        real_run = subprocess.run
        with tempfile.TemporaryDirectory() as root:
            config_dir, _, interpreter, cli = self.make_bound_environment(root)
            token = config_dir / self.module.TOKEN_STORE_NAME
            original_token = token.read_bytes()
            refresh = (
                "        (config_dir / " + repr(self.module.TOKEN_STORE_NAME)
                + ").write_bytes(b'synthetic refreshed token')\n"
            )
            cli.write_text(SYNTHETIC_CLI.replace(
                'if "--download" in sys.argv:\n',
                'if "--download" in sys.argv:\n' + refresh,
            ), encoding="utf-8")
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            bindings["runner"]["interpreter"] = self.module._runner_file_binding(Path(sys.executable))
            plan_path = Path(root) / "plan.json"
            self.module.write_sync_plan_atomic(plan_path, self.module.build_sync_plan(start, today, bindings=bindings))
            def run_child(command, **kwargs):
                temporary_dirs.append(kwargs["cwd"])
                completed = real_run(command, **kwargs)
                self.assertEqual(completed.returncode, 0, completed.stdout)
                self.assertEqual(
                    (kwargs["cwd"] / self.module.TOKEN_STORE_NAME).read_bytes(),
                    b"synthetic refreshed token",
                )
                self.assertEqual(token.read_bytes(), original_token)
                observed.append(json.loads(completed.stdout))
                return completed
            with patch.object(self.module, "locate_garmindb_cli", return_value=(Path(sys.executable), cli)), patch.object(
                self.module, "build_runner_binding", return_value=bindings["runner"]
            ):
                code, payload = self.module.execute_sync(
                    start, today,
                    network_capability=issue_capability(scope="network", operation="garmindb_sync", request=request),
                    sync_capability=issue_capability(scope="sync", operation="garmindb_sync", request=request),
                    plan_file=plan_path, config_dir=config_dir, garmindb_python=Path(sys.executable),
                    runner=run_child, post_sync_verifier=lambda *_: self.complete_verification(today.isoformat()),
                )
            self.assertEqual(token.read_bytes(), original_token)
            self.assertTrue(temporary_dirs)
            self.assertTrue(all(not path.exists() for path in temporary_dirs))
        self.assertEqual(code, 0, payload)
        self.assertEqual([item["stage"] for item in observed], ["download", "import_analyze"])
        self.assertEqual(observed[0]["dates"]["sleep"], [(start + timedelta(days=i)).isoformat() for i in range(3)])
        self.assertEqual(observed[1]["dates"], {})

    def test_stage_guards_reject_token_before_download_and_config_or_runner_before_import(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        for target in ("token", "config", "runner"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as root:
                config_dir, _, interpreter, cli = self.make_bound_environment(root)
                bindings = self.module.build_sync_bindings(config_dir, interpreter)
                plan_path = Path(root) / "plan.json"
                self.module.write_sync_plan_atomic(
                    plan_path, self.module.build_sync_plan(start, end, bindings=bindings),
                )
                temporary_dirs = []
                original_commands = self.module.build_garmindb_commands

                def build_commands(*args, target=target, original_commands=original_commands,
                                   temporary_dirs=temporary_dirs, **kwargs):
                    commands = original_commands(*args, **kwargs)
                    temporary_dirs.append(args[2])
                    if target == "token":
                        (args[2] / self.module.TOKEN_STORE_NAME).write_bytes(b"tampered input")
                    return commands

                def download(*args, target=target, cli=cli, **kwargs):
                    if target == "config":
                        (kwargs["cwd"] / self.module.CONFIG_NAME).write_text("{}", encoding="utf-8")
                    elif target == "runner":
                        cli.write_text(SYNTHETIC_CLI + "\n# changed", encoding="utf-8")
                    return subprocess.CompletedProcess(args[0], 0, stdout="")

                runner = unittest.mock.Mock(side_effect=download)
                with patch.object(self.module, "build_garmindb_commands", side_effect=build_commands):
                    code, payload = self.module.execute_sync(
                        start, end,
                        network_capability=issue_capability(scope="network", operation="garmindb_sync", request=SYNC_REQUEST),
                        sync_capability=issue_capability(scope="sync", operation="garmindb_sync", request=SYNC_REQUEST),
                        plan_file=plan_path, config_dir=config_dir, garmindb_python=interpreter,
                        runner=runner,
                    )
                self.assertEqual(code, self.module.EXIT_CONFIGURATION, payload)
                self.assertEqual(payload["error"], {
                    "token": "temporary_token_store_changed",
                    "config": "temporary_config_changed",
                    "runner": "bound_runner_changed",
                }[target])
                self.assertEqual(runner.call_count, 0 if target == "token" else 1)
                self.assertTrue(all(not path.exists() for path in temporary_dirs))

    def test_adapter_file_drift_invalidates_plan_before_child(self):
        start, end = self.module.parse_window("2026-08-01", "2026-08-07")
        with tempfile.TemporaryDirectory() as root:
            config_dir, _, interpreter, _ = self.make_bound_environment(root)
            bindings = self.module.build_sync_bindings(config_dir, interpreter)
            bindings["runner"]["adapter"]["sha256"] = "0" * 64
            plan_path = Path(root) / "plan.json"
            self.module.write_sync_plan_atomic(plan_path, self.module.build_sync_plan(start, end, bindings=bindings))
            runner = unittest.mock.Mock()
            code, payload = self.module.execute_sync(
                start, end,
                network_capability=issue_capability(scope="network", operation="garmindb_sync", request=SYNC_REQUEST),
                sync_capability=issue_capability(scope="sync", operation="garmindb_sync", request=SYNC_REQUEST),
                plan_file=plan_path, config_dir=config_dir, garmindb_python=interpreter, runner=runner,
            )
        self.assertEqual(code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["error"], "plan_bindings_mismatch")
        runner.assert_not_called()

    def test_bound_plan_preflight_does_not_execute_cli_or_network(self):
        with tempfile.TemporaryDirectory() as root:
            config_dir, _, interpreter, cli = self.make_bound_environment(root)
            cli.write_text("raise AssertionError('must_not_execute')\n" + SYNTHETIC_CLI, encoding="utf-8")
            with patch("socket.socket", side_effect=AssertionError("no network")), patch.object(self.module.subprocess, "run") as run:
                code, payload = self.run_main([
                    "sync", "--start", "2026-08-01", "--end", "2026-08-07", "--dry-run",
                    "--config-dir", str(config_dir), "--garmindb-python", str(interpreter),
                    "--plan-output", str(Path(root) / "plan.json"),
                ])
            run.assert_not_called()
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["network_accessed"])

    def test_commands_keep_download_bounded_and_import_only_latest_files(self):
        download, import_analyze = self.module.build_garmindb_commands(
            Path("C:/Python/python.exe"),
            Path("C:/Python/Scripts/garmindb_cli.py"),
            Path("C:/safe/window-config"),
            start=self.module.date(2026, 8, 1), end=self.module.date(2026, 8, 7),
            cli_sha256="a" * 64, config_sha256="b" * 64,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        )
        self.assertNotIn("--all", download)
        self.assertNotIn("--latest", download)
        self.assertIn("--download", download)
        self.assertNotIn("--import", download)
        self.assertIn("--latest", import_analyze)
        self.assertNotIn("--download", import_analyze)
        self.assertIn("--import", import_analyze)
        self.assertIn("--analyze", import_analyze)
        for command in (download, import_analyze):
            self.assertEqual(command[1:3], ["-I", "-B"])
            self.assertIn("--monitoring", command)
            self.assertIn("--sleep", command)
            self.assertIn("--rhr", command)
            self.assertIn("--hrv", command)
            self.assertIn("--weight", command)


if __name__ == "__main__":
    unittest.main()
