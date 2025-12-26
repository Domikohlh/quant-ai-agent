# tools/execution.py
import os
import time
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

def execute_order(symbol: str, side: str, qty: float, order_type: str = "MARKET", limit_price: float = None) -> dict:
    """
    Submits an order to Alpaca. 
    Supports MARKET and LIMIT orders.
    """
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    
    if not api_key:
        return {"error": "Alpaca keys missing"}

    trading_client = TradingClient(api_key, secret_key, paper=True)

    print(f"🚀 EXECUTING: {side} {qty} {symbol} ({order_type})")

    try:
        # Prepare Order Request
        req = None
        if order_type.upper() == "MARKET":
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
        elif order_type.upper() == "LIMIT" and limit_price:
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price
            )
        else:
            return {"error": "Invalid order type or missing limit price"}

        # Submit
        order = trading_client.submit_order(order_data=req)
        
        return {
            "id": str(order.id),
            "status": "SUBMITTED",
            "symbol": symbol,
            "filled_qty": 0 # Async fill, so initially 0
        }

    except Exception as e:
        print(f"⚠️ EXECUTION ERROR for {symbol}: {e}")
        return {"error": str(e)}

# Export
execution_tools = [execute_order]
