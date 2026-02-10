"""
<!-- Input: Ticker symbols or company names (List[str]), Options (period, start, end, format) -->
<!-- Output: Financial Data (JSON or Table String) -->
<!-- Pos: scripts/yf.py. Core financial data retrieval engine using yfinance. -->

!!! Maintenance Protocol: If API schema or dependency (yfinance) changes, 
!!! update this header AND SKILL.md usage examples.
"""

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
from datetime import datetime
from typing import List, Optional, Dict, Any

import dateparser
import requests
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

def search_symbol(query: str) -> Optional[str]:
    """Search for a stock symbol using Yahoo Finance API."""
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": query, "quotesCount": 1, "newsCount": 0}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "quotes" in data and len(data["quotes"]) > 0:
            return data["quotes"][0]["symbol"]
    except Exception as e:
        # Only print error if not in JSON mode, handled by caller
        pass
    return None

def get_stock_data(symbol: str, period: str = "1mo", start: str = None, end: str = None, 
                   fetch_price=True, fetch_info=True, fetch_news=True):
    """Fetch stock data with granular control."""
    ticker = yf.Ticker(symbol)
    
    history = None
    info = {}
    news = []

    if fetch_price:
        kwargs = {}
        if start or end:
            if start:
                parsed_start = dateparser.parse(start)
                if parsed_start:
                    kwargs['start'] = parsed_start.strftime('%Y-%m-%d')
            if end:
                parsed_end = dateparser.parse(end)
                if parsed_end:
                    kwargs['end'] = parsed_end.strftime('%Y-%m-%d')
        else:
            kwargs['period'] = period
        
        try:
            history = ticker.history(**kwargs)
        except Exception:
            pass

    if fetch_info:
        try:
            info = ticker.info
        except Exception:
            pass

    if fetch_news:
        try:
            news = ticker.news
        except Exception:
            pass

    return history, info, news

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
        "pub_time": pub_time_str
    }

def display_results_rich(query: str, symbol: str, history, info, news):
    """Display results using Rich (Human Readable)."""
    
    # Header
    name = info.get('longName', symbol)
    currency = info.get('currency', 'USD')
    
    current_price = "N/A"
    if history is not None and not history.empty:
        current_price = f"{history['Close'].iloc[-1]:.2f}"
    
    summary = f"[bold cyan]{name} ({symbol})[/bold cyan]\n"
    summary += f"Current/Last Close: [bold green]{current_price} {currency}[/bold green]"
    
    console.print(Panel(summary, title="Stock Info"))

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
             console.print(f"[dim]Showing last 20 of {len(history)} records...[/dim]")
             rows_to_show = history.tail(20)

        for date, row in rows_to_show.iterrows():
            table.add_row(
                date.strftime('%Y-%m-%d'),
                f"{row['Open']:.2f}",
                f"{row['High']:.2f}",
                f"{row['Low']:.2f}",
                f"{row['Close']:.2f}",
                f"{int(row['Volume']):,}"
            )
        console.print(table)
    elif history is not None:
         console.print("[yellow]No price data found for this range.[/yellow]")

    # News Section
    if news:
        console.print("\n[bold underline]Recent News[/bold underline]")
        for item in news[:5]:
            formatted = format_news_item(item)
            
            # Try to format date nicely for display
            display_time = formatted['pub_time']
            try:
                dt = dateparser.parse(formatted['pub_time'])
                if dt:
                    display_time = dt.strftime('%Y-%m-%d %H:%M')
            except:
                pass

            console.print(f"• [bold]{formatted['title']}[/bold] ([dim]{formatted['publisher']} - {display_time}[/dim])")
            console.print(f"  [blue]{formatted['link']}[/blue]")
            console.print("")

def main():
    parser = argparse.ArgumentParser(description="Fetch stock prices and news from Yahoo Finance.")
    parser.add_argument("queries", nargs="+", help="Stock symbols or company names")
    parser.add_argument("--period", default="1mo", help="Data period (1d, 5d, 1mo, 1y, ytd, max)")
    parser.add_argument("--start", help="Start date")
    parser.add_argument("--end", help="End date")
    
    # Granularity flags
    parser.add_argument("--info-only", action="store_true", help="Fetch only company info")
    parser.add_argument("--price-only", action="store_true", help="Fetch only price history")
    parser.add_argument("--news-only", action="store_true", help="Fetch only news")
    parser.add_argument("--no-news", action="store_true", help="Exclude news (legacy flag)")
    
    # Output format
    parser.add_argument("--json", action="store_true", help="Output JSON for machine consumption")
    
    args = parser.parse_args()

    # Determine what to fetch
    fetch_info = True
    fetch_price = True
    fetch_news = True

    if args.info_only or args.price_only or args.news_only:
        fetch_info = args.info_only
        fetch_price = args.price_only
        fetch_news = args.news_only
    
    if args.no_news:
        fetch_news = False

    results = []

    for query in args.queries:
        if not args.json:
            console.rule(f"[bold]Processing: {query}[/bold]")

        # 1. Resolve Symbol
        symbol = search_symbol(query)
        
        if not symbol:
            error_msg = f"Could not find symbol for '{query}'"
            if args.json:
                results.append({"query": query, "error": error_msg})
            else:
                console.print(f"[red]{error_msg}[/red]")
            continue
        
        if not args.json and symbol != query.upper():
            console.print(f"[dim]Resolved '{query}' to '{symbol}'[/dim]")

        # 2. Fetch Data
        history, info, news_raw = get_stock_data(
            symbol, 
            period=args.period, 
            start=args.start, 
            end=args.end,
            fetch_price=fetch_price,
            fetch_info=fetch_info,
            fetch_news=fetch_news
        )

        if args.json:
            result_entry = {
                "query": query,
                "symbol": symbol,
                "info": info if fetch_info else None,
                "news": [format_news_item(n) for n in news_raw] if fetch_news else None,
                "history": []
            }
            if fetch_price and history is not None and not history.empty:
                # Convert history to list of dicts with string dates
                hist_data = history.reset_index()
                hist_data['Date'] = hist_data['Date'].dt.strftime('%Y-%m-%d')
                result_entry["history"] = hist_data.to_dict(orient='records')
            
            results.append(result_entry)
        else:
            display_results_rich(query, symbol, history, info, news_raw)
            console.print("\n")

    if args.json:
        print(json.dumps(results, indent=2, default=str))

if __name__ == "__main__":
    main()
