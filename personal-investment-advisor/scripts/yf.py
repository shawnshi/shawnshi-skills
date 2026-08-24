"""
Yahoo Finance Data Retrieval Engine
====================================
@Input:  Ticker symbols or company names (List[str]), CLI options
@Output: Financial data and optional portfolio batch audit (JSON to stdout, or Rich table to console)
@Pos:    scripts/yf.py

!!! Maintenance Protocol: If API schema or dependency (yfinance) changes,
!!! update this header AND SKILL.md usage examples.
"""

__version__ = "2.2.2"

# /// script
# dependencies = [
#   "yfinance",
#   "pandas",
#   "rich",
#   "requests",
#   "dateparser",
#   "efinance",
#   "akshare",
#   "tenacity",
# ]
# ///

import argparse
import sys
import json
import math
import os
import re
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import dateparser
import requests
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from portfolio_loader import (
    build_portfolio_package,
    is_cash_position,
    load_positions,
    normalize_symbol,
)
from history_integrity_gate import evaluate_history_integrity
from quote_evidence_contract import (
    MAX_QUOTE_AGE_SECONDS,
    MAX_QUOTE_FUTURE_SKEW_SECONDS,
    QUOTE_FRESHNESS_POLICY_VERSION,
    QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE,
    build_portfolio_snapshot_binding,
    quote_freshness_policy,
)

console = Console(stderr=True)

# --- Constants ---

# Core info fields returned in JSON mode by default.
# Use --full-info to get the complete raw dict from yfinance.
INFO_KEYS_DEFAULT = [
    "longName", "shortName", "symbol", "exchange", "exchangeName",
    "currency", "currentPrice", "regularMarketPrice", "previousClose",
    "regularMarketTime", "quoteType", "exchangeTimezoneName",
    "marketState", "tradeable",
    "marketCap", "sector", "industry",
    "trailingPE", "forwardPE", "dividendYield",
    "priceToBook", "returnOnEquity", "operatingMargins",
    "debtToEquity", "beta", "pegRatio", "enterpriseToEbitda",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "totalRevenue", "revenueGrowth",
    "country", "website",
]

MAX_RETRIES = 2
RETRY_BACKOFF_BASE = 1.5  # seconds
REQUEST_TIMEOUT = 10  # seconds for search API
# Regex: all uppercase letters, digits, dots, dashes (e.g. AAPL, BRK-B, 0700.HK)
TICKER_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9.\-]{0,11}$')
PERMANENT_TRANSPORT_ERROR_MARKERS = (
    "invalid library",
    "certificate verify failed",
    "unsupported protocol",
    "invalid url",
    "no host supplied",
    "unable to open database file",
    "permission denied",
    "access is denied",
    "read-only file system",
    "yfinance_cache_unwritable",
)
SYSTEMIC_BATCH_ERROR_MARKERS = (
    "invalid library",
    "openssl_internal:invalid library",
    "curl: (35)",
)


def configure_yfinance_cache(
    cache_dir: Optional[str],
    *,
    task_local_default: bool = False,
) -> Optional[str]:
    """Configure all yfinance SQLite caches before the first ticker request."""
    selected = cache_dir or os.environ.get("PIA_YFINANCE_CACHE_DIR")
    if not selected and task_local_default:
        selected = str(Path.cwd() / "tmp" / "pia-yfinance-cache")
    if not selected:
        return None
    resolved = Path(selected).expanduser().resolve()
    probe_path = resolved / f".pia-cache-write-probe-{os.getpid()}-{time.time_ns()}"
    descriptor = None
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            str(probe_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        os.close(descriptor)
        descriptor = None
        probe_path.unlink()
        yf.set_tz_cache_location(str(resolved))
    except Exception as exc:
        raise RuntimeError(f"yfinance_cache_unwritable: {resolved}: {exc}") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            probe_path.unlink(missing_ok=True)
        except OSError:
            pass
    return str(resolved)


def detect_market_type(symbol: str) -> str:
    if symbol.endswith("=X"):
        return "外汇"
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "A股"
    if symbol.endswith(".HK"):
        return "港股"
    if "-" in symbol or symbol.isupper():
        return "美股"
    return "其他"


def _is_likely_ticker(query: str) -> bool:
    """Heuristic: check if input looks like a stock ticker symbol."""
    return bool(TICKER_PATTERN.match(query))


def _http_status_from_exception(exc: Exception) -> Optional[int]:
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _is_retryable_error(exc: Exception) -> bool:
    """Return False when repeating the same request cannot repair the failure."""
    if isinstance(
        exc,
        (
            PermissionError,
            FileNotFoundError,
            IsADirectoryError,
            NotADirectoryError,
        ),
    ):
        return False
    status = _http_status_from_exception(exc)
    if status is not None:
        return status in {408, 425, 429} or 500 <= status <= 599
    message = str(exc).lower()
    return not any(marker in message for marker in PERMANENT_TRANSPORT_ERROR_MARKERS)


def _systemic_transport_signature(errors: List[str]) -> Optional[str]:
    message = " ".join(str(error) for error in errors).lower()
    for marker in SYSTEMIC_BATCH_ERROR_MARKERS:
        if marker in message:
            return marker
    return None


def _retry(fn, retries=MAX_RETRIES, label="operation"):
    """Execute fn with exponential backoff retries. Returns result or raises."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < retries and _is_retryable_error(e):
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                console.print(
                    f"[yellow]⚠ {label} failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Retrying in {wait:.1f}s...[/yellow]"
                )
                time.sleep(wait)
            else:
                break
    raise last_err


def search_symbol(query: str) -> Optional[str]:
    """Search for a stock symbol using Yahoo Finance search API."""
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": query, "quotesCount": 1, "newsCount": 0}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        def _do_search():
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()

        data = _retry(_do_search, label=f"symbol search for '{query}'")
        if "quotes" in data and len(data["quotes"]) > 0:
            return data["quotes"][0]["symbol"]
    except Exception as e:
        console.print(f"[red]✗ Symbol search failed for '{query}': {e}[/red]")
    return None


def resolve_symbol(
    query: str,
    *,
    return_info: bool = False,
) -> Optional[str] | Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve a query to a ticker symbol.

    If the query looks like a ticker (e.g. AAPL), validate it directly first
    to avoid an unnecessary search API call. Callers may reuse the returned
    metadata so the validation request is not repeated by the data fetch.
    """
    resolved_info: Optional[Dict[str, Any]] = None
    if _is_likely_ticker(query):
        # Fast path: try direct validation
        try:
            ticker = yf.Ticker(query)
            info = ticker.info
            # If we get a valid longName or shortName, it's a real ticker
            if info and (info.get("longName") or info.get("shortName")):
                resolved_info = info
                return (query, resolved_info) if return_info else query
        except Exception:
            pass  # Fall through to search

    # Slow path: use search API
    symbol = search_symbol(query)
    return (symbol, resolved_info) if return_info else symbol


def get_stock_data(
    symbol: str,
    period: str = "1mo",
    interval: str = None,
    start: str = None,
    end: str = None,
    fetch_price: bool = True,
    fetch_info: bool = True,
    fetch_news: bool = True,
    a_share_history_source: str = "yahoo",
    prefetched_info: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Dict, List, List[str]]:
    """Fetch stock data with granular control. Returns (history, info, news, errors)."""
    ticker = yf.Ticker(symbol)
    history = None
    info = {}
    news = []
    errors = []

    if fetch_price:
        kwargs = {}
        if start or end:
            if start:
                parsed_start = dateparser.parse(start)
                if parsed_start:
                    kwargs['start'] = parsed_start.strftime('%Y-%m-%d')
                else:
                    errors.append(f"Could not parse start date: '{start}'")
            if end:
                parsed_end = dateparser.parse(end)
                if parsed_end:
                    kwargs['end'] = parsed_end.strftime('%Y-%m-%d')
                else:
                    errors.append(f"Could not parse end date: '{end}'")
        else:
            kwargs['period'] = period

        if interval:
            kwargs['interval'] = interval

        try:
            def _fetch_hist():
                # A-Share physical decoupling for daily data
                is_a_share = symbol.endswith(".SS") or symbol.endswith(".SZ") or symbol.endswith(".BJ")
                is_daily = not interval or interval in ["1d", "1wk", "1mo"]
                
                if (
                    is_a_share
                    and is_daily
                    and a_share_history_source in {"akshare", "auto"}
                ):
                    try:
                        from akshare_fetcher import StandaloneDataFetcher
                        fetcher = StandaloneDataFetcher()
                        code = symbol.split(".")[0]
                        # Best effort mapping of dates
                        start_date = kwargs.get('start', None)
                        end_date = kwargs.get('end', None)
                        df = fetcher.get_history(code, start_date=start_date, end_date=end_date)
                        if not df.empty:
                            df.attrs["pia_source"] = "Akshare"
                            df.attrs["pia_source_locator"] = "akshare:stock_zh_a_hist"
                            df.attrs["pia_adjustment"] = "qfq"
                            console.print(f"[green]✓ A-share history synchronized for {symbol}[/green]")
                            return df
                        else:
                            if a_share_history_source == "akshare":
                                raise ValueError("Akshare returned empty A-share history")
                            console.print(f"[yellow]⚠ Akshare returned empty history for {symbol}, falling back to Yahoo[/yellow]")
                    except Exception as e:
                        if a_share_history_source == "akshare":
                            raise
                        console.print(f"[yellow]⚠ A-share history fallback failed for {symbol}: {e}. Trying Yahoo Finance...[/yellow]")

                yahoo_history = ticker.history(**kwargs)
                if yahoo_history is not None:
                    yahoo_history.attrs["pia_source"] = "Yahoo Finance"
                    yahoo_history.attrs["pia_source_locator"] = f"yfinance:{symbol}:history"
                    yahoo_history.attrs["pia_adjustment"] = "provider_default"
                return yahoo_history
                
            history = _retry(_fetch_hist, label=f"price history for {symbol}")
        except Exception as e:
            errors.append(f"Price history fetch failed: {e}")
            console.print(f"[red]✗ Price history for {symbol}: {e}[/red]")

    if fetch_info:
        if prefetched_info is not None:
            info = prefetched_info
        else:
            try:
                def _fetch_info():
                    return ticker.info
                info = _retry(_fetch_info, label=f"info for {symbol}")
            except Exception as e:
                errors.append(f"Info fetch failed: {e}")
                console.print(f"[red]✗ Info for {symbol}: {e}[/red]")

    if fetch_news:
        try:
            def _fetch_news():
                return ticker.news
            news = _retry(_fetch_news, label=f"news for {symbol}")
        except Exception as e:
            errors.append(f"News fetch failed: {e}")
            console.print(f"[red]✗ News for {symbol}: {e}[/red]")

    return history, info, news, errors


def fetch_daily_sync_batch(
    symbols: List[str],
    *,
    max_workers: int = 2,
) -> Dict[str, Tuple[Any, Dict, List, List[str]]]:
    """Fetch independent quote-only metadata concurrently, preserving fail-closed results."""
    unique_symbols = list(dict.fromkeys(symbols))
    if not unique_symbols:
        return {}
    workers = max(1, min(int(max_workers), len(unique_symbols), 4))
    results: Dict[str, Tuple[Any, Dict, List, List[str]]] = {}

    def fetch(symbol: str) -> Tuple[Any, Dict, List, List[str]]:
        return get_stock_data(
            symbol,
            fetch_price=False,
            fetch_info=True,
            fetch_news=False,
        )

    queued = deque(unique_symbols)
    systemic_failures: Dict[str, int] = {}
    successful_results = 0
    circuit_breaker: Optional[str] = None
    circuit_threshold = min(2, workers, len(unique_symbols))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight = {}

        def submit_one() -> None:
            if queued:
                symbol = queued.popleft()
                in_flight[executor.submit(fetch, symbol)] = symbol

        for _ in range(workers):
            submit_one()

        while in_flight:
            completed, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            for future in completed:
                symbol = in_flight.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    result = (
                        None,
                        {},
                        [],
                        [f"Daily Sync batch fetch failed: {exc}"],
                    )
                results[symbol] = result
                signature = _systemic_transport_signature(result[3])
                if signature is not None:
                    systemic_failures[signature] = systemic_failures.get(signature, 0) + 1
                elif result[1]:
                    successful_results += 1

            if circuit_breaker is None and successful_results == 0:
                circuit_breaker = next(
                    (
                        signature
                        for signature, count in systemic_failures.items()
                        if count >= circuit_threshold
                    ),
                    None,
                )

            # Hold the queue after the first systemic failure until another
            # in-flight result confirms or disproves a batch-wide outage.
            hold_for_confirmation = (
                bool(systemic_failures)
                and successful_results == 0
                and bool(in_flight)
            )
            if circuit_breaker is None and not hold_for_confirmation:
                while queued and len(in_flight) < workers:
                    submit_one()

    if circuit_breaker is not None:
        while queued:
            symbol = queued.popleft()
            results[symbol] = (
                None,
                {},
                [],
                [
                    "Daily Sync batch circuit breaker opened after repeated "
                    f"systemic transport failure: {circuit_breaker}"
                ],
            )
    return results


def filter_info(info: Dict[str, Any], full: bool = False) -> Dict[str, Any]:
    """Return curated info dict. If full=True, return raw dict."""
    if full or not info:
        return info
    return {k: info[k] for k in INFO_KEYS_DEFAULT if k in info}


def extract_earnings_snapshot(info: Dict[str, Any]) -> Dict[str, Any]:
    if not info:
        return {}

    earnings_date = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
    if isinstance(earnings_date, (int, float)):
        earnings_date = datetime.fromtimestamp(earnings_date).strftime("%Y-%m-%d")

    return {
        "next_earnings_date": earnings_date,
        "revenue_growth": info.get("revenueGrowth"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry")
    }


def extract_catalyst_map(news_items: List[Dict[str, Any]], earnings_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    upcoming = []
    active = []
    broken = []
    data_gaps = []

    if earnings_snapshot.get("next_earnings_date"):
        upcoming.append(f"财报窗口: {earnings_snapshot['next_earnings_date']}")

    for item in news_items[:3]:
        title = item.get("title", "")
        if title:
            active.append(title)

    if not active:
        data_gaps.append("当前数据源未返回近期催化线索；这不是 thesis 破坏证据")

    return {
        "upcoming": upcoming,
        "active": active,
        "broken": broken,
        "data_gaps": data_gaps,
    }


def _has_quote_result(result: Dict[str, Any]) -> bool:
    candidates = [
        (result.get("summary") or {}).get("last_close"),
        (result.get("info") or {}).get("currentPrice"),
        (result.get("info") or {}).get("regularMarketPrice"),
        (result.get("portfolio_context") or {}).get("current_price"),
    ]
    for value in candidates:
        if isinstance(value, bool):
            continue
        try:
            if (
                value is not None
                and math.isfinite(float(value))
                and float(value) > 0
            ):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _positive_finite_number(value: Any) -> Optional[float]:
    """Return a positive finite float without changing its market precision."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def select_portfolio_current_price(history: Any, info: Dict[str, Any]) -> Optional[float]:
    """Select an unrounded market price for portfolio valuation.

    Summary values are intentionally presentation-oriented and rounded. They must
    never flow back into position market value or unrealized P/L calculations.
    """
    for key in ("regularMarketPrice", "currentPrice"):
        price = _positive_finite_number((info or {}).get(key))
        if price is not None:
            return price

    if history is not None and not getattr(history, "empty", True):
        try:
            price = _positive_finite_number(history["Close"].iloc[-1])
        except (KeyError, IndexError, TypeError, AttributeError):
            price = None
        if price is not None:
            return price
    return None


def _expected_position_metadata(
    portfolio_payload: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Build the active, non-cash identity contract used by a strict batch audit."""
    if not portfolio_payload or portfolio_payload.get("_status") != "ok":
        return {}
    return {
        normalize_symbol(position.get("symbol") or ""): {
            "symbol": normalize_symbol(position.get("symbol") or ""),
            "name": position.get("name"),
            "currency": str(position.get("currency") or "").strip().upper(),
            "market": position.get("market"),
            "asset_type": position.get("asset_type"),
        }
        for position in portfolio_payload.get("positions", [])
        if not is_cash_position(position)
        and normalize_symbol(position.get("symbol") or "")
    }


def _expected_market(symbol: str, position: Optional[Dict[str, Any]]) -> Optional[str]:
    market = str((position or {}).get("market") or "").strip().upper()
    if market not in {"CN", "HK", "US", "CASH"}:
        return None

    normalized_symbol = normalize_symbol(symbol)
    if market == "CN" and normalized_symbol.endswith(".SS"):
        return "CN_SH"
    if market == "CN" and normalized_symbol.endswith(".SZ"):
        return "CN_SZ"
    if market == "CN" and normalized_symbol.endswith(".BJ"):
        return "CN_BJ"
    return market


def _provider_market(exchange: Any) -> Optional[str]:
    value = re.sub(r"[^A-Z0-9]+", "", str(exchange or "").upper())
    if not value:
        return None
    if value in {"SHH", "SSE", "XSHG"} or "SHANGHAI" in value:
        return "CN_SH"
    if value in {"SHZ", "SZSE", "XSHE"} or "SHENZHEN" in value:
        return "CN_SZ"
    if value in {"BJE", "BJI", "BJSE"} or "BEIJING" in value:
        return "CN_BJ"
    if value in {"HKG", "HKSE", "XHKG"} or "HONGKONG" in value:
        return "HK"
    if (
        value in {
            "NMS", "NAS", "NGM", "NCM", "NYQ", "NYSE", "ASE", "AMEX",
            "PCX", "ARCA", "BTS", "BATS", "IEX", "PNK", "OTC",
        }
        or "NASDAQ" in value
        or value.startswith("NYSE")
    ):
        return "US"
    return None


def _markets_compatible(expected: Optional[str], actual: Optional[str]) -> bool:
    if expected is None or actual is None:
        return False
    if expected == "CN":
        return actual.startswith("CN_")
    return expected == actual


def _expected_asset_kind(position: Optional[Dict[str, Any]]) -> Optional[str]:
    if not position:
        return None
    asset_type = str(position.get("asset_type") or "").strip().lower()
    return {
        "stock": "EQUITY",
        "etf": "ETF",
        "fund": "FUND",
        "index": "INDEX",
        "cash": "CASH",
        "other": "OTHER",
    }.get(asset_type)


def load_history_integrity_packets(path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """Load source-backed ETF history-integrity packets keyed by normalized symbol.

    A file may contain either one packet or ``{"symbols": {symbol: packet}}``.
    Invalid containers fail closed instead of silently behaving like an empty file.
    """
    if not path:
        return {}
    from pathlib import Path

    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("history integrity file must contain a JSON object")
    if "symbols" in payload:
        packets = payload.get("symbols")
        if not isinstance(packets, dict):
            raise ValueError("history integrity file symbols must be an object")
    elif payload.get("symbol"):
        packets = {payload.get("symbol"): payload}
    else:
        raise ValueError(
            "history integrity file must contain one packet or a symbols object"
        )

    normalized: Dict[str, Dict[str, Any]] = {}
    for symbol, packet in packets.items():
        normalized_symbol = normalize_symbol(symbol or "")
        if not normalized_symbol or not isinstance(packet, dict):
            raise ValueError("every history integrity packet must have a symbol and object value")
        normalized[normalized_symbol] = packet
    return normalized


def history_integrity_decision(
    symbol: str,
    info: Optional[Dict[str, Any]],
    expected_position: Optional[Dict[str, Any]],
    packets: Optional[Dict[str, Dict[str, Any]]],
    history: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Decide whether derived technical metrics may be emitted for one symbol."""
    normalized_symbol = normalize_symbol(symbol or "")
    expected_kind = _expected_asset_kind(expected_position)
    provider_kind = _provider_asset_kind((info or {}).get("quoteType"))
    provider_identity = " ".join(
        str((info or {}).get(field) or "")
        for field in ("longName", "shortName", "category", "fundFamily")
    ).upper()
    provider_name_identifies_etf = (
        "ETF" in provider_identity or "交易型开放式" in provider_identity
    )
    provider_identifies_etf = provider_kind == "ETF" or provider_name_identifies_etf
    if (
        expected_kind is None
        and normalized_symbol.endswith("=X")
        and provider_kind in {None, "CURRENCY"}
    ):
        return {
            "status": "not_applicable",
            "detail_status": "verified_non_etf_provider_identity",
            "technical_metrics_allowed": True,
            "symbol": normalized_symbol or None,
            "errors": [],
            "event_mismatches": {},
        }
    if expected_kind is None and not provider_identifies_etf:
        return {
            "status": "insufficient_evidence",
            "detail_status": "asset_identity_unknown",
            "technical_metrics_allowed": False,
            "symbol": normalized_symbol or None,
            "errors": ["history_integrity_asset_identity_unknown"],
            "event_mismatches": {},
        }
    if expected_kind != "ETF" and expected_kind is not None:
        if provider_identifies_etf:
            return {
                "status": "invalid",
                "detail_status": "asset_identity_conflict",
                "technical_metrics_allowed": False,
                "symbol": normalized_symbol or None,
                "errors": ["history_integrity_asset_identity_conflict"],
                "event_mismatches": {},
            }
        if provider_kind is None:
            return {
                "status": "insufficient_evidence",
                "detail_status": "provider_asset_identity_unknown",
                "technical_metrics_allowed": False,
                "symbol": normalized_symbol or None,
                "errors": ["history_integrity_provider_asset_identity_unknown"],
                "event_mismatches": {},
            }
        return {
            "status": "not_applicable",
            "detail_status": "verified_non_etf_identity",
            "technical_metrics_allowed": True,
            "symbol": normalized_symbol or None,
            "errors": [],
            "event_mismatches": {},
        }

    packet = (packets or {}).get(normalized_symbol)
    if packet is None:
        return {
            "status": "insufficient_data",
            "detail_status": "history_integrity_packet_missing",
            "technical_metrics_allowed": False,
            "symbol": normalized_symbol or None,
            "errors": ["history_integrity_packet_missing"],
            "event_mismatches": {},
        }

    report = evaluate_history_integrity(packet)
    if normalize_symbol(report.get("symbol") or "") != normalized_symbol:
        errors = list(report.get("errors") or [])
        errors.append("history_integrity_symbol_mismatch")
        return {
            **report,
            "status": "invalid",
            "detail_status": "history_integrity_symbol_mismatch",
            "technical_metrics_allowed": False,
            "errors": list(dict.fromkeys(errors)),
        }
    if not report.get("packet_verified"):
        return report

    if history is None or history.empty:
        return {
            **report,
            "status": "insufficient_data",
            "detail_status": "history_series_missing",
            "technical_metrics_allowed": False,
            "errors": ["history_series_missing_for_integrity_binding"],
        }
    try:
        history_end = pd.Timestamp(history.index.max()).date()
    except (TypeError, ValueError, AttributeError):
        return {
            **report,
            "status": "insufficient_data",
            "detail_status": "history_series_date_invalid",
            "technical_metrics_allowed": False,
            "errors": ["history_series_end_date_invalid"],
        }
    try:
        packet_as_of = date.fromisoformat(str(packet.get("as_of_date") or "").strip())
    except ValueError:
        packet_as_of = None

    binding_errors = []
    if packet_as_of is None or packet_as_of < history_end:
        binding_errors.append("history_integrity_packet_does_not_cover_series_end")
    history_attrs = history.attrs if isinstance(history.attrs, dict) else {}
    binding_fields = (
        ("provider_source", "pia_source"),
        ("provider_source_locator", "pia_source_locator"),
        ("provider_adjustment", "pia_adjustment"),
    )
    for packet_field, history_field in binding_fields:
        expected = packet.get(packet_field)
        actual = history_attrs.get(history_field)
        if not isinstance(actual, str) or not actual.strip():
            binding_errors.append(f"history_series_missing_{history_field}")
        elif not isinstance(expected, str) or expected.strip().casefold() != actual.strip().casefold():
            binding_errors.append(f"history_integrity_{packet_field}_mismatch")
    if binding_errors:
        return {
            **report,
            "status": "invalid",
            "detail_status": "history_series_binding_mismatch",
            "technical_metrics_allowed": False,
            "errors": binding_errors,
            "history_binding": {
                "history_end_date": history_end.isoformat(),
                "packet_as_of_date": packet.get("as_of_date"),
            },
        }
    return {
        **report,
        "status": "ok",
        "detail_status": "series_bound_verified",
        "technical_metrics_allowed": True,
        "authorization_scope": "packet_and_runtime_series",
        "history_binding": {
            "history_end_date": history_end.isoformat(),
            "packet_as_of_date": packet.get("as_of_date"),
            "provider_source": history_attrs.get("pia_source"),
            "provider_source_locator": history_attrs.get("pia_source_locator"),
            "provider_adjustment": history_attrs.get("pia_adjustment"),
        },
    }


def _provider_asset_kind(quote_type: Any) -> Optional[str]:
    normalized = re.sub(r"[^A-Z]", "", str(quote_type or "").upper())
    return {
        "EQUITY": "EQUITY",
        "ETF": "ETF",
        "MUTUALFUND": "FUND",
        "FUND": "FUND",
        "INDEX": "INDEX",
        "CURRENCY": "CURRENCY",
    }.get(normalized)


def _history_suppression_gap(report: Dict[str, Any]) -> str:
    detail = str(report.get("detail_status") or "")
    if detail in {
        "asset_identity_unknown",
        "provider_asset_identity_unknown",
        "asset_identity_conflict",
    }:
        return "证券资产身份未闭合，已停止输出历史衍生技术指标"
    if detail in {
        "history_integrity_packet_missing",
        "corporate_action_conflict",
        "history_series_missing",
        "history_series_date_invalid",
        "history_series_binding_mismatch",
        "history_integrity_symbol_mismatch",
        "coverage_incomplete",
    }:
        return "ETF复权/公司行动一致性未验证，已停止输出历史衍生技术指标"
    return "历史完整性门未通过，已停止输出历史衍生技术指标"


def _quote_contract_report(
    result: Dict[str, Any],
    expected_position: Optional[Dict[str, Any]],
    *,
    now_epoch: float,
    max_quote_age_seconds: int,
) -> Dict[str, Any]:
    """Validate quote identity and freshness against one portfolio position."""
    errors: List[str] = []
    warnings: List[str] = []
    info = result.get("info") if isinstance(result.get("info"), dict) else {}
    result_symbol = normalize_symbol(result.get("symbol") or "")
    expected_symbol = normalize_symbol(
        (expected_position or {}).get("symbol") or result_symbol
    )

    if result.get("error") or result.get("errors"):
        errors.append("result_errors_present")

    raw_price_fields = ("regularMarketPrice", "currentPrice")
    if not any(
        _positive_finite_number(info.get(field)) is not None
        for field in raw_price_fields
    ):
        if any(field in info for field in raw_price_fields):
            errors.append("invalid_info.current_market_price")
        else:
            errors.append("missing_info.current_market_price")

    provider_symbol = normalize_symbol(info.get("symbol") or "")
    if not provider_symbol:
        errors.append("missing_info.symbol")
    elif provider_symbol != expected_symbol:
        errors.append("identity_mismatch.symbol")

    expected_market = _expected_market(expected_symbol, expected_position)
    if expected_market is None:
        errors.append("missing_position.market")

    exchanges = [
        value
        for value in (info.get("exchange"), info.get("exchangeName"))
        if value not in (None, "")
    ]
    if not exchanges:
        errors.append("missing_info.exchange_or_exchangeName")
    else:
        if expected_market is not None and not any(
            _markets_compatible(expected_market, _provider_market(exchange))
            for exchange in exchanges
        ):
            errors.append("identity_mismatch.exchange")

    currency = str(info.get("currency") or "").strip().upper()
    if not currency:
        errors.append("missing_info.currency")
    else:
        expected_currency = str(
            (expected_position or {}).get("currency") or ""
        ).strip().upper()
        if not expected_currency:
            errors.append("missing_position.currency")
        elif currency != expected_currency:
            errors.append("identity_mismatch.currency")

    quote_type = info.get("quoteType")
    provider_kind = _provider_asset_kind(quote_type)
    expected_kind = _expected_asset_kind(expected_position)
    if expected_kind is None:
        errors.append("missing_position.asset_type")
    if not quote_type:
        errors.append("missing_info.quoteType")
    elif expected_kind == "ETF" and provider_kind == "EQUITY" and (
        _expected_market(expected_symbol, expected_position) or ""
    ).startswith("CN"):
        # Yahoo commonly classifies Shanghai/Shenzhen ETFs as EQUITY. Accept the
        # known provider alias only when the portfolio explicitly identifies a
        # Chinese ETF and the exchange/currency/symbol checks also close.
        warnings.append("provider_quote_type_alias.cn_etf_as_equity")
    elif expected_kind is not None and provider_kind != expected_kind:
        errors.append("identity_mismatch.quoteType")

    market_state = info.get("marketState")
    freshness_policy = quote_freshness_policy(
        market_state,
        upper_bound_cap_seconds=max_quote_age_seconds,
    )
    if freshness_policy["upper_bound_cap_seconds"] is None:
        errors.append("invalid_quote_age_upper_bound_cap")
    if not isinstance(market_state, str) or not market_state.strip():
        errors.append("missing_info.marketState")
    elif market_state.strip().upper() not in {
        "PREPRE", "PRE", "REGULAR", "POST", "POSTPOST", "CLOSED"
    }:
        errors.append("invalid_info.marketState")

    quote_epoch = info.get("regularMarketTime")
    quote_age_seconds = None
    if isinstance(quote_epoch, bool):
        errors.append("invalid_info.regularMarketTime")
    else:
        try:
            quote_epoch_number = float(quote_epoch)
            if not math.isfinite(quote_epoch_number) or quote_epoch_number <= 0:
                raise ValueError
            quote_age_seconds = now_epoch - quote_epoch_number
            if quote_age_seconds < -MAX_QUOTE_FUTURE_SKEW_SECONDS:
                errors.append("future_info.regularMarketTime")
            elif (
                freshness_policy["applied_max_age_seconds"] is not None
                and quote_age_seconds > freshness_policy["applied_max_age_seconds"]
            ):
                errors.append("stale_info.regularMarketTime")
        except (TypeError, ValueError):
            errors.append("invalid_info.regularMarketTime")

    return {
        "status": "matched" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "quote_age_seconds": (
            round(float(quote_age_seconds), 3)
            if quote_age_seconds is not None
            else None
        ),
        "freshness_policy": freshness_policy,
    }


def list_active_non_cash_symbols(portfolio_payload: Dict[str, Any]) -> List[str]:
    """Return the strict quote-coverage universe from a validated loader payload."""
    return [
        normalize_symbol(position.get("symbol") or "")
        for position in portfolio_payload.get("positions", [])
        if not is_cash_position(position)
        and normalize_symbol(position.get("symbol") or "")
    ]


def build_portfolio_batch_audit(
    results: List[Dict[str, Any]],
    requested_count: int,
    expected_symbols: Optional[List[str]] = None,
    portfolio_load_status: Optional[str] = None,
    portfolio_load_error: Optional[str] = None,
    expected_position_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    now_epoch: Optional[float] = None,
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
    portfolio_snapshot_binding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Audit quote coverage and strict identity for one validated portfolio."""
    portfolio_status_counts: Dict[str, int] = {}
    inactive_symbols = set()
    resolved_symbols: List[str] = []
    quote_failed_symbols: List[str] = []
    unmatched_symbols: List[str] = []
    quote_success_count = 0
    portfolio_matched_count = 0
    quote_contract_matched_count = 0
    quote_contract_failures: Dict[str, List[str]] = {}
    quote_contract_warnings: Dict[str, List[str]] = {}
    quote_freshness_contracts: Dict[str, Dict[str, Any]] = {}
    result_error_symbols: List[str] = []
    stale_quote_symbols: List[str] = []
    position_metadata = {
        normalize_symbol(symbol): metadata
        for symbol, metadata in (expected_position_metadata or {}).items()
        if normalize_symbol(symbol)
    }
    audit_epoch = time.time() if now_epoch is None else float(now_epoch)

    for result in results:
        symbol = normalize_symbol(result.get("symbol") or "")
        display_symbol = symbol or str(result.get("query") or "UNKNOWN")
        if symbol:
            resolved_symbols.append(symbol)
        if _has_quote_result(result):
            quote_success_count += 1
        else:
            quote_failed_symbols.append(display_symbol)

        if result.get("error") or result.get("errors"):
            result_error_symbols.append(display_symbol)

        contract = _quote_contract_report(
            result,
            position_metadata.get(symbol),
            now_epoch=audit_epoch,
            max_quote_age_seconds=max_quote_age_seconds,
        )
        quote_freshness_contracts[display_symbol] = {
            **contract["freshness_policy"],
            "quote_age_seconds": contract["quote_age_seconds"],
            "status": contract["status"],
        }
        if contract["status"] == "matched":
            quote_contract_matched_count += 1
        else:
            quote_contract_failures[display_symbol] = contract["errors"]
            if "stale_info.regularMarketTime" in contract["errors"]:
                stale_quote_symbols.append(display_symbol)
        if contract["warnings"]:
            quote_contract_warnings[display_symbol] = contract["warnings"]

        context = result.get("portfolio_context") or {}
        status = context.get("position_status") or "unavailable"
        portfolio_status_counts[status] = portfolio_status_counts.get(status, 0) + 1
        if status == "matched":
            portfolio_matched_count += 1
        else:
            unmatched_symbols.append(display_symbol)

        summary = result.get("portfolio_summary") or {}
        inactive_symbols.update(
            summary.get("inactive_zero_quantity_symbols") or []
        )

    duplicates = sorted(
        {
            symbol
            for symbol in resolved_symbols
            if resolved_symbols.count(symbol) > 1
        }
    )
    unique_resolved = set(resolved_symbols)
    normalized_expected = sorted(
        {
            normalize_symbol(symbol)
            for symbol in (expected_symbols or [])
            if normalize_symbol(symbol)
        }
    )
    expected_set = set(normalized_expected)
    missing_requested = sorted(expected_set - unique_resolved)
    unexpected_requested = sorted(unique_resolved - expected_set) if expected_symbols is not None else []
    coverage_complete = (
        not missing_requested and not unexpected_requested
        if expected_symbols is not None
        else None
    )

    complete = (
        requested_count > 0
        and len(results) == requested_count
        and len(resolved_symbols) == requested_count
        and not duplicates
        and quote_success_count == requested_count
        and portfolio_matched_count == requested_count
        and portfolio_load_error is None
        and portfolio_load_status == "ok"
        and coverage_complete is not False
        and not result_error_symbols
        and quote_contract_matched_count == requested_count
    )
    return {
        "requested_count": requested_count,
        "result_record_count": len(results),
        "resolved_symbol_count": len(resolved_symbols),
        "unique_resolved_symbol_count": len(unique_resolved),
        "quote_success_count": quote_success_count,
        "strict_quote_contract": True,
        "quote_contract_matched_count": quote_contract_matched_count,
        "quote_contract_failures": quote_contract_failures,
        "quote_contract_warnings": quote_contract_warnings,
        "quote_freshness_policy": {
            "version": QUOTE_FRESHNESS_POLICY_VERSION,
            "state_thresholds_seconds": dict(QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE),
            "calendar_aware": False,
            "long_holiday_behavior": "fail_closed_after_state_threshold",
        },
        "quote_freshness_contracts": quote_freshness_contracts,
        "result_error_symbols": sorted(set(result_error_symbols)),
        "stale_quote_symbols": sorted(set(stale_quote_symbols)),
        "max_quote_age_seconds": max_quote_age_seconds,
        "max_quote_age_seconds_role": "upper_bound_cap",
        "portfolio_matched_count": portfolio_matched_count,
        "returned_symbols": resolved_symbols,
        "quote_failed_symbols": quote_failed_symbols,
        "unmatched_symbols": unmatched_symbols,
        "duplicate_requested_symbols": duplicates,
        "expected_active_symbols": normalized_expected,
        "missing_requested_symbols": missing_requested,
        "unexpected_requested_symbols": unexpected_requested,
        "coverage_complete": coverage_complete,
        "portfolio_status_counts": portfolio_status_counts,
        "inactive_zero_quantity_symbols": sorted(inactive_symbols),
        "portfolio_load_status": portfolio_load_status,
        "portfolio_load_error": portfolio_load_error,
        "portfolio_snapshot_binding": portfolio_snapshot_binding,
        "complete": complete,
        "status": "complete" if complete else "incomplete",
    }


def compute_summary(history) -> Optional[Dict[str, Any]]:
    """Compute summary statistics from price history DataFrame."""
    if history is None or history.empty or len(history) < 2:
        return None

    closes = history['Close']
    first_close = closes.iloc[0]
    last_close = closes.iloc[-1]
    
    # Calculate Drawdown metrics
    rolling_max = closes.cummax()
    drawdowns = (closes - rolling_max) / rolling_max
    max_drawdown = drawdowns.min() * 100
    
    current_high = history['High'].max()
    dd_from_high = ((last_close - current_high) / current_high) * 100 if current_high > 0 else 0

    # Calculate MAs and Bias based on the full history before lean truncation
    ma5 = round(float(closes.rolling(window=5, min_periods=1).mean().iloc[-1]), 2)
    ma10 = round(float(closes.rolling(window=10, min_periods=1).mean().iloc[-1]), 2)
    ma20 = round(float(closes.rolling(window=20, min_periods=1).mean().iloc[-1]), 2)
    bias_ma5 = round(float((last_close - ma5) / ma5 * 100), 2) if ma5 > 0 else 0.0

    # MACD (12, 26, 9) — standard institutional parameters
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_dif = ema12 - ema26
    macd_dea = macd_dif.ewm(span=9, adjust=False).mean()
    macd_hist = (macd_dif - macd_dea) * 2  # histogram (bar)

    # RSI-14
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14, min_periods=1).mean()
    avg_loss = loss.rolling(window=14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, float('nan'))
    rsi_14 = 100 - (100 / (1 + rs))

    # ATR-14
    high = history['High']
    low = history['Low']
    prev_close = closes.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_14 = tr.rolling(window=14, min_periods=1).mean()

    return {
        "period_return_pct": round((last_close - first_close) / first_close * 100, 2),
        "max_drawdown_pct": round(float(max_drawdown), 2),
        "dd_from_high_pct": round(float(dd_from_high), 2),
        "first_close": round(float(first_close), 2),
        "last_close": round(float(last_close), 2),
        "avg_close": round(float(closes.mean()), 2),
        "max_high": round(float(current_high), 2),
        "min_low": round(float(history['Low'].min()), 2),
        "avg_volume": int(history['Volume'].mean()),
        "volatility_std": round(float(closes.pct_change().std() * 100), 4),
        "data_points": len(history),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "bias_ma5_pct": bias_ma5,
        "macd_dif": round(float(macd_dif.iloc[-1]), 4),
        "macd_dea": round(float(macd_dea.iloc[-1]), 4),
        "macd_hist": round(float(macd_hist.iloc[-1]), 4),
        "rsi_14": round(float(rsi_14.iloc[-1]), 2) if pd.notna(rsi_14.iloc[-1]) else None,
        "atr_14": round(float(atr_14.iloc[-1]), 4) if pd.notna(atr_14.iloc[-1]) else None,
    }


def format_news_item(item: Dict[str, Any]) -> Dict[str, str]:
    """Normalize news item structure."""
    content = item.get('content', item)
    title = content.get('title', 'No Title')

    link = '#'
    if 'clickThroughUrl' in content and content['clickThroughUrl']:
        link = content['clickThroughUrl'].get('url', '#')
    elif 'canonicalUrl' in content and content['canonicalUrl']:
        link = content['canonicalUrl'].get('url', '#')
    elif 'link' in content:
        link = content['link']

    publisher = 'Unknown'
    if 'provider' in content and content['provider']:
        publisher = content['provider'].get('displayName', 'Unknown')
    elif 'publisher' in content:
        publisher = content['publisher']

    pub_time_str = content.get('pubDate', '')

    return {
        "title": title,
        "link": link,
        "publisher": publisher,
        "pub_time": pub_time_str,
    }


def display_results_rich(query: str, symbol: str, history, info, news, summary):
    """Display results using Rich (Human Readable)."""
    out = Console()  # stdout console for display output

    # Header
    name = info.get('longName', symbol)
    currency = info.get('currency', 'USD')

    current_price = "N/A"
    if history is not None and not history.empty:
        current_price = f"{history['Close'].iloc[-1]:.2f}"

    header = f"[bold cyan]{name} ({symbol})[/bold cyan]\n"
    header += f"Current/Last Close: [bold green]{current_price} {currency}[/bold green]"

    out.print(Panel(header, title="Stock Info"))

    # Summary Statistics
    if summary:
        ret_color = "green" if summary['period_return_pct'] >= 0 else "red"
        dd_color = "red" if summary['max_drawdown_pct'] < -10 else "yellow"
        out.print(Panel(
            f"Return: [{ret_color}]{summary['period_return_pct']:+.2f}%[/{ret_color}]  |  "
            f"Max DD: [{dd_color}]{summary['max_drawdown_pct']:.2f}%[/{dd_color}]  |  "
            f"Dist from High: {summary['dd_from_high_pct']:.2f}%\n"
            f"Avg Close: {summary['avg_close']}  |  "
            f"High: {summary['max_high']}  |  Low: {summary['min_low']}  |  "
            f"Avg Vol: {summary['avg_volume']:,}  |  "
            f"Volatility(σ): {summary['volatility_std']:.4f}%",
            title="Summary Statistics",
        ))

    # History Table
    if history is not None and not history.empty:
        table = Table(title=f"Price History ({len(history)} records)")
        table.add_column("Date", style="cyan")
        table.add_column("Open", style="magenta")
        table.add_column("High", style="green")
        table.add_column("Low", style="red")
        table.add_column("Close", style="yellow")
        table.add_column("Volume", style="blue")

        rows_to_show = history
        if len(history) > 20:
            out.print(f"[dim]Showing last 20 of {len(history)} records...[/dim]")
            rows_to_show = history.tail(20)

        # Performance: Replace iterrows with itertuples for ~6x faster iteration
        for row in rows_to_show.itertuples():
            table.add_row(
                row.Index.strftime('%Y-%m-%d'),
                f"{row.Open:.2f}",
                f"{row.High:.2f}",
                f"{row.Low:.2f}",
                f"{row.Close:.2f}",
                f"{int(row.Volume):,}",
            )
        out.print(table)
    elif history is not None:
        out.print("[yellow]No price data found for this range.[/yellow]")

    # News Section
    if news:
        out.print("\n[bold underline]Recent News[/bold underline]")
        for item in news[:5]:
            formatted = format_news_item(item)

            display_time = formatted['pub_time']
            try:
                dt = dateparser.parse(formatted['pub_time'])
                if dt:
                    display_time = dt.strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

            out.print(
                f"• [bold]{formatted['title']}[/bold] "
                f"([dim]{formatted['publisher']} - {display_time}[/dim])"
            )
            out.print(f"  [blue]{formatted['link']}[/blue]")
            out.print("")


def main():
    parser = argparse.ArgumentParser(
        description="Yahoo Finance Data Engine — fetch stock prices, fundamentals & news.",
        epilog="Examples:\n"
               "  %(prog)s AAPL --json --price-only --period 5d\n"
               "  %(prog)s \"Tesla\" \"Apple\" --json --info-only\n"
               "  %(prog)s MSFT --start \"1 month ago\" --end \"yesterday\" --json\n"
               "  %(prog)s 0700.HK --json --price-only --interval 1h --period 5d\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("queries", nargs="+", help="Stock symbols (AAPL) or company names (\"Tesla\")")
    parser.add_argument("--period", default="1mo", help="Data period: 1d, 5d, 1mo (default), 3mo, 6mo, 1y, 2y, 5y, ytd, max")
    parser.add_argument("--interval", default=None, help="Data interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d (default), 5d, 1wk, 1mo, 3mo")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD or natural language like '1 week ago')")
    parser.add_argument("--end", help="End date (YYYY-MM-DD or natural language)")

    # Granularity flags
    parser.add_argument("--info-only", action="store_true", help="Fetch only company info")
    parser.add_argument(
        "--price-only",
        action="store_true",
        help=(
            "Fetch price history plus the minimum security identity metadata "
            "required by the ETF history-integrity gate"
        ),
    )
    parser.add_argument("--news-only", action="store_true", help="Fetch only news")

    # Output format
    parser.add_argument("--json", action="store_true", help="Output structured JSON to stdout (recommended for agents)")
    parser.add_argument("--lean", action="store_true", help="Agent mode: truncate long price history to save tokens while keeping full summary (Recommended)")
    parser.add_argument("--full-info", action="store_true", help="Include all raw info fields in JSON (default: curated subset)")
    parser.add_argument(
        "--with-portfolio",
        action="store_true",
        help="Attach position context and a strict quote/match batch audit",
    )
    parser.add_argument("--positions-file", help="Override portfolio positions file path")
    parser.add_argument(
        "--cache-dir",
        help=(
            "Writable yfinance cache directory. PIA_YFINANCE_CACHE_DIR is used when "
            "set; otherwise all network modes default to "
            "./tmp/pia-yfinance-cache."
        ),
    )
    parser.add_argument(
        "--market",
        choices=["CN", "HK", "US"],
        help="Explicit instrument identity for history gating; use with --asset-type.",
    )
    parser.add_argument(
        "--asset-type",
        choices=["stock", "etf", "fund", "index", "other"],
        help="Explicit instrument identity for history gating; use with --market.",
    )
    parser.add_argument(
        "--a-share-history-source",
        choices=["yahoo", "akshare", "auto"],
        default="yahoo",
        help=(
            "A-share daily-history provider. 'akshare' fails closed; 'auto' "
            "falls back to Yahoo; default keeps Yahoo for compatibility."
        ),
    )
    parser.add_argument(
        "--a-share-enhanced",
        action="store_true",
        help="Fetch optional A-share quote/chip metrics with source-labelled gaps.",
    )
    parser.add_argument(
        "--history-integrity-file",
        help=(
            "Source-backed ETF corporate-action packet JSON. ETF technical "
            "metrics are suppressed unless the packet is verified."
        ),
    )
    parser.add_argument(
        "--daily-sync",
        action="store_true",
        help=(
            "Emit a lean quote-only portfolio package with one batch audit; "
            "implies --json and --with-portfolio."
        ),
    )
    parser.add_argument(
        "--daily-sync-workers",
        type=int,
        default=2,
        help="Concurrent quote-only workers for Daily Sync (default 2, maximum 4).",
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    if bool(args.market) != bool(args.asset_type):
        parser.error("--market and --asset-type must be supplied together")

    if args.daily_sync:
        args.json = True
        args.with_portfolio = True
        args.lean = True
        if not 1 <= args.daily_sync_workers <= 4:
            parser.error("--daily-sync-workers must be between 1 and 4")

    try:
        configure_yfinance_cache(
            args.cache_dir,
            task_local_default=True,
        )
    except RuntimeError as exc:
        if args.daily_sync:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "records": [],
                        "portfolio_batch_audit": None,
                        "errors": [str(exc)],
                    },
                    indent=2,
                )
            )
            raise SystemExit(2)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "query": query,
                            "status": "failed",
                            "error": str(exc),
                        }
                        for query in args.queries
                    ],
                    indent=2,
                )
            )
            raise SystemExit(2)
        parser.error(str(exc))

    portfolio_payload = None
    portfolio_load_status = None
    portfolio_load_error = None
    expected_portfolio_symbols = None
    expected_position_metadata: Dict[str, Dict[str, Any]] = {}
    if args.with_portfolio:
        try:
            portfolio_payload = load_positions(args.positions_file)
            portfolio_load_status = portfolio_payload.get("_status")
            if portfolio_load_status == "ok":
                expected_portfolio_symbols = list_active_non_cash_symbols(
                    portfolio_payload
                )
                expected_position_metadata = _expected_position_metadata(
                    portfolio_payload
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            portfolio_load_status = "invalid_positions_file"
            portfolio_load_error = str(exc)

    history_integrity_load_error = None
    try:
        history_integrity_packets = load_history_integrity_packets(
            args.history_integrity_file
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        history_integrity_packets = {}
        history_integrity_load_error = str(exc)

    # Determine what to fetch
    fetch_info = True
    fetch_price = True
    fetch_news = True

    if args.daily_sync:
        fetch_info = True
        fetch_price = False
        fetch_news = False
    elif args.info_only or args.price_only or args.news_only:
        # Price history cannot be classified safely without security identity.
        # In particular, an ETF must not bypass the corporate-action gate just
        # because --price-only previously disabled the metadata request.
        fetch_info = args.info_only or args.price_only
        fetch_price = args.price_only
        fetch_news = args.news_only

    results = []
    has_failure = bool(history_integrity_load_error)
    all_failed = True
    daily_sync_prefetch: Dict[str, Tuple[Any, Dict, List, List[str]]] = {}
    if args.daily_sync and expected_position_metadata:
        batch_symbols = [
            normalized
            for query in args.queries
            if (normalized := normalize_symbol(query)) in expected_position_metadata
        ]
        daily_sync_prefetch = fetch_daily_sync_batch(
            batch_symbols,
            max_workers=args.daily_sync_workers,
        )

    for query in args.queries:
        if not args.json:
            Console().rule(f"[bold]Processing: {query}[/bold]")

        # 1. Resolve Symbol. Daily Sync already has a validated portfolio
        # identity contract, so re-querying the search/metadata endpoints would
        # duplicate network calls and could remap a trusted code unexpectedly.
        normalized_query = normalize_symbol(query)
        prefetched_info = None
        if args.daily_sync and normalized_query in expected_position_metadata:
            symbol = normalized_query
        else:
            resolution = resolve_symbol(query, return_info=True)
            if isinstance(resolution, tuple):
                symbol, prefetched_info = resolution
            else:
                # Preserve compatibility with callers and test doubles that
                # implement the legacy string-only resolver contract.
                symbol = resolution

        if not symbol:
            has_failure = True
            error_msg = f"Could not find symbol for '{query}'"
            if args.json:
                results.append({"query": query, "error": error_msg})
            else:
                Console().print(f"[red]✗ {error_msg}[/red]")
            continue

        all_failed = False

        if not args.json and symbol != query.upper():
            Console().print(f"[dim]Resolved '{query}' → '{symbol}'[/dim]")

        # 2. Fetch Data
        if args.daily_sync and symbol in daily_sync_prefetch:
            history, info, news_raw, fetch_errors = daily_sync_prefetch[symbol]
        else:
            history, info, news_raw, fetch_errors = get_stock_data(
                symbol,
                period=args.period,
                interval=args.interval,
                start=args.start,
                end=args.end,
                fetch_price=fetch_price,
                fetch_info=fetch_info,
                fetch_news=fetch_news,
                a_share_history_source=args.a_share_history_source,
                prefetched_info=prefetched_info,
            )

        if fetch_info and not info:
            currency_history_is_usable = bool(
                fetch_price
                and symbol.endswith("=X")
                and history is not None
                and not history.empty
            )
            if not currency_history_is_usable:
                fetch_errors.append(
                    "Info fetch failed: provider returned empty metadata"
                )

        if fetch_errors:
            has_failure = True

        # 3. Gate derived ETF metrics against a source-backed action ledger.
        if fetch_price:
            bound_identity = expected_position_metadata.get(
                normalize_symbol(symbol)
            )
            if bound_identity is None and args.market and args.asset_type:
                bound_identity = {
                    "symbol": normalize_symbol(symbol),
                    "market": args.market,
                    "asset_type": args.asset_type,
                }
            history_integrity = history_integrity_decision(
                symbol,
                info,
                bound_identity,
                history_integrity_packets,
                history,
            )
        else:
            history_integrity = {
                "status": "not_applicable",
                "detail_status": "price_history_not_requested",
                "technical_metrics_allowed": True,
                "symbol": normalize_symbol(symbol) or None,
                "errors": [],
                "event_mismatches": {},
                "reason": "price_history_not_requested",
            }
        summary = (
            compute_summary(history)
            if fetch_price and history_integrity["technical_metrics_allowed"]
            else None
        )
        if fetch_price and not history_integrity["technical_metrics_allowed"]:
            has_failure = True

        if args.json:
            result_entry = {
                "query": query,
                "symbol": symbol,
                "market_type": detect_market_type(symbol),
                "data_sources": {
                    "price": (
                        "Yahoo Finance"
                        if args.daily_sync
                        else (
                            history.attrs.get("pia_source", "Yahoo Finance")
                            if history is not None
                            else None
                        )
                    ),
                    "price_locator": (
                        f"yfinance:{symbol}:quote"
                        if args.daily_sync
                        else (
                            history.attrs.get("pia_source_locator")
                            if history is not None
                            else None
                        )
                    ),
                    "price_adjustment": (
                        history.attrs.get("pia_adjustment")
                        if history is not None
                        else None
                    ),
                    "info": "Yahoo Finance" if info else None,
                    "news": "Yahoo Finance",
                    "enhanced_metrics": None,
                },
                "data_gaps": [],
                "history_integrity": history_integrity,
            }
            if history_integrity_load_error:
                result_entry["history_integrity"]["file_error"] = (
                    history_integrity_load_error
                )
            if fetch_info:
                # Basic info
                curated_info = filter_info(info, full=args.full_info)
                
                # Enhanced A-share info 
                is_a_share_symbol = bool(
                    symbol
                    and (
                        symbol.endswith(".SS")
                        or symbol.endswith(".SZ")
                        or symbol.endswith(".BJ")
                    )
                )
                if is_a_share_symbol and args.a_share_enhanced:
                    # e.g., '600519.SS' -> '600519'
                    a_share_code = symbol.split(".")[0]
                    if a_share_code.isdigit() and len(a_share_code) == 6:
                        try:
                            from akshare_fetcher import StandaloneDataFetcher
                            fetcher = StandaloneDataFetcher()
                            
                            # Context-Aware Downgrading: Skip heavy chip distribution if scanning multiple stocks in lean mode
                            skip_chip = args.lean and len(args.queries) > 2
                            enhanced_metrics = fetcher.get_enhanced_metrics(a_share_code, skip_chip_dist=skip_chip)
                            
                            # Merge into info
                            if curated_info is None:
                                curated_info = {}
                            result_entry["data_sources"]["enhanced_metrics"] = "Akshare/Efinance"
                            curated_info.update({
                                k: v for k, v in enhanced_metrics.items() if v is not None
                            })
                            if enhanced_metrics.get("enhancement_status") != "ok":
                                result_entry["data_gaps"].append(
                                    f"A股增强指标状态={enhanced_metrics.get('enhancement_status', 'unavailable')}"
                                )
                        except Exception as e:
                            # Silently fail or log for agents
                            result_entry["data_gaps"].append(f"A股增强指标获取失败: {e}")
                elif is_a_share_symbol:
                    result_entry["data_gaps"].append("A股增强指标未请求")
                else:
                    result_entry["data_gaps"].append("筹码增强字段不适用(非A股)")
                
                result_entry["info"] = curated_info
                result_entry["earnings_snapshot"] = extract_earnings_snapshot(info)
            if fetch_news:
                result_entry["news"] = [format_news_item(n) for n in (news_raw or [])]
                if not news_raw:
                    result_entry["data_gaps"].append("未获取到相关新闻: 建议使用 google_web_search 补充 '[stock_name] [stock_code] 财报 异动 新闻'")
                result_entry["catalyst_map"] = extract_catalyst_map(result_entry["news"], result_entry.get("earnings_snapshot", {}))
            if fetch_price:
                result_entry["history"] = []
                if (
                    history_integrity["technical_metrics_allowed"]
                    and history is not None
                    and not history.empty
                ):
                    hist_data = history.reset_index()
                    if 'Datetime' in hist_data.columns:
                        hist_data['Date'] = hist_data['Datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
                        hist_data = hist_data.drop(columns=['Datetime'])
                    elif 'Date' in hist_data.columns:
                        hist_data['Date'] = hist_data['Date'].dt.strftime('%Y-%m-%d')
                    
                    if args.lean and len(hist_data) > 6:
                        # Lean mode: truncate long history but keep trend markers
                        is_intraday = args.interval in ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"]
                        
                        if is_intraday and len(hist_data) > 20:
                            # Intraday: keeps first 5, last 10, and resamples middle
                            first_part = hist_data.iloc[:5]
                            last_part = hist_data.iloc[-10:]
                            mid_part = hist_data.iloc[5:-10]
                            if len(mid_part) > 5:
                                step = len(mid_part) // 5
                                mid_part = mid_part.iloc[::step].head(5)
                            lean_history = pd.concat([first_part, mid_part, last_part], ignore_index=True)
                        elif not is_intraday:
                            # Standard interday: keep first day and last 5 days
                            lean_history = pd.concat([hist_data.iloc[[0]], hist_data.iloc[-5:]], ignore_index=True)
                        else:
                            # Fallback for short intraday
                            lean_history = pd.concat([hist_data.iloc[:3], hist_data.iloc[-3:]], ignore_index=True)
                            
                        result_entry["history"] = lean_history.to_dict(orient='records')
                        result_entry["history_truncated"] = True
                    else:
                        result_entry["history"] = hist_data.to_dict(orient='records')
                        result_entry["history_truncated"] = False
                elif not history_integrity["technical_metrics_allowed"]:
                    result_entry["history_suppressed"] = True
                    result_entry["data_gaps"].append(
                        _history_suppression_gap(history_integrity)
                    )
                        
                result_entry["summary"] = summary
                if summary is None and history_integrity["technical_metrics_allowed"]:
                    result_entry["data_gaps"].append("未生成价格摘要统计")
            if args.with_portfolio:
                current_price = select_portfolio_current_price(history, info)
                if portfolio_load_error is None:
                    portfolio_package = build_portfolio_package(
                        symbol,
                        current_price=current_price,
                        positions_file=args.positions_file,
                        payload=portfolio_payload,
                    )
                else:
                    portfolio_package = {
                        "portfolio_context": {
                            "has_position": False,
                            "symbol": symbol,
                            "position_status": portfolio_load_status,
                            "positions_file": args.positions_file,
                            "position_note": portfolio_load_error,
                        },
                        "portfolio_summary": None,
                        "portfolio_risk": None,
                        "portfolio_fit": None,
                    }
                result_entry["portfolio_context"] = portfolio_package.get("portfolio_context")
                result_entry["portfolio_summary"] = portfolio_package.get("portfolio_summary")
                result_entry["portfolio_risk"] = portfolio_package.get("portfolio_risk")
                result_entry["portfolio_fit"] = portfolio_package.get("portfolio_fit")
                result_entry["data_sources"]["portfolio"] = result_entry["portfolio_context"].get("positions_file")
                if result_entry["portfolio_context"].get("position_status") == "file_missing":
                    result_entry["data_gaps"].append("持仓文件不存在，未生成持仓者建议上下文")
                elif result_entry["portfolio_context"].get("position_status") == "not_found":
                    result_entry["data_gaps"].append("持仓文件存在，但未找到该标的持仓记录")
                elif result_entry["portfolio_context"].get("position_status") == "inactive_zero_quantity":
                    result_entry["data_gaps"].append(
                        "标的在持仓文件中数量为零，已从有效持仓和组合计算中排除"
                    )
                elif result_entry["portfolio_context"].get("position_status") == "invalid_positions_file":
                    result_entry["data_gaps"].append(
                        "持仓文件无效，持仓匹配与组合风险无法判断"
                    )
            
            # Load thesis.md for research calls. Daily Sync stays quote-only and
            # leaves Thesis evidence assessment to the dedicated red-team stage.
            try:
                configured_dashboard_dir = os.environ.get("PIA_DASHBOARD_DIR")
                result_entry["thesis_context"] = None
                if configured_dashboard_dir and not args.daily_sync:
                    base_stocks_dir = Path(configured_dashboard_dir).expanduser()
                    safe_sym = symbol.replace(" ", "_").replace("/", "_")
                    thesis_path = base_stocks_dir / safe_sym / f"{safe_sym}_thesis.md"
                    if thesis_path.exists():
                        result_entry["thesis_context"] = thesis_path.read_text(encoding="utf-8")
                        result_entry["data_sources"]["thesis"] = str(thesis_path)
                    else:
                        legacy_path = base_stocks_dir / f"{safe_sym}_thesis.md"
                        if legacy_path.exists():
                            result_entry["thesis_context"] = legacy_path.read_text(encoding="utf-8")
                            result_entry["data_sources"]["thesis"] = str(legacy_path)
            except Exception as e:
                result_entry["thesis_context"] = f"Error loading thesis: {e}"

            if fetch_errors:
                result_entry["errors"] = fetch_errors
                result_entry["data_gaps"].extend(fetch_errors)

            results.append(result_entry)
        else:
            display_results_rich(query, symbol, history, info, news_raw, summary)
            Console().print("\n")

    if args.json:
        if args.with_portfolio:
            batch_audit = build_portfolio_batch_audit(
                results,
                requested_count=len(args.queries),
                expected_symbols=expected_portfolio_symbols,
                portfolio_load_status=portfolio_load_status,
                portfolio_load_error=portfolio_load_error,
                expected_position_metadata=_expected_position_metadata(
                    portfolio_payload
                ),
                portfolio_snapshot_binding=(
                    build_portfolio_snapshot_binding(portfolio_payload)
                    if portfolio_load_status == "ok" and portfolio_payload
                    else None
                ),
            )
            if not batch_audit["complete"]:
                has_failure = True
            if args.daily_sync:
                print(
                    json.dumps(
                        {
                            "status": (
                                "complete" if batch_audit["complete"] else "incomplete"
                            ),
                            "records": results,
                            "portfolio_batch_audit": batch_audit,
                        },
                        indent=2,
                        default=str,
                    )
                )
            else:
                for result_entry in results:
                    result_entry["portfolio_batch_audit"] = batch_audit
                print(json.dumps(results, indent=2, default=str))
        else:
            print(json.dumps(results, indent=2, default=str))

    # Exit codes: 0=all ok, 1=partial failure, 2=all failed
    if all_failed and len(args.queries) > 0:
        sys.exit(2)
    elif has_failure:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
