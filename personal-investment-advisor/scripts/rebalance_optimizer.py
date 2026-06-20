import json
import os
import argparse
from typing import Dict, Any

def analyze_portfolio_balance(filepath: str) -> Dict[str, Any]:
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 1. Aggregate sectors / markets
    sector_exposure = {}
    violations = []
    
    positions = data.get('positions', [])
    for pos in positions:
        market = pos.get('market_type', '未知')
        weight = pos.get('current_weight', 0.0)
        target = pos.get('target_weight', 0.0)
        max_wt = pos.get('max_weight', 0.0)
        symbol = pos.get('symbol', 'UNKNOWN')
        
        # In a real institutional setup, sector would be fetched from yf.info
        # Here we approximate by market type for simplicity, or we could read from yf cache
        sector_exposure[market] = sector_exposure.get(market, 0.0) + weight
        
        if weight > max_wt:
            violations.append(f"单票超标: {symbol} 权重 {weight*100:.2f}% 超过最大允许 {max_wt*100:.2f}%")
            
    # Risk Profile bounds
    risk_profile = data.get('risk_profile', {})
    max_market = risk_profile.get('max_market_exposure_high', 0.65)
    
    for market, exposure in sector_exposure.items():
        if market != 'CASH' and exposure > max_market:
            violations.append(f"板块超标: {market} 敞口 {exposure*100:.2f}% 超过系统硬边界 {max_market*100:.2f}%")
            
    return {
        "sector_exposure": sector_exposure,
        "violations": violations,
        "action_required": len(violations) > 0
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--filepath', default=r"C:\Users\shich\.gemini\MEMORY\raw\stocks\portfolio_positions.json")
    args = parser.parse_args()
    
    result = analyze_portfolio_balance(args.filepath)
    print(json.dumps(result, indent=2, ensure_ascii=False))
