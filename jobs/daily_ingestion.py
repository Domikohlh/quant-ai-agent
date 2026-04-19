import os
import sys
import logging
from pathlib import Path

# Ensure we can import from core/
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager
from core.ingestion_engine import DataIngestionEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DailyJob")

def get_or_create_universe(db: DatabaseManager) -> list:
    """Reads the target universe from Firestore, or creates a default one."""
    doc_ref = db.firestore_client.collection("config").document("trading_universe")
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        tickers = data.get("tickers", [])
        if tickers:
            return tickers
            
    # Default fallback if config doesn't exist
    default_universe = ["AAPL", "MSFT", "GOOGL", "NVDA", "SPY", "QQQ"]
    doc_ref.set({"tickers": default_universe, "updated_by": "system_init"})
    logger.info("Created default trading universe in Firestore.")
    return default_universe

def main():
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1")
    
    if not project_id:
        raise ValueError("Missing GCP_PROJECT_ID environment variable.")

    # Initialize Database Manager
    db = DatabaseManager(
        project_id=project_id, 
        region=region,
        sql_instance_name="dummy", # Not using SQL for this
        sql_db_name="dummy"
    )
    
    # Initialize Engine
    engine = DataIngestionEngine(db_manager=db)

    # 1. Fetch Universe from Firestore Config
    universe = get_or_create_universe(db)
    logger.info(f"🚀 Starting daily data ingestion for {len(universe)} tickers: {universe}")
    
    # 2. Ingest Data
    for ticker in universe:
        # Note: Changed to 1d interval for standard historical panel backtesting. 
        # You can change this to 1h if you strictly want hourly data.
        engine.update_ticker(ticker=ticker, period="5y", interval="1d")
        
    logger.info("✅ Daily ingestion job complete.")

if __name__ == "__main__":
    main()