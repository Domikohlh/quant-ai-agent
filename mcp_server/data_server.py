import os
import re
import sys
import logging
from pathlib import Path
from typing import Optional
import json

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
def update_stock_data(ticker: str, period: str = "1mo", interval: str = "1h") -> str:
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
        _validate_stock_params(ticker=ticker, period=period, interval=interval)
        safe_ticker = _sanitize_ticker(ticker)
        
        # --- INTELLIGENT INCREMENTAL LOAD ---
        table_id = os.getenv("BQ_TECH_TABLE_ID", "market_data.processed_tech_indicators")
        db = _get_db()
        
        # 1. Check BigQuery state
        last_date, bq_date_col = db.get_latest_record_info(table_id, safe_ticker)
        
        # 2. Adjust download parameters based on existing data
        yf_start = None
        if last_date:
            logger.info(f"Found existing data for {safe_ticker} up to {last_date}. Switching to incremental load.")
            # Set start date to the last known date (YF will usually handle overlaps, 
            # but we can filter strictly later)
            yf_start = last_date
            # If we are doing incremental, we ignore 'period' and use 'start'
            # However, YF requires we don't mix period and start/end in some versions.
            # Safe bet: If we have a start date, use it.
            
        logger.info(f"Fetching stock data ticker={safe_ticker} start={yf_start} period={period}")

        # 3. Download Data
        if yf_start:
            # Fetch slightly more to ensure indicator calculation continuity (e.g. need previous rows for SMA)
            # But for pure data appending, we just want new rows.
            # *Critical Note*: Calculating indicators (RSI/MACD) requires historical context.
            # If you download ONLY new days, your RSI for the first new row will be NaN.
            # Intelligent Fix: We must download `start` = last_date - buffer (e.g. 60 days) 
            # then filter the RESULT to only keep rows > last_date before saving.
            
            from datetime import timedelta
            buffer_days = 60 # Enough for SMA 50, roughly enough for EMA convergence
            buffered_start = last_date - timedelta(days=buffer_days)
            df = yf.download(safe_ticker, start=buffered_start, interval=interval, auto_adjust=True, progress=False)
        else:
            df = yf.download(safe_ticker, period=period, interval=interval, auto_adjust=True, progress=False)

        if df.empty:
            return f"Error: No data found for {safe_ticker}."

        # Flatten columns if MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 4. Calculate Indicators (Requires the buffer data!)
        import pandas_ta as ta  # noqa: F401
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

        # 5. Dynamic Schema Alignment (The "Follow BigQuery" Fix)
        df.reset_index(inplace=True)
        
        # Identify the DF's time column
        df_time_col = None
        for col in ["Date", "Datetime", "index"]:
            if col in df.columns:
                df_time_col = col
                break
        
        if df_time_col:
            # RENAME the DF column to match BigQuery's column name (bq_date_col)
            # This prevents the "Schema does not match" error.
            df.rename(columns={df_time_col: bq_date_col}, inplace=True)
        
        # Standardize other columns
        df.columns = [
            c if c == bq_date_col else c.lower().replace(" ", "_").replace("-", "_").replace(".", "_").replace("%", "pct")
            for c in df.columns
        ]
        
        df["ticker"] = safe_ticker
        df["source"] = "YFINANCE"

        # 6. Filter Overlaps (Crucial for Incremental Load)
        if last_date:
            # Convert both to timezone-naive or aware for comparison to avoid errors
            # Assuming BQ returns timezone aware, make sure DF is compatible
            if pd.api.types.is_datetime64_any_dtype(df[bq_date_col]):
                 # Keep only strictly new data
                 df = df[df[bq_date_col] > last_date]
        
        df.dropna(inplace=True)

        # 7. Store
        final_df = None
        rows_added = 0

        if not df.empty:
            # Case A: We have new data. Save it, and use IT for the response.
            # No need to query BigQuery again.
            db.save_market_data(df, table_id=table_id)
            rows_added = len(df)
            logger.info(f"Appended {rows_added} new rows to BigQuery.")
            
            # Use the data we already have in memory!
            final_df = df.copy()
        
        else:
            # Case B: No new data. We MUST query BigQuery to get context.
            logger.info("No new data to append. Fetching context from DB.")
            
            query = f"""
                SELECT *
                FROM `{db.project_id}.{table_id}`
                WHERE ticker = @ticker
                ORDER BY {bq_date_col} DESC
                LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", safe_ticker)]
            )
            final_df = db.bq_client.query(query, job_config=job_config).to_dataframe()

        if final_df is None or final_df.empty:
             return json.dumps({"status": "error", "message": "Data processed but could not be retrieved."})

        # Sort for the Agent (Oldest -> Newest)
        # Ensure we use the correct date column name we discovered earlier
        if bq_date_col in final_df.columns:
            final_df.sort_values(by=bq_date_col, ascending=True, inplace=True)
            latest_date = str(final_df[bq_date_col].max())
        else:
            # Fallback if column missing in returned data
            latest_date = "Unknown"

        response_data = {
            "status": "success",
            "ticker": safe_ticker,
            "rows_added": rows_added,
            "latest_data_date": latest_date,
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

# --- 4. Running the Server ---
if __name__ == "__main__":
    # This starts the stdio server loop
    # IMPORTANT: MCP stdio transport requires stdout to be reserved for JSON-RPC.
    # Disable the CLI banner (rich ASCII) which breaks the protocol.
    mcp.run(show_banner=False)