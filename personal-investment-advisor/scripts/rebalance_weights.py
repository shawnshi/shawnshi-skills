from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


REQUIRED_POLICY_FIELDS = (
    "bucket_targets",
    "max_weight_buffer",
    "history_period",
    "min_history_points",
)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _load_policy(data: dict[str, Any], policy_file: str | None) -> dict[str, Any] | None:
    if policy_file:
        return json.loads(Path(policy_file).read_text(encoding="utf-8"))
    policy = data.get("rebalance_policy")
    return policy if isinstance(policy, dict) else None


def _validate_policy(policy: dict[str, Any]) -> list[str]:
    errors = [
        f"missing rebalance policy field: {field}"
        for field in REQUIRED_POLICY_FIELDS
        if policy.get(field) in (None, "", {})
    ]
    targets = policy.get("bucket_targets")
    if isinstance(targets, dict):
        parsed = [_finite(value) for value in targets.values()]
        if any(value is None or value < 0 for value in parsed):
            errors.append("bucket_targets values must be finite and non-negative")
        elif abs(sum(parsed) - 1.0) > 1e-6:
            errors.append("bucket_targets must sum to 1.0")
    else:
        errors.append("bucket_targets must be an object")
    buffer_value = _finite(policy.get("max_weight_buffer"))
    if buffer_value is None or buffer_value < 0:
        errors.append("max_weight_buffer must be finite and non-negative")
    try:
        if int(policy.get("min_history_points")) <= 1:
            errors.append("min_history_points must be greater than 1")
    except (TypeError, ValueError):
        errors.append("min_history_points must be an integer")
    return errors


def _exchange_rate(data: dict[str, Any], currency: str) -> float:
    base = str(data.get("base_currency") or "").upper()
    currency = str(currency or "").upper()
    if not base or not currency:
        raise ValueError("base_currency and position currency are required")
    if currency == base:
        return 1.0
    value = _finite(data.get("exchange_rates", {}).get(currency))
    if value is None or value <= 0:
        raise ValueError(f"missing positive exchange rate for {currency} to {base}")
    return value


def recalculate_all_weights(
    filepath: str,
    *,
    write: bool = False,
    policy_file: str | None = None,
) -> dict[str, Any]:
    if not filepath:
        raise ValueError("filepath is required")
    path = Path(filepath)
    data = json.loads(path.read_text(encoding="utf-8"))
    positions = data.get("positions")
    if not isinstance(positions, list) or not positions:
        raise ValueError("positions must be a non-empty list")

    warnings: list[str] = []
    symbols = [
        str(position.get("symbol"))
        for position in positions
        if position.get("market_type") != "CASH" and position.get("symbol")
    ]
    prices: dict[str, float] = {}
    if symbols:
        history = yf.download(symbols, period="5d", progress=False)["Close"]
        if isinstance(history, pd.Series) and len(symbols) == 1:
            history = history.to_frame(symbols[0])
        for symbol in symbols:
            if symbol in history.columns:
                series = history[symbol].dropna()
                if not series.empty:
                    prices[symbol] = float(series.iloc[-1])

    values: list[float | None] = []
    for position in positions:
        quantity = _finite(position.get("quantity"))
        if quantity is None or quantity < 0:
            values.append(None)
            warnings.append(f"{position.get('symbol')}: quantity unavailable")
            continue
        try:
            rate = _exchange_rate(data, position.get("currency"))
        except ValueError as exc:
            values.append(None)
            warnings.append(str(exc))
            continue
        if position.get("market_type") == "CASH":
            price = 1.0
        else:
            price = prices.get(str(position.get("symbol")))
        if price is None:
            values.append(None)
            warnings.append(
                f"{position.get('symbol')}: current price unavailable; avg_cost was not substituted"
            )
            continue
        values.append(quantity * price * rate)

    if all(value is not None for value in values) and sum(values) > 0:
        total = float(sum(values))
        for position, value in zip(positions, values):
            position["current_weight"] = round(float(value) / total, 6)
        current_weight_status = "computed"
    else:
        current_weight_status = "not_computed_incomplete_market_data"

    policy = _load_policy(data, policy_file)
    if policy is None:
        data["_rebalance"] = {
            "status": "current_weights_only_policy_missing",
            "target_weights_computed": False,
            "warnings": warnings
            + ["No rebalance policy supplied; target_weight and max_weight were not calculated."],
        }
    else:
        policy_errors = _validate_policy(policy)
        if policy_errors:
            raise ValueError("; ".join(policy_errors))
        bucket_targets = {
            str(key): float(value) for key, value in policy["bucket_targets"].items()
        }
        buffer_value = float(policy["max_weight_buffer"])
        min_points = int(policy["min_history_points"])
        period = str(policy["history_period"])
        targets: dict[str, float] = {}
        for bucket, bucket_target in bucket_targets.items():
            bucket_positions = [
                position
                for position in positions
                if position.get("allocation_bucket") == bucket
            ]
            if not bucket_positions:
                raise ValueError(f"policy bucket {bucket!r} has no positions")
            if all(position.get("market_type") == "CASH" for position in bucket_positions):
                equal = bucket_target / len(bucket_positions)
                for position in bucket_positions:
                    targets[str(position["symbol"])] = equal
                continue
            bucket_symbols = [str(position["symbol"]) for position in bucket_positions]
            frame = yf.download(bucket_symbols, period=period, progress=False)["Close"]
            if isinstance(frame, pd.Series) and len(bucket_symbols) == 1:
                frame = frame.to_frame(bucket_symbols[0])
            inverse_vol: dict[str, float] = {}
            for symbol in bucket_symbols:
                if symbol not in frame.columns:
                    raise ValueError(f"{symbol}: history unavailable for target calculation")
                returns = frame[symbol].dropna().pct_change().dropna()
                if len(returns) < min_points:
                    raise ValueError(
                        f"{symbol}: requires at least {min_points} history points"
                    )
                volatility = float(returns.std())
                if not math.isfinite(volatility) or volatility <= 0:
                    raise ValueError(f"{symbol}: volatility is unavailable or zero")
                inverse_vol[symbol] = 1.0 / volatility
            denominator = sum(inverse_vol.values())
            for symbol, value in inverse_vol.items():
                targets[symbol] = value / denominator * bucket_target

        for position in positions:
            symbol = str(position.get("symbol"))
            if symbol not in targets:
                raise ValueError(
                    f"{symbol}: allocation_bucket is missing or absent from bucket_targets"
                )
            target = round(targets[symbol], 6)
            position["target_weight"] = target
            position["max_weight"] = round(target + buffer_value, 6)
        data["_rebalance"] = {
            "status": "targets_computed_from_explicit_policy",
            "current_weight_status": current_weight_status,
            "target_weights_computed": True,
            "policy": policy,
            "warnings": warnings,
        }

    if write:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recalculate current weights and optionally explicit-policy targets."
    )
    parser.add_argument("--filepath", required=True)
    parser.add_argument("--policy-file")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        recalculate_all_weights(
            args.filepath,
            write=args.write,
            policy_file=args.policy_file,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
