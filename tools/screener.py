# tools/screener.py
import os
import re
import yfinance as yf
import pandas as pd
from typing import List
from langchain_community.tools import BraveSearch

# 1. DEFINE A ROBUST STATIC UNIVERSE (The "Safety Net")
# If Brave Search fails or returns junk, we default to these 40 blue chips.
STATIC_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", # Tech/Growth
    "JPM", "BAC", "V", "MA", "WFC",                                   # Finance
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK",                        # Healthcare
    "PG", "KO", "PEP", "COST", "WMT", "MCD",                          # Staples/Consumer
    "XOM", "CVX", "LIN", "CAT", "UNP",                                # Industrial/Energy
    "RTX", "LMT", "GE", "HON"                                         # Defense/Industrial
]

def get_tickers_from_brave(query: str = "best undervalued S&P 100 stocks 2025") -> List[str]:
    """
    Uses Brave Search to find trending or recommended stocks dynamically.
    """
    print(f"🌐 BRAVE SEARCH: '{query}'...")
    
    try:
        # Initialize Brave Search (Requires BRAVE_API_KEY in .env)
        tool = BraveSearch.from_api_key(
            api_key=os.getenv("BRAVE_API_KEY"),
            search_kwargs={"count": 5}
        )
        results = tool.run(query)
        
        # --- SMART TICKER EXTRACTION ---
        # Regex: Finds 1-5 Uppercase letters.
        # We assume tickers often appear as $AAPL or just AAPL in finance context.
        # We filter out common words (THE, FOR, AND) to reduce noise.
        found_tickers = set(re.findall(r'\b[A-Z]{2,5}\b', results))
        
        # Basic Stoplist of common uppercase words in news snippets
        stoplist = {"THE", "FOR", "AND", "ARE", "WAS", "HAS", "NOT", "NEW", "YORK", "CEO", "USA", "USD", "GDP", "FYI", "AI", "ETF"}
        
        valid_tickers = [t for t in found_tickers if t not in stoplist]
        
        print(f"   ↳ Found in news: {valid_tickers}")
        return valid_tickers
        
    except Exception as e:
        print(f"⚠️ BRAVE SEARCH FAILED: {e}")
        return []

def get_fundamental_data(symbols: List[str]):
    """
    Fetches fundamental stats (Beta, Margin, Growth) for filtering.
    """
    print(f"🔍 SCREENING {len(symbols)} CANDIDATES...")
    metrics = []
    
    # Limit to first 30 to prevent timeouts
    scan_limit = symbols[:30]
    
    for symbol in scan_limit:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Skip if data is bad
            if 'beta' not in info:
                continue

            data = {
                "symbol": symbol,
                "beta": info.get("beta", 1.5),
                "profit_margin": info.get("profitMargins", 0),
                "rev_growth": info.get("revenueGrowth", 0),
                "div_yield": info.get("dividendYield", 0)
            }
            metrics.append(data)
        except Exception:
            # Silent skip for invalid tickers found by Brave
            continue

    return pd.DataFrame(metrics)

# --- AGENT TOOL ---
def screen_stocks(top_n: int = 5, mode: str = "standard", exclude_tickers: list = None) -> List[str]:
    """
    Screens stocks based on a specific 'Mode' for the Iterative Hunt.
    
    Args:
        top_n: Number of stocks to return.
        mode: 'standard' (Safe), 'undervalued' (Yield), or 'momentum' (Growth).
        exclude_tickers: List of symbols to skip (already analyzed).
    """
    if exclude_tickers is None: exclude_tickers = []
    
    print(f"🔍 SCREENER MODE: {mode.upper()} (Excluding {len(exclude_tickers)} items)")

    # 1. SETUP STRATEGY: Define Universe Source & Query
    if mode == "undervalued":
        query = "best undervalued high dividend stocks 2025"
        # Fallback: High yield, low valuation tickers
        fallback_list = ["T", "VZ", "PFE", "C", "KHC", "BMY", "CVX"]
        
    elif mode == "momentum":
        query = "top high growth momentum stocks 2025"
        # Fallback: High beta, high growth tickers
        fallback_list = ["AMD", "PLTR", "UBER", "NET", "DKNG", "CRWD", "NVDA"]
        
    else: # "standard" (Default)
        query = "safest growing S&P 500 stocks 2025"
        fallback_list = STATIC_UNIVERSE

    # 2. HYBRID DISCOVERY (Brave + Static)
    dynamic_picks = get_tickers_from_brave(query=query)
    universe = list(set(fallback_list + dynamic_picks))
    
    # 3. EXCLUSION FILTER (Remove previously analyzed stocks)
    # This forces the screener to look at *new* options on retry
    filtered_universe = [t for t in universe if t not in exclude_tickers]
    
    # If we filtered everything out, try the fallback list again or fail gracefully
    if not filtered_universe:
        print("⚠️ All candidates excluded. Resetting to fallback list.")
        filtered_universe = [t for t in fallback_list if t not in exclude_tickers]
        if not filtered_universe:
             return ["SPY"] # Last resort

    # 4. FETCH DATA
    df = get_fundamental_data(filtered_universe)
    
    if df.empty:
        return ["MSFT", "AAPL"]

    # 5. DYNAMIC FILTERING & RANKING
    # We apply different weights based on the active mode
    
    if mode == "undervalued":
        # Strategy: Strict on P/E (if we had it) or Yield, Relaxed on Beta
        # Filter: Must pay a dividend
        df = df[df['div_yield'] > 0.02].copy()
        
        # Rank: Heavily weight Dividend (70%) + Profitability (30%)
        df['score'] = (df['div_yield'].fillna(0) * 70) + (df['profit_margin'].fillna(0) * 30)
        
    elif mode == "momentum":
        # Strategy: High Growth, Allow High Volatility
        # Filter: Positive Revenue Growth
        df = df[df['rev_growth'] > 0.05].copy()
        
        # Rank: Heavily weight Growth (60%) + Beta (40%) (High beta = more movement)
        df['score'] = (df['rev_growth'].fillna(0) * 60) + (df['beta'].fillna(1) * 40)
        
    else: # standard
        # Strategy: The original "Steady Growth" logic
        # Filter: Low Volatility + High Margin
        df = df[df['beta'] < 1.5].copy()
        df = df[df['profit_margin'] > 0.15].copy()
        
        # Rank: Balanced
        df['score'] = (
            (df['profit_margin'].fillna(0) * 40) +
            (df['div_yield'].fillna(0) * 30) +
            (df['rev_growth'].fillna(0) * 30)
        )
    
    # 6. FINAL SORT
    df = df[~df['symbol'].isin(exclude_tickers)]
    
    top_picks = df.sort_values(by='score', ascending=False).head(top_n)
    
    print(f"\n🏆 {mode.upper()} SCREENER RESULTS:")
    print(top_picks[['symbol', 'score']].to_string(index=False)) # Cleaner print
    
    return top_picks['symbol'].tolist()
