# tools/portfolio.py
import os
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import OrderSide, QueryOrderStatus

# Initialize Client
trading_client = TradingClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY"),
    paper=True
)

def get_current_portfolio():
    """Fetches live account balance and positions."""
    try:
        # 1. Get Account Info (Cash, Equity)
        account = trading_client.get_account()
        
        # 2. Get Open Positions
        positions = trading_client.get_all_positions()
        
        # 3. Format Holdings
        holdings = []
        for p in positions:
            holdings.append({
                "Symbol": p.symbol,
                "Qty": float(p.qty),
                "Price": float(p.current_price),
                "Value": float(p.market_value),
                "P/L ($)": float(p.unrealized_pl),
                "P/L (%)": float(p.unrealized_plpc) * 100
            })
            
        return {
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "total_equity": float(account.equity),
            "holdings": holdings
        }
    except Exception as e:
        print(f"❌ PORTFOLIO ERROR: {e}")
        return {"cash": 0, "buying_power": 0, "total_equity": 0, "holdings": []}

def print_portfolio_dashboard():
    """Visualizes the portfolio for the Human-in-the-Loop."""
    data = get_current_portfolio()
    
    print("\n" + "="*50)
    print(f"🏦  LIVE PORTFOLIO DASHBOARD")
    print("="*50)
    
    # 1. Account Summary
    print(f"💵 Cash:          ${data['cash']:,.2f}")
    print(f"🔋 Buying Power:  ${data['buying_power']:,.2f}")
    print(f"💰 Total Equity:  ${data['total_equity']:,.2f}")
    print("-" * 50)
    
    # 2. Holdings Table
    if data['holdings']:
        df = pd.DataFrame(data['holdings'])
        # Reorder columns for readability
        df = df[["Symbol", "Qty", "Price", "Value", "P/L ($)", "P/L (%)"]]
        print("📜 CURRENT HOLDINGS:")
        print(df.to_string(index=False))
    else:
        print("📜 CURRENT HOLDINGS: [Empty]")
    
    print("="*50 + "\n")
