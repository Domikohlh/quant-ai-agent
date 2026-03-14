import os
import re
import sys
import logging
from pathlib import Path
from typing import Optional
import json
import requests
from datetime import timedelta, datetime
import time
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

active_training_jobs = {}
active_feature_jobs = {}

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
            return json.dumps({"result": "✅ FOUND: Engineered training data exists. SKIP `update_stock_data` and SKIP `ml_feature_analysis`. Proceed directly to Phase 2 (Model Training)."})
        elif raw_exists and not train_exists:
            return json.dumps({"result": "⚠️ PARTIAL: Raw data exists, but training data is missing. SKIP `update_stock_data`, but you MUST run `ml_feature_analysis`."})
        else:
            return json.dumps({"result": "❌ NOT FOUND: No data exists. You MUST run `update_stock_data` first, then run `ml_feature_analysis`."})
    except Exception as e:
        return json.dumps({"result": f"Error checking database: {str(e)}"})

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
            return json.dumps({"result": f"Error: No data found for {safe_ticker}."})

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
             return json.dumps({"status": "error", "message": f"Insufficient data length. SMA_200 requires 200+ rows."})

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
             return json.dumps({"result": "❌ Error: Data processed but could not be retrieved."})

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
            "instruction": "DATA SAVED. DO NOT CALL THIS TOOL AGAIN. Proceed immediately to ml_feature_analysis."
        }

        return json.dumps(response_data)

    except Exception as e:
        logger.error(f"Error updating stock data: {e}")
        return json.dumps({"result": f"❌ Error: {str(e)}"})

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
            return json.dumps({"result": f"❌ Error: No FRED data found for {series_id}."})
            
        df.reset_index(inplace=True)
        df.rename(columns={"index": "timestamp"}, inplace=True)
        
        # 2. Enrich
        df["indicator"] = series_id
        df["source"] = "FRED"
        
        # 3. Store
        table_id = os.getenv("BQ_MACRO_TABLE_ID", "market_data.macro_indicators")
        _get_db().save_market_data(df, table_id=table_id)
        
        latest_val = df.iloc[-1]['value']
        latest_date = df.iloc[-1]['timestamp'].strftime('%Y-%m-%d')
        
        return json.dumps({"result": f"✅ Updated {series_id}. Latest value: {latest_val} ({latest_date}). Stored in BigQuery table: {table_id}"})
        
    except Exception as e:
        return json.dumps({"result": f"❌ Error fetching FRED data: {e}"})

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
        return json.dumps({"result": "Error: BRAVE_API_KEY not found in environment variables."})

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
            return json.dumps({"result": "Error: Brave API rate limit exceeded."})
        if response.status_code != 200:
            return json.dumps({"result": f"Error: Brave API returned status {response.status_code}"})

        data = response.json()
        
        # 3. Format Results for the LLM
        # We only want the high-value bits: Title, Link, Description, and Age (if available)
        web_results = data.get("web", {}).get("results", [])
        
        if not web_results:
            return json.dumps({"result": f"No results found for '{query}' on trusted financial sites."})

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

        return json.dumps({"result": "\n\n".join(formatted_results)})

    except Exception as e:
        logger.error(f"Error executing Brave search: {e}")
        return json.dumps({"result": f"Error executing search: {str(e)}"})

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
        
        # --- 1. Check Firestore for the Latest Training Receipt ---
        doc_ref = db.firestore_client.collection("training_jobs").document(f"{ticker}_latest")
        doc = doc_ref.get()
        
        if doc.exists:
            receipt = doc.to_dict()
            receipt_time = datetime.fromisoformat(receipt["timestamp"])
            now = datetime.now(receipt_time.tzinfo)
            age_in_minutes = (now - receipt_time).total_seconds() / 60
            
            # If the receipt is fresh (< 15 mins old) and it was REJECTED
            if age_in_minutes < 15 and receipt.get("status") == "rejected":
                # Clear the document so we don't accidentally read it on the next loop
                doc_ref.delete() 
                
                return json.dumps({"result": (
                    f"❌ QA THRESHOLD FAILED: The recent training job completed, but accuracy was <= 50%. "
                    f"The model was NOT saved to GCS.\n\n"
                    f"--- FAILED METRICS ---\n{json.dumps(receipt, indent=2)}\n\n"
                    f"INSTRUCTION: DO NOT proceed to the Backtest Agent. You must adjust your hyperparameters "
                    f"(e.g., change n_estimators, learning_rate, or max_depth) and call `ml_train_basket_model` again."
                )})

        # --- 2. Check GCS for Success ---
        project_id = os.getenv("GCP_PROJECT_ID")
        bucket_name = os.getenv("GCS_MODEL_BUCKET", f"{project_id}-models")
        bucket = db.storage_client.bucket(bucket_name)
        
        blobs = list(bucket.list_blobs(prefix="models/"))
        matching_blobs = [b for b in blobs if ticker in b.name and b.name.endswith(".joblib")]
        
        if not matching_blobs:
            return json.dumps({"result": f"⏳ STILL TRAINING: No models found for {ticker} yet. Wait 60 seconds and try again."})

        # Sort by time (Newest First)
        matching_blobs.sort(key=lambda x: x.time_created, reverse=True)
        latest_blob = matching_blobs[0]
        
        now_utc = datetime.now(latest_blob.time_created.tzinfo)
        blob_age_minutes = (now_utc - latest_blob.time_created).total_seconds() / 60
        
        if blob_age_minutes > 15:
            return json.dumps({"result": f"⏳ STILL TRAINING: The newest model found is {int(blob_age_minutes)} minutes old. Wait 60 seconds."})

        latest_blob.reload() 
        metrics_text = json.dumps(latest_blob.metadata, indent=2) if latest_blob.metadata else "No metrics found."
        uri = f"gs://{bucket_name}/{latest_blob.name}"
        
        return json.dumps({"result": (
            f"✅ FOUND LATEST MODEL: {uri}\n\n"
            f"--- TRUE ML METRICS ---\n{metrics_text}\n\n"
            f"INSTRUCTION: Model passed QA and retrieval was successful. Proceed immediately to Backtest Agent."
        )})
            
    except Exception as e:
        return json.dumps({"result": f"❌ Error: {str(e)}"})

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
    global active_feature_jobs 
    current_time = time.time()
    job_key = f'{ticker}_feature'

    # 1. EMERGENCY IDEMPOTENCY LOCK
    if job_key in active_feature_jobs:
        time_elapsed = current_time - active_feature_jobs[job_key]
        if time_elapsed < 600:
            return json.dumps({"result": f"⚠️ REJECTED: Feature Analysis for {ticker} is currently running. DO NOT call this tool again. Stop and notify the user to wait."})
            
    active_feature_jobs[job_key] = current_time

    if not run_remote:
        try:
            # Pass the new date parameter to the core function
            result = run_feature_analysis_core(
                ticker, basket, barrier_width, time_horizon, 
                correlation_threshold, top_n, training_end_date
            )
            safe_result = {k: v for k, v in result.items() if k not in ['raw_data', 'dataframe']}
            return json.dumps({"result": f"✅ Local analysis complete: {safe_result}"})

        except Exception as e:
            return json.dumps({"result": f"❌ Error: {str(e)}"})

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
        return json.dumps({"result": f"🚀 SUCCESS: Feature Analysis Job triggered for {ticker}. STOP using tools and tell the user to wait 5 minutes."})

    except Exception as e:
        if job_key in active_feature_jobs:
            del active_feature_jobs[job_key]
        return json.dumps({"result": f"❌ Error triggering Cloud Job: {e}"})

@mcp.tool()
def ml_train_basket_model(
    target_ticker: str,
    run_remote: bool = True, 
    training_end_date: str = "2024-12-31",
    custom_params: dict = None
) -> str: 
    """
    [STEP 2 of Pipeline]
    Trains an XGBoost classifier using the datasets created by 'ml_feature_analysis'.
    
    QA GATE & AUTO-TUNING LOGIC:
    - The model MUST achieve >50% test accuracy to pass the QA Gate.
    - If it fails, it will be rejected and will NOT be saved to GCS.
    - If your previous attempt was rejected, you MUST use the `custom_params` dictionary 
      to provide new hyperparameters and retry. 
    - Valid keys for custom_params: 'n_estimators' (int), 'learning_rate' (float), 'max_depth' (int).
    
    Args:
        target_ticker: The stock ticker to train the model for.
        run_remote: Always set to True to run on Cloud Run Jobs.
        training_end_date: The chronological split date.
        custom_params: A dictionary of XGBoost hyperparameters to override the defaults. 
    """
    global active_training_jobs
    current_time = time.time()

    # 1. EMERGENCY IDEMPOTENCY LOCK
    if target_ticker in active_training_jobs:
        time_elapsed = current_time - active_training_jobs[target_ticker]
        if time_elapsed < 600: # 10 minute cooldown
            return json.dumps({
                "result": f"⚠️ REJECTED: A training job for {target_ticker} was already started {int(time_elapsed)} seconds ago and is currently running. DO NOT call this tool again. Stop and notify the orchestrator."
            })
            
    # Lock the ticker
    active_training_jobs[target_ticker] = current_time

    # 2. Setup GCP Variables
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1")
    bucket_name = os.getenv("GCS_MODEL_BUCKET", f"{project_id}-models")
    job_name = "quant-training-job"

    # 3. Local Execution (Bypasses Cloud Run)
    if not run_remote:
        try:
            result = train_basket_model_core(target_ticker, bucket_name, training_end_date)
            # Ensure it returns a flat dict
            return json.dumps({"result": f"✅ Local training complete. Details: {json.dumps(result)}"})
        except Exception as e:
            return json.dumps({"result": f"❌ Error during local training: {str(e)}"})

    # 4. Remote Execution (Cloud Run)
    try:
        endpoint = f"{region}-run.googleapis.com"
        client = run_v2.JobsClient(
            client_options=client_options.ClientOptions(api_endpoint=endpoint)
        )
        
        args = [
            "python", "mcp_server/training_logic.py", 
            "--task", "train",
            "--ticker", target_ticker, 
            "--bucket", bucket_name,
            "--training_end_date", training_end_date
        ]
        
        if custom_params:
            args.extend(["--custom_params", json.dumps(custom_params)])

        request = run_v2.RunJobRequest(
            name=f"projects/{project_id}/locations/{region}/jobs/{job_name}",
            overrides={
                "container_overrides": [{
                    "args": args
                }]
            }
        )
        operation = client.run_job(request=request)
        
        param_msg = f" using params: {custom_params}" if custom_params else " using default params."
        
        # Return string-wrapped json payload
        return json.dumps({
            "result": f"✅ SUCCESS: Training Job triggered for {target_ticker}{param_msg} Saving to {bucket_name}. STOP using tools and tell the user to wait 5 minutes."
        })

    except Exception as e:
        # Clear the lock if the API call actually failed so the agent can retry later
        if target_ticker in active_training_jobs:
            del active_training_jobs[target_ticker]
            
        return json.dumps({"result": f"❌ Error triggering Cloud Run Job: {str(e)}"})


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
    try:
        result = run_backtest_core(ticker, model_uri, start_date, end_date)
        
        # 1. TOKEN PROTECTION: Strip out massive arrays (time series, trade logs)
        safe_result = {}
        if isinstance(result, dict):
            # Only keep top-level stats, drop big lists
            safe_result = {k: v for k, v in result.items() if not isinstance(v, (list, pd.Series, np.ndarray))}
        else:
            safe_result = {"summary": str(result)[:500]} # Fallback truncation

        return json.dumps({"result": safe_result})
        
    except Exception as e:
        return json.dumps({"result": f"❌ Error during backtest: {str(e)}"})

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