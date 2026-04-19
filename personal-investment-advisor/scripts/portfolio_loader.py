import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_POSITIONS_FILE = Path.home() / ".gemini" / "MEMORY" / "raw" / "stocks" / "portfolio_positions.json"


def resolve_positions_file(path: Optional[str] = None) -> Path:
    if path:
        return Path(path).expanduser()
    configured = os.environ.get("PIA_POSITIONS_FILE")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_POSITIONS_FILE


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def load_positions(path: Optional[str] = None) -> Dict[str, Any]:
    positions_path = resolve_positions_file(path)
    if not positions_path.exists():
        return {"positions": [], "_status": "file_missing", "_path": str(positions_path)}

    payload = json.loads(positions_path.read_text(encoding="utf-8"))
    positions = payload.get("positions", [])
    if not isinstance(positions, list):
        raise ValueError("positions file must contain a top-level 'positions' list")
    return {"positions": positions, "_status": "ok", "_path": str(positions_path)}


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_portfolio_summary(positions: list[dict]) -> Dict[str, Any]:
    weights = []
    market_exposure: Dict[str, float] = {}
    top_positions = []
    missing_weight_count = 0
    thesis_missing_count = 0

    for item in positions:
        weight = _to_float(item.get("current_weight"))
        market = item.get("market_type") or "未知"
        thesis = item.get("thesis")
        if not thesis:
            thesis_missing_count += 1

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
    if concentration_score >= 0.18:
        concentration_bucket = "high"
    elif concentration_score >= 0.10:
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
    }


def build_portfolio_risk(summary: Dict[str, Any]) -> Dict[str, Any]:
    concentration_bucket = summary.get("concentration_bucket", "unknown")
    top_positions = summary.get("top_positions_by_weight", [])
    market_exposure = summary.get("market_exposure", {})
    missing_weight_count = summary.get("positions_missing_weight", 0)
    thesis_missing_count = summary.get("thesis_missing_count", 0)

    max_market_exposure = max(market_exposure.values(), default=0.0)
    if concentration_bucket == "high" or any(item.get("weight", 0) >= 0.2 for item in top_positions):
        concentration_risk = "高"
    elif concentration_bucket == "medium":
        concentration_risk = "中"
    else:
        concentration_risk = "低"

    if max_market_exposure >= 0.65:
        market_exposure_risk = "高"
    elif max_market_exposure >= 0.45:
        market_exposure_risk = "中"
    else:
        market_exposure_risk = "低"

    if thesis_missing_count > 0:
        style_drift_risk = "中"
    else:
        style_drift_risk = "低"

    if missing_weight_count > 0:
        liquidity_risk = "未知"
    else:
        liquidity_risk = "中" if concentration_risk == "高" else "低"

    return {
        "concentration_risk": concentration_risk,
        "market_exposure_risk": market_exposure_risk,
        "style_drift_risk": style_drift_risk,
        "liquidity_risk": liquidity_risk,
    }


def build_position_context(symbol: str, current_price: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    positions = payload["positions"]
    matched = next((item for item in positions if normalize_symbol(item.get("symbol", "")) == normalized), None)

    context: Dict[str, Any] = {
        "has_position": False,
        "symbol": symbol,
        "position_status": payload["_status"],
        "positions_file": payload["_path"],
    }

    if payload["_status"] == "file_missing":
        context["position_note"] = "positions file not found"
        return context

    if not matched:
        context["position_status"] = "not_found"
        context["position_note"] = "symbol not found in positions file"
        return context

    quantity = _to_float(matched.get("quantity")) or 0.0
    avg_cost = _to_float(matched.get("avg_cost"))
    price = _to_float(current_price)
    market_value = round(quantity * price, 2) if price is not None else None
    cost_basis = round(quantity * avg_cost, 2) if avg_cost is not None else None
    unrealized_pnl = None
    unrealized_pnl_pct = None
    if price is not None and avg_cost not in (None, 0):
        unrealized_pnl = round((price - avg_cost) * quantity, 2)
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
            action = "reduce_or_hold_only"
            impact = "reduces concentration risk"
            rationale = "单票已超过组合上限，不适合继续加仓。"
        elif weight_status == "above_target":
            action = "hold_or_trim"
            impact = "keeps risk stable"
            rationale = "单票已高于目标权重，新增配置会降低组合弹性。"
        else:
            action = "hold_or_add_small"
            impact = "limited impact on diversification"
            rationale = "当前仓位仍在目标区间，可小幅调节，但不应失控扩张。"
    else:
        concentration_risk = risk.get("concentration_risk")
        if concentration_risk == "高":
            action = "selective_only"
            impact = "may worsen concentration"
            rationale = "组合集中度已高，新增仓位必须显著提升组合质量。"
        else:
            action = "eligible"
            impact = "incremental risk acceptable"
            rationale = "组合仍有承载空间，可把该标的视作候选而非必选。"

    return {
        "action_in_portfolio": action,
        "allocation_impact": impact,
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

    if payload["_status"] == "file_missing":
        return package

    summary = build_portfolio_summary(positions)
    risk = build_portfolio_risk(summary)
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
    parser.add_argument("--positions-file")
    args = parser.parse_args()

    package = build_portfolio_package(
        args.symbol,
        current_price=args.current_price,
        positions_file=args.positions_file,
    )
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    message = json.dumps(package, ensure_ascii=False, indent=2)
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
