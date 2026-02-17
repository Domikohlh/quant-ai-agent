# helper_func.py
import re
import pandas as pd
import numpy as np
from datetime import datetime, date
import logging
import os
import json
from pathlib import Path
import sys
from numba import njit

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("DataHelper")  # <--- 3. Define the logger object

_db = None

def _get_db() -> DatabaseManager:
    """
    Singleton pattern to get the DatabaseManager.
    This allows both the MCP Server and the Cloud Run Job (Worker) to connect.
    """
    global _db
    if _db is not None:
        return _db

    # Ensure required env vars exist
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1") # Default to us-central1 if missing

    if not project_id:
        raise ValueError("GCP_PROJECT_ID is missing from environment variables.")

    # Initialize the manager
    _db = DatabaseManager(
        project_id=project_id,
        region=region,
        sql_instance_name=os.getenv("SQL_INSTANCE_NAME", "dummy"),
        sql_db_name=os.getenv("SQL_DB_NAME", "dummy"),
    )
    return _db

def get_fred():
    global _fred
    if _fred is not None:
        return _fred
    _require_env("FRED_API_KEY")
    from fredapi import Fred  # local import: only required if macro tool is called

    _fred = Fred(api_key=os.getenv("FRED_API_KEY"))
    logger.info("Initialized FRED client")
    return _fred

def sanitize_ticker(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw.strip().upper())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        raise ValueError("ticker is empty/invalid after sanitization")
    return cleaned

def validate_stock_params(ticker: str, period: str, interval: str) -> None:
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")

    allowed_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    allowed_intervals = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if period not in allowed_periods:
        raise ValueError(f"period must be one of {sorted(allowed_periods)}")
    if interval not in allowed_intervals:
        raise ValueError(f"interval must be one of {sorted(allowed_intervals)}")

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

def get_volatility(close_prices: pd.Series, span: int = 20) -> pd.Series:
    """Compute dynamic volatility (standard deviation of returns) for Triple Barrier."""
    # Simple returns
    returns = close_prices.pct_change()
    # EWM standard deviation
    return returns.ewm(span=span).std()

