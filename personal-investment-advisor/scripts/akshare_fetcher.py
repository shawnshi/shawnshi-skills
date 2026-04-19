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

import logging
import random
import time
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
    )
    def _fetch_quote_ef(self, symbol: str) -> pd.DataFrame:
        import efinance as ef
        self._enforce_rate_limit()
        # ef.stock.get_latest_quote works reliably for single quotes
        return ef.stock.get_latest_quote([symbol])

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
    )
    def _fetch_chip_distribution_ak(self, symbol: str) -> pd.DataFrame:
        import akshare as ak
        import threading
        self._enforce_rate_limit()
        
        # Soft timeout for chip distribution since it's heavy and often blocked
        result = []
        err = []
        def worker():
            try:
                result.append(ak.stock_cyq_em(symbol=symbol))
            except Exception as e:
                err.append(e)
                
        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=3.0)  # 3 seconds hard timeout
        
        if t.is_alive():
            logger.warning(f"Chip distribution fetch timed out for {symbol}")
            return pd.DataFrame()
        if err:
            logger.warning(f"Chip distribution fetch error: {err[0]}")
            return pd.DataFrame()
        return result[0] if result else pd.DataFrame()

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
        
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")
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

    def get_sector_info(self, symbol: str) -> str:
        """Fetch basic board/sector info for context."""
        try:
            self._enforce_rate_limit()
            # Note: For strict reliability and avoiding long loops, 
            # we return a placeholder directing the agent to use google_web_search
            # because akshare's 'stock_board_industry_name_em' requires mapping logic that is prone to break.
            return "建议通过 google_web_search 补充最新板块与概念轮动数据"
        except Exception:
            return "Sector Data Unavailable"

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
