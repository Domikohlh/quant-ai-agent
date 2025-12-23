# tools/market_data.py
import os
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from fredapi import Fred
import pandas as pd
from datetime import datetime, timedelta

# Initialize Clients
alpaca_client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY")
)
fred = Fred(api_key=os.getenv("FRED_API_KEY"))

def fetch_market_data(symbols: list[str], days: int = 365) -> dict:
    """
    Fetches OHLCV data from Alpaca for a list of symbols.
    """
    print(f"📉 FETCHING ALPCA DATA FOR: {symbols}")
    
    # Calculate Time Window
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    request_params = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_time,
        end=end_time
    )

    bars = alpaca_client.get_stock_bars(request_params)
    
    # Convert to standard Dictionary format for the State
    # Structure: {'AAPL': {'close': [...], 'volume': [...]}, ...}
    market_data = {}
    for symbol in symbols:
        df = bars.df.loc[symbol]
        market_data[symbol] = df.reset_index().to_dict(orient="records")
        
    return market_data

def fetch_macro_data() -> dict:
    """
    Fetches key macro indicators from FRED: VIX (Volatility) and GDP.
    """
    print("🏦 FETCHING MACRO DATA (FRED)...")
    try:
        # VIXCLS = CBOE Volatility Index
        vix = fred.get_series('VIXCLS', limit=10).iloc[-1]
        
        # UNRATE = Unemployment Rate
        unemployment = fred.get_series('UNRATE', limit=1).iloc[-1]
        
        return {
            "VIX": vix,
            "UNEMPLOYMENT": unemployment,
            "MARKET_CONDITION": "VOLATILE" if vix > 20 else "STABLE"
        }
    except Exception as e:
        print(f"⚠️ FRED ERROR: {e}")
        return {"VIX": 0, "ERROR": str(e)}

# List of tools to export to the Agent
data_tools = [fetch_market_data, fetch_macro_data]
