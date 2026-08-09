import io
import json
import unittest
from unittest.mock import patch

import runtime_preflight as gate


class RuntimePreflightTests(unittest.TestCase):
    def test_local_mode_accepts_current_interpreter_without_virtual_environment(self):
        with (
            patch.object(gate.metadata, "version", return_value="3.0.3"),
            patch.object(gate.importlib.util, "find_spec", return_value=object()),
        ):
            result = gate.verify_runtime("local")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "RUNTIME_READY")
        self.assertEqual(result["mode"], "local")
        self.assertNotIn("virtual_environment", result)

    def test_missing_or_mismatched_dependency_fails_closed(self):
        cases = (
            (gate.metadata.PackageNotFoundError(), None, "missing"),
            ("2.0.0", object(), "version_mismatch"),
            ("3.0.3", None, "not_importable"),
        )
        for version_result, spec, reason in cases:
            with self.subTest(reason=reason):
                version_side_effect = (
                    version_result
                    if isinstance(version_result, BaseException)
                    else None
                )
                with (
                    patch.object(
                        gate.metadata,
                        "version",
                        return_value=None if version_side_effect else version_result,
                        side_effect=version_side_effect,
                    ),
                    patch.object(gate.importlib.util, "find_spec", return_value=spec),
                ):
                    result = gate.verify_runtime("local")

                self.assertFalse(result["ok"])
                self.assertEqual(result["status"], "RUNTIME_DEPENDENCY_UNAVAILABLE")
                self.assertEqual(result["failures"][0]["reason"], reason)

    def test_live_and_activity_modes_require_only_their_declared_packages(self):
        versions = {
            "pandas": "3.0.3",
            "garminconnect": "0.3.9",
            "fitparse": "1.2.0",
            "gpxpy": "1.6.2",
        }
        with (
            patch.object(gate.metadata, "version", side_effect=versions.__getitem__),
            patch.object(gate.importlib.util, "find_spec", return_value=object()),
        ):
            live = gate.verify_runtime("live")
            activity = gate.verify_runtime("activity")

        self.assertEqual(set(live["requirements"]), {"pandas", "garminconnect"})
        self.assertEqual(set(activity["requirements"]), {"fitparse", "gpxpy"})

    def test_cli_returns_machine_readable_failure(self):
        failure = {
            "ok": False,
            "status": "RUNTIME_DEPENDENCY_UNAVAILABLE",
            "mode": "local",
            "failures": [{"package": "pandas", "reason": "missing"}],
        }
        output = io.StringIO()
        with patch.object(gate, "verify_runtime", return_value=failure), patch(
            "sys.stdout", output
        ):
            rc = gate.main(["--mode", "local"])

        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(output.getvalue()), failure)


if __name__ == "__main__":
    unittest.main()
