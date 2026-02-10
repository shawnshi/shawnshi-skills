# Yahoo Finance Skill

Financial market data access point for Gemini. Provides stock prices, fundamentals, news, and historical trends with natural language support.

## Features

- **Market Data**: Historical price data (Open, High, Low, Close, Volume).
- **Company Info**: Fundamentals, sector, industry, currency, and business summary.
- **News Aggregation**: Latest news extraction for specific tickers.
- **Smart Resolution**: Automatically resolves company names (e.g., "Apple") to tickers ("AAPL").
- **Flexible Output**: Supports human-readable terminal output (via Rich) and machine-parseable JSON.

## Capabilities

- **Natural Language Dates**: Understands "1 week ago", "yesterday", etc.
- **Multi-Symbol Support**: Fetch data for multiple companies in one go.
- **Granular Control**: Fetch only price, only news, or only info to save tokens.

## Installation

This skill requires Python 3.8+ and the following dependencies:

```bash
pip install yfinance rich requests dateparser
```

Or using `uv`:

```bash
uv pip install yfinance rich requests dateparser
```

## Usage

Basic usage via `uv`:

```bash
uv run scripts/yf.py [SYMBOLS...] [OPTIONS]
```

### Examples

**Fetch 1-month history for Apple:**
```bash
uv run scripts/yf.py AAPL
```

**Fetch data for multiple companies with natural language start date:**
```bash
uv run scripts/yf.py "Tesla" "Microsoft" --start "1 month ago"
```

**Get JSON output for analysis (Recommended for Agents):**
```bash
uv run scripts/yf.py NVDA --json --price-only
```

## Options

| Flag | Description |
| :--- | :--- |
| `SYMBOLS` | List of ticker symbols (e.g., AAPL) or company names (e.g., "Tesla"). |
| `--period` | Data period shortcut: `1d`, `5d`, `1mo` (default), `3mo`, `1y`, `ytd`, `max`. |
| `--start` | Start date (YYYY-MM-DD or natural language like "1 week ago"). |
| `--end` | End date (YYYY-MM-DD). |
| `--json` | Output structured JSON data (Recommended for Agents). |
| `--info-only` | Fetch only company fundamentals. |
| `--price-only` | Fetch only historical price data. |
| `--news-only` | Fetch only related news. |
| `--no-news` | Exclude news from the output. |

## Troubleshooting

- **Symbol Not Found**: Try using the full company name if the ticker is unknown.
- **No Data**: Ensure the market was open during the requested period (weekends/holidays).
- **Rate Limiting**: Yahoo Finance API has rate limits; if requests fail, wait a moment and try again.

---
*Powered by [yfinance](https://github.com/ranaroussi/yfinance)*
