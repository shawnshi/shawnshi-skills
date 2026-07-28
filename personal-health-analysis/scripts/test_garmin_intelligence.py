import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("garmin_intelligence.py")
SPEC = importlib.util.spec_from_file_location("garmin_intelligence", SCRIPT_PATH)
_STUBS = {
    "garmin_auth": types.SimpleNamespace(get_client=lambda: None),
    "garmin_data": types.SimpleNamespace(fetch_summary=lambda *_args, **_kwargs: {}),
}
_PREVIOUS_MODULES = {name: sys.modules.get(name) for name in _STUBS}
sys.modules.update(_STUBS)
try:
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
finally:
    for name, previous in _PREVIOUS_MODULES.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def sample_summary():
    return {
        "hrv": [
            {"date": "2026-07-25", "last_night_avg": 50},
            {"date": "2026-07-26", "last_night_avg": 52},
            {"date": "2026-07-27", "last_night_avg": 40},
        ],
        "heart_rate": [
            {"date": "2026-07-25", "resting_hr": 55},
            {"date": "2026-07-26", "resting_hr": 56},
            {"date": "2026-07-27", "resting_hr": 62},
        ],
        "sleep": [
            {"date": "2026-07-25", "sleep_time_seconds": 27000, "sleep_score": 80},
            {"date": "2026-07-26", "sleep_time_seconds": 25200, "sleep_score": 75},
            {"date": "2026-07-27", "sleep_time_seconds": 23400, "sleep_score": 60},
        ],
        "body_battery": [{"highest": 45}],
        "stress": [{"avg_stress": 55}],
        "training_status": {},
        "max_metrics": {},
        "body_composition": {},
    }


class SafetyBoundaryTests(unittest.TestCase):
    def setUp(self):
        module._CLINICAL_GUIDELINES = {
            "screening_signal": {"enabled": False},
            "readiness_index": {"enabled": False},
            "training_load_model": {"enabled": False},
        }

    def test_disabled_configuration_never_emits_health_risk_classification(self):
        result = module.analyze_baseline_change(sample_summary())
        self.assertEqual(result["classification"], "not_classified")
        self.assertFalse(result["medical_interpretation"])
        self.assertNotIn("risk_level", result)

    def test_disabled_configuration_never_emits_readiness_score(self):
        result = module.analyze_executive_readiness(sample_summary())
        self.assertEqual(result["status"], "not_scored")
        self.assertIsNone(result["score"])

    def test_audit_has_no_supplement_or_forced_schedule_directive(self):
        result = module.perform_bio_metric_audit(sample_summary())
        rendered = str(result)
        self.assertEqual(result["action_protocol"]["type"], "UNCLASSIFIED")
        for forbidden in ("mg", "茶氨酸", "维生素", "取消会议", "严禁决策"):
            self.assertNotIn(forbidden, rendered)

    def test_missing_local_observations_do_not_become_health_facts(self):
        date = "2026-07-28"
        summary_frame = module.pd.DataFrame(
            [
                {
                    "date": date,
                    "resting_heart_rate": float("nan"),
                    "max_hr": float("nan"),
                    "stress_avg": float("nan"),
                    "body_battery_highest": float("nan"),
                    "body_battery_lowest": float("nan"),
                    "body_battery_charged": float("nan"),
                    "rr_waking_avg": float("nan"),
                    "steps": float("nan"),
                    "high_stress_duration": float("nan"),
                    "medium_stress_duration": float("nan"),
                }
            ]
        )
        sleep_frame = module.pd.DataFrame(
            [
                {
                    "date": date,
                    "sleep_time_seconds": float("nan"),
                    "deep_sleep_seconds": float("nan"),
                    "rem_sleep_seconds": float("nan"),
                    "sleep_score": float("nan"),
                    "avg_spo2": float("nan"),
                    "avg_respiration": float("nan"),
                }
            ]
        )
        hrv_frame = module.pd.DataFrame(
            [{"date": date, "hrv_avg": float("nan"), "status": None}]
        )
        empty_frame = module.pd.DataFrame()

        with (
            patch.object(module, "HAS_SQLITE", True),
            patch.object(module, "sqlite_summary", return_value=summary_frame),
            patch.object(module, "sqlite_sleep", return_value=sleep_frame),
            patch.object(module, "sqlite_hrv", return_value=hrv_frame),
            patch.object(module, "sqlite_activities", return_value=empty_frame),
            patch.object(module, "sqlite_biomechanics", return_value=empty_frame),
            patch.object(module, "get_devices_info", return_value=empty_frame),
            patch.object(
                module, "get_body_composition_detailed", return_value=empty_frame
            ),
            patch.object(
                module,
                "get_max_metrics",
                return_value={"vo2_max": None, "fitness_age": None},
            ),
            patch.object(
                module,
                "get_daily_friction_matrix",
                side_effect=AssertionError("disabled model must not run"),
            ),
        ):
            result = module.fetch_local_summary(1)

        self.assertIsNone(result["heart_rate"][0]["resting_hr"])
        self.assertIsNone(result["heart_rate"][0]["max_hr"])
        self.assertIsNone(result["stress"][0]["avg_stress"])
        self.assertIsNone(result["body_battery"][0]["highest"])
        self.assertIsNone(result["sleep"][0]["sleep_time_seconds"])
        self.assertIsNone(result["sleep"][0]["avg_spo2"])
        self.assertIsNone(result["sleep"][0]["avg_respiration"])
        self.assertIsNone(result["hrv"][0]["last_night_avg"])
        self.assertIsNone(result["hrv"][0]["status"])
        self.assertTrue(result["is_stale"])
        self.assertEqual(len(result["data_gaps"]), 3)

        audit = module.perform_bio_metric_audit(result)
        self.assertIsNone(audit["system_status"]["rhr"]["current"])
        self.assertIsNone(audit["system_status"]["hrv"]["value"])
        self.assertIsNone(audit["recovery_loop"]["body_battery"]["peak"])
        self.assertIsNone(audit["load_friction"]["stress_score"])
        self.assertIsNone(
            audit["load_friction"]["dissipation"]["high_stress_hours"]
        )
        self.assertEqual(
            module.analyze_baseline_change(result)["status"], "insufficient_baseline"
        )
        self.assertEqual(
            module.analyze_executive_readiness(result)["status"], "not_scored"
        )


if __name__ == "__main__":
    unittest.main()
