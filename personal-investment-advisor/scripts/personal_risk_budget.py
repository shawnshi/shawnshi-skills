"""Compare an existing scenario report with explicitly user-confirmed loss limits.

No positions discovery, prediction, target weights, or execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from source_timing_contract import aware

VERSION = "pia_personal_risk_budget_v1"
MAX_BYTES = 32 * 1024 * 1024


def fraction(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def evaluate(report: Any, budget: Any, *, report_sha256: str) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(report, dict) or report.get("valid") is not True or report.get("status") != "ok" or report.get("scenario_contract_version") != "2.0":
        errors.append("scenario report must be complete v2, not an archive or partial risk diagnostic")
    if not isinstance(budget, dict) or budget.get("schema_version") != VERSION or budget.get("source_type") != "user_confirmed" or budget.get("scenario_report_sha256") != report_sha256:
        errors.append("budget requires user confirmation and exact bound scenario report SHA-256")
    if errors:
        return {"status": "invalid_input", "errors": errors}
    try:
        if aware(budget.get("confirmed_at")) > datetime.now(timezone.utc):
            errors.append("budget confirmation cannot be in the future")
        snapshot = report["weight_snapshot"]
        as_of = aware(snapshot["as_of"])
        if as_of > datetime.now(timezone.utc):
            errors.append("weight snapshot cannot be in the future")
    except (ValueError, TypeError, KeyError):
        errors.append("budget and snapshot require timezone-aware timestamp evidence")
        as_of = None
    horizon_policy = budget.get("horizon_policy", "finite")
    if horizon_policy == "finite":
        if type(budget.get("horizon_days")) is not int or budget["horizon_days"] <= 0:
            errors.append("finite horizon requires positive integer horizon_days")
    elif horizon_policy == "unbounded":
        if "horizon_days" not in budget or budget["horizon_days"] is not None:
            errors.append("unbounded horizon requires explicit null horizon_days")
    else:
        errors.append("horizon_policy must be finite or unbounded")
    fields = ("max_loss_fraction", "max_single_non_cash_weight", "minimum_cash_weight")
    for field in fields:
        if not fraction(budget.get(field)):
            errors.append(f"{field} must be a ratio in [0,1]")
    snapshot = report.get("weight_snapshot")
    weights = snapshot.get("reconciled_weights") if isinstance(snapshot, dict) else None
    if not isinstance(weights, dict) or not weights or any(not isinstance(key, str) or not fraction(value) for key, value in weights.items()) or not math.isclose(sum(weights.values()), 1, rel_tol=0, abs_tol=1e-6):
        errors.append("weight_snapshot must contain a complete normalized weight map")
        weights = {}
    scenarios = report.get("scenario_results")
    if not isinstance(scenarios, list) or not scenarios or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"] or not type(item.get("portfolio_return_after_cost")) in (int, float) or not math.isfinite(item["portfolio_return_after_cost"]) for item in scenarios):
        errors.append("scenarios require complete named after-cost portfolio returns")
        scenarios = []
    names = [item["name"] for item in scenarios]
    expected = budget.get("required_scenarios")
    if not isinstance(expected, list) or not expected or any(not isinstance(name, str) or not name for name in expected) or len(expected) != len(set(expected)) or set(expected) != set(names) or len(names) != len(set(names)):
        errors.append("required_scenarios must exactly cover unique reported scenarios")
    if errors:
        return {"status": "invalid_input", "errors": errors}
    cash_weight = sum(weight for symbol, weight in weights.items() if symbol == "CASH" or symbol.startswith("CASH_"))
    max_non_cash = max((weight for symbol, weight in weights.items() if symbol != "CASH" and not symbol.startswith("CASH_")), default=0.0)
    worst = min(item["portfolio_return_after_cost"] for item in scenarios)
    checks = {
        "scenario_loss": max(0.0, -worst) <= budget["max_loss_fraction"],
        "single_instrument": max_non_cash <= budget["max_single_non_cash_weight"],
        "cash_weight": cash_weight >= budget["minimum_cash_weight"],
    }
    return {
        "status": "complete", "detail_status": "user_budget_compared_to_supplied_scenarios",
        "budget_status": "within_supplied_scenarios" if all(checks.values()) else "budget_boundary_breached",
        "scenario_report_sha256": report_sha256, "snapshot_as_of": as_of.isoformat() if as_of else None,
        "horizon_policy": horizon_policy, "horizon_days": budget["horizon_days"], "checks": checks,
        "measurements": {"worst_after_cost_return": worst, "cash_weight": cash_weight, "max_non_cash_instrument_weight": max_non_cash},
        "limitations": ["Only the explicitly supplied scenarios were evaluated; an unmodeled loss may be larger. An unbounded personal holding horizon does not prove scenario coverage across time.", "Weights are bound to the report snapshot and are not claimed current without separate quote freshness checks.", "No industry, style, household liquidity, account value or liability inference is performed; no trade action follows."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline personal loss-budget check for a v2 scenario report")
    parser.add_argument("scenario_report", type=Path)
    parser.add_argument("budget", type=Path)
    args = parser.parse_args()
    try:
        values = []
        for path in (args.scenario_report, args.budget):
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("input_size_limit")
            values.append((json.loads(raw.decode("utf-8")), raw))
        report, report_raw = values[0]
        result = evaluate(report, values[1][0], report_sha256=hashlib.sha256(report_raw).hexdigest())
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "invalid_input", "errors": [f"input unreadable: {type(exc).__name__}: {exc}"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 3


if __name__ == "__main__":
    sys.exit(main())
