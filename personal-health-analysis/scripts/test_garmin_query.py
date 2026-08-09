import importlib.util
import io
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from garmin_capabilities import require_capability


SCRIPT_PATH = Path(__file__).with_name("garmin_query.py")
SPEC = importlib.util.spec_from_file_location("garmin_query", SCRIPT_PATH)
_PREVIOUS = sys.modules.get("garmin_auth")
sys.modules["garmin_auth"] = types.SimpleNamespace(get_client=lambda: None)
try:
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
finally:
    if _PREVIOUS is None:
        sys.modules.pop("garmin_auth", None)
    else:
        sys.modules["garmin_auth"] = _PREVIOUS


class PointQuerySafetyTests(unittest.TestCase):
    def test_cli_requires_network_permission_before_client_initialization(self):
        with (
            patch.object(
                module,
                "get_client",
                side_effect=AssertionError("permission gate must run first"),
            ) as get_client,
            patch.object(
                sys,
                "argv",
                [
                    "garmin_query.py",
                    "stress",
                    "15:00",
                    "--date",
                    "2026-08-07",
                    "--timezone",
                    "UTC",
                    "--max-tolerance-seconds",
                    "300",
                ],
            ),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            rc = module.main()

        self.assertEqual(rc, 2)
        get_client.assert_not_called()
        self.assertEqual(
            __import__("json").loads(stdout.getvalue())["status"],
            "NETWORK_ACCESS_NOT_AUTHORIZED",
        )

    def test_far_away_point_is_not_returned(self):
        target = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)
        midnight = int(datetime(2026, 8, 7, tzinfo=timezone.utc).timestamp())
        result = module.find_closest_datapoint(
            target,
            [{"startTimeInSeconds": midnight, "value": 42}],
            max_tolerance_seconds=300,
        )
        self.assertIsNone(result)

    def test_authorized_cli_uses_point_query_capability(self):
        client = object()
        with (
            patch.object(module, "get_client", return_value=client) as get_client,
            patch.object(
                module,
                "query_stress_at_time",
                return_value={"status": "no_observation"},
            ),
            patch.object(
                sys,
                "argv",
                [
                    "garmin_query.py",
                    "stress",
                    "15:00",
                    "--date",
                    "2026-08-07",
                    "--timezone",
                    "UTC",
                    "--max-tolerance-seconds",
                    "300",
                    "--allow-network",
                    "--allow-health-data",
                ],
            ),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            rc = module.main()

        self.assertEqual(rc, 0)
        get_client.assert_called_once()
        self.assertEqual(get_client.call_args.kwargs["operation"], "point_query_live")
        require_capability(
            get_client.call_args.kwargs["network_capability"],
            scope="network",
            operation="point_query_live",
            request=get_client.call_args.kwargs["request"],
        )

    def test_query_returns_observed_time_and_delta(self):
        observed = int(datetime(2026, 8, 7, 15, 2, tzinfo=timezone.utc).timestamp())
        client = types.SimpleNamespace(
            get_all_day_stress=lambda _date: {
                "stressValuesArray": [[observed * 1000, 42]]
            }
        )
        result = module.query_stress_at_time(
            client,
            "15:00",
            "2026-08-07",
            timezone_name="UTC",
            max_tolerance_seconds=300,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["delta_seconds"], 120)
        self.assertEqual(result["timezone"], "UTC")
        self.assertTrue(result["observed_at"].endswith("+00:00"))

    def test_query_returns_no_observation_when_tolerance_is_exceeded(self):
        observed = int(datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc).timestamp())
        client = types.SimpleNamespace(
            get_all_day_stress=lambda _date: {
                "stressValuesArray": [[observed * 1000, 42]]
            }
        )
        result = module.query_stress_at_time(
            client,
            "15:00",
            "2026-08-07",
            timezone_name="UTC",
            max_tolerance_seconds=300,
        )
        self.assertEqual(result["status"], "no_observation")
        self.assertNotIn("stress_level", result)

    def test_dst_ambiguous_or_nonexistent_local_time_is_rejected(self):
        for date_value, time_value, expected in (
            ("2026-03-08", "02:30", "nonexistent_local_time"),
            ("2026-11-01", "01:30", "ambiguous_local_time"),
        ):
            with self.subTest(date=date_value), self.assertRaisesRegex(ValueError, expected):
                module.parse_time(time_value, date_value, "America/New_York")

    def test_tolerance_cannot_expand_beyond_one_hour(self):
        target = datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "max_tolerance_seconds_out_of_range"):
            module.find_closest_datapoint(target, [], max_tolerance_seconds=3601)


if __name__ == "__main__":
    unittest.main()
