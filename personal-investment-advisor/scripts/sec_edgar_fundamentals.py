"""Build free point-in-time annual fundamental snapshots from SEC EDGAR."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, time, timezone
from typing import Any, cast

import requests


SCHEMA_VERSION = "pia_sec_edgar_fundamentals_v1"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
RESERVED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "example.test",
    "localhost",
}
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@([A-Z0-9.-]+)", re.IGNORECASE)
TAG_CANDIDATES = {
    "diluted_eps": (
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ),
    "net_income": (
        "NetIncomeLoss",
        "NetIncomeLossAttributableToParent",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "stockholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquityAttributableToParent",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}
PREFERRED_UNITS = {
    "diluted_eps": ("USD/shares", "USD / shares"),
    "net_income": ("USD",),
    "stockholders_equity": ("USD",),
    "operating_cash_flow": ("USD",),
    "diluted_shares": ("shares",),
}


def parse_as_of(value: str) -> datetime:
    rendered = value.strip()
    try:
        if "T" in rendered:
            parsed = datetime.fromisoformat(rendered.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("datetime must include a timezone")
            return parsed.astimezone(timezone.utc)
        parsed_date = date.fromisoformat(rendered)
    except ValueError as exc:
        raise ValueError("--as-of must be an ISO date or timezone-aware datetime") from exc
    return datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)


def validate_user_agent(value: str | None) -> str:
    rendered = str(value or "").strip()
    match = EMAIL_PATTERN.search(rendered)
    if not rendered or match is None:
        raise ValueError("PIA_SEC_USER_AGENT must contain a real contact email")
    domain = match.group(1).lower().rstrip(".")
    if domain in RESERVED_EMAIL_DOMAINS or domain.endswith((".test", ".invalid")):
        raise ValueError("PIA_SEC_USER_AGENT must not use a test email domain")
    return rendered


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _unit_lists(concept: dict[str, Any], preferred: tuple[str, ...]) -> list[tuple[str, list[Any]]]:
    units = concept.get("units")
    if not isinstance(units, dict):
        return []
    ordered = [unit for unit in preferred if isinstance(units.get(unit), list)]
    ordered.extend(unit for unit, facts in units.items() if unit not in ordered and isinstance(facts, list))
    return [(unit, units[unit]) for unit in ordered]


def _fact_payload(tag: str, unit: str, fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "concept": tag,
        "unit": unit,
        "value": fact.get("val"),
        "period_start": fact.get("start"),
        "period_end": fact.get("end"),
        "filed": fact.get("filed"),
        "form": fact.get("form"),
        "accession": fact.get("accn"),
    }


def _latest_annual_fact(
    us_gaap: dict[str, Any],
    candidates: tuple[str, ...],
    preferred_units: tuple[str, ...],
    as_of: datetime,
) -> dict[str, Any] | None:
    cutoff = as_of.date()
    for tag in candidates:
        concept = us_gaap.get(tag)
        if not isinstance(concept, dict):
            continue
        eligible: list[tuple[date, date, str, dict[str, Any]]] = []
        for unit, facts in _unit_lists(concept, preferred_units):
            for raw in facts:
                if not isinstance(raw, dict) or raw.get("val") is None:
                    continue
                start = _parse_date(raw.get("start"))
                end = _parse_date(raw.get("end"))
                filed = _parse_date(raw.get("filed"))
                if start is None or end is None or filed is None or filed > cutoff:
                    continue
                if raw.get("form") not in {"10-K", "10-K/A"}:
                    continue
                if not 250 <= (end - start).days <= 430:
                    continue
                eligible.append((end, filed, unit, raw))
        if eligible:
            _, _, unit, fact = max(eligible, key=lambda item: (item[0], item[1]))
            return _fact_payload(tag, unit, fact)
    return None


def _latest_instant_fact(
    us_gaap: dict[str, Any],
    candidates: tuple[str, ...],
    preferred_units: tuple[str, ...],
    as_of: datetime,
) -> dict[str, Any] | None:
    cutoff = as_of.date()
    for tag in candidates:
        concept = us_gaap.get(tag)
        if not isinstance(concept, dict):
            continue
        eligible: list[tuple[date, date, str, dict[str, Any]]] = []
        for unit, facts in _unit_lists(concept, preferred_units):
            for raw in facts:
                if not isinstance(raw, dict) or raw.get("val") is None or raw.get("start"):
                    continue
                end = _parse_date(raw.get("end"))
                filed = _parse_date(raw.get("filed"))
                if end is None or filed is None or filed > cutoff:
                    continue
                if raw.get("form") not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                    continue
                eligible.append((end, filed, unit, raw))
        if eligible:
            _, _, unit, fact = max(eligible, key=lambda item: (item[0], item[1]))
            return _fact_payload(tag, unit, fact)
    return None


def extract_company_snapshot(
    companyfacts: dict[str, Any],
    *,
    symbol: str,
    as_of: datetime,
    source_locator: str,
    content_sha256: str,
    retrieved_at: datetime,
) -> dict[str, Any]:
    facts_root = companyfacts.get("facts")
    us_gaap = facts_root.get("us-gaap", {}) if isinstance(facts_root, dict) else {}
    selected: dict[str, Any] = {}
    for name in ("diluted_eps", "net_income", "operating_cash_flow", "diluted_shares"):
        selected[name] = _latest_annual_fact(
            us_gaap,
            TAG_CANDIDATES[name],
            PREFERRED_UNITS[name],
            as_of,
        )
    selected["stockholders_equity"] = _latest_instant_fact(
        us_gaap,
        TAG_CANDIDATES["stockholders_equity"],
        PREFERRED_UNITS["stockholders_equity"],
        as_of,
    )
    missing = sorted(
        name
        for name, fact in selected.items()
        if not isinstance(fact, dict)
        or isinstance(fact.get("value"), bool)
        or not isinstance(fact.get("value"), (int, float))
        or not math.isfinite(float(fact["value"]))
    )
    derived: dict[str, float] = {}
    if not missing:
        net_income = float(cast(dict[str, Any], selected["net_income"])["value"])
        equity = float(cast(dict[str, Any], selected["stockholders_equity"])["value"])
        cash_flow = float(cast(dict[str, Any], selected["operating_cash_flow"])["value"])
        shares = float(cast(dict[str, Any], selected["diluted_shares"])["value"])
        if equity > 0:
            derived["roe"] = net_income / equity
        if shares > 0:
            derived["operating_cash_flow_per_diluted_share"] = cash_flow / shares
    return {
        "symbol": symbol,
        "cik": str(companyfacts.get("cik") or "").zfill(10),
        "entity_name": companyfacts.get("entityName"),
        "status": "complete" if not missing else "insufficient_evidence",
        "detail_status": "point_in_time_annual_snapshot_complete" if not missing else "required_annual_facts_missing",
        "as_of": as_of.isoformat(),
        "facts": selected,
        "derived": derived,
        "missing_facts": missing,
        "evidence": {
            "source_provider": "SEC EDGAR companyfacts",
            "source_locator": source_locator,
            "retrieved_at": retrieved_at.isoformat(),
            "content_sha256": content_sha256,
        },
        "limitations": [
            "The snapshot uses facts filed on or before as_of and does not use later amendments.",
            "SEC companyfacts does not establish historical index membership or delisting returns.",
            "No price is fetched; P/E and cash-flow yield require a separately time-bound price source.",
        ],
    }


def fetch_json(session: requests.Session, url: str, *, user_agent: str, timeout: float) -> tuple[dict[str, Any], str]:
    response = session.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"SEC response is not a JSON object: {url}")
    return payload, hashlib.sha256(response.content).hexdigest()


def build_report(
    symbols: list[str],
    *,
    as_of: datetime,
    user_agent: str,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    normalized = [symbol.strip().upper().replace(".", "-") for symbol in symbols]
    if not normalized or any(not symbol for symbol in normalized) or len(normalized) != len(set(normalized)):
        raise ValueError("symbols must be non-empty and unique")
    active_session = session or requests.Session()
    retrieved_at = datetime.now(timezone.utc)
    ticker_map, ticker_map_sha = fetch_json(
        active_session,
        TICKER_MAP_URL,
        user_agent=user_agent,
        timeout=timeout,
    )
    by_symbol = {
        str(item.get("ticker") or "").upper(): str(item.get("cik_str") or "")
        for item in ticker_map.values()
        if isinstance(item, dict)
    }
    results = []
    for symbol in normalized:
        cik = by_symbol.get(symbol)
        if not cik:
            results.append({
                "symbol": symbol,
                "status": "insufficient_evidence",
                "detail_status": "sec_cik_not_found",
                "missing_facts": list(TAG_CANDIDATES),
            })
            continue
        locator = COMPANYFACTS_URL.format(cik=cik.zfill(10))
        payload, content_sha = fetch_json(
            active_session,
            locator,
            user_agent=user_agent,
            timeout=timeout,
        )
        results.append(
            extract_company_snapshot(
                payload,
                symbol=symbol,
                as_of=as_of,
                source_locator=locator,
                content_sha256=content_sha,
                retrieved_at=retrieved_at,
            )
        )
    complete = all(result.get("status") == "complete" for result in results)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if complete else "insufficient_evidence",
        "detail_status": "all_snapshots_complete" if complete else "one_or_more_snapshots_incomplete",
        "decision_scope": "research_only",
        "data_access_mode": "free_public",
        "as_of": as_of.isoformat(),
        "retrieved_at": retrieved_at.isoformat(),
        "ticker_map_evidence": {
            "source_locator": TICKER_MAP_URL,
            "content_sha256": ticker_map_sha,
        },
        "results": results,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--user-agent", help="Defaults to PIA_SEC_USER_AGENT.")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    try:
        user_agent = validate_user_agent(args.user_agent or os.environ.get("PIA_SEC_USER_AGENT"))
        as_of = parse_as_of(args.as_of)
        if as_of > datetime.now(timezone.utc):
            raise ValueError("--as-of cannot be in the future")
        if not 1 <= args.timeout <= 120:
            raise ValueError("--timeout must be between 1 and 120 seconds")
        report = build_report(
            args.symbols,
            as_of=as_of,
            user_agent=user_agent,
            timeout=args.timeout,
        )
    except (OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "invalid_input",
            "detail_status": "sec_edgar_snapshot_failed",
            "decision_scope": "research_only",
            "errors": [str(exc)],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
