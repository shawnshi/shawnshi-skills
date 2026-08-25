import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import blackboard


class BlackboardContractTests(unittest.TestCase):
    def test_loading_existing_blackboard_does_not_reset_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blackboard.json"
            with patch.object(blackboard, "BLACKBOARD_PATH", path):
                blackboard.init_blackboard()
                blackboard.update_phase("baseline", "completed")
                blackboard.append_signal({"event_id": "evt-1"})

                reloaded = blackboard.load_blackboard()

        self.assertEqual(reloaded["phase"], "baseline")
        self.assertEqual(reloaded["status"], "completed")
        self.assertEqual(reloaded["signals"], [{"event_id": "evt-1"}])

    def test_explicit_paths_isolate_concurrent_blackboard_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "first" / "blackboard.json"
            second_path = root / "second" / "blackboard.json"
            barrier = threading.Barrier(2)

            def update_isolated_board(path: Path, label: str, count: int) -> dict:
                blackboard.init_blackboard(blackboard_path=path)
                barrier.wait(timeout=5)
                blackboard.update_phase(label, "running", blackboard_path=path)
                blackboard.record_scan_stats(count, count * 10, blackboard_path=path)
                blackboard.append_signal({"event_id": label}, blackboard_path=path)
                blackboard.mark_adversarial_audit({"lane": label}, blackboard_path=path)
                blackboard.finalize_briefing(
                    f"{label}.md",
                    blackboard_path=path,
                )
                return blackboard.load_blackboard(blackboard_path=path)

            with ThreadPoolExecutor(max_workers=2) as pool:
                first_future = pool.submit(update_isolated_board, first_path, "first", 1)
                second_future = pool.submit(update_isolated_board, second_path, "second", 2)
                first = first_future.result(timeout=10)
                second = second_future.result(timeout=10)

            self.assertEqual(first["scan_stats"]["source_count"], 1)
            self.assertEqual(first["signals"], [{"event_id": "first"}])
            self.assertEqual(first["adversarial_audit"], {"lane": "first"})
            self.assertEqual(first["final_briefing"]["path"], "first.md")
            self.assertEqual(second["scan_stats"]["source_count"], 2)
            self.assertEqual(second["signals"], [{"event_id": "second"}])
            self.assertEqual(second["adversarial_audit"], {"lane": "second"})
            self.assertEqual(second["final_briefing"]["path"], "second.md")
            self.assertEqual(list(root.rglob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
