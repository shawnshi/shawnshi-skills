import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from publish_directory_no_replace import PublishError, publish_directory_no_replace


class PublishDirectoryNoReplaceTests(unittest.TestCase):
    def test_publish_moves_complete_directory_when_target_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".pia-venv-staging-synthetic"
            target = root / "published"
            staging.mkdir()
            (staging / "sentinel.txt").write_text("complete", encoding="utf-8")

            published = publish_directory_no_replace(staging, target)

            self.assertEqual(published, target)
            self.assertFalse(staging.exists())
            self.assertEqual(
                (target / "sentinel.txt").read_text(encoding="utf-8"), "complete"
            )

    def test_existing_target_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".pia-venv-staging-synthetic"
            target = root / "published"
            staging.mkdir()
            target.mkdir()
            (staging / "new.txt").write_text("new", encoding="utf-8")
            (target / "sentinel.txt").write_text("preserve", encoding="utf-8")

            with self.assertRaisesRegex(PublishError, "target_exists"):
                publish_directory_no_replace(staging, target)

            self.assertTrue(staging.is_dir())
            self.assertFalse((target / "new.txt").exists())
            self.assertEqual(
                (target / "sentinel.txt").read_text(encoding="utf-8"), "preserve"
            )

    def test_cross_parent_publish_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            staging = first / ".pia-venv-staging-synthetic"
            staging.mkdir()

            with self.assertRaisesRegex(
                PublishError, "staging_and_target_must_share_parent"
            ):
                publish_directory_no_replace(staging, second / "published")

    def test_two_publishers_racing_same_target_have_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / ".pia-venv-staging-first"
            second = root / ".pia-venv-staging-second"
            target = root / "published"
            first.mkdir()
            second.mkdir()
            (first / "winner.txt").write_text("first", encoding="utf-8")
            (second / "winner.txt").write_text("second", encoding="utf-8")
            barrier = threading.Barrier(2)

            def publish(staging):
                barrier.wait()
                try:
                    publish_directory_no_replace(staging, target)
                    return "published"
                except PublishError as exc:
                    return str(exc)

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(publish, (first, second)))

            self.assertEqual(outcomes.count("published"), 1)
            self.assertEqual(outcomes.count("target_exists"), 1)
            self.assertIn(
                (target / "winner.txt").read_text(encoding="utf-8"),
                {"first", "second"},
            )
            self.assertEqual(sum(path.exists() for path in (first, second)), 1)


if __name__ == "__main__":
    unittest.main()
