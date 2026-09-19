"""Synthetic-only regression tests for bounded dashboard lookbacks."""
import contextlib
import sqlite3
import unittest
from unittest.mock import patch

import garmin_chart as chart
import garmin_intelligence as intelligence
import garmin_sqlite_adapter as adapter


class Window:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def public_summary(self):
        return {"status": "verified_unchanged", "database_count": 2}


class ScopeTests(unittest.TestCase):
    def test_default_components_include_only_aggregate_training(self):
        self.assertIn("training_load_series", chart.DASHBOARD_DEFAULT_COMPONENTS)
        self.assertNotIn("activities", chart.DASHBOARD_DEFAULT_COMPONENTS)

    def test_required_horizons_and_opt_out(self):
        c = chart.DASHBOARD_DEFAULT_COMPONENTS
        p = intelligence.dashboard_analysis_plan(7, c)
        self.assertEqual(p["analysis_days"], 29)
        self.assertEqual(p["sleep_regularity_days"], 14)
        self.assertEqual(p["association_pairs"], 28)
        self.assertNotIn("stress", p["components"])
        self.assertNotIn("body_battery", p["components"])
        self.assertEqual(intelligence.dashboard_analysis_plan(7, ("sleep",))["analysis_days"], 28)
        self.assertEqual(intelligence.dashboard_analysis_plan(7, ("stress",))["analysis_days"], 7)
        self.assertEqual(intelligence.dashboard_analysis_plan(7, c, "requested")["analysis_days"], 7)
        self.assertEqual(intelligence.dashboard_analysis_plan(60, c)["analysis_days"], 60)

    def test_read_windows_share_integrity_guard(self):
        def fake(days, **kwargs):
            return {"status": "partial", "summary": {"period": "2026-08-01 to 2026-09-13"}}
        with patch.object(intelligence, "_verified_local_read_window", return_value=Window()) as boundary, patch.object(intelligence, "_fetch_local_summary_unverified", side_effect=fake) as read:
            result = intelligence.fetch_dashboard_summary(7, components=chart.DASHBOARD_DEFAULT_COMPONENTS)
        self.assertEqual(boundary.call_count, 1)
        self.assertEqual([x.args[0] for x in read.call_args_list], [7, 29])
        self.assertEqual(set(read.call_args_list[1].kwargs["components"]), {"sleep", "hrv", "heart_rate", "training_load_series"})
        self.assertIn("_analysis_source", result)

    def test_no_data_does_not_expand(self):
        with patch.object(intelligence, "_verified_local_read_window", return_value=Window()), patch.object(intelligence, "_fetch_local_summary_unverified", return_value={"status": "no_data"}) as read:
            value = intelligence.fetch_dashboard_summary(7, components=chart.DASHBOARD_DEFAULT_COMPONENTS)
        self.assertEqual(read.call_count, 1)
        self.assertNotIn("_analysis_source", value)

    def test_requested_does_not_expand(self):
        with patch.object(intelligence, "_verified_local_read_window", return_value=Window()), patch.object(intelligence, "_fetch_local_summary_unverified", return_value={"status": "partial"}) as read:
            intelligence.fetch_dashboard_summary(7, components=chart.DASHBOARD_DEFAULT_COMPONENTS, policy="requested")
        self.assertEqual(read.call_count, 1)

    def test_read_error_is_not_no_data(self):
        with patch.object(intelligence, "_verified_local_read_window", return_value=Window()), patch.object(intelligence, "_fetch_local_summary_unverified", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                intelligence.fetch_dashboard_summary(7, components=chart.DASHBOARD_DEFAULT_COMPONENTS)

    def test_payload_separates_display_from_analysis_and_keeps_epoch_gate(self):
        from datetime import date, timedelta
        import copy
        end = date(2026, 9, 13)
        dates = [(end - timedelta(days=28 - i)).isoformat() for i in range(29)]
        def source(selected):
            return {
                'status': 'complete', 'summary': {'period': selected[0] + ' to ' + selected[-1]},
                'sleep': [{'date': d, 'sleep_time_seconds': 25200, 'sleep_start': d + 'T00:00:00+08:00', 'sleep_end': d + 'T07:00:00+08:00'} for d in selected],
                'hrv': [{'date': d, 'last_night_avg': 40} for d in selected],
                'heart_rate': [{'date': d, 'resting_hr': 60} for d in selected],
                'training_load_series': [{'date': d, 'acute_load': 10} for d in selected],
                'component_status': {c: {'status': 'observed'} for c in chart.DASHBOARD_DEFAULT_COMPONENTS},
            }
        data = source(dates[-7:])
        data['_analysis_source'] = source(dates)
        data['_analysis_plan'] = intelligence.dashboard_analysis_plan(7, chart.DASHBOARD_DEFAULT_COMPONENTS)
        value = chart.build_dashboard_payload(data, days=7, requested_source='local', effective_source='local', selected_components=chart.DASHBOARD_DEFAULT_COMPONENTS, live_fallback_attempted=False, requested_start=dates[-7], requested_end=dates[-1])
        projected = chart._project_dashboard_payload(value)
        self.assertEqual(len(projected['series']['dates']), 7)
        self.assertEqual(projected['meta']['analysis_range']['days'], 29)
        self.assertEqual(projected['patterns']['sleep_regularity']['window_days'], 14)
        self.assertNotEqual(projected['patterns']['sleep_regularity']['status'], 'insufficient_window')
        self.assertEqual(projected['patterns']['sleep_regularity']['status'], 'epoch_unknown')
        for item in projected['patterns']['lagged_associations'].values():
            self.assertNotEqual(item['status'], 'not_requested')

    def test_training_adapter_is_aggregate_only_no_zero_fill(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE activities(start_time TEXT, training_load REAL, name TEXT)")
        db.executemany("INSERT INTO activities VALUES(?,?,?)", [("2026-09-12T10:00:00", 10, "DO_NOT_READ"), ("2026-09-12T11:00:00", 20, "DO_NOT_READ")])
        queries = []
        db.set_trace_callback(queries.append)
        with patch.object(adapter, "get_connection", return_value=db), patch.object(adapter, "_window_start", return_value="2026-09-11"):
            frame = adapter.get_training_load_data(3)
        self.assertEqual(list(frame.columns), ["date", "training_load"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["training_load"], 30)
        self.assertFalse(any("name" in q.lower() for q in queries))

    def test_minimal_summary_real_sql_adapter_path(self):
        from datetime import date
        db = sqlite3.connect(':memory:')
        # Deliberately omit stress/Body Battery columns: over-reading must fail.
        db.execute('CREATE TABLE daily_summary(day TEXT, rhr REAL, hr_max REAL)')
        db.execute('INSERT INTO daily_summary VALUES(?,?,?)', (date.today().isoformat(), 60, 110))
        sql = []
        db.set_trace_callback(sql.append)
        with patch.object(adapter, 'get_connection', return_value=db), patch.object(intelligence, 'HAS_SQLITE', True):
            value = intelligence._fetch_local_summary_unverified(29, components=('heart_rate',), metadata_components=(), minimal_summary=True)
        today = next(r for r in value['heart_rate'] if r['date'] == date.today().isoformat())
        self.assertEqual(today['resting_hr'], 60)
        projections = [q for q in sql if 'FROM daily_summary' in q]
        self.assertEqual(len(projections), 1)
        self.assertNotIn('stress', projections[0])
        self.assertNotIn('bb_', projections[0])

    def test_overlay_default_does_not_add_load_or_lookback(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder, patch.object(chart, '_load_summary', return_value={'status': 'no_data'}) as load, patch.object(chart, 'build_dashboard_payload', return_value={}), patch.object(chart, 'render_report', return_value='<html></html>'):
            result = chart.main(['overlay', '--days', '7', '--allow-health-data', '--output', str(Path(folder)/'overlay.html')])
        self.assertEqual(result, 0)
        self.assertNotIn('training_load_series', load.call_args.kwargs['components'])
        self.assertEqual(load.call_args.kwargs['analysis_window'], 'requested')

    def test_sleep_adapter_passes_timestamps_without_invented_timezone(self):
        db = sqlite3.connect(":memory:")
        db.execute('CREATE TABLE sleep(day TEXT, total_sleep TEXT, deep_sleep TEXT, light_sleep TEXT, rem_sleep TEXT, awake TEXT, score REAL, avg_rr REAL, avg_spo2 REAL, avg_stress REAL, start TEXT, end TEXT)')
        db.execute('INSERT INTO sleep VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', ('2026-09-12','07:00:00','01:00:00','05:00:00','01:00:00','00:10:00',80,15,98,20,'2026-09-11T23:00:00','2026-09-12T06:00:00'))
        with patch.object(adapter, "get_connection", return_value=db), patch.object(adapter, "_window_start", return_value="2026-09-11"):
            frame = adapter.get_sleep_data(3, fill_missing=False)
        self.assertEqual(frame.iloc[0]["sleep_start"], '2026-09-11T23:00:00')
        self.assertEqual(frame.iloc[0]["sleep_end"], '2026-09-12T06:00:00')


if __name__ == "__main__":
    unittest.main()
