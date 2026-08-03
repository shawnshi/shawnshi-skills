# -*- coding: utf-8 -*-
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
import contextlib
import io
import json
import logging
import multiprocessing
import random
import sys
import time
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def _safe_float(val: Any) -> Optional[float]:
    try:
        if pd.isna(val) or val == '' or val is None:
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _provider_process_worker(provider: str, symbol: str, send_connection: Any) -> None:
    """Run one optional provider in a disposable process and return one payload."""
    captured_output = io.StringIO()
    try:
        with (
            contextlib.redirect_stdout(captured_output),
            contextlib.redirect_stderr(captured_output),
        ):
            if provider == "efinance_quote":
                import efinance as ef

                frame = ef.stock.get_latest_quote([symbol])
            elif provider == "akshare_chip_distribution":
                import akshare as ak

                frame = ak.stock_cyq_em(symbol=symbol)
            else:
                raise ValueError(f"unsupported isolated provider: {provider}")
        send_connection.send({"status": "ok", "data": frame})
    except Exception as exc:
        send_connection.send(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    finally:
        send_connection.close()


def _run_isolated_provider(
    provider: str,
    symbol: str,
    timeout_seconds: float,
) -> pd.DataFrame:
    """Return provider data or an empty frame; always reap the child process."""
    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_provider_process_worker,
        args=(provider, symbol, send_connection),
    )
    try:
        process.start()
    except Exception as exc:
        receive_connection.close()
        send_connection.close()
        logger.warning(f"Failed to start isolated {provider} provider: {exc}")
        return pd.DataFrame()
    send_connection.close()

    payload = None
    try:
        if receive_connection.poll(timeout_seconds):
            payload = receive_connection.recv()
        else:
            logger.warning(
                f"Isolated {provider} provider timed out for {symbol} "
                f"after {timeout_seconds:.1f}s"
            )
    except (EOFError, OSError) as exc:
        logger.warning(f"Isolated {provider} provider failed for {symbol}: {exc}")
    finally:
        receive_connection.close()
        alive = process.is_alive()
        if alive:
            process.terminate()
        process.join(timeout=1.0)
        alive = process.is_alive()
        if alive:
            process.kill()
            process.join(timeout=1.0)
            alive = process.is_alive()
        if alive:
            logger.error(
                f"Isolated {provider} provider process could not be reaped for {symbol}"
            )
        else:
            process.close()

    if not isinstance(payload, dict) or payload.get("status") != "ok":
        if isinstance(payload, dict) and payload.get("error"):
            logger.warning(
                f"Isolated {provider} provider error for {symbol}: "
                f"{payload.get('error_type', 'Error')}: {payload['error']}"
            )
        return pd.DataFrame()
    frame = payload.get("data")
    if not isinstance(frame, pd.DataFrame):
        logger.warning(f"Isolated {provider} provider returned non-tabular data")
        return pd.DataFrame()
    return frame


class StandaloneDataFetcher:
    """
    Standalone fetcher combining efinance (latest quote) and akshare (chip distribution).
    """
    
    def __init__(self, sleep_min: float = 1.0, sleep_max: float = 3.0):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._last_request_time: Optional[float] = None
            
    def _enforce_rate_limit(self) -> None:
        """Enforce rate limits with random jitter."""
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.sleep_min:
                time.sleep(self.sleep_min - elapsed)
        
        jitter = random.uniform(self.sleep_min, self.sleep_max)
        time.sleep(jitter)
        self._last_request_time = time.time()

    def _fetch_quote_ef(self, symbol: str) -> pd.DataFrame:
        self._enforce_rate_limit()
        return _run_isolated_provider("efinance_quote", symbol, 8.0)

    def _fetch_chip_distribution_ak(self, symbol: str) -> pd.DataFrame:
        self._enforce_rate_limit()
        return _run_isolated_provider("akshare_chip_distribution", symbol, 8.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
    )
    def get_history(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Fetch historical daily K-lines for A-shares using akshare.
        Returns a DataFrame compatible with yfinance output (Index: Date, Columns: Open, High, Low, Close, Volume).
        """
        import akshare as ak
        self._enforce_rate_limit()
        
        # akshare expects start_date/end_date in YYYYMMDD format
        start = start_date.replace("-", "") if start_date else "20000101"
        end = end_date.replace("-", "") if end_date else time.strftime("%Y%m%d")
        
        # Fail closed through tenacity without mutating process-wide proxy
        # environment variables. Provider routing belongs to the operator.
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )

        if df.empty:
            return pd.DataFrame()
            
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

    def get_sector_info(self, symbol: str) -> Optional[str]:
        """Return no value until a source-backed sector adapter is available.

        A natural-language collection instruction is not market evidence and must
        never be stored in a metric field.
        """
        return None

    def get_enhanced_metrics(self, symbol: str, skip_chip_dist: bool = False) -> Dict[str, Any]:
        """
        Fetch enhanced metrics for a given A-share symbol.
        Expects symbol in 6-digit format (e.g. '600519').
        """
        metrics = {
            "enhancement_status": "unavailable",
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
            logger.warning(f"Failed to fetch realtime quote for {symbol}: {e}")

        # 2. Fetch Chip Distribution via akshare (if not skipped)
        if not skip_chip_dist:
            try:
                df_chips = self._fetch_chip_distribution_ak(symbol=symbol)
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
                logger.warning(f"Failed to fetch chip distribution for {symbol}: {e}")
        if any(metrics.get(key) is not None for key in ["profit_ratio", "avg_cost", "concentration", "chip_90_low", "chip_90_high"]):
            metrics["enhancement_status"] = "ok"
        elif metrics["enhancement_status"] == "partial":
            metrics["enhancement_status"] = "partial"

        return metrics


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enhanced_payload(symbol: str, metrics: Dict[str, Any], retrieved_at: datetime) -> Dict[str, Any]:
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
    status = "complete" if metrics.get("enhancement_status") == "ok" else "insufficient_data"
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
) -> Dict[str, Any]:
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
            "data_gaps": [str(exc)],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
