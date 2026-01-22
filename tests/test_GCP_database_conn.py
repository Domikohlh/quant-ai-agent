# scripts/seed_data.py
import os
from pathlib import Path
import yfinance as yf
from fredapi import Fred
import pandas as pd
from datetime import datetime
import uuid

# Import your custom modules
from core.database import DatabaseManager
from core.types import AgentThought, TradeTransaction

from dotenv import load_dotenv

# --- Load environment (explicit path + override so .env wins) ---
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path, override=True)

# --- Read required config from environment ---
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_REGION = os.getenv("GCP_REGION")
SQL_INSTANCE_NAME = os.getenv("SQL_INSTANCE_NAME")
SQL_DB_NAME = os.getenv("SQL_DB_NAME")

# Optional: print DB auth info to confirm which creds are loaded
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

# Fail fast if any required env var is missing so we don't get NameError later
required = {
    "GCP_PROJECT_ID": GCP_PROJECT_ID,
    "GCP_REGION": GCP_REGION,
    "SQL_INSTANCE_NAME": SQL_INSTANCE_NAME,
    "SQL_DB_NAME": SQL_DB_NAME,
    "DB_USER": DB_USER,
    "DB_PASS": DB_PASS,
}
missing = [key for key, value in required.items() if not value]
if missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(missing)}. Check .env loading.")

# Initialize DB Manager with the loaded env values
db = DatabaseManager(GCP_PROJECT_ID, GCP_REGION, SQL_INSTANCE_NAME, SQL_DB_NAME)

print("--- SEED CONFIG ---")
print("Correct Information Loaded")
print("-------------------")


def ingest_market_data():
    print("--- 1. Fetching Market Data (YFinance) ---")
    tickers = ["AAPL", "GOOGL", "MSFT"]
    # Download last 1 month
    df = yf.download(tickers, period="1mo", group_by='ticker', auto_adjust=True)
    
    # Flatten multi-index DataFrame for BigQuery
    rows = []
    for ticker in tickers:
        ticker_df = df[ticker].copy()
        ticker_df['ticker'] = ticker
        ticker_df['source'] = 'YFINANCE'
        ticker_df.reset_index(inplace=True)
        # Rename columns to match BigQuery Schema
        ticker_df.rename(columns={"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        rows.append(ticker_df)
    
    final_df = pd.concat(rows)
    # Upload to BigQuery
    db.save_market_data(final_df, table_id="market_data.daily_prices")

def simulate_agent_decision():
    print("--- 2. Simulating Agent Decision (Firestore) ---")
    thought = AgentThought(
        session_id="session_test_001",
        agent_name="Backtester",
        task="Evaluate AAPL Mean Reversion",
        thought_process="RSI is 25. This indicates oversold conditions. Checking volume...",
        tools_used=[{"tool": "calculate_rsi", "result": 25.4}],
        final_decision="BUY_SIGNAL"
    )
    # Convert Pydantic to Dict and Save
    db.log_agent_thought(thought.model_dump())

def simulate_trade():
    print("--- 3. Simulating Trade (Cloud SQL) ---")
    trade = TradeTransaction(
        order_id=str(uuid.uuid4()),
        agent_id="Trader_Bot_1",
        symbol="AAPL",
        side="BUY",
        quantity=10,
        price=150.25,
        status="FILLED",
        timestamp=datetime.utcnow()
    )
    db.save_transaction(trade.model_dump())

if __name__ == "__main__":
    # Ensure you have 'gcloud auth application-default login' ran before this!
    db.create_tables()
    ingest_market_data()
    simulate_agent_decision()
    simulate_trade()