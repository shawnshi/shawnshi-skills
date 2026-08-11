import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
