# agents/gatekeeper.py
from core.state import AgentState
from tools.portfolio import get_current_portfolio

# ==========================================
# 1. CONFIGURATION (The Rules)
# ==========================================
STOP_LOSS_PCT = 0.08       # Sell if down 8%
TAKE_PROFIT_PCT = 0.20     # Sell if up 20%
MIN_CASH_BUFFER = 1000.0   # Must always have $1k cash

def gatekeeper_node(state: AgentState):
    """
    The Gatekeeper.
    Acts as the 'Bouncer' for the portfolio.
    1. Checks HOLDINGS for Hard Stop Losses / Take Profits.
    2. Checks CASH limits (Emergency Liquidation).
    3. Outputs signals (SELL or HOLD) to the workflow.
    """
    
    # --- 1. SETUP DATA ---
    market_data = state.get("market_data") or {}
    stocks = market_data.get("stocks", {})
    
    # Get full portfolio data (includes Average Entry Price)
    portfolio_obj = get_current_portfolio()
    holdings = portfolio_obj.get('holdings', [])
    cash = float(portfolio_obj.get('cash', 0.0))
    
    # Get current market prices
    current_prices = {}
    for sym, candles in stocks.items():
        if candles: current_prices[sym] = candles[-1]['close']

    print("🛡️ GATEKEEPER: Reviewing Holdings & Cash...")
    
    signals = []
    
    # --- 2. STOP LOSS / TAKE PROFIT CHECKS ---
    for pos in holdings:
        sym = pos['Symbol']
        qty = float(pos['Qty'])
        entry = float(pos.get('Entry Price', 0) or 0)
        curr = current_prices.get(sym)
        
        # Skip if data missing
        if not curr or entry == 0: continue
        
        pct_change = (curr - entry) / entry
        
        # A. HARD STOP LOSS
        if pct_change < -STOP_LOSS_PCT:
            signals.append({
                "symbol": sym,
                "action": "SELL",
                "confidence": 1.0,
                "qty": qty,
                "current_price": curr,
                "reasoning": f"Hard Stop Loss triggered (Down {pct_change*100:.1f}%).",
                "risk_analysis": "Capital Preservation Rule",
                "expected_return": "N/A",
                "stop_loss": "Triggered"
            })
            print(f"   🚨 STOP LOSS: {sym}")
        
        # B. TAKE PROFIT
        elif pct_change > TAKE_PROFIT_PCT:
            signals.append({
                "symbol": sym,
                "action": "SELL",
                "confidence": 1.0,
                "qty": qty,
                "current_price": curr,
                "reasoning": f"Take Profit triggered (Up {pct_change*100:.1f}%).",
                "risk_analysis": "Locking Gains",
                "expected_return": "Realized",
                "stop_loss": "N/A"
            })
            print(f"   💰 TAKE PROFIT: {sym}")
            
        # C. HOLD (Default State)
        else:
            # We log this so the Dashboard shows "HOLD" instead of nothing
            signals.append({
                "symbol": sym,
                "action": "HOLD",
                "confidence": 1.0,
                "qty": 0, # Zero qty for holds
                "current_price": curr,
                "reasoning": f"Position stable. PnL: {pct_change*100:.2f}%",
                "risk_analysis": "Stable",
                "expected_return": "Hold",
                "stop_loss": f"{entry*(1-STOP_LOSS_PCT):.2f}"
            })

    # --- 3. EMERGENCY CASH CHECK ---
    # If we are broke, find the "worst" holding to sell
    if cash < MIN_CASH_BUFFER:
        print(f"   ⚠️ LOW CASH (${cash:.2f}). Looking for liquidity...")
        
        # Filter out stocks already marked for SELL
        sell_list = [s['symbol'] for s in signals if s['action'] == "SELL"]
        candidates = [h for h in holdings if h['Symbol'] not in sell_list]
        
        if candidates:
            # Sort candidates by PnL (Sell the biggest loser first)
            # Logic: Cut losers, let winners run.
            candidates.sort(key=lambda x: (
                current_prices.get(x['Symbol'], 0) - float(x.get('Entry Price', 1))
            ) / float(x.get('Entry Price', 1)))
            
            victim = candidates[0]
            sym = victim['Symbol']
            qty = float(victim['Qty'])
            
            # Find the HOLD signal we created earlier and change it to SELL
            for s in signals:
                if s['symbol'] == sym:
                    s['action'] = "SELL"
                    s['qty'] = qty
                    s['reasoning'] = "Emergency liquidation to restore Cash Buffer."
                    s['risk_analysis'] = "Liquidity Crisis"
                    print(f"   📉 LIQUIDATING: {sym}")
                    break

    # --- 4. UPDATE STATE ---
    # Append these mandatory signals to any existing proposals
    existing_proposals = state.get("trade_proposal") or []
    return {"trade_proposal": existing_proposals + signals}
