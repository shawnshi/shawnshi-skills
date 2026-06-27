# -*- coding: utf-8 -*-
import argparse
import yfinance as yf
import pandas as pd
import numpy as np
from tabulate import tabulate
import json
import time
import random
from tenacity import retry, stop_after_attempt, wait_exponential

def get_financials(ticker_obj, freq="yearly"):
    try:
        inc = ticker_obj.financials
        cf = ticker_obj.cashflow
        bs = ticker_obj.balance_sheet
        if inc.empty or cf.empty or bs.empty:
            return None, None, None
        return inc, cf, bs
    except Exception as e:
        return None, None, None

def safe_get(df, index_name, year_index=0):
    try:
        if index_name in df.index:
            val = df.loc[index_name].iloc[year_index]
            if pd.isna(val):
                return 0
            return float(val)
    except:
        pass
    return 0

def safe_get_series(df, index_names):
    for name in index_names:
        if name in df.index:
            s = df.loc[name]
            s = pd.to_numeric(s, errors='coerce').fillna(0)
            if not s.empty:
                return s
    # Return empty series
    return pd.Series(dtype=float)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_yf_data(ticker_symbol):
    t = yf.Ticker(ticker_symbol)
    inc, cf, bs = get_financials(t)
    if inc is None:
        raise ValueError("Data unavailable")
    return t, inc, cf, bs

def evaluate_a_share_ticker(ticker_symbol):
    import akshare as ak
    code = ticker_symbol.split(".")[0]
    
    try:
        # Fetch fundamental indicators
        df = ak.stock_financial_analysis_indicator(symbol=code)
        if df.empty:
            return {"Company": ticker_symbol, "Status": "❌ Error", "Reason": "A-Share data empty"}
            
        if '日期' in df.columns:
            df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
            df = df.sort_values('日期', ascending=False)
            
        def get_col(candidates):
            for c in candidates:
                if c in df.columns:
                    return df[c]
            return pd.Series(dtype=float)
            
        roe_series = get_col(['净资产收益率(%)', '加权净资产收益率(%)'])
        gm_series = get_col(['销售毛利率(%)', '毛利率(%)'])
        nm_series = get_col(['销售净利率(%)', '净利率(%)'])
        
        roe_avg = (roe_series.head(5).mean() / 100.0) if not roe_series.empty else 0
        gm_avg = (gm_series.head(5).mean() / 100.0) if not gm_series.empty else 0
        nm_avg = (nm_series.head(5).mean() / 100.0) if not nm_series.empty else 0
        
        ocf_ps = get_col(['每股经营性现金流(元)', '每股经营现金流(元)'])
        fcf_sum = ocf_ps.head(5).sum() if not ocf_ps.empty else 1
        
        int_cov = 999 
        ocf_ni_avg = 1.0 
        dilution = 0
        
        shares = get_col(['总股本(万股)', '总股本(股)'])
        if not shares.empty and len(shares) > 1:
            newest = shares.iloc[0]
            oldest = shares.iloc[-1]
            if oldest > 0:
                dilution = (newest - oldest) / oldest

        pass_1 = roe_avg >= 0.08
        pass_2 = fcf_sum > 0
        pass_3 = True
        pass_4 = gm_avg >= 0.15
        pass_5 = True
        pass_6 = nm_avg >= 0.05
        pass_7 = dilution <= 0.20
        
        all_pass = pass_1 and pass_2 and pass_3 and pass_4 and pass_5 and pass_6 and pass_7
        status = "✅ Pass" if all_pass else "❌ Fail"
        
        failed_metrics = []
        if not pass_1: failed_metrics.append("ROE < 8%")
        if not pass_2: failed_metrics.append("FCF < 0")
        if not pass_4: failed_metrics.append("GM < 15%")
        if not pass_6: failed_metrics.append("NM < 5%")
        if not pass_7: failed_metrics.append("Dilution > 20%")
        
        return {
            "Company": ticker_symbol,
            "1.ROE": f"{roe_avg:.1%}",
            "2.FCF": "Pos" if fcf_sum > 0 else "Neg",
            "3.IntCov": "N/A(A)",
            "4.GM": f"{gm_avg:.1%}",
            "5.OCF/NI": "N/A(A)",
            "6.NM": f"{nm_avg:.1%}",
            "7.Dilution": f"{dilution:.1%}",
            "Status": status,
            "Reason": ", ".join(failed_metrics) if failed_metrics else ""
        }

    except Exception as e:
        return {"Company": ticker_symbol, "Status": "❌ Error", "Reason": f"Akshare fetch failed: {e}"}

def evaluate_ticker(ticker_symbol):
    if ticker_symbol.endswith(".SS") or ticker_symbol.endswith(".SZ"):
        print(f"Fetching A-Share data for {ticker_symbol} via akshare...")
        return evaluate_a_share_ticker(ticker_symbol)

    print(f"Fetching data for {ticker_symbol} via yfinance...")
    try:
        t, inc, cf, bs = fetch_yf_data(ticker_symbol)
    except Exception as e:
        return {"Company": ticker_symbol, "Status": "❌ Error", "Reason": "Data unavailable or rate limited"}
        
    info = t.info
    industry = info.get("industry", "")
    
    # Try to extract required series
    net_income = safe_get_series(inc, ["Net Income", "Net Income Common Stockholders"])
    equity = safe_get_series(bs, ["Stockholders Equity", "Total Stockholder Equity"])
    ocf = safe_get_series(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
    fcf = safe_get_series(cf, ["Free Cash Flow"])
    if fcf.empty and not ocf.empty:
        capex = safe_get_series(cf, ["Capital Expenditure"])
        if not capex.empty:
            fcf = ocf + capex # capex is usually negative in yfinance
        
    ebit = safe_get_series(inc, ["EBIT", "Operating Income"])
    interest = safe_get_series(inc, ["Interest Expense", "Interest Expense Non Operating"])
    revenue = safe_get_series(inc, ["Total Revenue", "Operating Revenue"])
    gross_profit = safe_get_series(inc, ["Gross Profit"])
    shares = safe_get_series(inc, ["Basic Average Shares", "Diluted Average Shares"])
    
    # 1. ROE (10y avg ideally, yf gives ~4 years usually, we use what we have)
    roe_avg = 0
    if not net_income.empty and not equity.empty:
        common_cols = net_income.index.intersection(equity.index)
        if len(common_cols) > 0:
            roes = (net_income[common_cols] / equity[common_cols].replace(0, np.nan)).dropna()
            roe_avg = roes.mean() if len(roes) > 0 else 0
            
    # 2. Cumulative FCF (5y)
    fcf_sum = fcf.sum() if not fcf.empty else 0
    
    # 3. Interest Coverage
    int_cov = 999
    if not ebit.empty and not interest.empty and interest.iloc[0] != 0:
        # interest is often negative in yfinance, use abs
        val = ebit.iloc[0] / abs(interest.iloc[0])
        int_cov = val if pd.notna(val) else 999
        
    # 4. Gross Margin
    gm_avg = 0
    if not gross_profit.empty and not revenue.empty:
        common_cols = gross_profit.index.intersection(revenue.index)
        if len(common_cols) > 0:
            gms = (gross_profit[common_cols] / revenue[common_cols].replace(0, np.nan)).dropna()
            gm_avg = gms.mean() if len(gms) > 0 else 0
            
    # 5. OCF/NI
    ocf_ni_avg = 0
    if not ocf.empty and not net_income.empty:
        common_cols = ocf.index.intersection(net_income.index)
        if len(common_cols) > 0:
            ocf_nis = (ocf[common_cols] / net_income[common_cols].replace(0, np.nan)).dropna()
            # remove extreme outliers
            ocf_nis = ocf_nis[(ocf_nis > -10) & (ocf_nis < 10)]
            ocf_ni_avg = ocf_nis.mean() if len(ocf_nis) > 0 else 0
            
    # 6. Net Margin
    nm_avg = 0
    if not net_income.empty and not revenue.empty:
        common_cols = net_income.index.intersection(revenue.index)
        if len(common_cols) > 0:
            nms = (net_income[common_cols] / revenue[common_cols].replace(0, np.nan)).dropna()
            nm_avg = nms.mean() if len(nms) > 0 else 0
            
    # 7. Dilution
    dilution = 0
    if not shares.empty and len(shares) > 1:
        # yf orders from newest to oldest
        newest = shares.iloc[0]
        oldest = shares.iloc[-1]
        if oldest > 0:
            dilution = (newest - oldest) / oldest
            
    # Evaluations
    metrics = {
        "1.ROE": roe_avg,
        "2.FCF_Sum": fcf_sum,
        "3.Int_Cov": int_cov,
        "4.Gross_Margin": gm_avg,
        "5.OCF/NI": ocf_ni_avg,
        "6.Net_Margin": nm_avg,
        "7.Dilution": dilution
    }
    
    pass_1 = roe_avg >= 0.08
    pass_2 = fcf_sum > 0
    pass_3 = (int_cov >= 2) or ("Bank" in industry or "Insurance" in industry)
    pass_4 = gm_avg >= 0.15
    pass_5 = ocf_ni_avg >= 0.7
    pass_6 = nm_avg >= 0.05
    pass_7 = dilution <= 0.20
    
    # Exemptions
    exemption_reason = ""
    # A. 战略投入期 (Growth phase)
    recent_ocf_sum = ocf.iloc[:2].sum() if len(ocf) >= 2 else ocf.sum() if not ocf.empty else 0
    if not pass_1 and gm_avg > 0.30 and recent_ocf_sum > 0:
        pass_1 = True
        exemption_reason += "[Exemption A: Growth Phase] "
        
    # B. 主动低利润率 (Strategic low margin)
    recent_nm = 0
    if not net_income.empty and not revenue.empty and len(net_income) >= 2:
        recent_nm = net_income.iloc[:2].sum() / revenue.iloc[:2].sum() if revenue.iloc[:2].sum() != 0 else 0
        
    if not pass_6 and gm_avg > 0.30 and recent_nm >= 0.05:
        pass_6 = True
        exemption_reason += "[Exemption B: Low Margin] "
        
    # C. 高周转薄利 (High turnover)
    if (not pass_4 or not pass_6) and roe_avg > 0.20 and ocf_ni_avg > 1.0:
        pass_4 = True
        pass_6 = True
        exemption_reason += "[Exemption C: High Turnover] "
        
    all_pass = pass_1 and pass_2 and pass_3 and pass_4 and pass_5 and pass_6 and pass_7
    
    status = "✅ Pass" if all_pass else "❌ Fail"
    if all_pass and exemption_reason:
        status = "⚠️ Pass (Exempt)"
        
    failed_metrics = []
    if not pass_1: failed_metrics.append("ROE < 8%")
    if not pass_2: failed_metrics.append("FCF < 0")
    if not pass_3: failed_metrics.append("IntCov < 2")
    if not pass_4: failed_metrics.append("GM < 15%")
    if not pass_5: failed_metrics.append("OCF/NI < 0.7")
    if not pass_6: failed_metrics.append("NM < 5%")
    if not pass_7: failed_metrics.append("Dilution > 20%")
    
    return {
        "Company": ticker_symbol,
        "1.ROE": f"{roe_avg:.1%}",
        "2.FCF": "Pos" if fcf_sum > 0 else "Neg",
        "3.IntCov": f"{int_cov:.1f}" if int_cov != 999 else "N/A",
        "4.GM": f"{gm_avg:.1%}",
        "5.OCF/NI": f"{ocf_ni_avg:.2f}",
        "6.NM": f"{nm_avg:.1%}",
        "7.Dilution": f"{dilution:.1%}",
        "Status": status,
        "Reason": ", ".join(failed_metrics) if failed_metrics else exemption_reason.strip()
    }

def main():
    parser = argparse.ArgumentParser(description="AI-Berkshire Quality Screener")
    parser.add_argument("--tickers", nargs="+", required=True, help="List of tickers to screen")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()
    
    results = []
    for ticker in args.tickers:
        res = evaluate_ticker(ticker)
        results.append(res)
        time.sleep(random.uniform(0.5, 2.0))  # Rate limiting jitter
        
    if args.format == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        df = pd.DataFrame(results)
        print("## AI-Berkshire 去劣漏斗筛选结果\n")
        print(tabulate(df, headers="keys", tablefmt="pipe", showindex=False))

if __name__ == "__main__":
    main()
