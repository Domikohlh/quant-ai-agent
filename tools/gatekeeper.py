# tools/gatekeeper.py
from tools.portfolio import get_current_portfolio

# --- CONFIGURATION ---
STOP_LOSS_PCT = 0.08       # Sell if down 8%
TAKE_PROFIT_PCT = 0.20     # Sell if up 20%
MIN_CASH_BUFFER = 1000.0   # Must always have $1k cash
STALE_THRESHOLD = 0.02     # If stock moves <2% in 30 days (Dead money)

def run_gatekeeper_checks(market_data: dict):
    """
    Deterministic rules to enforce portfolio hygiene.
    Returns a list of 'Forced Sell' proposals.
    """
    print("🛡️ GATEKEEPER: Running strict portfolio checks...")
    
    portfolio = get_current_portfolio()
    holdings = portfolio.get('holdings', [])
    cash = float(portfolio.get('cash', 0.0))
    equity = float(portfolio.get('total_equity', 0.0))
    
    forced_sells = []
    
    # 1. STOP LOSS / TAKE PROFIT CHECK
    # We need current prices from market_data
    current_prices = {}
    if 'stocks' in market_data:
        # Extract last close price from candles
        for sym, candles in market_data['stocks'].items():
            if candles:
                current_prices[sym] = candles[-1]['close']
    
    for position in holdings:
        symbol = position['Symbol']
        qty = float(position['Qty'])
        # Ensure we have entry price (Alpaca provides 'Avg Entry Price')
        avg_cost = float(position.get('Entry Price', 0.0))
        curr_price = current_prices.get(symbol)
        
        if not curr_price or avg_cost == 0:
            continue
            
        # Calculate PnL
        pct_change = (curr_price - avg_cost) / avg_cost
        
        # RULE A: STOP LOSS
        if pct_change < -STOP_LOSS_PCT:
            print(f"   🚨 STOP LOSS TRIGGERED: {symbol} is down {pct_change*100:.1f}%")
            forced_sells.append({
                "symbol": symbol,
                "action": "SELL",
                "qty": qty, # Liquidate full position
                "reasoning": f"GATEKEEPER: Hard Stop Loss triggered (-{STOP_LOSS_PCT*100}% rule).",
                "priority": "HIGH"
            })
            continue

        # RULE B: TAKE PROFIT
        if pct_change > TAKE_PROFIT_PCT:
            print(f"   💰 TAKE PROFIT TRIGGERED: {symbol} is up {pct_change*100:.1f}%")
            forced_sells.append({
                "symbol": symbol,
                "action": "SELL",
                "qty": qty,
                "reasoning": f"GATEKEEPER: Hard Take Profit triggered (+{TAKE_PROFIT_PCT*100}% rule).",
                "priority": "MEDIUM"
            })
            continue

    # 2. EMERGENCY CASH GENERATION
    # If we are broke, we MUST sell the weakest link to fund new trades.
    if cash < MIN_CASH_BUFFER:
        print(f"   ⚠️ LOW CASH ALERT: ${cash:.2f} < ${MIN_CASH_BUFFER}")
        
        # Find the worst performing asset that isn't already marked for sale
        marked_symbols = [x['symbol'] for x in forced_sells]
        candidates = [h for h in holdings if h['Symbol'] not in marked_symbols]
        
        if candidates:
            # Sort by PnL (Sell the biggest loser or the smallest winner?)
            # Usually, you cut losers.
            candidates.sort(key=lambda x: (current_prices.get(x['Symbol'], 0) - float(x.get('Entry Price', 1))) / float(x.get('Entry Price', 1)))
            
            victim = candidates[0]
            symbol = victim['Symbol']
            qty = float(victim['Qty'])
            
            print(f"   📉 LIQUIDATING FOR CASH: {symbol}")
            forced_sells.append({
                "symbol": symbol,
                "action": "SELL",
                "qty": qty,
                "reasoning": "GATEKEEPER: Emergency liquidation to restore Cash Buffer.",
                "priority": "CRITICAL"
            })

    return forced_sells
