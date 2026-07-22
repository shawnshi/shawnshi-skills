import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

import requests

from instrument_gate import validate_instrument


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
NASDAQ_INFO_URL = "https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=stocks"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ACCEPTED_DISCLOSURE_FORMS = {"10-K", "10-Q", "8-K", "20-F", "40-F", "6-K"}


class LiveProbeError(RuntimeError):
    pass


def _default_fetch_json(url: str, headers: dict[str, str], timeout: int) -> tuple[dict[str, Any], int, str]:
    response = requests.get(url, headers=headers, timeout=timeout)
    if response.status_code != 200:
        raise LiveProbeError(f"HTTP {response.status_code} from {url}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise LiveProbeError(f"non-JSON response from {url}") from exc
    if not isinstance(payload, dict):
        raise LiveProbeError(f"JSON object expected from {url}")
    return payload, response.status_code, response.url


def _exchange_family(value: Any) -> str | None:
    text = str(value or "").upper().replace(" ", "").replace("-", "")
    if any(token in text for token in ("NASDAQ", "NMS", "NGS", "NCM")):
        return "NASDAQ"
    if "NYSE" in text or text == "NYQ":
        return "NYSE"
    if "AMEX" in text or text == "ASE":
        return "AMEX"
    return text or None


def _iso_utc(epoch: Any) -> str | None:
    try:
        value = float(epoch)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _formal_sec_contact_allowed(user_agent: str) -> bool:
    match = re.search(r"[A-Z0-9._%+-]+@([A-Z0-9.-]+)", user_agent, flags=re.IGNORECASE)
    if not match:
        return False
    domain = match.group(1).lower()
    return not (
        domain in {"localhost", "example.com", "example.org", "example.net"}
        or domain.endswith(".example")
        or domain.endswith(".invalid")
        or domain.endswith(".test")
    )


def _recent_filings(submissions: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    output: list[dict[str, Any]] = []
    for index, form in enumerate(forms):
        if form not in ACCEPTED_DISCLOSURE_FORMS:
            continue
        try:
            accession = recent["accessionNumber"][index]
            filing_date = recent["filingDate"][index]
            primary_document = recent["primaryDocument"][index]
        except (KeyError, IndexError, TypeError):
            continue
        accession_compact = str(accession).replace("-", "")
        cik_compact = str(submissions.get("cik") or "").lstrip("0")
        output.append(
            {
                "form": form,
                "filing_date": filing_date,
                "accession_number": accession,
                "primary_document": primary_document,
                "filing_locator": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_compact}/"
                    f"{accession_compact}/{primary_document}"
                ),
            }
        )
        if len(output) >= limit:
            break
    return output


def probe_us_stock(
    symbol: str,
    sec_user_agent: str,
    timeout: int = 20,
    max_price_age_days: int = 7,
    fetch_json: Callable[[str, dict[str, str], int], tuple[dict[str, Any], int, str]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    fetch = fetch_json or _default_fetch_json
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gate = validate_instrument(symbol, "US", "stock", "USD")
    normalized = gate.get("normalized_symbol")
    errors = list(gate.get("errors", []))
    if not sec_user_agent or len(sec_user_agent.strip()) < 8:
        errors.append("a descriptive SEC user agent is required")
    if errors or not normalized:
        return {
            "valid": False,
            "formal_use_allowed": False,
            "symbol": normalized,
            "market": "US",
            "retrieved_at": retrieved_at.isoformat(),
            "sources": {},
            "cross_checks": {},
            "errors": errors,
        }

    public_headers = {
        "User-Agent": "Mozilla/5.0 PersonalInvestmentAdvisor/1.0",
        "Accept": "application/json, text/plain, */*",
    }
    nasdaq_headers = {
        **public_headers,
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{normalized.lower()}",
    }
    sec_headers = {
        "User-Agent": sec_user_agent.strip(),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }
    sec_ticker_headers = {**sec_headers, "Host": "www.sec.gov"}
    sec_submission_headers = {**sec_headers, "Host": "data.sec.gov"}

    yahoo_url = YAHOO_CHART_URL.format(symbol=quote(normalized))
    nasdaq_url = NASDAQ_INFO_URL.format(symbol=quote(normalized))
    yahoo_payload, yahoo_status, yahoo_final_url = fetch(yahoo_url, public_headers, timeout)
    nasdaq_payload, nasdaq_status, nasdaq_final_url = fetch(nasdaq_url, nasdaq_headers, timeout)
    tickers_payload, tickers_status, tickers_final_url = fetch(
        SEC_TICKERS_URL, sec_ticker_headers, timeout
    )

    chart_results = yahoo_payload.get("chart", {}).get("result") or []
    if not chart_results:
        raise LiveProbeError("Yahoo chart response has no result")
    chart = chart_results[0]
    quote_meta = chart.get("meta", {})
    quote_symbol = str(quote_meta.get("symbol") or "").upper()
    quote_time = _iso_utc(quote_meta.get("regularMarketTime"))
    quote_price = quote_meta.get("regularMarketPrice")
    try:
        quote_price = float(quote_price)
    except (TypeError, ValueError) as exc:
        raise LiveProbeError("Yahoo quote price is missing or non-numeric") from exc
    if quote_price <= 0:
        errors.append("market price must be positive")
    if not quote_time:
        errors.append("market price timestamp is missing")
    else:
        age_days = (retrieved_at.date() - datetime.fromisoformat(quote_time).date()).days
        if age_days < 0 or age_days > max_price_age_days:
            errors.append(f"market price age is {age_days} days; allowed range is 0..{max_price_age_days}")

    nasdaq_data = nasdaq_payload.get("data") or {}
    nasdaq_symbol = str(nasdaq_data.get("symbol") or "").upper()
    nasdaq_exchange = nasdaq_data.get("exchange")
    if not nasdaq_symbol:
        errors.append("Nasdaq identity response is missing symbol")

    fields = tickers_payload.get("fields") or []
    data = tickers_payload.get("data") or []
    try:
        ticker_index = fields.index("ticker")
        cik_index = fields.index("cik")
        name_index = fields.index("name")
        exchange_index = fields.index("exchange")
    except ValueError as exc:
        raise LiveProbeError("SEC ticker association fields are incomplete") from exc
    sec_row = next((row for row in data if str(row[ticker_index]).upper() == normalized), None)
    if sec_row is None:
        errors.append("symbol was not found in SEC ticker/exchange associations")
        cik = None
        sec_name = None
        sec_exchange = None
        submissions_payload: dict[str, Any] = {}
        submissions_status = None
        submissions_final_url = None
        filings: list[dict[str, Any]] = []
    else:
        cik = f"{int(sec_row[cik_index]):010d}"
        sec_name = sec_row[name_index]
        sec_exchange = sec_row[exchange_index]
        submissions_url = SEC_SUBMISSIONS_URL.format(cik=cik)
        submissions_payload, submissions_status, submissions_final_url = fetch(
            submissions_url, sec_submission_headers, timeout
        )
        filings = _recent_filings(submissions_payload)
        if not filings:
            errors.append("SEC submissions response has no accepted company disclosure forms")

    symbol_match = normalized == quote_symbol == nasdaq_symbol
    exchange_match = _exchange_family(nasdaq_exchange) == _exchange_family(sec_exchange)
    submissions_symbol_match = normalized in {
        str(item).upper() for item in submissions_payload.get("tickers", [])
    }
    submissions_exchange_match = _exchange_family(sec_exchange) in {
        _exchange_family(item) for item in submissions_payload.get("exchanges", [])
    }
    for name, passed in {
        "symbol_match": symbol_match,
        "exchange_match": exchange_match,
        "submissions_symbol_match": submissions_symbol_match,
        "submissions_exchange_match": submissions_exchange_match,
    }.items():
        if not passed:
            errors.append(f"cross-check failed: {name}")

    formal_contact_allowed = _formal_sec_contact_allowed(sec_user_agent)
    formal_blockers = [] if formal_contact_allowed else [
        "SEC User-Agent must contain a real non-test contact email for formal research use"
    ]

    return {
        "valid": not errors,
        "formal_use_allowed": not errors and formal_contact_allowed,
        "formal_blockers": formal_blockers,
        "symbol": normalized,
        "market": "US",
        "retrieved_at": retrieved_at.isoformat(),
        "sources": {
            "market_data": {
                "provider": "Yahoo Finance",
                "source_tier": "market_data",
                "locator": yahoo_final_url,
                "http_status": yahoo_status,
                "price": quote_price,
                "currency": quote_meta.get("currency"),
                "exchange": quote_meta.get("exchangeName") or quote_meta.get("exchange"),
                "data_timestamp": quote_time,
            },
            "exchange_identity": {
                "provider": "Nasdaq",
                "source_tier": "exchange_primary",
                "locator": nasdaq_final_url,
                "http_status": nasdaq_status,
                "symbol": nasdaq_symbol,
                "company_name": nasdaq_data.get("companyName"),
                "exchange": nasdaq_exchange,
                "market_status": nasdaq_data.get("marketStatus"),
            },
            "regulator_identity": {
                "provider": "SEC",
                "source_tier": "regulator_primary",
                "locator": tickers_final_url,
                "http_status": tickers_status,
                "cik": cik,
                "company_name": sec_name,
                "exchange": sec_exchange,
            },
            "company_disclosures": {
                "provider": "SEC EDGAR",
                "source_tier": "regulator_filing",
                "locator": submissions_final_url,
                "http_status": submissions_status,
                "filings": filings,
            },
        },
        "cross_checks": {
            "symbol_match": symbol_match,
            "exchange_match": exchange_match,
            "submissions_symbol_match": submissions_symbol_match,
            "submissions_exchange_match": submissions_exchange_match,
        },
        "errors": errors,
        "scope": "US exchange-listed operating-company stocks; ETFs, funds, ADR edge cases, CN and HK require market-specific official sources",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a live US quote, exchange identity, SEC identity, and recent company disclosures."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", default="US", choices=["US"])
    parser.add_argument("--asset-type", default="stock", choices=["stock"])
    parser.add_argument("--sec-user-agent", default=os.environ.get("PIA_SEC_USER_AGENT"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-price-age-days", type=int, default=7)
    args = parser.parse_args()
    if not args.sec_user_agent:
        parser.error("--sec-user-agent or PIA_SEC_USER_AGENT is required")
    try:
        result = probe_us_stock(
            args.symbol,
            args.sec_user_agent,
            timeout=args.timeout,
            max_price_age_days=args.max_price_age_days,
        )
    except (LiveProbeError, requests.RequestException) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
