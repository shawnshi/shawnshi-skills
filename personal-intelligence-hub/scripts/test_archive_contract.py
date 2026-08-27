import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from hub_utils import (
    WINDOWS_REPLACE_RETRY_DELAYS,
    _replace_with_retry,
    atomic_dump_json,
    atomic_write_text,
)


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

    def test_default_runtime_directory_is_workspace_backed(self):
        environment = dict(os.environ)
        environment.pop("PIH_RUNTIME_DIR", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
                    "import hub_utils; print(hub_utils.RUNTIME_DIR)"
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
            Path.home() / "MEMORY" / "brain" / "personal-intelligence-hub" / "runtime",
        )

    def test_runtime_environment_override_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["PIH_RUNTIME_DIR"] = directory
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
                        "import hub_utils; print(hub_utils.RUNTIME_DIR)"
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

    def test_concurrent_atomic_writers_do_not_share_a_temporary_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "briefing.md"
            barrier = threading.Barrier(2)
            original_replace = os.replace
            source_paths = []
            synchronized_sources = set()
            source_paths_lock = threading.Lock()

            def synchronized_replace(source, destination):
                with source_paths_lock:
                    source_path = Path(source)
                    source_paths.append(source_path)
                    first_attempt = source_path not in synchronized_sources
                    synchronized_sources.add(source_path)
                if first_attempt:
                    barrier.wait(timeout=5)
                return original_replace(source, destination)

            payloads = ("A" * 32768, "B" * 32768)
            replace_errors = []
            with patch("hub_utils.os.replace", side_effect=synchronized_replace):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(atomic_write_text, target, payload) for payload in payloads]
                    for future in futures:
                        try:
                            future.result(timeout=10)
                        except OSError as exc:
                            replace_errors.append(exc)

            self.assertEqual(len(set(source_paths)), 2)
            self.assertLessEqual(len(replace_errors), 1)
            self.assertIn(target.read_text(encoding="utf-8"), payloads)
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_atomic_write_cleans_only_its_temporary_file_after_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "briefing.md"

            with patch("hub_utils.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_text(target, "new")

            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_windows_replace_retries_bounded_transient_lock(self):
        transient = PermissionError(13, "access denied")
        transient.winerror = 5
        with (
            patch("hub_utils.os.name", "nt"),
            patch("hub_utils.os.replace", side_effect=[transient, transient, None]) as replace,
            patch("hub_utils.time.sleep") as sleep,
        ):
            _replace_with_retry(Path("source"), Path("destination"))

        self.assertEqual(replace.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            list(WINDOWS_REPLACE_RETRY_DELAYS[:2]),
        )

    def test_windows_replace_fails_closed_after_retry_budget(self):
        transient = PermissionError(13, "access denied")
        transient.winerror = 5
        with (
            patch("hub_utils.os.name", "nt"),
            patch("hub_utils.os.replace", side_effect=transient) as replace,
            patch("hub_utils.time.sleep") as sleep,
            self.assertRaises(PermissionError),
        ):
            _replace_with_retry(Path("source"), Path("destination"))

        self.assertEqual(replace.call_count, len(WINDOWS_REPLACE_RETRY_DELAYS) + 1)
        self.assertEqual(sleep.call_count, len(WINDOWS_REPLACE_RETRY_DELAYS))


if __name__ == "__main__":
    unittest.main()
