# tools/screener.py
import os
import re
import yfinance as yf
import pandas as pd
from typing import List
from langchain_community.tools import BraveSearch

# 1. DEFINE A ROBUST STATIC UNIVERSE (The "Safety Net")
STATIC_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", # Tech/Growth
    "JPM", "BAC", "V", "MA", "WFC",                                   # Finance
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK",                        # Healthcare
    "PG", "KO", "PEP", "COST", "WMT", "MCD",                          # Staples/Consumer
    "XOM", "CVX", "LIN", "CAT", "UNP",                                # Industrial/Energy
    "RTX", "LMT", "GE", "HON"                                         # Defense/Industrial
]

def get_tickers_from_brave(query: str) -> List[str]:
    """
    Uses Brave Search to find trending or recommended stocks dynamically.
    """
    print(f"🌐 BRAVE SEARCH: '{query}'...")
    
    try:
        # Initialize Brave Search
        # INCREASED COUNT to 20 to prevent candidate erosion
        tool = BraveSearch.from_api_key(
            api_key=os.getenv("BRAVE_API_KEY"),
            search_kwargs={"count": 20}
        )
        results = tool.run(query)
        
        # --- SMART TICKER EXTRACTION ---
        # Regex: Finds 2-5 Uppercase letters.
        found_tickers = set(re.findall(r'\b[A-Z]{2,5}\b', results))
        
        # Basic Stoplist
        stoplist = {
            "THE", "FOR", "AND", "ARE", "WAS", "HAS", "NOT", "NEW", "YORK",
            "CEO", "USA", "USD", "GDP", "FYI", "AI", "ETF", "EPS", "YTD",
            "BULL", "BEAR", "OWNS", "INC", "CORP", "LTD"
        }
        
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
            continue

    return pd.DataFrame(metrics)

# --- AGENT TOOL ---
def screen_stocks(top_n: int = 5, mode: str = "standard", exclude_tickers: list = None, custom_query: str = None) -> List[str]:
    """
    Screens stocks based on a specific 'Mode' OR a 'Custom Query'.
    """
    if exclude_tickers is None: exclude_tickers = []
    
    # 1. SETUP STRATEGY
    # PRIORITY: If custom_query exists (from Data Engineer LLM), use it.
    if custom_query:
        print(f"🔍 SCREENER: Running Custom Query -> '{custom_query}'")
        query = custom_query
        fallback_list = STATIC_UNIVERSE
    else:
        print(f"🔍 SCREENER MODE: {mode.upper()}")
        if mode == "undervalued":
            query = "best undervalued high dividend stocks 2025"
            fallback_list = ["T", "VZ", "PFE", "C", "KHC", "BMY", "CVX"]
        elif mode == "momentum":
            query = "top high growth momentum stocks 2025"
            fallback_list = ["AMD", "PLTR", "UBER", "NET", "DKNG", "CRWD", "NVDA"]
        else: # standard
            query = "safest growing S&P 500 stocks 2025"
            fallback_list = STATIC_UNIVERSE

    # 2. HYBRID DISCOVERY
    dynamic_picks = get_tickers_from_brave(query=query)
    
    # Combine lists (Dynamic takes precedence visually, but we mix them)
    universe = list(set(fallback_list + dynamic_picks))
    
    # 3. EXCLUSION FILTER
    filtered_universe = [t for t in universe if t not in exclude_tickers]
    
    # Fallback if exclusion wiped everything out
    if not filtered_universe:
        print("⚠️ All candidates excluded. Resetting to fallback list (ignoring exclusions).")
        filtered_universe = fallback_list

    # 4. FETCH DATA
    df = get_fundamental_data(filtered_universe)
    
    if df.empty:
        return ["SPY"]

    # 5. DYNAMIC FILTERING & RANKING
    if mode == "undervalued":
        df = df[df['div_yield'] > 0.02].copy()
        df['score'] = (df['div_yield'].fillna(0) * 70) + (df['profit_margin'].fillna(0) * 30)
        
    elif mode == "momentum":
        df = df[df['rev_growth'] > 0.05].copy()
        df['score'] = (df['rev_growth'].fillna(0) * 60) + (df['beta'].fillna(1) * 40)
        
    else: # standard
        df = df[df['beta'] < 1.5].copy()
        df = df[df['profit_margin'] > 0.15].copy()
        df['score'] = (
            (df['profit_margin'].fillna(0) * 40) +
            (df['div_yield'].fillna(0) * 30) +
            (df['rev_growth'].fillna(0) * 30)
        )
    
    # 6. FINAL SORT
    # Explicitly remove excluded tickers again just to be safe
    df = df[~df['symbol'].isin(exclude_tickers)]
    
    top_picks = df.sort_values(by='score', ascending=False).head(top_n)
    
    print(f"\n🏆 SCREENER RESULTS:")
    print(top_picks[['symbol', 'score']].to_string(index=False))
    
    return top_picks['symbol'].tolist()
