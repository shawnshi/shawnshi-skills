import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from await_artifacts import wait_for_artifacts


class AwaitArtifactsTests(unittest.TestCase):
    def test_waits_for_delayed_atomic_json_object(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"

            def publish() -> None:
                time.sleep(0.03)
                temporary = target.with_suffix(".tmp")
                temporary.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
                os.replace(temporary, target)

            writer = threading.Thread(target=publish)
            writer.start()
            result = wait_for_artifacts(
                [target], timeout_seconds=1, stable_seconds=0.03, poll_seconds=0.01
            )
            writer.join()

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["artifacts"][0]["path"], str(target.resolve()))
            self.assertEqual(len(result["artifacts"][0]["sha256"]), 64)

    def test_partial_json_is_not_treated_as_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            target.write_text('{"status":', encoding="utf-8")

            result = wait_for_artifacts(
                [target], timeout_seconds=0.05, stable_seconds=0, poll_seconds=0.01
            )

            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(result["pending"][0]["reason"], "invalid_json")

    def test_requires_json_object_not_array(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            target.write_text("[]", encoding="utf-8")

            result = wait_for_artifacts(
                [target], timeout_seconds=0.05, stable_seconds=0, poll_seconds=0.01
            )

            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(result["pending"][0]["reason"], "not_json_object")

    def test_rejects_waits_longer_than_runtime_update_budget(self):
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            wait_for_artifacts([Path("missing.json")], timeout_seconds=11)


if __name__ == "__main__":
    unittest.main()
