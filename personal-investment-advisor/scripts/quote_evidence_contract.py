"""Dependency-light quote freshness and snapshot binding contracts."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

from portfolio_loader import normalize_symbol


QUOTE_FRESHNESS_POLICY_VERSION = "market-state-v1"
QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE = {
    "REGULAR": 15 * 60,
    "PREPRE": 24 * 60 * 60,
    "PRE": 24 * 60 * 60,
    "POST": 24 * 60 * 60,
    "POSTPOST": 24 * 60 * 60,
    "CLOSED": 72 * 60 * 60,
}
MAX_QUOTE_AGE_SECONDS = max(QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE.values())
MAX_QUOTE_FUTURE_SKEW_SECONDS = 60 * 60
PORTFOLIO_SNAPSHOT_BINDING_VERSION = "pia_portfolio_snapshot_v1"
CANONICAL_JSON_BINDING_VERSION = "pia_canonical_json_sha256_v1"


def quote_freshness_policy(
    market_state: Any,
    *,
    upper_bound_cap_seconds: int = MAX_QUOTE_AGE_SECONDS,
) -> dict[str, Any]:
    """Return the deterministic fail-closed quote-age rule for one market state."""
    normalized = str(market_state or "").strip().upper()
    state_threshold = QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE.get(normalized)
    cap_is_valid = (
        isinstance(upper_bound_cap_seconds, (int, float))
        and not isinstance(upper_bound_cap_seconds, bool)
        and math.isfinite(float(upper_bound_cap_seconds))
        and float(upper_bound_cap_seconds) > 0
    )
    applied_threshold = (
        min(float(state_threshold), float(upper_bound_cap_seconds))
        if state_threshold is not None and cap_is_valid
        else None
    )
    return {
        "version": QUOTE_FRESHNESS_POLICY_VERSION,
        "market_state": normalized or None,
        "state_max_age_seconds": state_threshold,
        "upper_bound_cap_seconds": (
            float(upper_bound_cap_seconds) if cap_is_valid else None
        ),
        "applied_max_age_seconds": applied_threshold,
        "calendar_aware": False,
        "long_holiday_behavior": "fail_closed_after_state_threshold",
    }


def canonical_json_binding(payload: Any) -> dict[str, Any]:
    """Return a deterministic semantic JSON digest for one captured input."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        "schema_version": CANONICAL_JSON_BINDING_VERSION,
        "algorithm": "sha256",
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
    }


def _canonical_quantity(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("portfolio position quantity must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("portfolio position quantity must be numeric") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("portfolio position quantity must be non-negative and finite")
    normalized = format(parsed.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def build_portfolio_snapshot_binding(
    portfolio_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind active holdings, including cash, to decision-critical identity fields."""
    if not isinstance(portfolio_payload, dict):
        raise ValueError("portfolio payload must be an object")
    rows = []
    for position in portfolio_payload.get("positions", []):
        if not isinstance(position, dict):
            raise ValueError("portfolio position must be an object")
        quantity = _canonical_quantity(position.get("quantity"))
        if Decimal(quantity) == 0:
            continue
        rows.append(
            {
                "symbol": normalize_symbol(position.get("symbol") or ""),
                "quantity": quantity,
                "currency": str(position.get("currency") or "").strip().upper(),
                "market": str(position.get("market") or "").strip().upper(),
                "asset_type": str(position.get("asset_type") or "").strip().lower(),
            }
        )
    rows.sort(
        key=lambda row: (
            row["symbol"],
            row["market"],
            row["asset_type"],
            row["currency"],
            row["quantity"],
        )
    )
    digest = canonical_json_binding(rows)
    return {
        "schema_version": PORTFOLIO_SNAPSHOT_BINDING_VERSION,
        "fields": ["symbol", "quantity", "currency", "market", "asset_type"],
        "active_position_count": len(rows),
        "active_positions": rows,
        "algorithm": digest["algorithm"],
        "sha256": digest["sha256"],
    }
