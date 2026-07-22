import argparse
import json
import math
import os
import sys
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
    return (symbol or "").strip().upper()


_positions_cache: Dict[str, Dict[str, Any]] = {}


def validate_portfolio_payload(payload: Dict[str, Any]) -> list[str]:
    schema = json.loads(PORTFOLIO_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = []
    for field in schema["required_top_level"]:
        if payload.get(field) in (None, "", []):
            errors.append(f"missing portfolio field: {field}")
    positions = payload.get("positions")
    if not isinstance(positions, list):
        return errors + ["positions file must contain a top-level 'positions' list"]
    seen = set()
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
        symbol = normalize_symbol(position.get("symbol", ""))
        if symbol in seen:
            errors.append(f"duplicate position symbol: {symbol}")
        elif symbol:
            seen.add(symbol)
        for field in ["quantity", "avg_cost"]:
            value = _to_float(position.get(field))
            if value is None or value <= 0:
                errors.append(f"positions[{index}].{field} must be a positive finite number")
        if "current_weight" in position:
            weight = _to_float(position.get("current_weight"))
            if weight is None or not (0 < weight <= 1):
                errors.append(
                    f"positions[{index}].current_weight must be a finite number greater than 0 and at most 1"
                )
    return errors


def load_positions(path: Optional[str] = None) -> Dict[str, Any]:
    positions_path = resolve_positions_file(path)
    if positions_path is None:
        return {"positions": [], "_status": "not_configured", "_path": None}
    if not positions_path.exists():
        return {"positions": [], "_status": "file_missing", "_path": str(positions_path)}

    import copy
    path_str = str(positions_path)
    mtime = positions_path.stat().st_mtime
    if path_str in _positions_cache and _positions_cache[path_str]['mtime'] == mtime:
        return copy.deepcopy(_positions_cache[path_str]['payload'])

    payload = json.loads(positions_path.read_text(encoding="utf-8"))
    validation_errors = validate_portfolio_payload(payload)
    if validation_errors:
        raise ValueError("invalid positions file: " + "; ".join(validation_errors))
    positions = payload["positions"]

    import copy
    # Pre-compute a symbol map after duplicate-symbol validation.
    positions_dict = {}
    for p in positions:
        if "symbol" in p:
            sym = normalize_symbol(p["symbol"])
            if sym not in positions_dict:
                positions_dict[sym] = p

    result = {"positions": positions, "_status": "ok", "_path": path_str, "_positions_dict": positions_dict}

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


def get_exchange_rate(currency: str, payload: Dict[str, Any]) -> float:
    if not currency:
        raise ValueError("position currency is required")
    base_currency = str(payload.get("base_currency") or "").upper()
    if not base_currency:
        raise ValueError("portfolio base_currency is required")
    if currency.upper() == base_currency:
        return 1.0
    rates = payload.get("exchange_rates", {})
    if currency.upper() not in rates:
        raise ValueError(
            f"missing exchange rate for {currency.upper()} to {base_currency}; expected one unit of position currency in base currency"
        )
    return float(rates[currency.upper()])


def build_portfolio_summary(positions: list[dict], payload: Dict[str, Any] = None) -> Dict[str, Any]:
    payload = payload or {}
    risk_profile = payload.get("risk_profile", {})
    conc_high_th = risk_profile.get("high_concentration_threshold", 0.18)
    conc_med_th = risk_profile.get("medium_concentration_threshold", 0.10)
    
    weights = []
    market_exposure: Dict[str, float] = {}
    top_positions = []
    missing_weight_count = 0
    thesis_missing_count = 0
    liquidity_missing_count = 0
    days_to_liquidate_values = []

    for item in positions:
        weight = _to_float(item.get("current_weight"))
        market = item.get("market_type") or "未知"
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
    if concentration_score >= conc_high_th:
        concentration_bucket = "high"
    elif concentration_score >= conc_med_th:
        concentration_bucket = "medium"
    else:
        concentration_bucket = "low"

    tracked_weight = round(sum(weights), 4)
    return {
        "total_positions": len(positions),
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
    exp_high_th = risk_profile.get("max_market_exposure_high", 0.65)
    exp_med_th = risk_profile.get("max_market_exposure_medium", 0.45)
    single_weight_th = risk_profile.get("max_single_stock_weight", 0.20)

    concentration_bucket = summary.get("concentration_bucket", "unknown")
    top_positions = summary.get("top_positions_by_weight", [])
    market_exposure = summary.get("market_exposure", {})
    missing_weight_count = summary.get("positions_missing_weight", 0)
    thesis_missing_count = summary.get("thesis_missing_count", 0)
    liquidity_missing_count = summary.get("liquidity_missing_count", 0)
    max_days_to_liquidate = summary.get("max_days_to_liquidate")
    liquidity_high_days = risk_profile.get("liquidity_high_days", 5.0)
    liquidity_medium_days = risk_profile.get("liquidity_medium_days", 2.0)
    risk_data_gaps = []

    max_market_exposure = max(market_exposure.values(), default=0.0)
    if concentration_bucket == "high" or any(item.get("weight", 0) >= single_weight_th for item in top_positions):
        concentration_risk = "高"
    elif concentration_bucket == "medium":
        concentration_risk = "中"
    else:
        concentration_risk = "低"

    if max_market_exposure >= exp_high_th:
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

    if liquidity_missing_count > 0:
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

    if not matched:
        context["position_status"] = "not_found"
        context["position_note"] = "symbol not found in positions file"
        return context

    quantity = _to_float(matched.get("quantity")) or 0.0
    avg_cost = _to_float(matched.get("avg_cost"))
    price = _to_float(current_price)
    
    market_type = matched.get("market_type")
    if market_type == "CASH" and price is None:
        price = 1.0
        avg_cost = 1.0
        
    currency = matched.get("currency") or "CNY"
    fx_rate = get_exchange_rate(currency, payload)
    
    market_value = round(quantity * price * fx_rate, 2) if price is not None else None
    cost_basis = round(quantity * avg_cost * fx_rate, 2) if avg_cost is not None else None
    unrealized_pnl = None
    unrealized_pnl_pct = None
    if price is not None and avg_cost not in (None, 0):
        unrealized_pnl = round((price - avg_cost) * quantity * fx_rate, 2)
        unrealized_pnl_pct = round((price - avg_cost) / avg_cost, 4)

    current_weight = _to_float(matched.get("current_weight"))
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
        "market_type": matched.get("market_type"),
        "quantity": quantity,
        "avg_cost": avg_cost,
        "currency": matched.get("currency"),
        "opened_at": matched.get("opened_at"),
        "thesis": matched.get("thesis"),
        "target_weight": target_weight,
        "max_weight": max_weight,
        "current_weight": current_weight,
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
            eligibility = "blocked_by_max_weight"
            impact = "existing weight exceeds the configured maximum"
            rationale = "组合约束阻止新增配置；该结论不判断个股投资价值。"
        elif weight_status == "above_target":
            eligibility = "blocked_for_addition"
            impact = "existing weight exceeds the configured target"
            rationale = "当前权重不允许新增配置；是否减持仍需独立研究结论。"
        elif weight_status == "within_target":
            eligibility = "within_weight_constraint"
            impact = "weight constraint does not block research consideration"
            rationale = "仓位约束未触发，但这不构成买入或加仓建议。"
        else:
            eligibility = "unknown"
            impact = "weight constraint cannot be evaluated"
            rationale = "缺少当前、目标或最大权重，不能生成组合动作。"
    else:
        concentration_risk = risk.get("concentration_risk")
        if concentration_risk == "高":
            eligibility = "requires_concentration_review"
            impact = "a new position may worsen concentration"
            rationale = "组合集中度已高，新增仓位必须显著提升组合质量。"
        else:
            eligibility = "constraint_review_incomplete"
            impact = "no concentration block detected; other risks remain unassessed"
            rationale = "集中度没有触发硬门，但仍需预期收益、相关性和流动性证据。"

    return {
        "eligibility": eligibility,
        "constraint_impact": impact,
        "rationale": rationale,
        "portfolio_concentration_bucket": summary.get("concentration_bucket"),
    }


def build_portfolio_package(symbol: str, current_price: Any = None, positions_file: Optional[str] = None) -> Dict[str, Any]:
    payload = load_positions(positions_file)
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
