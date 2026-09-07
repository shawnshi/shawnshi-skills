"""
===================================
Standalone Fetcher (Combiner for Yahoo Finance Skill)
===================================

This module provides a standalone fetcher using both Akshare and Efinance 
to retrieve A-share specific metrics that Yahoo Finance lacks:
- volume_ratio (量比)
- turnover_rate (换手率)
- profit_ratio (获利比例)
- avg_cost (平均成本)
- concentration (筹码集中度)

This module has been refactored to remove external dependencies 
and uses resilient endpoints.
"""

import argparse
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from provider_runtime import (
    OPERATION_SECONDS,
    SUPPLEMENT_SECONDS,
    ProviderError,
    error_outcome,
    require_data,
    run_provider,
)

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def _safe_float(val: Any) -> float | None:
    try:
        if pd.isna(val) or val == '' or val is None:
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


REQUIRED_QUOTE_METRICS = ("volume_ratio", "turnover_rate")
REQUIRED_CHIP_METRICS = ("profit_ratio", "avg_cost", "concentration")


def _provider_frame(provider, symbol, **kwargs):
    if provider == "efinance_quote":
        import efinance as ef
        frame = ef.stock.get_latest_quote([symbol])
    elif provider == "akshare_chip_distribution":
        import akshare as ak
        frame = ak.stock_cyq_em(symbol=symbol)
    elif provider == "akshare_history":
        import akshare as ak
        frame = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq", **kwargs)
    else:
        raise ValueError(f"unsupported isolated provider: {provider}")
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("provider returned non-DataFrame")
    return frame


def _run_isolated_provider(provider, symbol, timeout_seconds, **kwargs):
    """Explicit outcome; only a genuine empty DataFrame means no_data."""
    return run_provider(_provider_frame, provider, symbol, timeout_seconds=timeout_seconds, **kwargs)


def _frame_outcome(frame):
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("provider returned non-DataFrame")
    return frame.attrs.get("pia_provider_outcome", {"status": "no_data" if frame.empty else "ok"})


class StandaloneDataFetcher:
    """
    Standalone fetcher combining efinance (latest quote) and akshare (chip distribution).
    """

    def __init__(self, sleep_min: float = 1.0, sleep_max: float = 3.0, *,
                 supplement_seconds: float = SUPPLEMENT_SECONDS,
                 operation_seconds: float = OPERATION_SECONDS):
        if sleep_min < 0 or sleep_max < sleep_min:
            raise ValueError("sleep bounds must satisfy 0 <= sleep_min <= sleep_max")
        self.supplement_seconds = supplement_seconds
        self.operation_seconds = operation_seconds
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._last_request_time: float | None = None

    def _enforce_rate_limit(self, deadline=None) -> None:
        """Wait once for a randomized request-start interval using a monotonic clock."""
        target_interval = random.uniform(self.sleep_min, self.sleep_max)
        now = time.monotonic()
        if self._last_request_time is None:
            self._last_request_time = now
            return
        elapsed = max(0.0, now - self._last_request_time)
        delay = max(0.0, target_interval - elapsed)
        if deadline is not None and delay >= deadline - time.monotonic():
            raise TimeoutError("provider_operation_deadline_during_rate_limit")
        if delay:
            time.sleep(delay)
        self._last_request_time = time.monotonic()

    def _bounded_frame(self, provider, symbol, seconds, **kwargs):
        deadline = time.monotonic() + seconds
        self._enforce_rate_limit(deadline)
        outcome = _run_isolated_provider(provider, symbol, deadline - time.monotonic(), **kwargs)
        frame = require_data(outcome)
        _frame_outcome(frame)
        frame.attrs["pia_provider_outcome"] = {key: value for key, value in outcome.items() if key != "data"}
        return frame

    def _fetch_quote_ef(self, symbol: str) -> pd.DataFrame:
        return self._bounded_frame("efinance_quote", symbol, self.supplement_seconds)

    def _fetch_chip_distribution_ak(self, symbol: str) -> pd.DataFrame:
        return self._bounded_frame("akshare_chip_distribution", symbol, self.supplement_seconds)

    def get_history(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """One isolated history operation, with at most three adapter attempts."""
        start = start_date.replace("-", "") if start_date else "20000101"
        end = end_date.replace("-", "") if end_date else time.strftime("%Y%m%d")
        df = self._bounded_frame(
            "akshare_history", symbol, self.operation_seconds,
            start_date=start, end_date=end,
        )

        if df.empty:
            return df

        # Map akshare columns to yfinance format
        # akshare cols: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        df = df.rename(columns={
            "日期": "Date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume"
        })

        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)

        # Return only the necessary columns
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def get_sector_info(self, symbol: str) -> str | None:
        """Return no value until a source-backed sector adapter is available.

        A natural-language collection instruction is not market evidence and must
        never be stored in a metric field.
        """
        return None

    def get_enhanced_metrics(self, symbol: str, skip_chip_dist: bool = False) -> dict[str, Any]:
        """
        Fetch enhanced metrics for a given A-share symbol.
        Expects symbol in 6-digit format (e.g. '600519').
        """
        metrics = {
            "enhancement_status": "unavailable",
            "provider_outcomes": {},
            "required_metrics": list(REQUIRED_QUOTE_METRICS + (() if skip_chip_dist else REQUIRED_CHIP_METRICS)),
            "volume_ratio": None,
            "turnover_rate": None,
            "profit_ratio": None,
            "avg_cost": None,
            "concentration": None,
            "amplitude": None,
            "chip_90_low": None,
            "chip_90_high": None,
            "chip_70_low": None,
            "chip_70_high": None,
            "belong_boards": None
        }

        if not (symbol.isdigit() and len(symbol) == 6):
            return metrics

        metrics['belong_boards'] = self.get_sector_info(symbol)

        # 1. Fetch Latest Quote via efinance for Volume Ratio, Turnover Rate, Amplitude
        try:
            df_quote = self._fetch_quote_ef(symbol)
            metrics["provider_outcomes"]["quote"] = _frame_outcome(df_quote)
            if not df_quote.empty:
                metrics["enhancement_status"] = "partial"
                row = df_quote.iloc[0]
                if '量比' in row:
                    metrics['volume_ratio'] = _safe_float(row['量比'])
                if '换手率' in row:
                    metrics['turnover_rate'] = _safe_float(row['换手率'])
                # efinance get_latest_quote 不直接返回"振幅"列，需手动计算
                high = _safe_float(row.get('最高'))
                low = _safe_float(row.get('最低'))
                prev_close = _safe_float(row.get('昨日收盘'))
                if high is not None and low is not None and prev_close and prev_close > 0:
                    metrics['amplitude'] = round((high - low) / prev_close * 100, 2)
                # A股修正市值（yfinance经常因汇率/股本计算出错）
                if '总市值' in row:
                    metrics['total_mv_cny'] = _safe_float(row['总市值'])
                if '流通市值' in row:
                    metrics['circ_mv_cny'] = _safe_float(row['流通市值'])
        except Exception as e:
            metrics["provider_outcomes"]["quote"] = e.outcome if isinstance(e, ProviderError) else error_outcome(e)

        # 2. Fetch Chip Distribution via akshare (if not skipped)
        if not skip_chip_dist:
            try:
                df_chips = self._fetch_chip_distribution_ak(symbol=symbol)
                metrics["provider_outcomes"]["chips"] = _frame_outcome(df_chips)
                if not df_chips.empty:
                    latest = df_chips.iloc[-1]
                    if '获利比例' in latest:
                        metrics['profit_ratio'] = _safe_float(latest['获利比例'])
                    if '平均成本' in latest:
                        metrics['avg_cost'] = _safe_float(latest['平均成本'])
                    if '90%筹码集中度' in latest:
                        metrics['concentration'] = _safe_float(latest['90%筹码集中度'])
                    if '90%成本区间下限' in latest:
                        metrics['chip_90_low'] = _safe_float(latest['90%成本区间下限'])
                    if '90%成本区间上限' in latest:
                        metrics['chip_90_high'] = _safe_float(latest['90%成本区间上限'])
                    if '70%成本区间下限' in latest:
                        metrics['chip_70_low'] = _safe_float(latest['70%成本区间下限'])
                    if '70%成本区间上限' in latest:
                        metrics['chip_70_high'] = _safe_float(latest['70%成本区间上限'])
            except Exception as e:
                metrics["provider_outcomes"]["chips"] = e.outcome if isinstance(e, ProviderError) else error_outcome(e)
        required = metrics["required_metrics"]
        metrics["evidence_status"] = (
            "complete" if all(metrics.get(key) is not None for key in required)
            else "partial" if any(metrics.get(key) is not None for key in required)
            else "unavailable"
        )
        hard_failure = any(item["status"] in {"error", "timeout"} for item in metrics["provider_outcomes"].values())
        metrics["enhancement_status"] = (
            "error" if hard_failure else "ok" if metrics["evidence_status"] == "complete"
            else metrics["evidence_status"]
        )

        return metrics


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enhanced_payload(symbol: str, metrics: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    gaps = []
    if metrics.get("belong_boards") is None:
        gaps.append("sector_info_unavailable")
    for field in (
        "volume_ratio",
        "turnover_rate",
        "profit_ratio",
        "avg_cost",
        "concentration",
    ):
        if metrics.get(field) is None:
            gaps.append(f"{field}_unavailable")
    outcomes = metrics.get("provider_outcomes", {})
    hard_failure = metrics.get("enhancement_status") == "error" or any(
        item.get("status") in {"error", "timeout"} for item in outcomes.values()
    )
    required = metrics.get("required_metrics", REQUIRED_QUOTE_METRICS + REQUIRED_CHIP_METRICS)
    status = "data_error" if hard_failure else (
        "complete" if all(metrics.get(field) is not None for field in required) else "insufficient_data"
    )
    return {
        "status": status,
        "symbol": symbol,
        "market": "CN",
        "asset_type_scope": "A-share stock only",
        "mode": "enhanced",
        "source": "Akshare/Efinance",
        "source_locator": "efinance:get_latest_quote; akshare:stock_cyq_em",
        "published_at": None,
        "retrieved_at": retrieved_at.isoformat(),
        "as_of_date": retrieved_at.date().isoformat(),
        "metrics": metrics,
        "data_gaps": gaps,
    }


def _history_payload(
    symbol: str,
    history: pd.DataFrame,
    retrieved_at: datetime,
    *,
    limit: int,
) -> dict[str, Any]:
    if history is None or history.empty:
        return {
            "status": "insufficient_data",
            "symbol": symbol,
            "market": "CN",
            "mode": "history",
            "source": "Akshare",
            "source_locator": "akshare:stock_zh_a_hist",
            "published_at": None,
            "retrieved_at": retrieved_at.isoformat(),
            "as_of_date": retrieved_at.date().isoformat(),
            "adjustment": "qfq",
            "history": [],
            "data_gaps": ["history_unavailable"],
        }
    frame = history.tail(limit).reset_index()
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    records = frame.to_dict(orient="records")
    last_date = records[-1].get("Date") if records else None
    return {
        "status": "complete",
        "symbol": symbol,
        "market": "CN",
        "mode": "history",
        "source": "Akshare",
        "source_locator": "akshare:stock_zh_a_hist",
        "published_at": last_date,
        "retrieved_at": retrieved_at.isoformat(),
        "as_of_date": retrieved_at.date().isoformat(),
        "adjustment": "qfq",
        "history": records,
        "data_gaps": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch source-labelled A-share supplemental evidence."
    )
    parser.add_argument("--symbol", required=True, help="Six-digit A-share code")
    parser.add_argument("--mode", choices=["enhanced", "history"], default="enhanced")
    parser.add_argument("--start", help="History start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="History end date (YYYY-MM-DD)")
    parser.add_argument("--skip-chip", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    symbol = args.symbol.strip()
    retrieved_at = _utc_now()
    if not (symbol.isdigit() and len(symbol) == 6):
        payload = {
            "status": "insufficient_evidence",
            "symbol": symbol,
            "market": "CN",
            "retrieved_at": retrieved_at.isoformat(),
            "as_of_date": retrieved_at.date().isoformat(),
            "data_gaps": ["symbol_must_be_six_digits"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    if args.limit <= 0:
        payload = {
            "status": "insufficient_evidence",
            "symbol": symbol,
            "market": "CN",
            "retrieved_at": retrieved_at.isoformat(),
            "as_of_date": retrieved_at.date().isoformat(),
            "data_gaps": ["limit_must_be_positive"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    fetcher = StandaloneDataFetcher()
    try:
        if args.mode == "enhanced":
            metrics = fetcher.get_enhanced_metrics(symbol, skip_chip_dist=args.skip_chip)
            payload = _enhanced_payload(symbol, metrics, retrieved_at)
        else:
            history = fetcher.get_history(symbol, start_date=args.start, end_date=args.end)
            payload = _history_payload(symbol, history, retrieved_at, limit=args.limit)
    except Exception as exc:
        payload = {
            "status": "data_error",
            "symbol": symbol,
            "market": "CN",
            "mode": args.mode,
            "retrieved_at": retrieved_at.isoformat(),
            "as_of_date": retrieved_at.date().isoformat(),
            "data_gaps": ["provider_operation_failed"],
            "provider_outcome": exc.outcome if isinstance(exc, ProviderError) else error_outcome(exc),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "complete" else 2 if payload["status"] == "data_error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
