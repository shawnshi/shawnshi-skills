import argparse
import importlib.util
import unittest
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
        end="2026-08-26",
        max_polls=3,
        poll_seconds=0.1,
        task_name="Codex-Garmin-Health-Sync",
        python=r"C:\Python\python.exe",
        runner=r"C:\skill\scripts\garmin_auto_sync.py",
        authority_config=r"C:\skill\runtime-authority.json",
        state_output=r"C:\state\status.json",
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


def terminal(run_id="new", status="success"):
    payload = {
        "status": status,
        "run_id": run_id,
        "requested_window": {"end": "2026-08-26"},
        "runtime_binding": {"authority_version": "11.6.0", "authority_sha256": "a" * 64},
        "database_fingerprint_changed": True,
        "component_latest_observation_dates": {name: "2026-08-26" for name in gate.COMPONENTS},
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
                state = terminal()
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


if __name__ == "__main__":
    unittest.main()
