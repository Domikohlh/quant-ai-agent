# tools/technical_analysis.py
import pandas as pd
import pandas_ta as ta

def calculate_technicals(symbol: str, data: list[dict]) -> dict:
    """
    Takes raw OHLCV data and returns key technical indicators.
    """
    if not data:
        return {"error": "No data"}

    # Convert list of dicts to DataFrame
    df = pd.DataFrame(data)
    
    # Ensure proper data types
    # Alpaca/IBKR usually return 'c', 'h', 'l', 'o', 'v' or 'close', 'high', ...
    # We normalize to lowercase full names for pandas_ta
    mapping = {'c': 'close', 'h': 'high', 'l': 'low', 'o': 'open', 'v': 'volume'}
    df = df.rename(columns=mapping)
    
    # Calculate Indicators
    try:
        # 1. RSI (Relative Strength Index) - Momentum
        df['RSI'] = df.ta.rsi(length=14)
        
        # 2. Bollinger Bands - Volatility
        bb = df.ta.bbands(length=20, std=2)
        df = pd.concat([df, bb], axis=1) # Append BB columns
        
        # 3. MACD (Moving Average Convergence Divergence) - Trend
        macd = df.ta.macd(fast=12, slow=26, signal=9)
        df = pd.concat([df, macd], axis=1)
        
        # 4. SMA (Simple Moving Average) - Trend Baseline
        df['SMA_50'] = df.ta.sma(length=50)
        df['SMA_200'] = df.ta.sma(length=200)
        
        # Get the latest row (Current state)
        latest = df.iloc[-1]
        
        return {
            "symbol": symbol,
            "current_price": float(latest['close']),
            "RSI": float(latest['RSI']),
            "MACD": float(latest['MACD_12_26_9']),
            "MACD_SIGNAL": float(latest['MACDs_12_26_9']),
            "BB_UPPER": float(latest['BBU_20_2.0']),
            "BB_LOWER": float(latest['BBL_20_2.0']),
            "SMA_50": float(latest['SMA_50']),
            "SMA_200": float(latest['SMA_200']),
            "trend": "BULLISH" if latest['close'] > latest['SMA_200'] else "BEARISH"
        }
    except Exception as e:
        print(f"⚠️ TA ERROR for {symbol}: {e}")
        return {"error": str(e)}
