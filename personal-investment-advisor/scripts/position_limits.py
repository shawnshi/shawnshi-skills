"""Derive per-position observation bounds from a user-confirmed risk policy.

Nothing here is hand-typed per symbol: every bound is recomputed from the user's
thresholds plus the current quantity / cost / portfolio total, so a position or
quote change moves the bounds automatically.

Bounds (all research-review triggers, never orders):
  downside  = avg_cost * (1 - max_single_position_loss)
  upside    = avg_cost * upside_cost_multiple              (price appreciation bound)
  weight cap = max_single_position_weight * portfolio_total / (quantity * fx)  (position-size bound)

Authority: the *policy* is user-confirmed; the bounds are therefore emitted with
``authority_status = derived_from_user_policy`` plus the policy locator and its
content SHA-256, and are consumed as a separate class from a Dashboard's own
user-confirmed price boundaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import instrument_labels

SCHEMA_VERSION = "pia_position_limits_v1"
DERIVED_AUTHORITY = "derived_from_user_policy"
POLICY_SCHEMA_VERSION = "pia_risk_bounds_policy_v1"
ELIGIBLE_ASSET_TYPES = {"stock", "etf", "fund", "index"}


class PolicyError(ValueError):
    """Raised when the user-confirmed policy is missing or malformed."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise PolicyError(f"{label} unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PolicyError(f"{label} must be a JSON object")
    return payload


def load_policy(path: str | Path) -> dict:
    policy = _read_json(path, "risk bounds policy")
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise PolicyError(f"policy schema_version must be {POLICY_SCHEMA_VERSION}")
    if policy.get("decision_scope") != "observation_only":
        raise PolicyError("policy decision_scope must be observation_only")
    if policy.get("authority_status") != "user_confirmed":
        raise PolicyError("policy authority_status must be user_confirmed")
    locator = policy.get("source_locator")
    if not isinstance(locator, str) or not locator:
        raise PolicyError("policy requires a source_locator")
    rules = policy.get("rules")
    if not isinstance(rules, dict):
        raise PolicyError("policy requires rules")
    for key in ("max_single_position_weight", "max_single_position_loss", "upside_cost_multiple"):
        rule = rules.get(key)
        if not isinstance(rule, dict) or not isinstance(rule.get("value"), (int, float)):
            raise PolicyError(f"policy rule {key} requires a numeric value")
        numeric = float(rule["value"])
        if numeric <= 0 or numeric > 5:
            raise PolicyError(f"policy rule {key} value {numeric} is out of range")
    proximity = policy.get("proximity")
    if proximity is not None:
        if not isinstance(proximity, dict):
            raise PolicyError("policy proximity must be an object when provided")
        if proximity.get("mode") != "explicit_relative_pct":
            raise PolicyError("policy proximity mode must be explicit_relative_pct")
        value = proximity.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PolicyError("policy proximity requires a numeric value")
        numeric_proximity = float(value)
        if numeric_proximity <= 0 or numeric_proximity >= 1:
            raise PolicyError("policy proximity value must be between 0 and 1 (exclusive)")
        if not isinstance(proximity.get("source_locator"), str) or not proximity["source_locator"].strip():
            raise PolicyError("policy proximity requires a source_locator")
    return policy


def build(weights: dict, positions: dict, *, policy: dict, policy_path: str | Path) -> dict:
    """Return the derived-limits payload for every eligible non-cash position."""
    rules = policy["rules"]
    max_weight = float(rules["max_single_position_weight"]["value"])
    max_loss = float(rules["max_single_position_loss"]["value"])
    upside_multiple = float(rules["upside_cost_multiple"]["value"])
    eligible = set(rules["max_single_position_weight"].get("applies_to_asset_types")
                   or ELIGIBLE_ASSET_TYPES)

    position_by_symbol = {}
    for item in positions.get("positions") or []:
        if isinstance(item, dict) and item.get("symbol"):
            position_by_symbol[str(item["symbol"]).upper()] = item

    total = sum(float(row["market_value_base"]) for row in weights["current_weights"])
    name_map = instrument_labels.symbol_name_map(positions)
    policy_sha = sha256_file(policy_path)
    proximity = policy.get("proximity")
    proximity_payload = None
    if isinstance(proximity, dict):
        proximity_payload = {
            "mode": proximity["mode"],
            "value": float(proximity["value"]),
            "source_tier": "user_authorized",
            "source_locator": proximity["source_locator"],
            "content_sha256": policy_sha,
            "as_of_date": proximity.get("confirmed_at"),
            "authority_status": "user_confirmed",
            "applies_to": proximity.get("applies_to"),
        }
    rows = []
    for row in weights["current_weights"]:
        symbol = str(row["symbol"]).upper()
        position = position_by_symbol.get(symbol)
        if not isinstance(position, dict):
            continue
        asset_type = str(position.get("asset_type") or "").lower()
        if asset_type not in eligible or str(position.get("market") or "").upper() == "CASH":
            continue
        quantity = float(row["quantity"])
        if quantity <= 0:
            continue
        fx = 1.0
        fx_block = row.get("fx_to_base")
        if isinstance(fx_block, dict) and isinstance(fx_block.get("rate"), (int, float)):
            fx = float(fx_block["rate"])
        avg_cost = float(position["avg_cost"])
        currency = str(row["currency"])
        current_price = float(row["current_price"])
        downside = round(avg_cost * (1 - max_loss), 6)
        upside = round(avg_cost * upside_multiple, 6)
        weight_cap_price = round(max_weight * total / (quantity * fx), 6)
        stem = symbol.lower().replace(".", "-")
        rows.append({
            "symbol": str(row["symbol"]),
            instrument_labels.NAME_FIELD: position.get("name"),
            instrument_labels.LABEL_FIELD: instrument_labels.label(row["symbol"], name_map),
            "currency": currency,
            "quantity": quantity,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "current_weight": round(float(row["current_weight"]), 6),
            "market_value_base": round(float(row["market_value_base"]), 2),
            "boundaries": [
                {
                    "boundary_id": f"{stem}-derived-downside",
                    "role": "downside_boundary",
                    "operator": "lte",
                    "value": downside,
                    "currency": currency,
                    "metric": "regular_market_price",
                    "authority_status": DERIVED_AUTHORITY,
                    "source_locator": policy["source_locator"],
                    "content_sha256": policy_sha,
                    "derivation": f"avg_cost {avg_cost} * (1 - {max_loss})",
                    "basis": "cost_drawdown",
                },
                {
                    "boundary_id": f"{stem}-derived-upside-cost",
                    "role": "upside_boundary",
                    "operator": "gte",
                    "value": upside,
                    "currency": currency,
                    "metric": "regular_market_price",
                    "authority_status": DERIVED_AUTHORITY,
                    "source_locator": policy["source_locator"],
                    "content_sha256": policy_sha,
                    "derivation": f"avg_cost {avg_cost} * {upside_multiple}",
                    "basis": "cost_appreciation",
                },
                {
                    "boundary_id": f"{stem}-derived-weight-cap",
                    "role": "upside_boundary",
                    "operator": "gte",
                    "value": weight_cap_price,
                    "currency": currency,
                    "metric": "regular_market_price",
                    "authority_status": DERIVED_AUTHORITY,
                    "source_locator": policy["source_locator"],
                    "content_sha256": policy_sha,
                    "derivation": (f"{max_weight} * portfolio_total {total:.2f} CNY / "
                                   f"({quantity} * fx {fx})"),
                    "basis": "position_weight_cap",
                },
            ],
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "decision_scope": policy["decision_scope"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_from": {
            "policy": str(policy_path),
            "policy_sha256": policy_sha,
            "evaluation_epoch": weights.get("evaluation_epoch"),
            "portfolio_total_market_value_base": round(total, 2),
            "base_currency": weights.get("base_currency"),
        },
        "rules": {
            "max_single_position_weight": max_weight,
            "max_single_position_loss": max_loss,
            "upside_cost_multiple": upside_multiple,
        },
        "proximity_policy": proximity_payload,
        "proximity_policy_note": ("来自用户已确认的风险政策；Dashboard 自带的 proximity_policy 优先，"
                                "本字段仅在其缺位时生效；两者均无时 gate 保持 near_rule_undefined。"),
        "positions": rows,
        "note": ("自动派生，仅触发研究复核；不生成订单。与 Dashboard 中用户逐笔确认的价格边界并列汇报，"
                 "两者都不互相替代。"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights-file", required=True)
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--policy-file", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        policy = load_policy(args.policy_file)
    except PolicyError as exc:
        print(json.dumps({"status": "failed", "detail_status": "policy_invalid",
                          "errors": [str(exc)]}, ensure_ascii=False, indent=1))
        return 3
    weights = _read_json(args.weights_file, "weights file")
    positions = _read_json(args.positions_file, "positions file")
    payload = build(weights, positions, policy=policy, policy_path=args.policy_file)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "complete", "detail_status": "position_limits_derived",
                      "positions": len(payload["positions"]), "out": str(out_path),
                      "rules": payload["rules"], "policy_sha256": payload["generated_from"]["policy_sha256"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
