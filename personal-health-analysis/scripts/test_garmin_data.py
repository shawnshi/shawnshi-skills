import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT_PATH = Path(__file__).with_name("garmin_data.py")
SPEC = importlib.util.spec_from_file_location("garmin_data", SCRIPT_PATH)
garmin_auth_stub = types.SimpleNamespace(get_client=lambda: None)
garminconnect_stub = types.SimpleNamespace(Garmin=object)
with patch.dict(
    sys.modules,
    {"garmin_auth": garmin_auth_stub, "garminconnect": garminconnect_stub},
):
    garmin_data = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(garmin_data)


def _component_mocks():
    return {
        "fetch_sleep": Mock(return_value={"sleep": [{"sleep_time_seconds": 28800, "sleep_score": 80}]}),
        "fetch_hrv": Mock(return_value={"hrv": [{"last_night_avg": 40}]}),
        "fetch_body_battery": Mock(return_value={"body_battery": [{"charged": 50}]}),
        "fetch_heart_rate": Mock(return_value={"heart_rate": [{"resting_hr": 55}]}),
        "fetch_activities": Mock(return_value={"activities": [{"calories": 100}]}),
        "fetch_stress": Mock(return_value={"stress": []}),
        "fetch_training_load_series": Mock(return_value={"training_load": []}),
        "fetch_training_status": Mock(return_value={"status": "ok"}),
        "fetch_max_metrics": Mock(return_value={"fitness_age": 40}),
        "fetch_hydration": Mock(return_value={"valueInML": 1000}),
        "fetch_body_composition": Mock(return_value={"weight": 70}),
        "fetch_alarms": Mock(return_value=[]),
    }


class GarminSummaryTests(unittest.TestCase):
    def test_summary_uses_single_bounded_concurrency_layer(self):
        mocks = _component_mocks()
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=7)

        self.assertNotIn("error", result)
        self.assertEqual(result["summary"]["total_activities"], 1)
        self.assertEqual(result["summary"]["total_calories"], 100)
        for name in (
            "fetch_sleep",
            "fetch_hrv",
            "fetch_body_battery",
            "fetch_heart_rate",
            "fetch_stress",
            "fetch_training_load_series",
        ):
            self.assertEqual(mocks[name].call_args.kwargs["max_workers"], 1)
        self.assertEqual(garmin_data.SUMMARY_MAX_WORKERS, 5)

    def test_component_failure_keeps_partial_summary(self):
        mocks = _component_mocks()
        mocks["fetch_hrv"].side_effect = RuntimeError("private upstream detail")
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=7)

        self.assertNotIn("error", result)
        self.assertEqual(result["hrv"], [])
        self.assertEqual(result["sleep"][0]["sleep_score"], 80)

    @patch.object(garmin_data.concurrent.futures, "ThreadPoolExecutor")
    def test_inline_daily_mapping_does_not_start_nested_pool(self, executor_mock):
        result = garmin_data._map_with_workers(lambda value: value * 2, [1, 2], 1)
        self.assertEqual(result, [2, 4])
        executor_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
