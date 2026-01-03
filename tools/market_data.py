# tools/market_data.py
import os
import yfinance as yf
from fredapi import Fred
import pandas as pd
import ssl
import certifi

# Global SSL Context Fix (Crucial for Mac/Local environments)
ssl._create_default_https_context = ssl._create_unverified_context

# Initialize Clients
# Note: Alpaca client removed. yfinance does not need authentication.
fred = Fred(api_key=os.getenv("FRED_API_KEY"))

def fetch_market_data(symbols: list[str], period: str = "1mo", interval: str = "1h") -> dict:
    """
    Fetches OHLCV data using Yahoo Finance.
    Arguments:
        symbols: List of tickers.
        period: Data duration ("1d", "5d", "1mo", "1y", "max").
        interval: Bar size ("1m", "5m", "15m", "1h", "1d").
    """
    print(f"📉 FETCHING YFINANCE DATA FOR: {symbols} (Interval: {interval})")
    
    market_data = {}
    
    # We iterate to handle each symbol safely and normalize headers
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            # Fetch history
            # auto_adjust=True fixes splits/dividends in one go
            hist = ticker.history(period=period, interval=interval, auto_adjust=True)
            
            if hist.empty:
                print(f"⚠️ Warning: No data found for {symbol}")
                market_data[symbol] = []
                continue

            # --- NORMALIZATION STEP ---
            # 1. Reset Index to make Date/Datetime a column
            hist = hist.reset_index()
            
            # 2. Lowercase column names for compatibility with Technical Analysis tools
            # (Converts 'Date', 'Open', 'Close' -> 'date', 'open', 'close')
            hist.columns = [c.lower() for c in hist.columns]
            
            # 3. Rename specific time column if needed (yfinance uses 'date' or 'datetime')
            # Ensure we have a consistent time key if needed, but 'date' is standard.
            
            # Convert to list of dictionaries
            market_data[symbol] = hist.to_dict(orient="records")
            
        except Exception as e:
            print(f"❌ ERROR fetching {symbol}: {e}")
            market_data[symbol] = []

    return market_data

def fetch_macro_data() -> dict:
    """
    Fetches key macro indicators from FRED.
    """
    print("🏦 FETCHING MACRO DATA (FRED)...")
    try:
        # VIXCLS = CBOE Volatility Index
        vix_series = fred.get_series('VIXCLS', limit=10)
        
        # Handle case where FRED returns NaN for the very last day
        vix = vix_series.dropna().iloc[-1] if not vix_series.empty else 20.0
        
        return {
            "VIX": float(vix),
            "MARKET_CONDITION": "VOLATILE" if vix > 20 else "STABLE"
        }
    except Exception as e:
        print(f"⚠️ FRED ERROR: {e}")
        return {"VIX": 0.0, "ERROR": str(e)}

# Export tools
data_tools = [fetch_market_data, fetch_macro_data]