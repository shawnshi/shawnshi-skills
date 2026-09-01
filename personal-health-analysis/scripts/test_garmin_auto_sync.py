import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("garmin_auto_sync.py")
SPEC = importlib.util.spec_from_file_location("garmin_auto_sync", MODULE_PATH)
if SPEC is None:
    raise RuntimeError("garmin_auto_sync module spec is unavailable")
auto_sync = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("garmin_auto_sync module loader is unavailable")
SPEC.loader.exec_module(auto_sync)


class GarminAutoSyncTests(unittest.TestCase):
    def test_window_is_inclusive_and_bounded(self):
        self.assertEqual(auto_sync.compute_window(date(2026, 8, 23), 7), ("2026-08-17", "2026-08-23"))
        for invalid in (0, 32):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    auto_sync.compute_window(date(2026, 8, 23), invalid)

    def test_error_codes_do_not_persist_paths(self):
        code = auto_sync._safe_error_code("database_fingerprint_before", OSError(r"C:\private\health.db"))
        self.assertEqual(code, "database_fingerprint_before_oserror")
        self.assertNotIn("private", code)

    def test_terminal_component_dates_must_be_exact_iso_end_date(self):
        valid = {name: "2026-08-23" for name in auto_sync.COMPONENTS}
        self.assertEqual(auto_sync._stale_components(valid, "2026-08-23"), [])
        for invalid in ("2026-8-23", "2026-08-24", "not-a-date", None):
            with self.subTest(invalid=invalid):
                dates = {**valid, "sleep": invalid}
                self.assertIn("sleep", auto_sync._stale_components(dates, "2026-08-23"))

    def test_all_three_capabilities_are_required(self):
        args = argparse.Namespace(
            allow_network=True,
            allow_sync=False,
            allow_health_data=True,
            days=7,
            garmindb_python=__file__,
            config_dir=str(Path(__file__).parent),
            scratch_dir=str(Path(__file__).parent),
            state_output=str(Path(__file__).with_suffix(".state.json")),
            authority_config=__file__,
            timeout_seconds=600,
            total_timeout_seconds=900,
        )
        code, state = auto_sync.run_scheduled_sync(args, today=date(2026, 8, 23))
        self.assertEqual(code, 2)
        self.assertEqual(state["status"], "capability_denied")

    def test_success_state_contains_coverage_but_no_health_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config"
            config.mkdir()
            state_path = root / "state" / "status.json"
            scratch = root / "scratch"
            calls = []

            def fake_runner(command, timeout):
                calls.append((command, timeout))
                if "--plan-output" in command:
                    Path(command[command.index("--plan-output") + 1]).write_text("{}", encoding="utf-8")
                    return {"status": "dry_run"}
                if "sync_health_data.py" in " ".join(command):
                    return {"status": "sync_completed"}
                if command[-1] == "live" or command[-1] == "local":
                    return {"ok": True, "status": "RUNTIME_READY"}
                return {
                    "status": "partial",
                    "data_status": "partial",
                    "observations": {
                        "sleep": {"latest_duration_hours": 8.25, "observation_count": 5, "date": "2026-08-23"},
                        "hrv": {"latest": 48, "observation_count": 5, "date": "2026-08-23"},
                        "body_battery": {"highest": {"latest": 100, "observation_count": 5, "date": "2026-08-23"}},
                        "resting_heart_rate": {"latest": 52, "observation_count": 5, "date": "2026-08-23"},
                        "stress_average": {"latest": 22, "observation_count": 5, "date": "2026-08-23"},
                    },
                }

            args = argparse.Namespace(
                allow_network=True,
                allow_sync=True,
                allow_health_data=True,
                days=7,
                garmindb_python=__file__,
                config_dir=str(config),
                scratch_dir=str(scratch),
                state_output=str(state_path),
                authority_config=__file__,
                timeout_seconds=600,
                total_timeout_seconds=900,
            )
            fingerprints = iter(("before", "after"))
            code, state = auto_sync.run_scheduled_sync(
                args,
                runner=fake_runner,
                authority_verifier=lambda _: {
                    "ok": True,
                    "authority_version": "11.6.0",
                    "authority_sha256": "a" * 64,
                },
                database_fingerprinter=lambda: next(fingerprints),
                today=date(2026, 8, 23),
            )
            self.assertEqual(code, 0)
            self.assertEqual(state["status"], "success")
            self.assertEqual(state["latest_observation_date"], "2026-08-23")
            self.assertTrue(state["database_fingerprint_changed"])
            persisted = json.loads(state_path.read_text(encoding="utf-8"))

            def keys_in(value):
                if isinstance(value, dict):
                    return set(value) | set().union(*(keys_in(item) for item in value.values()))
                if isinstance(value, list):
                    return set().union(*(keys_in(item) for item in value))
                return set()

            self.assertTrue(
                {"latest_duration_hours", "latest", "highest"}.isdisjoint(keys_in(persisted))
            )
            self.assertFalse(persisted["health_values_persisted"])
            plan_timeout = next(timeout for command, timeout in calls if "--plan-output" in command)
            self.assertEqual(plan_timeout, auto_sync.PLAN_TIMEOUT_SECONDS)

    def test_plan_timeout_is_sanitized_in_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config"
            config.mkdir()
            state_path = root / "state" / "status.json"
            scratch = root / "scratch"

            def fake_runner(command, timeout):
                if command[-1] == "live":
                    return {"ok": True, "status": "RUNTIME_READY"}
                if "--plan-output" in command:
                    raise subprocess.TimeoutExpired(command, timeout)
                raise AssertionError("unexpected command")

            args = argparse.Namespace(
                allow_network=True,
                allow_sync=True,
                allow_health_data=True,
                days=7,
                garmindb_python=__file__,
                config_dir=str(config),
                scratch_dir=str(scratch),
                state_output=str(state_path),
                authority_config=__file__,
                timeout_seconds=600,
                total_timeout_seconds=900,
            )
            code, state = auto_sync.run_scheduled_sync(
                args,
                runner=fake_runner,
                authority_verifier=lambda _: {
                    "ok": True,
                    "authority_version": "11.6.0",
                    "authority_sha256": "a" * 64,
                },
                database_fingerprinter=lambda: "before",
                today=date(2026, 8, 23),
            )
            self.assertEqual(code, 1)
            self.assertEqual(state["error_code"], "plan_timeout")
            self.assertNotIn("sync_health_data.py", json.dumps(state))

    def test_installer_uses_limited_interactive_singleton_task(self):
        installer = Path(__file__).with_name("install_auto_sync_task.ps1").read_text(encoding="utf-8")
        for marker in (
            "-LogonType Interactive",
            "-RunLevel Limited",
            "-StartWhenAvailable",
            "-MultipleInstances IgnoreNew",
            "--allow-network', '--allow-sync', '--allow-health-data",
            "--authority-config",
            "-ExecutionTimeLimit (New-TimeSpan -Minutes 18)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, installer)


if __name__ == "__main__":
    unittest.main()
