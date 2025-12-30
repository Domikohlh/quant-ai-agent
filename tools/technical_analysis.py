# tools/technical_analysis.py
import pandas as pd
import pandas_ta as ta
import numpy as np

def safe_float(value, default=0.0):
    """
    Safely converts a value to float.
    Handles None, NaN, strings, and other edge cases.
    """
    try:
        if value is None:
            return default
        if pd.isna(value): # Handles np.nan, pd.NA, math.nan
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def calculate_technicals(symbol: str, data: list[dict]) -> dict:
    """
    Computes technical indicators with strict type safety.
    """
    # 1. Validation: Need enough data
    if not data or len(data) < 30:
        return {"error": f"Insufficient data: {len(data)} bars (Need 30+)"}

    # 2. DataFrame Construction
    df = pd.DataFrame(data)
    
    # Normalize headers
    df.columns = [c.lower() for c in df.columns]
    
    # Deduplicate columns (Fix for "multiple columns" error)
    df = df.loc[:, ~df.columns.duplicated()]
    
    # Ensure 'close' exists
    if 'close' not in df.columns:
        return {"error": f"'close' column missing. Found: {df.columns.tolist()}"}
    
    # --- CRITICAL FIX: FORCE NUMERIC ---
    # Convert 'close' to numeric, coercing errors (None/String) to NaN
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    
    # Drop rows where 'close' is NaN (Corrupt data points)
    df.dropna(subset=['close'], inplace=True)
    
    if df.empty:
        return {"error": "All Close prices were invalid (NaN/None)."}

    try:
        # Extract Series safely
        close_series = df['close']

        # 3. Calculate Indicators
        # A. RSI (14)
        df['RSI'] = ta.rsi(close_series, length=14)
        
        # B. Bollinger Bands (20, 2.0)
        bb_df = ta.bbands(close_series, length=20, std=2)
        if bb_df is not None:
            df = pd.concat([df, bb_df], axis=1)
        
        # C. MACD
        macd_df = ta.macd(close_series, fast=12, slow=26, signal=9)
        if macd_df is not None:
            df = pd.concat([df, macd_df], axis=1)

        # D. SMA (Calculated cleanly)
        df['SMA_50'] = ta.sma(close_series, length=50)
        df['SMA_200'] = ta.sma(close_series, length=200)
        
        # 4. Extract Latest Values (The "Safe" Way)
        latest = df.iloc[-1]
        
        # We use the raw 'close' value from the row, ensuring it's a float
        current_price = safe_float(latest['close'])
        
        # Helper to find dynamic columns (like BBU_20_2.0)
        def get_col(prefix, default_val):
            # Search for column starting with prefix
            col_name = next((c for c in df.columns if c.startswith(prefix)), None)
            if col_name:
                return safe_float(latest.get(col_name), default_val)
            return default_val

        # --- CONSTRUCT SAFE RESPONSE ---
        # Note: We use safe_float() everywhere to prevent the NoneType error
        
        return {
            "symbol": symbol,
            "current_price": current_price,
            "RSI": safe_float(latest.get('RSI'), 50.0),
            "MACD": get_col('MACD_12', 0.0),
            "MACD_SIGNAL": get_col('MACDs_12', 0.0),
            "BB_UPPER": get_col('BBU', current_price), # Default to price if missing
            "BB_LOWER": get_col('BBL', current_price),
            "SMA_50": safe_float(latest.get('SMA_50'), current_price),
            "SMA_200": safe_float(latest.get('SMA_200'), current_price),
            "trend": "BULLISH" if current_price > safe_float(latest.get('SMA_200'), 0) else "BEARISH"
        }

    except Exception as e:
        print(f"⚠️ TA ERROR for {symbol}: {e}")
        return {"error": str(e)}
