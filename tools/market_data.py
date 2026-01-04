# tools/market_data.py
import os
import yfinance as yf
from fredapi import Fred
import pandas as pd
import ssl
import certifi

# Global SSL Context Fix
ssl._create_default_https_context = ssl._create_unverified_context

# Initialize Clients
fred = Fred(api_key=os.getenv("FRED_API_KEY"))

# ... (fetch_market_data remains the same) ...

def fetch_market_data(symbols: list[str], period: str = "1mo", interval: str = "1h") -> dict:
    """
    Fetches OHLCV data using Yahoo Finance.
    """
    print(f"📉 FETCHING YFINANCE DATA FOR: {symbols} (Interval: {interval})")
    
    market_data = {}
    
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period, interval=interval, auto_adjust=True)
            
            if hist.empty:
                print(f"⚠️ Warning: No data found for {symbol}")
                market_data[symbol] = []
                continue

            # Normalization
            hist = hist.reset_index()
            hist.columns = [c.lower() for c in hist.columns]
            market_data[symbol] = hist.to_dict(orient="records")
            
        except Exception as e:
            print(f"❌ ERROR fetching {symbol}: {e}")
            market_data[symbol] = []

    return market_data

def fetch_macro_data(series_ids: list[str] = None) -> dict:
    """
    Fetches key macro indicators from FRED.
    Arguments:
        series_ids: List of FRED Series IDs (e.g., ['VIXCLS', 'DGS10', 'GDP']).
                    Defaults to VIX only if None.
    """
    # 1. Default to VIX if nothing requested
    if not series_ids:
        series_ids = ["VIXCLS"]

    print(f"🏦 FETCHING MACRO DATA (FRED): {series_ids}...")
    macro_data = {}

    try:
        for series_id in series_ids:
            try:
                # Fetch last 10 points to ensure we get a non-NaN value
                series = fred.get_series(series_id, limit=10)
                
                if series.empty:
                    print(f"   ⚠️ Series {series_id} returned no data.")
                    macro_data[series_id] = None
                    continue

                # Get the last valid value (latest date)
                latest_value = series.dropna().iloc[-1]
                latest_date = series.dropna().index[-1].strftime('%Y-%m-%d')
                
                macro_data[series_id] = {
                    "value": float(latest_value),
                    "date": latest_date
                }
                
            except Exception as e_inner:
                print(f"   ⚠️ Failed to fetch {series_id}: {e_inner}")
                macro_data[series_id] = None

        # 2. Add Derivative Logic (Market Condition)
        # If VIX is present, we calculate the 'Mood'
        vix_entry = macro_data.get("VIXCLS")
        if vix_entry:
            vix_val = vix_entry["value"]
            macro_data["MARKET_CONDITION"] = "VOLATILE" if vix_val > 20 else "STABLE"
        
        return macro_data

    except Exception as e:
        print(f"⚠️ FRED FATAL ERROR: {e}")
        return {"ERROR": str(e)}

# Export tools
data_tools = [fetch_market_data, fetch_macro_data]
