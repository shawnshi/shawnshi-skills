import argparse
import copy
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


PORTFOLIO_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "portfolio_schema.json"


def resolve_positions_file(path: Optional[str] = None) -> Optional[Path]:
    if path:
        return Path(path).expanduser()
    configured = os.environ.get("PIA_POSITIONS_FILE")
    if configured:
        return Path(configured).expanduser()
    return None


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper() if isinstance(symbol, str) else ""


def is_cash_position(position: Dict[str, Any]) -> bool:
    symbol = normalize_symbol(position.get("symbol") or "")
    market = _normalized_market(position.get("market"))
    asset_type = _normalized_asset_type(position.get("asset_type"))
    return (
        market == "CASH"
        and asset_type == "cash"
        and (symbol == "CASH" or symbol.startswith("CASH_"))
    )


_positions_cache: Dict[str, Dict[str, Any]] = {}


def _strict_number(value: Any) -> Optional[float]:
    """Parse a JSON number while rejecting bools and numeric strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _normalized_market(value: Any) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def _normalized_asset_type(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _valid_iso_date_or_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_portfolio_payload(payload: Dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict):
        return ["portfolio root must be an object"]
    schema = json.loads(PORTFOLIO_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = []
    for field in schema.get("prohibited_top_level", []):
        if field in payload:
            errors.append(
                f"portfolio field {field} is prohibited; allocation policy must be supplied as a separate research input"
            )
    for field in schema["required_top_level"]:
        if payload.get(field) in (None, "", []):
            errors.append(f"missing portfolio field: {field}")
    base_currency = payload.get("base_currency")
    if base_currency not in (None, ""):
        if not isinstance(base_currency, str) or not re.fullmatch(
            r"[A-Za-z]{3}", base_currency.strip()
        ):
            errors.append("base_currency must be a three-letter string currency code")
    exchange_rates = payload.get("exchange_rates")
    normalized_rates: Dict[str, float] = {}
    if exchange_rates is not None:
        if not isinstance(exchange_rates, dict):
            errors.append("exchange_rates must be an object when provided")
        else:
            for currency, raw_rate in exchange_rates.items():
                normalized_currency = (
                    currency.strip().upper() if isinstance(currency, str) else ""
                )
                if not re.fullmatch(r"[A-Z]{3}", normalized_currency):
                    errors.append(
                        "exchange_rates currency keys must be three-letter strings"
                    )
                rate = _strict_number(raw_rate)
                if rate is None or rate <= 0:
                    errors.append(
                        f"exchange_rates.{currency} must be a positive finite JSON number; bool and numeric string are prohibited"
                    )
                elif normalized_currency:
                    normalized_rates[normalized_currency] = rate

    normalized_base_currency = (
        base_currency.strip().upper() if isinstance(base_currency, str) else ""
    )
    exchange_rate_metadata = payload.get("exchange_rate_metadata")
    if exchange_rate_metadata is not None:
        if not isinstance(exchange_rate_metadata, dict):
            errors.append("exchange_rate_metadata must be an object when provided")
        else:
            for currency, metadata in exchange_rate_metadata.items():
                normalized_currency = (
                    currency.strip().upper() if isinstance(currency, str) else ""
                )
                prefix = f"exchange_rate_metadata.{currency}"
                if not re.fullmatch(r"[A-Z]{3}", normalized_currency):
                    errors.append(
                        "exchange_rate_metadata currency keys must be three-letter strings"
                    )
                    continue
                if normalized_currency not in normalized_rates:
                    errors.append(
                        f"{prefix} has no matching numeric exchange_rates entry"
                    )
                if not isinstance(metadata, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                for field in (
                    "pair",
                    "as_of",
                    "source",
                    "source_locator",
                    "retrieved_at",
                ):
                    if metadata.get(field) in (None, ""):
                        errors.append(f"missing {prefix}.{field}")
                pair = metadata.get("pair")
                expected_pair = f"{normalized_currency}/{normalized_base_currency}"
                if not isinstance(pair, str) or pair.strip().upper() != expected_pair:
                    errors.append(f"{prefix}.pair must equal {expected_pair}")
                source = metadata.get("source")
                if not isinstance(source, str) or not source.strip():
                    errors.append(f"{prefix}.source must be a non-empty string")
                source_locator = metadata.get("source_locator")
                if not isinstance(source_locator, str) or not source_locator.strip():
                    errors.append(
                        f"{prefix}.source_locator must be a non-empty string"
                    )
                for field in ("as_of", "retrieved_at"):
                    if not _valid_iso_date_or_datetime(metadata.get(field)):
                        errors.append(
                            f"{prefix}.{field} must be an ISO date or datetime string"
                        )
    positions = payload.get("positions")
    if not isinstance(positions, list):
        return errors + ["positions file must contain a top-level 'positions' list"]
    seen = set()
    position_currencies = set()
    for index, position in enumerate(positions):
        if not isinstance(position, dict):
            errors.append(f"positions[{index}] must be an object")
            continue
        missing = [
            field
            for field in schema["required_position_fields"]
            if position.get(field) in (None, "")
        ]
        if missing:
            errors.append(f"positions[{index}] missing fields: {', '.join(missing)}")
        raw_symbol = position.get("symbol")
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            errors.append(f"positions[{index}].symbol must be a non-empty string")
        symbol = normalize_symbol(raw_symbol)
        if symbol in seen:
            errors.append(f"duplicate position symbol: {symbol}")
        elif symbol:
            seen.add(symbol)
        raw_currency = position.get("currency")
        currency = (
            raw_currency.strip().upper() if isinstance(raw_currency, str) else ""
        )
        if not re.fullmatch(r"[A-Z]{3}", currency):
            errors.append(
                f"positions[{index}].currency must be a three-letter string currency code"
            )
        raw_market = position.get("market")
        market = _normalized_market(raw_market)
        allowed_markets = {
            _normalized_market(value)
            for value in schema.get("allowed_markets", [])
        }
        if not isinstance(raw_market, str) or not raw_market.strip():
            errors.append(f"positions[{index}].market must be a non-empty string")
        elif raw_market != market:
            errors.append(f"positions[{index}].market must use uppercase canonical form")
        elif market not in allowed_markets:
            errors.append(
                f"positions[{index}].market is not allowed: {raw_market}"
            )

        raw_asset_type = position.get("asset_type")
        asset_type = _normalized_asset_type(raw_asset_type)
        allowed_asset_types = {
            _normalized_asset_type(value)
            for value in schema.get("allowed_asset_types", [])
        }
        if not isinstance(raw_asset_type, str) or not raw_asset_type.strip():
            errors.append(f"positions[{index}].asset_type must be a non-empty string")
        elif raw_asset_type != asset_type:
            errors.append(
                f"positions[{index}].asset_type must use lowercase canonical form"
            )
        elif asset_type not in allowed_asset_types:
            errors.append(
                f"positions[{index}].asset_type is not allowed: {raw_asset_type}"
            )

        symbol_is_cash = symbol == "CASH" or symbol.startswith("CASH_")
        market_is_cash = market == "CASH"
        asset_is_cash = asset_type == "cash"
        if not (symbol_is_cash == market_is_cash == asset_is_cash):
            errors.append(
                f"positions[{index}] cash identity requires symbol CASH/CASH_*, market CASH, and asset_type cash together"
            )
        if market == "CN":
            if not symbol.endswith((".SS", ".SZ")):
                errors.append(
                    f"positions[{index}].symbol must use .SS or .SZ for market CN"
                )
            if currency != "CNY":
                errors.append(
                    f"positions[{index}].currency must be CNY for market CN"
                )
        elif market == "HK":
            if not symbol.endswith(".HK"):
                errors.append(
                    f"positions[{index}].symbol must use .HK for market HK"
                )
            if currency != "HKD":
                errors.append(
                    f"positions[{index}].currency must be HKD for market HK"
                )
        elif market == "US":
            if symbol.endswith((".SS", ".SZ", ".HK")):
                errors.append(
                    f"positions[{index}].symbol suffix conflicts with market US"
                )
            if currency != "USD":
                errors.append(
                    f"positions[{index}].currency must be USD for market US"
                )
        elif market == "CASH" and symbol.startswith("CASH_"):
            symbol_currency = symbol.removeprefix("CASH_")
            if symbol_currency != currency:
                errors.append(
                    f"positions[{index}].currency must match the CASH_ symbol suffix"
                )

        quantity = _strict_number(position.get("quantity"))
        if quantity is None or quantity < 0:
            errors.append(
                f"positions[{index}].quantity must be a non-negative finite JSON number; bool and numeric string are prohibited"
            )
        elif quantity > 0 and currency:
            position_currencies.add(currency)
        avg_cost = _strict_number(position.get("avg_cost"))
        if avg_cost is None or avg_cost <= 0:
            errors.append(
                f"positions[{index}].avg_cost must be a positive finite JSON number; bool and numeric string are prohibited"
            )
        if "current_weight" in position:
            weight = _strict_number(position.get("current_weight"))
            if weight is None or not (0 <= weight <= 1):
                errors.append(
                    f"positions[{index}].current_weight must be a finite JSON number from 0 to 1; bool and numeric string are prohibited"
                )
            elif quantity == 0 and weight != 0:
                errors.append(
                    f"positions[{index}].current_weight must be 0 when quantity is 0"
                )
    for currency in sorted(position_currencies):
        if currency != normalized_base_currency and currency not in normalized_rates:
            errors.append(
                f"missing exchange rate for {currency} to {normalized_base_currency}"
            )
    risk_profile = payload.get("risk_profile")
    if risk_profile is not None:
        if not isinstance(risk_profile, dict):
            errors.append("risk_profile must be an object when provided")
        else:
            for field in schema.get("risk_profile_required_fields_when_configured", []):
                if risk_profile.get(field) in (None, "", []):
                    errors.append(f"missing risk_profile.{field}")
            provenance = risk_profile.get("provenance")
            if not isinstance(provenance, dict):
                errors.append("risk_profile.provenance must be an object")
            else:
                for field in schema.get("risk_profile_required_provenance_fields", []):
                    if provenance.get(field) in (None, ""):
                        errors.append(f"missing risk_profile.provenance.{field}")
    return errors


def load_positions(path: Optional[str] = None) -> Dict[str, Any]:
    positions_path = resolve_positions_file(path)
    if positions_path is None:
        return {"positions": [], "_status": "not_configured", "_path": None}
    if not positions_path.exists():
        return {"positions": [], "_status": "file_missing", "_path": str(positions_path)}

    path_str = str(positions_path)
    mtime = positions_path.stat().st_mtime
    if path_str in _positions_cache and _positions_cache[path_str]['mtime'] == mtime:
        return copy.deepcopy(_positions_cache[path_str]['payload'])

    payload = json.loads(positions_path.read_text(encoding="utf-8"))
    validation_errors = validate_portfolio_payload(payload)
    if validation_errors:
        raise ValueError("invalid positions file: " + "; ".join(validation_errors))
    result = copy.deepcopy(payload)
    all_positions = result["positions"]
    ignored_current_weights = {
        normalize_symbol(position.get("symbol") or ""): position.get("current_weight")
        for position in all_positions
        if isinstance(position, dict) and "current_weight" in position
    }
    for position in all_positions:
        if isinstance(position, dict):
            position.pop("current_weight", None)
    active_positions = [
        position
        for position in all_positions
        if (_to_float(position.get("quantity")) or 0.0) > 0
    ]
    inactive_positions = [
        position
        for position in all_positions
        if (_to_float(position.get("quantity")) or 0.0) == 0
    ]

    # Portfolio calculations and strict matching operate only on active holdings.
    # Zero-quantity records remain auditable but cannot masquerade as positions.
    result["positions"] = active_positions
    result["_status"] = "ok"
    result["_path"] = path_str
    result["_positions_dict"] = {
        normalize_symbol(position["symbol"]): position
        for position in active_positions
    }
    result["_inactive_positions_dict"] = {
        normalize_symbol(position["symbol"]): position
        for position in inactive_positions
    }
    result["_inactive_zero_quantity_symbols"] = [
        normalize_symbol(position["symbol"])
        for position in inactive_positions
    ]
    result["_position_file_record_count"] = len(all_positions)
    result["_weight_snapshot_status"] = "requires_validated_quote_refresh"
    result["_ignored_persisted_current_weights"] = ignored_current_weights
    result["_exchange_rate_data_status"] = {
        str(currency).strip().upper(): get_exchange_rate_details(
            str(currency), result
        )["data_status"]
        for currency in result.get("exchange_rates", {})
        if isinstance(currency, str) and currency.strip()
    }

    _positions_cache[path_str] = {'mtime': mtime, 'payload': result}
    return copy.deepcopy(result)


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def get_exchange_rate_details(currency: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("position currency is required")
    normalized_currency = currency.strip().upper()
    raw_base_currency = payload.get("base_currency")
    base_currency = (
        raw_base_currency.strip().upper()
        if isinstance(raw_base_currency, str)
        else ""
    )
    if not base_currency:
        raise ValueError("portfolio base_currency is required")
    if normalized_currency == base_currency:
        return {
            "rate": 1.0,
            "data_status": "base_currency_identity",
            "as_of": None,
            "source": "currency_identity",
            "retrieved_at": None,
        }
    rates = payload.get("exchange_rates", {})
    normalized_rates = {
        key.strip().upper(): value
        for key, value in rates.items()
        if isinstance(key, str)
    } if isinstance(rates, dict) else {}
    if normalized_currency not in normalized_rates:
        raise ValueError(
            f"missing exchange rate for {normalized_currency} to {base_currency}; expected one unit of position currency in base currency"
        )
    rate = _strict_number(normalized_rates[normalized_currency])
    if rate is None or rate <= 0:
        raise ValueError(
            f"exchange rate for {normalized_currency} to {base_currency} must be a positive finite JSON number"
        )
    metadata_by_currency = payload.get("exchange_rate_metadata")
    metadata = None
    if isinstance(metadata_by_currency, dict):
        metadata = next(
            (
                value
                for key, value in metadata_by_currency.items()
                if isinstance(key, str)
                and key.strip().upper() == normalized_currency
            ),
            None,
        )
    if isinstance(metadata, dict):
        return {
            "rate": rate,
            "data_status": "dated_snapshot",
            "as_of": metadata.get("as_of"),
            "source": metadata.get("source"),
            "source_locator": metadata.get("source_locator"),
            "retrieved_at": metadata.get("retrieved_at"),
        }
    return {
        "rate": rate,
        "data_status": "undated_static",
        "as_of": None,
        "source": None,
        "source_locator": None,
        "retrieved_at": None,
    }


def get_exchange_rate(currency: str, payload: Dict[str, Any]) -> float:
    return get_exchange_rate_details(currency, payload)["rate"]


def build_portfolio_summary(positions: list[dict], payload: Dict[str, Any] = None) -> Dict[str, Any]:
    payload = payload or {}
    weights_verified = payload.get("_weight_snapshot_status") == "verified"
    risk_profile = payload.get("risk_profile", {})
    conc_high_th = _to_float(risk_profile.get("high_concentration_threshold"))
    conc_med_th = _to_float(risk_profile.get("medium_concentration_threshold"))
    
    weights = []
    market_exposure: Dict[str, float] = {}
    top_positions = []
    missing_weight_count = 0
    thesis_missing_count = 0
    liquidity_missing_count = 0
    days_to_liquidate_values = []

    for item in positions:
        weight = _to_float(item.get("current_weight")) if weights_verified else None
        market = item.get("market") or "未知"
        thesis = item.get("thesis")
        days_to_liquidate = _to_float(item.get("days_to_liquidate"))
        if not thesis:
            thesis_missing_count += 1
        if days_to_liquidate is None:
            liquidity_missing_count += 1
        else:
            days_to_liquidate_values.append(days_to_liquidate)

        if weight is None:
            missing_weight_count += 1
        else:
            weights.append(weight)
            market_exposure[market] = round(market_exposure.get(market, 0.0) + weight, 4)
            top_positions.append({
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "weight": weight,
            })

    top_positions.sort(key=lambda x: x.get("weight") or 0.0, reverse=True)
    concentration_score = round(sum(weight * weight for weight in weights), 4)
    if missing_weight_count > 0 or conc_high_th is None or conc_med_th is None:
        concentration_bucket = "unknown"
    elif concentration_score >= conc_high_th:
        concentration_bucket = "high"
    elif concentration_score >= conc_med_th:
        concentration_bucket = "medium"
    else:
        concentration_bucket = "low"

    tracked_weight = round(sum(weights), 4)
    inactive_symbols = list(payload.get("_inactive_zero_quantity_symbols", []))
    return {
        "weight_data_status": (
            "verified" if weights_verified else "requires_validated_quote_refresh"
        ),
        "total_positions": len(positions),
        "position_file_record_count": payload.get(
            "_position_file_record_count", len(positions)
        ),
        "inactive_zero_quantity_count": len(inactive_symbols),
        "inactive_zero_quantity_symbols": inactive_symbols,
        "tracked_weight": tracked_weight,
        "positions_missing_weight": missing_weight_count,
        "market_exposure": market_exposure,
        "top_positions_by_weight": top_positions[:5],
        "concentration_score": concentration_score,
        "concentration_bucket": concentration_bucket,
        "thesis_missing_count": thesis_missing_count,
        "liquidity_missing_count": liquidity_missing_count,
        "max_days_to_liquidate": max(days_to_liquidate_values, default=None),
    }


def build_portfolio_risk(summary: Dict[str, Any], payload: Dict[str, Any] = None) -> Dict[str, Any]:
    payload = payload or {}
    risk_profile = payload.get("risk_profile", {})
    schema = json.loads(PORTFOLIO_SCHEMA_PATH.read_text(encoding="utf-8"))
    required_profile = schema.get("risk_profile_required_fields_when_configured", [])
    required_provenance = schema.get("risk_profile_required_provenance_fields", [])
    profile_missing = [
        field for field in required_profile if risk_profile.get(field) in (None, "", [])
    ]
    provenance = risk_profile.get("provenance", {})
    provenance_missing = [
        field for field in required_provenance
        if not isinstance(provenance, dict) or provenance.get(field) in (None, "")
    ]
    exp_high_th = _to_float(risk_profile.get("max_market_exposure_high"))
    exp_med_th = _to_float(risk_profile.get("max_market_exposure_medium"))
    single_weight_th = _to_float(risk_profile.get("max_single_stock_weight"))

    concentration_bucket = summary.get("concentration_bucket", "unknown")
    top_positions = summary.get("top_positions_by_weight", [])
    market_exposure = summary.get("market_exposure", {})
    missing_weight_count = summary.get("positions_missing_weight", 0)
    thesis_missing_count = summary.get("thesis_missing_count", 0)
    liquidity_missing_count = summary.get("liquidity_missing_count", 0)
    max_days_to_liquidate = summary.get("max_days_to_liquidate")
    liquidity_high_days = _to_float(risk_profile.get("liquidity_high_days"))
    liquidity_medium_days = _to_float(risk_profile.get("liquidity_medium_days"))
    profile_ready = (
        bool(risk_profile)
        and not profile_missing
        and not provenance_missing
        and all(
            value is not None
            for value in (
                exp_high_th,
                exp_med_th,
                single_weight_th,
                liquidity_high_days,
                liquidity_medium_days,
            )
        )
    )
    risk_data_gaps = []

    if not profile_ready:
        missing = profile_missing + [
            f"provenance.{field}" for field in provenance_missing
        ]
        risk_data_gaps.append(
            "未配置可追踪 risk_profile，风险等级保持未知"
            + (f"；缺少: {', '.join(missing)}" if missing else "")
        )

    max_market_exposure = max(market_exposure.values(), default=0.0)
    if not profile_ready or missing_weight_count > 0:
        concentration_risk = "未知"
    elif concentration_bucket == "high" or any(item.get("weight", 0) >= single_weight_th for item in top_positions):
        concentration_risk = "高"
    elif concentration_bucket == "medium":
        concentration_risk = "中"
    else:
        concentration_risk = "低"

    if not profile_ready or missing_weight_count > 0:
        market_exposure_risk = "未知"
    elif max_market_exposure >= exp_high_th:
        market_exposure_risk = "高"
    elif max_market_exposure >= exp_med_th:
        market_exposure_risk = "中"
    else:
        market_exposure_risk = "低"

    style_drift_risk = "未知"
    if thesis_missing_count > 0:
        risk_data_gaps.append("部分持仓缺少 thesis，无法判断风格漂移")
    else:
        risk_data_gaps.append("仅有 thesis 文本，缺少方法标签和历史暴露，无法判断风格漂移")

    if not profile_ready:
        liquidity_risk = "未知"
    elif liquidity_missing_count > 0:
        liquidity_risk = "未知"
        risk_data_gaps.append("部分持仓缺少 days_to_liquidate，无法判断组合流动性")
    elif max_days_to_liquidate is not None and max_days_to_liquidate > liquidity_high_days:
        liquidity_risk = "高"
    elif max_days_to_liquidate is not None and max_days_to_liquidate > liquidity_medium_days:
        liquidity_risk = "中"
    else:
        liquidity_risk = "低"
    if missing_weight_count > 0:
        risk_data_gaps.append("部分持仓缺少 current_weight，集中度与市场暴露不完整")

    return {
        "concentration_risk": concentration_risk,
        "market_exposure_risk": market_exposure_risk,
        "style_drift_risk": style_drift_risk,
        "liquidity_risk": liquidity_risk,
        "risk_data_gaps": risk_data_gaps,
        "risk_profile_status": "configured_and_traceable" if profile_ready else "not_configured",
        "risk_profile_provenance": provenance if profile_ready else None,
    }


def build_position_context(symbol: str, current_price: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)

    # Performance: O(1) dictionary lookup replacing O(N^2) generator next() scanning
    if "_positions_dict" in payload:
        matched = payload["_positions_dict"].get(normalized)
    else:
        positions = payload.get("positions", [])
        matched = next((item for item in positions if normalize_symbol(item.get("symbol", "")) == normalized), None)

    context: Dict[str, Any] = {
        "has_position": False,
        "symbol": symbol,
        "position_status": payload["_status"],
        "positions_file": payload["_path"],
    }

    if payload["_status"] != "ok":
        context["position_note"] = (
            "positions file not configured"
            if payload["_status"] == "not_configured"
            else "positions file not found"
        )
        return context

    inactive = payload.get("_inactive_positions_dict", {}).get(normalized)
    if not matched and inactive:
        context.update(
            {
                "position_status": "inactive_zero_quantity",
                "position_note": (
                    "symbol exists in the positions file with zero quantity "
                    "and is excluded from active holdings"
                ),
                "name": inactive.get("name"),
                "market": inactive.get("market"),
                "asset_type": inactive.get("asset_type"),
                "quantity": 0.0,
                "currency": inactive.get("currency"),
            }
        )
        return context

    if not matched:
        context["position_status"] = "not_found"
        context["position_note"] = "symbol not found in positions file"
        return context

    quantity = _to_float(matched.get("quantity")) or 0.0
    avg_cost = _to_float(matched.get("avg_cost"))
    price = _to_float(current_price)
    
    if is_cash_position(matched) and price is None:
        price = 1.0
        avg_cost = 1.0
        
    currency = str(matched.get("currency") or "").upper()
    fx_details = get_exchange_rate_details(currency, payload)
    fx_rate = fx_details["rate"]
    base_currency = str(payload.get("base_currency") or "").upper()
    
    market_value = round(quantity * price * fx_rate, 2) if price is not None else None
    cost_basis = round(quantity * avg_cost * fx_rate, 2) if avg_cost is not None else None
    unrealized_pnl = None
    unrealized_pnl_pct = None
    if price is not None and avg_cost not in (None, 0):
        unrealized_pnl = round((price - avg_cost) * quantity * fx_rate, 2)
        unrealized_pnl_pct = round((price - avg_cost) / avg_cost, 4)

    weights_verified = payload.get("_weight_snapshot_status") == "verified"
    current_weight = (
        _to_float(matched.get("current_weight")) if weights_verified else None
    )
    target_weight = _to_float(matched.get("target_weight"))
    max_weight = _to_float(matched.get("max_weight"))
    
    weight_status = "unknown"
    if current_weight is not None and max_weight is not None and current_weight > max_weight:
        weight_status = "above_max"
    elif current_weight is not None and target_weight is not None and current_weight > target_weight:
        weight_status = "above_target"
    elif current_weight is not None and target_weight is not None:
        weight_status = "within_target"

    context.update({
        "has_position": True,
        "position_status": "matched",
        "name": matched.get("name"),
        "market": matched.get("market"),
        "asset_type": matched.get("asset_type"),
        "quantity": quantity,
        "avg_cost": avg_cost,
        "currency": currency,
        "base_currency": base_currency,
        "fx_rate_to_base": fx_rate,
        "fx_data_status": fx_details["data_status"],
        "fx_as_of": fx_details["as_of"],
        "fx_source": fx_details["source"],
        "fx_source_locator": fx_details.get("source_locator"),
        "fx_retrieved_at": fx_details["retrieved_at"],
        "opened_at": matched.get("opened_at"),
        "thesis": matched.get("thesis"),
        "target_weight": target_weight,
        "max_weight": max_weight,
        "current_weight": current_weight,
        "current_weight_status": (
            "verified" if weights_verified else "requires_validated_quote_refresh"
        ),
        "weight_status": weight_status,
        "current_price": price,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
    })
    return context


def build_portfolio_fit(position_context: Dict[str, Any], summary: Dict[str, Any], risk: Dict[str, Any]) -> Dict[str, Any]:
    if position_context.get("has_position"):
        weight_status = position_context.get("weight_status")
        if weight_status == "above_max":
            constraint_status = "above_configured_max_weight"
            observation = "current_weight exceeds the configured max_weight"
            rationale = "仅记录已配置权重上限的违约事实，不生成持仓调整指令。"
        elif weight_status == "above_target":
            constraint_status = "above_configured_target_weight"
            observation = "current_weight exceeds the configured target_weight"
            rationale = "仅记录当前权重与目标权重的偏离，不生成持仓调整指令。"
        elif weight_status == "within_target":
            constraint_status = "within_configured_weight_range"
            observation = "current_weight does not exceed the configured target_weight"
            rationale = "已配置权重约束未被触发；该状态不代表证券研究结论。"
        else:
            constraint_status = "weight_constraint_unknown"
            observation = "weight constraint cannot be evaluated from available fields"
            rationale = "缺少当前、目标或最大权重，只能保留数据缺口。"
    else:
        concentration_risk = risk.get("concentration_risk")
        if concentration_risk == "高":
            constraint_status = "portfolio_concentration_high"
            observation = "configured portfolio concentration risk is high"
            rationale = "仅记录现有组合集中度状态，不推导标的配置结论。"
        else:
            constraint_status = "portfolio_constraint_evidence_incomplete"
            observation = "portfolio constraints remain incompletely evidenced"
            rationale = "预期收益、相关性、流动性或显式风险约束仍缺少可复核证据。"

    return {
        "constraint_status": constraint_status,
        "constraint_observation": observation,
        "rationale": rationale,
        "portfolio_concentration_bucket": summary.get("concentration_bucket"),
    }


def build_portfolio_package(
    symbol: str,
    current_price: Any = None,
    positions_file: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = payload if payload is not None else load_positions(positions_file)
    positions = payload["positions"]
    position_context = build_position_context(symbol, current_price=current_price, payload=payload)

    package: Dict[str, Any] = {
        "portfolio_context": position_context,
        "portfolio_summary": None,
        "portfolio_risk": None,
        "portfolio_fit": None,
    }

    if payload["_status"] != "ok":
        return package

    summary = build_portfolio_summary(positions, payload)
    risk = build_portfolio_risk(summary, payload)
    fit = build_portfolio_fit(position_context, summary, risk)
    package.update({
        "portfolio_summary": summary,
        "portfolio_risk": risk,
        "portfolio_fit": fit,
    })
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load portfolio context for a symbol.")
    parser.add_argument("symbol")
    parser.add_argument("--current-price", type=float)
    parser.add_argument("--positions-file", help="Portfolio JSON path; alternatively set PIA_POSITIONS_FILE.")
    args = parser.parse_args()

    package = build_portfolio_package(
        args.symbol,
        current_price=args.current_price,
        positions_file=args.positions_file,
    )
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    message = json.dumps(package, ensure_ascii=False, indent=2)
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
