from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "generate_prompt.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class PromptGeneratorTests(unittest.TestCase):
    def test_list_modes_do_not_require_subject(self) -> None:
        carriers = run_cli("--list-carriers")
        languages = run_cli("--list-visual-languages")
        self.assertEqual(carriers.returncode, 0, carriers.stderr)
        self.assertEqual(languages.returncode, 0, languages.stderr)
        self.assertIn("article-hero", carriers.stdout)
        self.assertIn("negative-space", languages.stdout)

    def test_invalid_aspect_ratio_is_rejected(self) -> None:
        result = run_cli("hospital AI", "--ratio", "7:banana")
        self.assertEqual(result.returncode, 2)
        self.assertIn("aspect ratio", result.stderr)

    def test_custom_album_ratio_is_preserved(self) -> None:
        result = run_cli(
            "fictional jazz album",
            "--carrier",
            "album-cover",
            "--ratio",
            "16:9",
            "--output-format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertEqual(payload["orientation"], "landscape")
        self.assertTrue(payload["warnings"])

    def test_album_default_is_square(self) -> None:
        result = run_cli(
            "fictional jazz album",
            "--carrier",
            "album-cover",
            "--output-format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["aspect_ratio"], "1:1")
        self.assertEqual(payload["orientation"], "square")

    def test_orientation_conflict_is_rejected(self) -> None:
        result = run_cli("future hospital", "--ratio", "9:16", "--orientation", "landscape")
        self.assertEqual(result.returncode, 2)
        self.assertIn("conflicts", result.stderr)

    def test_text_strategy_conflict_is_rejected(self) -> None:
        result = run_cli(
            "future hospital",
            "--text",
            "未来医院",
            "--text-strategy",
            "no-text",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("conflicts", result.stderr)

    def test_required_and_excluded_overlap_is_rejected(self) -> None:
        result = run_cli(
            "future hospital",
            "--must-include",
            "hospital,data grid",
            "--exclude",
            "hospital",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("both required and excluded", result.stderr)

    def test_post_layout_preserves_copy_as_metadata(self) -> None:
        result = run_cli(
            "future hospital",
            "--text",
            "未来医院",
            "--text-strategy",
            "post-layout",
            "--output-format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["layout_text"], "未来医院")
        self.assertEqual(payload["text_strategy"], "post-layout")
        self.assertIn("无字底图", payload["positive_prompt"])
        self.assertIn("任何可见文字", payload["negative_prompt"])

    def test_identical_input_is_deterministic(self) -> None:
        args = (
            "data governance before AI",
            "--carrier",
            "article-hero",
            "--visual-language",
            "negative-space",
            "--palette",
            "navy, teal, white",
            "--output-format",
            "json",
        )
        first = run_cli(*args)
        second = run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_package_has_no_legacy_imitation_anchors(self) -> None:
        blocked = (
            "mondo",
            "olly moss",
            "tyler stout",
            "saul bass",
            "shepard fairey",
            "batman",
            "pink floyd",
            "joy division",
            "blue note records",
            "obey aesthetic",
            "studio ghibli",
            "pixar",
            "disney",
        )
        sources = [SKILL_ROOT / "SKILL.md"]
        sources.extend((SKILL_ROOT / "references").rglob("*.md"))
        sources.extend((SKILL_ROOT / "scripts").rglob("*.py"))
        combined = "\n".join(path.read_text(encoding="utf-8") for path in sources).casefold()
        for token in blocked:
            self.assertNotIn(token, combined)

    def test_package_has_no_bundled_binary_examples(self) -> None:
        binary_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        binaries = [path for path in SKILL_ROOT.rglob("*") if path.suffix.casefold() in binary_suffixes]
        self.assertEqual(binaries, [])

    def test_referenced_local_files_exist(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        targets = re.findall(r"\]\((references/[^)]+)\)", skill_text)
        self.assertTrue(targets)
        for target in targets:
            self.assertTrue((SKILL_ROOT / target).is_file(), target)


if __name__ == "__main__":
    unittest.main()
