import argparse
import csv
import json
import os
from pathlib import Path

def resolve_positions_file(path: str | None) -> Path:
    configured = path or os.environ.get("PIA_POSITIONS_FILE")
    if not configured:
        raise ValueError("positions file is required; pass --positions-file or set PIA_POSITIONS_FILE")
    return Path(configured).expanduser()

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()

def sync_broker_data(csv_path: str, positions_file: str = None, cash_cny: float = None, cash_usd: float = None):
    pos_file = resolve_positions_file(positions_file)
    data = load_json(pos_file)
    positions = data.get("positions", [])
    
    # 1. Map existing positions
    pos_map = {normalize_symbol(p.get("symbol")): p for p in positions}
    
    # 2. Parse CSV and update
    if csv_path:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = normalize_symbol(row.get("symbol"))
                if not sym:
                    continue
                q = float(row.get("quantity", 0))
                cost = float(row.get("avg_cost", 0))
                
                if sym in pos_map:
                    pos_map[sym]["quantity"] = q
                    pos_map[sym]["avg_cost"] = cost
                else:
                    new_pos = {
                        "symbol": sym,
                        "name": row.get("name", sym),
                        "quantity": q,
                        "avg_cost": cost,
                        "currency": row.get("currency", "CNY").upper(),
                        "market_type": row.get("market_type", "A股"),
                        "opened_at": row.get("opened_at", ""),
                        "current_weight": 0.0,
                        "target_weight": 0.0,
                        "max_weight": 0.0,
                        "thesis": "Auto-imported from broker statement"
                    }
                    positions.append(new_pos)
                    pos_map[sym] = new_pos

    # 3. Handle Cash
    if cash_cny is not None:
        _update_cash(positions, pos_map, "CASH_CNY", "人民币现金", cash_cny, "CNY")
    if cash_usd is not None:
        _update_cash(positions, pos_map, "CASH_USD", "美元现金", cash_usd, "USD")
        
    data["positions"] = positions
    save_json(pos_file, data)
    print(f"Sync complete. Updated {pos_file}")

def _update_cash(positions, pos_map, symbol, name, amount, currency):
    if symbol in pos_map:
        pos_map[symbol]["quantity"] = amount
    else:
        positions.append({
            "symbol": symbol,
            "name": name,
            "quantity": amount,
            "avg_cost": 1.0,
            "currency": currency,
            "market_type": "CASH",
            "opened_at": "",
            "current_weight": 0.0,
            "target_weight": 0.0,
            "max_weight": 0.0,
            "thesis": "Portfolio liquidity / dry powder"
        })

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync portfolio with broker CSV or cash balances")
    parser.add_argument("--csv", help="Path to broker statement CSV")
    parser.add_argument("--cash-cny", type=float, help="Update CNY cash balance")
    parser.add_argument("--cash-usd", type=float, help="Update USD cash balance")
    parser.add_argument("--positions-file", help="Positions JSON path; alternatively set PIA_POSITIONS_FILE")
    args = parser.parse_args()
    
    try:
        sync_broker_data(args.csv, args.positions_file, args.cash_cny, args.cash_usd)
    except ValueError as exc:
        parser.error(str(exc))
