import json
import yfinance as yf
import os
import argparse
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

def recalculate_all_weights(filepath, write=False):
    if not filepath:
        raise ValueError("filepath is required")
        
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # ==========================================
    # 1. 计算市值与当前权重 (Current Weight MTM)
    # ==========================================
    exchange_rates = data.get('exchange_rates', {})
    symbols = [pos['symbol'] for pos in data['positions'] if pos['market_type'] != 'CASH']
    
    tickers = None
    if symbols:
        tickers = yf.Tickers(' '.join(symbols))

    total_mtm_value = 0.0
    mtm_values = []

    for pos in data['positions']:
        qty = pos.get('quantity', 0)
        currency = pos.get('currency', 'CNY')
        rate = exchange_rates.get(currency, 1.0)
        
        if pos['market_type'] == 'CASH':
            current_price = 1.0
        else:
            symbol = pos['symbol']
            try:
                current_price = tickers.tickers[symbol].history(period="1d")['Close'].iloc[-1]
            except Exception:
                current_price = pos.get('avg_cost', 0.0)
                
        val = float(qty) * float(current_price) * float(rate)
        mtm_values.append(val)
        total_mtm_value += val

    for i, pos in enumerate(data['positions']):
        if total_mtm_value > 0:
            cw = mtm_values[i] / total_mtm_value
        else:
            cw = 0.0
        pos['current_weight'] = round(cw, 4)

    # ==========================================
    # 2. 高级风险平价模型计算目标权重 (Target Weight)
    # ==========================================
    equities = []
    total_cash_target = 0.0

    for pos in data['positions']:
        if pos.get('market_type') == 'CASH':
            tw = round(pos.get('current_weight', 0.0), 2)
            pos['target_weight'] = tw
            pos['max_weight'] = round(tw + 0.05, 2)
            total_cash_target += tw
        else:
            equities.append(pos)

    total_equity_target = 1.0 - total_cash_target

    # 强制隔离: 80% A股 / 20% 美股
    a_share_target = total_equity_target * 0.80
    us_share_target = total_equity_target * 0.20

    a_shares = []
    us_shares = []

    for pos in equities:
        sym = pos['symbol']
        if sym.startswith('513') or sym in ['TQQQ', 'SOXL', 'INTC']:
            us_shares.append(sym)
        else:
            a_shares.append(sym)

    all_tickers = a_shares + us_shares
    
    hist_data = yf.download(all_tickers, period="1y", progress=False)['Close']

    ann_vol = {}
    for t in all_tickers:
        if t in hist_data.columns:
            ts = hist_data[t].dropna()
            if len(ts) > 30:
                rets = ts.pct_change().dropna()
                ann_vol[t] = rets.std() * np.sqrt(252)

    returns = hist_data.pct_change()
    corr_matrix = returns.corr()

    sandbox_targets = {
        'A_Share': {'tickers': a_shares, 'target_sum': a_share_target},
        'US_Share': {'tickers': us_shares, 'target_sum': us_share_target}
    }

    final_weights = {}

    for sandbox_name, config in sandbox_targets.items():
        tickers = [t for t in config['tickers'] if t in ann_vol]
        if not tickers:
            continue
            
        inv_vol = pd.Series({t: 1.0/ann_vol[t] for t in tickers})
        base_weights = inv_vol / inv_vol.sum()
        
        penalty = pd.Series(1.0, index=tickers)
        for t1 in tickers:
            high_corr_count = 0
            for t2 in tickers:
                if t1 != t2 and pd.notna(corr_matrix.loc[t1, t2]) and corr_matrix.loc[t1, t2] > 0.80:
                    high_corr_count += 1
            penalty[t1] = max(0.2, 1.0 - (0.15 * high_corr_count))
            
        adj_weights = base_weights * penalty
        adj_weights = adj_weights / adj_weights.sum() * config['target_sum']
        
        for t in tickers:
            final_weights[t] = adj_weights[t]

    for pos in data['positions']:
        sym = pos['symbol']
        if sym in final_weights:
            tw = round(final_weights[sym], 4)
            mw = round(tw + 0.05, 4)
            pos['target_weight'] = tw
            pos['max_weight'] = mw

    if write:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Recalculated weights saved to {filepath}.")
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))

    return data

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Recalculate portfolio weights")
    parser.add_argument('--filepath', required=True, help="Portfolio JSON file")
    parser.add_argument('--write', action='store_true', help="Overwrite the input file after review")
    args = parser.parse_args()
    recalculate_all_weights(args.filepath, write=args.write)
