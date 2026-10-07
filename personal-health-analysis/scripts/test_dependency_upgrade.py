import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import runtime_preflight as gate


class DependencyUpgradeTests(unittest.TestCase):
    def verify_live(self, version, python=(3, 13, 12)) -> dict[str, Any]:
        versions = {"pandas": "3.0.6", "garminconnect": version}
        with (
            patch.object(gate.metadata, "version", side_effect=versions.__getitem__),
            patch.object(gate.importlib.util, "find_spec", return_value=object()),
            patch.object(gate.sys, "version_info", python),
        ):
            return gate.verify_runtime("live")

    def test_only_reviewed_sdk_version_is_ready(self):
        result = self.verify_live("0.3.17", python=(3, 12, 0))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["requirements"]["garminconnect"]["expected"], "0.3.17")

    def test_previous_and_unreviewed_future_sdk_versions_fail_closed(self):
        for version in ("0.3.16", "0.3.18"):
            with self.subTest(version=version):
                result = self.verify_live(version)
                self.assertFalse(result["ok"], result)
                self.assertIn(
                    {"package": "garminconnect", "reason": "version_mismatch", "expected": "0.3.17", "actual": version},
                    result["failures"],
                )

    def test_live_python_minimum_matches_sdk_without_raising_local_minimum(self):
        live = self.verify_live("0.3.17", python=(3, 11, 12))
        self.assertIn(
            {"package": "python", "reason": "version_mismatch", "expected": ">=3.12", "actual": "3.11.12"},
            live["failures"],
        )
        with (
            patch.object(gate.metadata, "version", return_value="3.0.6"),
            patch.object(gate.importlib.util, "find_spec", return_value=object()),
            patch.object(gate.sys, "version_info", (3, 11, 12)),
        ):
            self.assertTrue(gate.verify_runtime("local")["ok"])

    def test_full_bundle_installers_reject_python_below_sdk_minimum(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("install.ps1", "install.sh"):
            with self.subTest(installer=name):
                installer = (root / name).read_text(encoding="utf-8")
                self.assertIn("sys.version_info >= (3, 12)", installer)
                self.assertNotIn("sys.version_info >= (3, 11)", installer)


if __name__ == "__main__":
    unittest.main()
