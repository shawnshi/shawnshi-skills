"""Offline inverse-volatility allocation experiment for PIA.

This module deliberately does not fetch prices or return trading instructions.
It consumes an explicit, source-labelled policy and emits a research-only
allocation experiment. Inverse-volatility allocation is not risk parity: it
does not model correlations or equalise portfolio risk contributions.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from portfolio_loader import is_cash_position, load_positions, normalize_symbol


SCHEMA_VERSION = "pia_inverse_volatility_allocation_v1"
POLICY_SCHEMA_VERSION = "pia_inverse_volatility_policy_v1"
EXPERIMENT_NAME = "inverse_volatility_allocation"
RESERVED_SOURCE_LOCATORS = ("example.com", "example.test", ".invalid", "localhost")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        return None
    return value


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_comparable(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid_input",
        "detail_status": "not_evaluated",
        "research_only": True,
        "decision_scope": "research_only",
        "operation_mode": "read_only_offline",
        "method": EXPERIMENT_NAME,
        "risk_parity_claim": False,
        "mutation_performed": False,
        "fail_closed": {"enforced": True, "triggered": True},
        "experimental_weights": [],
        "errors": [],
        "warnings": [],
        "limitations": [
            "Inverse-volatility allocation ignores correlations and does not equalise risk contributions.",
            "The experiment does not model expected returns, taxes, liquidity, transaction costs, or execution.",
            "Experimental weights are not target weights or trading instructions.",
        ],
    }


def _error_report(
    detail_status: str,
    errors: Iterable[str],
    *,
    status: str = "invalid_input",
) -> dict[str, Any]:
    report = _base_report()
    report["status"] = status
    report["detail_status"] = detail_status
    report["errors"] = list(errors)
    return report


def _validate_policy_root(policy: Any) -> list[str]:
    """Validate the root before any mapping access.

    The former implementation called ``.get`` on arbitrary JSON roots, which
    turned a policy-list error into an unstructured AttributeError.
    """

    if not isinstance(policy, dict):
        return ["policy root must be an object"]
    errors: list[str] = []
    required = (
        "schema_version",
        "experiment",
        "decision_scope",
        "as_of",
        "bucket_targets",
        "bucket_members",
        "volatility_observations",
    )
    for field in required:
        if field not in policy or policy.get(field) in (None, ""):
            errors.append(f"missing policy field: {field}")
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append(f"policy.schema_version must equal {POLICY_SCHEMA_VERSION}")
    if policy.get("experiment") != EXPERIMENT_NAME:
        errors.append(f"policy.experiment must equal {EXPERIMENT_NAME}")
    if policy.get("decision_scope") != "research_only":
        errors.append("policy.decision_scope must equal research_only")
    if _parse_iso(policy.get("as_of")) is None:
        errors.append("policy.as_of must be an ISO date or datetime")
    if not isinstance(policy.get("bucket_targets"), dict):
        errors.append("policy.bucket_targets must be an object")
    if not isinstance(policy.get("bucket_members"), dict):
        errors.append("policy.bucket_members must be an object")
    if not isinstance(policy.get("volatility_observations"), dict):
        errors.append("policy.volatility_observations must be an object")
    return errors


def _validate_policy(
    policy: Any,
    active_positions: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> list[str]:
    errors = _validate_policy_root(policy)
    if errors or not isinstance(policy, dict):
        return errors

    targets = policy["bucket_targets"]
    members = policy["bucket_members"]
    observations = policy["volatility_observations"]
    target_values: list[float] = []
    for bucket, raw_target in targets.items():
        if not isinstance(bucket, str) or not bucket.strip():
            errors.append("policy.bucket_targets keys must be non-empty strings")
            continue
        value = _finite_number(raw_target)
        if value is None or value < 0:
            errors.append(
                f"policy.bucket_targets.{bucket} must be a non-negative finite JSON number"
            )
        else:
            target_values.append(value)
    if target_values and abs(sum(target_values) - 1.0) > 1e-9:
        errors.append("policy.bucket_targets must sum to 1.0")
    if set(members) != set(targets):
        errors.append("policy.bucket_members keys must exactly match bucket_targets")

    active_by_symbol = {
        normalize_symbol(position.get("symbol") or ""): position
        for position in active_positions
    }
    active_symbols = set(active_by_symbol)
    listed_symbols: list[str] = []
    for bucket, raw_symbols in members.items():
        if not isinstance(raw_symbols, list) or not raw_symbols:
            errors.append(f"policy.bucket_members.{bucket} must be a non-empty list")
            continue
        normalized: list[str] = []
        for index, raw_symbol in enumerate(raw_symbols):
            symbol = normalize_symbol(raw_symbol)
            if not symbol:
                errors.append(
                    f"policy.bucket_members.{bucket}[{index}] must be a non-empty symbol"
                )
            else:
                normalized.append(symbol)
                listed_symbols.append(symbol)
        if len(normalized) != len(set(normalized)):
            errors.append(f"policy.bucket_members.{bucket} contains duplicate symbols")
        positions = [active_by_symbol[symbol] for symbol in normalized if symbol in active_by_symbol]
        cash_count = sum(is_cash_position(position) for position in positions)
        if cash_count and cash_count != len(positions):
            errors.append(
                f"policy bucket {bucket} cannot mix cash and non-cash positions"
            )
        if cash_count > 1:
            errors.append(
                f"policy bucket {bucket} contains multiple cash positions; use one explicit bucket per cash position"
            )
    if len(listed_symbols) != len(set(listed_symbols)):
        errors.append("a symbol may appear in only one policy bucket")
    if set(listed_symbols) != active_symbols:
        missing = sorted(active_symbols - set(listed_symbols))
        extra = sorted(set(listed_symbols) - active_symbols)
        if missing:
            errors.append("policy bucket membership missing active symbols: " + ", ".join(missing))
        if extra:
            errors.append("policy bucket membership contains unknown symbols: " + ", ".join(extra))

    required_observations = {
        symbol
        for symbol, position in active_by_symbol.items()
        if not is_cash_position(position)
    }
    observation_symbols = {
        normalize_symbol(symbol)
        for symbol in observations
        if isinstance(symbol, str) and normalize_symbol(symbol)
    }
    if observation_symbols != required_observations:
        missing = sorted(required_observations - observation_symbols)
        extra = sorted(observation_symbols - required_observations)
        if missing:
            errors.append("missing volatility observations: " + ", ".join(missing))
        if extra:
            errors.append("unexpected volatility observations: " + ", ".join(extra))

    policy_as_of = _parse_iso(policy.get("as_of"))
    current_date = today or date.today()
    if policy_as_of is not None and _utc_comparable(policy_as_of).date() > current_date:
        errors.append("policy.as_of cannot be in the future")
    for raw_symbol, observation in observations.items():
        symbol = normalize_symbol(raw_symbol)
        prefix = f"policy.volatility_observations.{symbol or raw_symbol}"
        if not isinstance(raw_symbol, str) or raw_symbol != symbol:
            errors.append(
                f"{prefix} key must use the uppercase canonical symbol form"
            )
        if not isinstance(observation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        volatility = _finite_number(observation.get("annualized_volatility"))
        if volatility is None or volatility <= 0:
            errors.append(f"{prefix}.annualized_volatility must be positive and finite")
        if _positive_integer(observation.get("observation_count")) is None:
            errors.append(f"{prefix}.observation_count must be an integer of at least 2")
        start = _parse_iso(observation.get("window_start"))
        end = _parse_iso(observation.get("window_end"))
        observed_as_of = _parse_iso(observation.get("as_of"))
        if start is None:
            errors.append(f"{prefix}.window_start must be an ISO date or datetime")
        if end is None:
            errors.append(f"{prefix}.window_end must be an ISO date or datetime")
        if observed_as_of is None:
            errors.append(f"{prefix}.as_of must be an ISO date or datetime")
        comparable = start is not None and end is not None and observed_as_of is not None
        if comparable and not (
            _utc_comparable(start)
            <= _utc_comparable(end)
            <= _utc_comparable(observed_as_of)
        ):
            errors.append(f"{prefix} must satisfy window_start <= window_end <= as_of")
        if (
            comparable
            and policy_as_of is not None
            and _utc_comparable(observed_as_of) > _utc_comparable(policy_as_of)
        ):
            errors.append(f"{prefix}.as_of cannot be after policy.as_of")
        for field, value in (
            ("window_start", start),
            ("window_end", end),
            ("as_of", observed_as_of),
        ):
            if value is not None and _utc_comparable(value).date() > current_date:
                errors.append(f"{prefix}.{field} cannot be in the future")
        for field in ("source", "source_locator"):
            value = observation.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
            elif field == "source_locator" and any(
                token in value.strip().lower() for token in RESERVED_SOURCE_LOCATORS
            ):
                errors.append(f"{prefix}.source_locator uses a reserved test locator")
    return errors


def run_inverse_volatility_experiment(
    active_positions: list[dict[str, Any]],
    policy: Any,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return explicit research weights, or a structured fail-closed report."""

    errors = _validate_policy(policy, active_positions, today=today)
    if errors:
        return _error_report("policy_validation_failed", errors)
    assert isinstance(policy, dict)

    active_by_symbol = {
        normalize_symbol(position.get("symbol") or ""): position
        for position in active_positions
    }
    observations = policy["volatility_observations"]
    weights: dict[str, float] = {}
    bucket_results: list[dict[str, Any]] = []
    for bucket, raw_target in policy["bucket_targets"].items():
        bucket_target = float(raw_target)
        symbols = [normalize_symbol(symbol) for symbol in policy["bucket_members"][bucket]]
        positions = [active_by_symbol[symbol] for symbol in symbols]
        if len(positions) == 1 and is_cash_position(positions[0]):
            weights[symbols[0]] = bucket_target
            bucket_results.append(
                {
                    "bucket": bucket,
                    "bucket_weight": bucket_target,
                    "calculation": "single_explicit_cash_member",
                    "symbols": symbols,
                }
            )
            continue
        inverse_volatility = {
            symbol: 1.0 / float(observations[symbol]["annualized_volatility"])
            for symbol in symbols
        }
        denominator = sum(inverse_volatility.values())
        for symbol, value in inverse_volatility.items():
            weights[symbol] = bucket_target * value / denominator
        bucket_results.append(
            {
                "bucket": bucket,
                "bucket_weight": bucket_target,
                "calculation": "inverse_annualized_volatility",
                "symbols": symbols,
            }
        )

    report = _base_report()
    report.update(
        {
            "status": "complete",
            "detail_status": "research_experiment_computed",
            "policy_schema_version": policy["schema_version"],
            "policy_as_of": policy["as_of"],
            "experimental_weights": [
                {
                    "symbol": symbol,
                    "experimental_weight": round(weight, 10),
                }
                for symbol, weight in sorted(weights.items())
            ],
            "bucket_results": bucket_results,
            "fail_closed": {"enforced": True, "triggered": False},
        }
    )
    return report


def _read_json(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label}_read_error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label}_json_error: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(
            json.dumps(
                _error_report("argument_error", [f"argument_error: {message}"]),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(2)


def main() -> int:
    parser = JsonArgumentParser(
        description="Run a read-only inverse-volatility allocation research experiment."
    )
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--policy-file", required=True)
    args = parser.parse_args()
    try:
        portfolio = load_positions(args.positions_file)
        policy = _read_json(args.policy_file, "policy_file")
        report = run_inverse_volatility_experiment(portfolio["positions"], policy)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = _error_report("input_validation_failed", [str(exc)])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
