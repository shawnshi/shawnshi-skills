import json
import argparse
import yfinance as yf
import pandas as pd
import numpy as np

def run_portfolio_review(filepath: str):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    positions = data.get('positions', [])
    symbols = [p['symbol'] for p in positions if p['market_type'] != 'CASH']
    
    # Fetch 1y data to compute vol and returns
    hist_data = yf.download(symbols, period="1y", progress=False)['Close']
    
    ranking_table = []
    
    for pos in positions:
        sym = pos['symbol']
        weight = pos.get('current_weight', 0.0)
        if weight <= 0 and pos.get('target_weight', 0.0) <= 0:
            continue
            
        if pos['market_type'] == 'CASH':
            ranking_table.append({
                "symbol": sym,
                "name": pos['name'],
                "weight": weight,
                "expected_return": 0.04,  # Cash yield ~4%
                "certainty": 1.0,
                "score": 4.0,
                "action": "Safe Haven"
            })
            continue

        # Expected return estimation (heuristic based on 1y momentum mean-reversion + proxy)
        if sym in hist_data.columns:
            ts = hist_data[sym].dropna()
            if len(ts) > 30:
                y1_return = (ts.iloc[-1] / ts.iloc[0]) - 1
                vol = ts.pct_change().std() * np.sqrt(252)
            else:
                y1_return = 0.05
                vol = 0.2
        else:
            y1_return = 0.05
            vol = 0.2
            
        # Certainty is inversely proportional to volatility
        certainty = 1.0 / (vol * 10) if vol > 0 else 0.5
        certainty = min(max(certainty, 0.1), 0.9)
        
        # Mean reversion expected return: if down a lot, expect bounce; if up a lot, expect moderation
        exp_return = max(0.05, 0.12 - (y1_return * 0.15)) 
        
        # Leveraged ETF adjustment
        if sym in ['TQQQ', 'SOXL']:
            exp_return *= 2.5
            certainty *= 0.4
            
        score = exp_return * certainty * 100 # scale for display
        action = "Review / Maintain"
        if score < 4.0:
            action = "Review / Reduce"
            
        ranking_table.append({
            "symbol": sym,
            "name": pos['name'],
            "weight": weight,
            "expected_return": exp_return,
            "certainty": certainty,
            "score": score,
            "action": action
        })
        
    ranking_table.sort(key=lambda x: x['score'], reverse=True)
    
    # Macro Stress Test
    scenarios = {
        "全球衰退 (Global Recession)": {"US_TECH": -0.35, "US_SEMI": -0.50, "A_SHARE": -0.20, "CASH": 0.0},
        "中美冲突极化 (Geopolitics)": {"US_TECH": -0.10, "US_SEMI": -0.30, "A_SHARE": -0.15, "CASH": 0.0},
        "流动性危机/不降息 (Liquidity Crisis)": {"US_TECH": -0.40, "US_SEMI": -0.40, "A_SHARE": -0.10, "CASH": 0.0}
    }
    
    stress_results = []
    
    for s_name, impacts in scenarios.items():
        total_drawdown = 0.0
        for pos in positions:
            sym = pos['symbol']
            weight = pos.get('current_weight', 0.0)
            if weight <= 0:
                continue
                
            # Map symbol to category
            if pos['market_type'] == 'CASH':
                cat = "CASH"
            elif sym in ['SOXL', 'INTC', '513310.SS']:
                cat = "US_SEMI"
            elif sym in ['TQQQ', '513390.SS', '513500.SS', '159509.SZ', '159501.SZ']:
                cat = "US_TECH"
            else:
                cat = "A_SHARE"
                
            drop = impacts.get(cat, -0.15)
            # Leveraged ETF multiplier
            if sym in ['TQQQ', 'SOXL']:
                drop *= 3.0
                
            total_drawdown += weight * drop
            
        stress_results.append({
            "scenario": s_name,
            "drawdown": total_drawdown
        })
        
    # Output formatting
    report = "# 组合级机会成本与宏观压测审计 (Portfolio Review)\n\n"
    report += "> 以下回报、确定性和压力参数是启发式情景输入，不是收益预测或交易指令。\n\n"
    
    report += "## 1. 机会成本情景排序\n"
    report += "按当前脚本的启发式参数比较资产；低于基准的结果只进入人工复核，不自动产生交易动作。\n\n"
    report += "| 排名 | 标的 | 预期年化回报 | 确定性系数 | 综合得分 | 动作判定 |\n"
    report += "|:---:|:---|:---:|:---:|:---:|:---|\n"
    for idx, item in enumerate(ranking_table, 1):
        action_mark = f"**{item['action']}**" if "Reduce" in item['action'] else item['action']
        report += f"| {idx} | {item['name']} ({item['symbol']}) | {item['expected_return']*100:.1f}% | {item['certainty']:.2f} | **{item['score']:.2f}** | {action_mark} |\n"
        
    report += "\n## 2. 宏观黑天鹅压力测试 (Macro Scenario Stress Test)\n"
    report += "基于各资产的国别与贝塔属性，测算当前实际仓位 (Current Weight) 在极端黑天鹅事件下的综合净值最大回撤预估。\n\n"
    report += "| 宏观情景 | 核心假设 | 组合预期最大回撤 |\n"
    report += "|:---|:---|:---|\n"
    for res in stress_results:
        dd_pct = res['drawdown'] * 100
        alert = "🚨 极度危险 (黑天鹅脆弱)" if dd_pct < -30 else ("⚠️ 需对冲" if dd_pct < -20 else "🟢 韧性良好 (防守充裕)")
        report += f"| **{res['scenario']}** | 根据历史 Beta 与国别敞口推演 | **{dd_pct:.2f}%** ({alert}) |\n"
        
    print(report)
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--filepath', required=True, help='Portfolio JSON file')
    args = parser.parse_args()
    
    run_portfolio_review(args.filepath)
