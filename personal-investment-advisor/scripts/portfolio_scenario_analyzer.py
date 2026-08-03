import argparse
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PORTFOLIO_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "references" / "portfolio_schema.json"
)
WEIGHT_TOLERANCE = 1e-6
MATRIX_TOLERANCE = 1e-9
SUPPORTED_CONTRACT_VERSIONS = {"1.0", "2.0"}


class DuplicateJsonKeyError(ValueError):
    pass


class CliUsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def _strict_number(value: Any, field: str, errors: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(
            f"{field} must be finite JSON number; bool and numeric string are prohibited"
        )
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        errors.append(f"{field} must be finite")
        return None
    return parsed


def _non_empty_string(value: Any, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return None
    return value.strip()


def _currency(value: Any, field: str, errors: list[str]) -> str | None:
    normalized = _non_empty_string(value, field, errors)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if not re.fullmatch(r"[A-Z]{3}", normalized):
        errors.append(f"{field} must be a three-letter currency code")
        return None
    return normalized


def _symbol(value: Any, field: str, errors: list[str]) -> str | None:
    normalized = _non_empty_string(value, field, errors)
    return normalized.upper() if normalized is not None else None


def _iso_date_or_datetime(value: Any, field: str, errors: list[str]) -> str | None:
    normalized = _non_empty_string(value, field, errors)
    if normalized is None:
        return None
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be an ISO date or datetime string")
        return None
    return normalized


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _normalize_symbol_mapping(
    value: Any,
    field: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return None
    normalized: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = _symbol(raw_key, f"{field} key", errors)
        if key is None:
            continue
        if key in normalized:
            errors.append(f"{field} contains duplicate normalized symbol: {key}")
            continue
        normalized[key] = item
    return normalized


def _normalize_symbol_list(
    value: Any,
    field: str,
    errors: list[str],
) -> list[str] | None:
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw_symbol in enumerate(value):
        symbol = _symbol(raw_symbol, f"{field}[{index}]", errors)
        if symbol is None:
            continue
        if symbol in seen:
            errors.append(f"{field} contains duplicate symbol: {symbol}")
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _result_shell(
    *,
    status: str,
    detail_status: str,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "valid": False,
        "status": status,
        "detail_status": detail_status,
        "scenario_contract_version": None,
        "base_currency": None,
        "weight_sum": 0.0,
        "weight_tolerance": WEIGHT_TOLERANCE,
        "inactive_zero_quantity_symbols": [],
        "currency_exposure": {},
        "weight_snapshot": None,
        "scenario_results": [],
        "constraint_violations": [],
        "bucket_policy_results": [],
        "transaction_cost_estimate": None,
        "transaction_cost_summary": {
            "status": "invalid",
            "detail_status": "invalid_input",
            "by_scenario": {},
            "missing_scenarios": [],
        },
        "risk_diagnostics": {
            "status": "not_calculated",
            "detail_status": "invalid_input",
        },
        "data_gaps": [],
        "model_boundary": (
            "user-supplied scenarios only; no return forecast, optimizer, risk parity, "
            "target weight, or trade action"
        ),
        "errors": _unique(errors),
        "warnings": [],
    }


def _weight_snapshot(
    value: Any,
    version: str,
    active_positions: dict[str, dict[str, Any]],
    weights: dict[str, float],
    base_currency: str | None,
    errors: list[str],
) -> dict[str, Any] | None:
    """Validate that v2 weights are tied to a sourced base-currency snapshot."""
    if version != "2.0":
        if value is not None:
            errors.append("weight_snapshot requires scenario_contract_version 2.0")
        return None
    if not isinstance(value, dict):
        errors.append("weight_snapshot is required and must be an object for v2")
        return None

    as_of = _iso_date_or_datetime(value.get("as_of"), "weight_snapshot.as_of", errors)
    source = _non_empty_string(
        value.get("source"), "weight_snapshot.source", errors
    )
    source_locator = _non_empty_string(
        value.get("source_locator"), "weight_snapshot.source_locator", errors
    )
    valuation_basis = _non_empty_string(
        value.get("valuation_basis"), "weight_snapshot.valuation_basis", errors
    )
    if (
        valuation_basis is not None
        and valuation_basis != "base_currency_market_value"
    ):
        errors.append(
            "weight_snapshot.valuation_basis must equal base_currency_market_value"
        )

    market_values = _normalize_symbol_mapping(
        value.get("market_values_base_currency"),
        "weight_snapshot.market_values_base_currency",
        errors,
    )
    active_symbols = set(active_positions)
    parsed_values: dict[str, float] = {}
    if market_values is not None:
        missing = sorted(active_symbols - set(market_values))
        extra = sorted(set(market_values) - active_symbols)
        if missing:
            errors.append(
                "weight_snapshot.market_values_base_currency missing active symbols: "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "weight_snapshot.market_values_base_currency contains non-active symbols: "
                + ", ".join(extra)
            )
        for symbol, raw_value in market_values.items():
            parsed = _strict_number(
                raw_value,
                f"weight_snapshot.market_values_base_currency.{symbol}",
                errors,
            )
            if parsed is not None and parsed <= 0:
                errors.append(
                    f"weight_snapshot.market_values_base_currency.{symbol} must be positive"
                )
            elif parsed is not None:
                parsed_values[symbol] = parsed

    total_market_value = sum(parsed_values.values())
    reconciled_weights: dict[str, float] = {}
    if set(parsed_values) == active_symbols and total_market_value > 0:
        for symbol in sorted(active_symbols):
            snapshot_weight = parsed_values[symbol] / total_market_value
            reconciled_weights[symbol] = round(snapshot_weight, 10)
            if abs(snapshot_weight - weights[symbol]) > WEIGHT_TOLERANCE:
                errors.append(
                    f"weight_snapshot weight mismatch for {symbol}: "
                    f"portfolio={weights[symbol]:.10f}, snapshot={snapshot_weight:.10f}"
                )

    foreign_currencies = sorted(
        {
            position["currency"]
            for position in active_positions.values()
            if base_currency is not None and position["currency"] != base_currency
        }
    )
    fx_provenance: dict[str, Any] | None = None
    if foreign_currencies:
        fx_as_of = _iso_date_or_datetime(
            value.get("fx_as_of"), "weight_snapshot.fx_as_of", errors
        )
        fx_source = _non_empty_string(
            value.get("fx_source"), "weight_snapshot.fx_source", errors
        )
        fx_source_locator = _non_empty_string(
            value.get("fx_source_locator"),
            "weight_snapshot.fx_source_locator",
            errors,
        )
        raw_fx_rates = value.get("fx_rates")
        if not isinstance(raw_fx_rates, dict):
            errors.append("weight_snapshot.fx_rates must be an object")
            raw_fx_rates = {}
        normalized_fx_rates: dict[str, float] = {}
        for raw_pair, raw_rate in raw_fx_rates.items():
            pair = _non_empty_string(raw_pair, "weight_snapshot.fx_rates key", errors)
            if pair is None:
                continue
            pair = pair.upper()
            if pair in normalized_fx_rates:
                errors.append(
                    "weight_snapshot.fx_rates contains duplicate normalized pair: "
                    + pair
                )
                continue
            rate = _strict_number(
                raw_rate, f"weight_snapshot.fx_rates.{pair}", errors
            )
            if rate is not None and rate <= 0:
                errors.append(f"weight_snapshot.fx_rates.{pair} must be positive")
            elif rate is not None:
                normalized_fx_rates[pair] = rate
        required_pairs = {
            f"{currency}/{base_currency}" for currency in foreign_currencies
        }
        missing_pairs = sorted(required_pairs - set(normalized_fx_rates))
        extra_pairs = sorted(set(normalized_fx_rates) - required_pairs)
        if missing_pairs:
            errors.append(
                "weight_snapshot.fx_rates missing required pairs: "
                + ", ".join(missing_pairs)
            )
        if extra_pairs:
            errors.append(
                "weight_snapshot.fx_rates contains unused pairs: "
                + ", ".join(extra_pairs)
            )
        if (
            fx_as_of is not None
            and fx_source is not None
            and fx_source_locator is not None
            and not missing_pairs
            and not extra_pairs
        ):
            fx_provenance = {
                "as_of": fx_as_of,
                "source": fx_source,
                "source_locator": fx_source_locator,
                "rates": {
                    pair: normalized_fx_rates[pair]
                    for pair in sorted(normalized_fx_rates)
                },
            }

    return {
        "as_of": as_of,
        "source": source,
        "source_locator": source_locator,
        "valuation_basis": valuation_basis,
        "market_values_base_currency": {
            symbol: parsed_values[symbol] for symbol in sorted(parsed_values)
        },
        "total_market_value_base_currency": (
            round(total_market_value, 8) if total_market_value > 0 else None
        ),
        "reconciled_weights": reconciled_weights,
        "fx_provenance": fx_provenance,
    }


def _legacy_transaction_cost(
    assumptions: dict[str, Any], errors: list[str]
) -> float | None:
    has_bps = "transaction_cost_bps" in assumptions
    has_turnover = "assumed_turnover" in assumptions
    if has_bps != has_turnover:
        errors.append(
            "transaction_cost_bps and assumed_turnover must either both be provided or both be omitted"
        )
        return None
    if not has_bps:
        return None
    bps = _strict_number(
        assumptions.get("transaction_cost_bps"), "transaction_cost_bps", errors
    )
    turnover = _strict_number(
        assumptions.get("assumed_turnover"), "assumed_turnover", errors
    )
    if bps is not None and bps < 0:
        errors.append("transaction_cost_bps cannot be negative")
    if turnover is not None and turnover < 0:
        errors.append("assumed_turnover cannot be negative")
    if bps is None or turnover is None or bps < 0 or turnover < 0:
        return None
    return bps / 10000 * turnover


def _cost_entry(
    value: Any,
    field: str,
    errors: list[str],
) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return None
    bps = _strict_number(
        value.get("transaction_cost_bps"),
        f"{field}.transaction_cost_bps",
        errors,
    )
    turnover = _strict_number(
        value.get("assumed_turnover"),
        f"{field}.assumed_turnover",
        errors,
    )
    if bps is not None and bps < 0:
        errors.append(f"{field}.transaction_cost_bps cannot be negative")
    if turnover is not None and turnover < 0:
        errors.append(f"{field}.assumed_turnover cannot be negative")
    if bps is None or turnover is None or bps < 0 or turnover < 0:
        return None
    return bps, turnover


def _scenario_costs(
    scenario: dict[str, Any],
    scenario_index: int,
    active_symbols: set[str],
    weights: dict[str, float],
    version: str,
    legacy_cost: float | None,
    legacy_cost_configured: bool,
    errors: list[str],
) -> tuple[float | None, dict[str, float], str]:
    cost_model = scenario.get("cost_model")
    if cost_model is None:
        if legacy_cost is None:
            return None, {}, "not_modeled"
        return (
            legacy_cost,
            {
                symbol: round(weight * legacy_cost, 8)
                for symbol, weight in weights.items()
            },
            "legacy_global",
        )
    prefix = f"scenarios[{scenario_index}].cost_model"
    if version != "2.0":
        errors.append(f"{prefix} requires scenario_contract_version 2.0")
        return None, {}, "invalid"
    if legacy_cost_configured:
        errors.append(
            f"{prefix} cannot be combined with top-level transaction_cost_bps and assumed_turnover"
        )
    if not isinstance(cost_model, dict):
        errors.append(f"{prefix} must be an object")
        return None, {}, "invalid"
    _non_empty_string(cost_model.get("source"), f"{prefix}.source", errors)
    _non_empty_string(
        cost_model.get("source_locator"), f"{prefix}.source_locator", errors
    )
    _iso_date_or_datetime(cost_model.get("as_of"), f"{prefix}.as_of", errors)
    default_entry = None
    if "default" in cost_model:
        default_entry = _cost_entry(cost_model.get("default"), f"{prefix}.default", errors)
    raw_by_symbol = cost_model.get("by_symbol", {})
    by_symbol = _normalize_symbol_mapping(
        raw_by_symbol, f"{prefix}.by_symbol", errors
    )
    if by_symbol is None:
        by_symbol = {}
    extra_symbols = sorted(set(by_symbol) - active_symbols)
    if extra_symbols:
        errors.append(
            f"{prefix}.by_symbol contains non-active symbols: {', '.join(extra_symbols)}"
        )
    if default_entry is None:
        missing_symbols = sorted(active_symbols - set(by_symbol))
        if missing_symbols:
            errors.append(
                f"{prefix} has no default and is missing active symbols: {', '.join(missing_symbols)}"
            )
    parsed_by_symbol: dict[str, tuple[float, float]] = {}
    for symbol, entry in by_symbol.items():
        parsed = _cost_entry(entry, f"{prefix}.by_symbol.{symbol}", errors)
        if parsed is not None:
            parsed_by_symbol[symbol] = parsed
    contributions: dict[str, float] = {}
    for symbol in sorted(active_symbols):
        entry = parsed_by_symbol.get(symbol, default_entry)
        if entry is None:
            continue
        bps, turnover = entry
        contributions[symbol] = round(
            weights[symbol] * turnover * bps / 10000,
            8,
        )
    if set(contributions) != active_symbols:
        return None, contributions, "invalid"
    return sum(contributions.values()), contributions, "position_level"


def _parse_fx_returns(
    scenario: dict[str, Any],
    scenario_index: int,
    required_pairs: set[str],
    errors: list[str],
) -> dict[str, float]:
    prefix = f"scenarios[{scenario_index}].fx_returns"
    raw_fx = scenario.get("fx_returns", {})
    if not isinstance(raw_fx, dict):
        errors.append(f"{prefix} must be an object")
        return {}
    normalized: dict[str, Any] = {}
    for raw_pair, entry in raw_fx.items():
        pair = _non_empty_string(raw_pair, f"{prefix} key", errors)
        if pair is None:
            continue
        pair = pair.upper()
        if pair in normalized:
            errors.append(f"{prefix} contains duplicate normalized pair: {pair}")
            continue
        normalized[pair] = entry
    missing = sorted(required_pairs - set(normalized))
    extra = sorted(set(normalized) - required_pairs)
    if missing:
        errors.append(f"{prefix} missing required pairs: {', '.join(missing)}")
    if extra:
        errors.append(f"{prefix} contains unused pairs: {', '.join(extra)}")
    parsed: dict[str, float] = {}
    for pair, entry in normalized.items():
        entry_prefix = f"{prefix}.{pair}"
        if not isinstance(entry, dict):
            errors.append(f"{entry_prefix} must be an object")
            continue
        fx_return = _strict_number(entry.get("return"), f"{entry_prefix}.return", errors)
        if fx_return is not None and fx_return <= -1:
            errors.append(f"{entry_prefix}.return must be greater than -1")
        _iso_date_or_datetime(entry.get("as_of"), f"{entry_prefix}.as_of", errors)
        _non_empty_string(entry.get("source"), f"{entry_prefix}.source", errors)
        _non_empty_string(
            entry.get("source_locator"), f"{entry_prefix}.source_locator", errors
        )
        if fx_return is not None and fx_return > -1:
            parsed[pair] = fx_return
    return parsed


def _scenario_returns(
    scenario: dict[str, Any],
    scenario_index: int,
    version: str,
    base_currency: str,
    positions: dict[str, dict[str, Any]],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    prefix = f"scenarios[{scenario_index}].asset_returns"
    returns = _normalize_symbol_mapping(scenario.get("asset_returns"), prefix, errors)
    if returns is None:
        return {}
    active_symbols = set(positions)
    missing = sorted(active_symbols - set(returns))
    extra = sorted(set(returns) - active_symbols)
    if missing:
        errors.append(f"{prefix} missing explicit returns for: {', '.join(missing)}")
    if extra:
        errors.append(f"{prefix} contains non-active symbols: {', '.join(extra)}")

    decompositions: dict[str, dict[str, Any]] = {}
    required_pairs: set[str] = set()
    pending_local: dict[str, tuple[float, str]] = {}
    for symbol, raw_return in returns.items():
        if symbol not in positions:
            continue
        if isinstance(raw_return, (int, float)) and not isinstance(raw_return, bool):
            base_return = _strict_number(raw_return, f"{prefix}.{symbol}", errors)
            if base_return is not None and base_return < -1:
                errors.append(f"{prefix}.{symbol} must be at least -1")
            if base_return is not None and base_return >= -1:
                decompositions[symbol] = {
                    "basis": "base_currency_total_return",
                    "local_return": None,
                    "fx_return": None,
                    "base_currency_return": base_return,
                }
            continue
        if not isinstance(raw_return, dict):
            _strict_number(raw_return, f"{prefix}.{symbol}", errors)
            continue
        if version != "2.0":
            errors.append(
                f"{prefix}.{symbol} object form requires scenario_contract_version 2.0"
            )
            continue
        basis = _non_empty_string(
            raw_return.get("basis"), f"{prefix}.{symbol}.basis", errors
        )
        if basis != "local_total_return":
            errors.append(
                f"{prefix}.{symbol}.basis must equal local_total_return"
            )
        local_return = _strict_number(
            raw_return.get("return"), f"{prefix}.{symbol}.return", errors
        )
        if local_return is not None and local_return < -1:
            errors.append(f"{prefix}.{symbol}.return must be at least -1")
        currency = _currency(
            raw_return.get("currency"), f"{prefix}.{symbol}.currency", errors
        )
        position_currency = positions[symbol]["currency"]
        if currency is not None and currency != position_currency:
            errors.append(
                f"{prefix}.{symbol}.currency must match position currency {position_currency}"
            )
        if local_return is None or local_return < -1 or currency is None:
            continue
        if currency == base_currency:
            if raw_return.get("fx_pair") not in (None, ""):
                errors.append(
                    f"{prefix}.{symbol}.fx_pair must be omitted for base-currency assets"
                )
            decompositions[symbol] = {
                "basis": "local_total_return",
                "local_return": local_return,
                "fx_return": 0.0,
                "base_currency_return": local_return,
            }
            continue
        fx_pair = _non_empty_string(
            raw_return.get("fx_pair"), f"{prefix}.{symbol}.fx_pair", errors
        )
        expected_pair = f"{currency}/{base_currency}"
        if fx_pair is not None and fx_pair.upper() != expected_pair:
            errors.append(
                f"{prefix}.{symbol}.fx_pair must equal {expected_pair}"
            )
        if fx_pair is not None and fx_pair.upper() == expected_pair:
            required_pairs.add(expected_pair)
            pending_local[symbol] = (local_return, expected_pair)

    fx_returns = _parse_fx_returns(
        scenario,
        scenario_index,
        required_pairs,
        errors,
    )
    for symbol, (local_return, pair) in pending_local.items():
        if pair not in fx_returns:
            continue
        fx_return = fx_returns[pair]
        decompositions[symbol] = {
            "basis": "local_total_return",
            "local_return": local_return,
            "fx_return": fx_return,
            "base_currency_return": round(
                (1 + local_return) * (1 + fx_return) - 1,
                12,
            ),
        }
    return decompositions


def _bucket_policy_results(
    raw_policies: Any,
    version: str,
    weights: dict[str, float],
    errors: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if raw_policies is None:
        return [], []
    if version != "2.0":
        errors.append(
            "constraints.bucket_policies requires scenario_contract_version 2.0"
        )
        return [], []
    if not isinstance(raw_policies, list):
        errors.append("constraints.bucket_policies must be a list")
        return [], []
    active_symbols = set(weights)
    seen_policy_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for policy_index, policy in enumerate(raw_policies):
        prefix = f"constraints.bucket_policies[{policy_index}]"
        if not isinstance(policy, dict):
            errors.append(f"{prefix} must be an object")
            continue
        policy_id = _non_empty_string(policy.get("id"), f"{prefix}.id", errors)
        if policy_id is not None:
            if policy_id in seen_policy_ids:
                errors.append(f"duplicate bucket policy id: {policy_id}")
            seen_policy_ids.add(policy_id)
        _non_empty_string(policy.get("source"), f"{prefix}.source", errors)
        _non_empty_string(
            policy.get("source_locator"), f"{prefix}.source_locator", errors
        )
        scope = _normalize_symbol_list(
            policy.get("scope_symbols"), f"{prefix}.scope_symbols", errors
        )
        if scope is None:
            scope = []
        excluded = _normalize_symbol_mapping(
            policy.get("excluded_symbols", {}),
            f"{prefix}.excluded_symbols",
            errors,
        )
        if excluded is None:
            excluded = {}
        for symbol, reason in excluded.items():
            _non_empty_string(
                reason, f"{prefix}.excluded_symbols.{symbol}", errors
            )
        scope_set = set(scope)
        excluded_set = set(excluded)
        overlap = sorted(scope_set & excluded_set)
        if overlap:
            errors.append(
                f"{prefix} symbols cannot be both scoped and excluded: {', '.join(overlap)}"
            )
        extra = sorted((scope_set | excluded_set) - active_symbols)
        uncovered = sorted(active_symbols - scope_set - excluded_set)
        if extra:
            errors.append(f"{prefix} references non-active symbols: {', '.join(extra)}")
        if uncovered:
            errors.append(
                f"{prefix} leaves active symbols unclassified: {', '.join(uncovered)}"
            )
        tolerance = _strict_number(
            policy.get("tolerance"), f"{prefix}.tolerance", errors
        )
        if tolerance is not None and not (0 <= tolerance <= 0.1):
            errors.append(f"{prefix}.tolerance must be from 0 to 0.1")
        buckets = policy.get("buckets")
        if not isinstance(buckets, list) or not buckets:
            errors.append(f"{prefix}.buckets must be a non-empty list")
            continue
        bucket_rows: list[dict[str, Any]] = []
        covered: set[str] = set()
        seen_bucket_ids: set[str] = set()
        all_target_rules = True
        target_sum = 0.0
        scope_weight = sum(weights.get(symbol, 0.0) for symbol in scope)
        if scope_weight <= 0:
            errors.append(f"{prefix}.scope_symbols must have positive total weight")
        for bucket_index, bucket in enumerate(buckets):
            bucket_prefix = f"{prefix}.buckets[{bucket_index}]"
            if not isinstance(bucket, dict):
                errors.append(f"{bucket_prefix} must be an object")
                continue
            bucket_id = _non_empty_string(
                bucket.get("id"), f"{bucket_prefix}.id", errors
            )
            if bucket_id is not None:
                if bucket_id in seen_bucket_ids:
                    errors.append(f"{prefix} contains duplicate bucket id: {bucket_id}")
                seen_bucket_ids.add(bucket_id)
            symbols = _normalize_symbol_list(
                bucket.get("symbols"), f"{bucket_prefix}.symbols", errors
            )
            if symbols is None:
                symbols = []
            symbol_set = set(symbols)
            outside_scope = sorted(symbol_set - scope_set)
            duplicate_members = sorted(symbol_set & covered)
            if outside_scope:
                errors.append(
                    f"{bucket_prefix} contains symbols outside policy scope: {', '.join(outside_scope)}"
                )
            if duplicate_members:
                errors.append(
                    f"{bucket_prefix} overlaps earlier buckets: {', '.join(duplicate_members)}"
                )
            covered.update(symbol_set)

            has_target = "target_weight" in bucket
            has_bounds = "min_weight" in bucket or "max_weight" in bucket
            if has_target == has_bounds:
                errors.append(
                    f"{bucket_prefix} requires either target_weight or min_weight/max_weight"
                )
            target = None
            minimum = None
            maximum = None
            if has_target:
                target = _strict_number(
                    bucket.get("target_weight"),
                    f"{bucket_prefix}.target_weight",
                    errors,
                )
                if target is not None and not (0 <= target <= 1):
                    errors.append(
                        f"{bucket_prefix}.target_weight must be from 0 to 1"
                    )
                if target is not None:
                    target_sum += target
            else:
                all_target_rules = False
                if "min_weight" in bucket:
                    minimum = _strict_number(
                        bucket.get("min_weight"),
                        f"{bucket_prefix}.min_weight",
                        errors,
                    )
                    if minimum is not None and not (0 <= minimum <= 1):
                        errors.append(
                            f"{bucket_prefix}.min_weight must be from 0 to 1"
                        )
                if "max_weight" in bucket:
                    maximum = _strict_number(
                        bucket.get("max_weight"),
                        f"{bucket_prefix}.max_weight",
                        errors,
                    )
                    if maximum is not None and not (0 <= maximum <= 1):
                        errors.append(
                            f"{bucket_prefix}.max_weight must be from 0 to 1"
                        )
                if minimum is not None and maximum is not None and minimum > maximum:
                    errors.append(
                        f"{bucket_prefix}.min_weight cannot exceed max_weight"
                    )
            absolute_weight = sum(weights.get(symbol, 0.0) for symbol in symbols)
            within_scope = absolute_weight / scope_weight if scope_weight > 0 else None
            row = {
                "id": bucket_id,
                "symbols": symbols,
                "absolute_portfolio_weight": round(absolute_weight, 8),
                "weight_within_scope": (
                    round(within_scope, 8) if within_scope is not None else None
                ),
                "target_weight": target,
                "min_weight": minimum,
                "max_weight": maximum,
                "deviation": (
                    round(within_scope - target, 8)
                    if within_scope is not None and target is not None
                    else None
                ),
            }
            bucket_rows.append(row)
            if within_scope is not None and tolerance is not None and bucket_id is not None:
                if target is not None and abs(within_scope - target) > tolerance:
                    violations.append(
                        {
                            "type": "bucket_target",
                            "policy_id": policy_id,
                            "bucket_id": bucket_id,
                            "value": round(within_scope, 8),
                            "target": target,
                            "tolerance": tolerance,
                        }
                    )
                if minimum is not None and within_scope < minimum - tolerance:
                    violations.append(
                        {
                            "type": "bucket_minimum",
                            "policy_id": policy_id,
                            "bucket_id": bucket_id,
                            "value": round(within_scope, 8),
                            "limit": minimum,
                            "tolerance": tolerance,
                        }
                    )
                if maximum is not None and within_scope > maximum + tolerance:
                    violations.append(
                        {
                            "type": "bucket_maximum",
                            "policy_id": policy_id,
                            "bucket_id": bucket_id,
                            "value": round(within_scope, 8),
                            "limit": maximum,
                            "tolerance": tolerance,
                        }
                    )
        missing_from_buckets = sorted(scope_set - covered)
        if missing_from_buckets:
            errors.append(
                f"{prefix}.buckets do not cover scope symbols: {', '.join(missing_from_buckets)}"
            )
        if all_target_rules and abs(target_sum - 1.0) > WEIGHT_TOLERANCE:
            errors.append(
                f"{prefix} target weights must sum to 1.0; got {target_sum:.8f}"
            )
        results.append(
            {
                "id": policy_id,
                "scope_weight": round(scope_weight, 8),
                "scope_symbols": scope,
                "excluded_symbols": excluded,
                "uncovered_active_symbols": uncovered,
                "tolerance": tolerance,
                "buckets": bucket_rows,
            }
        )
    return results, violations


def _is_positive_semidefinite(matrix: list[list[float]]) -> bool:
    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            value = matrix[row][column] - sum(
                lower[row][k] * lower[column][k] for k in range(column)
            )
            if row == column:
                if value < -MATRIX_TOLERANCE:
                    return False
                lower[row][column] = math.sqrt(max(value, 0.0))
            elif abs(lower[column][column]) <= MATRIX_TOLERANCE:
                if abs(value) > MATRIX_TOLERANCE:
                    return False
            else:
                lower[row][column] = value / lower[column][column]
    return True


def _risk_diagnostics(
    risk_model: Any,
    version: str,
    weights: dict[str, float],
    errors: list[str],
) -> dict[str, Any]:
    if risk_model is None:
        return {
            "status": "not_calculated",
            "detail_status": "insufficient_data",
            "data_gaps": [
                "explicit volatility and correlation model was not supplied"
            ],
            "model_boundary": "not risk parity and not an optimizer",
        }
    if version != "2.0":
        errors.append("risk_model requires scenario_contract_version 2.0")
        return {"status": "invalid", "detail_status": "contract_validation_failed"}
    if not isinstance(risk_model, dict):
        errors.append("risk_model must be an object")
        return {"status": "invalid", "detail_status": "contract_validation_failed"}
    if risk_model.get("type") != "explicit_volatility_correlation":
        errors.append("risk_model.type must equal explicit_volatility_correlation")
    if risk_model.get("units") != "decimal_annualized":
        errors.append("risk_model.units must equal decimal_annualized")
    as_of = _iso_date_or_datetime(risk_model.get("as_of"), "risk_model.as_of", errors)
    source = _non_empty_string(risk_model.get("source"), "risk_model.source", errors)
    source_locator = _non_empty_string(
        risk_model.get("source_locator"), "risk_model.source_locator", errors
    )
    observation_window = _non_empty_string(
        risk_model.get("observation_window"),
        "risk_model.observation_window",
        errors,
    )
    frequency = _non_empty_string(
        risk_model.get("frequency"), "risk_model.frequency", errors
    )
    scope = _normalize_symbol_list(
        risk_model.get("scope_symbols"), "risk_model.scope_symbols", errors
    )
    zero_symbols = _normalize_symbol_list(
        risk_model.get("zero_volatility_symbols", []),
        "risk_model.zero_volatility_symbols",
        errors,
    )
    if scope is None:
        scope = []
    if zero_symbols is None:
        zero_symbols = []
    scope_set = set(scope)
    zero_set = set(zero_symbols)
    active_symbols = set(weights)
    overlap = sorted(scope_set & zero_set)
    if overlap:
        errors.append(
            "risk_model scope_symbols and zero_volatility_symbols overlap: "
            + ", ".join(overlap)
        )
    coverage_gap = sorted(active_symbols - scope_set - zero_set)
    extras = sorted((scope_set | zero_set) - active_symbols)
    if coverage_gap:
        errors.append(
            "risk_model leaves active symbols uncovered: " + ", ".join(coverage_gap)
        )
    if extras:
        errors.append(
            "risk_model references non-active symbols: " + ", ".join(extras)
        )
    if not scope:
        errors.append("risk_model.scope_symbols must contain at least one volatile asset")

    raw_volatilities = _normalize_symbol_mapping(
        risk_model.get("volatilities"), "risk_model.volatilities", errors
    )
    if raw_volatilities is None:
        raw_volatilities = {}
    missing_vols = sorted(scope_set - set(raw_volatilities))
    extra_vols = sorted(set(raw_volatilities) - scope_set)
    if missing_vols:
        errors.append("risk_model.volatilities missing: " + ", ".join(missing_vols))
    if extra_vols:
        errors.append(
            "risk_model.volatilities contains out-of-scope symbols: "
            + ", ".join(extra_vols)
        )
    volatilities: dict[str, float] = {}
    for symbol, value in raw_volatilities.items():
        volatility = _strict_number(
            value, f"risk_model.volatilities.{symbol}", errors
        )
        if volatility is not None and volatility <= 0:
            errors.append(f"risk_model.volatilities.{symbol} must be positive")
        if volatility is not None and volatility > 0:
            volatilities[symbol] = volatility

    correlations = risk_model.get("correlations")
    if not isinstance(correlations, dict):
        errors.append("risk_model.correlations must be an object")
        correlations = {}
    normalized_rows = _normalize_symbol_mapping(
        correlations, "risk_model.correlations", errors
    )
    if normalized_rows is None:
        normalized_rows = {}
    missing_rows = sorted(scope_set - set(normalized_rows))
    extra_rows = sorted(set(normalized_rows) - scope_set)
    if missing_rows:
        errors.append("risk_model.correlations missing rows: " + ", ".join(missing_rows))
    if extra_rows:
        errors.append(
            "risk_model.correlations contains out-of-scope rows: "
            + ", ".join(extra_rows)
        )
    correlation_values: dict[str, dict[str, float]] = {}
    for row_symbol, raw_row in normalized_rows.items():
        row = _normalize_symbol_mapping(
            raw_row, f"risk_model.correlations.{row_symbol}", errors
        )
        if row is None:
            continue
        missing_columns = sorted(scope_set - set(row))
        extra_columns = sorted(set(row) - scope_set)
        if missing_columns:
            errors.append(
                f"risk_model.correlations.{row_symbol} missing columns: {', '.join(missing_columns)}"
            )
        if extra_columns:
            errors.append(
                f"risk_model.correlations.{row_symbol} contains out-of-scope columns: {', '.join(extra_columns)}"
            )
        parsed_row: dict[str, float] = {}
        for column_symbol, raw_correlation in row.items():
            correlation = _strict_number(
                raw_correlation,
                f"risk_model.correlations.{row_symbol}.{column_symbol}",
                errors,
            )
            if correlation is not None and not (-1 <= correlation <= 1):
                errors.append(
                    f"risk_model.correlations.{row_symbol}.{column_symbol} must be from -1 to 1"
                )
            if correlation is not None and -1 <= correlation <= 1:
                parsed_row[column_symbol] = correlation
        correlation_values[row_symbol] = parsed_row

    for symbol in scope:
        diagonal = correlation_values.get(symbol, {}).get(symbol)
        if diagonal is not None and abs(diagonal - 1.0) > MATRIX_TOLERANCE:
            errors.append(f"risk_model correlation diagonal for {symbol} must equal 1")
    for row_index, row_symbol in enumerate(scope):
        for column_symbol in scope[row_index + 1 :]:
            left = correlation_values.get(row_symbol, {}).get(column_symbol)
            right = correlation_values.get(column_symbol, {}).get(row_symbol)
            if left is not None and right is not None and abs(left - right) > MATRIX_TOLERANCE:
                errors.append(
                    f"risk_model correlations must be symmetric for {row_symbol}/{column_symbol}"
                )

    prerequisites_ready = (
        scope_set == set(volatilities)
        and scope_set == set(correlation_values)
        and all(scope_set == set(row) for row in correlation_values.values())
    )
    covariance: list[list[float]] = []
    if prerequisites_ready:
        covariance = [
            [
                volatilities[row_symbol]
                * volatilities[column_symbol]
                * correlation_values[row_symbol][column_symbol]
                for column_symbol in scope
            ]
            for row_symbol in scope
        ]
        if not _is_positive_semidefinite(covariance):
            errors.append("risk_model covariance matrix must be positive semidefinite")

    if errors or not covariance:
        return {"status": "invalid", "detail_status": "contract_validation_failed"}
    scoped_weights = [weights[symbol] for symbol in scope]
    covariance_times_weights = [
        sum(covariance[row][column] * scoped_weights[column] for column in range(len(scope)))
        for row in range(len(scope))
    ]
    variance = sum(
        scoped_weights[index] * covariance_times_weights[index]
        for index in range(len(scope))
    )
    if variance <= MATRIX_TOLERANCE:
        errors.append("risk_model produces non-positive portfolio variance")
        return {"status": "invalid", "detail_status": "contract_validation_failed"}
    portfolio_volatility = math.sqrt(variance)
    contributions: dict[str, dict[str, float]] = {}
    for index, symbol in enumerate(scope):
        component = scoped_weights[index] * covariance_times_weights[index] / portfolio_volatility
        contributions[symbol] = {
            "marginal_contribution_to_volatility": round(
                covariance_times_weights[index] / portfolio_volatility, 10
            ),
            "component_contribution_to_volatility": round(component, 10),
            "share_of_portfolio_variance": round(
                scoped_weights[index] * covariance_times_weights[index] / variance,
                10,
            ),
        }
    for symbol in zero_symbols:
        contributions[symbol] = {
            "marginal_contribution_to_volatility": 0.0,
            "component_contribution_to_volatility": 0.0,
            "share_of_portfolio_variance": 0.0,
        }
    return {
        "status": "calculated",
        "detail_status": "explicit_volatility_correlation",
        "portfolio_volatility": round(portfolio_volatility, 10),
        "portfolio_variance": round(variance, 10),
        "risk_contributions": contributions,
        "source": source,
        "source_locator": source_locator,
        "as_of": as_of,
        "observation_window": observation_window,
        "frequency": frequency,
        "model_boundary": "volatility contribution diagnostic; not risk parity and not an optimizer",
    }


def analyze_scenarios(portfolio: Any, assumptions: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    data_gaps: list[str] = []
    if not isinstance(portfolio, dict):
        return _result_shell(
            status="invalid",
            detail_status="portfolio_root_invalid",
            errors=["portfolio root must be an object"],
        )
    if not isinstance(assumptions, dict):
        return _result_shell(
            status="invalid",
            detail_status="assumptions_root_invalid",
            errors=["assumptions root must be an object"],
        )

    portfolio_schema = json.loads(PORTFOLIO_SCHEMA_PATH.read_text(encoding="utf-8"))
    version_raw = assumptions.get("scenario_contract_version", "1.0")
    version = _non_empty_string(
        version_raw, "scenario_contract_version", errors
    )
    if version is not None and version not in SUPPORTED_CONTRACT_VERSIONS:
        errors.append(
            "scenario_contract_version must be one of: "
            + ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
        )
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        version = "1.0"

    for field in portfolio_schema["required_top_level"]:
        if portfolio.get(field) in (None, "", []):
            errors.append(f"portfolio missing required field: {field}")
    portfolio_currency = _currency(
        portfolio.get("base_currency"), "portfolio.base_currency", errors
    )
    assumption_currency = _currency(
        assumptions.get("base_currency"), "assumptions.base_currency", errors
    )
    if (
        portfolio_currency is not None
        and assumption_currency is not None
        and portfolio_currency != assumption_currency
    ):
        errors.append("assumptions.base_currency must match portfolio.base_currency")
    base_currency = assumption_currency or portfolio_currency

    positions = portfolio.get("positions")
    if not isinstance(positions, list) or not positions:
        errors.append("portfolio.positions must be a non-empty list")
        positions = []
    active_positions: dict[str, dict[str, Any]] = {}
    seen_symbols: set[str] = set()
    inactive_symbols: list[str] = []
    for index, position in enumerate(positions):
        prefix = f"positions[{index}]"
        if not isinstance(position, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing_fields = [
            field
            for field in portfolio_schema["required_position_fields"]
            if field not in position or position.get(field) in (None, "")
        ]
        if missing_fields:
            errors.append(
                f"{prefix} missing portfolio schema fields: {', '.join(missing_fields)}"
            )
        symbol = _symbol(position.get("symbol"), f"{prefix}.symbol", errors)
        currency = _currency(
            position.get("currency"), f"{prefix}.currency", errors
        )
        quantity = _strict_number(
            position.get("quantity"), f"{prefix}.quantity", errors
        )
        avg_cost = _strict_number(
            position.get("avg_cost"), f"{prefix}.avg_cost", errors
        )
        if symbol is not None:
            if symbol in seen_symbols:
                errors.append(f"duplicate position symbol: {symbol}")
            seen_symbols.add(symbol)
        if quantity is not None and quantity < 0:
            errors.append(f"{prefix}.quantity must be non-negative")
        if avg_cost is not None and avg_cost <= 0:
            errors.append(f"{prefix}.avg_cost must be positive")
        if symbol is None or currency is None or quantity is None or quantity < 0:
            continue
        if quantity == 0:
            inactive_symbols.append(symbol)
            if "current_weight" in position:
                weight = _strict_number(
                    position.get("current_weight"),
                    f"{prefix}.current_weight",
                    errors,
                )
                if weight is not None and weight != 0:
                    errors.append(
                        f"{prefix}.current_weight must be 0 when quantity is 0"
                    )
            continue
        if "current_weight" not in position:
            errors.append(f"{prefix}.current_weight is required for active positions")
            continue
        weight = _strict_number(
            position.get("current_weight"), f"{prefix}.current_weight", errors
        )
        if weight is not None and not (0 < weight <= 1):
            errors.append(f"{prefix}.current_weight must be positive and at most 1")
        if symbol in active_positions:
            continue
        if weight is not None and 0 < weight <= 1:
            active_positions[symbol] = {
                "weight": weight,
                "currency": currency,
            }
    if positions and not active_positions:
        errors.append("portfolio must contain at least one valid active position")
    if inactive_symbols:
        warnings.append(
            "inactive zero-quantity records were excluded from scenario calculations: "
            + ", ".join(inactive_symbols)
        )
    weights = {
        symbol: position["weight"] for symbol, position in active_positions.items()
    }
    weight_sum = sum(weights.values())
    if weights and abs(weight_sum - 1.0) > WEIGHT_TOLERANCE:
        errors.append(
            f"active position weights must sum to 1.0 within {WEIGHT_TOLERANCE}; got {weight_sum:.8f}"
        )
    currency_exposure: dict[str, float] = {}
    for symbol, position in active_positions.items():
        currency = position["currency"]
        currency_exposure[currency] = currency_exposure.get(currency, 0.0) + weights[symbol]

    weight_snapshot = _weight_snapshot(
        assumptions.get("weight_snapshot"),
        version,
        active_positions,
        weights,
        base_currency,
        errors,
    )

    legacy_cost_configured = (
        "transaction_cost_bps" in assumptions or "assumed_turnover" in assumptions
    )
    legacy_cost = _legacy_transaction_cost(assumptions, errors)

    scenarios = assumptions.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("assumptions.scenarios must be a non-empty list")
        scenarios = []
    scenario_names: list[str] = []
    scenario_drafts: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        prefix = f"scenarios[{index}]"
        before_errors = len(errors)
        if not isinstance(scenario, dict):
            errors.append(f"{prefix} must be an object")
            continue
        name = _non_empty_string(scenario.get("name"), f"{prefix}.name", errors)
        if name is not None:
            normalized_name = name.casefold()
            if normalized_name in {item.casefold() for item in scenario_names}:
                errors.append(f"duplicate scenario name: {name}")
            scenario_names.append(name)
        source = _non_empty_string(
            scenario.get("assumption_source"),
            f"{prefix}.assumption_source",
            errors,
        )
        decompositions = (
            _scenario_returns(
                scenario,
                index,
                version,
                base_currency or "",
                active_positions,
                errors,
            )
            if base_currency is not None
            else {}
        )
        total_cost, cost_contributions, cost_status = _scenario_costs(
            scenario,
            index,
            set(weights),
            weights,
            version,
            legacy_cost,
            legacy_cost_configured,
            errors,
        )
        if len(errors) != before_errors or name is None or source is None:
            continue
        if set(decompositions) != set(weights):
            errors.append(f"{prefix} return decomposition is incomplete")
            continue
        position_contributions = {
            symbol: round(
                weights[symbol] * decompositions[symbol]["base_currency_return"],
                8,
            )
            for symbol in weights
        }
        portfolio_return = sum(position_contributions.values())
        scenario_drafts.append(
            {
                "name": name,
                "portfolio_return_before_cost": round(portfolio_return, 8),
                "portfolio_return_after_cost": (
                    round(portfolio_return - total_cost, 8)
                    if total_cost is not None
                    else None
                ),
                "position_contributions": position_contributions,
                "return_decomposition": decompositions,
                "transaction_cost_total": (
                    round(total_cost, 8) if total_cost is not None else None
                ),
                "transaction_cost_contributions": cost_contributions,
                "cost_model_status": cost_status,
                "assumption_source": source,
            }
        )
    if version == "1.0":
        missing_names = sorted(
            {"base", "bull", "bear"} - {name.casefold() for name in scenario_names}
        )
        if missing_names:
            errors.append(
                "assumptions.scenarios missing required v1 names: "
                + ", ".join(missing_names)
            )

    constraints = assumptions.get("constraints", {})
    if not isinstance(constraints, dict):
        errors.append("assumptions.constraints must be an object")
        constraints = {}
    constraint_violations: list[dict[str, Any]] = []
    max_single_weight = constraints.get("max_single_weight")
    if max_single_weight is not None:
        threshold = _strict_number(
            max_single_weight, "constraints.max_single_weight", errors
        )
        if threshold is not None and not (0 < threshold <= 1):
            errors.append(
                "constraints.max_single_weight must be greater than 0 and at most 1"
            )
        elif threshold is not None:
            for symbol, weight in weights.items():
                if weight > threshold:
                    constraint_violations.append(
                        {
                            "type": "max_single_weight",
                            "symbol": symbol,
                            "value": weight,
                            "limit": threshold,
                        }
                    )
    bucket_results, bucket_violations = _bucket_policy_results(
        constraints.get("bucket_policies"),
        version,
        weights,
        errors,
    )
    constraint_violations.extend(bucket_violations)

    risk_diagnostics = _risk_diagnostics(
        assumptions.get("risk_model"), version, weights, errors
    )
    if risk_diagnostics.get("status") == "not_calculated":
        data_gaps.extend(risk_diagnostics.get("data_gaps", []))
    if legacy_cost is None and all(
        scenario.get("cost_model") is None
        for scenario in scenarios
        if isinstance(scenario, dict)
    ):
        warnings.append(
            "transaction costs are not modeled without an explicit cost model"
        )
        data_gaps.append("transaction costs were not explicitly modeled")
    if not bucket_results:
        data_gaps.append("no explicit bucket policy was supplied")

    errors = _unique(errors)
    warnings = _unique(warnings)
    valid = not errors
    if not valid:
        transaction_cost_summary = {
            "status": "invalid",
            "detail_status": "contract_validation_failed",
            "by_scenario": {},
            "missing_scenarios": [],
        }
    else:
        scenario_costs = {
            draft["name"]: draft["transaction_cost_total"]
            for draft in scenario_drafts
            if draft["transaction_cost_total"] is not None
        }
        missing_cost_scenarios = [
            draft["name"]
            for draft in scenario_drafts
            if draft["transaction_cost_total"] is None
        ]
        if missing_cost_scenarios:
            transaction_cost_summary = {
                "status": "insufficient_data",
                "detail_status": (
                    "cost_model_missing"
                    if not scenario_costs
                    else "scenario_costs_incomplete"
                ),
                "by_scenario": scenario_costs,
                "missing_scenarios": missing_cost_scenarios,
            }
            if scenario_costs:
                data_gaps.append(
                    "transaction costs are missing for scenarios: "
                    + ", ".join(missing_cost_scenarios)
                )
        else:
            transaction_cost_summary = {
                "status": "ok",
                "detail_status": (
                    "legacy_global_cost_applied"
                    if legacy_cost is not None
                    else "explicit_scenario_costs_calculated"
                ),
                "by_scenario": scenario_costs,
                "missing_scenarios": [],
            }
    return {
        "valid": valid,
        "status": "ok" if valid else "invalid",
        "detail_status": (
            "scenario_analysis_complete" if valid else "contract_validation_failed"
        ),
        "scenario_contract_version": version,
        "base_currency": base_currency,
        "weight_sum": round(weight_sum, 8),
        "weight_tolerance": WEIGHT_TOLERANCE,
        "inactive_zero_quantity_symbols": inactive_symbols,
        "currency_exposure": {
            currency: round(weight, 8)
            for currency, weight in sorted(currency_exposure.items())
        },
        "weight_snapshot": weight_snapshot,
        "scenario_results": scenario_drafts if valid else [],
        "constraint_violations": constraint_violations if valid else [],
        "bucket_policy_results": bucket_results if valid else [],
        "transaction_cost_estimate": (
            round(legacy_cost, 8) if legacy_cost is not None else None
        ),
        "transaction_cost_summary": transaction_cost_summary,
        "risk_diagnostics": (
            risk_diagnostics
            if valid
            else {"status": "invalid", "detail_status": "contract_validation_failed"}
        ),
        "data_gaps": _unique(data_gaps),
        "model_boundary": (
            "user-supplied scenarios only; no return forecast, optimizer, risk parity, "
            "target weight, or trade action"
        ),
        "errors": errors,
        "warnings": warnings,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: str) -> Any:
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def _render(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = JsonArgumentParser(
        description=(
            "Analyze a portfolio using explicit user-supplied scenario returns, FX, "
            "costs, risk inputs, and constraints."
        )
    )
    parser.add_argument("portfolio_json")
    parser.add_argument("assumptions_json")
    parser.add_argument("--output")
    try:
        args = parser.parse_args(argv)
    except CliUsageError as exc:
        print(
            _render(
                _result_shell(
                    status="invalid",
                    detail_status="cli_usage_error",
                    errors=[str(exc)],
                )
            )
        )
        return 2

    try:
        portfolio = _load_json(args.portfolio_json)
        assumptions = _load_json(args.assumptions_json)
    except (json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        print(
            _render(
                _result_shell(
                    status="invalid",
                    detail_status="invalid_json",
                    errors=[str(exc)],
                )
            )
        )
        return 2
    except (OSError, UnicodeError) as exc:
        print(
            _render(
                _result_shell(
                    status="data_error",
                    detail_status="input_read_failed",
                    errors=[str(exc)],
                )
            )
        )
        return 2

    result = analyze_scenarios(portfolio, assumptions)
    rendered = _render(result)
    if not result["valid"]:
        print(rendered)
        return 1
    if args.output:
        try:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            print(
                _render(
                    _result_shell(
                        status="data_error",
                        detail_status="output_write_failed",
                        errors=[str(exc)],
                    )
                )
            )
            return 2
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
