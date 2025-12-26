# tools/portfolio.py
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest

def get_current_portfolio() -> dict:
    """
    Fetches current cash, equity, and open positions.
    """
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    
    if not api_key:
        return {"error": "Alpaca keys missing"}

    trading_client = TradingClient(api_key, secret_key, paper=True)

    try:
        # 1. Get Account Info (Cash, Equity)
        account = trading_client.get_account()
        
        # 2. Get Open Positions
        positions = trading_client.get_all_positions()
        
        # Format for the Agent
        holdings = {}
        for pos in positions:
            holdings[pos.symbol] = {
                "qty": float(pos.qty),
                "market_value": float(pos.market_value),
                "profit_pct": float(pos.unrealized_plpc),
                "current_price": float(pos.current_price)
            }

        return {
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "total_equity": float(account.portfolio_value),
            "holdings": holdings
        }

    except Exception as e:
        print(f"⚠️ PORTFOLIO ERROR: {e}")
        return {"error": str(e)}

# Export
portfolio_tools = [get_current_portfolio]
