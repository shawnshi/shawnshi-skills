import argparse
import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("freshness_task_gate.py")
SPEC = importlib.util.spec_from_file_location("freshness_task_gate", MODULE_PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gate)


def args():
    return argparse.Namespace(
        allow_network=True,
        allow_sync=True,
        allow_health_data=True,
        end=date.today().isoformat(),
        max_polls=3,
        poll_seconds=0.1,
        task_name="Codex-Garmin-Health-Sync",
        python=r"C:\Python\python.exe",
        runner=r"C:\skill\scripts\garmin_auto_sync.py",
        authority_config=r"C:\skill\runtime-authority.json",
        state_output=r"C:\state\status.json",
        allow_direct_sync=False,
        direct_config_dir=None,
        direct_garmindb_python=None,
        direct_scratch_dir=None,
        direct_days=7,
        direct_timeout_seconds=480,
        direct_total_timeout_seconds=900,
    )


def task(state="Ready"):
    return {
        "ok": True,
        "exists": True,
        "task_name": "Codex-Garmin-Health-Sync",
        "task_path": "\\",
        "state": state,
        "enabled": True,
        "current_identity": r"HOST\user",
        "current_sid": "S-1-5-21-1-2-3-1001",
        "user_id": r"HOST\user",
        "task_user_sid": "S-1-5-21-1-2-3-1001",
        "run_level": "Limited",
        "logon_type": "Interactive",
        "multiple_instances": "IgnoreNew",
        "start_when_available": True,
        "action_count": 1,
        "execute": r"C:\Python\python.exe",
        "working_directory": r"C:\skill\scripts",
        "arguments": (
            r"C:\skill\scripts\garmin_auto_sync.py --authority-config "
            r"C:\skill\runtime-authority.json --state-output C:\state\status.json "
            "--allow-network --allow-sync --allow-health-data"
        ),
        "arguments_sha256": "b" * 64,
    }


def terminal(run_id="new", status="success", end=None):
    end = end or date.today().isoformat()
    start = (date.fromisoformat(end) - timedelta(days=6)).isoformat()
    payload = {
        "status": status,
        "run_id": run_id,
        "requested_window": {"start": start, "end": end},
        "runtime_binding": {"authority_version": "11.6.0", "authority_sha256": "a" * 64},
        "database_fingerprint_changed": True,
        "component_latest_observation_dates": {name: end for name in gate.COMPONENTS},
        "health_values_persisted": False,
    }
    if status == "failed":
        payload["error_code"] = "sync_failed"
    return payload


class FreshnessTaskGateTests(unittest.TestCase):
    def setUp(self):
        self.original_verify = gate.runtime_authority.verify
        gate.runtime_authority.verify = lambda _: {
            "ok": True,
            "authority_version": "11.6.0",
            "authority_sha256": "a" * 64,
            "task_binding": {"arguments_sha256": "b" * 64},
            "entrypoints": {"scripts/garmin_auto_sync.py": r"C:\skill\scripts\garmin_auto_sync.py"},
        }
        self.original_read = Path.read_text
        Path.read_text = lambda self, encoding=None: "{}"

    def tearDown(self):
        gate.runtime_authority.verify = self.original_verify
        Path.read_text = self.original_read

    def test_started_task_ignores_old_terminal_until_new_run_id(self):
        probes = iter((task("Ready"), {"ok": True}, task("Running"), task("Ready")))
        states = iter((terminal("old"), terminal("old"), terminal("new")))
        code, audit = gate.run_gate(
            args(), probe=lambda _: next(probes), state_reader=lambda: next(states), sleeper=lambda _: None
        )
        self.assertEqual(code, 0)
        self.assertEqual(audit["task_status"], "success")

    def test_abandoned_running_state_is_interrupted(self):
        probes = iter((task("Running"), task("Ready")))
        states = iter(({"status": "running", "run_id": "one"}, {"status": "running", "run_id": "one"}))
        code, audit = gate.run_gate(
            args(), probe=lambda _: next(probes), state_reader=lambda: next(states), sleeper=lambda _: None
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["task_status"], "interrupted_or_terminated")

    def test_running_task_cannot_reuse_old_success_terminal(self):
        options = args()
        options.max_polls = 2
        probes = iter((task("Running"), task("Ready"), task("Ready")))
        old = terminal("old")
        states = iter((old, old, old))
        code, audit = gate.run_gate(
            options, probe=lambda _: next(probes), state_reader=lambda: next(states), sleeper=lambda _: None
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["task_status"], "timeout")

    def test_future_or_malformed_terminal_date_is_rejected(self):
        authority = {"authority_version": "11.6.0", "authority_sha256": "a" * 64}
        for invalid in ("2026-08-27", "2026-8-26", "bad"):
            with self.subTest(invalid=invalid):
                state = terminal(end="2026-08-26")
                state["component_latest_observation_dates"]["sleep"] = invalid
                self.assertIsNotNone(gate.validate_terminal_state(state, "2026-08-26", authority, "new"))

    def test_same_username_with_different_sid_is_rejected(self):
        snapshot = task()
        snapshot["current_identity"] = r"DOMAIN-A\alice"
        snapshot["user_id"] = r"DOMAIN-B\alice"
        snapshot["task_user_sid"] = "S-1-5-21-9-9-9-1001"
        expected = {
            "task_name": args().task_name,
            "python": args().python,
            "working_directory": str(Path(args().runner).resolve().parent),
            "arguments_sha256": "b" * 64,
        }
        self.assertEqual(gate.validate_task(snapshot, expected), "task_user_drift")

    def test_permission_denied_never_falls_back_to_direct_sync(self):
        options = args()
        options.allow_direct_sync = True
        called = []
        code, audit = gate.run_gate(
            options,
            probe=lambda _: {"ok": False, "exists": None, "error_code": "task_probe_permission_denied"},
            state_reader=lambda: None,
            sleeper=lambda _: None,
            direct_runner=lambda: called.append(True) or 0,
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "task_probe_permission_denied")
        self.assertEqual(called, [])

    def test_verified_missing_task_uses_direct_sync_and_binds_new_terminal(self):
        options = args()
        options.end = "2026-08-26"
        options.allow_direct_sync = True
        states = iter((terminal("old", end="2026-08-26"), terminal("new", end="2026-08-26")))
        probes = iter((
            {"ok": True, "exists": False, "reason": "task_missing"},
            {"ok": True, "exists": False, "reason": "task_missing"},
        ))
        code, audit = gate.run_gate(
            options,
            probe=lambda _: next(probes),
            state_reader=lambda: next(states),
            sleeper=lambda _: None,
            direct_runner=lambda: 0,
            today=date(2026, 8, 26),
        )
        self.assertEqual(code, 0)
        self.assertEqual(audit["sync_attempted"], "direct")
        self.assertEqual(audit["task_status"], "success")

    def test_missing_then_permission_denied_never_runs_direct(self):
        options = args()
        options.end = "2026-08-26"
        options.allow_direct_sync = True
        probes = iter((
            {"ok": True, "exists": False, "reason": "task_missing"},
            {"ok": False, "exists": None, "error_code": "task_probe_permission_denied"},
        ))
        called = []
        code, audit = gate.run_gate(
            options,
            probe=lambda _: next(probes),
            state_reader=lambda: None,
            sleeper=lambda _: None,
            direct_runner=lambda: called.append(True) or 0,
            today=date(2026, 8, 26),
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "task_probe_permission_denied")
        self.assertEqual(called, [])

    def test_direct_sync_rejects_old_terminal_run_id(self):
        options = args()
        options.end = "2026-08-26"
        options.allow_direct_sync = True
        probes = iter((
            {"ok": True, "exists": False, "reason": "task_missing"},
            {"ok": True, "exists": False, "reason": "task_missing"},
        ))
        old = terminal("old")
        code, audit = gate.run_gate(
            options,
            probe=lambda _: next(probes),
            state_reader=lambda: old,
            sleeper=lambda _: None,
            direct_runner=lambda: 0,
            today=date(2026, 8, 26),
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "direct_terminal_run_id_missing")

    def test_direct_sync_rejects_terminal_start_mismatch(self):
        options = args()
        options.end = "2026-08-26"
        options.allow_direct_sync = True
        probes = iter((
            {"ok": True, "exists": False, "reason": "task_missing"},
            {"ok": True, "exists": False, "reason": "task_missing"},
        ))
        bad = terminal("new", end="2026-08-26")
        bad["requested_window"]["start"] = "2026-08-21"
        states = iter((terminal("old", end="2026-08-26"), bad))
        code, audit = gate.run_gate(
            options,
            probe=lambda _: next(probes),
            state_reader=lambda: next(states),
            sleeper=lambda _: None,
            direct_runner=lambda: 0,
            today=date(2026, 8, 26),
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "terminal_window_mismatch")

    def test_malformed_missing_snapshot_never_runs_direct(self):
        options = args()
        options.allow_direct_sync = True
        called = []
        code, audit = gate.run_gate(
            options,
            probe=lambda _: {"ok": True, "exists": False},
            state_reader=lambda: None,
            sleeper=lambda _: None,
            direct_runner=lambda: called.append(True) or 0,
        )
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "task_probe_invalid")
        self.assertEqual(called, [])

    def test_non_current_end_rejected_before_probe(self):
        options = args()
        options.end = "2020-01-01"
        called = []
        code, audit = gate.run_gate(
            options,
            probe=lambda _: called.append(True) or task(),
            state_reader=lambda: None,
            sleeper=lambda _: None,
        )
        self.assertEqual(code, 2)
        self.assertEqual(audit["reason"], "requested_end_not_current")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
