import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hub_utils import atomic_dump_json, atomic_write_text


SCRIPT_DIR = Path(__file__).resolve().parent


class ArchiveContractTests(unittest.TestCase):
    def test_default_news_directory_is_memory_news(self):
        environment = dict(os.environ)
        environment.pop("PIH_NEWS_DIR", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
                    "import hub_utils; print(hub_utils.NEWS_DIR)"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            Path(result.stdout.strip()),
            Path.home() / "MEMORY" / "raw" / "news",
        )

    def test_environment_override_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["PIH_NEWS_DIR"] = directory
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
                        "import hub_utils; print(hub_utils.NEWS_DIR)"
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(Path(result.stdout.strip()), Path(directory))

    def test_atomic_writes_replace_target_and_remove_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text_path = root / "briefing.md"
            json_path = root / "briefing.json"
            text_path.write_text("old", encoding="utf-8")
            atomic_write_text(text_path, "new")
            atomic_dump_json(json_path, {"status": "ok"})

            self.assertEqual(text_path.read_text(encoding="utf-8"), "new")
            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8")),
                {"status": "ok"},
            )
            self.assertFalse((root / "briefing.md.tmp").exists())
            self.assertFalse((root / "briefing.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
