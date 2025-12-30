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
def screen_stocks(top_n: int = 5) -> List[str]:
    """
    Screens stocks for steady growth and low risk.
    Combines a static 'Safe' list with dynamic picks from Brave Search.
    
    Args:
        top_n: Number of stocks to return (default: 5).
    """
    # 1. HYBRID DISCOVERY
    # Merge the static list with new ideas from the web
    dynamic_picks = get_tickers_from_brave(query="safest growing S&P 500 stocks 2025")
    
    # Use Set to remove duplicates
    universe = list(set(STATIC_UNIVERSE + dynamic_picks))
    
    # 2. FETCH DATA
    df = get_fundamental_data(universe)
    
    if df.empty:
        print("⚠️ No data found. Defaulting to MSFT/AAPL.")
        return ["MSFT", "AAPL"]

    # 3. FILTER LOGIC (The "Steady Growth" Strategy)
    # A. Low Volatility: Beta < 1.3 (Slightly relaxed to include Tech)
    safe_stocks = df[df['beta'] < 1.3].copy()
    
    # B. Profitable: Margin > 15%
    quality_stocks = safe_stocks[safe_stocks['profit_margin'] > 0.15].copy()
    
    # 4. RANKING
    # Score = (Profit Margin * 40) + (Dividend * 30) + (Growth * 30)
    # This favors cash-rich, paying companies.
    quality_stocks['score'] = (
        (quality_stocks['profit_margin'].fillna(0) * 40) +
        (quality_stocks['div_yield'].fillna(0) * 30) +
        (quality_stocks['rev_growth'].fillna(0) * 30)
    )
    
    # Sort
    top_picks = quality_stocks.sort_values(by='score', ascending=False).head(top_n)
    
    print("\n🏆 AI SCREENER RESULTS:")
    print(top_picks[['symbol', 'beta', 'profit_margin', 'div_yield']])
    
    return top_picks['symbol'].tolist()
