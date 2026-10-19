"""Derive per-position observation bounds from a user-confirmed risk policy.

Bounds use the explicitly supplied confirmed policy and current position snapshot.
Bare position fields are records, not proof of confirmed individual authority.
Weight-cap prices are frozen-NAV mappings, not dynamic weight-trigger prices.

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
import math
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
        if (not isinstance(rule, dict) or isinstance(rule.get("value"), bool)
                or not isinstance(rule.get("value"), (int, float))):
            raise PolicyError(f"policy rule {key} requires a numeric value")
        try:
            numeric = float(rule["value"])
        except OverflowError as exc:
            raise PolicyError(f"policy rule {key} value is out of range") from exc
        upper = 1 if key != "upside_cost_multiple" else 5
        if not math.isfinite(numeric) or numeric <= 0 or numeric > upper:
            raise PolicyError(f"policy rule {key} value {numeric} is out of range")
        if key == "max_single_position_loss" and numeric == 1:
            raise PolicyError("max_single_position_loss must be less than 1")
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
        if not math.isfinite(numeric_proximity) or numeric_proximity <= 0 or numeric_proximity >= 1:
            raise PolicyError("policy proximity value must be between 0 and 1 (exclusive)")
        if not isinstance(proximity.get("source_locator"), str) or not proximity["source_locator"].strip():
            raise PolicyError("policy proximity requires a source_locator")
    return policy


def _policy_date(value: object):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if len(value) == 10 else None
    except ValueError:
        return None


def resolve_weight_constraints(position: dict, *, policy: dict, policy_sha: str,
                               evaluation_epoch: object) -> dict:
    """Intersect only explicitly effective, comparable, versioned hard caps."""
    rule = policy["rules"]["max_single_position_weight"]
    asset_type = position["asset_type"]
    eligible = rule.get("applies_to_asset_types") or ELIGIBLE_ASSET_TYPES
    active = []
    if asset_type in eligible:
        active.append({"constraint_id": "policy:max_single_position_weight",
                       "value": float(rule["value"]), "version": policy.get("schema_version"),
                       "source_locator": policy["source_locator"], "content_sha256": policy_sha,
                       "role": "hard_max_weight", "denominator": "portfolio_total_market_value_base",
                       "scope": {"asset_types": sorted(eligible)}, "authority_status": "user_confirmed"})
    if asset_type == "stock":
        active.append({"constraint_id": "skill:p0-single-stock", "value": .3,
                       "version": "P0-30-65", "source_locator": "SKILL.md#股票集中度硬上限",
                       "role": "hard_max_weight", "denominator": "portfolio_total_market_value_base",
                       "scope": {"asset_type": "stock"}, "authority_status": "skill_hard_limit"})
    result = {"status": "complete", "active_items": active, "recorded_unconfirmed": [],
              "conflicts": [], "gaps": [], "inactive_items": [], "excluded_items": []}
    if "max_weight" in position:
        result["recorded_unconfirmed"].append({"constraint_id": "position:max_weight",
            "value": position["max_weight"], "reason": "legacy_field_authority_unresolved",
            "source_locator": "positions:max_weight", "version": None,
            "scope": {"symbol": position["symbol"], "asset_type": asset_type},
            "denominator": "unconfirmed", "role": "unconfirmed"})
    today = None
    if isinstance(evaluation_epoch, (int, float)) and not isinstance(evaluation_epoch, bool):
        try:
            if math.isfinite(evaluation_epoch):
                today = datetime.fromtimestamp(evaluation_epoch, timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            today = None
    records = policy.get("individual_weight_constraints", [])
    if not isinstance(records, list):
        result["gaps"].append("individual_weight_constraints_must_be_list")
        records = []
    candidates = []
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("symbol"), str)
                or not record["symbol"].strip()):
            result["gaps"].append("individual_constraint_scope_missing")
            continue
        if record["symbol"].upper() != str(position["symbol"]).upper():
            continue
        item = {**record, "content_sha256": policy_sha}
        status = record.get("status")
        if status in ("revoked", "superseded"):
            result["inactive_items"].append(item)
            continue
        if status == "conflict":
            result["conflicts"].append({**item, "reason": "explicit_conflict"})
            continue
        if status != "effective" or record.get("authority_status") != "user_confirmed":
            result["recorded_unconfirmed"].append({**item, "reason": "not_explicitly_effective_confirmed"})
            continue
        supported_fields = {"constraint_id", "version", "source_locator", "symbol", "asset_type", "market",
                            "role", "denominator", "value", "authority_status", "status", "confirmed_at",
                            "effective_from", "effective_until"}
        if set(record) - supported_fields:
            result["recorded_unconfirmed"].append({**item, "reason": "unsupported_constraint_fields"})
            continue
        text_fields = ("constraint_id", "version", "source_locator")
        value = record.get("value")
        confirmed, effective = _policy_date(record.get("confirmed_at")), _policy_date(record.get("effective_from"))
        if (any(not isinstance(record.get(key), str) or not record[key].strip() for key in text_fields)
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0 < value <= 1 or not math.isfinite(value)
                or today is None or confirmed is None or effective is None or confirmed > today):
            result["recorded_unconfirmed"].append({**item, "reason": "confirmation_version_value_or_clock_missing"})
            continue
        end = _policy_date(record.get("effective_until")) if "effective_until" in record else None
        if "effective_until" in record and (end is None or end < effective):
            result["conflicts"].append({**item, "reason": "invalid_effective_interval"})
            continue
        if effective > today or (end is not None and end < today):
            result["inactive_items"].append({**item, "reason": "outside_effective_interval"})
            continue
        if (record.get("role") != "hard_max_weight"
                or record.get("denominator") != "portfolio_total_market_value_base"
                or record.get("asset_type") != asset_type
                or record.get("market") != position.get("market")):
            result["excluded_items"].append({**item, "reason": "incomparable_role_denominator_or_scope"})
            continue
        candidates.append(item)
    ids = [item["constraint_id"] for item in candidates]
    blocked_ids = {item.get("constraint_id") for key in ("conflicts", "recorded_unconfirmed")
                   for item in result[key] if isinstance(item.get("constraint_id"), str)}
    for item in candidates:
        if ids.count(item["constraint_id"]) > 1 or item["constraint_id"] in blocked_ids:
            result["conflicts"].append({**item, "reason": "multiple_effective_versions_or_values"})
        else:
            active.append(item)
    result["effective_max_weight"] = min(item["value"] for item in active) if active else None
    if any(result[key] for key in ("recorded_unconfirmed", "conflicts", "gaps", "excluded_items")):
        result["status"] = "unresolved"
    return result


def build(weights: dict, positions: dict, *, policy: dict, policy_path: str | Path) -> dict:
    """Return the derived-limits payload for every eligible non-cash position."""
    rules = policy["rules"]
    max_weight = float(rules["max_single_position_weight"]["value"])
    max_loss = float(rules["max_single_position_loss"]["value"])
    upside_multiple = float(rules["upside_cost_multiple"]["value"])
    eligible = set(rules["max_single_position_weight"].get("applies_to_asset_types")
                   or ELIGIBLE_ASSET_TYPES) | {"stock"}

    position_by_symbol = {}
    for item in positions.get("positions") or []:
        if isinstance(item, dict) and item.get("symbol"):
            position_by_symbol[str(item["symbol"]).upper()] = item

    total = sum(float(row["market_value_base"]) for row in weights["current_weights"])
    # Two denominators coexist and must never be mixed: the confirmed weight policy
    # measures against total portfolio value including cash, while bucket targets
    # measure against non-cash value.  Reporting only one of them is how a 2.5pp
    # breach can be shown as a marginal one.
    non_cash_total = 0.0
    for row in weights["current_weights"]:
        position = position_by_symbol.get(str(row["symbol"]).upper())
        if not isinstance(position, dict):
            continue
        if str(position.get("asset_type") or "").lower() == "cash":
            continue
        if str(position.get("market") or "").upper() == "CASH":
            continue
        non_cash_total += float(row["market_value_base"])
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
        constraints = resolve_weight_constraints(position, policy=policy, policy_sha=policy_sha,
                                                 evaluation_epoch=weights.get("evaluation_epoch"))
        effective_max = constraints["effective_max_weight"]
        weight_cap_price = round(effective_max * total / (quantity * fx), 6)
        weight_compliance = {
            "status": "breached" if float(row["current_weight"]) > effective_max else "within_limit",
            "current_weight": float(row["current_weight"]), "effective_max_weight": effective_max,
            "operator": "gt", "denominator": "portfolio_total_market_value_base",
            "current_weight_policy_denominator": (
                round(float(row["market_value_base"]) / non_cash_total, 10)
                if non_cash_total > 0 else None),
            "policy_denominator": "active_non_cash_market_value",
            "evaluation_epoch": weights.get("evaluation_epoch"), "basis": "snapshot_weight",
            "scope": "active_constraints_only",
        }
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
            "constraint_resolution": constraints,
            "weight_compliance": weight_compliance,
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
                    "derivation": (f"{effective_max} * portfolio_total {total:.2f} "
                                   f"{weights.get('base_currency')} / ({quantity} * fx {fx})"),
                    "basis": "position_weight_cap",
                    "price_mapping": {
                        "mode": "snapshot_frozen_nav", "denominator": "portfolio_total_market_value_base",
                        "frozen_nav": total, "base_currency": weights.get("base_currency"),
                        "evaluation_epoch": weights.get("evaluation_epoch"),
                        "effective_max_weight": effective_max,
                        "not_dynamic_weight_trigger": True,
                    },
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
        "constraint_resolution_status": ("unresolved" if any(
            row["constraint_resolution"]["status"] != "complete" for row in rows) else "complete"),
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
