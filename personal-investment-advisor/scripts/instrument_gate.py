import argparse
import json
import re
import sys
from typing import Any


MARKET_CURRENCY = {"CN": "CNY", "HK": "HKD", "US": "USD"}
ASSET_TYPES = {"stock", "etf", "fund", "index", "other"}


def _normalize_cn(symbol: str) -> str | None:
    match = re.fullmatch(r"(\d{6})(?:\.(SS|SZ|BJ))?", symbol)
    if not match:
        return None
    code, suffix = match.groups()
    if suffix:
        return f"{code}.{suffix}"
    if code[0] in {"5", "6"}:
        return f"{code}.SS"
    if code[0] in {"0", "1", "2", "3"}:
        return f"{code}.SZ"
    if code[0] in {"4", "8", "9"}:
        return f"{code}.BJ"
    return None


def _normalize_hk(symbol: str) -> str | None:
    match = re.fullmatch(r"(\d{1,5})(?:\.HK)?", symbol)
    if not match:
        return None
    return f"{int(match.group(1)):04d}.HK"


def _normalize_us(symbol: str) -> str | None:
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        return None
    return symbol


def validate_instrument(
    symbol: str,
    market: str,
    asset_type: str,
    currency: str | None = None,
) -> dict[str, Any]:
    raw_symbol = symbol.strip().upper()
    market = market.strip().upper()
    asset_type = asset_type.strip().lower()
    currency = currency.strip().upper() if currency else MARKET_CURRENCY.get(market)
    errors: list[str] = []
    warnings: list[str] = []

    if market not in MARKET_CURRENCY:
        errors.append("market must be one of CN, HK, US")
        normalized = None
    elif market == "CN":
        normalized = _normalize_cn(raw_symbol)
    elif market == "HK":
        normalized = _normalize_hk(raw_symbol)
    else:
        normalized = _normalize_us(raw_symbol)

    if market in MARKET_CURRENCY and normalized is None:
        errors.append(f"symbol syntax is inconsistent with market {market}")
    if asset_type not in ASSET_TYPES:
        errors.append(f"asset_type must be one of {sorted(ASSET_TYPES)}")
    expected_currency = MARKET_CURRENCY.get(market)
    if expected_currency and currency != expected_currency:
        errors.append(
            f"currency {currency!r} is inconsistent with market {market}; expected {expected_currency}"
        )

    warnings.append(
        "syntax and market mapping only; verify listing status and instrument identity with an exchange or live data source"
    )
    return {
        "valid": not errors,
        "input_symbol": raw_symbol,
        "normalized_symbol": normalized,
        "market": market,
        "asset_type": asset_type,
        "currency": currency,
        "validation_level": "syntax_and_market_mapping",
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate instrument syntax, market, asset type, and currency before data retrieval."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", required=True, choices=["CN", "HK", "US"])
    parser.add_argument("--asset-type", required=True, choices=sorted(ASSET_TYPES))
    parser.add_argument("--currency")
    args = parser.parse_args()

    result = validate_instrument(args.symbol, args.market, args.asset_type, args.currency)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
