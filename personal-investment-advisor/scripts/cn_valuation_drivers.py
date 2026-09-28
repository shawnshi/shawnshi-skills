"""Recompute an A-share operating-company DCF and compare its EV to Dashboard 3.0.

Projection assumptions remain analyst hypotheses, not verified issuer facts.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from instrument_gate import validate_instrument
from cn_filing_facts import evaluate as evaluate_filing_facts

VERSION = "pia_cn_operating_dcf_v1"
MAX_BYTES = 32 * 1024 * 1024
CASES = ("base", "bull", "bear")


def number(value: Any, *, low: float | None = None, high: float | None = None) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and (low is None or value > low) and (high is None or value < high)


def close(left: Any, right: float) -> bool:
    return number(left) and math.isclose(left, right, rel_tol=1e-8, abs_tol=0.01)


def evaluate(model: Any, dashboard: Any, *, filing_package: Any = None, verify_filing_raw: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(model, dict) or model.get("schema_version") != VERSION:
        return {"status": "invalid_input", "errors": [f"model.schema_version must be {VERSION}"]}
    instrument = model.get("instrument")
    symbol = instrument.get("symbol") if isinstance(instrument, dict) else None
    if not isinstance(symbol, str) or not symbol.strip() or instrument.get("market") != "CN" or instrument.get("asset_type") != "stock" or instrument.get("industry_type") != "operating_company" or instrument.get("currency") != "CNY":
        errors.append("instrument requires CN operating-company stock in CNY")
    else:
        identity = validate_instrument(symbol, "CN", "stock", "CNY")
        if not identity["valid"] or identity["normalized_symbol"] != symbol:
            errors.append("instrument.symbol must use canonical CN exchange suffix")
    try:
        as_of = date.fromisoformat(model["as_of_date"])
        if as_of > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            errors.append("as_of_date cannot be in the future")
    except (KeyError, TypeError, ValueError):
        errors.append("as_of_date must be an ISO date")
    base_revenue = model.get("base_revenue_cny")
    if not number(base_revenue, low=0):
        errors.append("base_revenue_cny must be positive and unscaled")
    anchor = model.get("revenue_anchor")
    if not isinstance(anchor, dict) or not isinstance(anchor.get("fact_id"), str) or not anchor["fact_id"].strip() or not isinstance(anchor.get("source_locator"), str) or not anchor["source_locator"].startswith("https://") or not isinstance(anchor.get("content_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", anchor["content_sha256"]) or not isinstance(anchor.get("reviewed_page"), str) or not anchor["reviewed_page"].strip() or not number(anchor.get("value")) or not number(anchor.get("scale"), low=0) or not close(base_revenue, anchor["value"] * anchor["scale"]):
        errors.append("revenue_anchor requires reviewed source locator/page, fact id, hash, value and scale matching base revenue")
    if not isinstance(dashboard, dict) or dashboard.get("stock_code") != symbol:
        errors.append("dashboard stock_code must match model instrument")
        scenarios = {}
    else:
        brief = dashboard.get("research_brief")
        if not isinstance(brief, dict) or not isinstance(brief.get("instrument"), dict) or any(brief["instrument"].get(field) != expected for field, expected in (("symbol", symbol), ("market", "CN"), ("asset_type", "stock"))):
            errors.append("dashboard research_brief instrument must match model")
        scenarios = dashboard.get("scenario_analysis")
        if not isinstance(scenarios, dict) or scenarios.get("valuation_contract_version") != "3.0" or scenarios.get("valuation_method") != "enterprise_value_bridge" or scenarios.get("currency") != "CNY" or scenarios.get("as_of_date") != model.get("as_of_date"):
            errors.append("dashboard requires matching stock 3.0 enterprise_value_bridge in CNY and as_of_date")
            scenarios = {}
    cases = model.get("cases")
    if not isinstance(cases, dict) or set(cases) != set(CASES):
        errors.append("model.cases requires exactly base, bull, bear")
        cases = {}
    results: dict[str, dict[str, float]] = {}
    for label in CASES:
        case = cases.get(label)
        if not isinstance(case, dict):
            errors.append(f"{label} requires a case object")
            continue
        years = case.get("years")
        r, g = case.get("discount_rate"), case.get("terminal_growth")
        if not isinstance(years, list) or not 1 <= len(years) <= 10 or not number(r, low=0, high=1) or not number(g, low=-1) or not g < r:
            errors.append(f"{label} requires 1..10 forecast years and -1 < terminal_growth < discount_rate < 1")
            continue
        revenue = float(base_revenue) if number(base_revenue, low=0) else 0.0
        pv = 0.0
        valid = True
        last_fcf = None
        for year, row in enumerate(years, start=1):
            if not isinstance(row, dict) or row.get("year") != year:
                errors.append(f"{label}.years[{year - 1}] must identify forecast year {year}")
                valid = False
                continue
            growth, margin, tax = (row.get(key) for key in ("revenue_growth", "operating_margin", "cash_tax_rate"))
            da, capex, nwc = (row.get(key) for key in ("depreciation_amortization_cny", "capital_expenditure_cny", "change_in_working_capital_cny"))
            if not number(growth, low=-1) or not number(margin, low=-1, high=1) or not number(tax) or not 0 <= tax <= 1 or not number(da) or da < 0 or not number(capex) or capex < 0 or not number(nwc):
                errors.append(f"{label}.years[{year - 1}] has missing or invalid operating drivers")
                valid = False
                continue
            revenue *= 1 + growth
            fcf = revenue * margin * (1 - tax) + da - capex - nwc
            pv += fcf / (1 + r) ** year
            last_fcf = fcf
        if not valid or last_fcf is None or last_fcf <= 0:
            errors.append(f"{label} terminal FCF must be positive and all years valid")
            continue
        terminal = last_fcf * (1 + g) / (r - g)
        ev = pv + terminal / (1 + r) ** len(years)
        if not math.isfinite(ev) or ev <= 0:
            errors.append(f"{label} enterprise value is nonfinite or nonpositive")
            continue
        dashboard_case = scenarios.get(label)
        if not isinstance(dashboard_case, dict) or not close(dashboard_case.get("enterprise_value"), ev):
            errors.append(f"dashboard {label}.enterprise_value differs from recomputed DCF")
        results[label] = {"enterprise_value_cny": round(ev, 2), "forecast_pv_cny": round(pv, 2), "terminal_pv_cny": round(terminal / (1 + r) ** len(years), 2), "terminal_share": round((terminal / (1 + r) ** len(years)) / ev, 6)}
    source_anchor_status = "self_report_only"
    if verify_filing_raw and filing_package is None:
        errors.append("verify_filing_raw requires filing_package")
    if filing_package is not None and not verify_filing_raw:
        errors.append("filing_package requires explicit verify_filing_raw")
    if filing_package is not None and verify_filing_raw and not errors:
        filing = evaluate_filing_facts(filing_package, verify_raw=True)
        if filing.get("status") != "complete":
            errors.append("filing_package did not pass raw capture and correction chain validation")
        elif filing_package["instrument"].get("symbol") != symbol or date.fromisoformat(filing_package["cutoff_at"][:10]) > as_of:
            errors.append("filing issuer or cutoff differs from model instrument/as_of_date")
        else:
            matches = [fact for fact in filing["selected_facts"] if fact["fact_id"] == anchor["fact_id"] and fact["metric"] == "operating_revenue_consolidated" and fact["unit"] == "CNY" and fact["period_end"] <= model["as_of_date"]]
            if len(matches) != 1 or any(matches[0].get(field) != anchor.get(field) for field in ("value", "scale", "source_locator", "content_sha256")) or not math.isclose(matches[0]["value"] * matches[0]["scale"], base_revenue, rel_tol=0, abs_tol=0.005):
                errors.append("revenue_anchor differs from selected verified filing fact")
            else:
                source_anchor_status = "raw_capture_bound_semantics_unverified"
    if errors:
        return {"status": "invalid_input", "errors": errors}
    return {"status": "complete", "detail_status": "operating_dcf_arithmetic_recomputed_assumptions_unverified", "source_anchor_status": source_anchor_status, "cases": results, "limitations": ["Forecast inputs, revenue anchor meaning, discount rate and terminal growth remain analyst assumptions; this gate does not replace dashboard_gate or dashboard_math_gate."]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline A-share operating DCF driver check against stock Dashboard 3.0")
    parser.add_argument("model", type=Path)
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--filing-package", type=Path, help="Explicit filing package to bind the revenue anchor")
    parser.add_argument("--verify-filing-raw", action="store_true", help="Authorize reading raw_artifact paths in the supplied filing package")
    args = parser.parse_args()
    try:
        documents = []
        for path in (args.model, args.dashboard, *((args.filing_package,) if args.filing_package else ())):
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("input_size_limit")
            documents.append(json.loads(raw.decode("utf-8")))
        result = evaluate(*documents[:2], filing_package=documents[2] if args.filing_package else None, verify_filing_raw=args.verify_filing_raw)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "invalid_input", "errors": [f"inputs unreadable: {type(exc).__name__}: {exc}"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 3


if __name__ == "__main__":
    sys.exit(main())
