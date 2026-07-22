import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def resolve_journal_path(path: str | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    configured = os.environ.get("PIA_ADVICE_JOURNAL")
    if configured:
        return Path(configured).expanduser()
    raise ValueError("journal path is required; pass --journal-path or set PIA_ADVICE_JOURNAL")


def _safe_get(data: Dict[str, Any], *keys: str, default=None):
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def build_journal_entry(data: Dict[str, Any], archive_path: str | None = None) -> Dict[str, Any]:
    stock_code = data.get("stock_code", "UNKNOWN")
    timestamp = datetime.now().isoformat(timespec="seconds")
    current_price = _safe_get(data, "dashboard", "data_perspective", "price_position", "current_price")
    portfolio = data.get("portfolio_context", {}) if isinstance(data.get("portfolio_context"), dict) else {}
    confidence_details = data.get("confidence_details", {}) if isinstance(data.get("confidence_details"), dict) else {}
    research_brief = data.get("research_brief", {}) if isinstance(data.get("research_brief"), dict) else {}
    benchmark = research_brief.get("benchmark", {}) if isinstance(research_brief.get("benchmark"), dict) else {}
    output_contract = research_brief.get("output_contract", {}) if isinstance(research_brief.get("output_contract"), dict) else {}
    evidence_items = data.get("evidence_items", [])
    evidence_json = json.dumps(evidence_items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_snapshot_hash = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()

    return {
        "entry_id": f"{stock_code}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "created_at": timestamp,
        "stock_code": stock_code,
        "stock_name": data.get("stock_name"),
        "market_type": data.get("market_type"),
        "research_mode": data.get("research_mode"),
        "decision_type": data.get("decision_type"),
        "operation_advice": data.get("operation_advice"),
        "confidence_level": data.get("confidence_level"),
        "confidence_score": confidence_details.get("score"),
        "as_of_date": research_brief.get("as_of_date"),
        "investment_horizon_days": research_brief.get("investment_horizon_days"),
        "benchmark_symbol": benchmark.get("symbol"),
        "benchmark_market": benchmark.get("market"),
        "position_direction": data.get("position_direction"),
        "transaction_cost_bps": output_contract.get("transaction_cost_bps"),
        "dual_trigger_policy": output_contract.get("dual_trigger_policy", "conservative"),
        "method_profile": research_brief.get("method_profile"),
        "core_hypothesis": research_brief.get("core_hypothesis"),
        "falsification_conditions": research_brief.get("falsification_conditions", []),
        "source_snapshot_hash": source_snapshot_hash,
        "dashboard_schema_version": "5.0",
        "current_price": current_price,
        "has_position": portfolio.get("has_position", False),
        "avg_cost": portfolio.get("avg_cost"),
        "quantity": portfolio.get("quantity"),
        "one_sentence": _safe_get(data, "dashboard", "core_conclusion", "one_sentence"),
        "holder_view": _safe_get(data, "position_advice", "holding_view"),
        "holder_action": _safe_get(data, "position_advice", "action_for_holder"),
        "watchlist_alerts": data.get("watchlist_alerts", []),
        "feedback_status": data.get("feedback_status", "pending"),
        "archive_path": archive_path,
        "stop_loss": _safe_get(data, "dashboard", "battle_plan", "sniper_points", "stop_loss"),
        "take_profit": _safe_get(data, "dashboard", "battle_plan", "sniper_points", "take_profit"),
        "outcome_status": None,
        "outcome_price": None,
        "outcome_date": None,
        "outcome_return_pct": None,
        "benchmark_return_pct": None,
        "net_excess_return_pct": None,
        "outcome_resolution_method": None,
        "outcome_resolution_timestamp": None,
        "calibration_quality": None,
        "dual_trigger_detected": False,
        "calibration_eligible": False,
        "calibration_exclusion_reason": "outcome not synchronized",
        "executed": None,
        "execution_price": None,
        "execution_date": None,
        "execution_timing": None
    }


def append_entry(data: Dict[str, Any], archive_path: str | None = None, journal_path: str | None = None) -> Path:
    path = resolve_journal_path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = build_journal_entry(data, archive_path=archive_path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def load_entries(path: str | None = None) -> List[Dict[str, Any]]:
    journal_path = resolve_journal_path(path)
    if not journal_path.exists():
        return []
    entries = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def update_outcome(
    entry_id: str,
    outcome_price: float,
    outcome_date: str,
    executed: bool,
    execution_price: float | None = None,
    execution_date: str | None = None,
    execution_timing: str | None = None,
    journal_path: str | None = None,
) -> Path:
    update = {
        "outcome_price": outcome_price,
        "outcome_date": outcome_date,
        "executed": executed,
    }
    if execution_price is not None:
        update["execution_price"] = execution_price
    if execution_date is not None:
        update["execution_date"] = execution_date
    if execution_timing is not None:
        update["execution_timing"] = execution_timing
    return batch_update_outcomes(
        {entry_id: update},
        journal_path=journal_path
    )


def batch_update_outcomes(updates: Dict[str, Dict[str, Any]], journal_path: str | None = None) -> Path:
    path = resolve_journal_path(journal_path)
    entries = load_entries(str(path))
    updated_count = 0
    for entry in entries:
        eid = entry.get("entry_id")
        if eid in updates:
            upd = updates[eid]
            if "outcome_price" in upd:
                entry["outcome_price"] = upd["outcome_price"]
            if "outcome_date" in upd:
                entry["outcome_date"] = upd["outcome_date"]
            if "outcome_status" in upd:
                entry["outcome_status"] = upd["outcome_status"]
            if "executed" in upd:
                entry["executed"] = upd["executed"]
            for field in [
                "outcome_return_pct",
                "benchmark_return_pct",
                "net_excess_return_pct",
                "calibration_eligible",
                "calibration_exclusion_reason",
                "outcome_resolution_method",
                "outcome_resolution_timestamp",
                "calibration_quality",
                "dual_trigger_detected",
                "dual_trigger_policy",
                "execution_price",
                "execution_date",
                "execution_timing",
            ]:
                if field in upd:
                    entry[field] = upd[field]

            execution_price = entry.get("execution_price")
            outcome_price = entry.get("outcome_price")
            if "outcome_return_pct" not in upd and execution_price not in (None, 0) and outcome_price is not None:
                try:
                    cp = float(execution_price)
                    op = float(outcome_price)
                    if cp != 0:
                        entry["outcome_return_pct"] = round((op - cp) / cp * 100, 2)
                except (TypeError, ValueError):
                    pass

            entry["feedback_status"] = "reviewed"
            updated_count += 1

    if updated_count > 0:
        path.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Advice journal utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("json_file")
    append_parser.add_argument("--archive-path")
    append_parser.add_argument("--journal-path")

    update_parser = subparsers.add_parser("update-outcome")
    update_parser.add_argument("entry_id")
    update_parser.add_argument("outcome_price", type=float)
    update_parser.add_argument("outcome_date")
    update_parser.add_argument("--executed", action="store_true")
    update_parser.add_argument("--execution-price", type=float)
    update_parser.add_argument("--execution-date")
    update_parser.add_argument("--execution-timing", choices=["open", "close"])
    update_parser.add_argument("--journal-path")

    args = parser.parse_args()

    if args.command == "append":
        payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        result = append_entry(payload, archive_path=args.archive_path, journal_path=args.journal_path)
        print(f"journal updated: {result}")
    elif args.command == "update-outcome":
        result = update_outcome(
            args.entry_id,
            args.outcome_price,
            args.outcome_date,
            args.executed,
            execution_price=args.execution_price,
            execution_date=args.execution_date,
            execution_timing=args.execution_timing,
            journal_path=args.journal_path,
        )
        print(f"journal updated: {result}")
