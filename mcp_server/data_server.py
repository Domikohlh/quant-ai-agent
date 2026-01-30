import os
import re
import sys
import logging
from pathlib import Path
from typing import Optional
import json
import requests
from datetime import timedelta
import numpy as np

import pandas as pd
import yfinance as yf
from fastmcp import FastMCP
from dotenv import load_dotenv

from google.cloud import bigquery

# --- 1. Path Setup (To import core/database.py) ---
# We need to add the project root to sys.path so we can import 'core'
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager

# --- 2. Initialization ---
logger = logging.getLogger("QuantDataServer")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Deterministic env loading: prefer `.env` next to this file, else project root `.env`.
dotenv_candidates = [current_dir / ".env", project_root / ".env"]
for candidate in dotenv_candidates:
    if candidate.exists():
        load_dotenv(dotenv_path=candidate, override=True)
        break
else:
    # Still allow running if env is provided via process/host.
    load_dotenv(override=True)

mcp = FastMCP("QuantDataServer")

# --- Lazy singletons (init only when a tool needs them) ---
_db: Optional[DatabaseManager] = None
_fred = None


def _require_env(*keys: str) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            "Missing required env vars: "
            + ", ".join(missing)
            + ". Ensure `.env` is loaded or these are set in the environment."
        )


def _get_db() -> DatabaseManager:
    """
    BigQuery writes require a valid GCP project.
    SQL config is optional for this MCP's tools, but DatabaseManager currently
    requires those args, so we pass env values if present, else dummy strings.
    """
    global _db
    if _db is not None:
        return _db

    _require_env("GCP_PROJECT_ID", "GCP_REGION")
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_REGION")

    _db = DatabaseManager(
        project_id=project_id,
        region=region,
        sql_instance_name=os.getenv("SQL_INSTANCE_NAME", "dummy"),
        sql_db_name=os.getenv("SQL_DB_NAME", "dummy"),
    )
    logger.info("Initialized DatabaseManager project=%s region=%s", project_id, region)
    return _db


def _get_fred():
    global _fred
    if _fred is not None:
        return _fred
    _require_env("FRED_API_KEY")
    from fredapi import Fred  # local import: only required if macro tool is called

    _fred = Fred(api_key=os.getenv("FRED_API_KEY"))
    logger.info("Initialized FRED client")
    return _fred


def _sanitize_ticker(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip().upper())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        raise ValueError("ticker is empty/invalid after sanitization")
    return cleaned


def _validate_stock_params(ticker: str, period: str, interval: str) -> None:
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")

    allowed_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    allowed_intervals = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if period not in allowed_periods:
        raise ValueError(f"period must be one of {sorted(allowed_periods)}")
    if interval not in allowed_intervals:
        raise ValueError(f"interval must be one of {sorted(allowed_intervals)}")

# --- 3. The Tools ---

@mcp.tool()
def update_stock_data(ticker: str, period: str = "2y", interval: str = "1h") -> str:
    """
    Downloads stock data from YFinance, calculates Technical Indicators (RSI, MACD, SMA),
    and saves the stock + technical data to BigQuery.
    
    Args:
        ticker: Stock Ticker Symbol like 'AAPL', 'NVDA'
        period: History to fetch ('1mo', '6mo', '1y', '5y')
        interval: Time interval for the data ('1h', '1d', '1w', '1m')
    
    Returns: 
        Summary of the data processed and stored in BigQuery.
        Example return:
        ''' JSON string containing the data processed and stored in BigQuery.
        Example return values:
        {
        "status": "success",
        "message": "Quant indicators (MACD Fast/Med/Slow, VWAP, Donchian) processed for AAPL",
        "bq_table_id": "market_data.processed_tech_indicators",
        "data_shape": [1000, 24],
        "columns": [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "macd_12_26_9",       
            "macdh_12_26_9",      
            "macds_12_26_9",      
            "macd_10_24_7",
            "macdh_10_24_7",
            "macds_10_24_7",
            "macd_5_13_4",
            "macdh_5_13_4",
            "macds_5_13_4",
            "dcl_20_20",          
            "dcm_20_20",          
            "dcu_20_20",          
            "bbe_20_2_0",         
            "bbl_20_2_0",         
            "bbu_20_2_0",         
            "atr_14",
            "vwap_d",
            "rsi_14",
            "sma_50",
            "sma_200",
            "ticker",
            "source"
        ],
        "feature_distribution_stats": {
            "close": {
            "count": 1000.0,
            "mean": 185.42,
            "std": 15.30,
            "min": 150.25,
            "25%": 172.10,
            "50%": 185.50,
            "75%": 198.20,
            "max": 220.15
            },
            "rsi_14": {
            "count": 1000.0,
            "mean": 52.10,
            "std": 12.45,
            "min": 22.40,
            "50%": 51.30,
            "max": 84.10
            },
            "macdh_5_13_4": {
            "count": 1000.0,
            "mean": 0.05,
            "std": 1.20,
            "min": -3.50,
            "50%": 0.02,
            "max": 4.10
            }
        },
        "sample_data": [
            {
            "timestamp": "2024-05-20T00:00:00.000Z",
            "open": 218.10,
            "high": 220.50,
            "low": 217.80,
            "close": 219.95,
            "volume": 45000200,
            "macd_12_26_9": 2.45,
            "macdh_12_26_9": 0.15,
            "macds_12_26_9": 2.30,
            "macd_5_13_4": 1.10,
            "macdh_5_13_4": 0.05,
            "dcl_20_20": 205.00,
            "dcu_20_20": 221.00,
            "vwap_d": 219.41,
            "rsi_14": 68.40,
            "ticker": "AAPL",
            "source": "YFINANCE"
            }
        ]
        }
        '''
        Error message if the data is not found or an error occurs.
        Example error message:
        {
            "status": "error",
            "message": "Error: No data found for AAPL."
        }
    """
    try:
        # 1. Initial Validation (Your Structure)
        _validate_stock_params(ticker=ticker, period=period, interval=interval)
        safe_ticker = _sanitize_ticker(ticker)
        
        # --- INTELLIGENT INCREMENTAL LOAD ---
        table_id = os.getenv("BQ_TECH_TABLE_ID", "market_data.processed_tech_indicators")
        db = _get_db()
        
        # 2. Check BigQuery state
        last_date, bq_date_col = db.get_latest_record_info(table_id, safe_ticker)
        
        df = pd.DataFrame()
        
        # 3. Decide Download Strategy
        if last_date:
            logger.info(f"Found existing data for {safe_ticker} up to {last_date}. Switching to incremental load.")
            
            # Intelligent Buffer: We fetch 30 days PRIOR to last_date to ensure indicators (MACD/RSI) 
            # have enough "warmup" data to be accurate.
            from datetime import timedelta
            import pytz
            
            # Ensure last_date is timezone-aware for math
            if isinstance(last_date, str):
                last_date = pd.to_datetime(last_date)
            if last_date.tzinfo is None:
                 last_date = last_date.replace(tzinfo=pytz.UTC)
                 
            buffer_days = 90 
            buffered_start = last_date - timedelta(days=buffer_days)
            
            # Use 'start' instead of 'period' to target the gap
            df = yf.download(safe_ticker, start=buffered_start, interval=interval, auto_adjust=True, progress=False)
            
        else:
            logger.info(f"Fetching full stock data ticker={safe_ticker} period={period}")
            df = yf.download(safe_ticker, period=period, interval=interval, auto_adjust=True, progress=False)

        if df.empty:
            return f"Error: No data found for {safe_ticker}."

        # Flatten columns if MultiIndex (Fix for recent YFinance versions)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 4. Calculate Indicators (Requires the buffer data!)
        import pandas_ta as ta
        if len(df) > 50:
            df.ta.rsi(append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.macd(fast=10, slow=24, signal=7, append=True)
            df.ta.macd(fast=5, slow=13, signal=4, append=True)
            df.ta.sma(length=50, append=True)
            df.ta.sma(length=200, append=True)
            df.ta.bbands(append=True)
            df.ta.atr(length=14, append=True)
            if 'Volume' in df.columns:
                df.ta.vwap(append=True)

            # New technical indicators
            df.ta.zscore(close=df['Close'], length=30, append=True)
            df.ta.ppo(fast=12, slow=26, signal=9, append=True)
            df['pct_rank_20'] = df['Close'].rolling(20).rank(pct=True)
            df.ta.trix(length=30, append=True)
            df.ta.roc(length=10, append=True)
            df.ta.apo(fast=12, slow=26, append=True)

            #Permutation
            #Downcast 
            float_cols = df.select_dtypes(include=['float64']).columns
            df[float_cols]= df[float_cols].astype('float32')


            raw_cols = {'timestamp', 'close', 'high', 'low', 'open', 'volume', 'ticker', 'source'}
            tech_indicators = [c for c in df.columns if c not in raw_cols]
            perm_windows = [1,3,6,12,24,36,48,72]

            for col in tech_indicators:
                for w in perm_windows:
                    # 1. Momentum: The rate of change of the indicator
                    # e.g., "Is RSI rising faster than usual?"
                    df[f'{col}_diff_{w}'] = df[col].diff(w).astype('float32')
                    
                    # 2. Volatility: The stability of the indicator
                    # e.g., "Is the MACD signal getting noisy/unstable?"
                    df[f'{col}_vol_{w}'] = df[col].rolling(w).std().astype('float32')
            
            if df.isna().all().any():
                df.dropna(axis=1, how='all', inplace=True)
            
            df.dropna(inplace=True)

            if df.empty:
             return json.dumps({"status": "error", "message": f"Insufficient data length. SMA_200 requires 200+ rows. Downloaded: {rows_added if 'rows_added' in locals() else 'unknown'}"})

        # 5. Dynamic Schema Alignment
        df.reset_index(inplace=True)
        
        # Identify the DF's time column
        df_time_col = None
        for col in ["Date", "Datetime", "index"]:
            if col in df.columns:
                df_time_col = col
                break
        
        if df_time_col:
            # RENAME to standardized 'timestamp' for DB
            df.rename(columns={df_time_col: bq_date_col}, inplace=True)
        
        # Standardize other columns
        df.columns = [
            c if c == bq_date_col else c.lower().replace(" ", "_").replace("-", "_").replace(".", "_").replace("%", "pct")
            for c in df.columns
        ]
        
        df["ticker"] = safe_ticker
        df["source"] = "YFINANCE"

        # 6. Filter Overlaps & Save
        rows_added = 0
        final_df = None

        if last_date:
            # We downloaded a buffer (old data). We must DROP it before saving.
            # Convert DF date to TZ-aware if needed
            if df[bq_date_col].dt.tz is None:
                 df[bq_date_col] = df[bq_date_col].dt.tz_localize('UTC')
            
            # Filter: Keep only strictly NEW data
            new_data_mask = df[bq_date_col] > last_date
            df_to_save = df.loc[new_data_mask].copy()
            
            if not df_to_save.empty:
                db.save_market_data(df_to_save, table_id=table_id)
                rows_added = len(df_to_save)
                # Return tail of new data for context
                final_df = df_to_save.tail(100)
            else:
                logger.info("No new data found after forward-fill.")
                final_df = df.tail(5) # Just show what we have
        else:
            # Initial Load - Save Everything
            db.save_market_data(df, table_id=table_id)
            rows_added = len(df)
            final_df = df.copy()

        # 7. Construct Response
        if final_df is None or final_df.empty:
             return json.dumps({"status": "error", "message": "Data processed but could not be retrieved."})

        # Ensure sorted
        if bq_date_col in final_df.columns:
            final_df.sort_values(by=bq_date_col, ascending=True, inplace=True)
            latest_date_str = str(final_df[bq_date_col].max())
        else:
            latest_date_str = "Unknown"

        response_data = {
            "status": "success",
            "ticker": safe_ticker,
            "rows_added": rows_added,
            "latest_data_date": latest_date_str,
            "columns": final_df.columns.tolist(),
            "sample_data": json.loads(final_df.tail(5).to_json(orient="records", date_format="iso"))
        }

        return json.dumps(response_data, indent=2)

    except Exception as e:
        logger.error(f"Error updating stock data: {e}")
        return json.dumps({"status": "error", "message": str(e)})

@mcp.tool()
def update_macro_data(series_id: str = "GDP") -> str:
    """
    Fetches macroeconomic data from FRED and stores it.
    Args:
        series_id: FRED Series ID (e.g., 'CPIAUCSL', 'UNRATE', 'FEDFUNDS')
    """
    try:
        if not isinstance(series_id, str) or not series_id.strip():
            raise ValueError("series_id must be a non-empty string")
        series_id = series_id.strip().upper()
        logger.info("Fetching macro data series_id=%s", series_id)
        
        # 1. Fetch
        fred = _get_fred()
        series = fred.get_series(series_id)
        df = series.to_frame(name="value")
        if df.empty:
            return f"Error: No FRED data found for {series_id}."
        df.reset_index(inplace=True)
        df.rename(columns={"index": "timestamp"}, inplace=True)
        
        # 2. Enrich
        df["indicator"] = series_id
        df["source"] = "FRED"
        
        # 3. Store
        # We might need a generic saver or reuse market_data with flexible schema
        # For now, let's assume we save to a specific macro table
        table_id = os.getenv("BQ_MACRO_TABLE_ID", "market_data.macro_indicators")
        _get_db().save_market_data(df, table_id=table_id)
        
        latest_val = df.iloc[-1]['value']
        latest_date = df.iloc[-1]['timestamp'].strftime('%Y-%m-%d')
        
        return f"✅ Updated {series_id}. Latest value: {latest_val} ({latest_date}). Stored in BigQuery table: {table_id}"
        
    except Exception as e:
        return f"❌ Error fetching FRED data: {e}"

@mcp.tool()
def search_financial_news(query: str, count: int = 5) -> str:
    """
    Searches high-trust financial news sources (Bloomberg, Reuters, WSJ, etc.) 
    using the Brave Search API. Use this for sentiment analysis and macro news.
    
    Args:
        query: The search topic (e.g., "NVDA institutional sentiment", "US GDP forecast")
        count: Number of results to return (default 5, max 20)
    """
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return "Error: BRAVE_API_KEY not found in environment variables."

    # 1. Define Trust Filter
    # We use the 'site:' operator to force the engine to only look at these domains.
    trusted_domains = [
        "bloomberg.com",
        "reuters.com",
        "wsj.com",
        "cnbc.com",
        "ft.com",
        "barrons.com",
        "marketwatch.com",
        "theinformation.com"
    ]
    
    # Construct the OR filter: (site:bloomberg.com OR site:reuters.com ...)
    site_filter = " OR ".join([f"site:{d}" for d in trusted_domains])
    final_query = f"{query} ({site_filter})"
    
    logger.info(f"Searching Brave with query: {final_query}")

    # 2. Call Brave Search API
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    params = {
        "q": final_query,
        "count": count,
        "search_lang": "en",
        "text_decorations": 0, # Turn off bolding tags
        "snippet_length": 150  # Get decent context for the LLM
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 429:
            return "Error: Brave API rate limit exceeded."
        if response.status_code != 200:
            return f"Error: Brave API returned status {response.status_code}"

        data = response.json()
        
        # 3. Format Results for the LLM
        # We only want the high-value bits: Title, Link, Description, and Age (if available)
        web_results = data.get("web", {}).get("results", [])
        
        if not web_results:
            return f"No results found for '{query}' on trusted financial sites."

        formatted_results = []
        for i, item in enumerate(web_results, 1):
            title = item.get("title", "No Title")
            url = item.get("url", "#")
            desc = item.get("description", "No description.")
            # Age is useful for sentiment (e.g., "2 hours ago")
            age = item.get("age", "Unknown date") 
            
            formatted_results.append(
                f"{i}. [{title}]({url})\n   Date: {age}\n   Summary: {desc}"
            )

        return "\n\n".join(formatted_results)

    except Exception as e:
        logger.error(f"Error executing Brave search: {e}")
        return f"Error executing search: {str(e)}"

# --- 4. Running the Server ---
if __name__ == "__main__":
    # This starts the stdio server loop
    # IMPORTANT: MCP stdio transport requires stdout to be reserved for JSON-RPC.
    # Disable the CLI banner (rich ASCII) which breaks the protocol.
    mcp.run(show_banner=False)