import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import pandas as pd
import yfinance as yf
from tabulate import tabulate
from tenacity import retry, stop_after_attempt, wait_exponential


DEFAULT_PROFILES_PATH = Path(__file__).resolve().parent.parent / "references" / "method_profiles.json"
VALID_MARKETS = {"CN", "HK", "US"}
VALID_ASSET_TYPES = {"stock", "etf", "fund", "index", "other"}


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


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _retrieval_time(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieved_at clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _base_result(
    ticker_symbol: Any,
    profile_name: Any,
    profile: dict[str, Any],
    *,
    market: Any,
    asset_type: Any,
    industry_type: Any,
    as_of_date: Any,
    retrieved_at: datetime,
    profile_version: str | None = None,
) -> dict[str, Any]:
    return {
        "symbol": ticker_symbol,
        "profile": profile_name,
        "profile_version": profile.get("profile_version") or profile_version or "unversioned",
        "market": market.strip().upper() if isinstance(market, str) else market,
        "asset_type": asset_type.strip().lower() if isinstance(asset_type, str) else asset_type,
        "industry_type": (
            industry_type.strip().lower() if isinstance(industry_type, str) else industry_type
        ),
        "as_of_date": as_of_date,
        "retrieved_at": retrieved_at.isoformat(),
        "data_period": None,
        "source": None,
        "source_locator": None,
        "metrics": {},
        "checks": [],
        "missing_metrics": [],
        "failed_metrics": [],
    }


def _applicability_errors(
    profile: dict[str, Any],
    *,
    market: Any,
    asset_type: Any,
    industry_type: Any,
    as_of_date: Any,
    retrieved_at: datetime,
) -> list[str]:
    strict_profile = any(
        field in profile
        for field in (
            "applicable_markets",
            "applicable_asset_types",
            "applicable_industry_types",
        )
    )
    if not strict_profile:
        return []

    errors: list[str] = []
    normalized_market = market.strip().upper() if isinstance(market, str) else None
    normalized_asset = asset_type.strip().lower() if isinstance(asset_type, str) else None
    normalized_industry = (
        industry_type.strip().lower() if isinstance(industry_type, str) else None
    )
    cutoff = _parse_iso_date(as_of_date)

    if normalized_market not in VALID_MARKETS:
        errors.append("market must be one of CN, HK, or US")
    elif normalized_market not in profile.get("applicable_markets", []):
        errors.append(f"profile does not apply to market {normalized_market}")

    if normalized_asset not in VALID_ASSET_TYPES:
        errors.append("asset_type is missing or invalid")
    elif normalized_asset not in profile.get("applicable_asset_types", []):
        errors.append(f"profile does not apply to asset_type {normalized_asset}")

    applicable_industries = profile.get("applicable_industry_types")
    if applicable_industries is not None and normalized_industry not in applicable_industries:
        errors.append(
            "profile requires industry_type in " + ", ".join(applicable_industries)
        )

    if cutoff is None:
        errors.append("as_of_date must be an ISO date")
    elif cutoff > retrieved_at.date():
        errors.append("as_of_date cannot be after retrieved_at")
    return errors


def _column_date(value: Any) -> date | None:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _filter_statement_as_of(frame: pd.DataFrame, cutoff: date) -> pd.DataFrame:
    dated_columns = [(column, _column_date(column)) for column in frame.columns]
    parseable = [(column, column_date) for column, column_date in dated_columns if column_date]
    if not parseable:
        return frame
    allowed = [column for column, column_date in parseable if column_date <= cutoff]
    return frame.loc[:, allowed]


def _statement_period(*frames: pd.DataFrame) -> dict[str, Any] | None:
    dates = [
        column_date
        for frame in frames
        for column_date in (_column_date(column) for column in frame.columns)
        if column_date is not None
    ]
    if not dates:
        return None
    return {
        "start": min(dates).isoformat(),
        "end": max(dates).isoformat(),
        "basis": "provider_financial_statement_columns",
    }


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


def extract_a_share_metrics(
    ticker_symbol: str,
    as_of_date: str | None = None,
    *,
    include_period: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any] | None]:
    import akshare as ak

    code = ticker_symbol.split(".")[0]
    frame = ak.stock_financial_analysis_indicator(symbol=code)
    if frame.empty:
        raise ValueError("A-share financial indicators unavailable")
    if "日期" in frame.columns:
        frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
        cutoff = _parse_iso_date(as_of_date)
        if cutoff is not None:
            frame = frame[frame["日期"].dt.date <= cutoff]
        frame = frame.sort_values("日期", ascending=False)
    if frame.empty:
        raise ValueError("A-share financial indicators unavailable at or before as_of_date")

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
    metrics = {
        "roe_avg": float(roe.head(5).mean() / 100) if not roe.empty else None,
        "gross_margin_avg": float(gross_margin.head(5).mean() / 100) if not gross_margin.empty else None,
        "net_margin_avg": float(net_margin.head(5).mean() / 100) if not net_margin.empty else None,
        "dilution": dilution,
    }
    data_period = None
    if "日期" in frame.columns:
        dates = frame["日期"].dropna().dt.date
        if not dates.empty:
            data_period = {
                "start": min(dates).isoformat(),
                "end": max(dates).isoformat(),
                "basis": "akshare_financial_indicator_dates",
            }
    return (metrics, data_period) if include_period else metrics


def evaluate_ticker(
    ticker_symbol: str,
    profile_name: str,
    profile: dict[str, Any],
    *,
    market: str | None = None,
    asset_type: str | None = None,
    as_of_date: str | None = None,
    industry_type: str | None = None,
    profile_version: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    retrieved_at = _retrieval_time(now)
    base = _base_result(
        ticker_symbol,
        profile_name,
        profile,
        market=market,
        asset_type=asset_type,
        industry_type=industry_type,
        as_of_date=as_of_date,
        retrieved_at=retrieved_at,
        profile_version=profile_version,
    )
    applicability_errors = _applicability_errors(
        profile,
        market=market,
        asset_type=asset_type,
        industry_type=industry_type,
        as_of_date=as_of_date,
        retrieved_at=retrieved_at,
    )
    if applicability_errors:
        return {
            **base,
            "status": "insufficient_evidence",
            "applicability_errors": applicability_errors,
            "reason": "; ".join(applicability_errors),
        }

    if profile.get("screening_mode") == "evidence_only":
        return {
            **base,
            "status": "not_applicable",
            "reason": (
                "financial quality screening is not applicable; verify ETF identity, "
                "tracking, fees, liquidity, NAV/premium-discount, concentration and adjustments"
            ),
        }
    try:
        normalized_market = market.strip().upper() if isinstance(market, str) else None
        cutoff = _parse_iso_date(as_of_date) or retrieved_at.date()
        if normalized_market == "CN" or ticker_symbol.endswith((".SS", ".SZ", ".BJ")):
            metrics, data_period = extract_a_share_metrics(
                ticker_symbol,
                as_of_date,
                include_period=True,
            )
            source = "akshare"
            source_locator = (
                "akshare:stock_financial_analysis_indicator:"
                f"{ticker_symbol.split('.')[0]}"
            )
        else:
            _, income, cashflow, balance = fetch_yf_data(ticker_symbol)
            income = _filter_statement_as_of(income, cutoff)
            cashflow = _filter_statement_as_of(cashflow, cutoff)
            balance = _filter_statement_as_of(balance, cutoff)
            if income.empty or cashflow.empty or balance.empty:
                return {
                    **base,
                    "status": "insufficient_data",
                    "reason": "financial statements unavailable at or before as_of_date",
                }
            metrics = extract_yf_metrics(income, cashflow, balance)
            data_period = _statement_period(income, cashflow, balance)
            source = "yfinance"
            source_locator = (
                f"https://finance.yahoo.com/quote/{quote(ticker_symbol, safe='')}/financials"
            )
    except Exception as exc:
        return {
            **base,
            "status": "data_error",
            "reason": str(exc),
        }
    result = evaluate_metrics(metrics, profile)
    return {
        **base,
        "source": source,
        "source_locator": source_locator,
        "data_period": data_period,
        "metrics": metrics,
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile-driven financial quality pre-screen.")
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--profile")
    parser.add_argument("--market")
    parser.add_argument("--asset-type")
    parser.add_argument("--as-of-date")
    parser.add_argument("--industry-type")
    parser.add_argument("--profiles-file")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()
    if not args.tickers or not args.profile:
        result = [{
            "symbol": None,
            "profile": args.profile,
            "profile_version": None,
            "status": "insufficient_evidence",
            "reason": "--tickers and --profile are required",
            "market": args.market,
            "asset_type": args.asset_type,
            "industry_type": args.industry_type,
            "as_of_date": args.as_of_date,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "data_period": None,
            "source": None,
            "source_locator": None,
            "metrics": {},
            "checks": [],
            "missing_metrics": [],
            "failed_metrics": [],
        }]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    try:
        profiles_payload = load_profiles(args.profiles_file)
    except (OSError, json.JSONDecodeError) as exc:
        result = [{
            "symbol": ticker,
            "profile": args.profile,
            "profile_version": None,
            "status": "data_error",
            "reason": str(exc),
            "market": args.market,
            "asset_type": args.asset_type,
            "industry_type": args.industry_type,
            "as_of_date": args.as_of_date,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "data_period": None,
            "source": None,
            "source_locator": None,
            "metrics": {},
            "checks": [],
            "missing_metrics": [],
            "failed_metrics": [],
        } for ticker in args.tickers]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    profiles = profiles_payload.get("profiles", {})
    if args.profile not in profiles:
        results = [{
            "symbol": ticker,
            "profile": args.profile,
            "profile_version": profiles_payload.get("version"),
            "status": "insufficient_evidence",
            "reason": f"unknown profile {args.profile!r}; choose from {sorted(profiles)}",
            "market": args.market,
            "asset_type": args.asset_type,
            "industry_type": args.industry_type,
            "as_of_date": args.as_of_date,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "data_period": None,
            "source": None,
            "source_locator": None,
            "metrics": {},
            "checks": [],
            "missing_metrics": [],
            "failed_metrics": [],
        } for ticker in args.tickers]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1
    results = [
        evaluate_ticker(
            ticker,
            args.profile,
            profiles[args.profile],
            market=args.market,
            asset_type=args.asset_type,
            as_of_date=args.as_of_date,
            industry_type=args.industry_type,
            profile_version=profiles_payload.get("version"),
        )
        for ticker in args.tickers
    ]
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
    return 1 if any(
        item["status"] in {"data_error", "insufficient_data", "insufficient_evidence"}
        for item in results
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
