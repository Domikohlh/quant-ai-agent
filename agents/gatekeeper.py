# agents/gatekeeper.py
from core.state import AgentState
from tools.portfolio import get_current_portfolio

# ==========================================
# 1. CONFIGURATION
# ==========================================
STOP_LOSS_PCT = 0.08
TAKE_PROFIT_PCT = 0.20
MIN_CASH_BUFFER = 1000.0

def gatekeeper_node(state: AgentState):
    """
    The Gatekeeper.
    1. Checks HOLDINGS for Hard Stop Losses / Take Profits.
    2. Checks CASH limits (Emergency Liquidation).
    3. Outputs signals (SELL or HOLD).
    """
    
    # --- 1. SETUP DATA ---
    market_data = state.get("market_data") or {}
    stocks = market_data.get("stocks", {})
    
    portfolio_obj = get_current_portfolio()
    holdings = portfolio_obj.get('holdings', [])
    cash = float(portfolio_obj.get('cash', 0.0))
    
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
        
        if not curr or entry == 0: continue
        
        pct_change = (curr - entry) / entry
        
        # A. HARD STOP LOSS
        if pct_change < -STOP_LOSS_PCT:
            signals.append({
                "symbol": sym, "action": "SELL", "confidence": 1.0, "qty": qty, "current_price": curr,
                "reasoning": f"Hard Stop Loss triggered (Down {pct_change*100:.1f}%).",
                "risk_analysis": "Capital Preservation Rule", "expected_return": "N/A", "stop_loss": "Triggered"
            })
            print(f"   🚨 STOP LOSS: {sym}")
        
        # B. TAKE PROFIT
        elif pct_change > TAKE_PROFIT_PCT:
            signals.append({
                "symbol": sym, "action": "SELL", "confidence": 1.0, "qty": qty, "current_price": curr,
                "reasoning": f"Take Profit triggered (Up {pct_change*100:.1f}%).",
                "risk_analysis": "Locking Gains", "expected_return": "Realized", "stop_loss": "N/A"
            })
            print(f"   💰 TAKE PROFIT: {sym}")
            
        # C. HOLD (Passive)
        else:
            signals.append({
                "symbol": sym, "action": "HOLD", "confidence": 1.0, "qty": 0, "current_price": curr,
                "reasoning": f"Position stable. PnL: {pct_change*100:.2f}%",
                "risk_analysis": "Stable", "expected_return": "Hold", "stop_loss": f"{entry*(1-STOP_LOSS_PCT):.2f}"
            })

    # --- 3. EMERGENCY CASH CHECK ---
    if cash < MIN_CASH_BUFFER:
        print(f"   ⚠️ LOW CASH (${cash:.2f}). Looking for liquidity...")
        sell_list = [s['symbol'] for s in signals if s['action'] == "SELL"]
        candidates = [h for h in holdings if h['Symbol'] not in sell_list]
        
        if candidates:
            candidates.sort(key=lambda x: (current_prices.get(x['Symbol'], 0) - float(x.get('Entry Price', 1))) / float(x.get('Entry Price', 1)))
            victim = candidates[0]
            
            # Update existing HOLD signal to SELL
            for s in signals:
                if s['symbol'] == victim['Symbol']:
                    s['action'] = "SELL"
                    s['qty'] = float(victim['Qty'])
                    s['reasoning'] = "Emergency liquidation for Cash."
                    print(f"   📉 LIQUIDATING: {victim['Symbol']}")
                    break

    # --- 4. UPDATE STATE (CRITICAL FIX) ---
    # Only update trade_proposal if we have ACTUAL signals.
    # Do NOT return an empty list if existing state is None,
    # as that would trigger the Supervisor's "Fast Track" retry.
    
    existing_proposals = state.get("trade_proposal")
    
    if signals:
        # If we have signals, merge them safely
        current_list = existing_proposals or []
        return {"trade_proposal": current_list + signals}
    
    # If no signals, return EMPTY DICT to preserve the 'None' state
    return {}
