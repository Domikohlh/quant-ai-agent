# tools/market_data.py
import os
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from fredapi import Fred
import pandas as pd
from datetime import datetime, timedelta
import ssl
import certifi

# Global SSL Context Fix
ssl._create_default_https_context = ssl._create_unverified_context

# Initialize Clients
alpaca_client = StockHistoricalDataClient(
    os.getenv("ALPACA_API_KEY"),
    os.getenv("ALPACA_SECRET_KEY")
)
fred = Fred(api_key=os.getenv("FRED_API_KEY"))

def fetch_market_data(symbols: list[str], days: int = 365) -> dict:
    """
    Fetches OHLCV data. 
    ADJUSTMENT: Applies a 20-minute lag to support Alpaca Free Plan.
    """
    print(f"📉 FETCHING ALPACA DATA FOR: {symbols}")
    
    # --- FIX IS HERE ---
    # Free Plan Data is delayed by 15 mins.
    # We subtract 20 mins to be safe and avoid the "SIP data" error.
    end_time = datetime.now() - timedelta(days=1)
    start_time = end_time - timedelta(days=days)

    try:
        request_params = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start_time,
            end=end_time
        )

        bars = alpaca_client.get_stock_bars(request_params)
        
        # Convert to Dictionary
        market_data = {}
        for symbol in symbols:
            # Check if we actually got data for this symbol
            if symbol in bars.df.index:
                df = bars.df.loc[symbol]
                market_data[symbol] = df.reset_index().to_dict(orient="records")
            else:
                print(f"⚠️ Warning: No data found for {symbol}")
                market_data[symbol] = []
            
        return market_data

    except Exception as e:
        print(f"❌ ALPACA DATA ERROR: {e}")
        return {}

def fetch_macro_data() -> dict:
    """
    Fetches key macro indicators from FRED.
    """
    print("🏦 FETCHING MACRO DATA (FRED)...")
    try:
        # VIXCLS = CBOE Volatility Index
        vix_series = fred.get_series('VIXCLS', limit=10)
        
        # Handle case where FRED returns NaN for the very last day (common)
        vix = vix_series.dropna().iloc[-1] if not vix_series.empty else 20.0
        
        return {
            "VIX": float(vix),
            "MARKET_CONDITION": "VOLATILE" if vix > 20 else "STABLE"
        }
    except Exception as e:
        print(f"⚠️ FRED ERROR: {e}")
        return {"VIX": 0.0, "ERROR": str(e)}

data_tools = [fetch_market_data, fetch_macro_data]
