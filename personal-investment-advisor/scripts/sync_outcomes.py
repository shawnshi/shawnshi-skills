import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from advice_journal import batch_update_outcomes, load_entries


OUTCOME_EVIDENCE_VERSION = "1.0"


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _history_coverage(history: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _sorted_history(history)
    return {
        "row_count": len(rows),
        "first_timestamp": str(rows[0]["Date"]) if rows else None,
        "last_timestamp": str(rows[-1]["Date"]) if rows else None,
        "content_sha256": _canonical_digest(rows),
    }


def _outcome_evidence(
    *,
    source_provider: str | None,
    source_locator: str | None,
    daily_interval: str,
    asset_history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]],
    result_summary: dict[str, Any],
    intraday_sequence: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not source_provider or not source_locator or daily_interval != "1d":
        return None
    if intraday_sequence is not None:
        trigger_timestamp = _row_datetime(
            {"Date": intraday_sequence.get("trigger_timestamp")}
        )
        benchmark_timestamp = _row_datetime(
            {"Date": intraday_sequence.get("benchmark_timestamp")}
        )
        summary = intraday_sequence.get("sequence_summary")
        if (
            intraday_sequence.get("provider") != source_provider
            or intraday_sequence.get("locator") != source_locator
            or intraday_sequence.get("interval") in (None, "", "1d")
            or intraday_sequence.get("first_trigger")
            not in {"downside_boundary", "upside_boundary"}
            or trigger_timestamp is None
            or trigger_timestamp.tzinfo is None
            or benchmark_timestamp is None
            or benchmark_timestamp.tzinfo is None
            or not isinstance(summary, dict)
            or summary.get("interval") != intraday_sequence.get("interval")
            or not isinstance(summary.get("rows_on_trigger_date"), int)
            or summary["rows_on_trigger_date"] <= 0
        ):
            return None
    evidence = {
        "contract_version": OUTCOME_EVIDENCE_VERSION,
        "generator": "sync_outcomes.py",
        "source": {
            "provider": source_provider,
            "locator": source_locator,
            "daily_interval": daily_interval,
        },
        "daily_coverage": {
            "asset": _history_coverage(asset_history),
            "benchmark": _history_coverage(benchmark_history),
        },
        "result_summary": result_summary,
        "intraday_sequence": intraday_sequence,
    }
    evidence["evidence_sha256"] = _canonical_digest(evidence)
    return evidence


def _row_date(row: dict[str, Any]) -> date:
    return date.fromisoformat(str(row["Date"])[:10])


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _sorted_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((row for row in history if row.get("Date")), key=_row_date)


def _first_on_or_after(history: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    return next((row for row in _sorted_history(history) if _row_date(row) >= target), None)


def _row_datetime(row: dict[str, Any]) -> datetime | None:
    raw = str(row.get("Date") or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _first_intraday_on_or_after(
    history: list[dict[str, Any]], target: datetime
) -> dict[str, Any] | None:
    candidates = []
    for row in history:
        timestamp = _row_datetime(row)
        if timestamp is not None and timestamp >= target:
            candidates.append((timestamp, row))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _resolve_dual_trigger(
    intraday_history: list[dict[str, Any]],
    trigger_date: date,
    direction: str,
    stop_loss: float,
    take_profit: float,
    policy: str,
    research_only: bool = False,
    intraday_interval: str = "5m",
) -> dict[str, Any]:
    stop_status = "Downside Boundary Reached" if research_only else "Stopped Out"
    target_status = "Upside Boundary Reached" if research_only else "Target Reached"
    if policy == "conservative":
        return {
            "resolved": True,
            "exit_price": stop_loss,
            "outcome_status": stop_status,
            "resolution_method": "daily_ohlc_conservative_stop_first",
            "calibration_quality": "assumption_based_conservative",
            "trigger_timestamp": None,
            "sensitivity_only": True,
        }

    rows = sorted(
        (row for row in intraday_history if row.get("Date") and _row_date(row) == trigger_date),
        key=lambda row: str(row["Date"]),
    )
    for row_index, row in enumerate(rows):
        row_timestamp = _row_datetime(row)
        if row_timestamp is None or row_timestamp.tzinfo is None:
            return {
                "resolved": False,
                "error": "intraday history timestamps must be timezone-aware",
            }
        high = _finite_float(row.get("High", row.get("Close")))
        low = _finite_float(row.get("Low", row.get("Close")))
        if high is None or low is None or high <= 0 or low <= 0:
            return {
                "resolved": False,
                "error": "intraday history prices must be finite and positive",
            }
        stop_hit = low <= stop_loss if direction == "long" else high >= stop_loss
        target_hit = high >= take_profit if direction == "long" else low <= take_profit
        if stop_hit and not target_hit:
            return {
                "resolved": True,
                "exit_price": stop_loss,
                "outcome_status": stop_status,
                "resolution_method": "intraday_first_trigger",
                "calibration_quality": "observed_intraday",
                "trigger_timestamp": str(row["Date"]),
                "first_trigger": "downside_boundary",
                "sequence_summary": {
                    "interval": intraday_interval,
                    "trigger_date": trigger_date.isoformat(),
                    "rows_on_trigger_date": len(rows),
                    "rows_reviewed_through_trigger": row_index + 1,
                    "first_timestamp": str(rows[0]["Date"]),
                    "last_timestamp": str(rows[-1]["Date"]),
                    "trigger_bar": {"high": high, "low": low},
                    "content_sha256": _canonical_digest(rows),
                },
                "sensitivity_only": False,
            }
        if target_hit and not stop_hit:
            return {
                "resolved": True,
                "exit_price": take_profit,
                "outcome_status": target_status,
                "resolution_method": "intraday_first_trigger",
                "calibration_quality": "observed_intraday",
                "trigger_timestamp": str(row["Date"]),
                "first_trigger": "upside_boundary",
                "sequence_summary": {
                    "interval": intraday_interval,
                    "trigger_date": trigger_date.isoformat(),
                    "rows_on_trigger_date": len(rows),
                    "rows_reviewed_through_trigger": row_index + 1,
                    "first_timestamp": str(rows[0]["Date"]),
                    "last_timestamp": str(rows[-1]["Date"]),
                    "trigger_bar": {"high": high, "low": low},
                    "content_sha256": _canonical_digest(rows),
                },
                "sensitivity_only": False,
            }
        if stop_hit and target_hit:
            break

    return {
        "resolved": False,
        "error": (
            "daily bar hit both observation boundaries; intraday order is unresolved"
            if research_only
            else "daily bar hit stop and target; intraday order is unresolved"
        ),
    }


def _missing_calibration_fields(entry: dict[str, Any]) -> list[str]:
    required = [
        "execution_price",
        "execution_date",
        "investment_horizon_days",
        "benchmark_symbol",
        "position_direction",
        "transaction_cost_bps",
        "execution_timing",
    ]
    return [field for field in required if entry.get(field) in (None, "")]


def _is_research_sample(entry: dict[str, Any]) -> bool:
    return (
        entry.get("calibration_sample_type") == "research"
        or entry.get("research_scope") == "research_only"
    )


def _research_boundary_values(
    entry: dict[str, Any],
) -> tuple[float | None, float | None, str | None]:
    boundaries = entry.get("observation_boundaries")
    if boundaries in (None, {}):
        return None, None, None
    if not isinstance(boundaries, dict):
        return None, None, "observation_boundaries must be an object"

    values: dict[str, float | None] = {
        "downside_boundary": None,
        "upside_boundary": None,
    }
    expected_operators = {
        "downside_boundary": "lte",
        "upside_boundary": "gte",
    }
    currencies = set()
    for role, operator in expected_operators.items():
        boundary = boundaries.get(role)
        if boundary is None:
            continue
        if not isinstance(boundary, dict):
            return None, None, f"{role} must be an object"
        value = _finite_float(boundary.get("value"))
        if (
            boundary.get("role") != role
            or boundary.get("operator") != operator
            or boundary.get("authority_status") != "user_confirmed"
            or value is None
            or value <= 0
        ):
            return None, None, f"{role} is not a valid user-confirmed observation boundary"
        currency = str(boundary.get("currency") or "").strip().upper()
        if currency:
            currencies.add(currency)
        values[role] = value
    if len(currencies) > 1:
        return None, None, "observation boundary currencies do not match"
    lower = values["downside_boundary"]
    upper = values["upside_boundary"]
    if lower is not None and upper is not None and lower >= upper:
        return None, None, "downside observation boundary must be below upside boundary"
    return lower, upper, None


def build_outcome_update(
    entry: dict[str, Any],
    asset_history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]],
    intraday_history: list[dict[str, Any]] | None = None,
    benchmark_intraday_history: list[dict[str, Any]] | None = None,
    dual_trigger_policy: str | None = None,
    today: date | None = None,
    source_provider: str | None = None,
    source_locator: str | None = None,
    daily_interval: str = "1d",
    intraday_interval: str = "5m",
) -> dict[str, Any]:
    research_only = _is_research_sample(entry)
    sample_type = "research" if research_only else "execution"
    policy = dual_trigger_policy or entry.get("dual_trigger_policy") or "exclude"
    if policy not in {"conservative", "exclude"}:
        return {
            "calibration_sample_type": sample_type,
            "calibration_eligible": False,
            "calibration_exclusion_reason": "dual_trigger_policy must be conservative or exclude",
        }

    if research_only:
        anchor_value = entry.get("research_anchor_date") or entry.get("as_of_date")
        missing = [
            field
            for field, value in [
                ("research_anchor_date", anchor_value),
                ("investment_horizon_days", entry.get("investment_horizon_days")),
                ("benchmark_symbol", entry.get("benchmark_symbol")),
            ]
            if value in (None, "")
        ]
        if missing:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": f"missing research fields: {', '.join(missing)}",
            }
        try:
            requested_anchor_date = date.fromisoformat(str(anchor_value)[:10])
            horizon_days = int(entry["investment_horizon_days"])
        except (TypeError, ValueError):
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "invalid research anchor or horizon field",
            }
        if horizon_days <= 0:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "research horizon must be positive",
            }
        stop_loss, take_profit, boundary_error = _research_boundary_values(entry)
        if boundary_error:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": boundary_error,
            }
        asset_start = _first_on_or_after(asset_history, requested_anchor_date)
        if asset_start is None:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "asset history unavailable on or after research anchor date",
            }
        execution_price = _finite_float(asset_start.get("Close"))
        execution_date = _row_date(asset_start)
        execution_timing = "close"
        transaction_cost_bps = 0.0
        direction = "long"
        return_definition = "asset_return_minus_benchmark_return_without_execution_assumptions"
    else:
        if entry.get("executed") is not True:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "not executed and not a research_only sample",
            }
        missing = _missing_calibration_fields(entry)
        if missing:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": f"missing fields: {', '.join(missing)}",
            }
        try:
            execution_price = _finite_float(entry["execution_price"])
            execution_date = date.fromisoformat(str(entry["execution_date"])[:10])
            horizon_days = int(entry["investment_horizon_days"])
            transaction_cost_bps = _finite_float(entry["transaction_cost_bps"])
        except (TypeError, ValueError):
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "invalid execution, horizon, or transaction-cost field",
            }
        execution_timing = str(entry.get("execution_timing") or "").lower()
        if execution_timing not in {"open", "close"}:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "execution_timing must be open or close",
            }
        direction = entry["position_direction"]
        if direction not in {"long", "short"}:
            return {
                "calibration_sample_type": sample_type,
                "calibration_eligible": False,
                "calibration_exclusion_reason": "position_direction must be long or short",
            }
        stop_loss = _finite_float(entry["stop_loss"]) if entry.get("stop_loss") not in (None, "") else None
        take_profit = _finite_float(entry["take_profit"]) if entry.get("take_profit") not in (None, "") else None
        if entry.get("stop_loss") not in (None, "") and stop_loss is None:
            return {"calibration_sample_type": sample_type, "calibration_eligible": False, "calibration_exclusion_reason": "stop_loss must be finite"}
        if entry.get("take_profit") not in (None, "") and take_profit is None:
            return {"calibration_sample_type": sample_type, "calibration_eligible": False, "calibration_exclusion_reason": "take_profit must be finite"}
        if stop_loss is not None and stop_loss <= 0:
            return {"calibration_sample_type": sample_type, "calibration_eligible": False, "calibration_exclusion_reason": "stop_loss must be positive"}
        if take_profit is not None and take_profit <= 0:
            return {"calibration_sample_type": sample_type, "calibration_eligible": False, "calibration_exclusion_reason": "take_profit must be positive"}
        return_definition = "direction_adjusted_return_minus_benchmark_return_and_declared_cost"

    if execution_price is None or transaction_cost_bps is None:
        return {
            "calibration_sample_type": sample_type,
            "calibration_eligible": False,
            "calibration_exclusion_reason": "calibration start price and transaction cost must be finite",
        }
    if execution_price <= 0 or horizon_days <= 0 or transaction_cost_bps < 0:
        return {
            "calibration_sample_type": sample_type,
            "calibration_eligible": False,
            "calibration_exclusion_reason": "calibration start price and horizon must be positive; cost cannot be negative",
        }

    target_date = execution_date + timedelta(days=horizon_days)
    today = today or date.today()
    asset_rows = [
        row
        for row in _sorted_history(asset_history)
        if (
            _row_date(row) > execution_date
            or (execution_timing == "open" and _row_date(row) == execution_date)
        )
    ]
    benchmark_rows = [row for row in _sorted_history(benchmark_history) if _row_date(row) >= execution_date]
    if not asset_rows or not benchmark_rows:
        return {
            "calibration_sample_type": sample_type,
            "calibration_start_date": execution_date.isoformat(),
            "calibration_start_price": round(float(execution_price), 6),
            "calibration_eligible": False,
            "calibration_exclusion_reason": "asset or benchmark history unavailable after calibration start date",
        }
    exit_price = None
    exit_date = None
    outcome_status = "Open"
    resolution_method = None
    calibration_quality = "observed_daily"
    dual_trigger_detected = False
    trigger_timestamp = None
    sensitivity_only = False
    intraday_sequence = None
    stop_status = "Downside Boundary Reached" if research_only else "Stopped Out"
    target_status = "Upside Boundary Reached" if research_only else "Target Reached"
    for row in asset_rows:
        row_date = _row_date(row)
        if row_date > target_date:
            break
        high = _finite_float(row.get("High", row.get("Close")))
        low = _finite_float(row.get("Low", row.get("Close")))
        if high is None or low is None or high <= 0 or low <= 0:
            return {"calibration_eligible": False, "calibration_exclusion_reason": "asset history prices must be finite and positive"}
        stop_hit = stop_loss is not None and (low <= stop_loss if direction == "long" else high >= stop_loss)
        target_hit = take_profit is not None and (high >= take_profit if direction == "long" else low <= take_profit)
        if stop_hit and target_hit:
            dual_trigger_detected = True
            resolution = _resolve_dual_trigger(
                intraday_history or [],
                row_date,
                direction,
                stop_loss,
                take_profit,
                policy,
                research_only=research_only,
                intraday_interval=intraday_interval,
            )
            if (
                not resolution["resolved"]
                and policy == "exclude"
                and entry.get("dual_trigger_sensitivity_policy") == "conservative"
            ):
                resolution = _resolve_dual_trigger(
                    intraday_history or [],
                    row_date,
                    direction,
                    stop_loss,
                    take_profit,
                    "conservative",
                    research_only=research_only,
                    intraday_interval=intraday_interval,
                )
            if not resolution["resolved"]:
                return {
                    "outcome_status": None,
                    "outcome_price": None,
                    "outcome_date": None,
                    "outcome_return_pct": None,
                    "benchmark_return_pct": None,
                    "net_excess_return_pct": None,
                    "outcome_resolution_method": None,
                    "outcome_resolution_timestamp": None,
                    "calibration_quality": "unresolved_daily_dual_trigger",
                    "sensitivity_analysis": None,
                    "calibration_sample_type": sample_type,
                    "calibration_start_date": execution_date.isoformat(),
                    "calibration_start_price": round(float(execution_price), 6),
                    "return_definition": return_definition,
                    "calibration_eligible": False,
                    "calibration_exclusion_reason": resolution["error"],
                    "dual_trigger_detected": True,
                    "dual_trigger_policy": policy,
                }
            exit_price = resolution["exit_price"]
            exit_date = row_date
            outcome_status = resolution["outcome_status"]
            resolution_method = resolution["resolution_method"]
            calibration_quality = resolution["calibration_quality"]
            trigger_timestamp = resolution.get("trigger_timestamp")
            if resolution_method == "intraday_first_trigger":
                intraday_sequence = {
                    "provider": source_provider,
                    "locator": source_locator,
                    "interval": intraday_interval,
                    "first_trigger": resolution.get("first_trigger"),
                    "trigger_timestamp": trigger_timestamp,
                    "sequence_summary": resolution.get("sequence_summary"),
                }
            sensitivity_only = resolution.get("sensitivity_only") is True
            break
        if stop_hit:
            exit_price, exit_date, outcome_status = stop_loss, row_date, stop_status
            resolution_method = "daily_single_trigger"
            break
        if target_hit:
            exit_price, exit_date, outcome_status = take_profit, row_date, target_status
            resolution_method = "daily_single_trigger"
            break

    if exit_price is None:
        horizon_row = _first_on_or_after(asset_rows, target_date)
        if horizon_row is None or target_date > today:
            return {
                "calibration_sample_type": sample_type,
                "calibration_start_date": execution_date.isoformat(),
                "calibration_start_price": round(float(execution_price), 6),
                "calibration_eligible": False,
                "calibration_exclusion_reason": "fixed evaluation horizon has not completed",
                "outcome_status": "Open",
            }
        exit_price = _finite_float(horizon_row.get("Close"))
        if exit_price is None or exit_price <= 0:
            return {"calibration_eligible": False, "calibration_exclusion_reason": "asset exit price must be finite and positive"}
        exit_date = _row_date(horizon_row)
        outcome_status = "Horizon Reached"
        resolution_method = "fixed_horizon_close"

    benchmark_start = _first_on_or_after(benchmark_rows, execution_date)
    benchmark_exit = _first_on_or_after(benchmark_rows, exit_date)
    if benchmark_start is None or benchmark_exit is None:
        return {
            "calibration_eligible": False,
            "calibration_exclusion_reason": "benchmark prices unavailable for execution or exit date",
        }
    benchmark_start_field = "Open" if execution_timing == "open" else "Close"
    benchmark_start_price = _finite_float(benchmark_start.get(benchmark_start_field))
    if resolution_method == "intraday_first_trigger":
        parsed_trigger_time = _row_datetime({"Date": trigger_timestamp})
        benchmark_intraday_row = (
            _first_intraday_on_or_after(benchmark_intraday_history or [], parsed_trigger_time)
            if parsed_trigger_time is not None
            else None
        )
        if benchmark_intraday_row is None:
            return {
                "calibration_eligible": False,
                "calibration_exclusion_reason": "benchmark intraday price is required for an intraday-resolved trigger",
                "dual_trigger_detected": True,
                "dual_trigger_policy": policy,
            }
        benchmark_exit_price = _finite_float(benchmark_intraday_row.get("Close"))
        if intraday_sequence is not None:
            intraday_sequence["benchmark_timestamp"] = str(
                benchmark_intraday_row.get("Date") or ""
            )
    else:
        benchmark_exit_price = _finite_float(benchmark_exit.get("Close"))
    if benchmark_start_price is None or benchmark_exit_price is None or benchmark_start_price <= 0 or benchmark_exit_price <= 0:
        return {
            "calibration_eligible": False,
            "calibration_exclusion_reason": "benchmark prices must be finite and positive",
        }
    asset_return_pct = (float(exit_price) - execution_price) / execution_price * 100
    benchmark_return_pct = (benchmark_exit_price - benchmark_start_price) / benchmark_start_price * 100
    if research_only:
        net_excess_return_pct = asset_return_pct - benchmark_return_pct
    else:
        direction_sign = 1 if direction == "long" else -1
        net_excess_return_pct = direction_sign * asset_return_pct - benchmark_return_pct - transaction_cost_bps / 100
    if sensitivity_only:
        sensitivity_analysis = {
            "policy": "conservative",
            "outcome_price": round(float(exit_price), 6),
            "outcome_date": exit_date.isoformat(),
            "outcome_status": outcome_status,
            "outcome_return_pct": round(asset_return_pct, 4),
            "benchmark_return_pct": round(benchmark_return_pct, 4),
            "net_excess_return_pct": round(net_excess_return_pct, 4),
            "outcome_resolution_method": resolution_method,
            "calibration_quality": calibration_quality,
            "return_definition": return_definition,
        }
        return {
            "outcome_price": None,
            "outcome_date": None,
            "outcome_status": None,
            "outcome_return_pct": None,
            "benchmark_return_pct": None,
            "net_excess_return_pct": None,
            "outcome_resolution_method": None,
            "outcome_resolution_timestamp": None,
            "calibration_quality": calibration_quality,
            "calibration_sample_type": sample_type,
            "calibration_start_date": execution_date.isoformat(),
            "calibration_start_price": round(float(execution_price), 6),
            "return_definition": return_definition,
            "dual_trigger_detected": True,
            "dual_trigger_policy": policy,
            "sensitivity_analysis": sensitivity_analysis,
            "calibration_eligible": False,
            "calibration_exclusion_reason": (
                "unresolved daily dual trigger is excluded from formal calibration; "
                "conservative stop-first result is sensitivity only"
            ),
        }
    result_summary = {
        "calibration_start_date": execution_date.isoformat(),
        "calibration_start_price": round(float(execution_price), 6),
        "outcome_date": exit_date.isoformat(),
        "outcome_price": round(float(exit_price), 6),
        "outcome_return_pct": round(asset_return_pct, 4),
        "benchmark_return_pct": round(benchmark_return_pct, 4),
        "net_excess_return_pct": round(net_excess_return_pct, 4),
        "outcome_resolution_method": resolution_method,
        "dual_trigger_detected": dual_trigger_detected,
    }
    evidence = _outcome_evidence(
        source_provider=source_provider,
        source_locator=source_locator,
        daily_interval=daily_interval,
        asset_history=asset_history,
        benchmark_history=benchmark_history,
        result_summary=result_summary,
        intraday_sequence=intraday_sequence,
    )
    return {
        "outcome_price": round(float(exit_price), 6),
        "outcome_date": exit_date.isoformat(),
        "outcome_status": outcome_status,
        "outcome_return_pct": round(asset_return_pct, 4),
        "benchmark_return_pct": round(benchmark_return_pct, 4),
        "net_excess_return_pct": round(net_excess_return_pct, 4),
        "outcome_resolution_method": resolution_method,
        "outcome_resolution_timestamp": trigger_timestamp,
        "calibration_quality": calibration_quality,
        "calibration_sample_type": sample_type,
        "calibration_start_date": execution_date.isoformat(),
        "calibration_start_price": round(float(execution_price), 6),
        "return_definition": return_definition,
        "sensitivity_analysis": None,
        "dual_trigger_detected": dual_trigger_detected,
        "dual_trigger_policy": policy,
        "calibration_eligible": evidence is not None,
        "calibration_exclusion_reason": (
            None
            if evidence is not None
            else "verified sync_outcomes source and coverage evidence is required"
        ),
        "outcome_evidence": evidence,
    }


def _fetch_histories(
    symbols: list[str], period: str = "5y", interval: str = "1d"
) -> dict[str, list[dict[str, Any]]]:
    script_path = Path(__file__).parent / "yf.py"
    command = [
        sys.executable,
        str(script_path),
        *symbols,
        "--json",
        "--price-only",
        "--period",
        period,
        "--interval",
        interval,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"yf.py failed: {result.stderr.strip()}")
    market_data = json.loads(result.stdout)
    return {
        item["symbol"]: item.get("history", [])
        for item in market_data
        if item.get("symbol") and isinstance(item.get("history"), list)
    }


def sync_all(journal_path: str | None = None, dual_trigger_policy: str | None = None) -> None:
    entries = load_entries(journal_path)
    pending = [entry for entry in entries if entry.get("calibration_eligible") is not True]
    if not pending:
        print("No entries need synchronization.")
        return
    symbols = sorted(
        {
            symbol
            for entry in pending
            for symbol in [entry.get("stock_code"), entry.get("benchmark_symbol")]
            if symbol
        }
    )
    histories = _fetch_histories(symbols)
    try:
        intraday_histories = _fetch_histories(symbols, period="60d", interval="5m")
    except RuntimeError:
        intraday_histories = {}
    updates = {}
    for entry in pending:
        asset_history = histories.get(entry.get("stock_code"), [])
        benchmark_history = histories.get(entry.get("benchmark_symbol"), [])
        updates[entry["entry_id"]] = build_outcome_update(
            entry,
            asset_history,
            benchmark_history,
            intraday_history=intraday_histories.get(entry.get("stock_code"), []),
            benchmark_intraday_history=intraday_histories.get(entry.get("benchmark_symbol"), []),
            dual_trigger_policy=dual_trigger_policy,
            source_provider="Yahoo Finance",
            source_locator="yf.py/yfinance chart history",
            daily_interval="1d",
            intraday_interval="5m",
        )
    journal_file = batch_update_outcomes(updates, journal_path=journal_path)
    print(f"updated {len(updates)} entries in {journal_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize benchmark-aware fixed-horizon outcomes.")
    parser.add_argument("--journal-path", help="Path to the advice journal file.")
    parser.add_argument(
        "--dual-trigger-policy",
        choices=["conservative", "exclude"],
        default="exclude",
        help=(
            "Formal default is exclude. conservative produces sensitivity-only results "
            "and never makes a dual-trigger sample calibration-eligible."
        ),
    )
    args = parser.parse_args()
    sync_all(args.journal_path, dual_trigger_policy=args.dual_trigger_policy)
