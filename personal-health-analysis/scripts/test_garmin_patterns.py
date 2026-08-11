import importlib.util
import json
import unittest
from datetime import date, timedelta
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("garmin_patterns.py")
SPEC = importlib.util.spec_from_file_location("garmin_patterns", SCRIPT_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def date_strings(start: str, count: int) -> list[str]:
    first = date.fromisoformat(start)
    return [(first + timedelta(days=offset)).isoformat() for offset in range(count)]


class NormalizeDailyNumericTests(unittest.TestCase):
    def test_order_is_irrelevant_and_identical_duplicates_are_idempotent(self):
        requested = date_strings("2026-01-01", 3)
        result = module.normalize_daily_numeric(
            [
                {"date": requested[2], "value": 30},
                {"date": requested[0], "value": 10},
                {"date": requested[1], "value": 20.0},
                {"date": requested[1], "value": 20},
            ],
            "value",
            requested,
        )

        self.assertEqual(
            result["values"],
            [
                {"date": requested[0], "value": 10.0},
                {"date": requested[1], "value": 20.0},
                {"date": requested[2], "value": 30.0},
            ],
        )
        self.assertEqual(result["idempotent_duplicate_dates"], [requested[1]])
        self.assertEqual(result["conflicting_duplicate_dates"], [])
        self.assertEqual(result["method_version"], "patterns.v1")
        self.assertFalse(result["medical_interpretation"])

    def test_conflicting_duplicates_are_marked_and_fully_excluded(self):
        requested = date_strings("2026-01-01", 2)
        result = module.normalize_daily_numeric(
            [
                {"date": requested[0], "value": 10},
                {"date": requested[0], "value": 11},
                {"date": requested[1], "value": 12},
            ],
            "value",
            requested,
        )

        self.assertEqual(result["conflicting_duplicate_dates"], [requested[0]])
        self.assertEqual(result["facts"], [{"date": requested[1], "value": 12.0}])
        self.assertEqual(result["values"], [{"date": requested[1], "value": 12.0}])
        self.assertIn("conflicting_duplicates_excluded", result["limitations"])

    def test_non_finite_null_and_invalid_dates_are_excluded_and_zero_is_a_fact(self):
        requested = date_strings("2026-01-01", 3)
        result = module.normalize_daily_numeric(
            [
                {"date": requested[0], "value": 0},
                {"date": requested[1], "value": None},
                {"date": requested[1], "value": float("nan")},
                {"date": requested[1], "value": float("inf")},
                {"date": "2026-1-2", "value": 2},
                {"date": requested[2], "value": True},
                {"date": "2026-02-01", "value": 9},
            ],
            "value",
            requested,
        )

        self.assertEqual(
            result["facts"],
            [
                {
                    "date": requested[0],
                    "value": 0.0,
                    "eligible_for_derived": False,
                    "exclusion_reason": "non_positive_value",
                }
            ],
        )
        self.assertEqual(result["values"], [])
        reasons = {item["reason"] for item in result["excluded_records"]}
        self.assertTrue(
            {
                "missing_value",
                "non_finite_value",
                "invalid_date",
                "non_numeric_value",
                "out_of_scope",
            }
            <= reasons
        )

        allowed = module.normalize_daily_numeric(
            [{"date": requested[0], "value": 0}],
            "value",
            requested,
            allow_zero=True,
        )
        self.assertEqual(allowed["values"], [{"date": requested[0], "value": 0.0}])

    def test_requested_dates_must_be_strict_iso_calendar_dates(self):
        for invalid in ("2026-1-01", "2026-02-30", 20260101, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                module.normalize_daily_numeric([], "value", [invalid])


class ObservationContinuityTests(unittest.TestCase):
    def test_reports_intervals_longest_and_current_missing_streaks(self):
        requested = date_strings("2026-02-01", 10)
        observed = [requested[index] for index in (0, 1, 4, 8)]

        result = module.observation_continuity(requested, observed)

        self.assertEqual(result["observed_days"], 4)
        self.assertEqual(result["missing_days"], 6)
        self.assertEqual(result["longest_missing_streak_days"], 3)
        self.assertEqual(result["current_missing_streak_days"], 1)
        self.assertEqual(
            result["missing_intervals"],
            [
                {"start": requested[2], "end": requested[3], "days": 2},
                {"start": requested[5], "end": requested[7], "days": 3},
                {"start": requested[9], "end": requested[9], "days": 1},
            ],
        )
        self.assertAlmostEqual(result["coverage_fraction"], 0.4)

    def test_empty_requested_scope_is_explicit(self):
        result = module.observation_continuity([], [])
        self.assertEqual(result["status"], "no_requested_dates")
        self.assertIsNone(result["coverage_fraction"])
        self.assertIn("no_requested_dates", result["limitations"])


class RobustPersonalTrendTests(unittest.TestCase):
    def test_uses_historical_median_mad_and_complete_recent_calendar_window(self):
        requested = date_strings("2026-03-01", 28)
        records = [
            {"date": day, "metric": value}
            for day, value in zip(requested[:21], range(1, 22), strict=True)
        ]
        records.extend({"date": day, "metric": 30} for day in reversed(requested[21:]))

        result = module.robust_personal_trend(
            records,
            "metric",
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["historical_sample_days"], 21)
        self.assertEqual(result["recent_sample_days"], 7)
        self.assertEqual(result["baseline_median"], 11.0)
        self.assertEqual(result["baseline_mad"], 5.0)
        self.assertEqual(result["recent_median"], 30.0)
        self.assertEqual(result["direction"], "above")
        self.assertAlmostEqual(result["robust_z"], 19 / (1.4826 * 5))
        self.assertIn("direction_has_no_health_valence", result["limitations"])

    def test_recent_window_is_calendar_exact_and_must_be_complete(self):
        requested = date_strings("2026-04-01", 28)
        records = [
            {"date": day, "metric": 10 + index} for index, day in enumerate(requested)
        ]
        records = [record for record in records if record["date"] != requested[-3]]

        result = module.robust_personal_trend(
            records,
            "metric",
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(result["status"], "recent_window_incomplete")
        self.assertEqual(result["recent_sample_days"], 6)
        self.assertIsNone(result["recent_median"])
        self.assertIsNone(result["direction"])

    def test_unknown_and_cross_epoch_fail_closed_without_comparison_values(self):
        requested = date_strings("2026-05-01", 28)
        records = [
            {"date": day, "metric": index + 1} for index, day in enumerate(requested)
        ]
        comparison_keys = (
            "baseline_median",
            "baseline_mad",
            "recent_median",
            "absolute_delta",
            "robust_z",
            "direction",
        )

        unknown = module.robust_personal_trend(
            records,
            "metric",
            requested,
            epoch_comparable=None,
            epoch_status="unknown",
        )
        crossed = module.robust_personal_trend(
            records,
            "metric",
            requested,
            epoch_comparable=False,
            epoch_status="cross_epoch",
        )

        self.assertEqual(unknown["status"], "epoch_unknown")
        self.assertEqual(crossed["status"], "cross_epoch")
        for result in (unknown, crossed):
            for key in comparison_keys:
                self.assertIsNone(result[key])

    def test_zero_mad_withholds_robust_z_and_direction(self):
        requested = date_strings("2026-06-01", 28)
        records = [{"date": day, "metric": 10} for day in requested[:21]]
        records.extend({"date": day, "metric": 12} for day in requested[21:])

        result = module.robust_personal_trend(
            records,
            "metric",
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(result["status"], "zero_baseline_mad")
        self.assertEqual(result["baseline_mad"], 0.0)
        self.assertEqual(result["recent_median"], 12.0)
        self.assertIsNone(result["robust_z"])
        self.assertIsNone(result["direction"])
        self.assertIn(
            "zero_baseline_mad_prevents_standardization", result["limitations"]
        )

    def test_direction_vocabulary_is_limited_to_descriptive_classes(self):
        requested = date_strings("2026-07-01", 28)
        baseline = list(range(1, 22))
        recent = [10, 11, 12, 11, 10, 12, 11]
        records = [
            {"date": day, "metric": value}
            for day, value in zip(requested, baseline + recent, strict=True)
        ]
        result = module.robust_personal_trend(
            records,
            "metric",
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )
        self.assertEqual(result["direction"], "mixed")
        self.assertIn(result["direction"], {"above", "below", "mixed", "equal"})


class SleepRegularitySnapshotTests(unittest.TestCase):
    @staticmethod
    def _sleep_record(day: str, start_hour: int, offset: str = "+08:00") -> dict:
        start_date = date.fromisoformat(day)
        if start_hour >= 12:
            end_date = start_date + timedelta(days=1)
            end_hour = (start_hour + 8) % 24
        else:
            end_date = start_date
            end_hour = start_hour + 8
        return {
            "date": day,
            "sleep_start": f"{start_date.isoformat()}T{start_hour:02d}:00:00{offset}",
            "sleep_end": f"{end_date.isoformat()}T{end_hour:02d}:00:00{offset}",
        }

    def test_reports_duration_and_circular_timing_dispersion(self):
        requested = date_strings("2026-08-01", 14)
        start_hours = [23, 0, 23, 0, 23, 0, 23]
        records = [
            self._sleep_record(day, hour)
            for day, hour in zip(requested[-7:], start_hours, strict=True)
        ]

        result = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["valid_nights"], 7)
        self.assertEqual(result["duration_status"], "eligible")
        self.assertEqual(result["timing_status"], "eligible")
        self.assertEqual(result["duration_source"], "timestamp_interval_seconds")
        self.assertEqual(result["duration_sd_hours"], 0.0)
        self.assertLess(result["bedtime_circular_sd_hours"], 1.0)
        self.assertLess(result["midpoint_circular_sd_hours"], 1.0)
        self.assertLess(result["wake_time_circular_sd_hours"], 1.0)
        serialized = json.dumps(result).lower()
        self.assertNotIn("social jetlag", serialized)
        self.assertNotIn('"sri"', serialized)
        self.assertFalse(result["medical_interpretation"])

    def test_daily_sleep_seconds_remain_available_without_timing_fields(self):
        requested = date_strings("2026-08-01", 14)
        records = [
            {
                "date": day,
                "sleep_time_seconds": 25200 if index % 2 else 28800,
            }
            for index, day in enumerate(requested)
        ]
        result = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )
        self.assertEqual(result["status"], "partial_available")
        self.assertEqual(result["duration_status"], "eligible")
        self.assertEqual(result["timing_status"], "source_not_supported")
        self.assertEqual(result["duration_source"], "sleep_time_seconds")
        self.assertEqual(result["duration_valid_nights"], 14)
        self.assertGreater(result["duration_sd_hours"], 0)
        self.assertIsNone(result["midpoint_circular_sd_hours"])

    def test_conflicting_daily_duration_is_excluded_before_derivation(self):
        requested = date_strings("2026-08-01", 8)
        records = [{"date": day, "sleep_time_seconds": 28800} for day in requested]
        records.append({"date": requested[0], "sleep_time_seconds": 25200})
        result = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )
        self.assertEqual(result["status"], "duplicate_conflict")
        self.assertEqual(result["duration_status"], "duplicate_conflict")
        self.assertIsNone(result["duration_sd_hours"])
        self.assertIn(requested[0], result["duration_excluded_dates"])
        self.assertNotIn(requested[0], result["duration_sample_dates"])

    def test_conflicting_sleep_timestamps_block_timing_derivation(self):
        requested = date_strings("2026-08-01", 14)
        records = [self._sleep_record(day, 23) for day in requested[-8:]]
        records.append(self._sleep_record(requested[-8], 22))

        result = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(result["status"], "duplicate_conflict")
        self.assertEqual(result["timing_status"], "duplicate_conflict")
        self.assertIsNone(result["bedtime_circular_sd_hours"])
        self.assertIsNone(result["midpoint_circular_sd_hours"])
        self.assertIsNone(result["wake_time_circular_sd_hours"])

    def test_records_outside_explicit_requested_dates_are_not_used(self):
        full_window = date_strings("2026-08-01", 14)
        requested = full_window[::2]
        records = [self._sleep_record(day, 23) for day in full_window[1::2]]
        result = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
            window_days=14,
        )
        self.assertEqual(result["status"], "source_not_supported")
        self.assertEqual(result["valid_nights"], 0)

    def test_naive_or_mixed_offsets_fail_closed(self):
        requested = date_strings("2026-08-01", 14)
        valid = [self._sleep_record(day, 23) for day in requested[-7:]]
        naive = [dict(item) for item in valid]
        naive[0]["sleep_start"] = naive[0]["sleep_start"].removesuffix("+08:00")
        mixed = [dict(item) for item in valid]
        mixed[-1] = self._sleep_record(requested[-1], 23, "+09:00")

        naive_result = module.sleep_regularity_snapshot(
            naive,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )
        mixed_result = module.sleep_regularity_snapshot(
            mixed,
            requested,
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(naive_result["status"], "timezone_unknown")
        self.assertEqual(naive_result["duration_status"], "insufficient_valid_nights")
        self.assertEqual(mixed_result["status"], "partial_available")
        self.assertEqual(mixed_result["duration_status"], "eligible")
        self.assertEqual(mixed_result["timing_status"], "mixed_utc_offset")
        self.assertEqual(mixed_result["duration_sd_hours"], 0.0)
        for result in (naive_result, mixed_result):
            self.assertIsNone(result["midpoint_circular_sd_hours"])

    def test_epoch_unknown_and_cross_epoch_fail_closed(self):
        requested = date_strings("2026-08-01", 14)
        records = [self._sleep_record(day, 23) for day in requested[-7:]]
        unknown = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=None,
            epoch_status="unknown",
        )
        crossed = module.sleep_regularity_snapshot(
            records,
            requested,
            epoch_comparable=False,
            epoch_status="cross_epoch",
        )
        self.assertEqual(unknown["status"], "epoch_unknown")
        self.assertEqual(crossed["status"], "cross_epoch")


class LaggedRankAssociationTests(unittest.TestCase):
    @staticmethod
    def _series(days: list[str], field: str, values) -> list[dict]:
        return [
            {"date": day, field: value} for day, value in zip(days, values, strict=True)
        ]

    def test_exact_next_calendar_day_spearman_is_exploratory_and_noncausal(self):
        requested = date_strings("2026-09-01", 29)
        exposure = self._series(requested, "load", range(29))
        outcome = self._series(requested, "recovery", range(1, 30))

        result = module.lagged_rank_association(
            exposure,
            "load",
            outcome,
            "recovery",
            requested,
            exposure_coverage_semantics="explicit_daily_zero",
            epoch_comparable=True,
            epoch_status="single_epoch",
        )

        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["pair_count"], 28)
        self.assertAlmostEqual(result["spearman_rho"], 1.0)
        self.assertFalse(result["causal_interpretation"])
        self.assertFalse(result["medical_interpretation"])
        self.assertIn("exploratory_association_not_causation", result["limitations"])
        self.assertEqual(result["pair_dates"][0]["exposure_date"], requested[0])
        self.assertEqual(result["pair_dates"][0]["outcome_date"], requested[1])

    def test_unknown_load_coverage_and_epoch_states_fail_closed(self):
        requested = date_strings("2026-09-01", 29)
        exposure = self._series(requested, "load", range(29))
        outcome = self._series(requested, "recovery", range(1, 30))
        common = (exposure, "load", outcome, "recovery", requested)

        unknown_load = module.lagged_rank_association(
            *common,
            exposure_coverage_semantics="activity_days_only",
            epoch_comparable=True,
            epoch_status="single_epoch",
        )
        unknown_epoch = module.lagged_rank_association(
            *common,
            exposure_coverage_semantics="explicit_daily_zero",
            epoch_comparable=None,
            epoch_status="unknown",
        )
        crossed = module.lagged_rank_association(
            *common,
            exposure_coverage_semantics="explicit_daily_zero",
            epoch_comparable=False,
            epoch_status="cross_epoch",
        )

        self.assertEqual(unknown_load["status"], "load_coverage_unknown")
        self.assertEqual(unknown_epoch["status"], "epoch_unknown")
        self.assertEqual(crossed["status"], "cross_epoch")
        for result in (unknown_load, unknown_epoch, crossed):
            self.assertIsNone(result["spearman_rho"])

    def test_exact_date_join_does_not_backfill_or_nearest_match(self):
        requested = date_strings("2026-10-01", 30)
        exposure = self._series(requested, "load", range(30))
        outcome_days = [
            day for index, day in enumerate(requested) if index not in (5, 11)
        ]
        outcome = self._series(
            outcome_days, "recovery", range(1, len(outcome_days) + 1)
        )

        result = module.lagged_rank_association(
            exposure,
            "load",
            outcome,
            "recovery",
            requested,
            exposure_coverage_semantics="explicit_daily_zero",
            epoch_comparable=True,
            epoch_status="single_epoch",
            min_pairs=28,
        )

        self.assertEqual(result["status"], "insufficient_pairs")
        self.assertEqual(result["pair_count"], 27)
        self.assertIsNone(result["spearman_rho"])

    def test_constant_rank_series_withholds_correlation(self):
        requested = date_strings("2026-11-01", 29)
        exposure = self._series(requested, "load", [1] * 29)
        outcome = self._series(requested, "recovery", range(1, 30))
        result = module.lagged_rank_association(
            exposure,
            "load",
            outcome,
            "recovery",
            requested,
            exposure_coverage_semantics="explicit_daily_zero",
            epoch_comparable=True,
            epoch_status="single_epoch",
        )
        self.assertEqual(result["status"], "constant_series")
        self.assertIsNone(result["spearman_rho"])

    def test_conflicting_duplicate_blocks_lag_correlation(self):
        requested = date_strings("2026-12-01", 30)
        exposure = self._series(requested, "load", range(30))
        exposure.append({"date": requested[0], "load": 999})
        outcome = self._series(requested, "recovery", range(1, 31))

        result = module.lagged_rank_association(
            exposure,
            "load",
            outcome,
            "recovery",
            requested,
            exposure_coverage_semantics="explicit_daily_zero",
            epoch_comparable=True,
            epoch_status="single_epoch",
            min_pairs=28,
        )

        self.assertEqual(result["status"], "duplicate_conflict")
        self.assertIsNone(result["spearman_rho"])
        self.assertEqual(result["pair_count"], 0)


if __name__ == "__main__":
    unittest.main()
