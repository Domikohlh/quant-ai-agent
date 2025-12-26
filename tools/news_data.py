# tools/news_data.py
import os
import requests
from difflib import SequenceMatcher

# 1. REMOVE NOISE (Clickbait / Robo-journalism)
BLACKLIST_DOMAINS = [
    "fool.com", "zacks.com", "investorplace.com", "seekingalpha.com", 
    "stocktwits.com", "yahoofinance.com" # Often just aggregates generic feeds
]

# 2. PRIORITIZE SIGNAL (Tier 1 Financial Journalism)
TRUSTED_SOURCES = [
    "bloomberg", "reuters", "wsj", "cnbc", "financial times", 
    "barron's", "marketwatch", "the information"
]

def clean_and_deduplicate(news_items: list[dict]) -> list[str]:
    cleaned = []
    seen_titles = []

    for item in news_items:
        title = item.get("title", "")
        desc = item.get("description", "")
        # Normalize source name for checking
        source_raw = item.get("source", {}).get("name", "Unknown")
        source_lower = source_raw.lower()
        full_text = f"{title} {desc}".lower()

        # --- A. FILTERING ---
        if any(bad in source_lower for bad in BLACKLIST_DOMAINS):
            continue
        # Skip generic stock report phrases
        if "zacks rank" in full_text or "motley fool" in full_text:
            continue

        # --- B. DEDUPLICATION ---
        is_duplicate = False
        for seen in seen_titles:
            if SequenceMatcher(None, title, seen).ratio() > 0.65:
                is_duplicate = True
                break
        if is_duplicate:
            continue
        
        seen_titles.append(title)

        # --- C. SOURCE WEIGHTING ---
        # We add a visual tag [⭐ TRUSTED] so the LLM pays more attention
        is_trusted = any(trusted in source_lower for trusted in TRUSTED_SOURCES)
        source_tag = f"⭐ {source_raw.upper()}" if is_trusted else source_raw.upper()

        # Format: [SOURCE] Title - Description
        entry = f"[{source_tag} | {item.get('age', 'recent')}] {title} - {desc}"
        cleaned.append(entry)

    return cleaned

def fetch_financial_news(ticker: str, count: int = 5) -> list[str]:
    """
    Fetches news metadata via Brave API (Safe from CAPTCHA).
    """
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return ["Error: BRAVE_API_KEY missing"]

    params = {
        "q": f"{ticker} stock news financial",
        "count": 15, # Fetch extra to allow for filtering
        "freshness": "pd", # Past Day
        "text_decorations": False
    }
    
    headers = {"X-Subscription-Token": api_key}
    
    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/news/search", 
            headers=headers, 
            params=params
        )
        data = response.json()
        results = clean_and_deduplicate(data.get("results", []))
        
        # Return top N after cleaning
        return results[:count]

    except Exception as e:
        print(f"⚠️ NEWS ERROR: {e}")
        return []

news_tools = [fetch_financial_news]
