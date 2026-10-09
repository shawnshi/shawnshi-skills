"""Read-only research/calculation lane for zero-quantity securities.

Actual portfolio quote bindings and weights are deliberately untouched. A quote
or an indicative third-party ratio never closes primary-source Thesis evidence.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dashboard_catalog
import dashboard_math_gate
import watchlist_gate
from portfolio_loader import analysis_positions, normalize_symbol, unpurchased_positions
from quote_evidence_contract import build_portfolio_snapshot_binding, canonical_json_binding
from thesis_evidence_gate import evaluate_thesis_evidence
from yf import MAX_QUOTE_AGE_SECONDS, _quote_contract_report

SCRIPT_DIR = Path(__file__).resolve().parent


def research_binding(positions: dict) -> dict:
    rows = [{key: row.get(key) for key in
             ("symbol", "name", "quantity", "market", "currency", "asset_type")}
            for row in unpurchased_positions(positions)]
    rows.sort(key=lambda row: normalize_symbol(row["symbol"]))
    held = build_portfolio_snapshot_binding(positions)
    digest = canonical_json_binding({"positions": rows, "held_snapshot": held})
    return {**digest, "schema_version": "pia_unpurchased_binding_v1",
            "scope": "unpurchased_research", "positions": rows,
            "held_snapshot_sha256": held["sha256"]}


def _number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and (not positive or value > 0) else None


def evaluate(positions: dict, quote_payload: Any, *, evaluation_epoch: float,
             dashboard_root: str | Path | None = None, thesis_payload: Any = None,
             holiday_table: dict | None = None, decision_scope: str = "advisory") -> dict:
    """Evaluate each zero row, preserving explicit missing/invalid evidence."""
    if _number(evaluation_epoch, positive=True) is None:
        raise ValueError("evaluation_epoch must be positive and finite")
    candidates = unpurchased_positions(positions)
    symbols = [normalize_symbol(row["symbol"]) for row in candidates]
    binding = research_binding(positions)
    records = quote_payload.get("records") if isinstance(quote_payload, dict) else quote_payload
    package_errors = []
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        records = []
        package_errors.append("research quote records must be a list of objects")
    grouped: dict[str, list[dict]] = {}
    for row in records:
        grouped.setdefault(normalize_symbol(row.get("symbol") or ""), []).append(row)
    extras = sorted(set(grouped) - set(symbols))
    if extras:
        package_errors.append("unexpected_research_symbols: " + ", ".join(extras))
    if (isinstance(quote_payload, dict)
            and canonical_json_binding(quote_payload.get("research_binding")) != canonical_json_binding(binding)):
        package_errors.append("research_snapshot_binding_mismatch")
    catalog = (dashboard_catalog.resolve_dashboards(dashboard_root, symbols)
               if dashboard_root is not None and symbols else {"entries": []})
    dashboards = {row["symbol"]: row for row in catalog.get("entries", [])
                  if row.get("status") == "valid"}
    thesis = (evaluate_thesis_evidence(
        thesis_payload, expected_symbols=symbols,
        portfolio_snapshot_binding=binding, evaluation_epoch=evaluation_epoch)
        if thesis_payload is not None and symbols else
        {"status": "not_assessed", "fatal_event_status": "not_assessed",
         "reason": "primary_source_research_thesis_pack_not_supplied"})
    result_rows = []
    for position in candidates:
        symbol = normalize_symbol(position["symbol"])
        matches = grouped.get(symbol, [])
        errors = list(package_errors)
        if len(matches) != 1:
            errors.append("quote_missing" if not matches else "duplicate_quote_symbol")
        quote = matches[0] if len(matches) == 1 else {}
        contract = _quote_contract_report(
            quote, position, now_epoch=evaluation_epoch,
            max_quote_age_seconds=MAX_QUOTE_AGE_SECONDS, holiday_table=holiday_table)
        errors.extend(contract.get("errors", []))
        price = (contract["quote_observation"]["price"]
                 if contract.get("status") == "matched" and not errors else None)
        info = quote.get("info") if isinstance(quote.get("info"), dict) else {}
        financial_currency = str(info.get("financialCurrency") or "").upper()
        currency = str(position.get("currency") or "").upper()
        eps = _number(info.get("trailingEps")) if price is not None else None
        pe_reason = ("quote_invalid" if price is None else
                     "not_applicable_non_stock" if str(position.get("asset_type") or "").lower() != "stock" else
                     "eps_missing_or_invalid" if eps is None else
                     "not_applicable_nonpositive_eps" if eps <= 0 else
                     "financial_currency_missing_or_mismatch" if financial_currency != currency else
                     "indicative_only")
        pe = price / eps if pe_reason == "indicative_only" else None
        valuation = {"status": "indicative_only" if pe is not None else "insufficient_data",
                     "price_to_trailing_eps": pe, "pe_reason": pe_reason,
                     "source": "Yahoo Finance screening data, not a primary valuation packet",
                     "share_basis_and_earnings_freshness_verified": False,
                     "reason": "primary valuation evidence still required"}
        boundary = {"status": "insufficient_evidence", "detail_status":
                    "dashboard_root_not_authorized" if dashboard_root is None else "dashboard_missing"}
        dashboard_status = "not_authorized" if dashboard_root is None else "missing"
        if symbol in dashboards:
            # Index resolver validates generation integrity. Do not scan old markdown.
            data = json.loads(Path(dashboards[symbol]["json_path"]).read_text(encoding="utf-8"))
            math_errors = dashboard_math_gate.validate_math_consistency(data)
            dashboard_status = "invalid_math" if math_errors else "validated"
            if math_errors:
                valuation["dashboard_math_errors"] = math_errors
            scenarios = data.get("scenario_analysis") or {}
            base_value = _number((scenarios.get("base") or {}).get("per_share_value"), positive=True)
            if (not math_errors and price is not None and base_value is not None
                    and str(data.get("currency") or "").upper() == currency
                    and scenarios.get("valuation_contract_version") in ("2.0", "3.0")):
                valuation.update(status="complete", source="indexed gate-valid Dashboard scenario",
                                 base_per_share_value=base_value,
                                 price_vs_base_value_pct=(price / base_value - 1) * 100,
                                 reason="scenario comparison, not an executable fair-value guarantee")
            observation = contract.get("quote_observation") or {}
            if price is not None and observation.get("session") == "REGULAR":
                runtime = {"symbol": symbol, "current_price": price, "currency": currency,
                           "as_of": datetime.fromtimestamp(observation["epoch"], timezone.utc).isoformat(),
                           "source": "Yahoo Finance", "market_state": info.get("marketState")}
                boundary = watchlist_gate.evaluate_watchlist(
                    data, runtime, now=datetime.fromtimestamp(evaluation_epoch, timezone.utc),
                    max_age_seconds=contract["freshness_policy"]["applied_max_age_seconds"])
            else:
                boundary = {"status": "insufficient_data",
                            "detail_status": "validated_regular_session_quote_required"}
        result_rows.append({
            "symbol": symbol, "name": position.get("name"), "lane": "unpurchased_research",
            "actual_quantity": 0, "actual_market_value": 0.0, "actual_cost_basis": 0.0,
            "excluded_from_actual_weight_denominator": True,
            "unrealized_pnl": None, "unrealized_pnl_pct": None,
            "current_price": price, "currency": currency,
            "quote_status": "matched" if price is not None else "insufficient_data",
            "quote_contract": contract, "valuation": valuation,
            "dashboard_status": dashboard_status, "observation_boundaries": boundary,
            "thesis_status": thesis.get("status"), "errors": errors,
            "trade_parameters": None,
        })
    quotes_complete = not package_errors and all(row["current_price"] is not None for row in result_rows)
    complete = (not symbols or (quotes_complete and thesis.get("status") == "complete"
                and all(row["dashboard_status"] == "validated" and
                        row["valuation"].get("status") == "complete" and
                        row["observation_boundaries"].get("status") == "complete"
                        for row in result_rows)))
    return {"schema_version": "pia_unpurchased_analysis_v1",
            "status": "complete" if complete else "insufficient_evidence",
            "detail_status": "no_unpurchased_securities" if not symbols else
                             "unpurchased_research_complete" if complete else "unpurchased_research_incomplete",
            "decision_scope": decision_scope, "evaluation_epoch": evaluation_epoch,
            "expected_symbols": symbols, "research_binding": binding,
            "coverage": {"held_non_cash_count": len(analysis_positions(positions)) - len(symbols),
                         "unpurchased_count": len(symbols),
                         "analysis_non_cash_count": len(analysis_positions(positions)),
                         "quote_coverage_complete": quotes_complete},
            "rows": result_rows, "thesis_red_team": thesis, "errors": package_errors,
            "orders_executed": False}


def run(positions: dict, *, task_dir: Path, cache_dir: Path, evaluation_epoch: float,
        dashboard_root: Path | None = None, quotes_file: Path | None = None,
        thesis_file: Path | None = None, holiday_table: dict | None = None,
        decision_scope: str = "advisory", reuse: bool = False) -> dict:
    """Collect ordinary quote-only research records, never a fabricated portfolio."""
    symbols = [row["symbol"] for row in unpurchased_positions(positions)]
    output = task_dir / "out" / "unpurchased_quotes.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    capture_errors = []
    source = quotes_file or (output if reuse and symbols else None)
    if source is not None:
        payload = json.loads(source.read_text(encoding="utf-8"))
        # Replay must prove this is the same zero-quantity research universe.
        if (not isinstance(payload, dict)
                or canonical_json_binding(payload.get("research_binding")) != canonical_json_binding(research_binding(positions))):
            raise ValueError("research_snapshot_binding_mismatch")
    elif symbols:
        command = [sys.executable, "-B", str(SCRIPT_DIR / "yf.py"), *symbols,
                   "--json", "--info-only", "--cache-dir", str(cache_dir)]
        completed = subprocess.run(command, capture_output=True, timeout=900, check=False)
        try:
            records = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("unpurchased_quote_output_invalid") from exc
        payload = {"records": records, "research_binding": research_binding(positions)}
        if completed.returncode:
            capture_errors.append(f"quote_process_exit_{completed.returncode}")
    else:
        payload = {"records": [], "research_binding": research_binding(positions)}
    # Never relabel a supplied/replayed packet with a newly minted binding.
    if source != output:
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    thesis = json.loads(thesis_file.read_text(encoding="utf-8")) if thesis_file else None
    report = evaluate(positions, payload, evaluation_epoch=evaluation_epoch,
                      dashboard_root=dashboard_root, thesis_payload=thesis,
                      holiday_table=holiday_table, decision_scope=decision_scope)
    if capture_errors:
        report["status"] = "insufficient_evidence"
        report["errors"].extend(capture_errors)
    (task_dir / "out" / "unpurchased_analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
