"""Stock 3.0 ordinary-equity bridge and direct DDM/FCFE recomputation.

Amounts are unscaled currency units; net_debt retains debt less cash meaning.
Claim identifiers name economic instruments, not source documents. A claim may
appear only once in a case, including hypothetical conversion shares.
"""
from __future__ import annotations

import math
from typing import TypeGuard

from source_timing_contract import PRIMARY_TIERS, iso_day

BRIDGE_COMPONENTS = ("enterprise_value", "net_debt", "nonoperating_assets", "noncontrolling_interest", "preferred_claims", "other_senior_claims")


def number(value) -> TypeGuard[int | float]:
    return type(value) in (int, float) and math.isfinite(value)


def close(left, right):
    return number(left) and number(right) and math.isclose(left, right, rel_tol=1e-9, abs_tol=0.01)


def validate_ordinary_equity(data):
    scenarios = data.get("scenario_analysis")
    if not isinstance(scenarios, dict) or scenarios.get("valuation_contract_version") != "3.0":
        return []
    errors = []
    currency = scenarios.get("currency")
    brief = data.get("research_brief")
    brief = brief if isinstance(brief, dict) else {}
    instrument = brief.get("instrument")
    instrument = instrument if isinstance(instrument, dict) else {}
    if currency != instrument.get("currency"):
        errors.append("stock3.0 currency must match instrument; explicit same-currency inputs required")
    method = scenarios.get("valuation_method")
    direct = method in ("DDM", "FCFE")
    if method not in ("enterprise_value_bridge", "DDM", "FCFE"):
        errors.append("stock3.0 method must be enterprise_value_bridge, DDM, or FCFE")
    items = data.get("evidence_items")
    items = items if isinstance(items, list) else []
    values = {}
    for name in ("base", "bull", "bear"):
        case = scenarios.get(name)
        prefix = f"scenario_analysis.{name}"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        claimed = set()

        def component(record, label, *, unit="currency", signed=False, allow_na=False, economic=False, cashflow=False, prefix=prefix, claimed=claimed):
            location = f"{prefix}.{label}"
            if not isinstance(record, dict):
                errors.append(f"{location} requires a sourced typed component")
                return None
            required = {"value", "status", "unit", "currency", "as_of_date", "evidence_index", "value_type", "measurement_basis", "rationale", "claim_ids"}
            allowed = required | ({"cash_flow_kind", "years", "discount_rate"} if cashflow else set())
            if not required <= set(record) or set(record) - allowed:
                errors.append(f"{location} missing/unknown component fields")
            if record.get("currency") != currency or record.get("unit") != unit:
                errors.append(f"{location} inconsistent currency or unit (no implicit scaling)")
            if not isinstance(record.get("rationale"), str) or not record["rationale"].strip():
                errors.append(f"{location} requires an explicit valuation/NA rationale")
            index = record.get("evidence_index")
            source = items[index] if type(index) is int and 0 <= index < len(items) and isinstance(items[index], dict) else {}
            if source.get("source_tier") not in PRIMARY_TIERS:
                errors.append(f"{location} must bind a primary evidence_index")
            try:
                component_date = iso_day(record.get("as_of_date"))
                if component_date > iso_day(scenarios.get("as_of_date")) or component_date > iso_day(source.get("as_of_date")):
                    errors.append(f"{location} component date cannot exceed source/research cutoff")
                if record.get("value_type") == "reported_fact" and "valuation_date" in source and component_date > iso_day(source["valuation_date"]):
                    errors.append(f"{location} component date cannot exceed bound observation date")
            except (ValueError, TypeError):
                errors.append(f"{location} requires valid component/source dates")
            ids = record.get("claim_ids")
            if not isinstance(ids, list) or any(not isinstance(x, str) or not x.strip() for x in ids):
                errors.append(f"{location}.claim_ids must be a string list")
                ids = []
            if len(ids) != len(set(ids)) or claimed.intersection(ids):
                errors.append(f"{location} duplicate economic claim or preferred/as-converted double counting")
            claimed.update(ids)
            if record.get("status") == "not_applicable":
                if not allow_na or record.get("value") is not None or ids or record.get("value_type") != "not_applicable" or record.get("measurement_basis") != "not_applicable":
                    errors.append(f"{location} invalid documented not_applicable component")
                return 0.0 if allow_na else None
            if record.get("status") != "included" or not ids:
                errors.append(f"{location} included component requires explicit nonduplicate claim_ids")
            value_type, basis = record.get("value_type"), record.get("measurement_basis")
            if value_type == "reported_fact":
                if basis not in ({"reported_market_value"} if economic else {"reported_amount", "reported_market_value"}):
                    errors.append(f"{location} reported book amount is not economic market value")
            elif value_type == "analyst_estimate":
                if basis != "estimated_economic_fair_value":
                    errors.append(f"{location} analyst estimate requires transparent economic fair-value basis")
            else:
                errors.append(f"{location} value_type must distinguish reported_fact from analyst_estimate")
            value = record.get("value")
            if not number(value) or (not signed and value < 0):
                errors.append(f"{location} invalid numeric value/sign")
                return None
            return float(value)

        bridge = case.get("ordinary_equity_bridge")
        if not isinstance(bridge, dict) or set(bridge) != set(BRIDGE_COMPONENTS):
            errors.append(f"{prefix}.ordinary_equity_bridge requires exactly {BRIDGE_COMPONENTS}")
            bridge = bridge if isinstance(bridge, dict) else {}
        amounts = {}
        for field in BRIDGE_COMPONENTS:
            record = bridge.get(field)
            amounts[field] = component(record, "ordinary_equity_bridge." + field, signed=field == "net_debt", allow_na=direct or field not in ("enterprise_value", "net_debt"), economic=field not in ("net_debt",))
            if direct and isinstance(record, dict) and record.get("status") != "not_applicable":
                errors.append(f"{prefix} direct ordinary equity requires all corporate bridge components not_applicable")
        if direct:
            if case.get("enterprise_value") != "not_applicable" or case.get("net_debt") != "not_applicable":
                errors.append(f"{prefix} DDM/FCFE enterprise_value and net_debt must be not_applicable")
            flows = case.get("ordinary_equity_cashflows")
            expected_equity = 0.0
            if not isinstance(flows, list) or not flows:
                errors.append(f"{prefix}.ordinary_equity_cashflows must be a non-empty discounted cashflow list")
                flows = []
            flow_keys = set()
            terminal_years = []
            ordinary_years = []
            for index, flow in enumerate(flows):
                value = component(flow, f"ordinary_equity_cashflows[{index}]", signed=method == "FCFE", economic=True, cashflow=True)
                if not isinstance(flow, dict):
                    continue
                if flow.get("value_type") != "analyst_estimate":
                    errors.append(f"{prefix} future ordinary cashflows must be explicit analyst estimates")
                kind, years, rate = flow.get("cash_flow_kind"), flow.get("years"), flow.get("discount_rate")
                if kind not in ("dividend" if method == "DDM" else "fcfe", "terminal_ordinary_equity"):
                    errors.append(f"{prefix} direct method cash_flow_kind mismatch")
                if not number(years) or years <= 0 or not number(rate) or not 0 < rate < 1:
                    errors.append(f"{prefix} cashflows require positive years and discount_rate ratio (0,1)")
                    continue
                key = (kind, years)
                if key in flow_keys:
                    errors.append(f"{prefix} duplicate cashflow period/claim")
                flow_keys.add(key)
                (terminal_years if kind == "terminal_ordinary_equity" else ordinary_years).append(years)
                if value is not None:
                    try:
                        expected_equity += value / (1 + rate) ** years
                    except OverflowError:
                        errors.append(f"{prefix} discounted cashflow overflow")
            if len(terminal_years) > 1 or (terminal_years and ordinary_years and terminal_years[0] < max(ordinary_years)):
                errors.append(f"{prefix} terminal equity cannot overlap later ordinary cashflows")
        else:
            if "ordinary_equity_cashflows" in case:
                errors.append(f"{prefix} bridge cannot also claim direct ordinary equity cashflows")
            expected_equity = None
            if all(v is not None for v in amounts.values()) and set(amounts) == set(BRIDGE_COMPONENTS):
                expected_equity = amounts["enterprise_value"] - amounts["net_debt"] + amounts["nonoperating_assets"] - amounts["noncontrolling_interest"] - amounts["preferred_claims"] - amounts["other_senior_claims"]
            for field in ("enterprise_value", "net_debt"):
                if not close(case.get(field), amounts.get(field)):
                    errors.append(f"{prefix}.{field} must match typed bridge; net_debt is not an adjustment plug")
        shares = case.get("share_basis")
        shares = shares if isinstance(shares, dict) else {}
        if set(shares) != {"basis", "as_of_date", "ordinary_shares", "incremental_shares"} or shares.get("basis") not in ("current_diluted", "hypothetical_as_converted"):
            errors.append(f"{prefix}.share_basis must explicitly declare current_diluted or hypothetical_as_converted")
        try:
            if iso_day(shares.get("as_of_date")) > iso_day(scenarios.get("as_of_date")):
                errors.append(f"{prefix} future share basis date")
        except (ValueError, TypeError):
            errors.append(f"{prefix} malformed share basis date")
        base_shares = component(shares.get("ordinary_shares"), "share_basis.ordinary_shares", unit="shares")
        increments = shares.get("incremental_shares")
        if not isinstance(increments, list):
            errors.append(f"{prefix} incremental_shares must be explicit (empty list if none)")
            increments = []
        if shares.get("basis") == "hypothetical_as_converted" and not increments:
            errors.append(f"{prefix} hypothetical conversion requires explicit incremental shares")
        total_shares = base_shares
        for index, increment in enumerate(increments):
            value = component(increment, f"share_basis.incremental_shares[{index}]", unit="shares")
            if value is not None and total_shares is not None:
                total_shares += value
        for record in [shares.get("ordinary_shares"), *increments]:
            if isinstance(record, dict) and record.get("as_of_date") != shares.get("as_of_date"):
                errors.append(f"{prefix} share components must match share_basis.as_of_date")
        if not number(total_shares) or total_shares <= 0 or not close(case.get("diluted_shares"), total_shares):
            errors.append(f"{prefix}.diluted_shares must equal positive sourced ordinary + incremental shares")
        if not close(case.get("equity_value"), expected_equity):
            errors.append(f"{prefix}.equity_value must equal recomputed ordinary equity")
        if number(expected_equity) and number(total_shares) and total_shares > 0:
            expected_per_share = expected_equity / total_shares
            if expected_per_share < 0 or not close(case.get("per_share_value"), expected_per_share):
                errors.append(f"{prefix}.per_share_value must equal nonnegative ordinary equity / diluted_shares")
            values[name] = expected_per_share
    if len(values) == 3 and not values["bear"] <= values["base"] <= values["bull"]:
        errors.append("stock3.0 values must satisfy bear <= base <= bull")
    return errors
