import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from advice_journal import load_entries, batch_update_outcomes

def sync_all(journal_path: str | None = None):
    entries = load_entries(journal_path)
    to_update = [e for e in entries if e.get("outcome_return_pct") is None or e.get("outcome_status") == "Open"]
    
    if not to_update:
        print("No entries need synchronization.")
        return

    symbols = sorted(list({e["stock_code"] for e in to_update}))
    print(f"Syncing prices for {len(symbols)} symbols: {', '.join(symbols)}")

    script_path = Path(__file__).parent / "yf.py"
    cmd = [sys.executable, str(script_path)] + symbols + ["--json", "--price-only", "--period", "6mo"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if not result.stdout.strip():
            print(f"Error: yf.py returned no output. Stderr: {result.stderr}")
            return
        market_data = json.loads(result.stdout)
    except Exception as e:
        print(f"Error fetching market data or parsing JSON: {e}")
        return

    history_map = {}
    for item in market_data:
        symbol = item.get("symbol")
        if "history" in item and isinstance(item["history"], list):
            history_map[symbol] = item["history"]
        else:
            summary_price = None
            if "summary" in item and item["summary"]:
                summary_price = item["summary"].get("last_close")
            if summary_price is not None:
                now_date = datetime.now().strftime("%Y-%m-%d")
                history_map[symbol] = [{"Date": now_date, "High": summary_price, "Low": summary_price, "Close": summary_price}]

    updates = {}
    now_iso = datetime.now().isoformat(timespec="seconds")
    for entry in to_update:
        symbol = entry["stock_code"]
        if symbol not in history_map:
            continue
            
        history = history_map[symbol]
        created_date_str = entry.get("created_at", "")[:10]
        
        valid_history = [row for row in history if row.get("Date", "") >= created_date_str]
        
        if not valid_history:
            continue
            
        stop_loss = entry.get("stop_loss")
        try: stop_loss = float(stop_loss) if stop_loss is not None else None
        except: stop_loss = None
        
        take_profit = entry.get("take_profit")
        try: take_profit = float(take_profit) if take_profit is not None else None
        except: take_profit = None
        
        outcome_status = "Open"
        outcome_price = valid_history[-1].get("Close")
        
        for day in valid_history:
            high = float(day.get("High", day.get("Close", 0)))
            low = float(day.get("Low", day.get("Close", 0)))
            
            if stop_loss is not None and low <= stop_loss:
                outcome_price = stop_loss
                outcome_status = "Stopped Out"
                break
                
            if take_profit is not None and high >= take_profit:
                outcome_price = take_profit
                outcome_status = "Target Reached"
                break
                
        updates[entry["entry_id"]] = {
            "outcome_price": outcome_price,
            "outcome_status": outcome_status,
            "outcome_date": now_iso
        }

    if not updates:
        print("No valid prices/history found for the pending symbols.")
        return

    journal_file = batch_update_outcomes(updates, journal_path=journal_path)
    print(f"Successfully updated {len(updates)} entries in {journal_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize advice outcomes with current market prices.")
    parser.add_argument("--journal-path", help="Path to the advice journal file.")
    args = parser.parse_args()
    sync_all(args.journal_path)
