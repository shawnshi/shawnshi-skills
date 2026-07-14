import argparse
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
        "executed": None
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


def update_outcome(entry_id: str, outcome_price: float, outcome_date: str, executed: bool, journal_path: str | None = None) -> Path:
    return batch_update_outcomes(
        {entry_id: {"outcome_price": outcome_price, "outcome_date": outcome_date, "executed": executed}},
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

            current_price = entry.get("current_price")
            outcome_price = entry.get("outcome_price")
            if current_price not in (None, 0) and outcome_price is not None:
                try:
                    cp = float(current_price)
                    op = float(outcome_price)
                    if cp != 0:
                        entry["outcome_return_pct"] = round((op - cp) / cp * 100, 2)
                except ValueError:
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
    update_parser.add_argument("--journal-path")

    args = parser.parse_args()

    if args.command == "append":
        payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        result = append_entry(payload, archive_path=args.archive_path, journal_path=args.journal_path)
        print(f"journal updated: {result}")
    elif args.command == "update-outcome":
        result = update_outcome(args.entry_id, args.outcome_price, args.outcome_date, args.executed, journal_path=args.journal_path)
        print(f"journal updated: {result}")
