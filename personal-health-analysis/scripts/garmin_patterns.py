"""Fail-closed, descriptive pattern analysis for daily wearable records.

The functions in this module do not diagnose, score health, or prescribe an
action.  They expose data sufficiency, within-person descriptive change, sleep
timing dispersion, and an exploratory exact-day lag association.  Every public
result carries an explicit method version and a false medical-interpretation
flag so downstream renderers cannot silently promote the values to clinical
claims.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date, datetime, timedelta
from numbers import Real
from typing import Any, Iterable


METHOD_VERSION = "patterns.v1"
_STRICT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLEEP_START_FIELDS = ("sleep_start", "sleep_start_time")
_SLEEP_END_FIELDS = ("sleep_end", "sleep_end_time")


def _base_result() -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "medical_interpretation": False,
    }


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _strict_date_string(value: Any) -> str:
    if not isinstance(value, str) or _STRICT_DATE.fullmatch(value) is None:
        raise ValueError(f"INVALID_DATE: {value!r}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"INVALID_DATE: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"INVALID_DATE: {value!r}")
    return value


def _sorted_dates(values: Iterable[Any]) -> list[str]:
    return sorted({_strict_date_string(value) for value in values})


def _record_date(value: Any) -> str | None:
    try:
        return _strict_date_string(value)
    except ValueError:
        return None


def _sample_scope(requested_dates: list[str]) -> dict[str, Any]:
    return {
        "requested_days": len(requested_dates),
        "requested_start": requested_dates[0] if requested_dates else None,
        "requested_end": requested_dates[-1] if requested_dates else None,
    }


def normalize_daily_numeric(
    records: Iterable[dict[str, Any]],
    field: str,
    requested_dates: Iterable[str] | None = None,
    allow_zero: bool = False,
) -> dict[str, Any]:
    """Normalize one finite numeric observation per strict calendar date.

    Identical duplicates collapse to one fact.  A date with conflicting values
    is excluded completely.  When ``allow_zero`` is false, zero remains visible
    in ``facts`` but is excluded from ``values`` so absence is never fabricated.
    Negative values follow the same positive-only rule.
    """

    if not isinstance(field, str) or not field:
        raise ValueError("INVALID_FIELD")
    if not isinstance(allow_zero, bool):
        raise ValueError("INVALID_ALLOW_ZERO")

    requested = None if requested_dates is None else _sorted_dates(requested_dates)
    requested_set = None if requested is None else set(requested)
    candidates: dict[str, list[float]] = {}
    excluded_records: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            excluded_records.append({"index": index, "reason": "invalid_record"})
            continue
        raw_day = record.get("date")
        day = _record_date(raw_day)
        if day is None:
            excluded_records.append(
                {"index": index, "date": raw_day, "reason": "invalid_date"}
            )
            continue
        if requested_set is not None and day not in requested_set:
            excluded_records.append(
                {"index": index, "date": day, "reason": "out_of_scope"}
            )
            continue
        raw_value = record.get(field)
        if raw_value is None:
            excluded_records.append(
                {"index": index, "date": day, "reason": "missing_value"}
            )
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            excluded_records.append(
                {"index": index, "date": day, "reason": "non_numeric_value"}
            )
            continue
        value = float(raw_value)
        if not math.isfinite(value):
            excluded_records.append(
                {"index": index, "date": day, "reason": "non_finite_value"}
            )
            continue
        candidates.setdefault(day, []).append(value)

    facts: list[dict[str, Any]] = []
    values: list[dict[str, float | str]] = []
    idempotent_duplicates: list[str] = []
    conflicting_duplicates: list[str] = []
    zero_or_negative_dates: list[str] = []

    for day in sorted(candidates):
        observed_values = candidates[day]
        if any(value != observed_values[0] for value in observed_values[1:]):
            conflicting_duplicates.append(day)
            excluded_records.append({"date": day, "reason": "conflicting_duplicate"})
            continue
        if len(observed_values) > 1:
            idempotent_duplicates.append(day)
        value = observed_values[0]
        if not allow_zero and value <= 0:
            zero_or_negative_dates.append(day)
            facts.append(
                {
                    "date": day,
                    "value": value,
                    "eligible_for_derived": False,
                    "exclusion_reason": "non_positive_value",
                }
            )
            continue
        fact = {"date": day, "value": value}
        facts.append(fact)
        values.append(fact.copy())

    limitations: list[str] = []
    if conflicting_duplicates:
        limitations.append("conflicting_duplicates_excluded")
    if zero_or_negative_dates:
        limitations.append("non_positive_values_retained_as_facts_only")
    if excluded_records:
        limitations.append("invalid_or_out_of_scope_records_excluded")

    result = _base_result()
    result.update(
        {
            "field": field,
            "allow_zero": allow_zero,
            "requested_dates": requested,
            "facts": facts,
            "values": values,
            "fact_days": len(facts),
            "derived_value_days": len(values),
            "idempotent_duplicate_dates": idempotent_duplicates,
            "conflicting_duplicate_dates": conflicting_duplicates,
            "non_positive_fact_dates": zero_or_negative_dates,
            "excluded_records": excluded_records,
            "limitations": limitations,
        }
    )
    return result


def observation_continuity(
    requested_dates: Iterable[str], observed_dates: Iterable[str]
) -> dict[str, Any]:
    """Describe daily observation gaps without imputing missing dates."""

    requested = _sorted_dates(requested_dates)
    observed_all = _sorted_dates(observed_dates)
    requested_set = set(requested)
    observed = [day for day in observed_all if day in requested_set]
    observed_set = set(observed)
    missing = [day for day in requested if day not in observed_set]

    limitations: list[str] = []
    if not requested:
        limitations.append("no_requested_dates")
    if len(observed) != len(observed_all):
        limitations.append("out_of_scope_observed_dates_ignored")
    if any(
        date.fromisoformat(right) - date.fromisoformat(left) != timedelta(days=1)
        for left, right in zip(requested, requested[1:])
    ):
        limitations.append("requested_dates_not_contiguous")

    intervals: list[dict[str, Any]] = []
    if missing:
        start = previous = missing[0]
        for current in missing[1:]:
            if date.fromisoformat(current) - date.fromisoformat(previous) != timedelta(
                days=1
            ):
                intervals.append(
                    {
                        "start": start,
                        "end": previous,
                        "days": (
                            date.fromisoformat(previous) - date.fromisoformat(start)
                        ).days
                        + 1,
                    }
                )
                start = current
            previous = current
        intervals.append(
            {
                "start": start,
                "end": previous,
                "days": (date.fromisoformat(previous) - date.fromisoformat(start)).days
                + 1,
            }
        )

    if not requested:
        status = "no_requested_dates"
    elif not missing:
        status = "complete"
    elif not observed:
        status = "no_observations"
    else:
        status = "partial"

    result = _base_result()
    result.update(
        {
            "status": status,
            **_sample_scope(requested),
            "observed_days": len(observed),
            "missing_days": len(missing),
            "coverage_fraction": len(observed) / len(requested) if requested else None,
            "observed_dates": observed,
            "missing_dates": missing,
            "longest_missing_streak_days": max(
                (interval["days"] for interval in intervals), default=0
            ),
            "current_missing_streak_days": (
                intervals[-1]["days"]
                if intervals and intervals[-1]["end"] == requested[-1]
                else 0
            ),
            "missing_intervals": intervals,
            "limitations": limitations,
        }
    )
    return result


def _trend_result_template(
    field: str,
    requested: list[str],
    epoch_comparable: bool | None,
    epoch_status: str,
    baseline_min_days: int,
    recent_window_days: int,
) -> dict[str, Any]:
    result = _base_result()
    result.update(
        {
            "status": None,
            "field": field,
            **_sample_scope(requested),
            "epoch_comparable": epoch_comparable,
            "epoch_status": epoch_status,
            "baseline_min_days": baseline_min_days,
            "recent_window_days": recent_window_days,
            "historical_sample_days": 0,
            "recent_sample_days": 0,
            "historical_dates": [],
            "recent_dates_expected": [],
            "recent_dates_observed": [],
            "baseline_median": None,
            "baseline_mad": None,
            "recent_median": None,
            "absolute_delta": None,
            "robust_z": None,
            "direction": None,
            "limitations": [],
        }
    )
    return result


def robust_personal_trend(
    records: Iterable[dict[str, Any]],
    field: str,
    requested_dates: Iterable[str],
    epoch_comparable: bool | None,
    epoch_status: str,
    baseline_min_days: int = 21,
    recent_window_days: int = 7,
    allow_zero: bool = False,
) -> dict[str, Any]:
    """Compare a complete recent calendar window with a personal history.

    The result is descriptive.  ``direction`` says only where each recent value
    sits relative to the historical median; it has no favorable or unfavorable
    meaning.  Unknown or crossed device epochs withhold all comparison values.
    """

    if (
        isinstance(baseline_min_days, bool)
        or not isinstance(baseline_min_days, int)
        or baseline_min_days < 1
    ):
        raise ValueError("INVALID_BASELINE_MIN_DAYS")
    if (
        isinstance(recent_window_days, bool)
        or not isinstance(recent_window_days, int)
        or recent_window_days < 1
    ):
        raise ValueError("INVALID_RECENT_WINDOW_DAYS")

    requested = _sorted_dates(requested_dates)
    result = _trend_result_template(
        field,
        requested,
        epoch_comparable,
        epoch_status,
        baseline_min_days,
        recent_window_days,
    )
    normalized = normalize_daily_numeric(
        records, field, requested, allow_zero=allow_zero
    )
    values_by_date = {
        str(item["date"]): float(item["value"]) for item in normalized["values"]
    }

    if not requested:
        result["status"] = "no_requested_dates"
        result["limitations"] = ["no_requested_dates"]
        return result

    requested_end = date.fromisoformat(requested[-1])
    recent_start = requested_end - timedelta(days=recent_window_days - 1)
    expected_recent = [
        (recent_start + timedelta(days=offset)).isoformat()
        for offset in range(recent_window_days)
    ]
    historical_dates = [day for day in requested if day < expected_recent[0]]
    historical_observed = [day for day in historical_dates if day in values_by_date]
    recent_observed = [day for day in expected_recent if day in values_by_date]
    result.update(
        {
            "historical_sample_days": len(historical_observed),
            "recent_sample_days": len(recent_observed),
            "historical_dates": historical_observed,
            "recent_dates_expected": expected_recent,
            "recent_dates_observed": recent_observed,
        }
    )

    limitations = list(normalized["limitations"])
    if epoch_comparable is not True:
        result["status"] = (
            "cross_epoch" if epoch_comparable is False else "epoch_unknown"
        )
        limitations.append(
            "cross_epoch_comparison_withheld"
            if epoch_comparable is False
            else "epoch_comparability_unknown"
        )
        result["limitations"] = _dedupe(limitations)
        return result
    if len(historical_observed) < baseline_min_days:
        result["status"] = "historical_baseline_insufficient"
        limitations.append("historical_baseline_insufficient")
        result["limitations"] = _dedupe(limitations)
        return result
    if len(recent_observed) != recent_window_days:
        result["status"] = "recent_window_incomplete"
        limitations.append("recent_calendar_window_must_be_complete")
        result["limitations"] = _dedupe(limitations)
        return result

    historical_values = [values_by_date[day] for day in historical_observed]
    recent_values = [values_by_date[day] for day in expected_recent]
    baseline_median = float(statistics.median(historical_values))
    baseline_mad = float(
        statistics.median(abs(value - baseline_median) for value in historical_values)
    )
    recent_median = float(statistics.median(recent_values))
    result.update(
        {
            "baseline_median": baseline_median,
            "baseline_mad": baseline_mad,
            "recent_median": recent_median,
            "absolute_delta": recent_median - baseline_median,
        }
    )
    limitations.extend(
        ["descriptive_within_person_only", "direction_has_no_health_valence"]
    )

    if baseline_mad == 0:
        result["status"] = "zero_baseline_mad"
        limitations.append("zero_baseline_mad_prevents_standardization")
        result["limitations"] = _dedupe(limitations)
        return result

    comparisons = {
        1 if value > baseline_median else -1 if value < baseline_median else 0
        for value in recent_values
    }
    if comparisons == {1}:
        direction = "above"
    elif comparisons == {-1}:
        direction = "below"
    elif comparisons == {0}:
        direction = "equal"
    else:
        direction = "mixed"

    result.update(
        {
            "status": "eligible",
            "robust_z": (recent_median - baseline_median) / (1.4826 * baseline_mad),
            "direction": direction,
            "limitations": _dedupe(limitations),
        }
    )
    return result


def _sleep_alias(record: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for field in aliases:
        if record.get(field) is not None:
            return record[field]
    return None


def _parse_aware_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("INVALID_TIMESTAMP")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("TIMEZONE_UNKNOWN")
    return parsed


def _circular_sd_hours(values: list[float]) -> float:
    angles = [value / 24 * 2 * math.pi for value in values]
    center_angle = math.atan2(
        statistics.mean(math.sin(angle) for angle in angles),
        statistics.mean(math.cos(angle) for angle in angles),
    )
    center_hour = (center_angle % (2 * math.pi)) / (2 * math.pi) * 24
    signed_offsets = [(value - center_hour + 12) % 24 - 12 for value in values]
    return float(statistics.stdev(signed_offsets))


def _clock_hour(value: datetime) -> float:
    return (
        value.hour
        + value.minute / 60
        + value.second / 3600
        + value.microsecond / 3_600_000_000
    )


def _sleep_result_template(
    requested: list[str],
    epoch_comparable: bool | None,
    epoch_status: str,
    window_days: int,
    min_valid_nights: int,
) -> dict[str, Any]:
    result = _base_result()
    result.update(
        {
            "status": None,
            **_sample_scope(requested),
            "epoch_comparable": epoch_comparable,
            "epoch_status": epoch_status,
            "window_days": window_days,
            "min_valid_nights": min_valid_nights,
            "window_start": None,
            "window_end": requested[-1] if requested else None,
            "valid_nights": 0,
            "sample_dates": [],
            "excluded_dates": [],
            "duration_status": None,
            "duration_source": None,
            "duration_valid_nights": 0,
            "duration_sample_dates": [],
            "duration_excluded_dates": [],
            "timing_status": None,
            "timing_valid_nights": 0,
            "timing_sample_dates": [],
            "timing_excluded_dates": [],
            "utc_offset_minutes": None,
            "duration_sd_hours": None,
            "bedtime_circular_sd_hours": None,
            "midpoint_circular_sd_hours": None,
            "wake_time_circular_sd_hours": None,
            "limitations": [],
        }
    )
    return result


def sleep_regularity_snapshot(
    records: Iterable[dict[str, Any]],
    requested_dates: Iterable[str],
    epoch_comparable: bool | None,
    epoch_status: str,
    window_days: int = 14,
    min_valid_nights: int = 7,
) -> dict[str, Any]:
    """Describe sleep-duration and local clock-time dispersion.

    Start and end timestamps must be ISO datetimes carrying one shared UTC
    offset.  The function does not infer a missing timezone or a midnight roll.
    Clock-time dispersion uses circular statistics so observations around
    midnight remain adjacent.
    """

    for value, name in (
        (window_days, "WINDOW_DAYS"),
        (min_valid_nights, "MIN_VALID_NIGHTS"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(f"INVALID_{name}")

    requested = _sorted_dates(requested_dates)
    result = _sleep_result_template(
        requested,
        epoch_comparable,
        epoch_status,
        window_days,
        min_valid_nights,
    )
    if not requested:
        result["status"] = "no_requested_dates"
        result["limitations"] = ["no_requested_dates"]
        return result

    window_end = date.fromisoformat(requested[-1])
    window_start = window_end - timedelta(days=window_days - 1)
    target_dates = {
        (window_start + timedelta(days=offset)).isoformat()
        for offset in range(window_days)
    }
    requested_set = set(requested)
    result["window_start"] = window_start.isoformat()

    if epoch_comparable is not True:
        result["status"] = (
            "cross_epoch" if epoch_comparable is False else "epoch_unknown"
        )
        result["limitations"] = [
            "cross_epoch_comparison_withheld"
            if epoch_comparable is False
            else "epoch_comparability_unknown"
        ]
        return result

    record_list = list(records)
    analysis_dates = sorted(target_dates & requested_set)
    duration_normalized = normalize_daily_numeric(
        record_list,
        "sleep_time_seconds",
        analysis_dates,
        allow_zero=False,
    )
    duration_field_supported = any(
        isinstance(record, dict)
        and _record_date(record.get("date")) in set(analysis_dates)
        and record.get("sleep_time_seconds") is not None
        for record in record_list
    )

    supported_pairs = 0
    timezone_unknown = False
    invalid_dates: list[str] = []
    parsed_by_date: dict[str, list[tuple[datetime, datetime]]] = {}

    for record in record_list:
        if not isinstance(record, dict):
            continue
        day = _record_date(record.get("date"))
        if day is None or day not in target_dates or day not in requested_set:
            continue
        start_raw = _sleep_alias(record, _SLEEP_START_FIELDS)
        end_raw = _sleep_alias(record, _SLEEP_END_FIELDS)
        if start_raw is None or end_raw is None:
            continue
        supported_pairs += 1
        try:
            start = _parse_aware_iso(start_raw)
            end = _parse_aware_iso(end_raw)
        except RuntimeError:
            timezone_unknown = True
            invalid_dates.append(day)
            continue
        except ValueError:
            invalid_dates.append(day)
            continue
        if end <= start:
            invalid_dates.append(day)
            continue
        parsed_by_date.setdefault(day, []).append((start, end))

    valid_by_date: dict[str, tuple[datetime, datetime]] = {}
    conflicting_dates: list[str] = []
    for day, pairs in parsed_by_date.items():
        signatures = {(start.isoformat(), end.isoformat()) for start, end in pairs}
        if len(signatures) != 1:
            conflicting_dates.append(day)
            continue
        valid_by_date[day] = pairs[0]

    offsets: set[int] = set()
    for start, end in valid_by_date.values():
        start_offset = start.utcoffset()
        end_offset = end.utcoffset()
        if start_offset is None or end_offset is None:
            timezone_unknown = True
            continue
        offsets.add(int(start_offset.total_seconds()))
        offsets.add(int(end_offset.total_seconds()))

    limitations: list[str] = []
    if invalid_dates:
        limitations.append("invalid_sleep_intervals_excluded")
    if conflicting_dates:
        limitations.append("conflicting_sleep_duplicates_excluded")

    timing_dates = sorted(valid_by_date)
    result["timing_valid_nights"] = len(timing_dates)
    result["timing_sample_dates"] = timing_dates
    result["timing_excluded_dates"] = sorted(set(invalid_dates + conflicting_dates))
    if conflicting_dates:
        result["timing_status"] = "duplicate_conflict"
        limitations.append("conflicting_sleep_timestamps_fail_closed")
    elif supported_pairs == 0:
        result["timing_status"] = "source_not_supported"
        limitations.append("sleep_start_end_not_available")
    elif timezone_unknown:
        result["timing_status"] = "timezone_unknown"
        limitations.append("naive_timestamp_prevents_timing_analysis")
    elif len(offsets) > 1:
        result["timing_status"] = "mixed_utc_offset"
        limitations.append("mixed_utc_offset_prevents_timing_analysis")
    elif len(timing_dates) < min_valid_nights:
        result["timing_status"] = "insufficient_valid_nights"
        limitations.append("timing_valid_nights_insufficient")
    else:
        starts = [valid_by_date[day][0] for day in timing_dates]
        ends = [valid_by_date[day][1] for day in timing_dates]
        midpoints = [start + (end - start) / 2 for start, end in zip(starts, ends)]
        result.update(
            {
                "timing_status": "eligible",
                "utc_offset_minutes": next(iter(offsets)) / 60,
                "bedtime_circular_sd_hours": _circular_sd_hours(
                    [_clock_hour(value) for value in starts]
                ),
                "midpoint_circular_sd_hours": _circular_sd_hours(
                    [_clock_hour(value) for value in midpoints]
                ),
                "wake_time_circular_sd_hours": _circular_sd_hours(
                    [_clock_hour(value) for value in ends]
                ),
            }
        )
        limitations.extend(
            [
                "descriptive_timing_dispersion_only",
                "timing_values_depend_on_source_timezone_accuracy",
            ]
        )

    duration_values = {
        str(item["date"]): float(item["value"])
        for item in duration_normalized["values"]
    }
    duration_conflicts = set(duration_normalized["conflicting_duplicate_dates"])
    interval_duration_values = {
        day: (end - start).total_seconds()
        for day, (start, end) in valid_by_date.items()
        if day not in duration_conflicts
    }
    if duration_conflicts:
        selected_duration_values = {}
        result["duration_source"] = None
    elif len(duration_values) >= min_valid_nights:
        selected_duration_values = duration_values
        result["duration_source"] = "sleep_time_seconds"
    elif len(interval_duration_values) >= min_valid_nights:
        selected_duration_values = interval_duration_values
        result["duration_source"] = "timestamp_interval_seconds"
        if duration_field_supported:
            limitations.append(
                "sleep_time_seconds_insufficient_used_timestamp_intervals"
            )
    else:
        selected_duration_values = {}

    duration_excluded = set(duration_normalized["conflicting_duplicate_dates"])
    duration_excluded.update(duration_normalized["non_positive_fact_dates"])
    if result["duration_source"] == "timestamp_interval_seconds":
        duration_excluded.update(invalid_dates)
        duration_excluded.update(conflicting_dates)
    result["duration_excluded_dates"] = sorted(duration_excluded)
    result["duration_sample_dates"] = sorted(selected_duration_values)
    result["duration_valid_nights"] = len(selected_duration_values)
    if duration_conflicts:
        result["duration_status"] = "duplicate_conflict"
        limitations.append("conflicting_sleep_duration_duplicates_fail_closed")
    elif selected_duration_values:
        durations = [
            selected_duration_values[day] / 3600
            for day in result["duration_sample_dates"]
        ]
        result["duration_status"] = "eligible"
        result["duration_sd_hours"] = float(statistics.stdev(durations))
        limitations.append("descriptive_sleep_duration_dispersion_only")
    elif duration_field_supported or supported_pairs:
        result["duration_status"] = "insufficient_valid_nights"
        limitations.append("duration_valid_nights_insufficient")
    else:
        result["duration_status"] = "source_not_supported"
        limitations.append("sleep_duration_source_not_available")

    duration_eligible = result["duration_status"] == "eligible"
    timing_eligible = result["timing_status"] == "eligible"
    if "duplicate_conflict" in {
        result["duration_status"],
        result["timing_status"],
    }:
        result["status"] = "duplicate_conflict"
    elif duration_eligible and timing_eligible:
        result["status"] = "eligible"
    elif duration_eligible or timing_eligible:
        result["status"] = "partial_available"
    elif result["timing_status"] in {"timezone_unknown", "mixed_utc_offset"}:
        result["status"] = result["timing_status"]
    elif "insufficient_valid_nights" in {
        result["duration_status"],
        result["timing_status"],
    }:
        result["status"] = "insufficient_valid_nights"
    else:
        result["status"] = "source_not_supported"

    result["valid_nights"] = max(
        result["duration_valid_nights"], result["timing_valid_nights"]
    )
    result["sample_dates"] = sorted(
        set(result["duration_sample_dates"]) | set(result["timing_sample_dates"])
    )
    result["excluded_dates"] = sorted(
        set(result["duration_excluded_dates"]) | set(result["timing_excluded_dates"])
    )
    result["limitations"] = _dedupe(duration_normalized["limitations"] + limitations)
    return result


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        average_rank = ((cursor + 1) + end) / 2
        for index, _value in indexed[cursor:end]:
            ranks[index] = average_rank
        cursor = end
    return ranks


def _pearson(values_x: list[float], values_y: list[float]) -> float | None:
    mean_x = statistics.mean(values_x)
    mean_y = statistics.mean(values_y)
    deviations_x = [value - mean_x for value in values_x]
    deviations_y = [value - mean_y for value in values_y]
    sum_squares_x = sum(value * value for value in deviations_x)
    sum_squares_y = sum(value * value for value in deviations_y)
    if sum_squares_x == 0 or sum_squares_y == 0:
        return None
    numerator = sum(
        value_x * value_y
        for value_x, value_y in zip(deviations_x, deviations_y, strict=True)
    )
    return numerator / math.sqrt(sum_squares_x * sum_squares_y)


def lagged_rank_association(
    exposure_records: Iterable[dict[str, Any]],
    exposure_field: str,
    outcome_records: Iterable[dict[str, Any]],
    outcome_field: str,
    requested_dates: Iterable[str],
    *,
    exposure_coverage_semantics: str,
    epoch_comparable: bool | None,
    epoch_status: str,
    min_pairs: int = 28,
    outcome_allow_zero: bool = False,
) -> dict[str, Any]:
    """Return an exploratory Spearman association for exact ``t -> t+1`` pairs.

    Exposure zeroes are eligible only because the caller must explicitly attest
    that every requested date has daily-zero coverage semantics.  Missing dates
    are never backfilled or matched to a nearest observation.
    """

    if isinstance(min_pairs, bool) or not isinstance(min_pairs, int) or min_pairs < 2:
        raise ValueError("INVALID_MIN_PAIRS")
    requested = _sorted_dates(requested_dates)
    result = _base_result()
    result.update(
        {
            "status": None,
            **_sample_scope(requested),
            "exposure_field": exposure_field,
            "outcome_field": outcome_field,
            "lag_calendar_days": 1,
            "join_semantics": "exact_calendar_day",
            "exposure_coverage_semantics": exposure_coverage_semantics,
            "epoch_comparable": epoch_comparable,
            "epoch_status": epoch_status,
            "min_pairs": min_pairs,
            "pair_count": 0,
            "pair_dates": [],
            "spearman_rho": None,
            "causal_interpretation": False,
            "limitations": [],
        }
    )
    if exposure_coverage_semantics != "explicit_daily_zero":
        result["status"] = "load_coverage_unknown"
        result["limitations"] = ["explicit_daily_zero_coverage_required"]
        return result
    if epoch_comparable is not True:
        result["status"] = (
            "cross_epoch" if epoch_comparable is False else "epoch_unknown"
        )
        result["limitations"] = [
            "cross_epoch_association_withheld"
            if epoch_comparable is False
            else "epoch_comparability_unknown"
        ]
        return result
    if not requested:
        result["status"] = "no_requested_dates"
        result["limitations"] = ["no_requested_dates"]
        return result

    exposure = normalize_daily_numeric(
        exposure_records, exposure_field, requested, allow_zero=True
    )
    outcome = normalize_daily_numeric(
        outcome_records,
        outcome_field,
        requested,
        allow_zero=outcome_allow_zero,
    )
    duplicate_conflicts = {
        name: normalized["conflicting_duplicate_dates"]
        for name, normalized in (("exposure", exposure), ("outcome", outcome))
        if normalized["conflicting_duplicate_dates"]
    }
    if duplicate_conflicts:
        result["status"] = "duplicate_conflict"
        result["duplicate_conflicts"] = duplicate_conflicts
        result["limitations"] = _dedupe(
            exposure["limitations"]
            + outcome["limitations"]
            + ["conflicting_duplicates_fail_closed"]
        )
        return result
    exposure_by_date = {
        str(item["date"]): float(item["value"]) for item in exposure["values"]
    }
    outcome_by_date = {
        str(item["date"]): float(item["value"]) for item in outcome["values"]
    }
    requested_set = set(requested)
    pairs: list[tuple[str, str, float, float]] = []
    for exposure_day in requested:
        outcome_day = (date.fromisoformat(exposure_day) + timedelta(days=1)).isoformat()
        if (
            outcome_day in requested_set
            and exposure_day in exposure_by_date
            and outcome_day in outcome_by_date
        ):
            pairs.append(
                (
                    exposure_day,
                    outcome_day,
                    exposure_by_date[exposure_day],
                    outcome_by_date[outcome_day],
                )
            )

    result["pair_count"] = len(pairs)
    result["pair_dates"] = [
        {"exposure_date": exposure_day, "outcome_date": outcome_day}
        for exposure_day, outcome_day, _exposure, _outcome in pairs
    ]
    limitations = _dedupe(exposure["limitations"] + outcome["limitations"])
    if len(pairs) < min_pairs:
        result["status"] = "insufficient_pairs"
        limitations.append("minimum_exact_day_pairs_not_met")
        result["limitations"] = _dedupe(limitations)
        return result

    exposure_values = [pair[2] for pair in pairs]
    outcome_values = [pair[3] for pair in pairs]
    rho = _pearson(_average_ranks(exposure_values), _average_ranks(outcome_values))
    if rho is None:
        result["status"] = "constant_series"
        limitations.append("constant_series_prevents_rank_correlation")
        result["limitations"] = _dedupe(limitations)
        return result

    result.update(
        {
            "status": "eligible",
            "spearman_rho": max(-1.0, min(1.0, rho)),
            "limitations": _dedupe(
                limitations
                + [
                    "exploratory_association_not_causation",
                    "unmeasured_confounders_not_controlled",
                ]
            ),
        }
    )
    return result
