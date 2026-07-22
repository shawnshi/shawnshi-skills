import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from tabulate import tabulate
from tenacity import retry, stop_after_attempt, wait_exponential


DEFAULT_PROFILES_PATH = Path(__file__).resolve().parent.parent / "references" / "method_profiles.json"


def load_profiles(path: str | None = None) -> dict[str, Any]:
    profile_path = Path(path) if path else DEFAULT_PROFILES_PATH
    return json.loads(profile_path.read_text(encoding="utf-8"))


def _series(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in frame.index:
            values = pd.to_numeric(frame.loc[name], errors="coerce").dropna()
            if not values.empty:
                return values
    return pd.Series(dtype=float)


def _mean_ratio(numerator: pd.Series, denominator: pd.Series) -> float | None:
    common = numerator.index.intersection(denominator.index)
    if common.empty:
        return None
    ratios = (numerator[common] / denominator[common].replace(0, np.nan)).dropna()
    return float(ratios.mean()) if not ratios.empty else None


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def evaluate_metrics(metrics: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    checks = []
    missing = []
    failed = []
    for metric, rule in profile.get("thresholds", {}).items():
        value = _finite(metrics.get(metric))
        if value is None:
            missing.append(metric)
            checks.append({"metric": metric, "status": "missing", "value": None, "rule": rule})
            continue
        passed = True
        if "min" in rule:
            passed = passed and value >= float(rule["min"])
        if "min_exclusive" in rule:
            passed = passed and value > float(rule["min_exclusive"])
        if "max" in rule:
            passed = passed and value <= float(rule["max"])
        if "max_exclusive" in rule:
            passed = passed and value < float(rule["max_exclusive"])
        status = "pass" if passed else "fail"
        checks.append({"metric": metric, "status": status, "value": value, "rule": rule})
        if not passed:
            failed.append(metric)

    if missing:
        status = "insufficient_data"
    elif failed:
        status = "fail"
    else:
        status = "pass"
    return {"status": status, "missing_metrics": missing, "failed_metrics": failed, "checks": checks}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_yf_data(ticker_symbol: str):
    ticker = yf.Ticker(ticker_symbol)
    income = ticker.financials
    cashflow = ticker.cashflow
    balance = ticker.balance_sheet
    if income.empty or cashflow.empty or balance.empty:
        raise ValueError("financial statements unavailable")
    return ticker, income, cashflow, balance


def extract_yf_metrics(income: pd.DataFrame, cashflow: pd.DataFrame, balance: pd.DataFrame) -> dict[str, Any]:
    net_income = _series(income, ["Net Income", "Net Income Common Stockholders"])
    equity = _series(balance, ["Stockholders Equity", "Total Stockholder Equity"])
    operating_cashflow = _series(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
    free_cashflow = _series(cashflow, ["Free Cash Flow"])
    if free_cashflow.empty:
        capex = _series(cashflow, ["Capital Expenditure"])
        common = operating_cashflow.index.intersection(capex.index)
        if not common.empty:
            free_cashflow = operating_cashflow[common] + capex[common]
    ebit = _series(income, ["EBIT", "Operating Income"])
    interest = _series(income, ["Interest Expense", "Interest Expense Non Operating"])
    revenue = _series(income, ["Total Revenue", "Operating Revenue"])
    gross_profit = _series(income, ["Gross Profit"])
    shares = _series(income, ["Basic Average Shares", "Diluted Average Shares"])

    interest_coverage = None
    if not ebit.empty and not interest.empty and interest.iloc[0] != 0:
        interest_coverage = float(ebit.iloc[0] / abs(interest.iloc[0]))
    dilution = None
    if len(shares) > 1 and shares.iloc[-1] > 0:
        dilution = float((shares.iloc[0] - shares.iloc[-1]) / shares.iloc[-1])
    return {
        "roe_avg": _mean_ratio(net_income, equity),
        "fcf_sum": float(free_cashflow.sum()) if not free_cashflow.empty else None,
        "interest_coverage": interest_coverage,
        "gross_margin_avg": _mean_ratio(gross_profit, revenue),
        "ocf_to_net_income_avg": _mean_ratio(operating_cashflow, net_income),
        "net_margin_avg": _mean_ratio(net_income, revenue),
        "dilution": dilution,
    }


def extract_a_share_metrics(ticker_symbol: str) -> dict[str, Any]:
    import akshare as ak

    code = ticker_symbol.split(".")[0]
    frame = ak.stock_financial_analysis_indicator(symbol=code)
    if frame.empty:
        raise ValueError("A-share financial indicators unavailable")
    if "日期" in frame.columns:
        frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
        frame = frame.sort_values("日期", ascending=False)

    def column(names: list[str]) -> pd.Series:
        for name in names:
            if name in frame.columns:
                return pd.to_numeric(frame[name], errors="coerce").dropna()
        return pd.Series(dtype=float)

    roe = column(["净资产收益率(%)", "加权净资产收益率(%)"])
    gross_margin = column(["销售毛利率(%)", "毛利率(%)"])
    net_margin = column(["销售净利率(%)", "净利率(%)"])
    shares = column(["总股本(万股)", "总股本(股)"])
    dilution = None
    if len(shares) > 1 and shares.iloc[-1] > 0:
        dilution = float((shares.iloc[0] - shares.iloc[-1]) / shares.iloc[-1])
    return {
        "roe_avg": float(roe.head(5).mean() / 100) if not roe.empty else None,
        "gross_margin_avg": float(gross_margin.head(5).mean() / 100) if not gross_margin.empty else None,
        "net_margin_avg": float(net_margin.head(5).mean() / 100) if not net_margin.empty else None,
        "dilution": dilution,
    }


def evaluate_ticker(ticker_symbol: str, profile_name: str, profile: dict[str, Any]) -> dict[str, Any]:
    try:
        if ticker_symbol.endswith((".SS", ".SZ", ".BJ")):
            metrics = extract_a_share_metrics(ticker_symbol)
            source = "akshare"
        else:
            _, income, cashflow, balance = fetch_yf_data(ticker_symbol)
            metrics = extract_yf_metrics(income, cashflow, balance)
            source = "yfinance"
    except Exception as exc:
        return {
            "symbol": ticker_symbol,
            "profile": profile_name,
            "status": "data_error",
            "source": None,
            "metrics": {},
            "checks": [],
            "reason": str(exc),
        }
    result = evaluate_metrics(metrics, profile)
    return {
        "symbol": ticker_symbol,
        "profile": profile_name,
        "source": source,
        "metrics": metrics,
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile-driven financial quality pre-screen.")
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--profiles-file")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()
    profiles_payload = load_profiles(args.profiles_file)
    profiles = profiles_payload.get("profiles", {})
    if args.profile not in profiles:
        parser.error(f"unknown profile {args.profile!r}; choose from {sorted(profiles)}")
    results = [evaluate_ticker(ticker, args.profile, profiles[args.profile]) for ticker in args.tickers]
    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        rows = [
            {
                "symbol": item["symbol"],
                "profile": item["profile"],
                "status": item["status"],
                "missing": ", ".join(item.get("missing_metrics", [])),
                "failed": ", ".join(item.get("failed_metrics", [])),
            }
            for item in results
        ]
        print(tabulate(rows, headers="keys", tablefmt="pipe", showindex=False))
    return 1 if any(item["status"] in {"data_error", "insufficient_data"} for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
