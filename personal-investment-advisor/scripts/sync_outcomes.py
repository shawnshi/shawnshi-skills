import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from advice_journal import load_entries, batch_update_outcomes

def sync_all(journal_path: str | None = None):
    entries = load_entries(journal_path)
    # Filter entries that need updating (outcome is missing)
    to_update = [e for e in entries if e.get("outcome_return_pct") is None]
    
    if not to_update:
        print("No entries need synchronization.")
        return

    symbols = sorted(list({e["stock_code"] for e in to_update}))
    print(f"Syncing prices for {len(symbols)} symbols: {', '.join(symbols)}")

    # Call yf.py to get latest prices
    script_path = Path(__file__).parent / "yf.py"
    cmd = [sys.executable, str(script_path)] + symbols + ["--json", "--price-only", "--lean"]
    
    try:
        # Using check=False because yf.py might have partial failures (A-share fallback)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if not result.stdout.strip():
            print(f"Error: yf.py returned no output. Stderr: {result.stderr}")
            return
        market_data = json.loads(result.stdout)
    except Exception as e:
        print(f"Error fetching market data or parsing JSON: {e}")
        return

    # Map symbol to current price
    price_map = {}
    for item in market_data:
        symbol = item.get("symbol")
        # Try summary first, then info
        price = None
        if "summary" in item and item["summary"]:
            price = item["summary"].get("last_close")
        if price is None and "info" in item and item["info"]:
            price = item["info"].get("currentPrice")
        
        if price is not None:
            price_map[symbol] = price

    # Build updates
    updates = {}
    now_iso = datetime.now().isoformat(timespec="seconds")
    for entry in to_update:
        symbol = entry["stock_code"]
        if symbol in price_map:
            updates[entry["entry_id"]] = {
                "outcome_price": price_map[symbol],
                "outcome_date": now_iso
            }

    if not updates:
        print("No prices found for the pending symbols.")
        return

    # Update journal
    journal_file = batch_update_outcomes(updates, journal_path=journal_path)
    print(f"Successfully updated {len(updates)} entries in {journal_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize advice outcomes with current market prices.")
    parser.add_argument("--journal-path", help="Path to the advice journal file.")
    args = parser.parse_args()
    sync_all(args.journal_path)
