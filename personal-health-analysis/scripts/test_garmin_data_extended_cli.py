import contextlib
import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from garmin_capabilities import issue_capability, require_capability


SCRIPT_PATH = Path(__file__).with_name("garmin_data_extended.py")


def load_module():
    auth_stub = types.SimpleNamespace(
        get_client=Mock(side_effect=AssertionError("network client must not load"))
    )
    with patch.dict(sys.modules, {"garmin_auth": auth_stub}):
        spec = importlib.util.spec_from_file_location(
            "garmin_data_extended_under_test", SCRIPT_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class GarminDataExtendedCliTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def run_main(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = self.module.main(argv)
        return exit_code, json.loads(stdout.getvalue())

    def test_help_does_not_initialize_network_client(self):
        with (
            patch.object(self.module, "_get_client") as get_client,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as raised:
                self.module.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        get_client.assert_not_called()

    def test_no_metric_is_machine_readable_and_zero_side_effect(self):
        with patch.object(self.module, "_get_client") as get_client:
            exit_code, payload = self.run_main([])
        self.assertEqual(exit_code, self.module.EXIT_USAGE)
        self.assertEqual(payload["status"], "usage_error")
        get_client.assert_not_called()

    def test_every_extended_metric_requires_allow_network(self):
        for metric in self.module.METRIC_CHOICES:
            with self.subTest(metric=metric), patch.object(
                self.module, "_get_client"
            ) as get_client:
                scope = (
                    ["--start", "2026-08-01", "--end", "2026-08-08"]
                    if metric in self.module.RANGE_METRICS
                    else ["--date", "2026-08-08"]
                )
                exit_code, payload = self.run_main([metric, *scope])
                self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
                self.assertEqual(
                    payload["status"], "network_authorization_required"
                )
                get_client.assert_not_called()

    def test_dry_run_is_zero_side_effect(self):
        with patch.object(self.module, "_get_client") as get_client:
            exit_code, payload = self.run_main(
                ["spo2", "--date", "2026-08-08", "--dry-run"]
            )
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["network_accessed"])
        get_client.assert_not_called()

    def test_authorized_request_uses_client_only_after_gate(self):
        client = object()
        with (
            patch.object(self.module, "_get_client", return_value=client) as get_client,
            patch.object(
                self.module,
                "fetch_spo2",
                return_value={"spo2": {"average": 97}, "date": "2026-08-08"},
            ) as fetch,
        ):
            exit_code, payload = self.run_main(
                [
                    "spo2",
                    "--date",
                    "2026-08-08",
                    "--allow-network",
                    "--allow-health-data",
                ]
            )
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertIn("spo2", payload)
        get_client.assert_called_once()
        require_capability(
            get_client.call_args.kwargs["network_capability"],
            scope="network",
            operation="extended_health_data_live",
            request=get_client.call_args.kwargs["request"],
        )
        fetch.assert_called_once_with(client, "2026-08-08")

    def test_direct_client_loader_rejects_bool_and_wrong_operation(self):
        with self.assertRaisesRegex(PermissionError, "network_authorization_required"):
            self.module._get_client(network_capability=True)
        with self.assertRaisesRegex(PermissionError, "network_authorization_required"):
            self.module._get_client(
                network_capability=issue_capability(
                    scope="network", operation="point_query_live"
                )
            )

    def test_date_bound_metrics_forward_the_requested_window(self):
        cases = (
            (
                "fitness_age",
                ["--date", "2026-08-08"],
                "get_fitnessage_data",
                ("2026-08-08",),
            ),
            (
                "endurance_score",
                ["--start", "2026-08-01", "--end", "2026-08-08"],
                "get_endurance_score",
                ("2026-08-01", "2026-08-08"),
            ),
            (
                "hill_score",
                ["--start", "2026-08-01", "--end", "2026-08-08"],
                "get_hill_score",
                ("2026-08-01", "2026-08-08"),
            ),
        )
        for metric, date_args, method_name, expected_args in cases:
            with self.subTest(metric=metric):
                client = Mock()
                getattr(client, method_name).return_value = {"observed": True}
                with patch.object(self.module, "_get_client", return_value=client):
                    exit_code, payload = self.run_main(
                        [metric, *date_args, "--allow-network", "--allow-health-data"]
                    )
                self.assertEqual(exit_code, self.module.EXIT_OK)
                self.assertNotIn("error", payload)
                getattr(client, method_name).assert_called_once_with(*expected_args)


if __name__ == "__main__":
    unittest.main()
