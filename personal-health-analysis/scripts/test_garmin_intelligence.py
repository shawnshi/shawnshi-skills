import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
import warnings
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("garmin_intelligence.py")
SPEC = importlib.util.spec_from_file_location("garmin_intelligence", SCRIPT_PATH)
_STUBS = {
    "garmin_auth": types.SimpleNamespace(get_client=lambda: None),
    "garmin_data": types.SimpleNamespace(
        fetch_summary=lambda *_args, **_kwargs: {},
        get_date_range=lambda _days=None, start=None, end=None: (
            start or "2026-08-09",
            end or "2026-08-09",
        ),
    ),
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


class _VerifiedWindowStub:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def public_summary(self):
        return {"status": "verified_unchanged", "databases": []}


class SafetyBoundaryTests(unittest.TestCase):
    def test_period_parser_rejects_invalid_zero_and_negative_scopes(self):
        for value in ("0d", "-1d", "7D", "garbage", ""):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "INVALID_PERIOD_SCOPE"
            ):
                module.parse_period(value, 7)
        for value in (0, -1, True, None):
            with self.subTest(days=value), self.assertRaisesRegex(
                ValueError, "INVALID_PERIOD_SCOPE"
            ):
                module.parse_period(None, value)

    def test_ytd_period_is_inclusive_of_january_first(self):
        today = date.today()
        self.assertEqual(
            module.parse_period("YTD", 7),
            (today - date(today.year, 1, 1)).days + 1,
        )

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

    def test_readiness_never_combines_shared_upstream_metrics(self):
        aligned = {
            "sleep": [{"date": "2026-08-09", "sleep_score": 90}],
            "body_battery": [{"date": "2026-08-09", "highest": 80}],
            "stress": [{"date": "2026-08-09", "avg_stress": 20}],
            "hrv": [{"date": "2026-08-09", "status": "BALANCED"}],
        }
        with patch.object(
            module,
            "usable_method_config",
            side_effect=AssertionError("readiness composite must stay disabled"),
        ):
            result = module.analyze_executive_readiness(aligned)

        self.assertEqual(result["status"], "not_scored")
        self.assertIsNone(result["score"])
        self.assertEqual(
            result["configuration_status"], "composite_disabled_shared_inputs"
        )
        self.assertFalse(result["metric_lineage"]["independent_inputs"])

    def test_readiness_method_config_is_hard_disabled(self):
        module._CLINICAL_GUIDELINES = {
            "readiness_index": {
                "enabled": True,
                "weights": {
                    "sleep_score": 0.4,
                    "body_battery_peak": 0.3,
                    "stress_recovery": 0.3,
                },
                "provenance": {
                    "source_type": "peer_reviewed_method",
                    "source": "https://example.test/method",
                    "published_at": "2026-01-01",
                    "retrieved_at": "2026-01-02",
                    "region": "global",
                    "population": "adults",
                    "intended_use": "descriptive_experimental_index",
                },
            }
        }

        self.assertIsNone(
            module.usable_method_config(
                "readiness_index",
                [
                    "weights.sleep_score",
                    "weights.body_battery_peak",
                    "weights.stress_recovery",
                ],
            )
        )

    def test_environment_variable_does_not_implicitly_write_state(self):
        with tempfile.TemporaryDirectory() as temp_root:
            implicit_dir = Path(temp_root) / "implicit-state"
            with (
                patch.dict(os.environ, {"GARMIN_STATE_DIR": str(implicit_dir)}),
                patch.object(module, "_load_summary", return_value=sample_summary()),
                patch.object(
                    sys,
                    "argv",
                    ["garmin_intelligence.py", "audit", "--allow-health-data"],
                ),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertFalse(implicit_dir.exists())

    def test_local_summary_requires_explicit_health_data_permission(self):
        with patch.object(
            module,
            "fetch_local_summary",
            side_effect=AssertionError("permission gate must run before local read"),
        ) as fetch_local:
            with self.assertRaisesRegex(
                PermissionError, "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"
            ):
                module._load_summary(7, "local", allow_health_data=False)

        fetch_local.assert_not_called()

    def test_direct_state_write_requires_explicit_capability(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "state" / "state.json"
            result = {
                "analysis_type": "bio_metric_audit",
                "status": "unclassified",
            }

            with self.assertRaisesRegex(PermissionError, "allow_state_write=True"):
                module._write_state_output(result, output)

            self.assertFalse(output.parent.exists())
            written = module._write_state_output(
                result, output, allow_state_write=True
            )
            self.assertEqual(written, output.resolve())
            self.assertTrue(output.exists())

    def test_live_summary_forwards_explicit_network_capability(self):
        from garmin_capabilities import require_capability

        client = object()
        with (
            patch.object(module, "get_client", return_value=client) as get_client,
            patch.object(module, "fetch_summary", return_value={"source": "live"}) as fetch,
        ):
            with self.assertRaisesRegex(PermissionError, "NETWORK_ACCESS_NOT_AUTHORIZED"):
                module._load_summary(1, "live", allow_network=False)
            get_client.assert_not_called()

            result = module._load_summary(
                1,
                "live",
                allow_network=True,
                allow_health_data=True,
                analysis="audit",
            )

        self.assertEqual(result, {"source": "live"})
        get_client.assert_called_once()
        call_kwargs = get_client.call_args.kwargs
        self.assertEqual(call_kwargs["operation"], module.LIVE_SUMMARY_OPERATION)
        require_capability(
            call_kwargs["network_capability"],
            scope="network",
            operation=module.LIVE_SUMMARY_OPERATION,
            request=call_kwargs["request"],
        )
        request = call_kwargs["request"]
        self.assertEqual(
            request["components"], list(module.LIVE_ANALYSIS_COMPONENTS["audit"])
        )
        self.assertEqual(set(request), {"analysis", "source", "start", "end", "components"})
        fetch.assert_called_once_with(
            client,
            start=request["start"],
            end=request["end"],
            components=module.LIVE_ANALYSIS_COMPONENTS["audit"],
        )

    def test_each_supported_live_analysis_uses_only_its_declared_components(self):
        for analysis, components in module.LIVE_ANALYSIS_COMPONENTS.items():
            with (
                self.subTest(analysis=analysis),
                patch.object(module, "get_client", return_value=object()) as get_client,
                patch.object(
                    module, "fetch_summary", return_value={"source": "live"}
                ) as fetch,
            ):
                module._load_summary(
                    1,
                    "live",
                    allow_network=True,
                    allow_health_data=True,
                    analysis=analysis,
                )
                request = get_client.call_args.kwargs["request"]
                self.assertEqual(request["components"], list(components))
                fetch.assert_called_once_with(
                    get_client.return_value,
                    start=request["start"],
                    end=request["end"],
                    components=components,
                )

    def test_unsupported_live_analyses_stop_before_client_initialization(self):
        for analysis in module.LIVE_UNSUPPORTED_ANALYSES:
            with self.subTest(analysis=analysis), patch.object(
                module, "get_client"
            ) as get_client:
                with self.assertRaisesRegex(
                    RuntimeError, "LIVE_ANALYSIS_NOT_SUPPORTED"
                ):
                    module._load_summary(
                        1,
                        "live",
                        allow_network=True,
                        allow_health_data=True,
                        analysis=analysis,
                    )
                get_client.assert_not_called()

    def test_explicit_state_output_refuses_overwrite_unless_authorized(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "state.json"
            output.write_text("preserve", encoding="utf-8")
            base_argv = [
                "garmin_intelligence.py",
                "audit",
                "--allow-health-data",
                "--state-output",
                str(output),
            ]
            with (
                patch.object(module, "_load_summary", return_value=sample_summary()),
                patch.object(sys, "argv", base_argv),
                patch("sys.stdout", new_callable=io.StringIO),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                refused_rc = module.main()
            self.assertEqual(refused_rc, 3)
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve")

            with (
                patch.object(module, "_load_summary", return_value=sample_summary()),
                patch.object(sys, "argv", [*base_argv, "--overwrite-state"]),
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                overwrite_rc = module.main()
            self.assertEqual(overwrite_rc, 0)
            stored = __import__("json").loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stored["analysis_type"], "bio_metric_audit")
            self.assertFalse(stored["medical_interpretation"])

    def test_zero_variance_baseline_is_unclassifiable_not_zero_z_score(self):
        start = date(2026, 7, 1)
        hrv = []
        heart_rate = []
        sleep = []
        for offset in range(module.MIN_PAIRED_BASELINE_DAYS):
            day = (start + timedelta(days=offset)).isoformat()
            hrv.append({"date": day, "last_night_avg": 50})
            heart_rate.append({"date": day, "resting_hr": 55})
            sleep.append({"date": day, "avg_respiration": 14})
        current_day = (start + timedelta(days=module.MIN_PAIRED_BASELINE_DAYS)).isoformat()
        hrv.append({"date": current_day, "last_night_avg": 20})
        heart_rate.append({"date": current_day, "resting_hr": 80})
        sleep.append({"date": current_day, "avg_respiration": 20})

        result = module.analyze_baseline_change(
            {
                "hrv": hrv,
                "heart_rate": heart_rate,
                "sleep": sleep,
                "measurement_epoch_evidence": {
                    "analysis_algorithm_epoch": module.BASELINE_ALGORITHM_EPOCH,
                    "manufacturer_algorithm_epoch": "synthetic-manufacturer-v1",
                    "firmware_history": [
                        {
                            "timestamp": "2026-06-01 00:00:00",
                            "serial_number": "synthetic",
                            "software_version": "1.0",
                        }
                    ],
                },
            }
        )

        self.assertEqual(result["status"], "unclassifiable")
        self.assertEqual(result["classification"], "unclassifiable_zero_variance")
        self.assertIsNone(result["metrics"]["rhr_z_score"])
        self.assertIsNone(result["metrics"]["hrv_z_score"])
        self.assertEqual(result["metrics"]["baseline_start_date"], start.isoformat())
        self.assertEqual(
            result["metrics"]["baseline_end_date"],
            (start + timedelta(days=module.MIN_PAIRED_BASELINE_DAYS - 1)).isoformat(),
        )
        self.assertEqual(
            result["metrics"]["required_paired_baseline_days"],
            module.MIN_PAIRED_BASELINE_DAYS,
        )
        self.assertNotIn("+0.0 个标准差", " ".join(result["observations"]))

    def test_current_metrics_must_share_one_date(self):
        start = date(2026, 7, 1)
        hrv = []
        heart_rate = []
        for offset in range(module.MIN_PAIRED_BASELINE_DAYS + 1):
            day = (start + timedelta(days=offset)).isoformat()
            hrv.append({"date": day, "last_night_avg": 50 + offset})
            heart_rate.append({"date": day, "resting_hr": 55 + offset})
        heart_rate[-1]["date"] = (start + timedelta(days=99)).isoformat()

        result = module.analyze_baseline_change(
            {"hrv": hrv, "heart_rate": heart_rate, "sleep": []}
        )

        self.assertEqual(result["date"], hrv[-2]["date"])
        self.assertEqual(result["paired_observation_date"], hrv[-2]["date"])

    def test_method_configuration_requires_semantic_provenance_and_safe_values(self):
        invalid_provenance = {field: "x" for field in module.REQUIRED_PROVENANCE_FIELDS}
        module._CLINICAL_GUIDELINES = {
            "screening_signal": {
                "enabled": True,
                "baseline_min_days": 2,
                "thresholds": {
                    "rhr_z_score_min": 1,
                    "hrv_z_score_max": -1,
                    "respiration_delta_min": 1,
                },
                "provenance": invalid_provenance,
            }
        }
        self.assertIsNone(
            module.usable_method_config(
                "screening_signal",
                [
                    "baseline_min_days",
                    "thresholds.rhr_z_score_min",
                    "thresholds.hrv_z_score_max",
                    "thresholds.respiration_delta_min",
                ],
            )
        )

        valid_provenance = {
            "source_type": "method_assumption",
            "source": "method://unit-test/baseline-v1",
            "published_at": "2026-07-01",
            "retrieved_at": "2026-07-02",
            "region": "test",
            "population": "synthetic",
            "intended_use": "non_diagnostic_screening",
        }
        module._CLINICAL_GUIDELINES["screening_signal"].update(
            {
                "baseline_min_days": module.MIN_PAIRED_BASELINE_DAYS,
                "provenance": valid_provenance,
            }
        )
        self.assertIsNotNone(
            module.usable_method_config(
                "screening_signal",
                [
                    "baseline_min_days",
                    "thresholds.rhr_z_score_min",
                    "thresholds.hrv_z_score_max",
                    "thresholds.respiration_delta_min",
                ],
            )
        )

    def test_audit_has_no_supplement_or_forced_schedule_directive(self):
        result = module.perform_bio_metric_audit(sample_summary())
        rendered = str(result)
        self.assertEqual(result["action_protocol"]["type"], "UNCLASSIFIED")
        for forbidden in ("mg", "茶氨酸", "维生素", "取消会议", "严禁决策"):
            self.assertNotIn(forbidden, rendered)

    def test_insight_has_no_training_or_schedule_advice(self):
        rendered = __import__("json").dumps(
            module.generate_chinese_insight(sample_summary()), ensure_ascii=False
        )
        for forbidden in (
            "降低活动强度",
            "安排休息",
            "停止训练",
            "取消会议",
            "调整日程",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_local_analysis_scope_is_forwarded_without_unrequested_components(self):
        for analysis, components in module.LOCAL_ANALYSIS_COMPONENTS.items():
            with (
                self.subTest(analysis=analysis),
                patch.object(module, "HAS_SQLITE", True),
                patch.object(module, "fetch_local_summary", return_value={}) as fetch,
            ):
                result = module._load_summary(
                    7,
                    "local",
                    allow_health_data=True,
                    analysis=analysis,
                )

                self.assertEqual(result, {})
                fetch.assert_called_once_with(
                    7,
                    components=components,
                    metadata_components=module.LOCAL_ANALYSIS_METADATA.get(
                        analysis, ()
                    ),
                )

    def test_scoped_verified_window_uses_only_databases_required_by_components(self):
        explicit = Path("synthetic-explicit.db")
        with (
            patch.object(module, "HAS_SQLITE", True),
            patch.object(
                module,
                "verified_database_read_window",
                return_value=_VerifiedWindowStub(),
            ) as verified,
            patch.object(module, "_fetch_local_summary_unverified", return_value={}),
        ):
            module.fetch_local_summary(1, components=("sleep",))
            self.assertEqual(verified.call_args.args[0], [module.GARMIN_DB])

            module.fetch_local_summary(1, components=("training_load_series",))
            self.assertEqual(
                verified.call_args.args[0], [module.GARMIN_DB, module.ACTIVITIES_DB]
            )

            module.fetch_local_summary(
                1,
                database_paths=[explicit],
                components=("training_load_series",),
            )
            self.assertEqual(verified.call_args.args[0], [explicit])

    def test_unknown_measurement_epoch_never_emits_z_score_or_config_classification(self):
        start = date(2026, 7, 1)
        hrv = []
        heart_rate = []
        for offset in range(module.MIN_PAIRED_BASELINE_DAYS + 1):
            day = (start + timedelta(days=offset)).isoformat()
            hrv.append({"date": day, "last_night_avg": 40 + offset})
            heart_rate.append({"date": day, "resting_hr": 50 + offset})

        with patch.object(
            module,
            "usable_method_config",
            side_effect=AssertionError("unknown epoch must stop before classification"),
        ):
            result = module.analyze_baseline_change(
                {"hrv": hrv, "heart_rate": heart_rate, "sleep": []}
            )

        self.assertEqual(result["status"], "epoch_unknown")
        self.assertEqual(result["classification"], "epoch_unknown_unclassified")
        self.assertIsNone(result["metrics"]["rhr_z_score"])
        self.assertIsNone(result["metrics"]["hrv_z_score"])
        self.assertIsNone(result["metrics"]["baseline_rhr"])
        self.assertIsNone(result["metrics"]["baseline_hrv"])
        self.assertEqual(
            result["metrics"]["rhr_absolute_change_from_historical_observed_mean"],
            11.0,
        )

    def test_unknown_manufacturer_algorithm_epoch_never_becomes_comparable(self):
        start = date(2026, 7, 1)
        dates = [
            (start + timedelta(days=offset)).isoformat()
            for offset in range(module.MIN_PAIRED_BASELINE_DAYS + 1)
        ]
        result = module.analyze_baseline_change(
            {
                "hrv": [
                    {"date": day, "last_night_avg": 40 + index}
                    for index, day in enumerate(dates)
                ],
                "heart_rate": [
                    {"date": day, "resting_hr": 50 + index}
                    for index, day in enumerate(dates)
                ],
                "sleep": [],
                "measurement_epoch_evidence": {
                    "analysis_algorithm_epoch": module.BASELINE_ALGORITHM_EPOCH,
                    "manufacturer_algorithm_epoch": "not_available_in_local_schema",
                    "firmware_history": [
                        {
                            "timestamp": "2026-06-01T00:00:00+08:00",
                            "serial_number": "synthetic",
                            "software_version": "1.0",
                        }
                    ],
                },
            }
        )

        self.assertEqual(result["status"], "epoch_unknown")
        self.assertEqual(
            result["epoch_comparability"]["status"],
            "manufacturer_algorithm_epoch_unknown",
        )
        self.assertIsNone(result["metrics"]["baseline_rhr"])
        self.assertIsNone(result["metrics"]["baseline_hrv"])

    def test_conflicting_same_day_values_fail_closed_but_identical_repeats_are_idempotent(self):
        start = date(2026, 7, 1)
        hrv = []
        heart_rate = []
        for offset in range(module.MIN_PAIRED_BASELINE_DAYS + 1):
            day = (start + timedelta(days=offset)).isoformat()
            hrv.append({"date": day, "last_night_avg": 40 + offset})
            heart_rate.append({"date": day, "resting_hr": 50 + offset})
        epoch = {
            "analysis_algorithm_epoch": module.BASELINE_ALGORITHM_EPOCH,
            "manufacturer_algorithm_epoch": "not_available_in_local_schema",
            "firmware_history": [
                {
                    "timestamp": "2026-06-01 00:00:00",
                    "serial_number": "synthetic",
                    "software_version": "1.0",
                }
            ],
        }
        base = {
            "hrv": hrv,
            "heart_rate": heart_rate,
            "sleep": [],
            "measurement_epoch_evidence": epoch,
        }
        expected = module.analyze_baseline_change(base)
        identical = {
            **base,
            "hrv": [*hrv, dict(hrv[5])],
        }
        conflicted = {
            **base,
            "heart_rate": [
                *heart_rate,
                {"date": heart_rate[5]["date"], "resting_hr": 999},
            ],
        }

        self.assertEqual(module.analyze_baseline_change(identical), expected)
        conflict_result = module.analyze_baseline_change(conflicted)
        self.assertEqual(conflict_result["status"], "duplicate_conflict")
        self.assertEqual(conflict_result["classification"], "not_classified")
        self.assertEqual(
            conflict_result["duplicate_conflicts"]["resting_heart_rate"],
            [heart_rate[5]["date"]],
        )
        self.assertIsNone(conflict_result["metrics"]["rhr_z_score"])

    def test_audit_separates_observed_history_from_a_qualified_baseline(self):
        audit = module.perform_bio_metric_audit(sample_summary())
        rhr = audit["system_status"]["rhr"]

        self.assertIsNone(rhr["baseline"])
        self.assertEqual(rhr["baseline_status"], "insufficient_baseline")
        self.assertEqual(rhr["historical_observed_median"], 55.5)
        self.assertIsNone(rhr["delta"])

    def test_environmental_context_marks_temperature_as_unsupported_when_absent(self):
        unsupported = module.analyze_env_stress(
            {"activities": [{"date": "2026-08-01", "duration": 60}]}
        )
        observed = module.analyze_env_stress(
            {"activities": [{"date": "2026-08-01", "temperature": 24.5}]}
        )

        self.assertEqual(unsupported["status"], "unsupported_by_current_source")
        self.assertIsNone(unsupported["average_recorded_temperature_c"])
        self.assertEqual(observed["status"], "observed")
        self.assertEqual(observed["average_recorded_temperature_c"], 24.5)

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
            patch.object(
                module,
                "_verified_local_read_window",
                return_value=_VerifiedWindowStub(),
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
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["component_status"]["heart_rate"]["status"], "no_data")
        self.assertEqual(result["component_status"]["sleep"]["status"], "no_data")
        self.assertEqual(result["coverage"]["requested_days"], 1)

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

    def test_explicit_local_components_do_not_read_unrequested_health_sources(self):
        sleep = module.pd.DataFrame(
            [
                {
                    "date": date.today().isoformat(),
                    "sleep_time_seconds": 0,
                    "sleep_score": 0,
                }
            ]
        )
        empty = module.pd.DataFrame()
        with __import__("contextlib").ExitStack() as stack:
            stack.enter_context(patch.object(module, "HAS_SQLITE", True))
            stack.enter_context(patch.object(module, "sqlite_sleep", return_value=sleep))
            for name in (
                "sqlite_summary",
                "sqlite_hrv",
                "sqlite_activities",
                "sqlite_biomechanics",
                "get_body_composition_detailed",
                "get_daily_friction_matrix",
                "get_max_metrics",
                "usable_method_config",
            ):
                stack.enter_context(
                    patch.object(
                        module,
                        name,
                        side_effect=AssertionError(
                            f"unrequested extractor called: {name}"
                        ),
                    )
                )
            stack.enter_context(
                patch.object(module, "get_devices_info", return_value=empty)
            )
            stack.enter_context(
                patch.object(module, "get_device_firmware_history", return_value=empty)
            )

            result = module._fetch_local_summary_unverified(
                1, components=("sleep",)
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["sleep"][0]["sleep_time_seconds"], 0)
        self.assertEqual(result["sleep"][0]["sleep_score"], 0)
        for key in (
            "heart_rate",
            "hrv",
            "stress",
            "body_battery",
            "activities",
            "training_load_series",
        ):
            self.assertEqual(result[key], [])
        self.assertEqual(result["component_status"]["sleep"]["status"], "complete")
        self.assertEqual(
            result["component_status"]["heart_rate"]["status"], "not_requested"
        )
        self.assertEqual(result["max_metrics"], {})
        self.assertEqual(result["body_composition_detailed"], [])

    def test_scoped_training_load_never_expands_the_requested_read_window(self):
        activities = module.pd.DataFrame(
            [
                {
                    "date": date.today().isoformat(),
                    "activity_id": "synthetic",
                    "training_load": 10,
                    "duration": "00:30:00",
                }
            ]
        )
        empty = module.pd.DataFrame()
        config = {
            "acute_span_days": 7,
            "chronic_span_days": 42,
            "daily_load_derivation": {"input_field": "training_load", "scale": 1},
            "provenance": {"source_type": "method_assumption"},
        }
        with (
            patch.object(module, "HAS_SQLITE", True),
            patch.object(module, "sqlite_activities", return_value=activities),
            patch.object(module, "usable_method_config", return_value=config),
            patch.object(
                module, "get_daily_friction_matrix", return_value=empty
            ) as get_matrix,
            patch.object(module, "get_devices_info", return_value=empty),
            patch.object(module, "get_device_firmware_history", return_value=empty),
        ):
            result = module._fetch_local_summary_unverified(
                7, components=("training_load_series",)
            )

        self.assertEqual(get_matrix.call_args.args[0], 7)
        self.assertEqual(result["activities"], [])
        self.assertEqual(
            result["training_load_series"],
            [{"date": date.today().isoformat(), "acute_load": 10.0}],
        )
        load_coverage = result["component_status"]["training_load_series"]
        self.assertEqual(load_coverage["status"], "observed")
        self.assertEqual(load_coverage["coverage_semantics"], "event_stream")
        self.assertEqual(load_coverage["zero_semantics"], "unknown")

    def test_sleep_midpoint_variability_has_accurate_name_and_deprecated_alias(self):
        sleep = [
            {
                "sleep_start": "2026-07-01T22:00:00+00:00",
                "sleep_end": "2026-07-02T06:00:00+00:00",
            },
            {
                "sleep_start": "2026-07-02T23:00:00+00:00",
                "sleep_end": "2026-07-03T07:00:00+00:00",
            },
            {
                "sleep_start": "2026-07-03T21:00:00+00:00",
                "sleep_end": "2026-07-04T05:00:00+00:00",
            },
        ]

        value = module.sleep_midpoint_variability_hours(sleep)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            alias_value = module.calculate_social_jetlag(sleep)

        self.assertEqual(value, 1.0)
        self.assertEqual(alias_value, value)
        self.assertTrue(any(item.category is DeprecationWarning for item in caught))
        self.assertNotIn("social_jetlag", module.sleep_midpoint_variability_hours.__doc__)

    def test_local_read_window_discloses_only_database_names_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as temp_root:
            garmin_db = Path(temp_root) / "garmin.db"
            activities_db = Path(temp_root) / "garmin_activities.db"
            for database in (garmin_db, activities_db):
                connection = __import__("sqlite3").connect(database)
                connection.execute("CREATE TABLE sample (value INTEGER)")
                connection.execute("INSERT INTO sample VALUES (1)")
                connection.commit()
                connection.close()

            with self._patched_local_extractors():
                result = module.fetch_local_summary(
                    1, database_paths=[garmin_db, activities_db]
                )

        integrity = result["data_integrity"]
        epoch_evidence = result["measurement_epoch_evidence"]
        self.assertEqual(integrity["status"], "verified_unchanged")
        self.assertEqual(
            [item["database"] for item in integrity["databases"]],
            ["garmin.db", "garmin_activities.db"],
        )
        rendered = __import__("json").dumps(integrity, ensure_ascii=False)
        self.assertNotIn(temp_root, rendered)
        for item in integrity["databases"]:
            self.assertEqual(len(item["sha256"]), 64)
            self.assertEqual(len(item["schema_sha256"]), 64)
            self.assertGreater(item["size_bytes"], 0)
            self.assertIn("mtime_ns", item)
        self.assertEqual(
            epoch_evidence["analysis_algorithm_epoch"],
            module.BASELINE_ALGORITHM_EPOCH,
        )
        self.assertEqual(
            epoch_evidence["manufacturer_algorithm_epoch"],
            "not_available_in_local_schema",
        )

    def test_local_read_window_fails_closed_if_database_changes(self):
        with tempfile.TemporaryDirectory() as temp_root:
            garmin_db = Path(temp_root) / "garmin.db"
            activities_db = Path(temp_root) / "garmin_activities.db"
            for database in (garmin_db, activities_db):
                connection = __import__("sqlite3").connect(database)
                connection.execute("CREATE TABLE sample (value INTEGER)")
                connection.execute("INSERT INTO sample VALUES (1)")
                connection.commit()
                connection.close()

            def mutate_database(_days):
                connection = __import__("sqlite3").connect(garmin_db)
                connection.execute("INSERT INTO sample VALUES (2)")
                connection.commit()
                connection.close()
                return module.pd.DataFrame(
                    [{"date": date.today().isoformat(), "resting_heart_rate": 55}]
                )

            with self._patched_local_extractors(summary_side_effect=mutate_database):
                with self.assertRaisesRegex(
                    module.LocalDataChangedError, "changed during the verified read window"
                ):
                    module.fetch_local_summary(
                        1, database_paths=[garmin_db, activities_db]
                    )

    def test_cross_firmware_epoch_baseline_is_not_comparable(self):
        start = date(2026, 7, 1)
        hrv = []
        heart_rate = []
        for offset in range(module.MIN_PAIRED_BASELINE_DAYS + 1):
            day = (start + timedelta(days=offset)).isoformat()
            hrv.append({"date": day, "last_night_avg": 50 + offset})
            heart_rate.append({"date": day, "resting_hr": 55 + offset})

        summary = {
            "hrv": hrv,
            "heart_rate": heart_rate,
            "sleep": [],
            "measurement_epoch_evidence": {
                "analysis_algorithm_epoch": module.BASELINE_ALGORITHM_EPOCH,
                "manufacturer_algorithm_epoch": "not_available_in_local_schema",
                "firmware_history": [
                    {
                        "timestamp": "2026-07-01 00:00:00",
                        "serial_number": "alpha",
                        "software_version": "1.0",
                    },
                    {
                        "timestamp": "2026-07-15 00:00:00",
                        "serial_number": "alpha",
                        "software_version": "2.0",
                    },
                ],
            },
        }

        result = module.analyze_baseline_change(summary)

        self.assertEqual(result["status"], "not_comparable")
        self.assertEqual(result["classification"], "not_comparable_cross_epoch")
        self.assertFalse(result["epoch_comparability"]["comparable"])
        self.assertIn("alpha|1.0", result["epoch_comparability"]["observed_epochs"])
        self.assertIn("alpha|2.0", result["epoch_comparability"]["observed_epochs"])

    def _patched_local_extractors(self, summary_side_effect=None):
        empty = module.pd.DataFrame()
        summary = module.pd.DataFrame(
            [{"date": date.today().isoformat(), "resting_heart_rate": 55}]
        )
        stack = __import__("contextlib").ExitStack()
        stack.enter_context(patch.object(module, "HAS_SQLITE", True))
        stack.enter_context(
            patch.object(
                module,
                "sqlite_summary",
                side_effect=summary_side_effect,
                return_value=None if summary_side_effect else summary,
            )
        )
        for name in (
            "sqlite_sleep",
            "sqlite_hrv",
            "sqlite_activities",
            "sqlite_biomechanics",
            "get_body_composition_detailed",
        ):
            stack.enter_context(patch.object(module, name, return_value=empty))
        stack.enter_context(patch.object(module, "get_devices_info", return_value=empty))
        stack.enter_context(
            patch.object(module, "get_device_firmware_history", return_value=empty)
        )
        stack.enter_context(
            patch.object(
                module,
                "get_max_metrics",
                return_value={"vo2_max": None, "fitness_age": None},
            )
        )
        return stack


if __name__ == "__main__":
    unittest.main()
