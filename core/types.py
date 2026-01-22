# core/types.py
from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any
from datetime import datetime

# --- 1. Market Data (For BigQuery) ---
class MarketDataRow(BaseModel):
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: Literal["YFINANCE", "IBKR", "ALPACA"]

# --- 2. Macro Data (For BigQuery) ---
class MacroDataRow(BaseModel):
    indicator: str  # e.g., "GDP", "CPI", "UNRATE"
    timestamp: datetime
    value: float
    source: Literal["FRED"]

# --- 3. Transaction Data (For Cloud SQL / Postgres) ---
class TradeTransaction(BaseModel):
    order_id: str
    agent_id: str          # Which agent triggered this?
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: float
    status: Literal["FILLED", "REJECTED", "PENDING"]
    timestamp: datetime
    fees: float = 0.0

# --- 4. Agent Decision Log (For Firestore) ---
class AgentThought(BaseModel):
    session_id: str
    agent_name: str        # e.g., "QuantAnalyst"
    task: str              # e.g., "Analyze AAPL"
    thought_process: str   # The internal reasoning
    tools_used: list[Dict[str, Any]] # [{"tool": "get_rsi", "result": 30}]
    final_decision: str    # "BUY_SIGNAL"
    timestamp: datetime = Field(default_factory=datetime.utcnow)