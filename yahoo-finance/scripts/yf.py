"""
Yahoo Finance Data Retrieval Engine
====================================
@Input:  Ticker symbols or company names (List[str]), CLI options
@Output: Financial data (JSON to stdout, or Rich table to console)
@Pos:    scripts/yf.py

!!! Maintenance Protocol: If API schema or dependency (yfinance) changes,
!!! update this header AND SKILL.md usage examples.
"""

__version__ = "2.0.0"

# /// script
# dependencies = [
#   "yfinance",
#   "rich",
#   "requests",
#   "dateparser",
# ]
# ///

import argparse
import sys
import json
import re
import time
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import dateparser
import requests
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console(stderr=True)

# --- Constants ---

# Core info fields returned in JSON mode by default.
# Use --full-info to get the complete raw dict from yfinance.
INFO_KEYS_DEFAULT = [
    "longName", "shortName", "symbol", "exchange",
    "currency", "currentPrice", "previousClose",
    "marketCap", "sector", "industry",
    "trailingPE", "forwardPE", "dividendYield",
    "priceToBook", "returnOnEquity", "operatingMargins",
    "debtToEquity", "beta", "enterpriseToEbitda",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "totalRevenue", "revenueGrowth",
    "country", "website",
]

MAX_RETRIES = 2
RETRY_BACKOFF_BASE = 1.5  # seconds
REQUEST_TIMEOUT = 10  # seconds for search API

# Regex: all uppercase letters, digits, dots, dashes (e.g. AAPL, BRK-B, 0700.HK)
TICKER_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9.\-]{0,11}$')


def _is_likely_ticker(query: str) -> bool:
    """Heuristic: check if input looks like a stock ticker symbol."""
    return bool(TICKER_PATTERN.match(query))


def _retry(fn, retries=MAX_RETRIES, label="operation"):
    """Execute fn with exponential backoff retries. Returns result or raises."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                console.print(
                    f"[yellow]⚠ {label} failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Retrying in {wait:.1f}s...[/yellow]"
                )
                time.sleep(wait)
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


def resolve_symbol(query: str) -> Optional[str]:
    """Resolve a query to a ticker symbol.

    If the query looks like a ticker (e.g. AAPL), validate it directly first
    to avoid an unnecessary search API call. Falls back to search API.
    """
    if _is_likely_ticker(query):
        # Fast path: try direct validation
        try:
            ticker = yf.Ticker(query)
            info = ticker.info
            # If we get a valid longName or shortName, it's a real ticker
            if info and (info.get("longName") or info.get("shortName")):
                return query
        except Exception:
            pass  # Fall through to search

    # Slow path: use search API
    return search_symbol(query)


def get_stock_data(
    symbol: str,
    period: str = "1mo",
    interval: str = None,
    start: str = None,
    end: str = None,
    fetch_price: bool = True,
    fetch_info: bool = True,
    fetch_news: bool = True,
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
                return ticker.history(**kwargs)
            history = _retry(_fetch_hist, label=f"price history for {symbol}")
        except Exception as e:
            errors.append(f"Price history fetch failed: {e}")
            console.print(f"[red]✗ Price history for {symbol}: {e}[/red]")

    if fetch_info:
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


def filter_info(info: Dict[str, Any], full: bool = False) -> Dict[str, Any]:
    """Return curated info dict. If full=True, return raw dict."""
    if full or not info:
        return info
    return {k: info[k] for k in INFO_KEYS_DEFAULT if k in info}


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

        for date, row in rows_to_show.iterrows():
            table.add_row(
                date.strftime('%Y-%m-%d'),
                f"{row['Open']:.2f}",
                f"{row['High']:.2f}",
                f"{row['Low']:.2f}",
                f"{row['Close']:.2f}",
                f"{int(row['Volume']):,}",
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
    parser.add_argument("--price-only", action="store_true", help="Fetch only price history")
    parser.add_argument("--news-only", action="store_true", help="Fetch only news")

    # Output format
    parser.add_argument("--json", action="store_true", help="Output structured JSON to stdout (recommended for agents)")
    parser.add_argument("--lean", action="store_true", help="Agent mode: truncate long price history to save tokens while keeping full summary (Recommended)")
    parser.add_argument("--full-info", action="store_true", help="Include all raw info fields in JSON (default: curated subset)")

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    # Determine what to fetch
    fetch_info = True
    fetch_price = True
    fetch_news = True

    if args.info_only or args.price_only or args.news_only:
        fetch_info = args.info_only
        fetch_price = args.price_only
        fetch_news = args.news_only

    results = []
    has_failure = False
    all_failed = True

    for query in args.queries:
        if not args.json:
            Console().rule(f"[bold]Processing: {query}[/bold]")

        # 1. Resolve Symbol
        symbol = resolve_symbol(query)

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
        history, info, news_raw, fetch_errors = get_stock_data(
            symbol,
            period=args.period,
            interval=args.interval,
            start=args.start,
            end=args.end,
            fetch_price=fetch_price,
            fetch_info=fetch_info,
            fetch_news=fetch_news,
        )

        if fetch_errors:
            has_failure = True

        # 3. Compute summary stats
        summary = compute_summary(history) if fetch_price else None

        if args.json:
            result_entry = {
                "query": query,
                "symbol": symbol,
            }
            if fetch_info:
                result_entry["info"] = filter_info(info, full=args.full_info)
            if fetch_news:
                result_entry["news"] = [format_news_item(n) for n in (news_raw or [])]
            if fetch_price:
                result_entry["history"] = []
                if history is not None and not history.empty:
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
                        
                result_entry["summary"] = summary
            if fetch_errors:
                result_entry["errors"] = fetch_errors

            results.append(result_entry)
        else:
            display_results_rich(query, symbol, history, info, news_raw, summary)
            Console().print("\n")

    if args.json:
        # Print JSON to stdout (console is stderr, so this is clean)
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
