import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from report_output import build_report_paths, get_report_dir


class CollaborationReportOutputTests(unittest.TestCase):
    def test_default_archive_is_workspace_output(self):
        workspace = Path(r"C:\workspace")
        with patch.dict(os.environ, {}, clear=True):
            output_dir = get_report_dir(workspace=workspace)

        self.assertEqual(
            output_dir,
            workspace / "output" / "mentat-collaboration-audit",
        )

    def test_environment_override_requires_explicit_opt_in(self):
        with patch.dict(
            os.environ,
            {
                "MENTAT_AUDIT_REPORT_DIR": r"D:\private\collaboration-reports",
                "PMI_REPORTS_DIR": r"D:\legacy-personal-insights",
            },
            clear=True,
        ):
            default_dir = get_report_dir(workspace=Path(r"C:\workspace"))
            configured_dir = get_report_dir(allow_environment=True)

        self.assertEqual(
            default_dir,
            Path(r"C:\workspace") / "output" / "mentat-collaboration-audit",
        )
        self.assertEqual(
            configured_dir,
            Path(r"D:\private\collaboration-reports"),
        )

    def test_markdown_and_html_share_one_stem(self):
        now = datetime(2026, 7, 27, 10, 15, 30)
        paths = build_report_paths(
            period="7d",
            now=now,
            output_dir=Path(r"C:\archive"),
        )

        self.assertEqual(paths["markdown"].stem, paths["html"].stem)
        self.assertEqual(
            paths["markdown"].name,
            "collaboration_audit_7d_20260727_101530.md",
        )
        self.assertEqual(
            paths["html"].name,
            "collaboration_audit_7d_20260727_101530.html",
        )

    def test_create_dir_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output_dir = Path(temp_root) / "nested" / "personal-insights"
            self.assertFalse(output_dir.exists())

            build_report_paths(
                period="30d",
                output_dir=output_dir,
                create_dir=False,
            )
            self.assertFalse(output_dir.exists())

            build_report_paths(
                period="30d",
                output_dir=output_dir,
                create_dir=True,
            )
            self.assertTrue(output_dir.is_dir())

    def test_period_rejects_path_characters(self):
        with self.assertRaises(ValueError):
            build_report_paths(period=r"..\outside")


if __name__ == "__main__":
    unittest.main()
