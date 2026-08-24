"""Atomically import broker rows with explicit market and asset identity.

Every CSV row must provide symbol, quantity, avg_cost, currency, market, and
asset_type. Legacy market_type values are ignored and cannot satisfy identity.
"""

import argparse
import copy
import csv
import json
import math
import os
import tempfile
from pathlib import Path

from portfolio_loader import validate_portfolio_payload


def resolve_positions_file(path: str | None) -> Path:
    configured = path or os.environ.get("PIA_POSITIONS_FILE")
    if not configured:
        raise ValueError("positions file is required; pass --positions-file or set PIA_POSITIONS_FILE")
    return Path(configured).expanduser()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    destination = Path(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _required_text(row: dict, field: str, row_number: int) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"broker row {row_number}: missing required field {field}")
    return value


def _required_number(
    row: dict, field: str, row_number: int, *, minimum: float = 0.0
) -> float:
    raw = row.get(field)
    if raw in (None, ""):
        raise ValueError(f"broker row {row_number}: missing required field {field}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"broker row {row_number}: {field} must be numeric"
        ) from exc
    if not math.isfinite(value) or value < minimum:
        raise ValueError(
            f"broker row {row_number}: {field} must be finite and >= {minimum}"
        )
    return value


def _apply_quantity_semantics(position: dict, quantity: float) -> None:
    if quantity == 0:
        position["current_weight"] = 0.0
        position.pop("target_weight", None)
        position.pop("max_weight", None)
    else:
        position.pop("current_weight", None)


def _stage_broker_rows(csv_path: str, positions: list[dict]) -> None:
    pos_map = {}
    for position in positions:
        symbol = normalize_symbol(position.get("symbol"))
        if not symbol:
            raise ValueError("positions file contains a position without symbol")
        if symbol in pos_map:
            raise ValueError(f"positions file contains duplicate symbol {symbol}")
        pos_map[symbol] = position

    seen = set()
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("broker CSV must contain a header row")
        for row_number, row in enumerate(reader, start=2):
            symbol = normalize_symbol(_required_text(row, "symbol", row_number))
            if symbol in seen:
                raise ValueError(f"broker row {row_number}: duplicate symbol {symbol}")
            seen.add(symbol)

            staged = {
                "symbol": symbol,
                "quantity": _required_number(row, "quantity", row_number),
                "avg_cost": _required_number(row, "avg_cost", row_number),
                "currency": _required_text(row, "currency", row_number).upper(),
                "market": _required_text(row, "market", row_number).upper(),
                "asset_type": _required_text(
                    row, "asset_type", row_number
                ).lower(),
            }
            for optional_field in ("name", "opened_at", "thesis"):
                value = str(row.get(optional_field) or "").strip()
                if value:
                    staged[optional_field] = value

            if symbol in pos_map:
                pos_map[symbol].update(staged)
                _apply_quantity_semantics(pos_map[symbol], staged["quantity"])
            else:
                _apply_quantity_semantics(staged, staged["quantity"])
                positions.append(staged)
                pos_map[symbol] = staged


def sync_broker_data(csv_path: str, positions_file: str = None, cash_cny: float = None, cash_usd: float = None):
    pos_file = resolve_positions_file(positions_file)
    data = copy.deepcopy(load_json(pos_file))
    positions = data.get("positions")
    if not isinstance(positions, list):
        raise ValueError("positions file must contain a positions list")
    if not csv_path and cash_cny is None and cash_usd is None:
        raise ValueError("no broker CSV or cash update was supplied")

    if csv_path:
        _stage_broker_rows(csv_path, positions)

    pos_map = {normalize_symbol(position.get("symbol")): position for position in positions}
    if cash_cny is not None:
        _update_cash(positions, pos_map, "CASH_CNY", "人民币现金", cash_cny, "CNY")
    if cash_usd is not None:
        _update_cash(positions, pos_map, "CASH_USD", "美元现金", cash_usd, "USD")

    data["positions"] = positions
    validation_errors = validate_portfolio_payload(data)
    if validation_errors:
        raise ValueError(
            "broker update violates portfolio contract: "
            + "; ".join(validation_errors)
        )
    save_json(pos_file, data)
    print(f"Sync complete. Updated {pos_file}")
    return data


def _update_cash(positions, pos_map, symbol, name, amount, currency):
    try:
        amount = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{symbol} amount must be numeric") from exc
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"{symbol} amount must be finite and non-negative")
    if symbol in pos_map:
        pos_map[symbol]["quantity"] = amount
        pos_map[symbol]["market"] = "CASH"
        pos_map[symbol]["asset_type"] = "cash"
        _apply_quantity_semantics(pos_map[symbol], amount)
    else:
        staged = {
            "symbol": symbol,
            "name": name,
            "quantity": amount,
            "avg_cost": 1.0,
            "currency": currency,
            "market": "CASH",
            "asset_type": "cash",
        }
        _apply_quantity_semantics(staged, amount)
        positions.append(staged)

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
