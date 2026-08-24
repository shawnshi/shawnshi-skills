"""Validate point-in-time alpha evidence and compute overfitting-aware metrics."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any

from active_research_contract import (
    base_report,
    canonical_sha256,
    fail_report,
    finite_number,
    normalize_symbol,
    parse_aware_iso,
    positive_integer,
    read_json,
    utc,
    valid_sha256,
    validate_evidence_stamp,
)


SCHEMA_VERSION = "pia_alpha_validation_report_v1"
PACKAGE_SCHEMA_VERSION = "pia_alpha_evidence_v1"
POLICY_SCHEMA_VERSION = "pia_alpha_promotion_policy_v1"
MAX_TRIALS = 1_000
MAX_PBO_SPLITS = 2_000


def _sample_std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def _sharpe(values: list[float], annualization: int) -> float | None:
    deviation = _sample_std(values)
    if deviation <= 0:
        return None
    return statistics.mean(values) / deviation * math.sqrt(annualization)


def _skewness(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    mean = statistics.mean(values)
    deviation = _sample_std(values)
    if deviation <= 0:
        return 0.0
    return sum(((value - mean) / deviation) ** 3 for value in values) / len(values)


def _kurtosis(values: list[float]) -> float:
    if len(values) < 4:
        return 3.0
    mean = statistics.mean(values)
    deviation = _sample_std(values)
    if deviation <= 0:
        return 3.0
    return sum(((value - mean) / deviation) ** 4 for value in values) / len(values)


def _max_drawdown(returns: list[float]) -> float:
    wealth = 1.0
    peak = 1.0
    maximum = 0.0
    for value in returns:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        if peak > 0:
            maximum = max(maximum, (peak - wealth) / peak)
    return maximum


def _deflated_sharpe_probability(
    selected_returns: list[float],
    trial_returns: dict[str, list[float]],
) -> float | None:
    if len(selected_returns) < 3:
        return None
    selected_std = _sample_std(selected_returns)
    if selected_std <= 0:
        return None
    trial_sharpes = []
    for values in trial_returns.values():
        deviation = _sample_std(values)
        if deviation > 0:
            trial_sharpes.append(statistics.mean(values) / deviation)
    if not trial_sharpes:
        return None
    trial_std = _sample_std(trial_sharpes)
    trial_count = len(trial_sharpes)
    if trial_count <= 1 or trial_std <= 0:
        expected_maximum = 0.0
    else:
        gamma = 0.5772156649015329
        normal = NormalDist()
        first = normal.inv_cdf(1.0 - 1.0 / trial_count)
        second = normal.inv_cdf(1.0 - 1.0 / (trial_count * math.e))
        expected_maximum = trial_std * ((1.0 - gamma) * first + gamma * second)
    observed = statistics.mean(selected_returns) / selected_std
    denominator = 1.0 - _skewness(selected_returns) * observed
    denominator += ((_kurtosis(selected_returns) - 1.0) / 4.0) * observed**2
    if denominator <= 0:
        return None
    statistic = (
        (observed - expected_maximum)
        * math.sqrt(len(selected_returns) - 1)
        / math.sqrt(denominator)
    )
    return NormalDist().cdf(statistic)


def _probability_backtest_overfitting(
    trial_returns: dict[str, list[float]],
    block_count: int,
) -> tuple[float | None, int]:
    if len(trial_returns) < 2:
        return None, 0
    observation_count = len(next(iter(trial_returns.values())))
    if observation_count < block_count * 2:
        return None, 0
    blocks: list[list[int]] = [[] for _ in range(block_count)]
    for index in range(observation_count):
        block_index = min(index * block_count // observation_count, block_count - 1)
        blocks[block_index].append(index)
    split_sets = list(itertools.combinations(range(block_count), block_count // 2))
    if len(split_sets) > MAX_PBO_SPLITS:
        return None, len(split_sets)
    failures = 0
    evaluated = 0
    trial_ids = sorted(trial_returns)
    all_blocks = set(range(block_count))
    for selected_blocks in split_sets:
        train_blocks = set(selected_blocks)
        test_blocks = all_blocks - train_blocks
        train_indices = [index for block in train_blocks for index in blocks[block]]
        test_indices = [index for block in test_blocks for index in blocks[block]]
        train_scores: dict[str, float] = {}
        test_scores: dict[str, float] = {}
        for trial_id in trial_ids:
            values = trial_returns[trial_id]
            train = [values[index] for index in train_indices]
            test = [values[index] for index in test_indices]
            train_std = _sample_std(train)
            test_std = _sample_std(test)
            if train_std <= 0 or test_std <= 0:
                continue
            train_scores[trial_id] = statistics.mean(train) / train_std
            test_scores[trial_id] = statistics.mean(test) / test_std
        common = sorted(set(train_scores) & set(test_scores))
        if len(common) < 2:
            continue
        winner = max(common, key=lambda item: (train_scores[item], item))
        ordered = sorted(common, key=lambda item: (test_scores[item], item))
        percentile = (ordered.index(winner) + 0.5) / len(ordered)
        failures += int(percentile <= 0.5)
        evaluated += 1
    return (failures / evaluated if evaluated else None), evaluated


def _validate_policy(policy: Any) -> list[str]:
    if not isinstance(policy, dict):
        return ["promotion policy root must be an object"]
    errors: list[str] = []
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append(f"policy.schema_version must equal {POLICY_SCHEMA_VERSION}")
    required_numbers = {
        "min_net_information_ratio": None,
        "min_deflated_sharpe_probability": (0.0, 1.0),
        "max_probability_backtest_overfitting": (0.0, 1.0),
        "max_drawdown_fraction": (0.0, 1.0),
        "max_annual_turnover": (0.0, None),
        "cost_stress_multiplier": (1.0, None),
        "min_cost_stress_information_ratio": None,
    }
    for field, bounds in required_numbers.items():
        value = finite_number(policy.get(field))
        if value is None:
            errors.append(f"policy.{field} must be a finite JSON number")
            continue
        if bounds is not None:
            lower, upper = bounds
            if value < lower or (upper is not None and value > upper):
                errors.append(f"policy.{field} is outside its allowed range")
    if positive_integer(policy.get("min_oos_observations"), minimum=3) is None:
        errors.append("policy.min_oos_observations must be an integer of at least 3")
    blocks = positive_integer(policy.get("pbo_block_count"), minimum=4)
    if blocks is None or blocks > 12 or blocks % 2:
        errors.append("policy.pbo_block_count must be an even integer from 4 to 12")
    return errors


def _validate_package(package: Any) -> tuple[list[str], dict[str, Any]]:
    if not isinstance(package, dict):
        return ["alpha package root must be an object"], {}
    errors: list[str] = []
    if package.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        errors.append(f"package.schema_version must equal {PACKAGE_SCHEMA_VERSION}")
    if package.get("decision_scope") != "research_only":
        errors.append("package.decision_scope must equal research_only")
    as_of = parse_aware_iso(package.get("as_of"))
    if as_of is None:
        errors.append("package.as_of must be a timezone-aware ISO datetime")
        return errors, {}
    if utc(as_of) > utc(datetime.now().astimezone()):
        errors.append("package.as_of cannot be in the future")
    annualization = positive_integer(package.get("annualization_factor"), minimum=2)
    if annualization is None:
        errors.append("package.annualization_factor must be an integer of at least 2")

    universe = package.get("universe")
    symbols: list[str] = []
    if not isinstance(universe, dict):
        errors.append("package.universe must be an object")
    else:
        raw_symbols = universe.get("symbols")
        if not isinstance(raw_symbols, list) or not raw_symbols:
            errors.append("package.universe.symbols must be a non-empty list")
        else:
            symbols = [normalize_symbol(item) for item in raw_symbols]
            if any(not item for item in symbols) or len(symbols) != len(set(symbols)):
                errors.append("package.universe.symbols must contain unique canonical symbols")
            if symbols != raw_symbols:
                errors.append("package.universe.symbols must use uppercase canonical form")
        for field in ("benchmark", "base_currency"):
            if not isinstance(universe.get(field), str) or not universe[field].strip():
                errors.append(f"package.universe.{field} must be a non-empty string")
        for field in ("survivorship_bias_control", "corporate_action_adjusted"):
            if universe.get(field) is not True:
                errors.append(f"package.universe.{field} must equal true")
        errors.extend(
            validate_evidence_stamp(
                universe.get("point_in_time_evidence"),
                "package.universe.point_in_time_evidence",
                as_of=as_of,
            )
        )

    model = package.get("model")
    trial_ids: list[str] = []
    selected_trial_id = None
    if not isinstance(model, dict):
        errors.append("package.model must be an object")
    else:
        for field in ("model_id", "version", "economic_rationale", "selected_trial_id"):
            if not isinstance(model.get(field), str) or not model[field].strip():
                errors.append(f"package.model.{field} must be a non-empty string")
        selected_trial_id = model.get("selected_trial_id")
        ledger = model.get("trial_ledger")
        if not isinstance(ledger, list) or not ledger:
            errors.append("package.model.trial_ledger must be a non-empty list")
        elif len(ledger) > MAX_TRIALS:
            errors.append(f"package.model.trial_ledger may contain at most {MAX_TRIALS} trials")
        else:
            for index, entry in enumerate(ledger):
                if not isinstance(entry, dict):
                    errors.append(f"package.model.trial_ledger[{index}] must be an object")
                    continue
                trial_id = entry.get("trial_id")
                fingerprint = entry.get("parameter_fingerprint")
                if not isinstance(trial_id, str) or not trial_id.strip():
                    errors.append(f"package.model.trial_ledger[{index}].trial_id is required")
                else:
                    trial_ids.append(trial_id)
                if not valid_sha256(fingerprint):
                    errors.append(
                        f"package.model.trial_ledger[{index}].parameter_fingerprint must be a lowercase SHA-256"
                    )
            if len(trial_ids) != len(set(trial_ids)):
                errors.append("package.model.trial_ledger trial_id values must be unique")
            if selected_trial_id not in trial_ids:
                errors.append("package.model.selected_trial_id must exist in trial_ledger")

    cost_model = package.get("cost_model")
    total_cost_bps = 0.0
    if not isinstance(cost_model, dict):
        errors.append("package.cost_model must be an object")
    else:
        for field in ("commission_bps", "spread_bps", "market_impact_bps", "tax_bps"):
            value = finite_number(cost_model.get(field))
            if value is None or value < 0:
                errors.append(f"package.cost_model.{field} must be non-negative and finite")
            else:
                total_cost_bps += value
        errors.extend(
            validate_evidence_stamp(cost_model.get("evidence"), "package.cost_model.evidence", as_of=as_of)
        )

    observations = package.get("observations")
    parsed_observations: list[dict[str, Any]] = []
    if not isinstance(observations, list) or not observations:
        errors.append("package.observations must be a non-empty list")
    else:
        previous_date: datetime | None = None
        for index, observation in enumerate(observations):
            prefix = f"package.observations[{index}]"
            if not isinstance(observation, dict):
                errors.append(f"{prefix} must be an object")
                continue
            date_value = parse_aware_iso(observation.get("date"))
            if date_value is None:
                errors.append(f"{prefix}.date must be a timezone-aware ISO datetime")
            elif utc(date_value) > utc(as_of):
                errors.append(f"{prefix}.date cannot be after package.as_of")
            elif previous_date is not None and utc(date_value) <= utc(previous_date):
                errors.append("package.observations dates must be strictly increasing")
            if date_value is not None:
                previous_date = date_value
            segment = observation.get("segment")
            if segment not in {"in_sample", "out_of_sample"}:
                errors.append(f"{prefix}.segment must be in_sample or out_of_sample")
            values: dict[str, float] = {}
            for field in ("gross_return", "benchmark_return", "turnover"):
                parsed = finite_number(observation.get(field))
                if parsed is None:
                    errors.append(f"{prefix}.{field} must be a finite JSON number")
                else:
                    values[field] = parsed
            if values.get("gross_return", 0.0) <= -1 or values.get("benchmark_return", 0.0) <= -1:
                errors.append(f"{prefix} returns must be greater than -1")
            if "turnover" in values and not 0 <= values["turnover"] <= 1:
                errors.append(f"{prefix}.turnover must be between 0 and 1")
            parsed_observations.append({**values, "segment": segment})

    trial_matrix = package.get("trial_net_excess_returns")
    parsed_trials: dict[str, list[float]] = {}
    if not isinstance(trial_matrix, dict):
        errors.append("package.trial_net_excess_returns must be an object")
    else:
        if set(trial_matrix) != set(trial_ids):
            errors.append("package.trial_net_excess_returns keys must exactly match trial_ledger")
        for trial_id, raw_values in trial_matrix.items():
            if not isinstance(raw_values, list) or len(raw_values) != len(parsed_observations):
                errors.append(
                    f"package.trial_net_excess_returns.{trial_id} must align one-for-one with observations"
                )
                continue
            values = [finite_number(value) for value in raw_values]
            if any(value is None for value in values):
                errors.append(f"package.trial_net_excess_returns.{trial_id} contains a non-finite value")
            else:
                parsed_trials[trial_id] = [float(value) for value in values if value is not None]

    signals = package.get("signals")
    if not isinstance(signals, list) or not signals:
        errors.append("package.signals must be a non-empty list")
    else:
        signal_symbols: list[str] = []
        for index, signal in enumerate(signals):
            prefix = f"package.signals[{index}]"
            if not isinstance(signal, dict):
                errors.append(f"{prefix} must be an object")
                continue
            symbol = normalize_symbol(signal.get("symbol"))
            signal_symbols.append(symbol)
            if not symbol or signal.get("symbol") != symbol:
                errors.append(f"{prefix}.symbol must use uppercase canonical form")
            for field in ("expected_excess_return_annualized", "expected_return_standard_error"):
                value = finite_number(signal.get(field))
                if value is None or (field.endswith("standard_error") and value < 0):
                    errors.append(f"{prefix}.{field} must be finite and valid")
            for field in ("economic_rationale", "invalidation_condition"):
                if not isinstance(signal.get(field), str) or not signal[field].strip():
                    errors.append(f"{prefix}.{field} must be a non-empty string")
            components = signal.get("components")
            names: list[str] = []
            if not isinstance(components, list) or not components:
                errors.append(f"{prefix}.components must be a non-empty list")
                continue
            for component_index, component in enumerate(components):
                component_prefix = f"{prefix}.components[{component_index}]"
                if not isinstance(component, dict):
                    errors.append(f"{component_prefix} must be an object")
                    continue
                name = component.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append(f"{component_prefix}.name must be a non-empty string")
                else:
                    names.append(name)
                score = finite_number(component.get("score"))
                confidence = finite_number(component.get("confidence"))
                half_life = finite_number(component.get("decay_half_life_days"))
                if score is None or not -5 <= score <= 5:
                    errors.append(f"{component_prefix}.score must be between -5 and 5")
                if confidence is None or not 0 <= confidence <= 1:
                    errors.append(f"{component_prefix}.confidence must be between 0 and 1")
                if half_life is None or half_life <= 0:
                    errors.append(f"{component_prefix}.decay_half_life_days must be positive")
                errors.extend(
                    validate_evidence_stamp(component.get("evidence"), f"{component_prefix}.evidence", as_of=as_of)
                )
            if len(names) != len(set(names)):
                errors.append(f"{prefix}.components names must be unique")
        if signal_symbols != symbols:
            errors.append("package.signals must follow and exactly cover universe.symbols")

    context = {
        "as_of": as_of,
        "annualization": annualization,
        "total_cost_bps": total_cost_bps,
        "observations": parsed_observations,
        "trials": parsed_trials,
        "selected_trial_id": selected_trial_id,
        "symbols": symbols,
    }
    return errors, context


def evaluate_alpha_package(
    package: Any,
    policy: Any,
    *,
    package_sha256: str | None = None,
    policy_sha256: str | None = None,
) -> dict[str, Any]:
    policy_errors = _validate_policy(policy)
    package_errors, context = _validate_package(package)
    errors = package_errors + policy_errors
    if errors:
        return fail_report(SCHEMA_VERSION, "alpha_contract_validation_failed", errors)
    assert isinstance(package, dict) and isinstance(policy, dict)
    observations = context["observations"]
    annualization = int(context["annualization"])
    cost_rate = context["total_cost_bps"] / 10_000.0
    stress_multiplier = float(policy["cost_stress_multiplier"])
    oos = [item for item in observations if item["segment"] == "out_of_sample"]
    if not oos:
        return fail_report(
            SCHEMA_VERSION,
            "out_of_sample_evidence_missing",
            ["at least one out_of_sample observation is required"],
            status="insufficient_evidence",
        )
    net_strategy = [item["gross_return"] - item["turnover"] * cost_rate for item in oos]
    net_excess = [
        item["gross_return"] - item["benchmark_return"] - item["turnover"] * cost_rate
        for item in oos
    ]
    stress_excess = [
        item["gross_return"]
        - item["benchmark_return"]
        - item["turnover"] * cost_rate * stress_multiplier
        for item in oos
    ]
    annual_turnover = statistics.mean(item["turnover"] for item in oos) * annualization
    information_ratio = _sharpe(net_excess, annualization)
    stress_information_ratio = _sharpe(stress_excess, annualization)
    selected_trial = context["trials"][context["selected_trial_id"]]
    selected_oos = [
        value
        for value, observation in zip(selected_trial, observations, strict=True)
        if observation["segment"] == "out_of_sample"
    ]
    trial_oos = {
        trial_id: [
            value
            for value, observation in zip(values, observations, strict=True)
            if observation["segment"] == "out_of_sample"
        ]
        for trial_id, values in context["trials"].items()
    }
    dsr = _deflated_sharpe_probability(selected_oos, trial_oos)
    pbo, split_count = _probability_backtest_overfitting(
        context["trials"], int(policy["pbo_block_count"])
    )
    metrics = {
        "oos_observation_count": len(oos),
        "net_information_ratio": round(information_ratio, 10) if information_ratio is not None else None,
        "cost_stress_information_ratio": (
            round(stress_information_ratio, 10)
            if stress_information_ratio is not None
            else None
        ),
        "deflated_sharpe_probability": round(dsr, 10) if dsr is not None else None,
        "probability_backtest_overfitting": round(pbo, 10) if pbo is not None else None,
        "pbo_split_count": split_count,
        "maximum_drawdown_fraction": round(_max_drawdown(net_strategy), 10),
        "annual_turnover": round(annual_turnover, 10),
        "average_net_excess_return": round(statistics.mean(net_excess), 10),
        "positive_net_excess_hit_rate": round(
            sum(value > 0 for value in net_excess) / len(net_excess), 10
        ),
        "cost_bps_per_unit_turnover": round(context["total_cost_bps"], 10),
        "cost_stress_multiplier": stress_multiplier,
    }
    checks = {
        "oos_observations": len(oos) >= int(policy["min_oos_observations"]),
        "net_information_ratio": information_ratio is not None
        and information_ratio >= float(policy["min_net_information_ratio"]),
        "cost_stress_information_ratio": stress_information_ratio is not None
        and stress_information_ratio >= float(policy["min_cost_stress_information_ratio"]),
        "deflated_sharpe_probability": dsr is not None
        and dsr >= float(policy["min_deflated_sharpe_probability"]),
        "probability_backtest_overfitting": pbo is not None
        and pbo <= float(policy["max_probability_backtest_overfitting"]),
        "maximum_drawdown": metrics["maximum_drawdown_fraction"]
        <= float(policy["max_drawdown_fraction"]),
        "annual_turnover": annual_turnover <= float(policy["max_annual_turnover"]),
    }
    eligible = all(checks.values())
    report = base_report(SCHEMA_VERSION)
    report.update(
        {
            "status": "complete" if eligible else "incomplete",
            "detail_status": (
                "eligible_for_active_research"
                if eligible
                else "experimental_only_thresholds_not_met"
            ),
            "promotion_status": (
                "eligible_for_active_research" if eligible else "experimental_only"
            ),
            "formal_use_allowed": eligible,
            "alpha_package_sha256": package_sha256,
            "promotion_policy_sha256": policy_sha256,
            "model_id": package["model"]["model_id"],
            "selected_trial_id": package["model"]["selected_trial_id"],
            "trial_count": len(package["model"]["trial_ledger"]),
            "symbols": context["symbols"],
            "metrics": metrics,
            "promotion_checks": checks,
            "fail_closed": {"enforced": True, "triggered": not eligible},
            "limitations": [
                "Eligibility is an active-research gate, not evidence that future excess returns will occur.",
                "The report does not authorize target weights, orders, leverage, or execution.",
            ],
        }
    )
    return report


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps(fail_report(SCHEMA_VERSION, "argument_error", [message]), indent=2))
        raise SystemExit(2)


def main() -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("alpha_package")
    parser.add_argument("--policy-file", required=True)
    args = parser.parse_args()
    try:
        package = read_json(args.alpha_package, "alpha_package")
        policy = read_json(args.policy_file, "promotion_policy")
        report = evaluate_alpha_package(
            package,
            policy,
            package_sha256=canonical_sha256(args.alpha_package),
            policy_sha256=canonical_sha256(args.policy_file),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = fail_report(SCHEMA_VERSION, "input_read_failed", [str(exc)])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
