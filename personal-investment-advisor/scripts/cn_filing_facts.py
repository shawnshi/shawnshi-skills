"""Offline A-share filing fact selection; source authenticity remains a human check.

No network, file discovery, portfolio access, or implicit raw-artifact reads.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from instrument_gate import validate_instrument
from source_timing_contract import aware, iso_day, validate_source_timing, verify_source_capture

VERSION = "pia_cn_filing_facts_v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_FACTS = 1000


def evaluate(package: Any, *, verify_raw: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(package, dict) or package.get("schema_version") != VERSION:
        return {"status": "invalid_input", "errors": [f"schema_version must be {VERSION}"]}
    instrument = package.get("instrument")
    if not isinstance(instrument, dict) or instrument.get("market") != "CN" or instrument.get("asset_type") != "stock" or not isinstance(instrument.get("symbol"), str) or not instrument["symbol"].strip():
        errors.append("instrument requires CN stock and nonempty symbol")
    else:
        identity = validate_instrument(instrument["symbol"], "CN", "stock", "CNY")
        if not identity["valid"] or identity["normalized_symbol"] != instrument["symbol"]:
            errors.append("instrument.symbol must use canonical CN exchange suffix")
    try:
        cutoff = aware(package.get("cutoff_at"))
        if cutoff > datetime.now(timezone.utc):
            errors.append("cutoff_at cannot be in the future")
    except (ValueError, TypeError):
        errors.append("cutoff_at requires a timezone-aware seconds-level timestamp")
        cutoff = None
    facts = package.get("facts")
    if not isinstance(facts, list) or not 0 < len(facts) <= MAX_FACTS:
        errors.append(f"facts must contain 1..{MAX_FACTS} records")
        facts = []
    by_id: dict[str, dict[str, Any]] = {}
    keys: set[tuple[str, str, str]] = set()
    for index, fact in enumerate(facts):
        prefix = f"facts[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{prefix} must be an object")
            continue
        ident = fact.get("fact_id")
        if not isinstance(ident, str) or not ident.strip() or ident in by_id:
            errors.append(f"{prefix}.fact_id missing or duplicate")
            continue
        by_id[ident] = fact
        if not isinstance(instrument, dict) or fact.get("symbol") != instrument.get("symbol"):
            errors.append(f"{prefix}.symbol must match instrument")
        try:
            period = iso_day(fact.get("period_end")).isoformat()
            if cutoff is not None and period > cutoff.date().isoformat():
                errors.append(f"{prefix}.period_end follows cutoff")
        except (ValueError, TypeError):
            errors.append(f"{prefix}.period_end invalid")
            continue
        metric, unit, value, scale = fact.get("metric"), fact.get("unit"), fact.get("value"), fact.get("scale")
        if not isinstance(metric, str) or not metric.strip() or not isinstance(unit, str) or not unit.strip() or type(value) not in (int, float) or not math.isfinite(value) or type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
            errors.append(f"{prefix} requires metric, unit, positive scale and finite numeric value")
            continue
        keys.add((metric, period, unit))
        if fact.get("source_type") != "filing" or fact.get("source_tier") not in ("company_primary", "exchange", "annual_audited_filing", "quarterly_filing", "current_report"):
            errors.append(f"{prefix} requires primary filing evidence")
        if fact.get("valuation_date") != period:
            errors.append(f"{prefix}.valuation_date must equal period_end")
        if cutoff is not None:
            errors.extend(validate_source_timing(fact, {"cutoff_at": package["cutoff_at"]}, prefix))
        if verify_raw:
            receipt = fact.get("source_capture_receipt")
            if not isinstance(receipt, dict):
                errors.append(f"{prefix} missing source capture receipt")
            else:
                try:
                    verify_source_capture(receipt.get("raw_artifact"), source_locator=fact.get("source_locator"), availability_observed_at=fact.get("availability_observed_at"), retrieved_at=fact.get("retrieved_at"), expected_sha256=fact.get("content_sha256"), expected_receipt=receipt)
                except (OSError, ValueError, TypeError) as exc:
                    errors.append(f"{prefix} raw capture verification failed: {type(exc).__name__}")
    successors: dict[str, str] = {}
    for ident, fact in by_id.items():
        parent_id = fact.get("supersedes_fact_id")
        if parent_id is None:
            if fact.get("revision") != "original":
                errors.append(f"{ident} without parent must be original")
            continue
        parent = by_id.get(parent_id)
        if fact.get("revision") != "correction" or parent is None or parent_id == ident:
            errors.append(f"{ident} correction requires an existing distinct parent")
            continue
        if parent_id in successors:
            errors.append(f"{parent_id} correction chain forks")
        successors[parent_id] = ident
        if any(fact.get(field) != parent.get(field) for field in ("symbol", "metric", "period_end", "unit", "scale")):
            errors.append(f"{ident} correction changes metric, period, unit or scale")
        try:
            if aware(fact.get("availability_observed_at")) <= aware(parent.get("availability_observed_at")):
                errors.append(f"{ident} correction must be observed after parent")
        except (ValueError, TypeError):
            errors.append(f"{ident} correction has invalid observation time")
    selected = []
    for key in sorted(keys):
        leaves = [fact for ident, fact in by_id.items() if (fact.get("metric"), fact.get("period_end"), fact.get("unit")) == key and ident not in successors]
        if len(leaves) != 1:
            errors.append(f"ambiguous original/correction chain for {key}")
        elif not errors:
            fact = leaves[0]
            selected.append({"fact_id": fact["fact_id"], "metric": key[0], "period_end": key[1], "unit": key[2], "scale": fact["scale"], "value": fact["value"], "availability_observed_at": fact["availability_observed_at"], "retrieved_at": fact["retrieved_at"], "source_locator": fact["source_locator"], "content_sha256": fact["content_sha256"]})
    if errors:
        return {"status": "invalid_input", "errors": errors}
    return {"status": "complete" if verify_raw else "insufficient_evidence", "detail_status": "raw_capture_reverified_semantics_unverified" if verify_raw else "raw_capture_not_reverified", "selected_facts": selected if verify_raw else [], "limitations": ["Source identity, excerpt meaning and full amendment coverage require independent review; a hash does not prove historical availability."]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline A-share filing facts and correction chain gate")
    parser.add_argument("package", type=Path)
    parser.add_argument("--verify-raw", action="store_true", help="Explicitly read every raw_artifact named in the authorized package")
    args = parser.parse_args()
    try:
        with args.package.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("input_size_limit")
        result = evaluate(json.loads(raw.decode("utf-8")), verify_raw=args.verify_raw)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "invalid_input", "errors": [f"package unreadable: {type(exc).__name__}: {exc}"]}
    print(json.dumps(result, ensure_ascii=False))
    return {"complete": 0, "insufficient_evidence": 2}.get(result["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
