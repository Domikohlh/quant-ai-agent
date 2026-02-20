import os
import re
import sys
import logging
from pathlib import Path
from typing import Optional
import json
import requests
from datetime import timedelta, datetime
import numpy as np
import joblib
import io

import pandas as pd
import yfinance as yf
from fastmcp import FastMCP
from dotenv import load_dotenv

from google.cloud import bigquery, storage, run_v2
from google.api_core import client_options
import asyncio
from google.cloud.exceptions import NotFound


# --- 1. Path Setup (To import core/database.py) ---
# We need to add the project root to sys.path so we can import 'core'
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager
from helpers.data_helper import get_fred, sanitize_ticker, validate_stock_params, json_serial
from helpers.ml_helper import train_basket_model_core, run_feature_analysis_core
from helpers.backtest_helper import run_backtest_core

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

    _require_env("GCP_PROJECT_ID", "GCP_COMPUTE_REGION")
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION")

    _db = DatabaseManager(
        project_id=project_id,
        region=region,
        sql_instance_name=os.getenv("SQL_INSTANCE_NAME", "dummy"),
        sql_db_name=os.getenv("SQL_DB_NAME", "dummy"),
    )
    logger.info("Initialized DatabaseManager project=%s region=%s", project_id, region)
    return _db


# --- 3. The Tools ---

#====================================================================================

# 3.1 Data Calculating Module

#====================================================================================

@mcp.tool()
def check_existing_dataset(
    ticker: str, 
    basket_name: str = "default", 
    training_end_date: str = "2024-12-31"
) -> str:
    """
    Checks BigQuery to see if data exists for this asset and strategy.
    Returns the exact status of BOTH raw data and engineered training data.

    Args: 

        ticker = Target ticker for analysis
        basket_name = Set it to default for further finding 
        training_end_date = Set it to 2024-12-31 for the cutoff for backtesting in later stage
    """
    print(f"🔍 [AGENT HEARTBEAT]: Checking BigQuery for {ticker} ({basket_name}) data...")
    try:
        db = _get_db()
        safe_ticker = ticker.replace("-", "_").upper()
        safe_strategy = basket_name.replace("-", "_").lower()
        safe_date = training_end_date.replace("-", "")
        
        # Check 1: Raw Market Data
        raw_table = f"{db.project_id}.market_data.processed_indicators_{safe_strategy}"
        raw_exists = False
        try:
            db.bq_client.get_table(raw_table)
            raw_exists = True
        except NotFound:
            pass

        # Check 2: Engineered Training Data
        train_table = f"{db.project_id}.market_data.training_{safe_strategy}_{safe_ticker}_{safe_date}"
        train_exists = False
        try:
            db.bq_client.get_table(train_table)
            train_exists = True
        except NotFound:
            pass

        # Return explicit instructions to the Agent
        if train_exists:
            return "✅ FOUND: Engineered training data exists. SKIP `update_stock_data` and SKIP `ml_feature_analysis`. Proceed directly to Phase 2 (Model Training)."
        elif raw_exists and not train_exists:
            return "⚠️ PARTIAL: Raw data exists, but training data is missing. SKIP `update_stock_data`, but you MUST run `ml_feature_analysis`."
        else:
            return "❌ NOT FOUND: No data exists. You MUST run `update_stock_data` first, then run `ml_feature_analysis`."

    except Exception as e:
        return f"Error checking database: {str(e)}"

@mcp.tool()
def update_stock_data(ticker: str, period: str = "5y", interval: str = "1h") -> str:
    """
    Downloads historical OHLCV data for a stock, calculates technical indicators (RSI, MACD, Bollinger Bands),
    and saves the data to BigQuery.
    
    Args:
        ticker: The stock symbol (e.g., 'NVDA', 'AAPL').
        period: How far back to fetch data (e.g., '1y', '2y', '5y').
        interval: Bar size (e.g., '1h', '1d'). Defaults to '1h'.

    
    """
    try:
        # 1. Initial Validation (Your Structure)
        validate_stock_params(ticker=ticker, period=period, interval=interval)
        safe_ticker = sanitize_ticker(ticker)
        
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
    Fetches macroeconomic data from FRED (Federal Reserve Economic Data) and stores it in BigQuery.
    Useful for getting context on interest rates, inflation, or GDP.
    
    Args:
        series_id: The FRED Series ID (e.g., 'CPIAUCSL' for CPI, 'FEDFUNDS' for Fed Funds Rate).
    """
    try:
        if not isinstance(series_id, str) or not series_id.strip():
            raise ValueError("series_id must be a non-empty string")
        series_id = series_id.strip().upper()
        logger.info("Fetching macro data series_id=%s", series_id)
        
        # 1. Fetch
        fred = get_fred()
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
    Searches high-trust financial news sources (Bloomberg, Reuters, WSJ) for specific topics.
    Use this to find qualitative data to explain quantitative moves.
    
    Args:
        query: The search topic (e.g., "NVDA supply chain issues").
        count: Number of articles to return (default 5).
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

#====================================================================================

# 3.2 Machine Learning Module

#====================================================================================
@mcp.tool()
def get_latest_model_uri(ticker: str) -> str:
    """
    Retrieves the GCS URI of the most recently trained model for a specific ticker.
    This tool performs a fuzzy search in the 'models/' folder for any file containing the ticker.
    MUST perform this tool first before running any machine learning training module. 
    
    Args:
        ticker: The stock symbol (e.g., 'NVDA').
    """
    try:
        db = _get_db()
        project_id = os.getenv("GCP_PROJECT_ID")
        bucket_name = os.getenv("GCS_MODEL_BUCKET", f"{project_id}-models")
        bucket = db.storage_client.bucket(bucket_name)
        
        blobs = list(bucket.list_blobs(prefix="models/"))
        matching_blobs = [b for b in blobs if ticker in b.name and b.name.endswith(".joblib")]
        
        if not matching_blobs:
            return f"Error: No models found for {ticker}."

        # Sort by time (Newest First)
        matching_blobs.sort(key=lambda x: x.time_created, reverse=True)
        latest_blob = matching_blobs[0]
        
        # --- FIX: The Race Condition Time Gate ---
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        age_in_minutes = (now - latest_blob.time_created).total_seconds() / 60
        
        # If the newest model is older than 15 minutes, the Cloud Run job hasn't finished saving the new one yet.
        if age_in_minutes > 15:
            return (
                f"⏳ STILL TRAINING: The newest model found is {int(age_in_minutes)} minutes old. "
                f"The background incremental training job has not finished yet. "
                f"Do NOT proceed. Wait 60 seconds and call this tool again."
            )

        # --- FIX: Retrieve Metadata ---
        # GCS requires reloading the blob to fetch custom metadata
        latest_blob.reload() 
        metrics_text = json.dumps(latest_blob.metadata, indent=2) if latest_blob.metadata else "No metrics found attached to model."
        
        uri = f"gs://{bucket_name}/{latest_blob.name}"
        
        return (
            f"✅ FOUND LATEST MODEL: {uri}\n\n"
            f"--- TRUE ML METRICS ---\n"
            f"{metrics_text}\n\n"
            f"INSTRUCTION: Model retrieval successful. Proceed immediately to Phase 3 (backtest_model_strategy) using this URI."
        )
            
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def ml_feature_analysis(
    ticker: str, 
    basket: str = None, 
    barrier_width: float = 1.0, 
    time_horizon: int = 5,
    correlation_threshold: float = 0.85, 
    top_n: int = 15,
    training_end_date: str="2024-12-31",
    run_remote: bool = True
) -> str:
    """
    [STEP 1 of Pipeline] 
    Performs 'Triple Barrier' labeling and feature engineering on a basket of stocks.
    This tool GENERATES the training datasets required for Step 2.
    **CRITICAL *ONLY RUN THIS FUNCTION ONCE.
    
    Args:
        ticker: The target stock to predict (e.g., 'NVDA').
        basket: A COMMA-SEPARATED string of peer stocks to include in the analysis (e.g., 'NVDA,AMD,INTC,MSFT').
        barrier_width: The volatility multiplier for the target label (default 1.0).
        time_horizon: The number of bars to look ahead for the move (default 5).
        top_n: Number of best features to select (default 15).
        training_end_date: The cutoff date. Data BEFORE this is for Training. Data AFTER is for Testing.
        run_remote: Always set to True to run on Cloud Run Jobs.
    """

    if not run_remote:
        try:
            # Pass the new date parameter to the core function
            result = run_feature_analysis_core(
                ticker, basket, barrier_width, time_horizon, 
                correlation_threshold, top_n, training_end_date  # <--- Pass it here
            )
            return json.dumps(result, default=json_serial, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    try:
        from google.cloud import run_v2
        project_id = os.getenv("GCP_PROJECT_ID")
        region = os.getenv("GCP_COMPUTE_REGION", "us-central1")
        job_name = "quant-training-job" # We reuse the same job definition

        # Pass all args as string flags
        args = [
            "python", "mcp_server/training_logic.py",
            "--task", "analyze",
            "--ticker", ticker,
            "--barrier_width", str(barrier_width),
            "--time_horizon", str(time_horizon),
            "--top_n", str(top_n),
            "--training_end_date", training_end_date
        ]
        if basket:
            args.extend(["--basket", basket])

        client = run_v2.JobsClient()
        request = run_v2.RunJobRequest(
            name=f"projects/{project_id}/locations/{region}/jobs/{job_name}",
            overrides={
                "container_overrides": [{
                    "args": args
                }]
            }
        )
        operation = client.run_job(request=request)
        return f"🚀 Feature Analysis Job triggered for {ticker} (Basket: {basket or 'Single'})."

    except Exception as e:
        return f"Error triggering Cloud Job: {e}"

@mcp.tool()
def ml_train_basket_model(target_ticker: str, run_remote: bool = True, training_end_date: str="2024-12-31",) -> str:
    """
    [STEP 2 of Pipeline]
    Trains an XGBoost classifier using the datasets created by 'ml_feature_analysis'.
    **CRITICAL * ONLY RUN THIS FUNCTION ONCE.
    
    Args:
        target_ticker: The stock ticker to train the model for (must match the ticker used in Step 1).
        run_remote: Always set to True to run on Cloud Run Jobs.
    """
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1")
    bucket_name = os.getenv("GCS_MODEL_BUCKET", f"{project_id}-models")
    job_name = "quant-training-job" # Name of your Cloud Run Job

    if not run_remote:
        # Pass the new date parameter to the core function
        result = train_basket_model_core(target_ticker, bucket_name, training_end_date)
        return json.dumps(result, indent=2)

    try:
        # Trigger Cloud Run Job
        endpoint = f"{region}-run.googleapis.com"
        client = run_v2.JobsClient(
            client_options=client_options.ClientOptions(api_endpoint=endpoint)
        )
        request = run_v2.RunJobRequest(
            name=f"projects/{project_id}/locations/{region}/jobs/{job_name}",
            overrides={
                "container_overrides": [{
                    "args": ["python", 
                    "mcp_server/training_logic.py", 
                    "--task", "train",
                    "--ticker", target_ticker, 
                    "--bucket", bucket_name,
                    "--training_end_date", training_end_date
                    ]
                }]
            }
        )
        operation = client.run_job(request=request)
        return f"🚀 Training Job triggered for {target_ticker}. Saving to {bucket_name}. (Async execution started)"

    except Exception as e:
        return f"Error triggering Cloud Run Job: {e}"


#====================================================================================

# 3.3 Backtesting Module

#====================================================================================
@mcp.tool()
def backtest_model_strategy(
    ticker: str,
    model_uri: str,
    start_date: str = "2025-01-01",
    end_date: str = "2025-12-31"
) -> str:
    """
    Validates a trained model by running a vectorized backtest on historical data.
    Uses 'Triple Barrier' physics (Stop Loss 3%, Take Profit 5%, Time Limit 5 days).
    
    Args:
        ticker: The stock symbol (e.g., 'NVDA').
        model_uri: GCS URI of the trained model (from ml_train_basket_model).
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
    """
    result = run_backtest_core(ticker, model_uri, start_date, end_date)
    return json.dumps(result, indent=2)

# --- 4. Running the Server ---
if __name__ == "__main__":
    import os
    
    # Cloud Run ALWAYS sets the 'PORT' environment variable.
    # Local runs typically do not.
    port = os.getenv("PORT")

    if port:
        # --- CLOUD RUN MODE (SSE / HTTP) ---
        logger.info(f"🚀 Starting QuantDataServer in SSE mode on port {port}...")
        
        # 'transport="sse"' tells FastMCP to start a Uvicorn web server
        # host="0.0.0.0" is required for Docker/Cloud containers
        mcp.run(transport="sse", host="0.0.0.0", port=int(port))
        
    else:
        # --- LOCAL MODE (Stdio) ---
        # This runs when you type 'python data_server.py' or use the inspector locally
        logger.info("🔌 Starting QuantDataServer in Stdio mode (Local)...")
        mcp.run()