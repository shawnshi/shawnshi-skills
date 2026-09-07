import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

import garmin_chart
import garmin_intelligence
from garmin_capabilities import issue_capability


class _VerifiedWindowStub:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def public_summary(self):
        return {"status": "verified_unchanged", "databases": []}


class GarminChartFailureContractTests(unittest.TestCase):
    def test_default_dashboard_reads_only_rendered_components(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "default-scope.html"
            with (
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    return_value={"status": "no_data"},
                ) as fetch_local,
                patch.object(
                    garmin_chart,
                    "build_dashboard_payload",
                    return_value={"schema_version": "dashboard.v3"},
                ),
                patch.object(garmin_chart, "render_report", return_value="<html></html>"),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(rc, 0)
        fetch_local.assert_called_once_with(
            7, components=garmin_chart.DASHBOARD_DEFAULT_COMPONENTS
        )
        self.assertNotIn("activities", garmin_chart.DASHBOARD_DEFAULT_COMPONENTS)
        self.assertNotIn("training_load_series", garmin_chart.DASHBOARD_DEFAULT_COMPONENTS)

    def test_local_dashboard_requires_health_data_permission_before_read(self):
        stderr = io.StringIO()
        with (
            patch.object(
                garmin_chart,
                "fetch_local_summary",
                side_effect=AssertionError("permission gate must run before local read"),
            ) as fetch_local,
            patch("sys.stderr", stderr),
        ):
            result = garmin_chart.main(["dashboard", "--days", "7"])

        self.assertEqual(result, 2)
        self.assertEqual(
            json.loads(stderr.getvalue())["status"],
            "HEALTH_DATA_ACCESS_NOT_AUTHORIZED",
        )
        fetch_local.assert_not_called()

    def test_invalid_period_stops_before_live_client_initialization(self):
        stderr = io.StringIO()
        with (
            patch.object(garmin_chart, "get_client") as get_client,
            patch("sys.stderr", stderr),
        ):
            result = garmin_chart.main(
                [
                    "dashboard",
                    "--source",
                    "live",
                    "--period",
                    "0d",
                    "--allow-network",
                    "--allow-health-data",
                ]
            )
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(stderr.getvalue())["status"], "INVALID_PERIOD_SCOPE")
        get_client.assert_not_called()

    def test_malformed_bound_scope_stops_before_live_client_initialization(self):
        base = {
            "chart": "dashboard",
            "source": "live",
            "start": "2026-08-01",
            "end": "2026-08-02",
            "components": list(garmin_chart.LIVE_SUMMARY_COMPONENTS),
        }
        malformed = []
        wrong_components = dict(base)
        wrong_components["components"] = ["sleep", "profile"]
        malformed.append(wrong_components)
        wrong_window = dict(base)
        wrong_window["end"] = "2026-08-03"
        malformed.append(wrong_window)
        invalid_date = dict(base)
        invalid_date["start"] = "not-a-date"
        malformed.append(invalid_date)

        for request in malformed:
            with self.subTest(request=request), patch.object(
                garmin_chart, "get_client"
            ) as get_client:
                with self.assertRaisesRegex(RuntimeError, "LIVE_SCOPE_INVALID"):
                    garmin_chart._load_summary(
                        2,
                        "live",
                        network_capability=issue_capability(
                            scope="network",
                            operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                            request=request,
                        ),
                        health_data_capability=issue_capability(
                            scope="health_data",
                            operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                            request=request,
                        ),
                        request=request,
                    )
                get_client.assert_not_called()

    def test_live_dashboard_uses_exact_bound_window_and_fixed_components(self):
        request = {
            "chart": "dashboard",
            "source": "live",
            "start": "2026-08-01",
            "end": "2026-08-02",
            "components": list(garmin_chart.LIVE_SUMMARY_COMPONENTS),
        }
        client = object()
        with (
            patch.object(garmin_chart, "get_client", return_value=client),
            patch.object(
                garmin_chart, "fetch_summary", return_value={"summary": {}}
            ) as fetch,
        ):
            result = garmin_chart._load_summary(
                2,
                "live",
                network_capability=issue_capability(
                    scope="network",
                    operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                    request=request,
                ),
                health_data_capability=issue_capability(
                    scope="health_data",
                    operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                    request=request,
                ),
                request=request,
            )

        self.assertEqual(result, {"summary": {}})
        fetch.assert_called_once_with(
            client,
            start="2026-08-01",
            end="2026-08-02",
            components=request["components"],
        )

    def test_database_change_fails_before_dashboard_write(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "dashboard.html"
            stderr = io.StringIO()
            with (
                patch.object(garmin_chart, "HAS_SQLITE", True),
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    side_effect=RuntimeError("database_changed_during_read"),
                ),
                patch("sys.stderr", stderr),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--source",
                        "local",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertFalse(output.exists())
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["status"], "DATA_SOURCE_UNAVAILABLE")
            self.assertEqual(payload["source"], "local")
            self.assertFalse(payload["live_fallback_attempted"])

    def test_no_data_fallback_requires_explicit_network_authorization(self):
        stderr = io.StringIO()
        with (
            patch.object(garmin_chart, "fetch_local_summary") as fetch_local,
            patch.object(garmin_chart, "get_client") as get_client,
            patch("sys.stderr", stderr),
        ):
            rc = garmin_chart.main(
                [
                    "dashboard",
                    "--days",
                    "7",
                    "--source",
                    "local",
                    "--fallback-live",
                    "--components",
                    "sleep,hrv,body_battery,heart_rate,activities,stress",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(rc, 2)
        self.assertEqual(
            json.loads(stderr.getvalue())["status"],
            "NETWORK_ACCESS_NOT_AUTHORIZED",
        )
        fetch_local.assert_not_called()
        get_client.assert_not_called()

    def test_local_no_data_falls_back_to_exact_authorized_components(self):
        components = [
            "sleep",
            "hrv",
            "body_battery",
            "heart_rate",
            "activities",
            "stress",
        ]
        insight = {
            "overall_insight": "fixture",
            "audit_data": {},
            "period": "fixture",
            "quant_scores": {},
        }
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "fallback.html"
            with (
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    return_value={"status": "no_data"},
                ),
                patch.object(garmin_chart, "get_client", return_value=object()) as get_client,
                patch.object(
                    garmin_chart,
                    "fetch_summary",
                    return_value={"status": "partial", "sleep": []},
                ) as fetch_summary,
                patch.object(
                    garmin_chart, "generate_chinese_insight", return_value=insight
                ),
                patch.object(garmin_chart, "render_report", return_value="<html></html>"),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--source",
                        "local",
                        "--fallback-live",
                        "--components",
                        ",".join(components),
                        "--allow-network",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(rc, 0)
        request = get_client.call_args.kwargs["request"]
        self.assertEqual(request["components"], components)
        fetch_summary.assert_called_once_with(
            get_client.return_value,
            start=request["start"],
            end=request["end"],
            components=components,
        )

    def test_real_local_no_data_contract_triggers_authorized_live_fallback(self):
        components = list(garmin_chart.LIVE_SUMMARY_COMPONENTS)
        null_summary = garmin_intelligence.pd.DataFrame(
            [
                {
                    "date": date.today().isoformat(),
                    "resting_heart_rate": None,
                    "stress_avg": None,
                    "body_battery_highest": None,
                }
            ]
        )
        empty = garmin_intelligence.pd.DataFrame()
        observed_local = []
        real_fetch_local = garmin_intelligence.fetch_local_summary

        def fetch_real_no_data(days, *, components=None):
            result = real_fetch_local(days, components=components)
            observed_local.append(result)
            return result

        with tempfile.TemporaryDirectory() as temp_root, ExitStack() as stack:
            output = Path(temp_root) / "real-no-data-fallback.html"
            stack.enter_context(patch.object(garmin_intelligence, "HAS_SQLITE", True))
            stack.enter_context(
                patch.object(
                    garmin_intelligence,
                    "_verified_local_read_window",
                    return_value=_VerifiedWindowStub(),
                )
            )
            stack.enter_context(
                patch.object(
                    garmin_intelligence, "sqlite_summary", return_value=null_summary
                )
            )
            for name in (
                "sqlite_sleep",
                "sqlite_hrv",
                "sqlite_activities",
                "sqlite_biomechanics",
                "get_body_composition_detailed",
                "get_devices_info",
                "get_device_firmware_history",
            ):
                stack.enter_context(
                    patch.object(garmin_intelligence, name, return_value=empty)
                )
            stack.enter_context(
                patch.object(garmin_intelligence, "usable_method_config", return_value=None)
            )
            stack.enter_context(
                patch.object(garmin_chart, "fetch_local_summary", side_effect=fetch_real_no_data)
            )
            get_client = stack.enter_context(
                patch.object(garmin_chart, "get_client", return_value=object())
            )
            fetch_summary = stack.enter_context(
                patch.object(
                    garmin_chart,
                    "fetch_summary",
                    return_value={"status": "partial", "sleep": []},
                )
            )
            stack.enter_context(
                patch.object(
                    garmin_chart, "render_report", return_value="<html></html>"
                )
            )

            rc = garmin_chart.main(
                [
                    "dashboard",
                    "--days",
                    "7",
                    "--source",
                    "local",
                    "--fallback-live",
                    "--components",
                    ",".join(components),
                    "--allow-network",
                    "--allow-health-data",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(observed_local[0]["status"], "no_data")
        self.assertTrue(
            all(
                observed_local[0]["component_status"][name]["status"] == "no_data"
                for name in components
            )
        )
        request = get_client.call_args.kwargs["request"]
        fetch_summary.assert_called_once_with(
            get_client.return_value,
            start=request["start"],
            end=request["end"],
            components=components,
        )

    def test_partial_local_data_does_not_fall_back_live(self):
        insight = {
            "overall_insight": "fixture",
            "audit_data": {},
            "period": "fixture",
            "quant_scores": {},
        }
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "local-partial.html"
            with (
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    return_value={"status": "partial", "sleep": []},
                ),
                patch.object(garmin_chart, "get_client") as get_client,
                patch.object(
                    garmin_chart, "generate_chinese_insight", return_value=insight
                ),
                patch.object(garmin_chart, "render_report", return_value="<html></html>"),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--source",
                        "local",
                        "--fallback-live",
                        "--components",
                        "sleep,hrv,body_battery,heart_rate,activities,stress",
                        "--allow-network",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(rc, 0)
        get_client.assert_not_called()

class GarminChartProblemInsightTests(unittest.TestCase):
    @staticmethod
    def fixture(count=2):
        days = ["2026-09-01", "2026-09-02"][:count]
        return {
            "sleep": [{"date": day, "sleep_time_seconds": 25200, "deep_sleep_seconds": 3600,
                       "rem_sleep_seconds": 7200, "light_sleep_seconds": 14400,
                       "avg_respiration": 15, "avg_spo2": 97, "sleep_score": 80} for day in days],
            "hrv": [{"date": day, "last_night_avg": 45} for day in days],
            "heart_rate": [{"date": day, "resting_hr": 60} for day in days],
            "body_battery": [{"date": day, "highest": 80, "lowest": 30} for day in days],
            "stress": [{"date": day, "avg_stress": 25, "steps": 4000} for day in days],
            "activities": [{"date": "2026-09-01", "activity_name": "PRIVATE_ACTIVITY", "calories": 9999}],
            "weight": [{"date": "2026-09-01", "weight": 9999}],
            "device_info": [{"serial_number": "PRIVATE_SERIAL", "software_version": "1"}],
            "debug_path": "C:/private/context.json",
        }

    def build(self, count=2, components=None, context=None):
        with patch("garmin_health_profile.build_profile", side_effect=AssertionError("no profile DB loader")):
            return garmin_chart.build_dashboard_payload(
                self.fixture(count), days=2, requested_start="2026-09-01", requested_end="2026-09-02",
                requested_source="local", effective_source="local", live_fallback_attempted=False,
                selected_components=components or garmin_chart.DASHBOARD_DEFAULT_COMPONENTS,
                context_records=context,
            )

    def test_complete_partial_no_data_and_unknown_epoch(self):
        for count, status in ((2, "complete"), (1, "partial"), (0, "no_data")):
            with self.subTest(status=status):
                payload = self.build(count)
                result = payload["problem_insights"]
                self.assertEqual(result["data_status"], status)
                self.assertLessEqual(len(result["optional_actions"]), 2)
                self.assertEqual(payload["narrative"]["optional_considerations"], [])
                self.assertFalse(payload["baseline"]["qualified"])
                self.assertEqual(result["items"][1]["qualification"]["comparison_status"], "epoch_unknown")
                self.assertEqual(result["items"][0]["observations"][0]["value"], 7 if count else None)
                if count == 1:
                    self.assertEqual(result["optional_actions"][0]["id"], "verify_observation_coverage")
                    self.assertEqual(payload["kpis"]["sleep"]["observed_date"], "2026-09-01")
                for forbidden in ("PRIVATE_ACTIVITY", "PRIVATE_SERIAL", "C:/private", "9999", "/modules/"):
                    self.assertNotIn(forbidden, json.dumps(payload))

    def test_filtered_components_do_not_leak_metrics_or_context(self):
        for components, expected in ((["hrv"], ["last_night_hrv"]), (["heart_rate"], ["resting_heart_rate"]), (["sleep"], ["sleep_duration"]), (["stress"], [])):
            payload = self.build(components=components)
            items = payload["problem_insights"]["items"]
            self.assertEqual([obs["metric"] for item in items for obs in item["observations"]], expected)
            self.assertIsNone(payload["user_context_review"])
            if components == ["hrv"]:
                self.assertEqual(items[0]["qualification"]["status"], "descriptive_available")
                self.assertEqual(payload["problem_insights"]["optional_actions"], [])
        with self.assertRaisesRegex(garmin_chart.ContextValidationError, "CONTEXT_NOT_REQUESTED"):
            self.build(components=["hrv"], context=[])

    def test_context_aggregates_and_strict_projection(self):
        context = [{"date": "2026-09-01", "sleep_opportunity_minutes": 480, "caffeine_last_time": "13:37",
                    "user_selected_action": "observe_sleep_opportunity", "performed": False}]
        payload = self.build(context=context)
        review = payload["user_context_review"]
        self.assertEqual(review["summary"]["action_completed_days"], 0)
        self.assertEqual(review["summary"]["action_not_completed_days"], 1)
        self.assertEqual(review["summary"]["action_missing_days"], 1)
        self.assertEqual(review["summary"]["paired_device_sleep_duration_median_minutes"], 420)
        self.assertEqual(review["effectiveness"], "not_evaluated")
        review["records"] = context
        review["summary"]["raw_path"] = "C:/private/context.json"
        review["summary"]["action_completed_days"] = {"raw": "PRIVATE"}
        payload["problem_insights"]["items"][0]["question"] = "<img src=x onerror=alert(1)>"
        result = garmin_chart._project_dashboard_payload(payload)
        serialized = json.dumps(result)
        for forbidden in ("13:37", "C:/private", "PRIVATE", "<img", '"records"'):
            self.assertNotIn(forbidden, serialized)
        self.assertIsNone(result["user_context_review"]["summary"]["action_completed_days"])
        result["meta"]["source"]["components"] = ["hrv"]
        self.assertIsNone(garmin_chart._project_dashboard_payload(result)["user_context_review"])

    def test_context_permission_and_component_gate_before_read(self):
        for extra, status in (([], "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"),
                              (["--allow-health-data", "--components", "hrv"], "context_not_requested"),
                              (["--source", "live", "--allow-health-data"], "NETWORK_ACCESS_NOT_AUTHORIZED")):
            stderr = io.StringIO()
            with patch.object(garmin_chart, "_load_context") as read, patch.object(garmin_chart, "_load_summary") as db, patch("sys.stderr", stderr):
                rc = garmin_chart.main(["dashboard", "--days", "2", "--context-file", "//private/share.json", *extra])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(stderr.getvalue())["status"], status)
            read.assert_not_called()
            db.assert_not_called()

    def test_invalid_context_fails_before_db_and_redacts_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sensitive-name.json"
            invalids = ['{"schema_version":1,"records":[],"extra":"x"}',
                        '{"schema_version":1,"records":[{"date":"1999-01-01"}]}',
                        '{"schema_version":1,"schema_version":1,"records":[]}',
                        '{"schema_version":1,"records":[{"date":"2026-09-01","caffeine_last_time":"<script>"}]}']
            for raw in invalids:
                path.write_text(raw, encoding="utf-8")
                stderr = io.StringIO()
                with patch.object(garmin_chart, "_load_summary") as db, patch("sys.stderr", stderr):
                    rc = garmin_chart.main(["dashboard", "--days", "2", "--allow-health-data", "--context-file", str(path)])
                self.assertEqual(rc, 2)
                self.assertEqual(json.loads(stderr.getvalue())["status"], "invalid_context")
                self.assertNotIn(str(path), stderr.getvalue())
                db.assert_not_called()
            for filename, expected in ((str(Path(temp)/"missing.json"), "read_error"), ("//private/share.json", "invalid_context")):
                stderr = io.StringIO()
                with patch.object(garmin_chart, "_load_summary") as db, patch("sys.stderr", stderr):
                    garmin_chart.main(["dashboard", "--days", "2", "--allow-health-data", "--context-file", filename])
                self.assertEqual(json.loads(stderr.getvalue())["status"], expected)
                self.assertNotIn(filename, stderr.getvalue())
                db.assert_not_called()

    def test_cli_synthetic_html_and_omitted_context_no_additional_read(self):
        import base64
        import re
        with tempfile.TemporaryDirectory() as temp:
            context = Path(temp)/"context.json"
            context.write_text(json.dumps({"schema_version": 1, "records": [{"date": "2026-09-01", "sleep_opportunity_minutes": 480}]}), encoding="utf-8")
            for supplied in (False, True):
                output = Path
                output = Path(temp)/f"dashboard-{supplied}.html"
                with patch.object(garmin_chart, "get_date_range", return_value=("2026-09-01", "2026-09-02")), patch.object(garmin_chart, "_load_summary", return_value=self.fixture()), patch.object(garmin_chart, "_load_context", wraps=garmin_chart._load_context) as read:
                    rc = garmin_chart.main(["dashboard", "--days", "2", "--allow-health-data", "--output", str(output), *(["--context-file", str(context)] if supplied else [])])
                self.assertEqual(rc, 0)
                self.assertEqual(read.call_count, int(supplied))
                html = output.read_text(encoding="utf-8")
                match = re.search(r'type="application/octet-stream">([^<]+)', html)
                assert match is not None
                payload = json.loads(base64.b64decode(match.group(1)))
                self.assertEqual(payload["user_context_review"] is not None, supplied)
                self.assertIn("重点问题与证据", html)
                self.assertNotIn(str(context), html)
                self.assertLessEqual(len(payload["problem_insights"]["optional_actions"]), 2)

    def test_malicious_prose_is_encoded_not_executable(self):
        payload = self.build()
        attack = '</script><img src=x onerror="window.ATTACK=true">'
        payload["narrative"]["overall"] = attack
        html = garmin_chart.render_report(payload)
        self.assertNotIn(attack, html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("connect-src 'none'", html)


if __name__ == "__main__":
    unittest.main()
