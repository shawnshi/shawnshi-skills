import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("context_recovery_receipt.py")


class ContextRecoveryReceiptTests(unittest.TestCase):
    def test_valid_state_emits_redacted_receipt(self):
        state = {
            "objective": "finish audit",
            "authorization_scope": {"mode": "local_write"},
            "completed_steps": ["freeze snapshot"],
            "output_paths": ["C:/scratch/events.jsonl"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            output = root / "receipt.jsonl"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--state",
                    str(state_path),
                    "--root-task-id",
                    "r1",
                    "--actor-id",
                    "root",
                    "--context-epoch",
                    "2",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(receipt["required_fields_verified"])
        self.assertEqual(receipt["completed_step_count"], 1)
        self.assertEqual(receipt["output_path_count"], 1)
        self.assertNotIn("finish audit", json.dumps(receipt))

    def test_missing_authorization_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_path = root / "state.json"
            output = root / "receipt.jsonl"
            state_path.write_text(
                json.dumps({"objective": "audit", "completed_steps": [], "output_paths": []}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--state",
                    str(state_path),
                    "--root-task-id",
                    "r1",
                    "--actor-id",
                    "root",
                    "--context-epoch",
                    "2",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
