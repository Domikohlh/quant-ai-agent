# tools/technical_analysis.py
import pandas as pd
import pandas_ta as ta

def calculate_technicals(symbol: str, data: list[dict]) -> dict:
    if not data or len(data) < 30:
        return {"error": f"Insufficient data: {len(data)} bars (Need 30+)"}

    df = pd.DataFrame(data)
    
    # Normalize
    mapping = {'c': 'close', 'h': 'high', 'l': 'low', 'o': 'open', 'v': 'volume'}
    df = df.rename(columns=mapping)
    df['close'] = pd.to_numeric(df['close'])

    try:
        # 1. RSI
        df['RSI'] = df.ta.rsi(length=14)
        
        # 2. Bollinger Bands
        # appends columns like BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
        df.ta.bbands(length=20, std=2, append=True)
        
        # 3. MACD
        df.ta.macd(fast=12, slow=26, signal=9, append=True)

        # 4. SMA
        df['SMA_50'] = df.ta.sma(length=50)
        df['SMA_200'] = df.ta.sma(length=200)
        
        latest = df.iloc[-1]
        
        # --- FIX: ROBUST COLUMN FINDER ---
        # We don't assume the name is 'BBU_20_2.0'. We look for ANY column starting with BBU.
        bbu_col = next((c for c in df.columns if c.startswith('BBU')), None)
        bbl_col = next((c for c in df.columns if c.startswith('BBL')), None)
        
        # Safe Extraction Helper
        def get_val(col_name, default=0.0):
            if col_name and col_name in latest:
                val = latest[col_name]
                return float(val) if pd.notna(val) else default
            return default

        current_price = float(latest['close'])

        return {
            "symbol": symbol,
            "current_price": current_price,
            "RSI": get_val('RSI', 50.0),
            "MACD": get_val('MACD_12_26_9', 0.0),
            "MACD_SIGNAL": get_val('MACDs_12_26_9', 0.0),
            "BB_UPPER": get_val(bbu_col, current_price), # Default to price (no deviation)
            "BB_LOWER": get_val(bbl_col, current_price),
            "SMA_50": get_val('SMA_50', current_price),
            "SMA_200": get_val('SMA_200', current_price),
            "trend": "BULLISH" if current_price > get_val('SMA_200', current_price) else "BEARISH"
        }

    except Exception as e:
        print(f"⚠️ TA ERROR for {symbol}: {e}")
        return {"error": str(e)}
