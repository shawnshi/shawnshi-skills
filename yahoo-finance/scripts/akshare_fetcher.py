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
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
    )
    def _fetch_chip_distribution_ak(self, symbol: str) -> pd.DataFrame:
        import akshare as ak
        self._enforce_rate_limit()
        return ak.stock_cyq_em(symbol=symbol)

    def get_enhanced_metrics(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch enhanced metrics for a given A-share symbol.
        Expects symbol in 6-digit format (e.g. '600519').
        """
        metrics = {
            "volume_ratio": None,
            "turnover_rate": None,
            "profit_ratio": None,
            "avg_cost": None,
            "concentration": None
        }
        
        if not (symbol.isdigit() and len(symbol) == 6):
            return metrics
            
        # 1. Fetch Latest Quote via efinance for Volume Ratio and Turnover Rate
        try:
            df_quote = self._fetch_quote_ef(symbol)
            if not df_quote.empty:
                row = df_quote.iloc[0]
                if '量比' in row:
                    metrics['volume_ratio'] = _safe_float(row['量比'])
                if '换手率' in row:
                    metrics['turnover_rate'] = _safe_float(row['换手率'])
        except Exception as e:
            logger.warning(f"Failed to fetch realtime quote for {symbol}: {e}")

        # 2. Fetch Chip Distribution via akshare for Profit Ratio, Avg Cost, Concentration
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
        except Exception as e:
            logger.warning(f"Failed to fetch chip distribution for {symbol}: {e}")

        return metrics
