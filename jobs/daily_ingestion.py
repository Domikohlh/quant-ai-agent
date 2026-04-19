import os
import sys
import logging
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from core.database import DatabaseManager
from core.ingestion_engine import DataIngestionEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DailyJob")

def get_or_create_universe(db: DatabaseManager) -> list:
    doc_ref = db.firestore_client.collection("config").document("trading_universe")
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        tickers = data.get("tickers", [])
        if tickers:
            return tickers
            
    default_universe = [
        "AAPL", "MSFT", "GOOGL", "META", "AMZN",
        "NVDA", "AMD", "TSM", "AVGO", "QCOM", "TXN", "MU", "ASML", "AMAT",
        "CRM", "ADBE", "ORCL", "NOW", "INTU", "SNOW", "PLTR",
        "CRWD", "PANW", "FTNT",
        "CSCO", "IBM", "DELL",
        "QQQ", "XLK", "SMH"
    ]
    doc_ref.set({"tickers": default_universe, "updated_by": "system_init"})
    return default_universe

def main():
    project_id = os.getenv("GCP_PROJECT_ID")
    region = os.getenv("GCP_COMPUTE_REGION", "us-central1")
    
    db = DatabaseManager(
        project_id=project_id, 
        region=region,
        sql_instance_name="dummy", 
        sql_db_name="dummy"
    )
    
    engine = DataIngestionEngine(db_manager=db)
    universe = get_or_create_universe(db)
    
    logger.info(f"🚀 Starting daily data ingestion for {len(universe)} tickers...")
    
    all_dataframes = []

    # 1. Collect all data locally in Python
    for ticker in universe:
        df = engine.update_ticker(ticker=ticker, period="5y", interval="1d")
        if df is not None and not df.empty:
            all_dataframes.append(df)
            
    # 2. Stitch together and Upload in one BATCH
    if all_dataframes:
        master_df = pd.concat(all_dataframes, ignore_index=True)
        engine.upload_batch(master_df)
    else:
        logger.info("No new data to upload across the universe.")
        
    logger.info("✅ Daily ingestion job complete.")

if __name__ == "__main__":
    main()