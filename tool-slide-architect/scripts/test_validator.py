import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from validator import audit_outline, load_source


FIXTURE = (
    Path(__file__).resolve().parent.parent / "evals" / "valid-outline.md"
).read_text(encoding="utf-8")


class BlueprintValidatorTests(unittest.TestCase):
    def test_literal_mustache_not_owned_by_template_is_allowed(self):
        content = FIXTURE.replace(
            "The fixture contains no unresolved placeholders.",
            "The fixture documents literal {{patient_id}} syntax.",
        )

        report, _ = audit_outline(content)

        self.assertFalse(
            any(item["code"] == "E_UNRESOLVED_PLACEHOLDER" for item in report["errors"])
        )

    def test_known_template_token_is_rejected(self):
        content = FIXTURE.replace(
            "The fixture contains no unresolved placeholders.",
            "The topic is still {{TOPIC}}.",
        )

        report, _ = audit_outline(content)

        self.assertTrue(
            any(item["code"] == "E_UNRESOLVED_PLACEHOLDER" for item in report["errors"])
        )

    def test_directory_requires_canonical_outline_file(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            (root / "chunk_1.md").write_text(FIXTURE, encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                load_source(root)


if __name__ == "__main__":
    unittest.main()
