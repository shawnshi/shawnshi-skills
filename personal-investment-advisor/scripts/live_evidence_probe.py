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
DISCLOSURE_TIER_BY_FORM = {
    "10-K": "annual_audited_filing",
    "10-K/A": "annual_audited_filing",
    "10-Q": "quarterly_filing",
    "10-Q/A": "quarterly_filing",
    "8-K": "current_report",
    "8-K/A": "current_report",
}
ACCEPTED_DISCLOSURE_FORMS = set(DISCLOSURE_TIER_BY_FORM)
FOREIGN_ISSUER_FORMS = {"20-F", "40-F", "6-K"}
QUOTE_FRESHNESS_POLICY_VERSION = "market-state-v1"
QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE = {
    "REGULAR": 15 * 60,
    "PREPRE": 24 * 60 * 60,
    "PRE": 24 * 60 * 60,
    "POST": 24 * 60 * 60,
    "POSTPOST": 24 * 60 * 60,
    "CLOSED": 72 * 60 * 60,
}
DISALLOWED_INSTRUMENT_TYPES = {
    "ADR",
    "ADS",
    "ETF",
    "MUTUALFUND",
    "MUTUAL FUND",
    "FUND",
    "INDEX",
}


class LiveProbeError(RuntimeError):
    pass


def _empty_probe_result(
    *,
    symbol: str | None,
    retrieved_at: datetime,
    status: str,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "identity_valid": False,
        "valid": False,
        "formal_use_allowed": False,
        "formal_blockers": list(errors),
        "symbol": symbol,
        "market": "US",
        "retrieved_at": retrieved_at.isoformat(),
        "sources": {},
        "cross_checks": {},
        "identity_errors": list(errors),
        "data_errors": [],
        "evidence_errors": [],
        "errors": list(errors),
    }


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


def _quote_freshness_policy(market_state: Any) -> dict[str, Any]:
    normalized = str(market_state or "").strip().upper()
    return {
        "version": QUOTE_FRESHNESS_POLICY_VERSION,
        "market_state": normalized or None,
        "max_age_seconds": QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE.get(normalized),
        "calendar_aware": False,
        "long_holiday_behavior": "fail_closed_after_state_threshold",
    }


def _resolve_market_state(
    quote_meta: dict[str, Any], retrieved_at: datetime
) -> tuple[str | None, str | None]:
    explicit = str(quote_meta.get("marketState") or "").strip().upper()
    if explicit:
        return explicit, "provider_market_state"

    periods = quote_meta.get("currentTradingPeriod")
    if not isinstance(periods, dict):
        return None, None
    now_epoch = retrieved_at.timestamp()
    valid_period_count = 0
    for period_name, state in (
        ("pre", "PRE"),
        ("regular", "REGULAR"),
        ("post", "POST"),
    ):
        period = periods.get(period_name)
        if not isinstance(period, dict):
            continue
        try:
            start = float(period.get("start"))
            end = float(period.get("end"))
        except (TypeError, ValueError):
            continue
        if start <= 0 or end <= start:
            continue
        valid_period_count += 1
        if start <= now_epoch < end:
            return state, "derived_from_current_trading_period"
    if valid_period_count:
        return "CLOSED", "derived_from_current_trading_period"
    return None, None


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


def _normalize_cik(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("CIK must contain 1 to 10 digits")
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,10}", text) or int(text) <= 0:
        raise ValueError("CIK must contain 1 to 10 digits and be greater than zero")
    return text.zfill(10)


def _has_depositary_marker(value: Any) -> bool:
    text = str(value or "").upper()
    return any(
        marker in text
        for marker in (
            " ADR",
            "ADR ",
            " ADS",
            "ADS ",
            "DEPOSITARY RECEIPT",
            "DEPOSITARY SHARE",
            "AMERICAN DEPOSITARY",
        )
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
                "source_tier": DISCLOSURE_TIER_BY_FORM[form],
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
    fetch_json: Callable[[str, dict[str, str], int], tuple[dict[str, Any], int, str]] | None = None,
    now: datetime | None = None,
    cik: str | int | None = None,
) -> dict[str, Any]:
    fetch = fetch_json or _default_fetch_json
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gate = validate_instrument(symbol, "US", "stock", "USD")
    normalized = gate.get("normalized_symbol")
    identity_errors = list(gate.get("errors", []))
    data_errors: list[str] = []
    evidence_errors: list[str] = []
    if not sec_user_agent or len(sec_user_agent.strip()) < 8:
        identity_errors.append("a descriptive SEC user agent is required")
    try:
        explicit_cik = _normalize_cik(cik)
    except ValueError as exc:
        identity_errors.append(str(exc))
    if identity_errors or not normalized:
        return _empty_probe_result(
            symbol=normalized,
            retrieved_at=retrieved_at,
            status="configuration_error" if not sec_user_agent else "identity_invalid",
            errors=identity_errors,
        )

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
    tickers_status = None
    tickers_final_url = None
    if explicit_cik is None:
        tickers_payload, tickers_status, tickers_final_url = fetch(
            SEC_TICKERS_URL, sec_ticker_headers, timeout
        )
    else:
        tickers_payload = {}

    chart_results = yahoo_payload.get("chart", {}).get("result") or []
    if not chart_results:
        raise LiveProbeError("Yahoo chart response has no result")
    chart = chart_results[0]
    quote_meta = chart.get("meta", {})
    quote_symbol = str(quote_meta.get("symbol") or "").upper()
    quote_time = _iso_utc(quote_meta.get("regularMarketTime"))
    market_state, market_state_source = _resolve_market_state(
        quote_meta, retrieved_at
    )
    freshness_policy = _quote_freshness_policy(market_state)
    quote_price = quote_meta.get("regularMarketPrice")
    try:
        quote_price = float(quote_price)
    except (TypeError, ValueError) as exc:
        raise LiveProbeError("Yahoo quote price is missing or non-numeric") from exc
    if quote_price <= 0:
        data_errors.append("market price must be positive")
    if not quote_time:
        data_errors.append("market price timestamp is missing")
    else:
        age_seconds = (
            retrieved_at - datetime.fromisoformat(quote_time).astimezone(timezone.utc)
        ).total_seconds()
        max_age_seconds = freshness_policy["max_age_seconds"]
        if max_age_seconds is None:
            data_errors.append(
                "market state is missing or unsupported; quote freshness cannot be established"
            )
        elif age_seconds < -60 * 60:
            data_errors.append("market price timestamp is more than 3600 seconds in the future")
        elif age_seconds > max_age_seconds:
            data_errors.append(
                f"market price age is {round(age_seconds, 3)} seconds; "
                f"{freshness_policy['market_state']} allows at most {max_age_seconds} seconds"
            )

    quote_instrument_type = str(
        quote_meta.get("instrumentType") or quote_meta.get("quoteType") or ""
    ).strip().upper()
    if quote_instrument_type in DISALLOWED_INSTRUMENT_TYPES:
        identity_errors.append(
            f"unsupported US instrument type: {quote_instrument_type}; use a market-specific evidence path"
        )

    nasdaq_data = nasdaq_payload.get("data") or {}
    nasdaq_symbol = str(nasdaq_data.get("symbol") or "").upper()
    nasdaq_exchange = nasdaq_data.get("exchange")
    if not nasdaq_symbol:
        identity_errors.append("Nasdaq identity response is missing symbol")
    nasdaq_asset_class = str(
        nasdaq_data.get("assetClass") or nasdaq_data.get("instrumentType") or ""
    ).strip().upper()
    if nasdaq_asset_class in DISALLOWED_INSTRUMENT_TYPES:
        identity_errors.append(
            f"unsupported Nasdaq instrument type: {nasdaq_asset_class}; use a market-specific evidence path"
        )
    if _has_depositary_marker(nasdaq_data.get("companyName")):
        identity_errors.append(
            "Nasdaq company identity indicates an ADR or depositary security edge case"
        )

    if explicit_cik is None:
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
    else:
        sec_row = None

    submissions_cik = None
    if explicit_cik is None and sec_row is None:
        identity_errors.append("symbol was not found in SEC ticker/exchange associations")
        resolved_cik = None
        sec_name = None
        sec_exchange = None
        submissions_payload: dict[str, Any] = {}
        submissions_status = None
        submissions_final_url = None
        filings: list[dict[str, Any]] = []
    else:
        resolved_cik = explicit_cik or f"{int(sec_row[cik_index]):010d}"
        sec_name = sec_row[name_index] if sec_row is not None else None
        sec_exchange = sec_row[exchange_index] if sec_row is not None else None
        submissions_url = SEC_SUBMISSIONS_URL.format(cik=resolved_cik)
        submissions_payload, submissions_status, submissions_final_url = fetch(
            submissions_url, sec_submission_headers, timeout
        )
        submissions_cik_raw = submissions_payload.get("cik")
        try:
            submissions_cik = _normalize_cik(submissions_cik_raw)
        except ValueError:
            submissions_cik = None
        if explicit_cik is not None and submissions_cik != resolved_cik:
            identity_errors.append("cross-check failed: submissions_cik_match")
        submission_tickers = [
            str(item).upper() for item in submissions_payload.get("tickers", [])
        ]
        submission_exchanges = list(submissions_payload.get("exchanges", []))
        if explicit_cik is not None:
            sec_name = submissions_payload.get("name")
            try:
                submission_index = submission_tickers.index(normalized)
            except ValueError:
                submission_index = None
            sec_exchange = (
                submission_exchanges[submission_index]
                if submission_index is not None
                and submission_index < len(submission_exchanges)
                else None
            )
        filings = _recent_filings(submissions_payload)
        recent_forms = set(
            submissions_payload.get("filings", {}).get("recent", {}).get("form", [])
        )
        foreign_forms = sorted(recent_forms.intersection(FOREIGN_ISSUER_FORMS))
        if foreign_forms:
            identity_errors.append(
                "foreign issuer disclosure forms detected: " + ", ".join(foreign_forms)
            )
        if not filings:
            evidence_errors.append(
                "SEC submissions response has no accepted domestic company disclosure forms"
            )
        if _has_depositary_marker(sec_name) or _has_depositary_marker(
            submissions_payload.get("name")
        ):
            identity_errors.append(
                "SEC company identity indicates an ADR or depositary security edge case"
            )

    symbol_match = normalized == quote_symbol == nasdaq_symbol
    yahoo_exchange = quote_meta.get("exchangeName") or quote_meta.get("exchange")
    exchange_match = _exchange_family(nasdaq_exchange) == _exchange_family(sec_exchange)
    if explicit_cik is not None:
        exchange_match = exchange_match and (
            _exchange_family(yahoo_exchange) == _exchange_family(sec_exchange)
        )
    submissions_symbol_match = normalized in {
        str(item).upper() for item in submissions_payload.get("tickers", [])
    }
    submissions_exchange_match = _exchange_family(sec_exchange) in {
        _exchange_family(item) for item in submissions_payload.get("exchanges", [])
    }
    submissions_cik_match = resolved_cik is not None and submissions_cik == resolved_cik
    cross_checks = {
        "symbol_match": symbol_match,
        "exchange_match": exchange_match,
        "submissions_symbol_match": submissions_symbol_match,
        "submissions_exchange_match": submissions_exchange_match,
    }
    if explicit_cik is not None:
        cross_checks["submissions_cik_match"] = submissions_cik_match
    for name, passed in cross_checks.items():
        if not passed:
            identity_errors.append(f"cross-check failed: {name}")

    formal_contact_allowed = _formal_sec_contact_allowed(sec_user_agent)
    formal_blockers = [] if formal_contact_allowed else [
        "SEC User-Agent must contain a real non-test contact email for formal research use"
    ]

    errors = list(dict.fromkeys(identity_errors + data_errors + evidence_errors))
    identity_valid = not identity_errors
    valid = not errors
    formal_use_allowed = valid and formal_contact_allowed
    if formal_use_allowed:
        status = "complete"
    elif not identity_valid:
        status = "identity_invalid"
    elif data_errors or evidence_errors:
        status = "insufficient_data"
    else:
        status = "formal_use_blocked"

    return {
        "status": status,
        "identity_valid": identity_valid,
        "valid": valid,
        "formal_use_allowed": formal_use_allowed,
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
                "market_state": freshness_policy["market_state"],
                "market_state_source": market_state_source,
                "data_timestamp": quote_time,
                "freshness_policy": freshness_policy,
            },
            "exchange_identity": {
                "provider": "Nasdaq",
                "source_tier": "exchange",
                "locator": nasdaq_final_url,
                "http_status": nasdaq_status,
                "symbol": nasdaq_symbol,
                "company_name": nasdaq_data.get("companyName"),
                "exchange": nasdaq_exchange,
                "market_status": nasdaq_data.get("marketStatus"),
            },
            "regulator_identity": {
                "provider": "SEC",
                "source_tier": "regulator",
                "locator": submissions_final_url if explicit_cik else tickers_final_url,
                "http_status": submissions_status if explicit_cik else tickers_status,
                "association_mode": "explicit_cik" if explicit_cik else "ticker_mapping",
                "cik": resolved_cik,
                "company_name": sec_name,
                "exchange": sec_exchange,
            },
            "company_disclosures": {
                "provider": "SEC EDGAR",
                "source_tier": "regulator",
                "locator": submissions_final_url,
                "http_status": submissions_status,
                "filings": filings,
            },
        },
        "cross_checks": cross_checks,
        "identity_errors": list(dict.fromkeys(identity_errors)),
        "data_errors": list(dict.fromkeys(data_errors)),
        "evidence_errors": list(dict.fromkeys(evidence_errors)),
        "errors": errors,
        "scope": (
            "US exchange-listed domestic operating-company stocks; ETFs, funds, ADRs, "
            "foreign issuers, CN and HK require market-specific official sources"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a live US quote, exchange identity, SEC identity, and recent company disclosures."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", default="US", choices=["US"])
    parser.add_argument("--asset-type", default="stock", choices=["stock"])
    parser.add_argument("--sec-user-agent", default=os.environ.get("PIA_SEC_USER_AGENT"))
    parser.add_argument("--cik", help="Optional explicit SEC CIK with 1 to 10 digits.")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    if not args.sec_user_agent:
        result = _empty_probe_result(
            symbol=str(args.symbol).strip().upper() or None,
            retrieved_at=datetime.now(timezone.utc),
            status="configuration_error",
            errors=["--sec-user-agent or PIA_SEC_USER_AGENT is required"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    try:
        result = probe_us_stock(
            args.symbol,
            args.sec_user_agent,
            timeout=args.timeout,
            cik=args.cik,
        )
    except (LiveProbeError, requests.RequestException) as exc:
        result = _empty_probe_result(
            symbol=str(args.symbol).strip().upper() or None,
            retrieved_at=datetime.now(timezone.utc),
            status="data_error",
            errors=[str(exc)],
        )
        result["identity_errors"] = []
        result["data_errors"] = [str(exc)]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["formal_use_allowed"] else 1


if __name__ == "__main__":
    sys.exit(main())
