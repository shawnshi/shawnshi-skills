import json
import yfinance as yf
import os

def recalculate_mtm_weights(filepath=None):
    if not filepath:
        filepath = r"C:\Users\shich\.gemini\MEMORY\raw\stocks\portfolio_positions.json"
        
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    exchange_rates = data.get('exchange_rates', {})

    symbols = [pos['symbol'] for pos in data['positions'] if pos['market_type'] != 'CASH']
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

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print(f"MTM weights recalculated and saved to {filepath}.")

if __name__ == '__main__':
    recalculate_mtm_weights()
