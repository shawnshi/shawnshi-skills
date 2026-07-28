import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parent))
import domain_manager


COMPLETE_DOMAIN = """# Domain: Demo
# Source: https://example.org/primary
# Structural_Primitives: objects, relations, constraints

## Core Objects

- A documented object.

## Core Morphisms

- A documented directional relation.

## Theorems / Patterns

### Verified mechanism

- **Statement**: A bounded mechanism.
- **Preconditions**: The stated conditions hold.
- **Applicable structure**: The source and target share the documented relation.
- **Mapping hint**: Test the relation with a reversible experiment.
- **Counterexample / limit**: The relation fails outside the stated conditions.
- **Source**: https://example.org/primary

## Tags

- demo
"""


class DomainManagerTests(unittest.TestCase):
    def workspace(self, root: Path):
        references = root / "references"
        drafts = references / "drafts"
        verified = references / "verified"
        drafts.mkdir(parents=True)
        verified.mkdir(parents=True)
        allowlist = references / "verified_domains.json"
        allowlist.write_text(
            json.dumps({"schema_version": 1, "domains": []}),
            encoding="utf-8",
        )
        return patch.multiple(
            domain_manager,
            REFERENCES=references,
            DRAFTS=drafts,
            VERIFIED=verified,
            ALLOWLIST=allowlist,
        )

    def test_duplicate_and_placeholder_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            with self.workspace(root):
                target = domain_manager.VERIFIED / "demo.md"
                target.write_text(COMPLETE_DOMAIN, encoding="utf-8")
                digest = domain_manager._sha256(target)
                domain_manager.ALLOWLIST.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "domains": [
                                {
                                    "name": "demo",
                                    "path": "verified/demo.md",
                                    "sha256": digest,
                                    "source": "TBD",
                                },
                                {
                                    "name": "demo",
                                    "path": "verified/demo.md",
                                    "sha256": digest,
                                    "source": "TBD",
                                },
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                result = domain_manager.list_domains()

                self.assertEqual(result["status"], "error")
                joined = "\n".join(result["errors"])
                self.assertIn("source is missing or unresolved", joined)
                self.assertIn("duplicate name", joined)
                self.assertIn("duplicate path", joined)

    def test_promote_previews_then_atomically_activates(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            with self.workspace(root):
                draft = domain_manager.DRAFTS / "demo.md"
                draft.write_text(COMPLETE_DOMAIN, encoding="utf-8")

                preview = domain_manager.promote_domain("demo", apply=False)

                self.assertEqual(preview["status"], "preview")
                self.assertTrue(draft.exists())
                self.assertFalse((domain_manager.VERIFIED / "demo.md").exists())

                applied = domain_manager.promote_domain("demo", apply=True)
                listed = domain_manager.list_domains()

                self.assertEqual(applied["status"], "promoted")
                self.assertFalse(draft.exists())
                self.assertTrue((domain_manager.VERIFIED / "demo.md").exists())
                self.assertEqual(listed["status"], "success")
                self.assertEqual(listed["count"], 1)

    def test_incomplete_draft_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            with self.workspace(root):
                draft = domain_manager.DRAFTS / "demo.md"
                draft.write_text(
                    domain_manager.TEMPLATE.format(
                        display_name="Demo",
                        source="https://example.org/primary",
                        primitives="objects, relations",
                    ),
                    encoding="utf-8",
                )

                result = domain_manager.promote_domain("demo", apply=True)

                self.assertEqual(result["status"], "error")
                self.assertEqual(result["category"], "domain_schema")
                self.assertTrue(draft.exists())
                self.assertFalse((domain_manager.VERIFIED / "demo.md").exists())


if __name__ == "__main__":
    unittest.main()
